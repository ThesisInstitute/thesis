#!/usr/bin/env python3
"""Strict parser for SBA Loan Program Performance Disaster cells.

The parser fixtures exercise source layout only. Resolution must additionally
select the earliest witnessed, custody-verified capture; see the SBA custody
family design note.
"""

from __future__ import annotations

import datetime as dt
import functools
import hashlib
import io
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

LAYOUT_REFUSAL = "SBA PDF LAYOUT DRIFT (refusing):"
PARTIAL_REFUSAL = "SBA PERIOD PARTIAL (refusing):"
PARSER_REFUSAL = "SBA PDF PARSER UNAVAILABLE (refusing):"

CHARGE_OFF_AMOUNT_SERIES = "sba.disaster.loan_program.charge_off_amount"
CHARGE_OFF_RATE_SERIES = "sba.disaster.loan_program.charge_off_rate_upb"
POST_CHARGE_OFF_RECOVERY_SERIES = "sba.disaster.loan_program.post_charge_off_recovery"

COMPLETION_PARTIAL = "partial"
COMPLETION_COMPLETED = "completed"
SbaCompletionStatus = Literal["partial", "completed"]


@dataclass(frozen=True)
class SbaReportSpec:
    title: str
    page_count: int
    unit: str
    footer_lead: str
    definition_marker: str
    revision_marker: str


@dataclass(frozen=True)
class SbaLoanPerformanceCell:
    series: str
    fiscal_year: int
    value: int | float
    unit: str
    printed_value: str
    table_title: str
    report_as_of: str
    completion_status: SbaCompletionStatus
    partial_fiscal_year: int | None
    header_years: tuple[int, ...]
    pdf_sha256: str | None = None


@dataclass(frozen=True)
class _PdfBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def inside(self, outer: _PdfBox, *, tolerance: float = 0.0) -> bool:
        return (
            self.x0 >= outer.x0 - tolerance
            and self.y0 >= outer.y0 - tolerance
            and self.x1 <= outer.x1 + tolerance
            and self.y1 <= outer.y1 + tolerance
        )

    def intersects(self, other: _PdfBox) -> bool:
        return (
            self.x0 < other.x1
            and self.x1 > other.x0
            and self.y0 < other.y1
            and self.y1 > other.y0
        )


@dataclass(frozen=True)
class _PdfRectangle:
    box: _PdfBox
    axis_aligned: bool
    reviewed_grid_paint: bool = False


@dataclass(frozen=True)
class _PdfTextBox:
    text: str
    box: _PdfBox
    tag: str | None
    black_fill: bool


@dataclass(frozen=True)
class _PdfTextMark:
    tag: str | None
    black_fill: bool


@dataclass(frozen=True)
class _PdfGridRow:
    cells: tuple[_PdfBox, ...]


@dataclass(frozen=True)
class _SbaPdfGeometry:
    text: str
    header_years: tuple[int, ...]
    printed_values: tuple[str, ...]


class _PdfLayoutError(ValueError):
    pass


SBA_REPORT_SPECS = {
    CHARGE_OFF_AMOUNT_SERIES: SbaReportSpec(
        title="Table 5 - Charge Off Amount by Program",
        page_count=2,
        unit="USD",
        footer_lead=(
            "This table displays the total charge off amount by program as of "
            "the end of each fiscal year."
        ),
        definition_marker=(
            "Charge off amount is defined as the total dollar amount of principal "
            "and interest outstanding at the time that the loan is charged off."
        ),
        revision_marker=(
            "Charge off amounts for a given fiscal year may be adjusted due to "
            "data updates."
        ),
    ),
    CHARGE_OFF_RATE_SERIES: SbaReportSpec(
        title=(
            "Table 9 - Charge Off Rates as a Percent of Unpaid Principal "
            "Balance (UPB) Amount by Program"
        ),
        page_count=1,
        unit="percent",
        footer_lead=(
            "This table displays the charge off rates by program for each given "
            "fiscal year."
        ),
        definition_marker=(
            "Charge off rates are defined as the charge off amount during the "
            "fiscal year as a percent of UPB at fiscal year end."
        ),
        revision_marker=(
            "Charge off rates for previous fiscal years are updated to reflect "
            "changes to charge off amounts."
        ),
    ),
    POST_CHARGE_OFF_RECOVERY_SERIES: SbaReportSpec(
        title="Table 7 - Post-Charge Off Recovery Amount by Program",
        page_count=2,
        unit="USD",
        footer_lead=(
            "This table displays the total post-charge off recovery amount by "
            "program as of the end of each fiscal year."
        ),
        definition_marker=(
            "Post-charge off recovery amount is typically defined as the dollar "
            "amount recovered via the Treasury Cross Servicing program after a "
            "loan has been charged off, however not all these recoveries are due "
            "to Treasury efforts."
        ),
        revision_marker=(
            "Post-charge off recovery amounts for a given fiscal year may be "
            "adjusted due to data updates."
        ),
    ),
}

_HEADER_RE = re.compile(r"Program((?:\s+\d{4}){10})")
_USD_RE = re.compile(r"\$-?(?:0|[1-9]\d{0,2}(?:,\d{3})*)")
_PERCENT_RE = re.compile(r"(?:0|[1-9]\d*)(?:\.\d{2})%")
_PARTIAL_TAIL_RE = re.compile(
    r" Since data are not available through the end of the most recent fiscal "
    r"year, the data displayed in (?P<year>\d{4}) are as of "
    r"(?P<date>\d{2}/\d{2}/\d{4})\."
)
_EXPECTED_MEDIA_BOX = (1008.0, 612.0)
_EXPECTED_PAGE_BOX = (0.0, 0.0, *_EXPECTED_MEDIA_BOX)
_EXPECTED_CLIP_BOX = _PdfBox(17.28, 17.28, 990.72, 594.72)
_QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}
_MATRIX_TOLERANCE = 1e-6
_GEOMETRY_TOLERANCE = 0.75
_BOX_TOLERANCE = 1.0
_GRID_RULE_MAX_THICKNESS = 1.0
_GRID_ROW_MIN_HEIGHT = 8.0
_GRID_ROW_MAX_HEIGHT = 40.0
_REVIEWED_GRID_RGB = (0.569, 0.569, 0.569)
_REVIEWED_BACKGROUND_RGB = {
    (0.565, 0.69, 0.851),
    (0.8, 0.8, 0.8),
    (0.933, 0.933, 0.933),
}
_REVIEWED_TABLE_TEXT_HEIGHT = 8.19
_TABLE_TEXT_HEIGHT_TOLERANCE = 0.1


def _spec(series: str) -> SbaReportSpec:
    try:
        return SBA_REPORT_SPECS[series]
    except KeyError as exc:
        raise ValueError(f"unsupported SBA Loan Performance series {series!r}") from exc


def _layout_refusal(reason: str) -> tuple[None, str]:
    return None, f"{LAYOUT_REFUSAL} {reason}"


def _normalized_lines(text: str) -> list[str]:
    return [
        normalized
        for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        if (normalized := " ".join(line.split()))
    ]


def _box(values: Any) -> tuple[float, float, float, float]:
    return tuple(round(float(value), 3) for value in values)  # type: ignore[return-value]


def _clustered(values: list[float], *, tolerance: float) -> list[float]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if (
            not clusters
            or abs(value - sum(clusters[-1]) / len(clusters[-1])) > tolerance
        ):
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _transformed_rectangle(args: Any, cm: Any) -> _PdfRectangle | None:
    if len(args) != 4 or len(cm) != 6:
        return None
    x, y, width, height = (float(value) for value in args)
    a, b, c, d, e, f = (float(value) for value in cm)
    if not all(math.isfinite(value) for value in (x, y, width, height, *cm)):
        return None
    corners = (
        (a * x + c * y + e, b * x + d * y + f),
        (a * (x + width) + c * y + e, b * (x + width) + d * y + f),
        (a * x + c * (y + height) + e, b * x + d * (y + height) + f),
        (
            a * (x + width) + c * (y + height) + e,
            b * (x + width) + d * (y + height) + f,
        ),
    )
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return _PdfRectangle(
        box=_PdfBox(min(xs), min(ys), max(xs), max(ys)),
        axis_aligned=(abs(b) <= _MATRIX_TOLERANCE and abs(c) <= _MATRIX_TOLERANCE),
    )


def _page_rectangles(
    page: Any,
) -> tuple[list[_PdfRectangle], list[tuple[_PdfRectangle, ...] | None]]:
    """Return painted rectangles and the rectangles used as clipping paths."""

    pending: list[_PdfRectangle] = []
    painted: list[_PdfRectangle] = []
    clips: list[tuple[_PdfRectangle, ...] | None] = []
    complex_path = False
    grid_paint_started = False
    text_paint_started = False
    color_stack: list[
        tuple[
            tuple[str, tuple[float, ...] | None],
            tuple[str, tuple[float, ...] | None],
        ]
    ] = [(("/DeviceGray", (0.0,)), ("/DeviceGray", (0.0,)))]
    paint_operators = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
    other_path_operators = {b"m", b"l", b"c", b"v", b"y", b"h"}
    text_operators = {b"Tj", b"TJ", b"'", b'"'}
    non_path_paint_operators = {b"Do", b"sh", b"BI", b"ID", b"EI", b"INLINE IMAGE"}

    def visit(operator: bytes, args: Any, cm: Any, tm: Any) -> None:
        nonlocal complex_path, grid_paint_started, text_paint_started
        del tm
        if operator == b"q":
            color_stack.append(color_stack[-1])
        elif operator == b"Q":
            if len(color_stack) == 1:
                raise ValueError("unbalanced graphics-state restore")
            color_stack.pop()
        elif operator == b"g":
            color_stack[-1] = (
                ("/DeviceGray", _color_components(args)),
                color_stack[-1][1],
            )
        elif operator == b"G":
            color_stack[-1] = (
                color_stack[-1][0],
                ("/DeviceGray", _color_components(args)),
            )
        elif operator == b"rg":
            color_stack[-1] = (
                ("/DeviceRGB", _color_components(args)),
                color_stack[-1][1],
            )
        elif operator == b"RG":
            color_stack[-1] = (
                color_stack[-1][0],
                ("/DeviceRGB", _color_components(args)),
            )
        elif operator == b"k":
            color_stack[-1] = (
                ("/DeviceCMYK", _color_components(args)),
                color_stack[-1][1],
            )
        elif operator == b"K":
            color_stack[-1] = (
                color_stack[-1][0],
                ("/DeviceCMYK", _color_components(args)),
            )
        elif operator == b"cs":
            color_stack[-1] = (
                (str(args[0]) if args else "", None),
                color_stack[-1][1],
            )
        elif operator == b"CS":
            color_stack[-1] = (
                color_stack[-1][0],
                (str(args[0]) if args else "", None),
            )
        elif operator in {b"sc", b"scn"}:
            color_stack[-1] = (
                (color_stack[-1][0][0], _color_components(args)),
                color_stack[-1][1],
            )
        elif operator in {b"SC", b"SCN"}:
            color_stack[-1] = (
                color_stack[-1][0],
                (color_stack[-1][1][0], _color_components(args)),
            )
        elif operator in text_operators:
            text_paint_started = True
        elif operator in non_path_paint_operators:
            raise _PdfLayoutError("page 1 uses unsupported non-rectangle painting")
        elif operator == b"re":
            rectangle = _transformed_rectangle(args, cm)
            if rectangle is not None:
                pending.append(rectangle)
            else:
                complex_path = True
        elif operator in other_path_operators:
            complex_path = True
        elif operator in {b"W", b"W*"}:
            clips.append(None if complex_path else tuple(pending))
        elif operator in paint_operators:
            if complex_path or not pending:
                raise _PdfLayoutError("page 1 uses unsupported non-rectangle painting")
            fill, stroke = color_stack[-1]
            reviewed_grid_paint = (
                operator == b"B*"
                and _reviewed_grid_color(fill)
                and _reviewed_grid_color(stroke)
                and not complex_path
                and bool(pending)
                and all(_grid_rule_shape(rectangle) for rectangle in pending)
            )
            reviewed_background_paint = (
                operator == b"B*"
                and _reviewed_background_color(fill)
                and fill == stroke
            )
            if text_paint_started:
                raise _PdfLayoutError("page 1 paints over reviewed text")
            if grid_paint_started and not reviewed_grid_paint:
                raise _PdfLayoutError("page 1 paints over the reviewed table grid")
            if not grid_paint_started and not (
                reviewed_grid_paint or reviewed_background_paint
            ):
                raise _PdfLayoutError("page 1 uses unreviewed table background paint")
            grid_paint_started = grid_paint_started or reviewed_grid_paint
            painted.extend(
                replace(rectangle, reviewed_grid_paint=reviewed_grid_paint)
                for rectangle in pending
            )
            pending.clear()
            complex_path = False
        elif operator == b"n":
            pending.clear()
            complex_path = False

    page.extract_text(visitor_operand_before=visit)
    return painted, clips


def _reviewed_grid_color(
    color: tuple[str, tuple[float, ...] | None],
) -> bool:
    color_space, components = color
    return (
        color_space == "/DeviceRGB"
        and components is not None
        and len(components) == 3
        and all(
            math.isfinite(actual) and abs(actual - expected) <= _MATRIX_TOLERANCE
            for actual, expected in zip(components, _REVIEWED_GRID_RGB, strict=True)
        )
    )


def _reviewed_background_color(
    color: tuple[str, tuple[float, ...] | None],
) -> bool:
    color_space, components = color
    if color_space != "/DeviceRGB" or components is None or len(components) != 3:
        return False
    return any(
        all(
            math.isfinite(actual) and abs(actual - expected) <= _MATRIX_TOLERANCE
            for actual, expected in zip(components, reviewed, strict=True)
        )
        for reviewed in _REVIEWED_BACKGROUND_RGB
    )


def _grid_rule_shape(rectangle: _PdfRectangle) -> bool:
    return rectangle.axis_aligned and (
        (
            0 < rectangle.box.width <= _GRID_RULE_MAX_THICKNESS
            and _GRID_ROW_MIN_HEIGHT <= rectangle.box.height <= _GRID_ROW_MAX_HEIGHT
        )
        or (
            0 < rectangle.box.height <= _GRID_RULE_MAX_THICKNESS
            and rectangle.box.width >= 20
        )
    )


def _black_fill(color_space: str, components: tuple[float, ...] | None) -> bool:
    if components is None or not all(math.isfinite(value) for value in components):
        return False
    if color_space == "/DeviceGray":
        return len(components) == 1 and abs(components[0]) <= _MATRIX_TOLERANCE
    if color_space == "/DeviceRGB":
        return len(components) == 3 and all(
            abs(value) <= _MATRIX_TOLERANCE for value in components
        )
    if color_space == "/DeviceCMYK":
        return (
            len(components) == 4
            and all(abs(value) <= _MATRIX_TOLERANCE for value in components[:3])
            and abs(components[3] - 1) <= _MATRIX_TOLERANCE
        )
    return False


def _color_components(args: Any) -> tuple[float, ...] | None:
    try:
        return tuple(float(value) for value in args)
    except (TypeError, ValueError):
        return None


def _text_show_marks(operations: list[Any]) -> list[_PdfTextMark]:
    """Return tagged paint state for each text-show value."""

    marks: list[_PdfTextMark] = []
    stack: list[str] = []
    paint_stack: list[tuple[str, tuple[float, ...] | None]] = [("/DeviceGray", (0.0,))]

    def append_mark() -> None:
        color_space, components = paint_stack[-1]
        marks.append(
            _PdfTextMark(
                tag=stack[-1] if stack else None,
                black_fill=_black_fill(color_space, components),
            )
        )

    for args, operator in operations:
        if operator in {b"BDC", b"BMC"}:
            tag = str(args[0]) if args else ""
            if tag == "/OC":
                raise _PdfLayoutError("page 1 uses optional-content marking")
            stack.append(tag)
        elif operator == b"EMC":
            if not stack:
                raise ValueError("unbalanced marked-content end")
            stack.pop()
        elif operator == b"q":
            paint_stack.append(paint_stack[-1])
        elif operator == b"Q":
            if len(paint_stack) == 1:
                raise ValueError("unbalanced graphics-state restore")
            paint_stack.pop()
        elif operator == b"g":
            paint_stack[-1] = ("/DeviceGray", _color_components(args))
        elif operator == b"rg":
            paint_stack[-1] = ("/DeviceRGB", _color_components(args))
        elif operator == b"k":
            paint_stack[-1] = ("/DeviceCMYK", _color_components(args))
        elif operator == b"cs":
            paint_stack[-1] = (str(args[0]) if args else "", None)
        elif operator in {b"sc", b"scn"}:
            paint_stack[-1] = (paint_stack[-1][0], _color_components(args))
        elif operator == b"Tr":
            mode = _color_components(args)
            if mode != (0.0,):
                raise _PdfLayoutError("page 1 uses non-fill text rendering mode")
        elif operator in {b"Tj", b"'", b'"'}:
            append_mark()
        elif operator == b"TJ":
            if not args:
                continue
            for value in args[0]:
                if isinstance(value, (str, bytes)):
                    append_mark()
    if stack:
        raise ValueError("unbalanced marked-content start")
    if len(paint_stack) != 1:
        raise ValueError("unbalanced graphics-state save")
    return marks


def _validate_graphics_states(page: Any, operations: list[Any]) -> None:
    resources = page.get("/Resources")
    if not isinstance(resources, Mapping):
        raise _PdfLayoutError("page 1 has no reviewed resource dictionary")
    ext_states = resources.get("/ExtGState", {})
    if not isinstance(ext_states, Mapping):
        raise _PdfLayoutError("page 1 has an invalid graphics-state dictionary")
    referenced = {
        str(args[0])
        for args, operator in operations
        if operator == b"gs" and len(args) == 1
    }
    if any(operator == b"gs" and len(args) != 1 for args, operator in operations):
        raise _PdfLayoutError("page 1 has an invalid graphics-state reference")
    if referenced - {str(name) for name in ext_states}:
        raise _PdfLayoutError("page 1 references an unknown graphics state")

    allowed_keys = {"/Type", "/CA", "/ca"}
    for name, raw_state in ext_states.items():
        state = raw_state.get_object()
        if not isinstance(state, Mapping):
            raise _PdfLayoutError(f"page 1 graphics state {name} is invalid")
        if {str(key) for key in state} - allowed_keys:
            raise _PdfLayoutError(
                f"page 1 graphics state {name} has unsupported effects"
            )
        if state.get("/Type", "/ExtGState") != "/ExtGState":
            raise _PdfLayoutError(f"page 1 graphics state {name} has the wrong type")
        try:
            stroke_alpha = float(state.get("/CA", 1))
            fill_alpha = float(state.get("/ca", 1))
        except (TypeError, ValueError) as exc:
            raise _PdfLayoutError(
                f"page 1 graphics state {name} has invalid opacity"
            ) from exc
        if (
            not math.isfinite(stroke_alpha)
            or not math.isfinite(fill_alpha)
            or abs(stroke_alpha - 1) > _MATRIX_TOLERANCE
            or abs(fill_alpha - 1) > _MATRIX_TOLERANCE
        ):
            raise _PdfLayoutError(f"page 1 graphics state {name} is not opaque")


def _page_text_boxes(page: Any) -> list[_PdfTextBox]:
    """Extract individual tagged text-show bounding boxes from page 1."""

    from pypdf._text_extraction._layout_mode._fixed_width_page import (
        TextStateManager,
        recurse_to_target_op,
        resolve_font,
    )
    from pypdf.generic import ContentStream

    content = ContentStream(page["/Contents"].get_object(), page.pdf, "bytes")
    operations = content.operations
    _validate_graphics_states(page, operations)
    marks = _text_show_marks(operations)
    operation_iterator = iter(operations)
    fonts = page._layout_mode_fonts()
    state = TextStateManager()
    text_states: list[Any] = []
    for args, operator in operation_iterator:
        if operator in {b"BT", b"q"}:
            _, values = recurse_to_target_op(
                operation_iterator,
                state,
                b"ET" if operator == b"BT" else b"Q",
                fonts,
                True,
            )
            text_states.extend(values)
        elif operator == b"Tf":
            state.set_font(resolve_font(fonts, args[0]), args[1])
        else:
            state.set_state_param(operator, args)
    if len(text_states) != len(marks):
        raise ValueError("text-show and marked-content inventories disagree")

    result: list[_PdfTextBox] = []
    for value, mark in zip(text_states, marks, strict=True):
        text = value.text.strip()
        if not text:
            continue
        if not mark.black_fill:
            raise _PdfLayoutError("page 1 text is not painted in reviewed black")
        transform = tuple(float(item) for item in value.transform)
        if (
            value.rotated
            or value.flip_vertical
            or len(transform) != 6
            or not all(math.isfinite(item) for item in transform)
            or transform[0] <= 0
            or transform[3] <= 0
            or abs(transform[1]) > _MATRIX_TOLERANCE
            or abs(transform[2]) > _MATRIX_TOLERANCE
            or not value.font.interpretable
        ):
            raise ValueError("page text uses unsupported geometry")
        x0, x1 = sorted((float(value.tx), float(value.displaced_tx)))
        y0, y1 = sorted((float(value.ty), float(value.ty) + float(value.font_height)))
        if not all(math.isfinite(item) for item in (x0, y0, x1, y1)):
            raise ValueError("page text has non-finite geometry")
        if x1 - x0 <= _MATRIX_TOLERANCE or y1 - y0 <= _MATRIX_TOLERANCE:
            raise _PdfLayoutError("page 1 text has an empty bounding box")
        result.append(
            _PdfTextBox(
                text=text,
                box=_PdfBox(x0, y0, x1, y1),
                tag=mark.tag,
                black_fill=mark.black_fill,
            )
        )
    return result


def _reviewed_grid_rows(rectangles: list[_PdfRectangle]) -> list[_PdfGridRow]:
    vertical = [
        rectangle.box
        for rectangle in rectangles
        if rectangle.reviewed_grid_paint
        and rectangle.axis_aligned
        and 0 < rectangle.box.width <= _GRID_RULE_MAX_THICKNESS
        and _GRID_ROW_MIN_HEIGHT <= rectangle.box.height <= _GRID_ROW_MAX_HEIGHT
    ]
    horizontal = [
        rectangle.box
        for rectangle in rectangles
        if rectangle.reviewed_grid_paint
        and rectangle.axis_aligned
        and 0 < rectangle.box.height <= _GRID_RULE_MAX_THICKNESS
        and rectangle.box.width >= 20
    ]

    groups: list[dict[str, Any]] = []
    for rule in sorted(vertical, key=lambda item: (item.y0, item.y1, item.x0)):
        group = next(
            (
                candidate
                for candidate in groups
                if abs(candidate["y0"] - rule.y0) <= _GEOMETRY_TOLERANCE
                and abs(candidate["y1"] - rule.y1) <= _GEOMETRY_TOLERANCE
            ),
            None,
        )
        if group is None:
            group = {"y0": rule.y0, "y1": rule.y1, "xs": []}
            groups.append(group)
        group["xs"].append((rule.x0 + rule.x1) / 2)

    rows: list[_PdfGridRow] = []
    for group in groups:
        boundaries = _clustered(group["xs"], tolerance=_GEOMETRY_TOLERANCE)
        if len(boundaries) != 12:
            continue
        year_widths = [
            boundaries[index + 1] - boundaries[index] for index in range(1, 11)
        ]
        if (
            min(year_widths, default=0) <= 0
            or max(year_widths, default=0) - min(year_widths, default=0)
            > _BOX_TOLERANCE
        ):
            continue
        y0 = float(group["y0"])
        y1 = float(group["y1"])
        covered = True
        for left, right in zip(boundaries, boundaries[1:]):
            for edge in (y0, y1):
                if not any(
                    abs((rule.y0 + rule.y1) / 2 - edge) <= _GEOMETRY_TOLERANCE
                    and rule.x0 <= left + _BOX_TOLERANCE
                    and rule.x1 >= right - _BOX_TOLERANCE
                    for rule in horizontal
                ):
                    covered = False
                    break
            if not covered:
                break
        if not covered:
            continue
        rows.append(
            _PdfGridRow(
                cells=tuple(
                    _PdfBox(left, y0, right, y1)
                    for left, right in zip(boundaries, boundaries[1:])
                )
            )
        )
    return rows


def _text_lines(tokens: list[_PdfTextBox]) -> list[list[_PdfTextBox]]:
    groups: list[dict[str, Any]] = []
    for token in sorted(tokens, key=lambda item: (-item.box.y0, item.box.x0)):
        group = next(
            (
                candidate
                for candidate in groups
                if abs(candidate["y"] - token.box.y0) <= _GEOMETRY_TOLERANCE
            ),
            None,
        )
        if group is None:
            group = {"y": token.box.y0, "tokens": []}
            groups.append(group)
        group["tokens"].append(token)
    return [sorted(group["tokens"], key=lambda item: item.box.x0) for group in groups]


def _aligned_grid_row(
    tokens: list[_PdfTextBox], grid_rows: list[_PdfGridRow]
) -> _PdfGridRow | None:
    matches: list[_PdfGridRow] = []
    for row in grid_rows:
        indexes: list[int] = []
        for token in tokens:
            containing = [
                index
                for index, cell in enumerate(row.cells)
                if token.box.inside(cell, tolerance=_BOX_TOLERANCE)
            ]
            if len(containing) != 1:
                break
            indexes.append(containing[0])
        else:
            if indexes == list(range(11)):
                matches.append(row)
    return matches[0] if len(matches) == 1 else None


def _grid_row_contains_only(
    all_tokens: list[_PdfTextBox],
    expected_tokens: list[_PdfTextBox],
    row: _PdfGridRow,
) -> bool:
    for cell, expected in zip(row.cells, expected_tokens, strict=True):
        intersecting = [token for token in all_tokens if token.box.intersects(cell)]
        if len(intersecting) != 1 or intersecting[0] is not expected:
            return False
    return True


def _reviewed_clip(clip: tuple[_PdfRectangle, ...] | None) -> bool:
    if clip is None or len(clip) != 1 or not clip[0].axis_aligned:
        return False
    box = clip[0].box
    return all(
        abs(actual - expected) <= _GEOMETRY_TOLERANCE
        for actual, expected in zip(
            (box.x0, box.y0, box.x1, box.y1),
            (
                _EXPECTED_CLIP_BOX.x0,
                _EXPECTED_CLIP_BOX.y0,
                _EXPECTED_CLIP_BOX.x1,
                _EXPECTED_CLIP_BOX.y1,
            ),
            strict=True,
        )
    )


@functools.lru_cache(maxsize=32)
def _sba_pdf_geometry(
    raw: bytes, *, series: str
) -> tuple[_SbaPdfGeometry | None, str | None]:
    # A pure function of the PDF bytes, and the answer is immutable. The 87 SBA
    # witnesses in the chain on 2026-11-02 share one ZIP archive, so one
    # verification replay parsed the same three PDFs 86 times each.
    spec = _spec(series)
    if not raw.startswith(b"%PDF-"):
        return _layout_refusal("response does not start with %PDF-")
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        return None, f"{PARSER_REFUSAL} pypdf is not installed"

    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            return _layout_refusal("PDF is encrypted")
        page_count = len(reader.pages)
        if page_count != spec.page_count:
            return _layout_refusal(
                f"expected {spec.page_count} pages for {series}, found {page_count}"
            )
        page = reader.pages[0]
        root = reader.trailer["/Root"]
        if (page.rotation or 0) != 0:
            return _layout_refusal("page 1 rotation changed")
        if page.get("/Annots") is not None:
            return _layout_refusal("page 1 annotations are not allowed")
        if page.get("/Group") is not None:
            return _layout_refusal("page 1 transparency groups are not allowed")
        if root.get("/OCProperties") is not None:
            return _layout_refusal("PDF optional-content configuration is not allowed")
        media_box = _box(page.mediabox)
        if media_box != _EXPECTED_PAGE_BOX:
            return _layout_refusal("page 1 media box must remain 0 0 1008 612")
        crop_box = _box(page.cropbox)
        if crop_box != media_box:
            return _layout_refusal("page 1 crop box must match its media box")
        page_bounds = _PdfBox(*media_box)
        rectangles, clips = _page_rectangles(page)
        if any(
            not rectangle.box.inside(page_bounds, tolerance=_GEOMETRY_TOLERANCE)
            for rectangle in rectangles
        ):
            return _layout_refusal("page 1 drawing extends outside its page bounds")
        if any(not _reviewed_clip(clip) for clip in clips):
            return _layout_refusal("page 1 uses an unreviewed clipping path")
        grid_rows = _reviewed_grid_rows(rectangles)
        if not grid_rows:
            return _layout_refusal("page 1 has no reviewed table grid")
        tokens = _page_text_boxes(page)
        if any(
            not token.box.inside(page_bounds, tolerance=_GEOMETRY_TOLERANCE)
            for token in tokens
        ):
            return _layout_refusal("page 1 text extends outside its page bounds")
        mark_info = root.get("/MarkInfo")
        struct_tree = root.get("/StructTreeRoot")
        if hasattr(struct_tree, "get_object"):
            struct_tree = struct_tree.get_object()
        if (
            not isinstance(mark_info, Mapping)
            or bool(mark_info.get("/Marked")) is not True
            or not isinstance(struct_tree, Mapping)
            or struct_tree.get("/Type") != "/StructTreeRoot"
            or not isinstance(page.get("/StructParents"), int)
        ):
            return _layout_refusal("page 1 is not a reviewed tagged table")
        text = page.extract_text(extraction_mode="layout")
    except _PdfLayoutError as exc:
        return _layout_refusal(str(exc))
    except (ImportError, AttributeError):
        return None, f"{PARSER_REFUSAL} pypdf geometric extraction is unavailable"
    except Exception:
        return _layout_refusal("strict PDF parsing failed")
    if not text or not text.strip():
        return _layout_refusal("page 1 has no extractable text")

    lines = _text_lines(tokens)
    header_lines = [
        line
        for line in lines
        if len(line) == 11
        and line[0].text == "Program"
        and all(re.fullmatch(r"\d{4}", token.text) for token in line[1:])
    ]
    if len(header_lines) != 1:
        return _layout_refusal(
            f"expected one geometric ten-year Program header, found {len(header_lines)}"
        )
    header = header_lines[0]
    if header[0].tag != "/TH" or any(token.tag != "/TD" for token in header[1:]):
        return _layout_refusal("Program header tags do not match the reviewed table")
    if any(not token.black_fill for token in header):
        return _layout_refusal("Program header text is not painted in reviewed black")
    if any(
        abs(token.box.height - _REVIEWED_TABLE_TEXT_HEIGHT)
        > _TABLE_TEXT_HEIGHT_TOLERANCE
        for token in header
    ):
        return _layout_refusal("Program header text height changed")
    header_grid = _aligned_grid_row(header, grid_rows)
    if header_grid is None:
        return _layout_refusal(
            "Program header bounding boxes do not align with one 11-column grid row"
        )
    if not _grid_row_contains_only(tokens, header, header_grid):
        return _layout_refusal("Program header grid cells contain unexpected text")
    years = tuple(int(token.text) for token in header[1:])
    if years != tuple(range(years[0], years[0] + 10)):
        return _layout_refusal("fiscal-year header is not ten consecutive years")

    value_re = _USD_RE if spec.unit == "USD" else _PERCENT_RE
    disaster_lines = [
        line
        for line in lines
        if len(line) == 11
        and line[0].text == "Disaster"
        and all(value_re.fullmatch(token.text) for token in line[1:])
    ]
    if len(disaster_lines) != 1:
        return _layout_refusal(
            f"expected one geometric Disaster value row, found {len(disaster_lines)}"
        )
    disaster = disaster_lines[0]
    if disaster[0].tag != "/TH" or any(token.tag != "/TD" for token in disaster[1:]):
        return _layout_refusal("Disaster row tags do not match the reviewed table")
    if any(not token.black_fill for token in disaster):
        return _layout_refusal("Disaster row text is not painted in reviewed black")
    if any(
        abs(token.box.height - _REVIEWED_TABLE_TEXT_HEIGHT)
        > _TABLE_TEXT_HEIGHT_TOLERANCE
        for token in disaster
    ):
        return _layout_refusal("Disaster row text height changed")
    disaster_grid = _aligned_grid_row(disaster, grid_rows)
    if disaster_grid is None:
        return _layout_refusal(
            "Disaster row bounding boxes do not align with one 11-column grid row"
        )
    if not _grid_row_contains_only(tokens, disaster, disaster_grid):
        return _layout_refusal("Disaster row grid cells contain unexpected text")
    for header_cell, disaster_cell in zip(
        header_grid.cells, disaster_grid.cells, strict=True
    ):
        if (
            abs(header_cell.x0 - disaster_cell.x0) > _BOX_TOLERANCE
            or abs(header_cell.x1 - disaster_cell.x1) > _BOX_TOLERANCE
        ):
            return _layout_refusal(
                "Program header and Disaster row columns do not align"
            )

    return (
        _SbaPdfGeometry(
            text=text,
            header_years=years,
            printed_values=tuple(token.text for token in disaster[1:]),
        ),
        None,
    )


def sba_pdf_text(raw: bytes, *, series: str) -> tuple[str | None, str | None]:
    """Extract page-one layout text while enforcing the reviewed PDF shape."""

    geometry, refusal = _sba_pdf_geometry(raw, series=series)
    if refusal is not None:
        return None, refusal
    assert geometry is not None
    return geometry.text, None


def parse_sba_loan_performance_text(
    text: str,
    *,
    series: str,
    fiscal_year: int,
    _geometric_printed_value: str | None = None,
) -> tuple[SbaLoanPerformanceCell | None, str | None]:
    """Validate page text; PDF callers supply the geometry-selected value."""

    if type(fiscal_year) is not int:
        raise TypeError("fiscal_year must be an integer")
    spec = _spec(series)
    lines = _normalized_lines(text)
    collapsed = " ".join(text.split())

    title_count = lines.count(spec.title)
    if title_count != 1:
        return _layout_refusal(
            f"expected one exact title {spec.title!r}, found {title_count}"
        )

    headers = [match for line in lines if (match := _HEADER_RE.fullmatch(line))]
    if len(headers) != 1:
        return _layout_refusal(
            f"expected one ten-year Program header, found {len(headers)}"
        )
    fiscal_year_label_count = lines.count("Fiscal Year")
    if fiscal_year_label_count != 1:
        return _layout_refusal(
            f"expected one exact 'Fiscal Year' label, found {fiscal_year_label_count}"
        )
    years = tuple(int(value) for value in headers[0].group(1).split())
    if years != tuple(range(years[0], years[0] + 10)):
        return _layout_refusal("fiscal-year header is not ten consecutive years")
    header_line = f"Program {' '.join(str(year) for year in years)}"
    if lines[:3] != [spec.title, "Fiscal Year", header_line]:
        return _layout_refusal(
            "title, Fiscal Year label, and Program header are not in the reviewed order"
        )

    section_indexes = [index for index, line in enumerate(lines) if line == "Disaster"]
    row_indexes = [
        index for index, line in enumerate(lines) if line.startswith("Disaster ")
    ]
    if len(section_indexes) != 1 or len(row_indexes) != 1:
        return _layout_refusal(
            "expected one Disaster section and one Disaster row, found "
            f"{len(section_indexes)} and {len(row_indexes)}"
        )
    if row_indexes[0] != section_indexes[0] + 1:
        return _layout_refusal("Disaster row does not immediately follow its section")

    row = lines[row_indexes[0]].split()
    values = row[1:]
    if len(values) != len(years):
        return _layout_refusal(
            f"Disaster row has {len(values)} values for {len(years)} headers"
        )
    value_re = _USD_RE if spec.unit == "USD" else _PERCENT_RE
    invalid = next((value for value in values if not value_re.fullmatch(value)), None)
    if invalid is not None:
        return _layout_refusal(
            f"Disaster {spec.unit} row contains invalid token {invalid!r}"
        )

    for label, marker in (
        ("unit definition", spec.definition_marker),
        ("revision", spec.revision_marker),
    ):
        marker_count = collapsed.count(marker)
        if marker_count != 1:
            return _layout_refusal(
                f"expected one exact {label} statement, found {marker_count}"
            )

    footer_lead_count = collapsed.count(spec.footer_lead)
    if footer_lead_count != 1:
        return _layout_refusal(
            "expected one exact fiscal-year completion lead, found "
            f"{footer_lead_count}"
        )
    footer_start = collapsed.index(spec.footer_lead)
    definition_start = collapsed.index(spec.definition_marker)
    if definition_start <= footer_start:
        return _layout_refusal(
            "fiscal-year completion statement does not precede the unit definition"
        )
    footer_statement = collapsed[footer_start:definition_start].strip()
    partial_re = re.compile(re.escape(spec.footer_lead) + _PARTIAL_TAIL_RE.pattern)
    partial_match = partial_re.fullmatch(footer_statement)
    if footer_statement == spec.footer_lead:
        completion_status: SbaCompletionStatus = COMPLETION_COMPLETED
        partial_year = None
        try:
            report_as_of = dt.date(years[-1], 9, 30)
        except ValueError:
            return _layout_refusal("completed fiscal year is not a valid date year")
    elif partial_match is not None:
        completion_status = COMPLETION_PARTIAL
        partial_year = int(partial_match.group("year"))
        date_text = partial_match.group("date")
        try:
            report_as_of = dt.datetime.strptime(date_text, "%m/%d/%Y").date()
        except ValueError:
            return _layout_refusal("quarter-to-date statement has an invalid date")
        if (report_as_of.month, report_as_of.day) not in _QUARTER_ENDS:
            return _layout_refusal("report as-of date is not a quarter end")
        as_of_fiscal_year = report_as_of.year + (report_as_of.month >= 10)
        if partial_year != as_of_fiscal_year or partial_year != years[-1]:
            return _layout_refusal(
                "quarter-to-date fiscal year does not match the report as-of date "
                "and final header"
            )
    else:
        return _layout_refusal(
            "fiscal-year completion statement is neither the reviewed completed "
            "nor quarter-to-date form"
        )

    if fiscal_year not in years:
        return _layout_refusal(
            f"fiscal year {fiscal_year} is absent from the ten-year header"
        )
    if completion_status == COMPLETION_PARTIAL and fiscal_year == partial_year:
        return (
            None,
            f"{PARTIAL_REFUSAL} fiscal year {fiscal_year} is quarter-to-date "
            f"as of {report_as_of.isoformat()}",
        )

    if _geometric_printed_value is None:
        return _layout_refusal("value-to-year mapping requires validated PDF geometry")
    printed_value = _geometric_printed_value
    if not value_re.fullmatch(printed_value) or printed_value not in values:
        return _layout_refusal(
            "geometric Disaster value is absent from the validated text row"
        )
    if spec.unit == "USD":
        parsed_value: int | float = int(printed_value[1:].replace(",", ""))
    else:
        parsed_value = float(printed_value[:-1])
    return (
        SbaLoanPerformanceCell(
            series=series,
            fiscal_year=fiscal_year,
            value=parsed_value,
            unit=spec.unit,
            printed_value=printed_value,
            table_title=spec.title,
            report_as_of=report_as_of.isoformat(),
            completion_status=completion_status,
            partial_fiscal_year=partial_year,
            header_years=years,
        ),
        None,
    )


def parse_sba_loan_performance_pdf(
    raw: bytes, *, series: str, fiscal_year: int
) -> tuple[SbaLoanPerformanceCell | None, str | None]:
    """Parse an official PDF and bind the result to the member-byte hash."""

    geometry, refusal = _sba_pdf_geometry(raw, series=series)
    if refusal is not None:
        return None, refusal
    assert geometry is not None
    geometric_printed_value = (
        geometry.printed_values[geometry.header_years.index(fiscal_year)]
        if fiscal_year in geometry.header_years
        else None
    )
    cell, refusal = parse_sba_loan_performance_text(
        geometry.text,
        series=series,
        fiscal_year=fiscal_year,
        _geometric_printed_value=geometric_printed_value,
    )
    if refusal is not None:
        return None, refusal
    assert cell is not None
    if cell.header_years != geometry.header_years:
        return _layout_refusal("layout text and geometric fiscal-year headers disagree")
    return (
        replace(
            cell,
            pdf_sha256=hashlib.sha256(raw).hexdigest(),
        ),
        None,
    )
