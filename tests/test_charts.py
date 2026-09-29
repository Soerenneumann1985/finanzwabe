from calculations import MonthTotals
from charts import column_chart, line_chart, nice_step


def test_nice_step_uses_clean_numbers():
    assert nice_step(400_000) == 100_000      # 4.000 € in 4 steps -> 1.000 €
    assert nice_step(900_000) == 250_000      # 9.000 € -> 2.500 €
    assert nice_step(0) == 10_000


def test_column_chart_scales_to_axis_max():
    chart = column_chart([MonthTotals(2026, 8, 300_000, 150_000), MonthTotals(2026, 9, 0, 0)],
                         current=(2026, 9))
    assert chart.ticks[-1].value >= 300_000
    first, second = chart.groups
    assert 0 < first.expense_pct < first.income_pct <= 100
    assert second.income_pct == 0
    assert second.current and not first.current
    assert "Saldo" in first.tip


def test_line_chart_points_span_the_box():
    chart = line_chart([("Jul", 100_000), ("Aug", 150_000), ("Sep", 125_000)])
    assert [p.x for p in chart.points] == [0, 50, 100]
    assert all(0 <= p.y <= 100 for p in chart.points)
    assert chart.line_path.startswith("M0.00,")
    assert chart.zero_y is None


def test_line_chart_with_negative_values_has_zero_line():
    chart = line_chart([("Jul", -50_000), ("Aug", 20_000)])
    assert chart.zero_y is not None and 0 < chart.zero_y < 100


def test_line_chart_single_point_and_empty():
    assert line_chart([("Sep", 500)]).points[0].x == 50
    assert line_chart([]) is None
