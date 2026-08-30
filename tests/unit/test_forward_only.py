"""AC-9: no backward time integration, anywhere."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.simulate.openoil_runner import BackwardIntegrationError, assert_forward_only

SIMULATE_DIR = Path(__file__).resolve().parent.parent.parent / "core" / "simulate"


def test_negative_time_step_is_refused():
    now = datetime(2025, 5, 26, 0, 0)
    with pytest.raises(BackwardIntegrationError, match="never integrates backwards"):
        assert_forward_only([now], now + timedelta(hours=1), -600)


def test_end_time_before_the_last_seed_is_refused():
    now = datetime(2025, 5, 26, 0, 0)
    with pytest.raises(BackwardIntegrationError, match="never integrates backwards"):
        assert_forward_only([now], now - timedelta(hours=1), 600)


def test_empty_seed_is_refused():
    with pytest.raises(BackwardIntegrationError):
        assert_forward_only([], datetime(2025, 5, 26), 600)


def test_a_forward_run_is_accepted():
    now = datetime(2025, 5, 26, 0, 0)
    assert_forward_only([now, now + timedelta(minutes=30)], now + timedelta(hours=6), 600)


def test_no_negative_time_step_literal_in_the_simulation_package():
    """Static check: nothing in core/simulate may pass a negative time step or
    reverse a time array."""
    offenders: list[str] = []
    patterns = [
        re.compile(r"time_step\s*=\s*-"),
        re.compile(r"time_step_output\s*=\s*-"),
        re.compile(r"\btimes\[::-1\]"),
        re.compile(r"\btime\[::-1\]"),
        re.compile(r"reversed\(\s*(?:self\.)?times?\s*\)"),
    ]
    for path in SIMULATE_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.split("#", 1)[0]
            for pattern in patterns:
                if pattern.search(stripped):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], "backward integration found:\n" + "\n".join(offenders)
