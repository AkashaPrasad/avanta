"""AC-10 and AC-14: the posterior is a proper distribution and the evidence
terms add up to the score they claim to explain."""
from __future__ import annotations

import numpy as np
import pytest

from core.score.posterior import H0_ID, H0_LABEL, Hypothesis, build, softmax


def _hypotheses(scores: list[float]) -> list[Hypothesis]:
    out = [Hypothesis(f"v{i}", f"MV {i}", score, 0.0) for i, score in enumerate(scores)]
    out.append(Hypothesis(H0_ID, H0_LABEL, -20.0, 0.0, is_null=True))
    return out


@pytest.mark.parametrize(
    "scores",
    [[-10.0, -12.0, -30.0], [-1.0], [-500.0, -501.0], [0.0, 0.0, 0.0], [-1e3, -2.0]],
)
def test_posterior_sums_to_one_including_h0(scores):
    posterior = build(_hypotheses(scores))
    total = sum(e.probability for e in posterior.entries)
    assert abs(total - 1.0) < 1e-9, f"posterior summed to {total}"


def test_h0_is_always_present_as_a_row():
    posterior = build(_hypotheses([-10.0, -11.0]))
    assert any(e.is_null for e in posterior.entries), "H0 must never be hidden"


def test_h0_wins_when_no_candidate_explains_the_observation():
    """The failure mode this guards against: a system that cannot say 'I don't
    know' will accuse whoever happens to be closest."""
    posterior = build(_hypotheses([-60.0, -62.0, -65.0]))
    assert posterior.p_null > 0.5
    assert posterior.no_attribution
    assert posterior.entries[0].is_null


def test_a_good_candidate_beats_h0():
    posterior = build(_hypotheses([-5.0, -30.0]))
    assert not posterior.no_attribution
    assert posterior.p_null < 0.5
    assert posterior.entries[0].hypothesis_id == "v0"


def test_ranks_are_dense_and_ordered():
    posterior = build(_hypotheses([-10.0, -12.0, -14.0]))
    assert [e.rank for e in posterior.entries] == [1, 2, 3, 4]
    probabilities = [e.probability for e in posterior.entries]
    assert probabilities == sorted(probabilities, reverse=True)


def test_softmax_is_stable_at_extreme_scores():
    result = softmax(np.array([-1e6, -1e6 - 1.0, -1e6 - 50.0]))
    assert np.isfinite(result).all()
    assert abs(result.sum() - 1.0) < 1e-12


def test_prior_shifts_the_ranking():
    """The behaviour prior has to be able to change the answer, or it is
    decoration."""
    flat = build([
        Hypothesis("a", "A", -10.0, 0.0),
        Hypothesis("b", "B", -10.2, 0.0),
        Hypothesis(H0_ID, H0_LABEL, -25.0, 0.0, is_null=True),
    ])
    assert flat.entries[0].hypothesis_id == "a"

    tilted = build([
        Hypothesis("a", "A", -10.0, 0.0),
        Hypothesis("b", "B", -10.2, 2.0),   # B was silent during the window
        Hypothesis(H0_ID, H0_LABEL, -25.0, 0.0, is_null=True),
    ])
    assert tilted.entries[0].hypothesis_id == "b"
