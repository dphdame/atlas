"""[SOFTWARE_TEST FIXTURE — DEMONSTRATES SOFTWARE MECHANICS ONLY, NOT EMPIRICAL FINDINGS]

Rebuilds the binary SOFTWARE_TEST fixtures byte-for-byte:
  data/samples/software_test_teams_multiline.docx  (python-docx)
  data/samples/software_test_survey.xlsx           (hand-written SpreadsheetML)

The Word file mimics a speakerless Microsoft Teams export: every paragraph is a
timestamp followed by line breaks and the spoken text. Its banner sits in the
page header and core properties so it does not become a dialogue turn.

Both builds run entirely in memory and never touch a temporary directory, so
the byte-for-byte rebuild check also works on a read-only filesystem. (openpyxl
is avoided on purpose: it spools every worksheet through a temporary file even
when saving to a buffer.) The .xlsx parts are written directly with inline
strings, so its bytes depend only on this file. The .docx bytes are deterministic
for a given python-docx version: the archive is rewritten uncompressed
(ZIP_STORED, no zlib dependence) with a fixed member timestamp and permissions,
and the core-properties dates are pinned.

Usage: python data/samples/software_test_build_binary_fixtures.py
"""

import datetime
import io
import re
import zipfile
from pathlib import Path

from xml.sax.saxutils import escape

import docx

BANNER = "[SOFTWARE_TEST FIXTURE — DEMONSTRATES SOFTWARE MECHANICS ONLY, NOT EMPIRICAL FINDINGS]"
FIXED_DATETIME = datetime.datetime(2026, 11, 19, 0, 0, 0)
FIXED_W3CDTF = b"2026-11-19T00:00:00Z"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

SAMPLES = Path(__file__).resolve().parent
DOCX_PATH = SAMPLES / "software_test_teams_multiline.docx"
XLSX_PATH = SAMPLES / "software_test_survey.xlsx"

DOCX_PARAGRAPHS = [
    "\n0:00\nLet me start with our first question. What does a typical week look like for you?",
    "\n0:02\nFirst line of response.\nSecond line that used to be dropped.",
    "\n0:45\nCan I ask whether the benefit covers travel time to appointments?",
    "\n1:10\nThat covers what I wanted to know.\nThe paperwork took two visits.",
]

XLSX_ROWS = [
    ["respondent_id", "role", "response", "software_test_label"],
    ["R001", "participant", "Cuando se agotó el beneficio, busqué otro trabajo.", BANNER],
    ["R002", "staff", "   ", BANNER],
    ["R003", "participant", "The clinic hours did not match my shift.", BANNER],
]

_DATE_TAGS = re.compile(rb"(<dcterms:(created|modified)\b[^>]*>)[^<]*(</dcterms:\2>)")


def normalize_ooxml(raw: bytes) -> bytes:
    """Rewrite an Office Open XML archive with fixed timestamps and no compression."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = _DATE_TAGS.sub(lambda m: m.group(1) + FIXED_W3CDTF + m.group(3), data)
            member = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            member.compress_type = zipfile.ZIP_STORED
            member.create_system = 3
            member.external_attr = 0o644 << 16
            dst.writestr(member, data)
    return out.getvalue()


def build_docx_bytes() -> bytes:
    document = docx.Document()
    document.sections[0].header.paragraphs[0].text = BANNER
    props = document.core_properties
    props.title = BANNER
    props.comments = BANNER
    props.author = "ATLAS SOFTWARE_TEST"
    props.last_modified_by = "ATLAS SOFTWARE_TEST"
    props.created = FIXED_DATETIME
    props.modified = FIXED_DATETIME
    for text in DOCX_PARAGRAPHS:
        document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return normalize_ooxml(buf.getvalue())


XLSX_PARTS_STATIC = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        "</Types>"
    ),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        "</Relationships>"
    ),
    "xl/workbook.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="software_test_survey" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    ),
    "xl/_rels/workbook.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    ),
}


def _xlsx_core_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(BANNER)}</dc:title>"
        "<dc:creator>ATLAS SOFTWARE_TEST</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{FIXED_W3CDTF.decode()}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{FIXED_W3CDTF.decode()}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _xlsx_sheet_xml() -> str:
    rows = []
    for r_idx, row in enumerate(XLSX_ROWS, start=1):
        cells = []
        for c_idx, value in enumerate(row):
            ref = f"{chr(ord('A') + c_idx)}{r_idx}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
            )
        rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows)}</sheetData>'
        "</worksheet>"
    )


def build_xlsx_bytes() -> bytes:
    parts = dict(XLSX_PARTS_STATIC)
    parts["docProps/core.xml"] = _xlsx_core_xml()
    parts["xl/worksheets/sheet1.xml"] = _xlsx_sheet_xml()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as dst:
        for name, text in parts.items():
            member = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            member.compress_type = zipfile.ZIP_STORED
            member.create_system = 3
            member.external_attr = 0o644 << 16
            dst.writestr(member, text.encode("utf-8"))
    return out.getvalue()


def build() -> list:
    DOCX_PATH.write_bytes(build_docx_bytes())
    XLSX_PATH.write_bytes(build_xlsx_bytes())
    return [DOCX_PATH, XLSX_PATH]


if __name__ == "__main__":
    for path in build():
        print(path)
