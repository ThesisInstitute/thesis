"""Synthetic VA MMWR workbook builder shared by the resolver tests.

Mirrors the official ``Transformation`` sheet layout observed in every 2026
MMWR file (section title in D2, the ``Reporting through`` identity cell in
D4, headers in J3:L3, the national rating-bundle row in row 5 with formulas
whose cached values are read); the official files are ~3 MB each and stay
out of the repo.
"""

from __future__ import annotations

import io
import zipfile


def build_workbook(
    *,
    pending: float = 600878,
    over_125: float = 69481,
    pct: float | None = None,
    through: str = "Reporting through July 11, 2026",
    sheet_name: str = "Transformation",
    title: str = "Compensation and Pension Rating Bundle Metrics",
    extra_rows: str = "",
) -> bytes:
    """A minimal OOXML workbook with the MMWR Transformation layout."""
    if pct is None:
        pct = over_125 / pending
    strings = [
        title,  # 0
        "National View",  # 1
        "# Pending",  # 2
        "# Pending > 125",  # 3
        "% Pending > 125 days",  # 4
        "Compensation and Pension Rating Bundle",  # 5
        "Total",  # 6
        "Original Entitlement",  # 7
    ]
    shared = "".join(f"<si><t>{s}</t></si>" for s in strings)
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(strings)}" uniqueCount="{len(strings)}">{shared}</sst>'
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="2"><c r="D2" t="s"><v>0</v></c></row>'
        '<row r="3"><c r="D3" t="s"><v>1</v></c><c r="J3" t="s"><v>2</v></c>'
        '<c r="K3" t="s"><v>3</v></c><c r="L3" t="s"><v>4</v></c></row>'
        f'<row r="4"><c r="D4" t="str"><f>Driver!A1</f><v>{through}</v></c></row>'
        '<row r="5"><c r="D5" t="s"><v>5</v></c><c r="I5" t="s"><v>6</v></c>'
        f'<c r="J5"><f>SUM(J6:J7)</f><v>{pending}</v></c>'
        f'<c r="K5"><f>SUM(K6:K7)</f><v>{over_125}</v></c>'
        f'<c r="L5"><f>K5/J5</f><v>{pct}</v></c></row>'
        '<row r="6"><c r="D6" t="s"><v>7</v></c><c r="I6" t="s"><v>6</v></c>'
        '<c r="J6"><f>X</f><v>148609</v></c><c r="K6"><f>X</f><v>31292</v></c>'
        '<c r="L6"><f>X</f><v>0.2105</v></c></row>'
        f"{extra_rows}"
        "</sheetData>"
        '<mergeCells count="3"><mergeCell ref="L3:L4"/><mergeCell ref="K3:K4"/>'
        '<mergeCell ref="J3:J4"/></mergeCells>'
        "</worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="Legend" sheetId="1" r:id="rId1"/>'
        f'<sheet name="{sheet_name}" sheetId="2" r:id="rId2"/></sheets></workbook>'
    )
    rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<Relationships "
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel_type}/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{rel_type}/worksheet" '
        'Target="worksheets/sheet2.xml"/>'
        f'<Relationship Id="rId3" Type="{rel_type}/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
    legend_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="s"><v>1</v></c></row></sheetData>'
        "</worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", legend_xml)
        archive.writestr("xl/worksheets/sheet2.xml", sheet_xml)
    return buffer.getvalue()
