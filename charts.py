"""Positions for the HTML/CSS charts.

This module only does layout (axis ticks, bar heights, line points in
percent). The money rules themselves live in calculations.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from calculations import MonthTotals
from money import format_cents, format_cents_short

MONTH_SHORT = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def nice_step(span_cents: int, ticks: int = 4) -> int:
    """A clean step (1, 2, 2.5 or 5 times a power of ten euros) for the axis."""
    if span_cents <= 0:
        return 100_00
    raw = span_cents / 100 / ticks
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * magnitude
        if step >= raw:
            return max(round(step * 100), 1)
    return round(10 * magnitude * 100)


@dataclass
class Tick:
    value: int
    percent: float  # distance from the bottom of the plot
    label: str


def _ticks(low: int, high: int, step: int) -> list[Tick]:
    ticks, value = [], low
    while value <= high:
        ticks.append(Tick(value, (value - low) * 100 / (high - low), format_cents_short(value)))
        value += step
    return ticks


@dataclass
class ColumnGroup:
    label: str
    income_pct: float
    expense_pct: float
    tip: str
    year: int
    month: int
    current: bool = False


@dataclass
class ColumnChart:
    groups: list[ColumnGroup]
    ticks: list[Tick]


def column_chart(months: list[MonthTotals], current: tuple[int, int] | None = None) -> ColumnChart:
    """Income vs expenses per month as two columns per group."""
    top = max([m.income for m in months] + [m.expenses for m in months] + [0])
    step = nice_step(top)
    axis_max = max(step * math.ceil(top / step), step)
    groups = [
        ColumnGroup(
            label=MONTH_SHORT[m.month - 1],
            income_pct=max(m.income, 0) * 100 / axis_max,
            expense_pct=max(m.expenses, 0) * 100 / axis_max,
            tip=(f"{MONTH_SHORT[m.month - 1]} {m.year}\nEinnahmen {format_cents(m.income)}\n"
                 f"Ausgaben {format_cents(m.expenses)}\nSaldo {format_cents(m.balance)}"),
            year=m.year,
            month=m.month,
            current=(m.year, m.month) == current,
        )
        for m in months
    ]
    return ColumnChart(groups, _ticks(0, axis_max, step))


@dataclass
class LinePoint:
    label: str
    value: int
    x: float  # percent from the left
    y: float  # percent from the top
    tip: str


@dataclass
class LineChart:
    points: list[LinePoint]
    ticks: list[Tick]
    line_path: str
    area_path: str
    zero_y: float | None


def line_chart(series: list[tuple[str, int]]) -> LineChart | None:
    """A single line (e.g. net worth per month) scaled to a 0..100 box."""
    if not series:
        return None
    values = [v for _, v in series]
    low, high = min(values), max(values)
    if low > 0 and low < high / 2:
        low = 0  # start at zero when that doesn't squash the line
    step = nice_step(max(high - low, abs(high), 1))
    axis_low = step * math.floor(low / step)
    axis_high = max(step * math.ceil(high / step), axis_low + step)
    span = axis_high - axis_low

    count = len(series)
    points = []
    for index, (label, value) in enumerate(series):
        x = 50.0 if count == 1 else index * 100 / (count - 1)
        y = 100 - (value - axis_low) * 100 / span
        points.append(LinePoint(label, value, x, y, f"{label}\n{format_cents(value)}"))

    line = " ".join(f"{'M' if i == 0 else 'L'}{p.x:.2f},{p.y:.2f}" for i, p in enumerate(points))
    area = f"{line} L{points[-1].x:.2f},100 L{points[0].x:.2f},100 Z"
    zero_y = 100 - (0 - axis_low) * 100 / span if axis_low < 0 < axis_high else None
    return LineChart(points, _ticks(axis_low, axis_high, step), line, area, zero_y)
