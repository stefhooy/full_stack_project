"""Tests for src/tools/stats_tool.py's three pure computation functions.
These already got real, ad hoc verification during Slice 4 development
(see DOCEXP.md — a real type-coercion bug and a real group-mislabeling
bug were both found that way) but never a checked-in suite; this captures
that as a real regression test instead of relying on memory of "I checked
this once."
"""

from __future__ import annotations

import pytest

from src.tools.stats_tool import _compare_two_groups, _describe, _outliers


def test_describe_computes_correct_summary_stats():
    result = _describe(["price"], [[10.0], [20.0], [30.0], [None]])
    assert result["mode"] == "describe"
    assert result["n"] == 3  # the None is dropped, not counted
    assert result["mean"] == pytest.approx(20.0)
    assert result["median"] == pytest.approx(20.0)
    assert result["min"] == 10.0
    assert result["max"] == 30.0


def test_describe_rejects_wrong_column_count():
    with pytest.raises(ValueError, match="one numeric column"):
        _describe(["a", "b"], [[1, 2]])


def test_describe_rejects_all_null_input():
    with pytest.raises(ValueError, match="no non-null"):
        _describe(["price"], [[None], [None]])


def test_compare_two_groups_flags_a_real_difference_as_significant():
    # Two groups with a large, consistent gap and enough points that the
    # difference isn't just noise -- should come back significant.
    rows = [["a", v] for v in [1.0, 1.1, 0.9, 1.05, 0.95]] + [
        ["b", v] for v in [10.0, 10.1, 9.9, 10.05, 9.95]
    ]
    result = _compare_two_groups(["group", "value"], rows)
    assert result["mode"] == "compare_two_groups"
    assert result["group_a"] == "a"
    assert result["group_b"] == "b"
    assert result["significant_at_0.05"] is True
    assert result["p_value"] < 0.05


def test_compare_two_groups_does_not_flag_noise_as_significant():
    rows = [["a", v] for v in [10.0, 12.0, 8.0, 11.0]] + [
        ["b", v] for v in [10.5, 9.5, 11.5, 9.0]
    ]
    result = _compare_two_groups(["group", "value"], rows)
    assert result["significant_at_0.05"] is False


def test_compare_two_groups_requires_exactly_two_groups():
    rows = [["a", 1.0], ["b", 2.0], ["c", 3.0], ["a", 1.5], ["b", 2.5], ["c", 3.5]]
    with pytest.raises(ValueError, match="exactly two distinct group labels"):
        _compare_two_groups(["group", "value"], rows)


def test_compare_two_groups_requires_at_least_two_obs_per_group():
    with pytest.raises(ValueError, match="at least 2 observations"):
        _compare_two_groups(["group", "value"], [["a", 1.0], ["b", 2.0], ["b", 2.1]])


def test_outliers_finds_the_obvious_one():
    # 20 tightly-clustered points, not 4 -- z-score outlier detection has a
    # real small-sample "masking" effect where one extreme point inflates
    # the mean/stddev enough to lower its own z-score below the threshold
    # (found by actually running this with 4 points first and getting 0
    # outliers back, not assumed) -- correct behavior of the statistic,
    # not a bug, but it means this test needs enough points that the
    # outlier can't drag the mean/stddev toward itself.
    labels = [f"Normal{i}" for i in range(20)] + ["WayOff"]
    values = [10] * 20 + [500]
    result = _outliers(["name", "value"], list(zip(labels, values, strict=True)), z_threshold=2.5)
    assert result["mode"] == "outliers"
    assert len(result["outliers"]) == 1
    assert result["outliers"][0]["label"] == "WayOff"


def test_outliers_reports_none_when_everything_is_identical():
    rows = [["a", 5], ["b", 5], ["c", 5]]
    result = _outliers(["name", "value"], rows, z_threshold=2.5)
    assert result["outliers"] == []
    assert result["stddev"] == 0.0


def test_outliers_requires_at_least_two_values():
    with pytest.raises(ValueError, match="at least 2"):
        _outliers(["name", "value"], [["a", 1]], z_threshold=2.5)
