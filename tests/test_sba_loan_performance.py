from __future__ import annotations

import base64
import dataclasses
import hashlib
import io
import pathlib
import sys
from collections.abc import Callable
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sba_loan_performance as sba  # noqa: E402

FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "sba_loan_performance"
FIXTURES = {
    sba.CHARGE_OFF_AMOUNT_SERIES: (
        "WDS_ChargeOffAmount_Report_20250630.pdf",
        107_076,
        "b3f352425adcc3304cbcc406d63a2ced149bc8224f3b604c2b47403edc9070f3",
        299_971_326,
        "USD",
        "$299,971,326",
    ),
    sba.CHARGE_OFF_RATE_SERIES: (
        "WDS_ChargeOffRates_Report_20250630.pdf",
        167_134,
        "23ab3dc1d37dc08be200b8076d07371b1ac901730e1828a697278bf279a1d762",
        3.06,
        "percent",
        "3.06%",
    ),
    sba.POST_CHARGE_OFF_RECOVERY_SERIES: (
        "WDS_PostChargeOffRecovery_Report_20250630.pdf",
        109_817,
        "09616e8af327a6ea8e3bbc340e44392bbead98e581a9f85a7de99ef8b81e380f",
        126_510_000,
        "USD",
        "$126,510,000",
    ),
}
ADVERSARIAL_FIXTURE = (
    "adversarial-ungridded.pdf.b64",
    2_481,
    "5c8a3b33d13154b13c66a102490db767780f4f603ed3e7bb2f8621c674a442dd",
)


def fixture_bytes(series: str) -> bytes:
    return (FIXTURE_ROOT / FIXTURES[series][0]).read_bytes()


def adversarial_fixture_bytes() -> bytes:
    encoded = (FIXTURE_ROOT / ADVERSARIAL_FIXTURE[0]).read_bytes()
    return base64.b64decode(encoded.strip(), validate=True)


def rewritten_pdf(raw: bytes, mutate: Callable[[Any, Any], None]) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(raw), strict=True)
    writer = PdfWriter(clone_from=reader)
    mutate(writer.pages[0], writer)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def completed_q4_pdf_bytes(series: str) -> bytes:
    from pypdf.generic import ByteStringObject, ContentStream

    spec = sba.SBA_REPORT_SPECS[series]
    footer_replacements = 0

    def complete_footer(page: Any, writer: Any) -> None:
        nonlocal footer_replacements
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        for args, operator in content.operations:
            if operator != b"Tj" or len(args) != 1:
                continue
            printed = bytes(args[0])
            if printed.startswith(spec.footer_lead.encode()):
                args[0] = ByteStringObject(spec.footer_lead.encode() + b" ")
                footer_replacements += 1
            elif b"06/30/2025." in printed:
                args[0] = ByteStringObject(b"")
        page.replace_contents(content)

    rewritten = rewritten_pdf(fixture_bytes(series), complete_footer)
    assert footer_replacements == 1
    return rewritten


@pytest.mark.parametrize("series", FIXTURES)
def test_official_pdf_fixture_bytes_match_reviewed_pins(series: str) -> None:
    _, expected_size, expected_sha256, *_ = FIXTURES[series]
    raw = fixture_bytes(series)

    assert len(raw) == expected_size
    assert hashlib.sha256(raw).hexdigest() == expected_sha256


def test_adversarial_ungridded_pdf_fixture_matches_reviewed_pin() -> None:
    _, expected_size, expected_sha256 = ADVERSARIAL_FIXTURE
    raw = adversarial_fixture_bytes()

    assert len(raw) == expected_size
    assert hashlib.sha256(raw).hexdigest() == expected_sha256


@pytest.mark.parametrize("series", FIXTURES)
def test_real_official_pdf_parses_exact_disaster_fy2024_cell(series: str) -> None:
    _, _, expected_sha256, expected_value, expected_unit, printed = FIXTURES[series]

    cell, refusal = sba.parse_sba_loan_performance_pdf(
        fixture_bytes(series), series=series, fiscal_year=2024
    )

    assert refusal is None
    assert cell is not None
    assert cell.value == expected_value
    assert cell.unit == expected_unit
    assert cell.printed_value == printed
    assert cell.report_as_of == "2025-06-30"
    assert cell.completion_status == sba.COMPLETION_PARTIAL
    assert cell.partial_fiscal_year == 2025
    assert cell.header_years == tuple(range(2016, 2026))
    assert cell.pdf_sha256 == expected_sha256


@pytest.mark.parametrize(
    ("series", "expected_value", "expected_unit", "printed"),
    (
        (sba.CHARGE_OFF_AMOUNT_SERIES, 107_714_599, "USD", "$107,714,599"),
        (sba.CHARGE_OFF_RATE_SERIES, 0.90, "percent", "0.90%"),
        (
            sba.POST_CHARGE_OFF_RECOVERY_SERIES,
            85_429_990,
            "USD",
            "$85,429,990",
        ),
    ),
)
def test_completed_q4_footer_parses_latest_fiscal_year(
    series: str,
    expected_value: int | float,
    expected_unit: str,
    printed: str,
) -> None:
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        completed_q4_pdf_bytes(series),
        series=series,
        fiscal_year=2025,
    )

    assert refusal is None
    assert cell is not None
    assert cell.value == expected_value
    assert cell.unit == expected_unit
    assert cell.printed_value == printed
    assert cell.report_as_of == "2025-09-30"
    assert cell.completion_status == sba.COMPLETION_COMPLETED
    assert cell.partial_fiscal_year is None
    assert cell.header_years == tuple(range(2016, 2026))


def test_real_pdf_refuses_current_partial_year_with_literal_message() -> None:
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES),
        series=sba.CHARGE_OFF_AMOUNT_SERIES,
        fiscal_year=2025,
    )

    assert cell is None
    assert refusal == (
        "SBA PERIOD PARTIAL (refusing): fiscal year 2025 is quarter-to-date "
        "as of 2025-06-30"
    )


def test_real_pdf_refuses_wrong_table_identity_with_literal_message() -> None:
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES),
        series=sba.POST_CHARGE_OFF_RECOVERY_SERIES,
        fiscal_year=2024,
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): expected one exact title "
        "'Table 7 - Post-Charge Off Recovery Amount by Program', found 0"
    )


def test_text_only_parser_refuses_value_to_year_mapping() -> None:
    text, refusal = sba.sba_pdf_text(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES),
        series=sba.CHARGE_OFF_AMOUNT_SERIES,
    )
    assert refusal is None and text is not None

    cell, refusal = sba.parse_sba_loan_performance_text(
        text, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): value-to-year mapping requires "
        "validated PDF geometry"
    )


def test_non_pdf_refusal_is_literal() -> None:
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        b"not a PDF",
        series=sba.CHARGE_OFF_AMOUNT_SERIES,
        fiscal_year=2024,
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): response does not start with %PDF-"
    )


def test_ungridded_pdf_probe_is_refused_with_literal_message() -> None:
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        adversarial_fixture_bytes(),
        series=sba.CHARGE_OFF_AMOUNT_SERIES,
        fiscal_year=2024,
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 has no reviewed table grid"
    )


def test_pdf_refuses_crop_box_that_does_not_match_page_bounds() -> None:
    from pypdf.generic import RectangleObject

    def crop_page(page: Any, writer: Any) -> None:
        del writer
        page.cropbox = RectangleObject((0, 0, 900, 612))

    raw = rewritten_pdf(fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), crop_page)
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 crop box must match its media box"
    )


def test_pdf_refuses_value_bounding_box_outside_its_year_column() -> None:
    from pypdf.generic import ContentStream, FloatObject, NameObject

    def shift_value(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        for index, (args, operator) in enumerate(content.operations):
            if operator == b"Tj" and b"$299,971,326" in args[0]:
                offset_args, offset_operator = content.operations[index - 1]
                assert offset_operator == b"Td"
                offset_args[0] = FloatObject(float(offset_args[0]) - 30)
                restore_args, restore_operator = content.operations[index + 3]
                assert restore_operator == b"Td"
                restore_args[0] = FloatObject(float(restore_args[0]) + 30)
                page[NameObject("/Contents")] = content
                return
        raise AssertionError("reviewed FY2024 value text operator is absent")

    raw = rewritten_pdf(fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), shift_value)
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): Disaster row bounding boxes do not "
        "align with one 11-column grid row"
    )


def test_pdf_refuses_invisible_geometrically_aligned_value() -> None:
    from pypdf.generic import ByteStringObject, ContentStream, NameObject, NumberObject

    def hide_replacement_value(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        for index, (args, operator) in enumerate(content.operations):
            if operator == b"Tj" and b"$299,971,326" in args[0]:
                args[0] = ByteStringObject(b"$999,999,999 ")
                content.operations[index : index + 1] = [
                    ([NumberObject(3)], b"Tr"),
                    (args, operator),
                    ([NumberObject(0)], b"Tr"),
                ]
                page[NameObject("/Contents")] = content
                return
        raise AssertionError("reviewed FY2024 value text operator is absent")

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), hide_replacement_value
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 uses non-fill text rendering mode"
    )


def test_pdf_refuses_transparent_graphics_state() -> None:
    from pypdf.generic import FloatObject, NameObject

    def make_page_transparent(page: Any, writer: Any) -> None:
        del writer
        state = page["/Resources"]["/ExtGState"]["/GS0"].get_object()
        state[NameObject("/CA")] = FloatObject(0)
        state[NameObject("/ca")] = FloatObject(0)

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), make_page_transparent
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 graphics state /GS0 is not opaque"
    )


def test_pdf_refuses_white_geometrically_aligned_value() -> None:
    from pypdf.generic import ByteStringObject, ContentStream, FloatObject, NameObject

    def whiten_replacement_value(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        for index, (args, operator) in enumerate(content.operations):
            if operator == b"Tj" and b"$299,971,326" in args[0]:
                args[0] = ByteStringObject(b"$999,999,999 ")
                content.operations[index : index + 1] = [
                    ([FloatObject(1), FloatObject(1), FloatObject(1)], b"rg"),
                    (args, operator),
                    ([FloatObject(0), FloatObject(0), FloatObject(0)], b"rg"),
                ]
                page[NameObject("/Contents")] = content
                return
        raise AssertionError("reviewed FY2024 value text operator is absent")

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), whiten_replacement_value
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 text is not painted in "
        "reviewed black"
    )


def test_pdf_refuses_clipping_path_that_hides_page_content() -> None:
    from pypdf.generic import ContentStream, FloatObject, NameObject

    def narrow_first_clip(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        for index, (args, operator) in enumerate(content.operations):
            if operator == b"W*":
                rectangle_args, rectangle_operator = content.operations[index - 1]
                assert rectangle_operator == b"re"
                rectangle_args[2] = FloatObject(1)
                page[NameObject("/Contents")] = content
                return
        raise AssertionError("reviewed page clipping path is absent")

    raw = rewritten_pdf(fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), narrow_first_clip)
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 uses an unreviewed clipping path"
    )


def test_pdf_refuses_rectangle_painted_over_geometric_value() -> None:
    from pypdf.generic import ByteStringObject, ContentStream, FloatObject, NameObject

    def cover_replacement_value(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        for args, operator in content.operations:
            if operator == b"Tj" and b"$299,971,326" in args[0]:
                args[0] = ByteStringObject(b"$999,999,999 ")
                break
        else:
            raise AssertionError("reviewed FY2024 value text operator is absent")
        content.operations.extend(
            [
                ([], b"q"),
                ([FloatObject(1), FloatObject(1), FloatObject(1)], b"rg"),
                (
                    [
                        FloatObject(800),
                        FloatObject(170),
                        FloatObject(65),
                        FloatObject(16),
                    ],
                    b"re",
                ),
                ([], b"f"),
                ([], b"Q"),
            ]
        )
        page[NameObject("/Contents")] = content

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), cover_replacement_value
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 paints over reviewed text"
    )


def test_pdf_refuses_dark_background_behind_geometric_value() -> None:
    from pypdf.generic import ContentStream, FloatObject, NameObject

    def darken_value_background(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        first_grid_paint = next(
            index
            for index, (args, operator) in enumerate(content.operations)
            if operator == b"B*"
            and content.operations[index - 1][1] == b"re"
            and (
                float(content.operations[index - 1][0][2]) <= 1
                or float(content.operations[index - 1][0][3]) <= 1
            )
        )
        insertion_index = next(
            index
            for index in range(first_grid_paint, -1, -1)
            if content.operations[index][1] == b"q"
        )
        content.operations[insertion_index:insertion_index] = [
            ([], b"q"),
            ([FloatObject(0), FloatObject(0), FloatObject(0)], b"rg"),
            (
                [
                    FloatObject(800),
                    FloatObject(170),
                    FloatObject(65),
                    FloatObject(16),
                ],
                b"re",
            ),
            ([], b"f"),
            ([], b"Q"),
        ]
        page[NameObject("/Contents")] = content

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), darken_value_background
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 uses unreviewed table "
        "background paint"
    )


def test_pdf_refuses_additional_text_inside_geometric_value_cell() -> None:
    from pypdf.generic import ByteStringObject, ContentStream, FloatObject, NameObject

    def add_second_visible_value(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        content.operations.extend(
            [
                ([], b"q"),
                ([], b"BT"),
                ([FloatObject(0), FloatObject(0), FloatObject(0)], b"rg"),
                ([NameObject("/TT0"), FloatObject(1)], b"Tf"),
                (
                    [
                        FloatObject(4),
                        FloatObject(0),
                        FloatObject(0),
                        FloatObject(4),
                        FloatObject(809.7),
                        FloatObject(169),
                    ],
                    b"Tm",
                ),
                ([ByteStringObject(b"$999,999,999 ")], b"Tj"),
                ([], b"ET"),
                ([], b"Q"),
            ]
        )
        page[NameObject("/Contents")] = content

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), add_second_visible_value
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): Disaster row grid cells contain "
        "unexpected text"
    )


def test_pdf_refuses_white_table_grid() -> None:
    from pypdf.generic import ContentStream, FloatObject, NameObject

    def whiten_grid(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        changed = 0
        for args, operator in content.operations:
            if operator in {b"rg", b"RG"} and tuple(map(float, args)) == (
                0.569,
                0.569,
                0.569,
            ):
                args[:] = [FloatObject(1), FloatObject(1), FloatObject(1)]
                changed += 1
        assert changed == 832
        page[NameObject("/Contents")] = content

    raw = rewritten_pdf(fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), whiten_grid)
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 uses unreviewed table "
        "background paint"
    )


def test_pdf_refuses_printable_annotation_over_geometric_value() -> None:
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        NumberObject,
        RectangleObject,
    )

    def cover_value_with_annotation(page: Any, writer: Any) -> None:
        appearance = DecodedStreamObject()
        appearance.set_data(b"q 1 1 1 rg 0 0 65 16 re f Q")
        appearance.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): RectangleObject((0, 0, 65, 16)),
                NameObject("/Resources"): DictionaryObject(),
            }
        )
        appearance_ref = writer._add_object(appearance)
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Square"),
                NameObject("/Rect"): RectangleObject((800, 170, 865, 186)),
                NameObject("/F"): NumberObject(4),
                NameObject("/AP"): DictionaryObject({NameObject("/N"): appearance_ref}),
            }
        )
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), cover_value_with_annotation
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 annotations are not allowed"
    )


def test_pdf_refuses_hidden_optional_content_value() -> None:
    from pypdf.generic import (
        ArrayObject,
        ByteStringObject,
        ContentStream,
        DictionaryObject,
        NameObject,
        TextStringObject,
    )

    def hide_replacement_value(page: Any, writer: Any) -> None:
        content = ContentStream(page["/Contents"].get_object(), writer, "bytes")
        for target_index, (args, operator) in enumerate(content.operations):
            if operator == b"Tj" and b"$299,971,326" in args[0]:
                args[0] = ByteStringObject(b"$999,999,999 ")
                break
        else:
            raise AssertionError("reviewed FY2024 value text operator is absent")
        start_index = next(
            index
            for index in range(target_index, -1, -1)
            if content.operations[index][1] == b"BDC"
            and str(content.operations[index][0][0]) == "/TD"
        )
        end_index = next(
            index
            for index in range(target_index, len(content.operations))
            if content.operations[index][1] == b"EMC"
        )

        optional_group = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/OCG"),
                NameObject("/Name"): TextStringObject("Hidden value"),
            }
        )
        optional_group_ref = writer._add_object(optional_group)
        writer.root_object[NameObject("/OCProperties")] = DictionaryObject(
            {
                NameObject("/OCGs"): ArrayObject([optional_group_ref]),
                NameObject("/D"): DictionaryObject(
                    {NameObject("/OFF"): ArrayObject([optional_group_ref])}
                ),
            }
        )
        properties = page["/Resources"].get("/Properties", DictionaryObject())
        properties[NameObject("/OC1")] = optional_group_ref
        page["/Resources"][NameObject("/Properties")] = properties
        content.operations.insert(
            start_index,
            ([NameObject("/OC"), NameObject("/OC1")], b"BDC"),
        )
        content.operations.insert(end_index + 2, ([], b"EMC"))
        page[NameObject("/Contents")] = content

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), hide_replacement_value
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): PDF optional-content configuration "
        "is not allowed"
    )


def test_pdf_refuses_page_transparency_group() -> None:
    from pypdf.generic import DictionaryObject, NameObject

    def add_transparency_group(page: Any, writer: Any) -> None:
        del writer
        page[NameObject("/Group")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/Transparency"),
                NameObject("/CS"): NameObject("/DeviceRGB"),
            }
        )

    raw = rewritten_pdf(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES), add_transparency_group
    )
    cell, refusal = sba.parse_sba_loan_performance_pdf(
        raw, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): page 1 transparency groups are not allowed"
    )


def test_text_parser_refuses_duplicate_header_with_literal_message() -> None:
    text, refusal = sba.sba_pdf_text(
        fixture_bytes(sba.CHARGE_OFF_RATE_SERIES),
        series=sba.CHARGE_OFF_RATE_SERIES,
    )
    assert refusal is None and text is not None
    text += "\nProgram 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025\n"

    cell, refusal = sba.parse_sba_loan_performance_text(
        text, series=sba.CHARGE_OFF_RATE_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): expected one ten-year Program header, found 2"
    )


def test_text_parser_refuses_renamed_fiscal_year_label() -> None:
    text, refusal = sba.sba_pdf_text(
        fixture_bytes(sba.CHARGE_OFF_RATE_SERIES),
        series=sba.CHARGE_OFF_RATE_SERIES,
    )
    assert refusal is None and text is not None
    text = text.replace("Fiscal Year", "Calendar Year", 1)

    cell, refusal = sba.parse_sba_loan_performance_text(
        text, series=sba.CHARGE_OFF_RATE_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): expected one exact 'Fiscal Year' "
        "label, found 0"
    )


def test_text_parser_refuses_title_moved_below_table() -> None:
    series = sba.CHARGE_OFF_RATE_SERIES
    title = sba.SBA_REPORT_SPECS[series].title
    text, refusal = sba.sba_pdf_text(fixture_bytes(series), series=series)
    assert refusal is None and text is not None
    text = text.replace(title, "", 1) + f"\n{title}\n"

    cell, refusal = sba.parse_sba_loan_performance_text(
        text, series=series, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): title, Fiscal Year label, and Program "
        "header are not in the reviewed order"
    )


def test_text_parser_refuses_invalid_unit_token_with_literal_message() -> None:
    text, refusal = sba.sba_pdf_text(
        fixture_bytes(sba.CHARGE_OFF_AMOUNT_SERIES),
        series=sba.CHARGE_OFF_AMOUNT_SERIES,
    )
    assert refusal is None and text is not None
    text = text.replace("$299,971,326", "299971326", 1)

    cell, refusal = sba.parse_sba_loan_performance_text(
        text, series=sba.CHARGE_OFF_AMOUNT_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): Disaster USD row contains invalid "
        "token '299971326'"
    )


def test_text_parser_refuses_missing_completed_year_marker() -> None:
    text, refusal = sba.sba_pdf_text(
        fixture_bytes(sba.POST_CHARGE_OFF_RECOVERY_SERIES),
        series=sba.POST_CHARGE_OFF_RECOVERY_SERIES,
    )
    assert refusal is None and text is not None
    text = text.replace("as of the end of each fiscal year", "year to date", 1)

    cell, refusal = sba.parse_sba_loan_performance_text(
        text, series=sba.POST_CHARGE_OFF_RECOVERY_SERIES, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): expected one exact fiscal-year "
        "completion lead, found 0"
    )


def test_text_parser_refuses_malformed_completion_suffix() -> None:
    series = sba.CHARGE_OFF_AMOUNT_SERIES
    text, refusal = sba.sba_pdf_text(fixture_bytes(series), series=series)
    assert refusal is None and text is not None
    text = text.replace(
        "Since data are not available through the end of the most recent fiscal year",
        "Because recent data remain unavailable",
        1,
    )

    cell, refusal = sba.parse_sba_loan_performance_text(
        text,
        series=series,
        fiscal_year=2024,
        _geometric_printed_value="$299,971,326",
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): fiscal-year completion statement is "
        "neither the reviewed completed nor quarter-to-date form"
    )


def test_text_parser_refuses_changed_recovery_definition() -> None:
    series = sba.POST_CHARGE_OFF_RECOVERY_SERIES
    text, refusal = sba.sba_pdf_text(fixture_bytes(series), series=series)
    assert refusal is None and text is not None
    text = text.replace(
        "after a loan has been charged off",
        "before a loan has been charged off",
        1,
    )

    cell, refusal = sba.parse_sba_loan_performance_text(
        text, series=series, fiscal_year=2024
    )

    assert cell is None
    assert refusal == (
        "SBA PDF LAYOUT DRIFT (refusing): expected one exact unit definition "
        "statement, found 0"
    )


# --- One verification replay parses the same three PDFs many times ---


@pytest.mark.parametrize("series", FIXTURES)
def test_a_kept_geometry_equals_a_fresh_parse(series: str) -> None:
    raw = fixture_bytes(series)
    fresh = sba._sba_pdf_geometry.__wrapped__(raw, series=series)
    assert fresh[0] is not None and fresh[1] is None
    assert sba._sba_pdf_geometry(raw, series=series) == fresh
    assert sba._sba_pdf_geometry(raw, series=series) == fresh


def test_a_kept_refusal_equals_a_fresh_refusal() -> None:
    series = next(iter(FIXTURES))
    raw = adversarial_fixture_bytes()
    fresh = sba._sba_pdf_geometry.__wrapped__(raw, series=series)
    assert fresh[0] is None and fresh[1]
    assert sba._sba_pdf_geometry(raw, series=series) == fresh
    assert sba._sba_pdf_geometry(raw, series=series) == fresh


def test_one_pdf_is_parsed_once_per_series() -> None:
    first, second = list(FIXTURES)[:2]
    raw = fixture_bytes(first)
    sba._sba_pdf_geometry.cache_clear()
    sba._sba_pdf_geometry(raw, series=first)
    for _replay in range(5):
        sba._sba_pdf_geometry(raw, series=first)
    assert sba._sba_pdf_geometry.cache_info().hits == 5
    assert sba._sba_pdf_geometry.cache_info().misses == 1
    # The same bytes under another series get that series' own answer.
    assert sba._sba_pdf_geometry(
        raw, series=second
    ) == sba._sba_pdf_geometry.__wrapped__(raw, series=second)
    assert sba._sba_pdf_geometry.cache_info().misses == 2


def test_a_kept_geometry_cannot_be_changed() -> None:
    series = next(iter(FIXTURES))
    geometry, _refusal = sba._sba_pdf_geometry(fixture_bytes(series), series=series)
    assert geometry is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        geometry.text = "changed"
    assert isinstance(geometry.header_years, tuple)
    assert isinstance(geometry.printed_values, tuple)
