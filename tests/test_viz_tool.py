"""Tests for src/tools/viz_tool.py's deterministic chart-type inference."""

from __future__ import annotations

from src.tools.viz_tool import infer_chart_spec


def test_label_then_number_infers_a_bar_chart():
    spec = infer_chart_spec(["name", "price"], [["A", 1.0], ["B", 2.0]])
    assert spec["type"] == "bar"
    assert spec["x"]["field"] == "name"
    assert spec["y"]["field"] == "price"


def test_number_then_label_swaps_so_the_label_becomes_the_x_axis():
    spec = infer_chart_spec(["price", "name"], [[1.0, "A"], [2.0, "B"]])
    assert spec["type"] == "bar"
    assert spec["x"]["field"] == "name"
    assert spec["y"]["field"] == "price"
    assert spec["data"][0] == {"name": "A", "price": 1.0}


def test_two_numeric_columns_infers_a_scatter_plot():
    spec = infer_chart_spec(["price", "score"], [[1.0, 0.9], [2.0, 0.8]])
    assert spec["type"] == "scatter"


def test_two_non_numeric_columns_returns_none():
    assert infer_chart_spec(["a", "b"], [["x", "y"], ["p", "q"]]) is None


def test_a_single_row_returns_none():
    # One row is a fact, not a distribution -- nothing to chart.
    assert infer_chart_spec(["name", "price"], [["A", 1.0]]) is None


def test_three_columns_returns_none():
    # Which two matter is ambiguous without an LLM call -- punt to a table.
    assert infer_chart_spec(["a", "b", "c"], [[1, 2, 3], [4, 5, 6]]) is None


def test_no_rows_returns_none():
    assert infer_chart_spec(["name", "price"], []) is None
