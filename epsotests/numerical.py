"""Deterministic EPSO numerical-reasoning question generation.

The numerical generator deliberately separates three concerns:

* :class:`NumericalTable` and :class:`NumericalChart` preserve source data;
* calculation helpers return explicit, serialisable calculation steps; and
* renderers/explanations consume those models without changing the maths.

The public question payload follows the visual generator's learner-facing
contract: option controls are hidden-answer friendly, the ``explainLogic``
action is available on demand, and every question can be regenerated from its
seed and metadata without a browser or third-party runtime dependency.
"""

from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
import html
import io
import json
import math
import random
from typing import Any, Iterable, Mapping, Sequence

from .signatures import stable_signature
from .visual_abstract import (
    EXAM_PROFILES,
    EXPLAIN_LOGIC_ACTION_ID,
    HIDE_SOLUTION_ACTION_ID,
    ExamProfile,
    resolve_exam_profile,
)


SUPPORTED_NUMERICAL_FORMATS = ("table", "bar-chart", "line-chart")
SUPPORTED_NUMERICAL_OPERATIONS = (
    "percentage-change",
    "ratio",
    "proportion",
    "total",
    "growth",
    "comparison",
    "multi-step",
)
SUPPORTED_NUMERICAL_DIFFICULTIES = ("easy", "medium", "hard")
_NUMERICAL_OPERATION_ALIASES = {
    "percentage": "percentage-change",
    "percent-change": "percentage-change",
    "percentage_change": "percentage-change",
    "percent": "percentage-change",
    "ratios": "ratio",
    "proportions": "proportion",
    "sum": "total",
    "totals": "total",
    "increase": "growth",
    "compound-growth": "growth",
    "compare": "comparison",
    "difference": "comparison",
    "multi_step": "multi-step",
    "multistep": "multi-step",
}
_FORMAT_ALIASES = {
    "chart": "bar-chart",
    "bar": "bar-chart",
    "bar_chart": "bar-chart",
    "line": "line-chart",
    "line_chart": "line-chart",
    "grid": "table",
}


# ---------------------------------------------------------------------------
# Typed source and calculation models


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError(f"not a numeric value: {value!r}") from error


def _quantize(value: Decimal, decimals: int = 1) -> Decimal:
    decimals = max(0, int(decimals))
    quantum = Decimal(1).scaleb(-decimals)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _json_number(value: Decimal) -> int | float:
    value = value.normalize()
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _json_number(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _fmt(value: Any, decimals: int | None = None) -> str:
    number = _decimal(value)
    if decimals is None:
        text = format(number, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    return f"{number:.{max(0, int(decimals))}f}"


def _rounding_text(decimals: int) -> str:
    return "nearest whole number" if decimals == 0 else f"{decimals} decimal place" + ("s" if decimals != 1 else "")


def _unit_suffix(unit: str) -> str:
    return "" if not unit or unit == "%" else f" {unit}"


@dataclass(frozen=True)
class CalculationStep:
    """One inspectable step in a numerical solution."""

    id: str
    label: str
    formula: str
    substitution: str
    result: Any
    unit: str = ""
    rounding: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "formula": self.formula,
            "substitution": self.substitution,
            "result": _json_value(self.result),
            "unit": self.unit,
            "rounding": self.rounding,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalculationStep":
        return cls(
            id=str(data.get("id", "step")),
            label=str(data.get("label", "Calculation")),
            formula=str(data.get("formula", "")),
            substitution=str(data.get("substitution", "")),
            result=data.get("result"),
            unit=str(data.get("unit", "")),
            rounding=str(data.get("rounding", "")),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True)
class NumericalTable:
    """A serialisable table whose rows remain in their source order."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    title: str = ""
    unit: str = ""

    def __post_init__(self) -> None:
        columns = tuple(str(column) for column in self.columns)
        object.__setattr__(self, "columns", columns)
        normalized: list[tuple[Any, ...]] = []
        for row in self.rows:
            values = tuple(row)
            if len(values) != len(columns):
                raise ValueError("every table row must match the number of columns")
            normalized.append(values)
        object.__setattr__(self, "rows", tuple(normalized))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "table",
            "title": self.title,
            "unit": self.unit,
            "columns": list(self.columns),
            "rows": [
                {column: _json_value(value) for column, value in zip(self.columns, row)}
                for row in self.rows
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NumericalTable":
        return parse_table(data)


@dataclass(frozen=True)
class ChartPoint:
    label: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "value": _json_value(self.value)}


@dataclass(frozen=True)
class ChartSeries:
    name: str
    points: tuple[ChartPoint, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "points": [point.to_dict() for point in self.points],
        }


@dataclass(frozen=True)
class NumericalChart:
    """Chart data independent of the SVG renderer."""

    chart_type: str
    title: str
    series: tuple[ChartSeries, ...]
    x_label: str = ""
    y_label: str = ""
    unit: str = ""

    def __post_init__(self) -> None:
        chart_type = str(self.chart_type).lower()
        if chart_type not in ("bar-chart", "line-chart"):
            raise ValueError("chart_type must be bar-chart or line-chart")
        object.__setattr__(self, "chart_type", chart_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.chart_type,
            "title": self.title,
            "xLabel": self.x_label,
            "yLabel": self.y_label,
            "unit": self.unit,
            "series": [series.to_dict() for series in self.series],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NumericalChart":
        return parse_chart(data)


@dataclass(frozen=True)
class NumericalOption:
    id: str
    value: Any
    label: str
    unit: str
    mutation: Mapping[str, Any]
    numeric_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "value": _json_value(self.value),
            "label": self.label,
            "unit": self.unit,
            "mutation": _json_value(dict(self.mutation)),
        }
        if self.numeric_value is not None:
            result["numericValue"] = _json_value(self.numeric_value)
        return result


@dataclass(frozen=True)
class NumericalQuestion:
    """Typed view of the portable numerical learner-facing payload."""

    id: str
    item_number: int
    exam_profile: str
    option_count: int
    format: str
    difficulty: str
    operation: str
    stimulus: Mapping[str, Any]
    question: str
    options: tuple[Mapping[str, Any], ...]
    correct_option: str
    explanation: str
    explanation_fragments: tuple[str, ...]
    actions: Mapping[str, Any]
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "itemNumber": self.item_number,
            "exam": "numerical",
            "examProfile": self.exam_profile,
            "optionCount": self.option_count,
            "format": self.format,
            "difficulty": self.difficulty,
            "operation": self.operation,
            "stimulus": _json_value(dict(self.stimulus)),
            "question": self.question,
            "options": [_json_value(dict(option)) for option in self.options],
            "correctOption": self.correct_option,
            "explanation": self.explanation,
            "explanationFragments": list(self.explanation_fragments),
            "actions": _json_value(dict(self.actions)),
            "metadata": _json_value(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NumericalQuestion":
        return cls(
            id=str(data["id"]),
            item_number=int(data.get("itemNumber", 1)),
            exam_profile=str(data["examProfile"]),
            option_count=int(data["optionCount"]),
            format=str(data["format"]),
            difficulty=str(data["difficulty"]),
            operation=str(data["operation"]),
            stimulus=dict(data["stimulus"]),
            question=str(data["question"]),
            options=tuple(dict(option) for option in data["options"]),
            correct_option=str(data["correctOption"]),
            explanation=str(data["explanation"]),
            explanation_fragments=tuple(data.get("explanationFragments", ())),
            actions=dict(data["actions"]),
            metadata=dict(data["metadata"]),
        )


# ---------------------------------------------------------------------------
# Parsing and rendering, deliberately independent from calculations


def parse_table(data: Any) -> NumericalTable:
    """Parse a table from the typed model, JSON-shaped mapping, rows, or CSV."""

    if isinstance(data, NumericalTable):
        return data
    title = ""
    unit = ""
    if isinstance(data, str):
        records = list(csv.reader(io.StringIO(data.strip())))
        if not records:
            raise ValueError("table CSV is empty")
        columns = tuple(records[0])
        return NumericalTable(columns, tuple(tuple(row) for row in records[1:]))
    if isinstance(data, Mapping):
        title = str(data.get("title", ""))
        unit = str(data.get("unit", ""))
        raw_rows = data.get("rows", data.get("data", ()))
        columns = tuple(str(column) for column in data.get("columns", ()))
    else:
        raw_rows = data
        columns = ()
    raw_rows = list(raw_rows or ())
    if not columns and raw_rows and isinstance(raw_rows[0], Mapping):
        columns = tuple(str(column) for column in raw_rows[0].keys())
    if not columns and raw_rows:
        columns = tuple(
            ["Category"] + [f"Value {index}" for index in range(1, len(raw_rows[0]))]
            if isinstance(raw_rows[0], (list, tuple))
            else ["Category", "Value"]
        )
    if not columns:
        columns = ("Category", "Value")
    rows: list[tuple[Any, ...]] = []
    for raw_row in raw_rows:
        if isinstance(raw_row, Mapping):
            rows.append(tuple(raw_row.get(column, "") for column in columns))
        else:
            values = tuple(raw_row)
            if len(values) != len(columns):
                raise ValueError("every parsed table row must match its columns")
            rows.append(values)
    return NumericalTable(columns, tuple(rows), title, unit)


def parse_chart(data: Any) -> NumericalChart:
    """Parse a chart mapping while retaining every series and point."""

    if isinstance(data, NumericalChart):
        return data
    if not isinstance(data, Mapping):
        raise TypeError("chart data must be a mapping or NumericalChart")
    chart_type = _FORMAT_ALIASES.get(
        str(data.get("type", data.get("chartType", "bar-chart"))).lower(),
        str(data.get("type", data.get("chartType", "bar-chart"))).lower(),
    )
    series_data = data.get("series", ())
    series: list[ChartSeries] = []
    for raw_series in series_data:
        if isinstance(raw_series, Mapping):
            name = str(raw_series.get("name", "Series"))
            raw_points = raw_series.get("points", raw_series.get("data", ()))
        else:
            name = "Series"
            raw_points = raw_series
        points: list[ChartPoint] = []
        for raw_point in raw_points or ():
            if isinstance(raw_point, Mapping):
                points.append(
                    ChartPoint(
                        str(raw_point.get("label", raw_point.get("x", ""))),
                        raw_point.get("value", raw_point.get("y", 0)),
                    )
                )
            else:
                points.append(ChartPoint(str(len(points) + 1), raw_point))
        series.append(ChartSeries(name, tuple(points)))
    return NumericalChart(
        chart_type=chart_type,
        title=str(data.get("title", "")),
        x_label=str(data.get("xLabel", data.get("x_label", ""))),
        y_label=str(data.get("yLabel", data.get("y_label", ""))),
        unit=str(data.get("unit", "")),
        series=tuple(series),
    )


def table_to_chart(
    table: NumericalTable | Mapping[str, Any], chart_type: str = "bar-chart"
) -> NumericalChart:
    """Create chart data from numeric table columns without rendering it."""

    table = parse_table(table)
    if len(table.columns) < 2:
        raise ValueError("a chart table needs a label column and one numeric column")
    label_column = table.columns[0]
    series: list[ChartSeries] = []
    for column_index, column in enumerate(table.columns[1:], start=1):
        points = []
        for row in table.rows:
            try:
                value: Any = _decimal(row[column_index])
            except ValueError:
                continue
            points.append(ChartPoint(str(row[0]), value))
        if points:
            series.append(ChartSeries(column, tuple(points)))
    return NumericalChart(
        chart_type=_FORMAT_ALIASES.get(str(chart_type).lower(), str(chart_type).lower()),
        title=table.title,
        series=tuple(series),
        x_label=label_column,
        y_label=table.unit or "Value",
        unit=table.unit,
    )


def render_table_html(table: NumericalTable | Mapping[str, Any]) -> str:
    """Render an accessible, HTML-friendly table representation."""

    table = parse_table(table)
    caption = f"<caption>{html.escape(table.title)}</caption>" if table.title else ""
    head = "".join(f"<th scope=\"col\">{html.escape(column)}</th>" for column in table.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(_json_value(value)))}</td>" for value in row) + "</tr>"
        for row in table.rows
    )
    return f'<table role="table" aria-label="{html.escape(table.title or "source data", quote=True)}">{caption}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def render_chart_svg(
    chart: NumericalChart | Mapping[str, Any], width: int = 640, height: int = 340
) -> str:
    """Render bar or line chart data as deterministic accessible SVG."""

    chart = parse_chart(chart)
    width, height = int(width), int(height)
    left, top, right, bottom = 64, 48, 22, 62
    plot_width, plot_height = width - left - right, height - top - bottom
    all_values = [
        _decimal(point.value)
        for series in chart.series
        for point in series.points
    ] or [Decimal(0)]
    minimum = min(Decimal(0), min(all_values))
    maximum = max(Decimal(1), max(all_values))
    span = maximum - minimum or Decimal(1)

    def x_for(index: int, count: int) -> float:
        return left + (plot_width * (index + 0.5) / max(1, count))

    def y_for(value: Decimal) -> float:
        return top + float((maximum - value) / span) * plot_height

    title = html.escape(chart.title or "Numerical reasoning chart", quote=True)
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" data-chart-type="{html.escape(chart.chart_type, quote=True)}" aria-label="{title}">',
        f"<title>{title}</title>",
        f'<rect width="100%" height="100%" fill="#ffffff"/><line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#374151"/><line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#374151"/>',
        f'<text x="{width // 2}" y="24" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#111827">{title}</text>',
    ]
    colors = ("#2563eb", "#dc2626", "#059669", "#7c3aed", "#d97706")
    point_count = max((len(series.points) for series in chart.series), default=1)
    labels = chart.series[0].points if chart.series else ()
    for index, point in enumerate(labels):
        x = x_for(index, point_count)
        pieces.append(f'<text x="{x:.2f}" y="{top + plot_height + 25}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#111827">{html.escape(point.label)}</text>')
    if chart.chart_type == "line-chart":
        for series_index, series in enumerate(chart.series):
            color = colors[series_index % len(colors)]
            points = " ".join(f"{x_for(i, point_count):.2f},{y_for(_decimal(point.value)):.2f}" for i, point in enumerate(series.points))
            pieces.append(f'<polyline data-series="{html.escape(series.name, quote=True)}" points="{points}" fill="none" stroke="{color}" stroke-width="3"/>')
            for point_index, point in enumerate(series.points):
                x, y = x_for(point_index, point_count), y_for(_decimal(point.value))
                pieces.append(f'<circle data-series="{html.escape(series.name, quote=True)}" cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}"/><title>{html.escape(series.name)}: {html.escape(_fmt(point.value))}</title>')
    else:
        series_count = max(1, len(chart.series))
        group_width = plot_width / max(1, point_count)
        bar_width = group_width * 0.72 / series_count
        for series_index, series in enumerate(chart.series):
            color = colors[series_index % len(colors)]
            for point_index, point in enumerate(series.points):
                value = _decimal(point.value)
                x = left + point_index * group_width + group_width * 0.14 + series_index * bar_width
                y = min(y_for(value), y_for(Decimal(0)))
                bar_height = abs(y_for(value) - y_for(Decimal(0)))
                pieces.append(f'<rect data-series="{html.escape(series.name, quote=True)}" x="{x:.2f}" y="{y:.2f}" width="{bar_width * 0.88:.2f}" height="{bar_height:.2f}" fill="{color}"><title>{html.escape(series.name)}: {html.escape(_fmt(value))}</title></rect>')
    for series_index, series in enumerate(chart.series):
        x = left + 8 + series_index * 118
        pieces.append(f'<text x="{x}" y="{height - 14}" font-family="sans-serif" font-size="11" fill="#111827">■ {html.escape(series.name)}</text>')
    if chart.y_label:
        pieces.append(f'<text x="14" y="{top + plot_height // 2}" transform="rotate(-90 14 {top + plot_height // 2})" font-family="sans-serif" font-size="11" fill="#111827">{html.escape(chart.y_label)}</text>')
    pieces.append("</svg>")
    return "".join(pieces)


# ---------------------------------------------------------------------------
# Calculation helpers


def calculate_percentage_change(old: Any, new: Any, decimals: int = 1) -> Decimal:
    old_value, new_value = _decimal(old), _decimal(new)
    if old_value == 0:
        raise ValueError("percentage change needs a non-zero original value")
    return _quantize((new_value - old_value) / old_value * 100, decimals)


def percentage_change(old: Any, new: Any, decimals: int = 1) -> Decimal:
    return calculate_percentage_change(old, new, decimals)


def simplify_ratio(numerator: Any, denominator: Any) -> str:
    first, second = _decimal(numerator), _decimal(denominator)
    if second == 0:
        raise ValueError("ratio denominator cannot be zero")
    fraction = Fraction(first) / Fraction(second)
    sign = -1 if fraction < 0 else 1
    fraction = abs(fraction)
    return f"{sign * fraction.numerator}:{fraction.denominator}"


def calculate_ratio(numerator: Any, denominator: Any) -> str:
    return simplify_ratio(numerator, denominator)


def ratio(numerator: Any, denominator: Any) -> str:
    return simplify_ratio(numerator, denominator)


def calculate_proportion(part: Any, whole: Any, total: Any | None = None, decimals: int = 1) -> Decimal:
    part_value, whole_value = _decimal(part), _decimal(whole)
    if whole_value == 0:
        raise ValueError("proportion whole cannot be zero")
    fraction = part_value / whole_value
    if total is not None:
        return _quantize(fraction * _decimal(total), decimals)
    return _quantize(fraction * 100, decimals)


def calculate_total(values: Iterable[Any], decimals: int = 2) -> Decimal:
    return _quantize(sum((_decimal(value) for value in values), Decimal(0)), decimals)


def total(values: Iterable[Any], decimals: int = 2) -> Decimal:
    return calculate_total(values, decimals)


def calculate_growth(initial: Any, rate_percent: Any, periods: int, decimals: int = 1) -> Decimal:
    if int(periods) < 0:
        raise ValueError("growth periods cannot be negative")
    return _quantize(_decimal(initial) * (1 + _decimal(rate_percent) / 100) ** int(periods), decimals)


def growth(initial: Any, rate_percent: Any, periods: int, decimals: int = 1) -> Decimal:
    return calculate_growth(initial, rate_percent, periods, decimals)


def calculate_comparison(first: Any, second: Any, decimals: int = 2) -> Decimal:
    return _quantize(_decimal(first) - _decimal(second), decimals)


def comparison(first: Any, second: Any, decimals: int = 2) -> Decimal:
    return calculate_comparison(first, second, decimals)


@dataclass(frozen=True)
class _Computation:
    value: Any
    label: str
    unit: str
    formula: str
    steps: tuple[CalculationStep, ...]
    visual_shortcut: str
    decimals: int
    details: Mapping[str, Any] = field(default_factory=dict)
    numeric_value: Any = None


@dataclass(frozen=True)
class _SourceBundle:
    table: NumericalTable
    parameters: Mapping[str, Any]
    question: str
    unit: str


def _level(difficulty: str | int) -> str:
    if isinstance(difficulty, int):
        return ("easy", "medium", "hard")[max(0, min(2, difficulty - 1))]
    value = str(difficulty).lower()
    if value in ("1", "easy", "low"):
        return "easy"
    if value in ("3", "hard", "high"):
        return "hard"
    return "medium"


def _operation(operation: str) -> str:
    normalized = str(operation).lower().replace("_", "-")
    normalized = _NUMERICAL_OPERATION_ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_NUMERICAL_OPERATIONS:
        raise ValueError(f"Unsupported numerical operation: {operation}")
    return normalized


def _representation(value: str | None, operation: str) -> str:
    if value is None:
        return "line-chart" if operation == "growth" else "bar-chart"
    normalized = _FORMAT_ALIASES.get(str(value).lower().replace("_", "-"), str(value).lower().replace("_", "-"))
    if normalized not in SUPPORTED_NUMERICAL_FORMATS:
        raise ValueError(f"Unsupported numerical representation: {value}")
    return normalized


def _source_bundle(seed: int, level: str, operation: str) -> _SourceBundle:
    rng = random.Random(seed * 37 + len(operation) * 11)
    difficulty_scale = {"easy": 1, "medium": 2, "hard": 3}[level]
    if operation == "percentage-change":
        old = 80 + rng.randrange(0, 11) * difficulty_scale
        change = 12 + rng.randrange(0, 6) * difficulty_scale
        new = old + change
        table = NumericalTable(
            ("Period", "Visitors"),
            (("January", old), ("February", new)),
            "Monthly visitors",
            "visitors",
        )
        return _SourceBundle(table, {"old": old, "new": new, "template": abs(int(seed)) % 2}, "What was the percentage change in visitors from January to February?", " %")
    if operation == "ratio":
        # Multiplying a fixed 3:2 pair only changes the drawing.  Pick from
        # explicit ratio templates so the answer and simplification path vary.
        ratio_templates = ((3, 2), (4, 3), (5, 2), (7, 4))
        template = abs(int(seed)) % len(ratio_templates)
        base_first, base_second = ratio_templates[template]
        multiplier = 1 + rng.randrange(1, 4)
        first, second = base_first * multiplier, base_second * multiplier
        table = NumericalTable(
            ("Department", "Applications"),
            (("Operations", first), ("Policy", second)),
            "Applications by department",
            "applications",
        )
        return _SourceBundle(table, {"numerator": first, "denominator": second, "template": template}, "What is the simplified ratio of Operations applications to Policy applications?", "")
    if operation == "proportion":
        fraction_templates = ((1, 3), (2, 5), (3, 8), (3, 4))
        template = abs(int(seed)) % len(fraction_templates)
        numerator, denominator = fraction_templates[template]
        whole = denominator * (30 + rng.randrange(0, 5) * difficulty_scale)
        part = numerator * (whole // denominator)
        table = NumericalTable(
            ("Group", "People"),
            (("Completed training", part), ("All participants", whole)),
            "Training participation",
            "people",
        )
        return _SourceBundle(table, {"part": part, "whole": whole, "template": template}, "What percentage of all participants completed training?", " %")
    if operation == "total":
        values = tuple(24 + rng.randrange(0, 8) * difficulty_scale for _ in range(4 if level != "hard" else 5))
        rows = tuple((f"Region {index + 1}", value) for index, value in enumerate(values))
        table = NumericalTable(("Region", "Cases"), rows, "Cases by region", "cases")
        return _SourceBundle(table, {"values": values, "template": abs(int(seed)) % 2}, "What is the total number of cases across all regions?", " cases")
    if operation == "growth":
        initial = 200 + rng.randrange(0, 5) * 25
        rate = (5, 8, 10)[rng.randrange(3)]
        periods = 2 + (0 if level == "easy" else 1 if level == "medium" else 2)
        rows = (("Year 1", initial), ("Year 2", _quantize(_decimal(initial) * (1 + _decimal(rate) / 100), 1)))
        table = NumericalTable(("Year", "Revenue"), rows, "Revenue growth", "thousand EUR")
        return _SourceBundle(table, {"initial": initial, "rate": rate, "periods": periods, "template": abs(int(seed)) % 2}, f"Revenue is {rate}% higher each year. What will it be after {periods} years?", " thousand EUR")
    if operation == "comparison":
        first = 100 + rng.randrange(0, 8) * 10
        second = 60 + rng.randrange(0, 5) * 8
        table = NumericalTable(
            ("Programme", "Requests"),
            (("Programme A", first), ("Programme B", second)),
            "Requests by programme",
            "requests",
        )
        return _SourceBundle(table, {"first": first, "second": second, "template": abs(int(seed)) % 2}, "How many more requests did Programme A receive than Programme B?", " requests")
    quantity_a = 3 + rng.randrange(0, 4)
    quantity_b = 2 + rng.randrange(0, 3)
    price_a, price_b = 18 + rng.randrange(0, 4) * 2, 25 + rng.randrange(0, 4) * 3
    discount = (10, 15, 20)[rng.randrange(3)]
    tax = (5, 8, 10)[rng.randrange(3)]
    table = NumericalTable(
        ("Item", "Quantity", "Unit price (EUR)"),
        (("Report", quantity_a, price_a), ("Workshop", quantity_b, price_b)),
        "Procurement order",
        "EUR",
    )
    return _SourceBundle(table, {"discount": discount, "tax": tax, "template": abs(int(seed)) % 2}, f"What is the final cost after a {discount}% discount and then {tax}% tax?", " EUR")


def _compute(bundle: _SourceBundle, operation: str, level: str) -> _Computation:
    table, p = bundle.table, bundle.parameters
    decimals = 0 if level == "easy" else 1 if level == "medium" else 2
    if operation == "percentage-change":
        old, new = _decimal(p["old"]), _decimal(p["new"])
        change = new - old
        result = calculate_percentage_change(old, new, decimals)
        if int(p.get("template", 0)) % 2:
            rate = change / old
            steps = (
                CalculationStep("1", "Relative change", "(new − original) ÷ original", f"({_fmt(new)} − {_fmt(old)}) ÷ {_fmt(old)}", rate, "rate", "not rounded"),
                CalculationStep("2", "Percentage change", "relative change × 100", f"{_fmt(rate, 4)} × 100", result, "%", _rounding_text(decimals)),
            )
            formula = "((new − original) ÷ original) × 100"
        else:
            steps = (
                CalculationStep("1", "Absolute change", "new − original", f"{_fmt(new)} − {_fmt(old)}", change, "visitors", "not rounded"),
                CalculationStep("2", "Percentage change", "(change ÷ original) × 100", f"({_fmt(change)} ÷ {_fmt(old)}) × 100", result, "%", _rounding_text(decimals)),
            )
            formula = "(new − original) ÷ original × 100"
        return _Computation(result, f"{_fmt(result, decimals)}%", "%", formula, steps, "Compare the two readings first; use the original reading as the denominator.", decimals, {"old": old, "new": new, "change": change, "template": p.get("template", 0)}, result)
    if operation == "ratio":
        first, second = _decimal(p["numerator"]), _decimal(p["denominator"])
        fraction = Fraction(first) / Fraction(second)
        result = simplify_ratio(first, second)
        divisor = math.gcd(int(first), int(second))
        if int(p.get("template", 0)) % 2:
            steps = (
                CalculationStep("1", "Scale to one part", "denominator ÷ numerator", f"{_fmt(second)} ÷ {_fmt(first)}", Decimal(fraction.numerator) / Decimal(fraction.denominator), "ratio", "exact"),
                CalculationStep("2", "Reduce both terms", "numerator ÷ gcd : denominator ÷ gcd", f"{_fmt(first)} ÷ {divisor} : {_fmt(second)} ÷ {divisor}", result, "", "exact"),
            )
            formula = "numerator : denominator, reduced by their greatest common divisor"
        else:
            steps = (
                CalculationStep("1", "Common divisor", "gcd(numerator, denominator)", f"gcd({_fmt(first)}, {_fmt(second)})", divisor, "applications", "exact"),
                CalculationStep("2", "Simplified ratio", "numerator ÷ gcd : denominator ÷ gcd", f"{_fmt(first)} ÷ {divisor} : {_fmt(second)} ÷ {divisor}", result, "", "exact"),
            )
            formula = "numerator : denominator, then divide both by their greatest common divisor"
        return _Computation(result, result, "", formula, steps, "Read the two bars in the requested order; simplify both by the same divisor.", 0, {"numerator": first, "denominator": second, "template": p.get("template", 0)}, _quantize(Decimal(fraction.numerator) / Decimal(fraction.denominator), 3))
    if operation == "proportion":
        part, whole = _decimal(p["part"]), _decimal(p["whole"])
        result = calculate_proportion(part, whole, decimals=decimals)
        if int(p.get("template", 0)) % 2:
            fraction = part / whole
            steps = (
                CalculationStep("1", "Part as a fraction", "part ÷ whole", f"{_fmt(part)} ÷ {_fmt(whole)}", fraction, "fraction", "not rounded"),
                CalculationStep("2", "Percentage", "fraction × 100", f"{_fmt(fraction, 4)} × 100", result, "%", _rounding_text(decimals)),
            )
        else:
            steps = (CalculationStep("1", "Proportion", "part ÷ whole × 100", f"{_fmt(part)} ÷ {_fmt(whole)} × 100", result, "%", _rounding_text(decimals)),)
        return _Computation(result, f"{_fmt(result, decimals)}%", "%", "part ÷ whole × 100", steps, "Use the part over the whole, then convert the fraction to a percentage.", decimals, {"part": part, "whole": whole, "template": p.get("template", 0)}, result)
    if operation == "total":
        values = tuple(_decimal(value) for value in p["values"])
        result = calculate_total(values, decimals)
        if int(p.get("template", 0)) % 2:
            midpoint = len(values) // 2
            first_group = calculate_total(values[:midpoint], decimals)
            second_group = calculate_total(values[midpoint:], decimals)
            steps = (
                CalculationStep("1", "First regional group", "value₁ + … + valueₙ", " + ".join(_fmt(value) for value in values[:midpoint]), first_group, "cases", _rounding_text(decimals)),
                CalculationStep("2", "Second regional group", "valueₙ₊₁ + … + valueₘ", " + ".join(_fmt(value) for value in values[midpoint:]), second_group, "cases", _rounding_text(decimals)),
                CalculationStep("3", "Total", "first group + second group", f"{_fmt(first_group)} + {_fmt(second_group)}", result, "cases", _rounding_text(decimals)),
            )
            formula = "(sum of first regional group) + (sum of second regional group)"
        else:
            steps = (CalculationStep("1", "Total", "value₁ + value₂ + …", " + ".join(_fmt(value) for value in values), result, "cases", _rounding_text(decimals)),)
            formula = "sum of all regional values"
        return _Computation(result, f"{_fmt(result, decimals)} cases", "cases", formula, steps, "Add every regional value exactly once.", decimals, {"values": values, "template": p.get("template", 0)}, result)
    if operation == "growth":
        initial, rate, periods = _decimal(p["initial"]), _decimal(p["rate"]), int(p["periods"])
        result = calculate_growth(initial, rate, periods, decimals)
        factor = 1 + rate / 100
        steps: list[CalculationStep] = [CalculationStep("1", "Growth factor", "1 + rate ÷ 100", f"1 + {_fmt(rate)} ÷ 100", factor, "factor", "exact")]
        current = initial
        for index in range(1, periods + 1):
            previous = current
            current = current * factor
            rounded = _quantize(current, decimals)
            if int(p.get("template", 0)) % 2:
                formula = "previous value + (previous value × rate ÷ 100)"
                substitution = f"{_fmt(previous, decimals)} + ({_fmt(previous, decimals)} × {_fmt(rate)} ÷ 100)"
            else:
                formula = "previous value × growth factor"
                substitution = f"{_fmt(previous, decimals)} × {_fmt(factor, 3)}"
            steps.append(CalculationStep(str(index + 1), f"After year {index}", formula, substitution, rounded, "thousand EUR", _rounding_text(decimals)))
        return _Computation(result, f"{_fmt(result, decimals)} thousand EUR", "thousand EUR", "initial × (1 + rate ÷ 100)^years", tuple(steps), "Follow the trend and apply the same multiplier for each additional year.", decimals, {"initial": initial, "rate": rate, "periods": periods, "template": p.get("template", 0)}, result)
    if operation == "comparison":
        first, second = _decimal(p["first"]), _decimal(p["second"])
        result = calculate_comparison(first, second, decimals)
        if int(p.get("template", 0)) % 2:
            absolute = abs(first - second)
            steps = (
                CalculationStep("1", "Absolute gap", "|A − B|", f"|{_fmt(first)} − {_fmt(second)}|", absolute, "requests", "exact"),
                CalculationStep("2", "Direction", "A − B", f"{_fmt(first)} − {_fmt(second)}", result, "requests", _rounding_text(decimals)),
            )
            formula = "absolute gap, then retain the direction Programme A − Programme B"
        else:
            steps = (CalculationStep("1", "Difference", "A − B", f"{_fmt(first)} − {_fmt(second)}", result, "requests", _rounding_text(decimals)),)
            formula = "Programme A − Programme B"
        return _Computation(result, f"{_fmt(result, decimals)} requests", "requests", formula, steps, "Subtract the shorter bar from the taller bar and keep the requested direction.", decimals, {"first": first, "second": second, "template": p.get("template", 0)}, result)
    quantity_a, quantity_b = _decimal(table.rows[0][1]), _decimal(table.rows[1][1])
    price_a, price_b = _decimal(table.rows[0][2]), _decimal(table.rows[1][2])
    discount, tax = _decimal(p["discount"]), _decimal(p["tax"])
    subtotal_a, subtotal_b = quantity_a * price_a, quantity_b * price_b
    subtotal = subtotal_a + subtotal_b
    discount_amount = subtotal * discount / 100
    after_discount = subtotal - discount_amount
    tax_amount = after_discount * tax / 100
    result = _quantize(after_discount + tax_amount, decimals)
    steps = (
        CalculationStep("1", "Report subtotal", "quantity × unit price", f"{_fmt(quantity_a)} × {_fmt(price_a)}", subtotal_a, "EUR", "exact"),
        CalculationStep("2", "Workshop subtotal", "quantity × unit price", f"{_fmt(quantity_b)} × {_fmt(price_b)}", subtotal_b, "EUR", "exact"),
        CalculationStep("3", "Order subtotal", "subtotal₁ + subtotal₂", f"{_fmt(subtotal_a)} + {_fmt(subtotal_b)}", subtotal, "EUR", "exact"),
        CalculationStep("4", "After discount", "subtotal × (1 − discount ÷ 100)", f"{_fmt(subtotal)} × (1 − {_fmt(discount)} ÷ 100)", after_discount, "EUR", "exact"),
        CalculationStep("5", "Final cost", "after discount × (1 + tax ÷ 100)", f"{_fmt(after_discount)} × (1 + {_fmt(tax)} ÷ 100)", result, "EUR", _rounding_text(decimals)),
    )
    return _Computation(result, f"{_fmt(result, decimals)} EUR", "EUR", "(Σ quantity × unit price) × (1 − discount ÷ 100) × (1 + tax ÷ 100)", steps, "Multiply each row first, combine subtotals, then apply the two percentages in order.", decimals, {"subtotal": subtotal, "discount": discount, "tax": tax}, result)


def _option_key(value: Any) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))


def _candidate(value: Any, computation: _Computation, kind: str, description: str, numeric_value: Any = None) -> NumericalOption:
    if isinstance(value, str):
        label = value if not computation.unit else f"{value}{_unit_suffix(computation.unit)}"
    else:
        label = f"{_fmt(value, computation.decimals)}{_unit_suffix(computation.unit)}"
    return NumericalOption("", value, label, computation.unit, {"kind": kind, "description": description}, numeric_value if numeric_value is not None else value)


def _distractor_candidates(computation: _Computation, operation: str) -> list[NumericalOption]:
    d = computation.details
    if operation == "percentage-change":
        old, new, change = _decimal(d["old"]), _decimal(d["new"]), _decimal(d["change"])
        return [
            _candidate(_quantize(change, computation.decimals), computation, "absolute-change", "uses the absolute change instead of dividing by the original value"),
            _candidate(_quantize(change / new * 100, computation.decimals), computation, "new-denominator", "divides by the new value rather than the original value"),
            _candidate(_quantize((new + old) / old * 100, computation.decimals), computation, "adds-values", "adds the two readings before calculating the change"),
        ]
    if operation == "ratio":
        numerator, denominator = _decimal(d["numerator"]), _decimal(d["denominator"])
        return [
            _candidate(simplify_ratio(denominator, numerator), computation, "reversed-ratio", "reverses the requested numerator and denominator", _decimal(denominator) / numerator),
            _candidate(f"{_fmt(numerator)}:{_fmt(denominator + 1)}", computation, "wrong-denominator", "changes the denominator instead of dividing both values by the common divisor", _decimal(numerator) / (denominator + 1)),
            _candidate(f"{_fmt(numerator + denominator)}:1", computation, "summed-ratio", "adds the two quantities instead of comparing them", _decimal(numerator + denominator)),
        ]
    if operation == "proportion":
        part, whole = _decimal(d["part"]), _decimal(d["whole"])
        return [
            _candidate(_quantize(part / whole, computation.decimals), computation, "fraction-not-percent", "leaves the fraction as a decimal instead of converting it to a percentage"),
            _candidate(_quantize(whole / part * 100, computation.decimals), computation, "reversed-proportion", "uses the whole as the numerator"),
            _candidate(_quantize((whole - part) / whole * 100, computation.decimals), computation, "complement", "calculates the percentage not in the selected group"),
        ]
    if operation == "total":
        values = tuple(_decimal(value) for value in d["values"])
        return [
            _candidate(_quantize(sum(values[:-1]), computation.decimals), computation, "omitted-value", "omits the last region from the total"),
            _candidate(_quantize(sum(values) / len(values), computation.decimals), computation, "average", "calculates an average instead of a total"),
            _candidate(_quantize(sum(values) + values[0], computation.decimals), computation, "double-counted", "counts the first region twice"),
        ]
    if operation == "growth":
        initial, rate, periods = _decimal(d["initial"]), _decimal(d["rate"]), int(d["periods"])
        return [
            _candidate(_quantize(initial * (1 + rate / 100 * periods), computation.decimals), computation, "simple-growth", "applies the rate to the original value only"),
            _candidate(_quantize(initial * (1 + rate / 100) ** max(0, periods - 1), computation.decimals), computation, "missing-period", "applies growth for one too few periods"),
            _candidate(_quantize(initial * (1 - rate / 100) ** periods, computation.decimals), computation, "decrease", "uses a decrease multiplier instead of a growth multiplier"),
        ]
    if operation == "comparison":
        first, second = _decimal(d["first"]), _decimal(d["second"])
        return [
            _candidate(_quantize(second - first, computation.decimals), computation, "reversed-subtraction", "subtracts Programme A from Programme B"),
            _candidate(_quantize(first + second, computation.decimals), computation, "sum-not-difference", "adds both programmes instead of finding the difference"),
            _candidate(_quantize(first / second * 100, computation.decimals), computation, "percentage-not-count", "reports a percentage instead of a number of requests"),
        ]
    subtotal, discount, tax = _decimal(d["subtotal"]), _decimal(d["discount"]), _decimal(d["tax"])
    return [
        _candidate(_quantize(subtotal * (1 - discount / 100), computation.decimals), computation, "stops-after-discount", "stops after the discount and omits tax"),
        _candidate(_quantize(subtotal * (1 + tax / 100), computation.decimals), computation, "omits-discount", "applies tax but omits the discount"),
        _candidate(_quantize(subtotal * (1 - (discount + tax) / 100), computation.decimals), computation, "combines-rates", "combines the rates as subtraction instead of applying them in order"),
    ]


def _option_records(computation: _Computation, operation: str, seed: int, option_count: int) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    if option_count < 2 or option_count > 26:
        raise ValueError("option_count must be between 2 and 26")
    correct = _candidate(computation.value, computation, "correct", "matches the formula and every calculation step", computation.numeric_value)
    wrong: list[NumericalOption] = []
    seen = {_option_key(correct.value)}
    for item in _distractor_candidates(computation, operation):
        if _option_key(item.value) not in seen:
            seen.add(_option_key(item.value))
            wrong.append(item)
    fallback = Decimal(1)
    while len(wrong) < option_count - 1:
        value = _quantize(_decimal(computation.numeric_value if computation.numeric_value is not None and not isinstance(computation.value, str) else 1) + fallback, computation.decimals)
        fallback += 1
        if _option_key(value) not in seen:
            seen.add(_option_key(value))
            wrong.append(_candidate(value, computation, "fallback", "uses a nearby value that does not follow the stated calculation"))
    candidates = [correct] + wrong[: option_count - 1]
    random.Random(seed + 7919).shuffle(candidates)
    options: list[dict[str, Any]] = []
    correct_option = ""
    correct_key = _option_key(correct.value)
    for index, option in enumerate(candidates):
        option_id = chr(65 + index)
        payload = option.to_dict()
        payload["id"] = option_id
        options.append(payload)
        if _option_key(option.value) == correct_key and option.mutation["kind"] == "correct":
            correct_option = option_id
    distractors = [dict(option["mutation"], option=option["id"], answer=option["value"]) for option in options if option["id"] != correct_option]
    return options, correct_option, distractors


def _step_text(step: CalculationStep) -> str:
    result = f"{_fmt(step.result)}{_unit_suffix(step.unit)}" if isinstance(step.result, (int, float, Decimal)) else str(step.result)
    if step.rounding == "exact":
        rounding = "; exact"
    elif step.rounding:
        rounding = f"; rounded to {step.rounding}"
    else:
        rounding = ""
    return f"{step.label}: {step.formula}; substitute {step.substitution} = {result}{rounding}."


def _final_rounding_text(computation: _Computation) -> str:
    if computation.steps and all(step.rounding == "exact" for step in computation.steps):
        return "using exact arithmetic"
    return f"rounded to {_rounding_text(computation.decimals)} where needed"


def _action(
    explanation: str,
    computation: _Computation,
    options: Sequence[Mapping[str, Any]],
    correct_option: str,
    source_data: Mapping[str, Any],
    profile: ExamProfile,
    distractors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "id": EXPLAIN_LOGIC_ACTION_ID,
        "type": "button",
        "label": "Explain logic",
        "localizedLabel": "Ver solución",
        "labels": {"en": "Explain Logic", "es": "Ver solución"},
        "ariaLabel": "Explain Logic / Ver solución",
        "initiallyVisible": False,
        "revealsAnswer": True,
        "solutionView": {
            "initiallyVisible": False,
            "hideAction": {
                "id": HIDE_SOLUTION_ACTION_ID,
                "type": "button",
                "label": "Hide solution",
                "localizedLabel": "Ocultar solución",
                "visibleAfterReveal": True,
            },
        },
        "result": {
            "optionCount": profile.option_count,
            "formula": computation.formula,
            "calculationSteps": [step.to_dict() for step in computation.steps],
            "visualShortcut": computation.visual_shortcut,
            "sourceData": _json_value(dict(source_data)),
            "explanation": explanation,
            "correctOption": correct_option,
            "correctReason": f"Option {correct_option} is correct because it follows the formula and all intermediate steps.",
            "distractors": [dict(item) for item in distractors],
        },
    }


def generate_numerical_question(
    operation: str = "percentage-change",
    seed: int = 0,
    difficulty: str | int = "medium",
    exam_profile: str | ExamProfile | None = None,
    representation: str | None = None,
) -> dict[str, Any]:
    """Generate one deterministic numerical chart/table question."""

    operation = _operation(operation)
    level = _level(difficulty)
    profile = resolve_exam_profile(exam_profile)
    display_format = _representation(representation, operation)
    bundle = _source_bundle(int(seed), level, operation)
    computation = _compute(bundle, operation, level)
    if display_format == "table":
        representation_data: dict[str, Any] = bundle.table.to_dict()
        rendered = render_table_html(bundle.table)
        stimulus: dict[str, Any] = {
            "type": "table",
            "title": bundle.table.title,
            "sourceData": bundle.table.to_dict(),
            "table": bundle.table.to_dict(),
            "representation": representation_data,
            "html": rendered,
            "accessibleText": f"{bundle.table.title}: " + "; ".join(", ".join(f"{key} {value}" for key, value in row.items()) for row in representation_data["rows"]),
        }
    else:
        chart = table_to_chart(bundle.table, display_format)
        representation_data = chart.to_dict()
        rendered = render_chart_svg(chart)
        stimulus = {
            "type": display_format,
            "title": chart.title,
            "sourceData": bundle.table.to_dict(),
            "chart": chart.to_dict(),
            "representation": representation_data,
            "svg": rendered,
            "accessibleText": f"{chart.title}: " + "; ".join(f"{series.name} " + ", ".join(f"{point.label} {point.value}" for point in series.points) for series in chart.series),
        }
    source_data = {**bundle.table.to_dict(), "parameters": _json_value(dict(bundle.parameters))}
    stimulus["sourceData"] = source_data
    options, correct_option, distractors = _option_records(computation, operation, int(seed) + 401, profile.option_count)
    step_texts = [_step_text(step) for step in computation.steps]
    explanation = (
        f"Read the values from the {('table' if display_format == 'table' else 'chart')} and apply the stated operation. "
        f"Formula: {computation.formula}. " + " ".join(step_texts) + " "
        f"Final result: {computation.label} ({_final_rounding_text(computation)}). "
        f"Option {correct_option} is correct. Visual shortcut: {computation.visual_shortcut} "
        "Each distractor records the specific calculation mistake it makes."
    )
    fragments = [
        f"Formula: {computation.formula}.",
        *step_texts,
        f"Final result: {computation.label}.",
        f"Visual shortcut: {computation.visual_shortcut}",
    ]
    action = _action(explanation, computation, options, correct_option, source_data, profile, distractors)
    answer_option = next(option for option in options if option["id"] == correct_option)
    operation_signature = stable_signature(
        {
            "operation": operation,
            "formula": computation.formula,
            "steps": [(step.label, step.formula) for step in computation.steps],
            "template": bundle.parameters.get("template", 0),
        }
    )
    calculation_signature = stable_signature(
        {"operation": operation, "steps": [step.to_dict() for step in computation.steps]}
    )
    answer_signature = json.dumps(
        {"value": answer_option["value"], "unit": computation.unit},
        sort_keys=True,
        separators=(",", ":"),
    )
    metadata: dict[str, Any] = {
        "seed": int(seed),
        "examProfile": profile.name,
        "optionCount": profile.option_count,
        "operation": operation,
        "sourceData": source_data,
        "table": bundle.table.to_dict(),
        "sourceParameters": _json_value(dict(bundle.parameters)),
        "representation": representation_data,
        "chart": representation_data if display_format != "table" else None,
        "formula": computation.formula,
        "calculationSteps": [step.to_dict() for step in computation.steps],
        "rounding": _rounding_text(computation.decimals),
        "visualShortcut": computation.visual_shortcut,
        "generatedFigures": [representation_data],
        "distractors": distractors,
        "explanationFragments": fragments,
        "answerValue": answer_option["value"],
        "answerUnit": computation.unit,
        "answerSignature": answer_signature,
        "answerValueSignature": stable_signature(answer_signature),
        "operationSignature": operation_signature,
        "calculationSignature": calculation_signature,
        "methodSignature": operation_signature,
        "explanationSignature": stable_signature(fragments),
    }
    question = NumericalQuestion(
        id=f"numerical-{operation}-{int(seed)}-{level}",
        item_number=1,
        exam_profile=profile.name,
        option_count=profile.option_count,
        format=display_format,
        difficulty=level,
        operation=operation,
        stimulus=stimulus,
        question=bundle.question,
        options=tuple(options),
        correct_option=correct_option,
        explanation=explanation,
        explanation_fragments=tuple(fragments),
        actions={"explainLogic": action},
        metadata=metadata,
    )
    return question.to_dict()


def generate_numerical(
    operation: str = "percentage-change",
    seed: int = 0,
    difficulty: str | int = "medium",
    exam_profile: str | ExamProfile | None = None,
    representation: str | None = None,
) -> dict[str, Any]:
    return generate_numerical_question(operation, seed, difficulty, exam_profile, representation)


def generate_percentage_change(**kwargs: Any) -> dict[str, Any]:
    return generate_numerical_question("percentage-change", **kwargs)


def generate_ratio(**kwargs: Any) -> dict[str, Any]:
    return generate_numerical_question("ratio", **kwargs)


def generate_proportion(**kwargs: Any) -> dict[str, Any]:
    return generate_numerical_question("proportion", **kwargs)


def generate_total(**kwargs: Any) -> dict[str, Any]:
    return generate_numerical_question("total", **kwargs)


def generate_growth(**kwargs: Any) -> dict[str, Any]:
    return generate_numerical_question("growth", **kwargs)


def generate_comparison(**kwargs: Any) -> dict[str, Any]:
    return generate_numerical_question("comparison", **kwargs)


def generate_multi_step(**kwargs: Any) -> dict[str, Any]:
    return generate_numerical_question("multi-step", **kwargs)


def explain_numerical_logic(question: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of the hidden numerical solution result."""

    try:
        action = question["actions"]["explainLogic"]
        if action["id"] != EXPLAIN_LOGIC_ACTION_ID:
            raise KeyError("unexpected action id")
        return deepcopy(action["result"])
    except (KeyError, TypeError) as error:
        raise ValueError("question has no Explain Logic action") from error


# A numerical-specific name keeps imports unambiguous while accepting the
# shared action shape used by visual consumers.
explain_logic = explain_numerical_logic

# Numeric aliases are intentionally kept alongside the longer Numerical names;
# both spellings are common in consumer code and serialize to the same model.
NumericChart = NumericalChart
NumericQuestion = NumericalQuestion
NumericTable = NumericalTable
generate_numeric_question = generate_numerical_question


__all__ = [
    "CalculationStep",
    "ChartPoint",
    "ChartSeries",
    "EXAM_PROFILES",
    "ExamProfile",
    "NumericalChart",
    "NumericalOption",
    "NumericalQuestion",
    "NumericalTable",
    "NumericChart",
    "NumericQuestion",
    "NumericTable",
    "SUPPORTED_NUMERICAL_DIFFICULTIES",
    "SUPPORTED_NUMERICAL_FORMATS",
    "SUPPORTED_NUMERICAL_OPERATIONS",
    "calculate_comparison",
    "calculate_growth",
    "calculate_percentage_change",
    "calculate_proportion",
    "calculate_ratio",
    "calculate_total",
    "comparison",
    "explain_logic",
    "explain_numerical_logic",
    "generate_comparison",
    "generate_growth",
    "generate_multi_step",
    "generate_numerical",
    "generate_numerical_question",
    "generate_numeric_question",
    "generate_percentage_change",
    "generate_proportion",
    "generate_ratio",
    "generate_total",
    "growth",
    "parse_chart",
    "parse_table",
    "percentage_change",
    "ratio",
    "render_chart_svg",
    "render_table_html",
    "simplify_ratio",
    "table_to_chart",
    "total",
]
