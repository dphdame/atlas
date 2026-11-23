"""[SOFTWARE_TEST FIXTURE — DEMONSTRATES SOFTWARE MECHANICS ONLY, NOT EMPIRICAL FINDINGS]

ATLAS v1.2 slice 1: structured 3-column focus-group notes (.docx).

Every fixture here is synthetic SOFTWARE_TEST data. The notes fixtures are built by
data/samples/software_test_build_binary_fixtures.py; ad-hoc layouts are written to a
temporary directory with python-docx.
"""

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import docx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from atlas_engine import AtlasEngine  # noqa: E402
from universal_transcript_parser import SOFTWARE_TEST_BANNER, UniversalTranscriptParser  # noqa: E402

SAMPLES = REPO_ROOT / "data" / "samples"
BINARY_BUILDER = SAMPLES / "software_test_build_binary_fixtures.py"
TREATMENT_DOCX = SAMPLES / "software_test_gbi_group_treatment.docx"
CONTROL_DOCX = SAMPLES / "software_test_gbi_group_control.docx"
TEAMS_DOCX = SAMPLES / "software_test_teams_multiline.docx"
SURVEY_CSV = SAMPLES / "software_test_survey.csv"
ZOOM_VTT = SAMPLES / "software_test_zoom_session.vtt"
TWO_QUESTIONS_TXT = SAMPLES / "software_test_two_questions.txt"
CODEBOOK = REPO_ROOT / "config" / "intake_and_enrollment.yaml"

TREATMENT_ID = "data/samples/software_test_gbi_group_treatment.docx"
CONTROL_ID = "data/samples/software_test_gbi_group_control.docx"

# v1.1 fixtures whose bytes must not change when the builder gains new fixtures.
V11_BINARY_SHA256 = {
    "software_test_teams_multiline.docx": "5bee36078575a35e03b12cab1fb9985762040689b88dfbbd3e58afcb391b35eb",
    "software_test_survey.xlsx": "716d429a4917a2b9fd9ad5ca65f78fffa87e4c3c0fdc5f84ba1d31fe9e02f104",
}

ADDITIVE_KEYS = ("document_structure", "evidence_type", "question_id", "group_id", "participant_id")
STANDARD_KEYS = (
    "turn_id", "document_name", "source_id", "unit_id", "line_number", "timestamp",
    "speaker", "is_facilitator", "text", "word_count", "char_start", "char_end",
)

KP, QUOTE, OBS, THEMES = "key_point_paraphrase", "notable_quote_verbatim", "observation", "themes_summary"
ALL_TYPES = (KP, QUOTE, OBS, THEMES)

# (question_id, speaker, evidence_type, text) in document order, all evidence types.
TREATMENT_ALL = [
    ("Question 1", "P1", KP, "Gathered forms in one afternoon."),
    ("Question 1", "P1", QUOTE, "\"The paperwork was simple once I had help.\""),
    ("Question 1", "P2", KP, "Needed two trips to the office. Brought the wrong form the first time."),
    ("Question 1", "P2", QUOTE, "I had to come back the next week."),
    ("Question 1", "P2", OBS, "Laughed while describing the second trip."),
    ("Question 1", "P4", OBS, "Nodded along; did not speak to this item."),
    ("Question 1", "NoteTaker_Themes", THEMES, "Help from staff shortened the paperwork step."),
    ("Question 2", "P1", KP, "About three weeks waiting."),
    ("Question 2", "P2", KP, "No callback until the second month."),
    ("Question 2", "P2", QUOTE, "“I kept checking the mailbox every day.”"),
    ("Question 2", "P3", KP, "Approved in the first week."),
    ("Question 2", "P3", OBS, "Spoke quietly."),
    ("Question 2", "P4", KP, "Still waiting on a pending approval."),
    ("Question 2", "P4", QUOTE, "Nobody told me what was missing."),
    ("Question 2", "NoteTaker_Themes", THEMES, "Wait times varied from one week to two months."),
    ("Question 3", "P1", KP, "A checklist before the first visit."),
    ("Question 3", "P2", KP, "Evening office hours."),
    ("Question 3", "P3", KP, "Text message reminders."),
    ("Question 3", "P3", QUOTE, "\"A reminder would have saved me a trip.\""),
    ("Question 3", "NoteTaker_Themes", THEMES, "Participants asked for clearer advance instructions."),
]

CONTROL_ALL = [
    ("Question 1", "P1", KP, "Filled out the forms alone at home."),
    ("Question 1", "P1", QUOTE, "It took me most of a weekend."),
    ("Question 1", "P2", KP, "Did not know which proof of income to bring."),
    ("Question 1", "P2", OBS, "Looked frustrated."),
    ("Question 1", "NoteTaker_Themes", THEMES, "Uncertainty about required documents."),
    ("Question 2", "P1", KP, "Two weeks waiting."),
    ("Question 2", "P2", KP, "Called three times before hearing back."),
    ("Question 2", "P2", QUOTE, "\"Every call was a different person.\""),
    ("Question 2", "P3", KP, "Has not heard back yet."),
    ("Question 2", "P3", QUOTE, "I stopped calling after a month."),
    ("Question 2", "P3", OBS, "Shrugged."),
    ("Question 2", "NoteTaker_Themes", THEMES, "Repeat calls were common."),
]

# Exact v1.1 (137722e) parser output for ordinary Word layouts, keys STANDARD_KEYS only.
V11_TEAMS_TURNS = [
    {"turn_id": 1, "document_name": "software_test_teams_multiline.docx",
     "source_id": "data/samples/software_test_teams_multiline.docx",
     "unit_id": "data/samples/software_test_teams_multiline.docx", "line_number": 1, "timestamp": "0:00",
     "speaker": "Unknown", "is_facilitator": False,
     "text": "Let me start with our first question. What does a typical week look like for you?",
     "word_count": 16, "char_start": 0, "char_end": 81},
    {"turn_id": 2, "document_name": "software_test_teams_multiline.docx",
     "source_id": "data/samples/software_test_teams_multiline.docx",
     "unit_id": "data/samples/software_test_teams_multiline.docx", "line_number": 2, "timestamp": "0:02",
     "speaker": "Unknown", "is_facilitator": False,
     "text": "First line of response. Second line that used to be dropped.",
     "word_count": 11, "char_start": 82, "char_end": 142},
    {"turn_id": 3, "document_name": "software_test_teams_multiline.docx",
     "source_id": "data/samples/software_test_teams_multiline.docx",
     "unit_id": "data/samples/software_test_teams_multiline.docx", "line_number": 3, "timestamp": "0:45",
     "speaker": "Unknown", "is_facilitator": False,
     "text": "Can I ask whether the benefit covers travel time to appointments?",
     "word_count": 11, "char_start": 143, "char_end": 208},
    {"turn_id": 4, "document_name": "software_test_teams_multiline.docx",
     "source_id": "data/samples/software_test_teams_multiline.docx",
     "unit_id": "data/samples/software_test_teams_multiline.docx", "line_number": 4, "timestamp": "1:10",
     "speaker": "Unknown", "is_facilitator": False,
     "text": "That covers what I wanted to know. The paperwork took two visits.",
     "word_count": 12, "char_start": 209, "char_end": 274},
]


def _std(name, line, ts, speaker, text, wc, start, end):
    return {"turn_id": None, "document_name": name, "source_id": name, "unit_id": name, "line_number": line,
            "timestamp": ts, "speaker": speaker, "is_facilitator": False, "text": text, "word_count": wc,
            "char_start": start, "char_end": end}


def _numbered(turns):
    for idx, t in enumerate(turns, start=1):
        t["turn_id"] = idx
    return turns


# Ordinary table layouts: (filename, header, rows, leading paragraphs, trailing paragraphs, v1.1 turns).
ORDINARY_LAYOUTS = [
    ("two_col.docx", ["Speaker", "Dialogue"],
     [["Interviewer", "What brought you in today?"],
      ["Ana Lopez", "The paperwork for my renewal.\nIt was due Friday."],
      ["Ana Lopez", ""]],
     ["Intake interview notes"], ["Ana Lopez: One more thing about the forms."],
     _numbered([
         _std("two_col.docx", 1, "", "Unknown", "Intake interview notes", 3, 0, 22),
         _std("two_col.docx", 3, "", "Interviewer", "What brought you in today?", 5, 23, 49),
         _std("two_col.docx", 4, "", "Ana Lopez", "The paperwork for my renewal. It was due Friday.", 9, 50, 98),
         _std("two_col.docx", 6, "", "Ana Lopez", "One more thing about the forms.", 6, 99, 130),
     ])),
    ("three_col.docx", ["Speaker", "Dialogue", "Timestamp"],
     [["Interviewer", "How long did you wait?", "00:01:05"],
      ["Ben Ortiz", "Two weeks waiting.", "00:01:20"]],
     [], [],
     _numbered([
         _std("three_col.docx", 2, "00:01:05", "Interviewer", "How long did you wait?", 5, 0, 22),
         _std("three_col.docx", 3, "00:01:20", "Ben Ortiz", "Two weeks waiting.", 3, 23, 41),
     ])),
    # "Key Points" without "Notable Quotes" is not a notes table.
    ("no_quotes_col.docx", ["Key Points", "Summary", "Observations"],
     [["P1: Forms were long.", "Short summary.", "Calm."]],
     [], [],
     _numbered([
         _std("no_quotes_col.docx", 1, "Observations", "Key Points", "Summary", 1, 0, 7),
         _std("no_quotes_col.docx", 2, "Calm.", "P1: Forms were long.", "Short summary.", 2, 8, 22),
     ])),
    # A 2-column "Key Points | Notable Quotes" table is below the 3-column threshold.
    ("two_col_notes.docx", ["Key Points", "Notable Quotes"],
     [["P1: Forms were long.", "It took all day."]],
     [], [],
     _numbered([
         _std("two_col_notes.docx", 1, "", "Key Points", "Notable Quotes", 2, 0, 14),
         _std("two_col_notes.docx", 2, "", "P1: Forms were long.", "It took all day.", 4, 15, 31),
     ])),
]


def load_binary_builder():
    spec = importlib.util.spec_from_file_location("software_test_build_binary_fixtures", BINARY_BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_table_doc(path, header, rows, leading=(), trailing=()):
    document = docx.Document()
    for text in leading:
        document.add_paragraph(text)
    table = document.add_table(rows=1 + len(rows), cols=len(header))
    for col, label in enumerate(header):
        table.rows[0].cells[col].text = label
    for r_idx, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            table.rows[r_idx].cells[col].text = value
    for text in trailing:
        document.add_paragraph(text)
    document.save(str(path))


def write_notes_doc(path, blocks):
    """blocks: ("p", text) paragraphs or ("t", rows) 3-column notes tables (header added)."""
    document = docx.Document()
    for kind, value in blocks:
        if kind == "p":
            document.add_paragraph(value)
            continue
        table = document.add_table(rows=1 + len(value), cols=3)
        for col, label in enumerate(["Key Points", "Notable Quotes", "Observations"]):
            table.rows[0].cells[col].text = label
        for r_idx, row in enumerate(value, start=1):
            for col, cell in enumerate(row):
                table.rows[r_idx].cells[col].text = cell
    document.save(str(path))


def strip_additive(turns):
    return [{k: v for k, v in t.items() if k not in ADDITIVE_KEYS} for t in turns]


def summary(turns):
    return [(t["question_id"], t["speaker"], t["evidence_type"], t["text"]) for t in turns]


def parse_notes(path, **kwargs):
    parser = UniversalTranscriptParser(root_dir=str(REPO_ROOT), **kwargs)
    return parser, parser.parse_file(str(path))


class NotesFixtureTests(unittest.TestCase):
    def test_fixtures_exist_and_are_labelled(self):
        for path in (TREATMENT_DOCX, CONTROL_DOCX):
            with self.subTest(fixture=path.name):
                self.assertTrue(path.is_file(), path)
                self.assertTrue(path.name.startswith("software_test_"))
                paragraphs = [p.text for p in docx.Document(str(path)).paragraphs]
                self.assertEqual(paragraphs[0], SOFTWARE_TEST_BANNER, "banner must open the document body")

    def test_builder_rebuilds_notes_fixtures_byte_for_byte(self):
        builder = load_binary_builder()
        versions = f"python-docx {docx.__version__}"
        self.assertEqual(builder.build_gbi_docx_bytes("treatment"), TREATMENT_DOCX.read_bytes(), versions)
        self.assertEqual(builder.build_gbi_docx_bytes("control"), CONTROL_DOCX.read_bytes(), versions)
        with self.assertRaises(ValueError):
            builder.build_gbi_docx_bytes("placebo")

    def test_v11_fixtures_unchanged_by_builder(self):
        builder = load_binary_builder()
        for name, expected in V11_BINARY_SHA256.items():
            with self.subTest(fixture=name):
                self.assertEqual(hashlib.sha256((SAMPLES / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(hashlib.sha256(builder.build_docx_bytes()).hexdigest(),
                         V11_BINARY_SHA256["software_test_teams_multiline.docx"])
        self.assertEqual(hashlib.sha256(builder.build_xlsx_bytes()).hexdigest(),
                         V11_BINARY_SHA256["software_test_survey.xlsx"])

    def test_fixture_layout_mirrors_template(self):
        for path, n_questions, n_participants in ((TREATMENT_DOCX, 3, 4), (CONTROL_DOCX, 2, 3)):
            with self.subTest(fixture=path.name):
                document = docx.Document(str(path))
                paragraphs = [p.text for p in document.paragraphs]
                self.assertEqual(sum(p.startswith("Question ") for p in paragraphs), n_questions)
                self.assertTrue(any(p.startswith("Consent") for p in paragraphs))
                notes_tables = [t for t in document.tables if t.rows[0].cells[0].text == "Key Points"]
                self.assertEqual(len(notes_tables), n_questions)
                for table in notes_tables:
                    self.assertEqual([c.text for c in table.rows[0].cells],
                                     ["Key Points", "Notable Quotes", "Observations"])
                    labels = [row.cells[0].text.split(":")[0].upper() for row in table.rows[1:-1]]
                    self.assertEqual(labels, [f"P{i}" for i in range(1, n_participants + 1)])
                    self.assertTrue(table.rows[-1].cells[0].text.startswith("Themes / Topics / Patterns:"))
                one_col = [t.rows[0].cells[0].text for t in document.tables if len(t.columns) == 1]
                self.assertEqual(one_col, ["Summary of Session (1-2 Sentences):", "Main Observations (4-5) Ideas:"])

    def test_banner_never_emitted_and_recorded(self):
        for path in (TREATMENT_DOCX, CONTROL_DOCX):
            with self.subTest(fixture=path.name):
                parser, turns = parse_notes(path, include_evidence_types=ALL_TYPES)
                self.assertTrue(turns)
                self.assertFalse(any("SOFTWARE_TEST" in t["text"] for t in turns))
                self.assertEqual(parser.last_fixture_banner_lines, [1])


class DetectionTests(unittest.TestCase):
    def test_notes_documents_detected(self):
        for path in (TREATMENT_DOCX, CONTROL_DOCX):
            with self.subTest(fixture=path.name):
                _, turns = parse_notes(path)
                self.assertTrue(turns)
                self.assertEqual({t["document_structure"] for t in turns}, {"focus_group_notes"})

    def test_teams_docx_is_transcript_and_identical_to_v11(self):
        turns = UniversalTranscriptParser().parse_file(str(TEAMS_DOCX), root_dir=str(REPO_ROOT))
        self.assertEqual(strip_additive(turns), V11_TEAMS_TURNS)
        for t in turns:
            self.assertEqual(list(t)[:len(STANDARD_KEYS)], list(STANDARD_KEYS), "standard key order kept")
            self.assertEqual(t["document_structure"], "transcript")
            self.assertEqual(t["evidence_type"], "verbatim_turn")
            self.assertEqual(t["question_id"], "")
            self.assertEqual(t["group_id"], t["source_id"])
            self.assertEqual(t["participant_id"], t["unit_id"])

    def test_ordinary_table_layouts_identical_to_v11(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, header, rows, leading, trailing, expected in ORDINARY_LAYOUTS:
                with self.subTest(layout=name):
                    path = Path(tmp) / name
                    write_table_doc(path, header, rows, leading, trailing)
                    parser = UniversalTranscriptParser()
                    turns = parser.parse_file(str(path), root_dir=tmp)
                    self.assertEqual(strip_additive(turns), expected)
                    self.assertEqual({t["document_structure"] for t in turns}, {"transcript"})
                    self.assertEqual({t["evidence_type"] for t in turns}, {"verbatim_turn"})
                    self.assertNotIn(name, parser.last_document_metadata)

    def test_other_formats_carry_structure_keys(self):
        parser = UniversalTranscriptParser(root_dir=str(REPO_ROOT))
        for path, structure in ((ZOOM_VTT, "transcript"), (TWO_QUESTIONS_TXT, "transcript"),
                                (SURVEY_CSV, "tabular")):
            with self.subTest(fixture=path.name):
                turns = parser.parse_file(str(path))
                self.assertTrue(turns)
                for t in turns:
                    self.assertEqual(t["document_structure"], structure)
                    self.assertEqual(t["evidence_type"], "verbatim_turn")
                    self.assertEqual(t["question_id"], "")
                    self.assertEqual(t["group_id"], t["source_id"])
                    self.assertEqual(t["participant_id"], t["unit_id"])

    def test_notes_header_case_and_whitespace_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loose_header.docx"
            write_table_doc(path, ["  KEY   points ", "notable QUOTES:", "observations"],
                            [["P1: Forms were long.", "It took all day.", ""]],
                            leading=["Question 1: How was it?"])
            turns = UniversalTranscriptParser().parse_file(str(path), root_dir=tmp)
            self.assertEqual(summary(turns), [("Question 1", "P1", KP, "Forms were long."),
                                              ("Question 1", "P1", QUOTE, "It took all day.")])


class ExtractionTests(unittest.TestCase):
    def test_treatment_default_turns_exact(self):
        _, turns = parse_notes(TREATMENT_DOCX)
        expected = [row for row in TREATMENT_ALL if row[2] in (KP, QUOTE)]
        self.assertEqual(summary(turns), expected)

    def test_control_default_turns_exact(self):
        _, turns = parse_notes(CONTROL_DOCX)
        expected = [row for row in CONTROL_ALL if row[2] in (KP, QUOTE)]
        self.assertEqual(summary(turns), expected)

    def test_all_evidence_types_exact(self):
        for path, expected in ((TREATMENT_DOCX, TREATMENT_ALL), (CONTROL_DOCX, CONTROL_ALL)):
            with self.subTest(fixture=path.name):
                _, turns = parse_notes(path, include_evidence_types=ALL_TYPES)
                self.assertEqual(summary(turns), expected)

    def test_standard_keys_offsets_and_line_numbers(self):
        _, turns = parse_notes(TREATMENT_DOCX, include_evidence_types=ALL_TYPES)
        for idx, t in enumerate(turns, start=1):
            self.assertEqual(list(t)[:len(STANDARD_KEYS)], list(STANDARD_KEYS))
            for key in ADDITIVE_KEYS:
                self.assertIn(key, t)
            self.assertEqual(t["turn_id"], idx)
            self.assertEqual(t["document_name"], TREATMENT_DOCX.name)
            self.assertEqual(t["source_id"], TREATMENT_ID)
            self.assertEqual(t["group_id"], TREATMENT_ID)
            self.assertEqual(t["timestamp"], "")
            self.assertEqual(t["word_count"], len(t["text"].split()))
            self.assertEqual(t["char_end"] - t["char_start"], len(t["text"]))
        for prev, cur in zip(turns, turns[1:]):
            self.assertEqual(cur["char_start"], prev["char_end"] + 1)
            self.assertLessEqual(prev["line_number"], cur["line_number"])
        # Every evidence item from one table row shares that row's block location.
        p2_q1 = [t for t in turns if t["question_id"] == "Question 1" and t["speaker"] == "P2"]
        self.assertEqual(len({t["line_number"] for t in p2_q1}), 1)
        q1_rows = sorted({t["line_number"] for t in turns if t["question_id"] == "Question 1"})
        self.assertEqual(len(q1_rows), 4, "P1, P2, P4 and Themes rows")

    def test_missing_space_lowercase_label_and_multiline(self):
        _, turns = parse_notes(TREATMENT_DOCX)
        p2 = [t for t in turns if t["speaker"] == "P2"]
        self.assertIn("Needed two trips to the office. Brought the wrong form the first time.",
                      [t["text"] for t in p2])
        self.assertIn("No callback until the second month.", [t["text"] for t in p2])  # "p2:" label
        self.assertFalse(any(t["text"].startswith((":", "P2", "p2")) for t in turns))

    def test_blank_rows_emit_nothing(self):
        _, turns = parse_notes(TREATMENT_DOCX, include_evidence_types=ALL_TYPES)
        self.assertFalse([t for t in turns if t["question_id"] == "Question 1" and t["speaker"] == "P3"])
        self.assertFalse([t for t in turns if t["question_id"] == "Question 3" and t["speaker"] == "P4"])
        self.assertFalse([t for t in turns if not t["text"].strip()])

    def test_observation_only_row(self):
        _, default_turns = parse_notes(TREATMENT_DOCX)
        self.assertFalse([t for t in default_turns if t["question_id"] == "Question 1" and t["speaker"] == "P4"])
        _, obs_turns = parse_notes(TREATMENT_DOCX, include_evidence_types=(OBS,))
        p4 = [t for t in obs_turns if t["question_id"] == "Question 1" and t["speaker"] == "P4"]
        self.assertEqual([(t["evidence_type"], t["text"]) for t in p4],
                         [(OBS, "Nodded along; did not speak to this item.")])
        self.assertEqual(p4[0]["participant_id"], f"{TREATMENT_ID}::P4")

    def test_quotes_with_and_without_quotation_marks(self):
        _, turns = parse_notes(TREATMENT_DOCX, include_evidence_types=(QUOTE,))
        texts = [t["text"] for t in turns]
        self.assertIn("\"The paperwork was simple once I had help.\"", texts)
        self.assertIn("I had to come back the next week.", texts)
        self.assertIn("“I kept checking the mailbox every day.”", texts)
        self.assertEqual({t["evidence_type"] for t in turns}, {QUOTE})

    def test_merged_and_split_themes_rows(self):
        _, t_turns = parse_notes(TREATMENT_DOCX, include_evidence_types=(THEMES,))
        _, c_turns = parse_notes(CONTROL_DOCX, include_evidence_types=(THEMES,))
        self.assertEqual(len(t_turns), 3, "a merged themes row is one turn, not one per column")
        self.assertEqual([t["text"] for t in c_turns],
                         ["Uncertainty about required documents.", "Repeat calls were common."])
        for t in t_turns + c_turns:
            self.assertEqual(t["speaker"], "NoteTaker_Themes")
            self.assertTrue(t["is_facilitator"])
            self.assertEqual(t["evidence_type"], THEMES)

    def test_missing_question_heading_falls_back_to_table_order(self):
        row = [["P1: Forms were long.", "It took all day.", ""]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clipped.docx"
            write_notes_doc(path, [
                ("t", row),
                ("p", "Question 2: How long did you wait?"),
                ("p", "Probe: Anyone call you back?"),
                ("t", row),
                ("t", row),
            ])
            parser = UniversalTranscriptParser()
            turns = parser.parse_file(str(path), root_dir=tmp)
            self.assertEqual([t["question_id"] for t in turns if t["evidence_type"] == KP],
                             ["Question 1", "Question 2", "Question 3"])
            self.assertFalse(any("Probe" in t["text"] or "How long" in t["text"] for t in turns))
            self.assertEqual(parser.last_document_metadata["clipped.docx"]["questions"]["Question 2"],
                             "How long did you wait?\nProbe: Anyone call you back?")

    def test_reordered_columns_keep_themes_and_roles(self):
        header = ["Observations", "Notable Quotes", "Key Points"]
        rows = [
            ["Calm.", "It took all day.", "P1: Forms were long."],
            ["", "Callbacks were slow.", "Themes / Topics / Patterns: Long forms."],
            ["", "", "Themes / Topics / Patterns:"],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reordered.docx"
            write_table_doc(path, header, rows, leading=["Question 1: How was it?"])
            turns = UniversalTranscriptParser(include_evidence_types=ALL_TYPES).parse_file(str(path), root_dir=tmp)
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Forms were long."),
            ("Question 1", "P1", QUOTE, "It took all day."),
            ("Question 1", "P1", OBS, "Calm."),
            ("Question 1", "NoteTaker_Themes", THEMES, "Long forms. Callbacks were slow."),
        ])

    def test_conflicting_cell_labels_attributed_per_cell(self):
        rows = [
            ["P1: Forms were long.", "P2: It took all day.", "Nodded."],
            ["P3:", "P4: Nobody called back.", ""],
            ["P5: Short wait.", "P5: Same day.", ""],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conflict.docx"
            write_notes_doc(path, [("p", "Question 1: How was it?"), ("t", rows)])
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES)
            turns = parser.parse_file(str(path), root_dir=tmp)
        # In a mixed row an unlabelled cell has no reliable owner, so it is "Unknown".
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Forms were long."),
            ("Question 1", "P2", QUOTE, "It took all day."),
            ("Question 1", "Unknown", OBS, "Nodded."),
            ("Question 1", "P4", QUOTE, "Nobody called back."),
            ("Question 1", "P5", KP, "Short wait."),
            ("Question 1", "P5", QUOTE, "Same day."),
        ])
        self.assertEqual([t["participant_id"] for t in turns][:3],
                         ["conflict.docx::P1", "conflict.docx::P2", "conflict.docx::Unknown"])
        # Rows whose cells name different participants are reported (block locations).
        self.assertEqual(parser.last_document_metadata["conflict.docx"]["mixed_label_rows"], [3, 4])

    def test_mixed_row_unlabelled_quote_reaches_engine_as_unknown(self):
        rows = [
            ["P1: Gathered the forms early.", "The paperwork took weeks.", "P2: Nodded."],
            ["P3: Brought the forms twice.", "The paperwork was lost once.", "Frowned."],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed_engine.docx"
            write_notes_doc(path, [("p", "Question 1: How was it?"), ("t", rows)])
            parser = UniversalTranscriptParser(include_evidence_types=(KP, QUOTE, OBS),
                                               notes_unit_level="participant")
            turns = parser.parse_file(str(path), root_dir=tmp)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Gathered the forms early."),
            ("Question 1", "Unknown", QUOTE, "The paperwork took weeks."),
            ("Question 1", "P2", OBS, "Nodded."),
            ("Question 1", "P3", KP, "Brought the forms twice."),
            ("Question 1", "P3", QUOTE, "The paperwork was lost once."),  # unmixed row inherits
            ("Question 1", "P3", OBS, "Frowned."),
        ])
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"mixed_engine.docx": sha})
        quotes = results["quotes_df"]
        paperwork = quotes[quotes["domain_id"] == "paperwork_delays"]
        by_text = dict(zip(paperwork["text"], zip(paperwork["speaker"], paperwork["unit_id"])))
        self.assertEqual(by_text["The paperwork took weeks."], ("Unknown", "mixed_engine.docx::Unknown"))
        self.assertEqual(by_text["Gathered the forms early."], ("P1", "mixed_engine.docx::P1"))
        self.assertEqual(by_text["The paperwork was lost once."], ("P3", "mixed_engine.docx::P3"))
        self.assertNotIn(("P1", "The paperwork took weeks."),
                         set(zip(results["tagged_turns_df"]["speaker"], results["tagged_turns_df"]["text"])))

    def test_fixtures_have_no_mixed_label_rows(self):
        for path in (TREATMENT_DOCX, CONTROL_DOCX):
            parser, _ = parse_notes(path)
            self.assertEqual(next(iter(parser.last_document_metadata.values()))["mixed_label_rows"], [])

    def test_unlabelled_participant_row_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unlabelled.docx"
            write_notes_doc(path, [("p", "Question 1: How was it?"),
                                   ("t", [["Forms were long.", "", ""]])])
            turns = UniversalTranscriptParser().parse_file(str(path), root_dir=tmp)
            self.assertEqual(summary(turns), [("Question 1", "Unknown", KP, "Forms were long.")])
            self.assertEqual(turns[0]["participant_id"], "unlabelled.docx::Unknown")


def new_notes_table(document, n_rows, header=("Key Points", "Notable Quotes", "Observations")):
    """A notes table with its header row and n_rows empty body rows (cells set by the caller)."""
    table = document.add_table(rows=1 + n_rows, cols=len(header))
    for col, label in enumerate(header):
        table.rows[0].cells[col].text = label
    return table


class RepairRound1Tests(unittest.TestCase):
    """Codex review of d67458c: two P1 and two P2 defects (synthetic SOFTWARE_TEST layouts)."""

    def test_multiple_participants_in_one_key_points_cell(self):
        rows = [
            ["P1: Forms took a week.\nP2: Forms took a month.", "\"The paperwork never ended.\"", "Sighed."],
            ["P3: Forms took a day.\np4: Forms were lost.", "P4: \"Nobody called.\"", ""],
            ["P5: Short wait.", "\"Same day.\"", ""],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi.docx"
            write_notes_doc(path, [("p", "Question 1: How was it?"), ("t", rows)])
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES, notes_unit_level="participant")
            turns = parser.parse_file(str(path), root_dir=tmp)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Forms took a week."),
            ("Question 1", "P2", KP, "Forms took a month."),
            # Several participants in the row and no label in the cell: no reliable owner.
            ("Question 1", "Unknown", QUOTE, "\"The paperwork never ended.\""),
            ("Question 1", "Unknown", OBS, "Sighed."),
            ("Question 1", "P3", KP, "Forms took a day."),
            ("Question 1", "P4", KP, "Forms were lost."),
            ("Question 1", "P4", QUOTE, "\"Nobody called.\""),
            ("Question 1", "P5", KP, "Short wait."),
            ("Question 1", "P5", QUOTE, "\"Same day.\""),
        ])
        self.assertEqual([t["participant_id"] for t in turns][:3],
                         ["multi.docx::P1", "multi.docx::P2", "multi.docx::Unknown"])
        for prev, cur in zip(turns, turns[1:]):
            self.assertEqual(cur["char_start"], prev["char_end"] + 1)
        for t in turns:
            self.assertEqual(t["char_end"] - t["char_start"], len(t["text"]))
        meta = parser.last_document_metadata["multi.docx"]
        self.assertEqual(meta["mixed_label_rows"], [3, 4])
        self.assertEqual(meta["ambiguous_multilabel_rows"], [3], "row 4 has no unlabelled cell")
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"multi.docx": sha})
        self.assertIn("multi.docx::P2", set(results["tagged_turns_df"]["unit_id"]))
        self.assertNotIn(("P1", "Forms took a week. P2: Forms took a month."),
                         set(zip(results["tagged_turns_df"]["speaker"], results["tagged_turns_df"]["text"])))

    def test_embedded_structural_rows_are_not_evidence(self):
        document = docx.Document()
        document.add_paragraph("Question 1: How did the enrollment go?")
        table = new_notes_table(document, 8)
        body = [
            ["P1: Gathered the paperwork early.", "", ""],
            "Summary of Session: The paperwork took weeks for most.",
            "Consent: Verbal consent was read again after the paperwork break.",
            "Question 2: How long did the paperwork take to process?",
            "Probe: Did the paperwork come back?",
            ["P2: The paperwork took a month.", "", ""],
            "Main Observations (4-5) Ideas:\n1. Paperwork delays.\n2. Lost forms.",
            SOFTWARE_TEST_BANNER,
        ]
        for r_idx, value in enumerate(body, start=1):
            row = table.rows[r_idx]
            if isinstance(value, list):
                for col, text in enumerate(value):
                    row.cells[col].text = text
            else:
                row.cells[0].merge(row.cells[2]).text = value  # full-width merged row
        # A structural row typed in column 0 only (not merged) is still structure.
        table.add_row().cells[0].text = "Follow-up: Anything else about the paperwork?"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "embedded.docx"
            document.save(str(path))
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES)
            turns = parser.parse_file(str(path), root_dir=tmp)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Gathered the paperwork early."),
            ("Question 2", "P2", KP, "The paperwork took a month."),
        ])
        meta = parser.last_document_metadata["embedded.docx"]
        self.assertEqual(meta["summary_of_session"], "The paperwork took weeks for most.")
        self.assertEqual(meta["main_observations"], "1. Paperwork delays.\n2. Lost forms.")
        self.assertEqual(meta["questions"]["Question 2"],
                         "How long did the paperwork take to process?\nProbe: Did the paperwork come back?\n"
                         "Follow-up: Anything else about the paperwork?")
        self.assertEqual(parser.last_fixture_banner_lines, [10])
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"embedded.docx": sha})
        self.assertEqual(set(results["tagged_turns_df"]["speaker"]), {"P1", "P2"})

    def test_embedded_consent_statement_without_colon_is_not_evidence(self):
        document = docx.Document()
        document.add_paragraph("Question 1: How did the enrollment go?")
        table = new_notes_table(document, 5)
        table.cell(1, 0).text = "P1: Gathered the paperwork early."
        table.cell(2, 0).merge(table.cell(2, 2)).text = "Consent statement was read again after the paperwork break."
        table.cell(3, 0).text = "Consent form signed by all before the paperwork questions."
        # Participant notes that merely start with the word "consent" stay evidence.
        table.cell(4, 0).text = "Consent forms were confusing paperwork."
        table.cell(5, 0).text = "Consent was unclear on the paperwork."
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "consent.docx"
            document.save(str(path))
            turns = UniversalTranscriptParser(include_evidence_types=ALL_TYPES).parse_file(str(path), root_dir=tmp)
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Gathered the paperwork early."),
            ("Question 1", "Unknown", KP, "Consent forms were confusing paperwork."),
            ("Question 1", "Unknown", KP, "Consent was unclear on the paperwork."),
        ])
        self.assertEqual([t["line_number"] for t in turns], [3, 6, 7])

    def test_vertically_merged_key_point_emitted_once(self):
        document = docx.Document()
        document.add_paragraph("Question 1: How did the paperwork go?")
        table = new_notes_table(document, 3)
        table.cell(1, 0).merge(table.cell(2, 0)).text = "P1: The paperwork took weeks."
        table.cell(1, 1).text = "Notable Quote A about the paperwork."
        table.cell(2, 1).text = "Notable Quote B about the paperwork."
        table.cell(2, 2).text = "Frowned."
        table.cell(3, 0).text = "P2: Approved the same day."
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vmerge.docx"
            document.save(str(path))
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES)
            turns = parser.parse_file(str(path), root_dir=tmp)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "The paperwork took weeks."),
            ("Question 1", "P1", QUOTE, "Notable Quote A about the paperwork."),
            ("Question 1", "P1", QUOTE, "Notable Quote B about the paperwork."),
            ("Question 1", "P1", OBS, "Frowned."),
            ("Question 1", "P2", KP, "Approved the same day."),
        ])
        self.assertEqual([t["line_number"] for t in turns], [3, 3, 4, 4, 5])
        self.assertEqual(parser.last_document_metadata["vmerge.docx"]["mixed_label_rows"], [])
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"vmerge.docx": sha})
        quotes = results["quotes_df"]
        matched = quotes[quotes["domain_id"] == "paperwork_delays"]
        self.assertEqual(sorted(matched["text"]), [
            "Notable Quote A about the paperwork.", "Notable Quote B about the paperwork.",
            "The paperwork took weeks.",
        ])
        freq = results["frequencies_df"].set_index("domain_id")
        self.assertEqual(int(freq.loc["paperwork_delays", "matching_turns"]), 3)

    def test_vertically_merged_themes_cell_keeps_new_quote_below(self):
        document = docx.Document()
        document.add_paragraph("Question 1: How did the paperwork go?")
        table = new_notes_table(document, 3)
        table.cell(1, 0).text = "P1: The paperwork took weeks."
        table.cell(2, 0).merge(table.cell(3, 0)).text = "Themes / Topics / Patterns: Paperwork delays."
        table.cell(2, 1).text = "Delays were common."
        table.cell(3, 1).text = "\"The paperwork came back twice.\""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vmerge_themes.docx"
            document.save(str(path))
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES)
            turns = parser.parse_file(str(path), root_dir=tmp)
            default_turns = UniversalTranscriptParser().parse_file(str(path), root_dir=tmp)
        # The themes turn is emitted once on its first row; the new quote on the
        # continuation row is participant evidence with no label, so "Unknown".
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "The paperwork took weeks."),
            ("Question 1", "NoteTaker_Themes", THEMES, "Paperwork delays. Delays were common."),
            ("Question 1", "Unknown", QUOTE, "\"The paperwork came back twice.\""),
        ])
        self.assertEqual([t["line_number"] for t in turns], [3, 4, 5])
        self.assertIn(("Question 1", "Unknown", QUOTE, "\"The paperwork came back twice.\""),
                      summary(default_turns))

    def test_duplicate_semantic_columns_keep_all_text(self):
        header = ["Key Points", "Notable Quotes", "Notable Quotes", "Observations"]
        document = docx.Document()
        document.add_paragraph("Question 1: How was it?")
        table = new_notes_table(document, 2, header)
        for col, text in enumerate(["P1: Forms were long.", "quote A", "quote B", "Calm."]):
            table.cell(1, col).text = text
        # A quote cell merged across both quote columns is one quote, emitted once.
        table.cell(2, 0).text = "P2: Forms were short."
        table.cell(2, 1).merge(table.cell(2, 2)).text = "quote C"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dupcols.docx"
            document.save(str(path))
            turns = UniversalTranscriptParser(include_evidence_types=ALL_TYPES).parse_file(str(path), root_dir=tmp)
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Forms were long."),
            ("Question 1", "P1", QUOTE, "quote A"),
            ("Question 1", "P1", QUOTE, "quote B"),
            ("Question 1", "P1", OBS, "Calm."),
            ("Question 1", "P2", KP, "Forms were short."),
            ("Question 1", "P2", QUOTE, "quote C"),
        ])


class MultiGroupTests(unittest.TestCase):
    def test_groups_and_participants_never_collide(self):
        parser = UniversalTranscriptParser(root_dir=str(REPO_ROOT))
        treatment = parser.parse_file(str(TREATMENT_DOCX))
        control = parser.parse_file(str(CONTROL_DOCX))
        self.assertEqual({t["group_id"] for t in treatment}, {TREATMENT_ID})
        self.assertEqual({t["group_id"] for t in control}, {CONTROL_ID})
        t_ids = {t["participant_id"] for t in treatment}
        c_ids = {t["participant_id"] for t in control}
        self.assertEqual(t_ids, {f"{TREATMENT_ID}::P{i}" for i in range(1, 5)})
        self.assertEqual(c_ids, {f"{CONTROL_ID}::P{i}" for i in range(1, 4)})
        self.assertFalse(t_ids & c_ids)
        self.assertEqual(sorted({t["question_id"] for t in treatment}), ["Question 1", "Question 2", "Question 3"])
        self.assertEqual(sorted({t["question_id"] for t in control}), ["Question 1", "Question 2"])
        # Metadata from both files survives on the shared parser.
        self.assertEqual(parser.last_document_metadata[TREATMENT_ID]["focus_group_type"], "Treatment")
        self.assertEqual(parser.last_document_metadata[CONTROL_ID]["focus_group_type"], "Control")

    def test_unit_level_group_default_and_participant(self):
        _, group_turns = parse_notes(TREATMENT_DOCX)
        self.assertEqual({t["unit_id"] for t in group_turns}, {TREATMENT_ID})
        _, part_turns = parse_notes(TREATMENT_DOCX, notes_unit_level="participant",
                                    include_evidence_types=ALL_TYPES)
        for t in part_turns:
            self.assertEqual(t["unit_id"], t["participant_id"])
            self.assertEqual(t["participant_id"], f"{TREATMENT_ID}::{t['speaker']}")
        _, group_again = parse_notes(TREATMENT_DOCX, notes_unit_level="group")
        self.assertEqual(strip_additive(group_again), strip_additive(group_turns))

    def test_invalid_unit_level_fails_closed(self):
        for bad in ("respondent", "", "GROUP", None):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    UniversalTranscriptParser(notes_unit_level=bad)


class EvidenceTypeFilterTests(unittest.TestCase):
    def test_default_types(self):
        _, turns = parse_notes(TREATMENT_DOCX)
        self.assertEqual({t["evidence_type"] for t in turns}, {KP, QUOTE})
        self.assertFalse(any(t["is_facilitator"] for t in turns))

    def test_opt_in_types(self):
        for types in ((QUOTE,), (KP, OBS), (THEMES,), ALL_TYPES):
            with self.subTest(types=types):
                _, turns = parse_notes(TREATMENT_DOCX, include_evidence_types=types)
                self.assertEqual(summary(turns), [r for r in TREATMENT_ALL if r[2] in types])
                self.assertEqual([t["turn_id"] for t in turns], list(range(1, len(turns) + 1)))

    def test_invalid_types_fail_closed(self):
        for bad in (("observations",), (KP, "verbatim"), (), "observation", ("",)):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    UniversalTranscriptParser(include_evidence_types=bad)

    def test_filter_does_not_touch_ordinary_files(self):
        turns = UniversalTranscriptParser(include_evidence_types=(QUOTE,)).parse_file(
            str(TEAMS_DOCX), root_dir=str(REPO_ROOT))
        self.assertEqual(strip_additive(turns), V11_TEAMS_TURNS)


class MetadataTests(unittest.TestCase):
    def test_metadata_extracted(self):
        parser = UniversalTranscriptParser(root_dir=str(REPO_ROOT))
        parser.parse_file(str(TREATMENT_DOCX))
        parser.parse_file(str(CONTROL_DOCX))
        treatment = parser.last_document_metadata[TREATMENT_ID]
        control = parser.last_document_metadata[CONTROL_ID]
        self.assertEqual(treatment["project_name"], "SOFTWARE_TEST Enrollment Pilot")
        self.assertEqual(treatment["note_taker"], "Note Taker A")
        self.assertEqual(treatment["focus_group_type"], "Treatment")
        self.assertEqual(treatment["facilitator"], "Facilitator A")
        self.assertEqual(treatment["date"], "2026-01-15")
        self.assertEqual(treatment["location"], "Community Room B")
        self.assertEqual(treatment["number_of_participants"], "4")
        self.assertEqual(control["focus_group_type"], "Control")
        self.assertEqual(control["number_of_participants"], "3")
        self.assertEqual(control["date"], "2026-01-22")
        self.assertEqual(treatment["summary_of_session"],
                         "Participants described staff help with forms as useful and wait times as uneven.")
        self.assertEqual(treatment["main_observations"],
                         "1. Staff help mattered.\n2. Wait times varied.\n3. Reminders were requested.\n"
                         "4. Evening hours were requested.")
        self.assertEqual(control["summary_of_session"],
                         "Participants completed forms alone and waited two weeks or longer.")
        self.assertEqual(sorted(treatment["questions"]), ["Question 1", "Question 2", "Question 3"])
        self.assertEqual(treatment["questions"]["Question 1"],
                         "How did the enrollment process go for you?\nFollow-up: What made it easier or harder?")
        for meta in (treatment, control):
            for key in meta:
                self.assertRegex(key, r"^[a-z][a-z0-9_]*$")

    def test_no_metadata_prompt_or_summary_leakage(self):
        forbidden = [
            "Project Name", "SOFTWARE_TEST Enrollment Pilot", "Note Taker", "Focus Group Type", "Treatment",
            "Control", "Facilitator", "Date", "2026-01", "Location", "Community Room", "Number of Participants",
            "Consent", "Question", "Follow-up", "Probe", "How did the enrollment", "Summary of Session",
            "Main Observations", "Staff help mattered", "Participants described", "Key Points",
            "Notable Quotes", "Observations", "Themes", SOFTWARE_TEST_BANNER,
        ]
        for path in (TREATMENT_DOCX, CONTROL_DOCX):
            _, turns = parse_notes(path, include_evidence_types=ALL_TYPES)
            for t in turns:
                for fragment in forbidden:
                    with self.subTest(fixture=path.name, fragment=fragment):
                        self.assertNotIn(fragment, t["text"])
            self.assertEqual(len(turns), len(TREATMENT_ALL if path == TREATMENT_DOCX else CONTROL_ALL))

    def test_stale_metadata_removed_on_reparse_as_other_file(self):
        parser = UniversalTranscriptParser(root_dir=str(REPO_ROOT))
        parser.parse_file(str(TREATMENT_DOCX))
        parser.parse_file(str(TEAMS_DOCX))
        self.assertIn(TREATMENT_ID, parser.last_document_metadata)
        self.assertNotIn("data/samples/software_test_teams_multiline.docx", parser.last_document_metadata)


class EngineCompatibilityTests(unittest.TestCase):
    def test_process_corpus_counts_groups(self):
        engine = AtlasEngine(str(CODEBOOK))
        results = engine.process_corpus([str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO_ROOT))
        self.assertEqual(results["total_documents"], 2)
        self.assertEqual(set(results["file_hashes"]), {TREATMENT_ID, CONTROL_ID})
        self.assertEqual(results["total_turns_parsed"], 14 + 8)
        self.assertEqual(results["participant_turns_analyzed"], 14 + 8)
        freq = results["frequencies_df"].set_index("domain_id")
        self.assertEqual(int(freq.loc["paperwork_delays", "documents_reporting"]), 2)
        quotes = results["quotes_df"]
        self.assertEqual(set(quotes["unit_id"]), {TREATMENT_ID, CONTROL_ID})
        tagged = results["tagged_turns_df"]
        self.assertEqual(set(tagged["document_structure"]), {"focus_group_notes"})
        self.assertEqual(set(tagged["evidence_type"]), {KP, QUOTE})

    def test_process_turns_participant_units_and_themes_excluded(self):
        parser = UniversalTranscriptParser(root_dir=str(REPO_ROOT), notes_unit_level="participant",
                                           include_evidence_types=ALL_TYPES)
        turns = parser.parse_file(str(TREATMENT_DOCX)) + parser.parse_file(str(CONTROL_DOCX))
        hashes = {TREATMENT_ID: hashlib.sha256(TREATMENT_DOCX.read_bytes()).hexdigest(),
                  CONTROL_ID: hashlib.sha256(CONTROL_DOCX.read_bytes()).hexdigest()}
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, hashes)
        self.assertEqual(results["total_documents"], 7, "4 treatment + 3 control participants")
        n_themes = sum(t["evidence_type"] == THEMES for t in turns)
        self.assertEqual(n_themes, 5)
        self.assertEqual(results["participant_turns_analyzed"], len(turns) - n_themes)
        self.assertNotIn("NoteTaker_Themes", set(results["tagged_turns_df"]["speaker"]))


class RepairRound2Tests(unittest.TestCase):
    """Codex review of 3fff4f9: split-cell structural rows and merged-continuation consent prose."""

    def test_split_cell_structural_rows_are_not_evidence(self):
        document = docx.Document()
        document.add_paragraph("Question 1: How did enrollment go?")
        table = new_notes_table(document, 8)
        rows = [
            ["P1: Arrived early for intake.", "", ""],
            ["Summary of Session:", "Paperwork took weeks.", ""],
            ["Consent:", "Verbal consent received from all.", ""],
            ["Question 2:", "How long did the paperwork take?", ""],
            ["Probe:", "Ask about paperwork delays.", ""],
            ["Follow-up:", "Any portal issues?", ""],
            ["P2: Staff answered quickly.", "", ""],
            ["Main Observations (4-5) Ideas:", "1. Paperwork delays.", "2. Portal timeouts."],
        ]
        for r_idx, cells in enumerate(rows, start=1):
            for col, text in enumerate(cells):
                table.rows[r_idx].cells[col].text = text
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "split_struct.docx"
            document.save(str(path))
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES, notes_unit_level="participant")
            turns = parser.parse_file(str(path), root_dir=tmp)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Arrived early for intake."),
            ("Question 2", "P2", KP, "Staff answered quickly."),
        ])
        meta = parser.last_document_metadata["split_struct.docx"]
        self.assertEqual(meta["summary_of_session"], "Paperwork took weeks.")
        self.assertEqual(meta["main_observations"], "1. Paperwork delays.\n2. Portal timeouts.")
        self.assertEqual(meta["questions"]["Question 2"],
                         "How long did the paperwork take?\nProbe: Ask about paperwork delays.\nFollow-up: Any portal issues?")
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"split_struct.docx": sha})
        self.assertEqual(results["total_documents"], 2, "must not inflate 2 participants to 3 with Unknown")
        self.assertEqual(set(results["tagged_turns_df"]["speaker"]), {"P1", "P2"})
        self.assertEqual(int(results["frequencies_df"].set_index("domain_id").loc["paperwork_delays", "documents_reporting"]), 0)

    def test_vertically_merged_continuation_preserves_consent_prose(self):
        document = docx.Document()
        document.add_paragraph("Question 1: What slowed you down?")
        table = new_notes_table(document, 4)
        table.cell(1, 0).merge(table.cell(2, 0)).text = "P1: Enrollment took weeks."
        table.cell(1, 1).text = "First quote about intake."
        table.cell(2, 1).text = "Consent form paperwork was confusing."
        table.cell(3, 0).text = "Consent form paperwork was hard to finish."
        table.cell(4, 0).text = "P2: Approved smoothly."
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vmerge_consent.docx"
            document.save(str(path))
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES, notes_unit_level="participant")
            turns = parser.parse_file(str(path), root_dir=tmp)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Enrollment took weeks."),
            ("Question 1", "P1", QUOTE, "First quote about intake."),
            ("Question 1", "P1", QUOTE, "Consent form paperwork was confusing."),
            ("Question 1", "Unknown", KP, "Consent form paperwork was hard to finish."),
            ("Question 1", "P2", KP, "Approved smoothly."),
        ])
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"vmerge_consent.docx": sha})
        matched = results["quotes_df"]
        self.assertIn("Consent form paperwork was confusing.", set(matched["text"]))
        self.assertIn("Consent form paperwork was hard to finish.", set(matched["text"]))

    def test_prose_opening_with_main_observations_is_not_swallowed(self):
        document = docx.Document()
        document.add_paragraph("Question 1: Overall impressions?")
        table = new_notes_table(document, 2)
        table.cell(1, 0).text = "Main observations about the program were positive."
        table.cell(1, 1).text = "It helped our family."
        table.cell(2, 0).text = "Summary of Session"
        table.cell(2, 1).text = "Paperwork took weeks."
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prose_obs.docx"
            document.save(str(path))
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES)
            turns = parser.parse_file(str(path), root_dir=tmp)
        self.assertEqual(summary(turns), [
            ("Question 1", "Unknown", KP, "Main observations about the program were positive."),
            ("Question 1", "Unknown", QUOTE, "It helped our family."),
        ])
        self.assertEqual(parser.last_document_metadata["prose_obs.docx"]["summary_of_session"], "Paperwork took weeks.")


class RepairRound3Tests(unittest.TestCase):
    """Codex review of 6b88714: column-order independence, participant ownership, consent and summary grammar."""

    ROLES = ("Key Points", "Notable Quotes", "Observations")
    LABELS = (
        ("Question 2:", "How long did it take?", "Question 2"),
        ("Probe:", "Ask about delays.", "Question 1"),
        ("Follow-up:", "Any portal issues?", "Question 1"),
        ("Consent:", "Verbal consent received.", "Question 1"),
        ("Consent form", "Verbal consent received.", "Question 1"),
        ("Summary of Session:", "Paperwork took weeks.", "Question 1"),
        ("Main Observations (4-5) Ideas:", "1. Delays.", "Question 1"),
    )

    @staticmethod
    def _run(tmp, name, build, header=("Key Points", "Notable Quotes", "Observations"), n_rows=3, intro="Question 1: Start?"):
        document = docx.Document()
        document.add_paragraph(intro)
        table = new_notes_table(document, n_rows, header)
        build(table)
        path = Path(tmp) / name
        document.save(str(path))
        parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES, notes_unit_level="participant")
        turns = parser.parse_file(str(path), root_dir=tmp)
        return parser, turns, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_structural_labels_are_independent_of_column_order(self):
        import itertools
        probes = 0
        for perm in itertools.permutations(self.ROLES):
            key_col = perm.index("Key Points")
            for label, payload, after_q in self.LABELS:
                for position in range(3):
                    for shape in ("split", "single"):
                        def build(table, position=position, shape=shape, label=label, payload=payload):
                            table.cell(1, key_col).text = "P1: Before."
                            table.cell(2, position).text = label
                            if shape == "split":
                                table.cell(2, (position + 1) % 3).text = payload
                            table.cell(3, key_col).text = "P2: After."
                        with self.subTest(perm=perm, label=label, position=position, shape=shape):
                            probes += 1
                            with tempfile.TemporaryDirectory() as tmp:
                                _, turns, _ = self._run(tmp, "order.docx", build, header=perm)
                            self.assertEqual(
                                [(t["question_id"], t["speaker"], t["text"]) for t in turns],
                                [("Question 1", "P1", "Before."), (after_q, "P2", "After.")])
        self.assertGreaterEqual(probes, 42)

    def test_explicit_participant_label_outside_key_points_keeps_row(self):
        def build(table):
            table.cell(1, 0).text = "P1: Start."
            table.cell(2, 0).text = "Consent form was signed at the wrong office, so my paperwork was delayed."
            table.cell(2, 1).text = "P1: I had to return twice."
            table.cell(3, 0).text = "P2: Fine."
        with tempfile.TemporaryDirectory() as tmp:
            _, turns, sha = self._run(tmp, "outside_kp.docx", build)
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Start."),
            ("Question 1", "P1", KP, "Consent form was signed at the wrong office, so my paperwork was delayed."),
            ("Question 1", "P1", QUOTE, "I had to return twice."),
            ("Question 1", "P2", KP, "Fine."),
        ])
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"outside_kp.docx": sha})
        self.assertEqual(results["total_documents"], 2)

    def test_inherited_participant_label_does_not_hide_structure(self):
        def build(table):
            table.cell(1, 0).merge(table.cell(4, 0)).text = "P1: Enrollment took weeks."
            table.cell(1, 1).text = "First quote."
            table.cell(2, 1).text = "Consent: Verbal consent received from all."
            table.cell(3, 1).text = "Question 2: How long did it take?"
            table.cell(4, 1).text = "It took weeks."
            table.cell(5, 0).text = "P2: Fine."
        with tempfile.TemporaryDirectory() as tmp:
            parser, turns, _ = self._run(tmp, "inherited.docx", build, n_rows=5)
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Enrollment took weeks."),
            ("Question 1", "P1", QUOTE, "First quote."),
            ("Question 2", "P1", QUOTE, "It took weeks."),
            ("Question 2", "P2", KP, "Fine."),
        ])
        self.assertEqual(parser.last_document_metadata["inherited.docx"]["questions"]["Question 2"], "How long did it take?")

    def test_consent_prose_beneath_vertical_merge_stays_evidence(self):
        def build(table):
            table.cell(1, 0).merge(table.cell(3, 0)).text = "P1: Enrollment took weeks."
            table.cell(1, 1).text = "Consent form paperwork was confusing."
            table.cell(2, 1).text = "Consent form was signed at the wrong office, so my paperwork was delayed."
            table.cell(3, 1).text = "Consent forms took too long."
        with tempfile.TemporaryDirectory() as tmp:
            _, turns, _ = self._run(tmp, "merge_prose.docx", build)
        self.assertEqual([(t["speaker"], t["text"]) for t in turns], [
            ("P1", "Enrollment took weeks."),
            ("P1", "Consent form paperwork was confusing."),
            ("P1", "Consent form was signed at the wrong office, so my paperwork was delayed."),
            ("P1", "Consent forms took too long."),
        ])

    def test_bare_consent_headers_are_structural(self):
        for header in ("Consent", "Consent form", "Consent forms", "Consent statement", "Consent script",
                       "Consent form (verbal)", "Consent form reviewed and signed.", "Consent statement read aloud"):
            def build(table, header=header):
                table.cell(1, 0).text = "P1: Start."
                table.cell(2, 0).text = header
                table.cell(3, 0).text = "P2: After."
            with self.subTest(header=header), tempfile.TemporaryDirectory() as tmp:
                _, turns, sha = self._run(tmp, "bare.docx", build)
                self.assertEqual([t["speaker"] for t in turns], ["P1", "P2"])
                results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"bare.docx": sha})
                self.assertEqual(results["total_documents"], 2)

    def test_consent_grammar_rejects_participant_prose(self):
        from universal_transcript_parser import _NOTES_CONSENT
        for prose in ("Consent form paperwork was confusing.",
                      "Consent form was signed at the wrong office, so my paperwork was delayed.",
                      "Consent forms took too long.",
                      "Consent statement was confusing and delayed my appointment.",
                      "Consent script was too long, so I left.",
                      "Consent statement made me nervous.",
                      "Consent statement was read before I could ask questions.",
                      "Consent form signed before I understood the paperwork rules."):
            self.assertIsNone(_NOTES_CONSENT.match(prose), prose)

    def test_consent_statement_prose_stays_evidence(self):
        def build(table):
            table.cell(1, 0).text = "Consent statement was confusing and delayed my appointment."
            table.cell(1, 1).text = "It took weeks."
            table.cell(2, 0).text = "Consent script was too long, so I left."
            table.cell(3, 0).text = "Consent statement was read before I could ask questions."
        with tempfile.TemporaryDirectory() as tmp:
            _, turns, _ = self._run(tmp, "consent_prose.docx", build, n_rows=3)
        self.assertEqual([t["text"] for t in turns], [
            "Consent statement was confusing and delayed my appointment.", "It took weeks.",
            "Consent script was too long, so I left.",
            "Consent statement was read before I could ask questions."])

    def test_colon_containing_observations_prose_is_evidence(self):
        def build(table):
            table.cell(1, 0).text = "Main observations about the program: the paperwork was confusing."
            table.cell(1, 1).text = "It took weeks."
            table.cell(2, 0).text = "Summary of session notes from P1: paperwork was hard."
        with tempfile.TemporaryDirectory() as tmp:
            parser, turns, _ = self._run(tmp, "obs_prose.docx", build, n_rows=2)
        self.assertEqual([t["text"] for t in turns], [
            "Main observations about the program: the paperwork was confusing.",
            "It took weeks.",
            "Summary of session notes from P1: paperwork was hard.",
        ])
        meta = parser.last_document_metadata["obs_prose.docx"]
        self.assertNotIn("main_observations", meta)

    def test_summary_label_grammar(self):
        from universal_transcript_parser import _NOTES_SUMMARY_LABEL
        for ok in ("Summary of Session:", "Summary of Session: Paperwork took weeks.", "Summary of Session",
                   "Main Observations:", "Main Observations (4-5) Ideas:", "Main Observations (4-5) Ideas: 1. Delays.",
                   "Main Observations (4-5) Ideas"):
            self.assertIsNotNone(_NOTES_SUMMARY_LABEL.match(ok), ok)
        for bad in ("Main observations about the program: the paperwork was confusing.",
                    "Main observations about the program were positive.",
                    "Summary of session notes from P1: paperwork was hard."):
            self.assertIsNone(_NOTES_SUMMARY_LABEL.match(bad), bad)


class RepairRound4Tests(unittest.TestCase):
    """Codex review of df96ba2: themes ownership/grammar and parenthesized summary heading."""

    ROLES = ("Key Points", "Notable Quotes", "Observations")

    def test_themes_prose_with_explicit_participant_stays_evidence(self):
        document = docx.Document()
        document.add_paragraph("Question 1: How did enrollment go?")
        table = new_notes_table(document, 3, ("Observations", "Notable Quotes", "Key Points"))
        table.cell(1, 0).text = "Themes of frustration emerged."
        table.cell(1, 1).text = "I had to return twice."
        table.cell(1, 2).text = "P1: Paperwork took weeks."
        table.cell(2, 2).text = "P2: Staff answered quickly."
        table.cell(3, 0).text = "Themes: Paperwork delays."
        table.cell(3, 2).text = "P1: Still waiting for approval."
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "themes_owner.docx"
            document.save(str(path))
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES, notes_unit_level="participant")
            turns = parser.parse_file(str(path), root_dir=tmp)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(summary(turns), [
            ("Question 1", "P1", KP, "Paperwork took weeks."),
            ("Question 1", "P1", QUOTE, "I had to return twice."),
            ("Question 1", "P1", OBS, "Themes of frustration emerged."),
            ("Question 1", "P2", KP, "Staff answered quickly."),
            ("Question 1", "P1", KP, "Still waiting for approval."),
            ("Question 1", "P1", OBS, "Themes: Paperwork delays."),
        ])
        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"themes_owner.docx": sha})
        self.assertEqual(results["total_documents"], 2)
        self.assertEqual(set(results["tagged_turns_df"]["speaker"]), {"P1", "P2"})

    def test_unlabelled_themes_prose_is_not_reclassified(self):
        document = docx.Document()
        document.add_paragraph("Question 1: Overall impressions?")
        table = new_notes_table(document, 2)
        table.cell(1, 0).text = "Themes of frustration emerged during intake."
        table.cell(2, 0).text = "Themes / Topics / Patterns: Long wait times."
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "themes_prose.docx"
            document.save(str(path))
            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES)
            turns = parser.parse_file(str(path), root_dir=tmp)
        self.assertEqual(summary(turns), [
            ("Question 1", "Unknown", KP, "Themes of frustration emerged during intake."),
            ("Question 1", "NoteTaker_Themes", THEMES, "Long wait times."),
        ])

    def test_parenthesized_summary_of_session_across_column_orders(self):
        import itertools
        probes = 0
        for perm in itertools.permutations(self.ROLES):
            key_col = perm.index("Key Points")
            for label_col in range(3):
                for payload_col in (None, (label_col + 1) % 3, (label_col + 2) % 3):
                    with self.subTest(perm=perm, label_col=label_col, payload_col=payload_col):
                        probes += 1
                        document = docx.Document()
                        document.add_paragraph("Question 1: Start?")
                        table = new_notes_table(document, 3, perm)
                        table.cell(1, key_col).text = "P1: Arrived early."
                        if payload_col is None:
                            table.cell(2, label_col).text = "Summary of Session (1-2 Sentences): Paperwork took weeks."
                        else:
                            table.cell(2, label_col).text = "Summary of Session (1-2 Sentences):"
                            table.cell(2, payload_col).text = "Paperwork took weeks."
                        table.cell(3, key_col).text = "P2: Staff answered quickly."
                        with tempfile.TemporaryDirectory() as tmp:
                            path = Path(tmp) / "summary_paren.docx"
                            document.save(str(path))
                            parser = UniversalTranscriptParser(include_evidence_types=ALL_TYPES, notes_unit_level="participant")
                            turns = parser.parse_file(str(path), root_dir=tmp)
                            sha = hashlib.sha256(path.read_bytes()).hexdigest()
                        self.assertEqual([(t["speaker"], t["text"]) for t in turns], [
                            ("P1", "Arrived early."),
                            ("P2", "Staff answered quickly."),
                        ])
                        self.assertEqual(parser.last_document_metadata["summary_paren.docx"]["summary_of_session"],
                                         "Paperwork took weeks.")
                        results = AtlasEngine(str(CODEBOOK)).process_turns(turns, {"summary_paren.docx": sha})
                        self.assertEqual(results["total_documents"], 2)
        self.assertEqual(probes, 54)


if __name__ == "__main__":
    unittest.main()
