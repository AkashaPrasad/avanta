"""The attribution pipeline: candidates in, calibrated posterior out.

For each surviving candidate:
  1. Enumerate release hypotheses theta over the configured grid.
  2. Run a forward ensemble for each theta, perturbing the forcing.
  3. Marginalise the likelihood over ensemble members and profile over theta.
  4. Add the behaviour prior.
Then softmax over all candidates plus H0.

Step 3 is where the honesty about uncertainty lives. Marginalising over the
ensemble rather than picking the best member asks "does this vessel explain the
observation under forcing we cannot pin down", not "does it explain it under one
lucky realisation". A candidate whose simulated slick only lands on the observed
one for a single wind perturbation is penalised, which is correct, and it is why
the posterior necessarily widens as a slick ages and ensemble members diverge.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from core.ais.tracks import Track
from core.config import settings
from core.score import prior as prior_module
from core.score.compare import ComparisonGrid, difference_map, score_null, score_simulation
from core.score.likelihood import LikelihoodTerms
from core.score.posterior import H0_ID, H0_LABEL, Hypothesis, Posterior, build
from core.simulate.ensemble import perturbations, summarise
from core.simulate.line_source import ReleaseParams, theta_grid
from core.simulate.openoil_runner import SimulationResult, run_forward

log = logging.getLogger(__name__)


def logsumexp(values: np.ndarray) -> float:
    peak = float(np.max(values))
    return peak + float(np.log(np.sum(np.exp(values - peak))))


@dataclass
class CandidateEvidence:
    mmsi: str
    name: str | None
    ship_type: str
    is_dark: bool
    best_params: ReleaseParams
    marginal_log_likelihood: float
    per_member_log_likelihood: list[float]
    likelihood_terms: LikelihoodTerms
    prior: prior_module.PriorResult
    best_simulation: SimulationResult
    difference: dict[str, Any]
    theta_profile: list[dict[str, Any]] = field(default_factory=list)
    runtime_s: float = 0.0

    @property
    def score(self) -> float:
        return self.marginal_log_likelihood + self.prior.log_prior

    def evidence_breakdown(self) -> dict[str, Any]:
        """Every term that produced the score, signed, summing to the score.

        This is checked by AC-14: if these numbers do not add up to the reported
        log-score, the panel is decorative rather than an audit trail.
        """
        likelihood_terms = [
            {
                "group": "likelihood",
                "name": "coverage",
                "value": round(self.likelihood_terms.coverage_term, 6),
                "explanation": "Log density of simulated oil under the pixels where oil was observed.",
            },
            {
                "group": "likelihood",
                "name": "false_area_penalty",
                "value": round(self.likelihood_terms.false_area_term, 6),
                "explanation": "Penalty for simulated oil landing where none was observed.",
            },
            {
                "group": "likelihood",
                "name": "ensemble_marginalisation",
                "value": round(
                    self.marginal_log_likelihood
                    - self.likelihood_terms.coverage_term
                    - self.likelihood_terms.false_area_term,
                    6,
                ),
                "explanation": (
                    f"Adjustment from marginalising over {len(self.per_member_log_likelihood)} "
                    "ensemble members with perturbed wind and current forcing, rather than "
                    "scoring the single best member."
                ),
            },
        ]
        prior_terms = [
            {"group": "prior", "name": f.name, "value": round(f.contribution, 6), "explanation": f.explanation}
            for f in self.prior.features
        ]
        terms = likelihood_terms + prior_terms
        # Every figure here is rounded to the same precision. The panel's whole
        # claim is that these terms add up to the score, so the numbers actually
        # shown have to add up -- rounding the parts and the total differently
        # makes the panel visibly wrong by a few units in the last place.
        return {
            "terms": terms,
            "sum": round(sum(t["value"] for t in terms), 6),
            "score": round(self.score, 6),
            "log_likelihood": round(self.marginal_log_likelihood, 6),
            "log_prior": round(self.prior.log_prior, 6),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mmsi": self.mmsi,
            "name": self.name,
            "ship_type": self.ship_type,
            "is_dark": self.is_dark,
            "release": self.best_params.to_dict(),
            "log_likelihood": round(self.marginal_log_likelihood, 4),
            "log_prior": round(self.prior.log_prior, 4),
            "score": round(self.score, 4),
            "likelihood_terms": self.likelihood_terms.to_dict(),
            "prior": self.prior.to_dict(),
            "difference": self.difference,
            "seed": self.best_simulation.seed.to_summary(),
            "theta_profile": self.theta_profile,
            "ensemble_members": len(self.per_member_log_likelihood),
            "runtime_s": round(self.runtime_s, 2),
        }


@dataclass
class AttributionRun:
    grid: ComparisonGrid
    candidates: list[CandidateEvidence]
    posterior: Posterior
    null_terms: LikelihoodTerms
    acquisition: datetime
    ensemble_spread: dict[str, Any]
    runtime_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition_utc": self.acquisition.isoformat(),
            "posterior": self.posterior.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "null": {
                "hypothesis_id": H0_ID,
                "label": H0_LABEL,
                "log_likelihood": round(self.null_terms.log_likelihood, 4),
                "log_prior": round(prior_module.null_log_prior(), 4),
                "explanation": (
                    "Oil released uniformly at random inside the feasibility cone: a source "
                    "that is somewhere in the search window but is none of the candidates "
                    "observed. Every named vessel has to beat this to be worth accusing."
                ),
            },
            "ensemble_spread": self.ensemble_spread,
            "grid": {
                "shape": list(self.grid.shape),
                "downsample_factor": self.grid.factor,
                "slick_cells": self.grid.n_slick_cells,
            },
            "runtime_s": round(self.runtime_s, 2),
        }


def _mass_weights(sim: SimulationResult, index: int) -> np.ndarray | None:
    mass = sim.mass_oil[:, index]
    ok = np.isfinite(sim.lon[:, index]) & np.isfinite(sim.lat[:, index]) & (mass > 0)
    return mass[ok] if ok.any() else None


def score_candidate(
    track: Track,
    grid: ComparisonGrid,
    acquisition: datetime,
    currents_path: Path,
    wind_path: Path,
    *,
    n_ensemble: int | None = None,
    n_per_point: int | None = None,
    oil_type: str = "GENERIC INTERMEDIATE FUEL OIL 180",
    prior_kwargs: dict[str, Any] | None = None,
    progress: Callable[[str, float], None] | None = None,
) -> CandidateEvidence | None:
    import time as _time

    started = _time.time()
    cfg = settings()["simulate"]
    n_members = n_ensemble if n_ensemble is not None else int(cfg["n_ensemble"])
    thetas = theta_grid(track, acquisition, cfg["theta_grid"], oil_type)
    if not thetas:
        log.info("no feasible release window for %s", track.mmsi)
        return None

    rng = np.random.default_rng(abs(hash(track.mmsi)) % (2**32))
    members = perturbations(n_members, rng)

    best: dict[str, Any] | None = None
    profile: list[dict[str, Any]] = []
    failures: list[str] = []

    for theta_index, params in enumerate(thetas):
        member_ll: list[float] = []
        member_terms: LikelihoodTerms | None = None
        best_sim: SimulationResult | None = None
        for member_index, perturbation in enumerate(members):
            try:
                sim = run_forward(
                    track,
                    params,
                    acquisition,
                    currents_path,
                    wind_path,
                    n_per_point=n_per_point,
                    wind_drift_factor=perturbation["wind_drift_factor"],
                    horizontal_diffusivity=perturbation["horizontal_diffusivity"],
                    current_scale=perturbation["current_scale"],
                    wind_scale=perturbation["wind_scale"],
                    wind_rotate_deg=perturbation["wind_rotate_deg"],
                    seed_rng=theta_index * 100 + member_index,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("simulation failed for %s theta=%d member=%d: %s",
                            track.mmsi, theta_index, member_index, exc)
                failures.append(f"theta={theta_index} member={member_index}: {exc}")
                continue
            last = len(sim.times) - 1
            lon, lat, mass = sim.surface_at(last)
            if lon.size == 0:
                continue
            terms, _ = score_simulation(grid, lon, lat, mass)
            member_ll.append(terms.log_likelihood)
            if member_index == 0:
                member_terms, best_sim = terms, sim
            if progress is not None:
                done = theta_index * len(members) + member_index + 1
                progress(f"{track.mmsi}: θ {theta_index + 1}/{len(thetas)}", done / (len(thetas) * len(members)))

        if not member_ll or member_terms is None or best_sim is None:
            continue
        marginal = logsumexp(np.array(member_ll)) - float(np.log(len(member_ll)))
        profile.append(
            {
                **params.to_dict(),
                "marginal_log_likelihood": round(marginal, 4),
                "ensemble_spread": summarise(member_ll),
            }
        )
        if best is None or marginal > best["marginal"]:
            best = {
                "marginal": marginal,
                "params": params,
                "member_ll": member_ll,
                "terms": member_terms,
                "sim": best_sim,
            }

    if best is None:
        # Every member of every hypothesis failed. That is a broken pipeline, not
        # a vessel that happens not to fit, and silently returning None would
        # hide it as "this candidate produced no evidence".
        if failures:
            raise RuntimeError(
                f"every simulation failed for {track.mmsi} "
                f"({len(failures)} attempts). First failure: {failures[0]}"
            )
        return None

    window_start = best["params"].t_start
    window_end = best["params"].t_end
    prior_result = prior_module.evaluate(
        track,
        window_start.replace(tzinfo=track.t_start.tzinfo),
        window_end.replace(tzinfo=track.t_start.tzinfo),
        **(prior_kwargs or {}),
    )
    sim: SimulationResult = best["sim"]
    lon, lat, mass = sim.surface_at(len(sim.times) - 1)
    _, density = score_simulation(grid, lon, lat, mass)

    return CandidateEvidence(
        mmsi=track.mmsi,
        name=track.name,
        ship_type=track.ship_type,
        is_dark=track.is_dark,
        best_params=best["params"],
        marginal_log_likelihood=best["marginal"],
        per_member_log_likelihood=best["member_ll"],
        likelihood_terms=best["terms"],
        prior=prior_result,
        best_simulation=sim,
        difference=difference_map(grid, density),
        theta_profile=sorted(profile, key=lambda p: -p["marginal_log_likelihood"])[:12],
        runtime_s=_time.time() - started,
    )


def run_attribution(
    tracks: list[Track],
    grid: ComparisonGrid,
    acquisition: datetime,
    currents_path: Path,
    wind_path: Path,
    *,
    n_ensemble: int | None = None,
    n_per_point: int | None = None,
    oil_type: str = "GENERIC INTERMEDIATE FUEL OIL 180",
    prior_kwargs: dict[str, dict[str, Any]] | None = None,
    progress: Callable[[str, float], None] | None = None,
) -> AttributionRun:
    import time as _time

    started = _time.time()
    evidence: list[CandidateEvidence] = []
    for index, track in enumerate(tracks):
        if progress is not None:
            progress(f"simulating candidate {index + 1} of {len(tracks)}", index / max(len(tracks), 1))
        result = score_candidate(
            track,
            grid,
            acquisition,
            currents_path,
            wind_path,
            n_ensemble=n_ensemble,
            n_per_point=n_per_point,
            oil_type=oil_type,
            prior_kwargs=(prior_kwargs or {}).get(track.mmsi),
            progress=None,
        )
        if result is not None:
            evidence.append(result)

    null_terms = score_null(grid)
    hypotheses = [
        Hypothesis(
            hypothesis_id=c.mmsi,
            label=c.name or f"MMSI {c.mmsi}",
            log_likelihood=c.marginal_log_likelihood,
            log_prior=c.prior.log_prior,
            detail={"is_dark": c.is_dark, "ship_type": c.ship_type},
        )
        for c in evidence
    ]
    hypotheses.append(
        Hypothesis(H0_ID, H0_LABEL, null_terms.log_likelihood, prior_module.null_log_prior(), is_null=True)
    )
    posterior = build(hypotheses)

    spread = {
        c.mmsi: summarise(c.per_member_log_likelihood) for c in evidence
    }
    return AttributionRun(
        grid=grid,
        candidates=evidence,
        posterior=posterior,
        null_terms=null_terms,
        acquisition=acquisition,
        ensemble_spread=spread,
        runtime_s=_time.time() - started,
    )
