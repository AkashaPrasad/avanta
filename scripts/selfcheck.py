"""Invariants, performance budgets, and matrix reconciliation.

Three jobs:
  * assert the properties that must hold for any result to mean anything;
  * measure the operations that have a published budget and fail if exceeded;
  * cross-reference CAPABILITY_MATRIX.md against the test suite, so a row cannot
    claim REAL without a test that proves it.

The last one is the mechanism that makes honesty structural rather than
aspirational.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import settings  # noqa: E402


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    seconds: float | None = None
    budget: float | None = None


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)
        mark = "PASS" if check.ok else "FAIL"
        timing = ""
        if check.seconds is not None:
            timing = f"  {check.seconds:7.2f}s"
            if check.budget is not None:
                timing += f" / {check.budget:.1f}s budget"
        print(f"  [{mark}] {check.name}{timing}")
        if not check.ok:
            print(f"         {check.detail}")

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


def timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - start


def check_invariants(report: Report) -> None:
    print("\nInvariants")
    from core.score.posterior import H0_ID, H0_LABEL, Hypothesis, build

    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(200):
        scores = rng.normal(-20, 30, size=int(rng.integers(1, 9))).tolist()
        hypotheses = [Hypothesis(f"v{i}", f"MV {i}", s, 0.0) for i, s in enumerate(scores)]
        hypotheses.append(Hypothesis(H0_ID, H0_LABEL, float(rng.normal(-25, 10)), 0.0, is_null=True))
        total = sum(e.probability for e in build(hypotheses).entries)
        worst = max(worst, abs(total - 1.0))
    report.add(Check(
        "posterior sums to 1.0 including H0 (200 random draws)",
        worst < 1e-6, f"worst deviation {worst:.2e}",
    ))

    posterior = build([
        Hypothesis("a", "A", -80.0, 0.0),
        Hypothesis("b", "B", -82.0, 0.0),
        Hypothesis(H0_ID, H0_LABEL, -20.0, 0.0, is_null=True),
    ])
    report.add(Check(
        "H0 wins and no_attribution is set when nothing fits",
        posterior.no_attribution and posterior.p_null > 0.5,
        f"p_null={posterior.p_null:.4f} no_attribution={posterior.no_attribution}",
    ))

    from datetime import datetime, timedelta

    from core.simulate.openoil_runner import BackwardIntegrationError, assert_forward_only

    now = datetime(2025, 5, 26)
    try:
        assert_forward_only([now], now - timedelta(hours=1), 600)
        rejected = False
    except BackwardIntegrationError:
        rejected = True
    report.add(Check("backward integration is refused at runtime", rejected, "guard did not fire"))


def check_static_forward_only(report: Report) -> None:
    print("\nStatic analysis")
    patterns = [
        re.compile(r"time_step\s*=\s*-"),
        re.compile(r"\btimes?\[::-1\]"),
        re.compile(r"reversed\(\s*(?:self\.)?times?\s*\)"),
    ]
    offenders: list[str] = []
    for path in (ROOT / "core" / "simulate").rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            if any(p.search(code) for p in patterns):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    report.add(Check(
        "no backward time integration in core/simulate",
        not offenders, "; ".join(offenders),
    ))


def check_performance(report: Report) -> None:
    print("\nPerformance budgets")
    budgets = settings()["performance_budgets_s"]

    scenes = sorted((ROOT / "fixtures" / "scenes").glob("*.tif"))
    if scenes:
        from core.sar.preprocess import read_scene
        from core.sar.segment_classical import segment

        raster, load_s = timed(lambda: read_scene(str(scenes[0])))
        detection, seg_s = timed(lambda: segment(raster))
        report.add(Check(
            "segmentation (classical)", seg_s <= budgets["segmentation"],
            f"{len(detection.regions)} regions", seg_s, budgets["segmentation"],
        ))
        report.add(Check(
            "scene read (cached raster)", load_s <= budgets["scene_ingest_cached"],
            f"{raster.shape}", load_s, budgets["scene_ingest_cached"],
        ))
    else:
        report.add(Check("segmentation", False, "no fixture scene available to time"))

    ais = sorted((ROOT / "fixtures" / "ais").glob("*.json"))
    if ais:
        from core.hypothesis.prefilter import SlickGeometry, prefilter
        from core.pipeline import load_ais_fixture

        tracks, _ = load_ais_fixture(ais[0])
        if tracks:
            geometry = SlickGeometry(
                centroid_lon=float(np.mean([f.lon for f in tracks[0].fixes])),
                centroid_lat=float(np.mean([f.lat for f in tracks[0].fixes])),
                major_axis_deg=45.0, major_axis_km=12.0, area_km2=8.0,
                acquired_utc=max(t.t_end for t in tracks),
            )
            subset = tracks[:200]
            results, prefilter_s = timed(lambda: prefilter(subset, geometry))
            report.add(Check(
                f"candidate prefilter ({len(subset)} vessels)",
                prefilter_s <= budgets["prefilter"],
                f"{sum(1 for r in results if r.kept)} kept",
                prefilter_s, budgets["prefilter"],
            ))
    else:
        report.add(Check("candidate prefilter", False, "no AIS fixture available to time"))


def check_matrix(report: Report) -> None:
    """AC-25. Every REAL row must name a test that actually exists and passes."""
    print("\nCapability matrix reconciliation")
    matrix = ROOT / "CAPABILITY_MATRIX.md"
    if not matrix.exists():
        report.add(Check("CAPABILITY_MATRIX.md exists", False, "file not found"))
        return

    rows: list[tuple[str, str, str]] = []
    for line in matrix.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Status |" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 3 and cells[1] in {"REAL", "PARTIAL", "STUBBED", "PLANNED"}:
            rows.append((cells[0], cells[1], cells[2]))

    collected = subprocess.run(
        # `-o addopts=` clears pytest.ini's own -q, which otherwise collapses
        # collection to per-file counts instead of listing node ids.
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "tests"],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout
    # Both the test-function names and the file stems count as evidence: a row
    # may cite a whole spec file or one specific assertion.
    known = set(re.findall(r"::([\w_]+)", collected))
    known.update(re.findall(r"([\w_]+)\.py::", collected))
    for spec in (ROOT / "web" / "tests" / "e2e").glob("*.spec.ts"):
        known.update(re.findall(r"test\(\s*['\"]([^'\"]+)", spec.read_text(encoding="utf-8")))
        known.add(spec.stem)

    unbacked: list[str] = []
    for claim, status, evidence in rows:
        if status != "REAL":
            continue
        names = re.findall(r"`([^`]+)`", evidence)
        if not names:
            unbacked.append(f"{claim!r}: REAL with no named evidence")
            continue
        if not any(
            n.replace(".py", "").replace(".ts", "") in known
            or any(n.replace(".py", "").replace(".ts", "") in k for k in known)
            for n in names
        ):
            unbacked.append(f"{claim!r}: names {names} but no such test was collected")

    report.add(Check(
        f"every REAL row is backed by a collected test ({len(rows)} rows)",
        not unbacked, "\n         ".join(unbacked),
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", action="store_true", help="only reconcile the capability matrix")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    report = Report()
    print("AVANTA selfcheck")
    if args.matrix:
        check_matrix(report)
    else:
        check_invariants(report)
        check_static_forward_only(report)
        check_performance(report)
        check_matrix(report)

    print("\nTiming summary")
    for check in report.checks:
        if check.seconds is not None:
            budget = f"{check.budget:.1f}s" if check.budget else "—"
            print(f"  {check.name:44s} {check.seconds:7.2f}s   budget {budget}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"name": c.name, "ok": c.ok, "detail": c.detail,
             "seconds": c.seconds, "budget": c.budget}
            for c in report.checks
        ]
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    failed = report.failed
    print(f"\n{len(report.checks) - len(failed)}/{len(report.checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
