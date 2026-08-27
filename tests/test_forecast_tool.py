"""Tests for src/tools/forecast_tool.py's `_forecast` — capturing the same
scenarios that were verified by hand (a synthetic 6-point rising series,
both a near and a deliberately-absurd horizon) when this tool was first
built, per DOCEXP.md's Slice 9b entry, as a real regression suite instead
of a one-off script.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.tools.forecast_tool import _forecast


def _rising_series(n=6, step_hours=6, start_value=1000.0, slope_per_hour=50.0):
    base = datetime(2026, 1, 1)
    return [
        [base + timedelta(hours=step_hours * i), start_value + slope_per_hour * step_hours * i]
        for i in range(n)
    ]


def test_reports_insufficient_history_with_one_snapshot():
    rows = [[datetime(2026, 1, 1), 1000.0]]
    result = _forecast(["polled_at", "player_count"], rows, horizon_days=1)
    assert result["insufficient_history"] is True
    assert result["n_snapshots"] == 1
    assert "message" in result


def test_reports_insufficient_history_with_zero_real_rows():
    with pytest.raises(ValueError, match="no non-null"):
        _forecast(["polled_at", "player_count"], [[None, None]], horizon_days=1)


def test_projects_forward_along_a_clean_linear_trend():
    rows = _rising_series()
    result = _forecast(["polled_at", "player_count"], rows, horizon_days=2)
    assert result["insufficient_history"] is False
    assert result["n_snapshots"] == 6
    assert result["r_squared"] == pytest.approx(1.0, abs=1e-6)
    # slope_per_day should be 50/hr * 24 = 1200/day
    assert result["slope_per_day"] == pytest.approx(1200.0, rel=0.01)
    assert result["projected_value"] > rows[-1][1]  # rising trend, projects higher


def test_flags_low_confidence_when_horizon_dwarfs_observed_span():
    rows = _rising_series()  # spans 1.25 days
    result = _forecast(["polled_at", "player_count"], rows, horizon_days=365)
    assert result["low_confidence"] is True
    assert any("day(s) ahead" in reason for reason in result["low_confidence_reasons"])


def test_flags_low_confidence_when_snapshots_are_few_even_at_a_near_horizon():
    rows = _rising_series(n=3)
    result = _forecast(["polled_at", "player_count"], rows, horizon_days=1)
    assert result["low_confidence"] is True
    assert any("snapshots collected" in reason for reason in result["low_confidence_reasons"])


def test_does_not_flag_low_confidence_with_enough_points_and_a_near_horizon():
    rows = _rising_series(n=6, step_hours=24)  # spans 5 days
    result = _forecast(["polled_at", "player_count"], rows, horizon_days=1)
    assert result["low_confidence"] is False


def test_projected_value_never_goes_negative():
    # A steeply falling series projected far enough forward would cross
    # zero on a pure linear fit -- the tool clips to 0 rather than
    # reporting a nonsensical negative player count.
    base = datetime(2026, 1, 1)
    rows = [[base + timedelta(hours=6 * i), 100.0 - 40.0 * i] for i in range(6)]
    result = _forecast(["polled_at", "player_count"], rows, horizon_days=30)
    assert result["projected_value"] >= 0.0


def test_rejects_wrong_column_count():
    with pytest.raises(ValueError, match="exactly two columns"):
        _forecast(["polled_at"], [[datetime(2026, 1, 1)]], horizon_days=1)


def test_rejects_non_positive_horizon():
    rows = _rising_series()
    with pytest.raises(ValueError, match="positive"):
        _forecast(["polled_at", "player_count"], rows, horizon_days=0)
