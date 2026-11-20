"""Slice 3 repair rounds 1-2 (RED): regressions for the Codex P2 defects.

1. Two uploads that share a filename must keep their own text-column
   detection, so tables that keep their free text in different columns are
   rejected instead of silently collapsing onto one column.
2. Malformed uploads (empty CSV, extra non-empty cells, invalid UTF-8, corrupt
   .xlsx / .docx, unterminated CSV quote) show st.error and stop; the app never
   raises an uncaught exception.
3. An unterminated CSV quote raises ValueError instead of merging the next
   respondent record into the quoted cell; valid multi-line quoted cells and
   escaped "" quotes still parse.
4. (Round 2) A '"' inside an unquoted cell is malformed under strict RFC 4180
   and raises ValueError instead of silently splitting the cell at a comma.
5. (Round 2) A valid .docx ZIP whose word/document.xml is malformed XML shows
   st.error instead of raising an uncaught lxml XMLSyntaxError.

Every input is a SOFTWARE_TEST fixture that demonstrates software mechanics
only; nothing asserted here is an empirical finding.

Run: .venv/bin/python -m unittest tests/test_slice3_adversarial_regressions.py -v
"""

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from universal_transcript_parser import UniversalTranscriptParser  # noqa: E402

APP_PATH = REPO_ROOT / "app.py"
CORPUS_LABEL = "Corpus Dataset"
KPI_LABEL = "Analytical Units (N)"

UNTERMINATED_CSV = b'id,response\nR1,"The bus was late.\nR2,The clinic closed.\n'
MID_FIELD_QUOTE_CSV = b'id,response,comment\nR1,The bus was "late, clinic closed",\n'
SAMPLE_DOCX = REPO_ROOT / "data" / "samples" / "software_test_teams_multiline.docx"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def docx_with_broken_document_xml():
    """A real .docx ZIP package whose word/document.xml is malformed XML."""
    out = io.BytesIO()
    with zipfile.ZipFile(SAMPLE_DOCX) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = b"<broken" if item.filename == "word/document.xml" else src.read(item.filename)
            dst.writestr(item, data)
    return out.getvalue()


def boot_upload(files):
    at = AppTest.from_file(str(APP_PATH), default_timeout=20)
    at.run()
    box = next(s for s in at.selectbox if s.label == CORPUS_LABEL)
    box.select(next(o for o in box.options if "Upload" in o))
    at.run()
    at.file_uploader[0].set_value(files)
    at.run()
    return at


def ran_analysis(at):
    return any(m.label == KPI_LABEL for m in at.metric)


class TestDuplicateFilenameTextColumnDetection(unittest.TestCase):
    """Both uploads are named a.csv; each table keeps its free text in the other column."""

    TABLE_RESPONSE = (
        b"id,response,comment\n"
        b"R1,The bus to the clinic was late every single morning.,ok\n"
        b"R2,We waited two hours at the bus stop in the rain.,\n"
    )
    TABLE_COMMENT = (
        b"id,response,comment\n"
        b"S1,ok,The bus never came so we walked to the clinic.\n"
        b"S2,,The bus schedule changed and nobody told us.\n"
    )

    def test_duplicate_names_with_disagreeing_columns_are_rejected(self):
        at = boot_upload([
            ("a.csv", self.TABLE_RESPONSE, "text/csv"),
            ("a.csv", self.TABLE_COMMENT, "text/csv"),
        ])
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertGreater(len(at.error), 0, "duplicate-name tables with different text columns were accepted")
        message = " ".join(str(e.value) for e in at.error)
        self.assertIn("response", message)
        self.assertIn("comment", message)
        self.assertFalse(ran_analysis(at), "analysis ran on tables that disagree on the text column")

    def test_distinct_names_with_disagreeing_columns_are_rejected(self):
        at = boot_upload([
            ("a.csv", self.TABLE_RESPONSE, "text/csv"),
            ("b.csv", self.TABLE_COMMENT, "text/csv"),
        ])
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertGreater(len(at.error), 0)
        self.assertFalse(ran_analysis(at))

    def test_duplicate_names_that_agree_still_analyse_both(self):
        at = boot_upload([
            ("a.csv", self.TABLE_RESPONSE, "text/csv"),
            ("a.csv", self.TABLE_RESPONSE.replace(b"R1,", b"Q1,").replace(b"R2,", b"Q2,"), "text/csv"),
        ])
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(len(at.error), 0, [e.value for e in at.error])
        n = next(m for m in at.metric if m.label == KPI_LABEL)
        self.assertEqual(int(str(n.value)), 4)


class TestMalformedUploadsShowErrors(unittest.TestCase):
    CASES = {
        "empty_csv": ("empty.csv", b"", "text/csv"),
        "extra_nonempty_cells": ("extra.csv", b"id,response\nR1,hello there,extra cell\n", "text/csv"),
        "invalid_utf8_csv": ("bad_utf8.csv", b"id,response\nR1,caf\xe9 \xff\xfe\n", "text/csv"),
        "corrupt_xlsx": ("corrupt.xlsx", b"this is not a zip workbook",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "corrupt_docx": ("corrupt.docx", b"this is not a zip document",
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "unterminated_quote_csv": ("unterminated.csv", UNTERMINATED_CSV, "text/csv"),
        "garbage_after_closing_quote": ("after_quote.csv", b'id,response\nR1,"late"x\n', "text/csv"),
        "mid_field_quote_csv": ("mid_quote.csv", MID_FIELD_QUOTE_CSV, "text/csv"),
    }

    def test_docx_with_malformed_document_xml_shows_error_without_exception(self):
        at = boot_upload(("broken_xml.docx", docx_with_broken_document_xml(), DOCX_MIME))
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertGreaterEqual(len(at.error), 1, "no st.error shown for malformed document.xml")
        self.assertFalse(ran_analysis(at), "analysis rendered for a .docx with malformed XML")

    def test_each_malformed_upload_shows_error_without_exception(self):
        for case, upload in self.CASES.items():
            with self.subTest(case=case):
                at = boot_upload(upload)
                self.assertEqual(len(at.exception), 0, f"{case}: {[e.value for e in at.exception]}")
                self.assertGreaterEqual(len(at.error), 1, f"{case}: no st.error shown")
                self.assertFalse(ran_analysis(at), f"{case}: analysis rendered for a malformed upload")


class TestParserCsvQuoting(unittest.TestCase):
    def _parse(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "software_test_quoting.csv"
            path.write_bytes(payload)
            return UniversalTranscriptParser().parse_tabular(str(path), text_col="response", id_col="id")

    def test_unterminated_quote_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse(UNTERMINATED_CSV)
        self.assertIn("line 2", str(ctx.exception))

    def test_unterminated_quote_after_comment_banner_reports_physical_line(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse(b"# SOFTWARE_TEST banner\n\n" + UNTERMINATED_CSV)
        self.assertIn("line 4", str(ctx.exception))

    def test_character_after_closing_quote_raises(self):
        with self.assertRaises(ValueError):
            self._parse(b'id,response\nR1,"late"x\nR2,fine\n')

    def test_multiline_quoted_cell_still_parses(self):
        turns = self._parse(b'id,response\na,"first\nstill first"\nb,last\n')
        self.assertEqual([t["unit_id"].split("::")[-1] for t in turns], ["a", "b"])
        self.assertEqual([t["line_number"] for t in turns], [2, 4])
        self.assertIn("still first", turns[0]["text"])

    def test_escaped_quotes_still_parse(self):
        turns = self._parse(b'id,response\na,"He said ""hi"""\n')
        self.assertEqual(len(turns), 1)
        self.assertIn('He said "hi"', turns[0]["text"])

    def test_quote_inside_unquoted_cell_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse(MID_FIELD_QUOTE_CSV)
        self.assertIn("line 2", str(ctx.exception))
        self.assertIn("unexpected quote inside unquoted field", str(ctx.exception))

    def test_quote_inside_unquoted_cell_after_banner_reports_physical_line(self):
        with self.assertRaises(ValueError) as ctx:
            self._parse(b"# SOFTWARE_TEST banner\n\n" + MID_FIELD_QUOTE_CSV)
        self.assertIn("line 4", str(ctx.exception))

    def test_quoted_cell_with_comma_and_crlf_still_parses(self):
        turns = self._parse(b'id,response\r\na,"quoted, with comma"\r\nb,"He said ""hello"""\r\n')
        self.assertEqual(len(turns), 2)
        self.assertIn("quoted, with comma", turns[0]["text"])
        self.assertIn('He said "hello"', turns[1]["text"])


if __name__ == "__main__":
    unittest.main()
