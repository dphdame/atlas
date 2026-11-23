"""[SOFTWARE_TEST FIXTURE — DEMONSTRATES SOFTWARE MECHANICS ONLY, NOT EMPIRICAL FINDINGS]

ATLAS v1.2 slice 2: multi-group notes mode UI, statistical guardrails and the
generic, exclusion-fenced GBI focus-group starter codebook.

Covers:
- config/gbi_focus_group_starter.yaml compiles to the 8 generic domains, and its
  exclusion fences stop the prefix matcher from firing on card / career / care /
  cargo / carbon / parent / current / different / billion / debtor.
- atlas_engine: QUOTE_COLUMNS keeps the 16 v1.1 columns in order and appends the
  4 notes provenance columns; process_corpus accepts include_evidence_types and
  notes_unit_level and returns document_structures, notes_metadata and a
  reference-only note_taker_themes_df; exports verify on notes corpora.
- app.py (driven through streamlit.testing.v1.AppTest): the sidebar "Data Type"
  radio auto-selects Group mode for structured notes and can be overridden; Group
  mode shows group-scoped KPIs, an integer g-of-G chart, a group x theme tile
  matrix, literal st.html summaries, a "Quotable Verbatim Only" filter, and in
  Tab 2 hides the binomial SE / 95% CI while Individual mode keeps them.

Every input is a synthetic SOFTWARE_TEST fixture; nothing asserted is an
empirical finding.

Run: .venv/bin/python -m unittest tests/test_v12_group_mode_ui.py -v
"""

import ast
import hashlib
import html
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import docx
import openpyxl
import pandas as pd
import pyarrow as pa
import yaml
from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from atlas_engine import QUOTE_COLUMNS, AtlasEngine  # noqa: E402
from universal_transcript_parser import UniversalTranscriptParser  # noqa: E402

SAMPLES = REPO / "data" / "samples"
GBI_CODEBOOK = REPO / "config" / "gbi_focus_group_starter.yaml"
TREATMENT_DOCX = SAMPLES / "software_test_gbi_group_treatment.docx"
CONTROL_DOCX = SAMPLES / "software_test_gbi_group_control.docx"
TREATMENT_ID = "data/samples/software_test_gbi_group_treatment.docx"
CONTROL_ID = "data/samples/software_test_gbi_group_control.docx"

KP, QUOTE, OBS, THEMES = "key_point_paraphrase", "notable_quote_verbatim", "observation", "themes_summary"

V11_QUOTE_COLUMNS = [
    "domain_id", "domain_name", "document_name", "source_id", "unit_id", "turn_id", "line_number",
    "timestamp", "speaker", "text", "char_start", "char_end", "match_char_start", "match_char_end",
    "match_text", "source_sha256",
]
NOTES_QUOTE_COLUMNS = ["evidence_type", "question_id", "group_id", "participant_id"]

GBI_DOMAIN_IDS = [
    "housing_rent_stability", "food_groceries_basic_needs", "debt_financial_breathing_room",
    "employment_education_career", "transportation_mobility", "family_caregiving_wellbeing",
    "stress_relief_mental_health", "program_enrollment_paperwork",
]

DATA_TYPE_INDIVIDUAL = "Individual transcripts / survey responses"
DATA_TYPE_GROUP = "Group / summarized notes"
CORPUS_GBI_NOTES = "Sample: Multi-Group Focus-Group Notes DOCX (SOFTWARE_TEST)"
GROUP_TABLE_COLUMNS = [
    "Domain ID", "Domain", "Groups Reporting", "Total Groups (G)", "Group Share (%)",
    "Distinct Participant Voices", "Verbatim Quotes", "Paraphrased Key Points", "Matching Entries",
]
THEMES_EXPANDER = "Note-Taker Themes Summary (Reference Only — Not Counted in Prevalence)"
NON_VOICES = {"", "Unknown", "NoteTaker_Themes"}

# Adversarial labels Streamlit's Markdown / shortcode plugins would rewrite.
ADVERSARIAL_DOMAIN = "Forms <b>bold</b> [link](https://example.invalid/a) :smile: *emph* $x$ & co"
ADVERSARIAL_CODEBOOK = yaml.safe_dump({
    "project": "SOFTWARE_TEST Adversarial Group Labels",
    "domains": [{"id": "adv_forms", "name": ADVERSARIAL_DOMAIN, "roots_en": ["paperwork", "forms"]}],
}, allow_unicode=True, sort_keys=False).encode("utf-8")
ADVERSARIAL_GROUP_FILE = "software_test_*grp*_[a]_<i>.docx"

UPLOAD_TXT_A = b"[SOFTWARE_TEST]\nP1: The paperwork took two visits.\nP2: My car broke down on the way.\n"
UPLOAD_TXT_B = b"[SOFTWARE_TEST]\nP1: I filled the forms at home.\n"


def load_app_helpers(*names):
    """Compile app.py's top-level imports, constants and the named helper functions
    without running the Streamlit page script."""
    tree = ast.parse((REPO / "app.py").read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            body.append(node)
        elif isinstance(node, ast.Try) and all(isinstance(n, (ast.Import, ast.ImportFrom)) for n in node.body):
            body.append(node)  # guarded optional imports (LxmlError)
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets):
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            body.append(node)
    missing = set(names) - {n.name for n in body if isinstance(n, ast.FunctionDef)}
    if missing:
        raise AssertionError(f"app.py defines no top-level function(s): {sorted(missing)}")
    namespace = {"__name__": "atlas_app_helpers", "__file__": str(REPO / "app.py")}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(REPO / "app.py"), "exec"), namespace)
    return namespace


def notes_docx_bytes(rows, title="SOFTWARE_TEST synthetic focus-group notes"):
    """A minimal 3-column structured notes document (Question 1 heading + notes table)."""
    document = docx.Document()
    document.add_paragraph(title)
    document.add_paragraph("Question 1: How did the enrollment steps go?")
    table = document.add_table(rows=1 + len(rows), cols=3)
    for col, label in enumerate(["Key Points", "Notable Quotes", "Observations"]):
        table.rows[0].cells[col].text = label
    for r_idx, row in enumerate(rows, start=1):
        for col, cell in enumerate(row):
            table.rows[r_idx].cells[col].text = cell
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


UPLOAD_NOTES_ROWS = [
    ("P1: Brought the forms twice.", "\"The paperwork was long.\"", "Smiled."),
    ("P2: Waited for a callback.", "", "Looked frustrated."),
]


def contrast(fg, bg):
    def lum(hex_color):
        rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def engine_on_texts(texts):
    """Run the GBI codebook over synthetic single-turn texts; {text: set(domain_ids)}."""
    turns, hashes = [], {}
    for idx, text in enumerate(texts):
        sid = f"software_test_fence_{idx}.txt"
        turns.append({"source_id": sid, "unit_id": sid, "document_name": sid, "speaker": "P1", "text": text})
        hashes[sid] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    results = AtlasEngine(str(GBI_CODEBOOK)).process_turns(turns, hashes)
    out = {t: set() for t in texts}
    for _, q in results["quotes_df"].iterrows():
        out[texts[int(q["source_id"].split("_")[-1].split(".")[0])]].add(q["domain_id"])
    return out


# ------------------------------------------------------------------------------
# 1. Generic GBI starter codebook
# ------------------------------------------------------------------------------
class GbiStarterCodebookTests(unittest.TestCase):
    def test_compiles_eight_generic_domains_with_roots(self):
        engine = AtlasEngine(str(GBI_CODEBOOK))
        self.assertEqual([r["id"] for r in engine.compiled_rules], GBI_DOMAIN_IDS)
        for rule in engine.compiled_rules:
            with self.subTest(rule=rule["id"]):
                self.assertTrue(rule["root_patterns"], "every domain must compile real roots")
                self.assertTrue(rule["name"].strip())
        raw = yaml.safe_load(GBI_CODEBOOK.read_text(encoding="utf-8"))
        self.assertIn("project", raw)
        for domain in raw["domains"]:
            with self.subTest(domain=domain["id"]):
                self.assertTrue(domain.get("exclude_fences") is None or domain.get("exclude_window") is not None,
                                "a fence without a token window would drop the whole turn")

    def test_prefix_false_triggers_are_fenced(self):
        negatives = {
            "I paid with my credit card.": "transportation_mobility",
            "Two gift cards came in the mail.": "transportation_mobility",
            "I want a new career in nursing.": "transportation_mobility",
            "Other careers felt out of reach.": "transportation_mobility",
            "She takes care of everything.": "transportation_mobility",
            "We were careful with every purchase.": "transportation_mobility",
            "The cargo van belonged to my uncle.": "transportation_mobility",
            "The carbon monoxide alarm beeped.": "transportation_mobility",
            "My parent watched the kids.": "housing_rent_stability",
            "My parents helped a lot.": "housing_rent_stability",
            "The current situation is fine.": "housing_rent_stability",
            "We are currently okay.": "housing_rent_stability",
            "Things are different now.": "housing_rent_stability",
            "A billion things happened.": "debt_financial_breathing_room",
            "The debtor letter was confusing.": "debt_financial_breathing_room",
        }
        positives = {
            "My car broke down last week.": "transportation_mobility",
            "We pay rent on the first.": "housing_rent_stability",
            "The electric bill was late.": "debt_financial_breathing_room",
            "Credit card debt kept growing.": "debt_financial_breathing_room",
            "Brought the wrong paperwork to the office.": "program_enrollment_paperwork",
            "We bought groceries for the week.": "food_groceries_basic_needs",
        }
        matched = engine_on_texts(list(negatives) + list(positives))
        for text, domain in negatives.items():
            with self.subTest(negative=text):
                self.assertNotIn(domain, matched[text])
        for text, domain in positives.items():
            with self.subTest(positive=text):
                self.assertIn(domain, matched[text])

    def test_codebook_is_generic_and_public_safe(self):
        text = GBI_CODEBOOK.read_text(encoding="utf-8").lower()
        for banned in ("yet", "chw", "santa clara", "san jos", "promotora", "/users/"):
            self.assertNotRegex(text, rf"\b{banned}\b", banned)

    def test_starter_codebook_matches_notes_fixtures(self):
        results = AtlasEngine(str(GBI_CODEBOOK)).process_corpus(
            [str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO))
        freq = results["frequencies_df"].set_index("domain_id")
        self.assertEqual(int(freq.loc["program_enrollment_paperwork", "documents_reporting"]), 2)


# ------------------------------------------------------------------------------
# 2. Engine notes metadata and provenance
# ------------------------------------------------------------------------------
class EngineNotesMetadataTests(unittest.TestCase):
    def test_quote_columns_append_notes_provenance_after_v11(self):
        self.assertEqual(QUOTE_COLUMNS[:16], V11_QUOTE_COLUMNS)
        self.assertEqual(QUOTE_COLUMNS[16:], NOTES_QUOTE_COLUMNS)

    def test_notes_corpus_populates_provenance_columns(self):
        results = AtlasEngine(str(GBI_CODEBOOK)).process_corpus(
            [str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO))
        quotes = results["quotes_df"]
        self.assertEqual(list(quotes.columns), QUOTE_COLUMNS)
        self.assertFalse(quotes.empty)
        self.assertTrue(set(quotes["evidence_type"]) <= {KP, QUOTE})
        self.assertTrue(all(str(q).startswith("Question ") for q in quotes["question_id"]))
        self.assertEqual(set(quotes["group_id"]), set(quotes["source_id"]))
        for _, q in quotes.iterrows():
            self.assertEqual(q["participant_id"], f"{q['source_id']}::{q['speaker']}")

    def test_legacy_turns_store_empty_strings(self):
        sid = "software_test_legacy.txt"
        turns = [{"source_id": sid, "unit_id": sid, "document_name": sid, "speaker": "P1",
                  "text": "The paperwork was long."}]
        quotes = AtlasEngine(str(GBI_CODEBOOK)).process_turns(turns, {sid: "0" * 64})["quotes_df"]
        self.assertEqual(len(quotes), 1)
        for col in NOTES_QUOTE_COLUMNS:
            self.assertEqual(quotes.iloc[0][col], "")

    def test_process_corpus_notes_kwargs_and_return_keys(self):
        engine = AtlasEngine(str(GBI_CODEBOOK))
        default = engine.process_corpus([str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO))
        with_obs = engine.process_corpus(
            [str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO),
            include_evidence_types=(KP, QUOTE, OBS), notes_unit_level="group")
        self.assertEqual(default["total_documents"], 2)
        self.assertEqual(with_obs["total_documents"], 2)
        self.assertEqual(default["participant_turns_analyzed"], 22)
        self.assertEqual(with_obs["participant_turns_analyzed"], 27)
        self.assertIn(OBS, set(with_obs["tagged_turns_df"]["evidence_type"]))
        self.assertNotIn(OBS, set(default["tagged_turns_df"]["evidence_type"]))

        self.assertEqual(default["document_structures"],
                         {TREATMENT_ID: "focus_group_notes", CONTROL_ID: "focus_group_notes"})
        self.assertEqual(set(default["notes_metadata"]), {TREATMENT_ID, CONTROL_ID})
        self.assertIn("questions", default["notes_metadata"][TREATMENT_ID])

        themes = default["note_taker_themes_df"]
        self.assertIsInstance(themes, pd.DataFrame)
        self.assertEqual(len(themes), 5)
        self.assertEqual(set(themes["speaker"]), {"NoteTaker_Themes"})
        self.assertEqual(set(themes["evidence_type"]), {THEMES})
        self.assertEqual(set(themes["source_id"]), {TREATMENT_ID, CONTROL_ID})
        # Reference only: never coded or counted.
        self.assertNotIn("NoteTaker_Themes", set(default["quotes_df"]["speaker"]))
        self.assertNotIn(THEMES, set(default["tagged_turns_df"]["evidence_type"]))

        participant = engine.process_corpus([str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO),
                                            notes_unit_level="participant")
        self.assertEqual(participant["total_documents"], 7)
        with self.assertRaises(ValueError):
            engine.process_corpus([str(TREATMENT_DOCX)], root_dir=str(REPO), notes_unit_level="room")

    def test_v11_corpus_keeps_results_and_reports_transcript_structure(self):
        engine = AtlasEngine(str(REPO / "config" / "pfl_case_study_codebook.yaml"))
        files = [str(SAMPLES / "software_test_bilingual_interview.txt"), str(SAMPLES / "software_test_zoom_session.vtt")]
        results = engine.process_corpus(files, root_dir=str(REPO))
        self.assertEqual(set(results["document_structures"].values()), {"transcript"})
        self.assertEqual(results["notes_metadata"], {})
        self.assertTrue(results["note_taker_themes_df"].empty)
        self.assertEqual(list(results["quotes_df"].columns), QUOTE_COLUMNS)

    def test_exports_round_trip_and_verify_on_both_corpora(self):
        corpora = {
            "notes": ("gbi_focus_group_starter.yaml", [TREATMENT_DOCX, CONTROL_DOCX], None),
            "v11": ("pfl_case_study_codebook.yaml",
                    [SAMPLES / "software_test_bilingual_interview.txt", SAMPLES / "software_test_zoom_session.vtt"], None),
            "survey": ("pfl_case_study_codebook.yaml", [SAMPLES / "software_test_survey.csv"],
                       {"text_col": "response", "id_col": "respondent_id", "speaker_col": "role"}),
        }
        for label, (codebook, files, tab) in corpora.items():
            with self.subTest(corpus=label), tempfile.TemporaryDirectory() as tmp:
                engine = AtlasEngine(str(REPO / "config" / codebook))
                results = engine.process_corpus([str(f) for f in files], root_dir=str(REPO), tabular_options=tab)
                engine.export_results(results, tmp)
                ok, problems = AtlasEngine.verify_workbook_integrity(
                    str(Path(tmp) / "actuarial_parameter_matrix.xlsx"), str(Path(tmp) / "provenance_manifest.json"))
                self.assertTrue(ok, problems)
                quotes = results["quotes_df"]
                full_stem = "coded_evidence_inventory" if label == "notes" else "verbatim_quotes_inventory"
                self.assertEqual((Path(tmp) / "coded_evidence_inventory.csv").is_file(), label == "notes")
                csv_df = pd.read_csv(Path(tmp) / f"{full_stem}.csv", keep_default_na=False)
                pq_df = pd.read_parquet(Path(tmp) / f"{full_stem}.parquet")
                self.assertEqual(list(csv_df.columns), QUOTE_COLUMNS)
                self.assertEqual(list(pq_df.columns), QUOTE_COLUMNS)
                for col in NOTES_QUOTE_COLUMNS:
                    self.assertEqual(list(pq_df[col]), list(quotes[col]))
                    self.assertEqual([str(v) for v in csv_df[col]], list(quotes[col]))

    def test_mixed_evidence_exports_label_every_row(self):
        engine = AtlasEngine(str(GBI_CODEBOOK))
        results = engine.process_corpus([str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO),
                                        include_evidence_types=(KP, QUOTE, OBS))
        quotes = results["quotes_df"]
        self.assertTrue({KP, QUOTE, OBS} <= set(quotes["evidence_type"]),
                        "fixture must exercise paraphrases, quotes and observations")
        with tempfile.TemporaryDirectory() as tmp:
            engine.export_results(results, tmp)
            verbatim = pd.read_csv(Path(tmp) / "verbatim_quotes_inventory.csv", keep_default_na=False)
            self.assertEqual(set(verbatim["evidence_type"]), {QUOTE})
            self.assertEqual(len(verbatim), int((quotes["evidence_type"] == QUOTE).sum()))
            pq_verbatim = pd.read_parquet(Path(tmp) / "verbatim_quotes_inventory.parquet")
            self.assertEqual(set(pq_verbatim["evidence_type"]), {QUOTE})
            coded = pd.read_csv(Path(tmp) / "coded_evidence_inventory.csv", keep_default_na=False)
            self.assertEqual(list(coded["evidence_type"]), list(quotes["evidence_type"]))

            wb = openpyxl.load_workbook(Path(tmp) / "actuarial_parameter_matrix.xlsx")
            self.assertNotIn("Verbatim Quotes & Provenance", wb.sheetnames)
            ws = wb["Coded Evidence & Provenance"]
            header = [c.value for c in ws[1]]
            self.assertNotIn("Verbatim Statement", header)
            self.assertIn("Coded Entry Text (see Evidence Type)", header)
            ev_col = header.index("Evidence Type")
            q_col = header.index("Question")
            labels = [row[ev_col] for row in ws.iter_rows(min_row=2, values_only=True)]
            self.assertEqual(len(labels), len(quotes))
            expected = {KP: "Paraphrase (Key Point, not verbatim)", QUOTE: "Verbatim Quote (notes)",
                        OBS: "Note-Taker Observation (not verbatim)"}
            self.assertEqual(labels, [expected[e] for e in quotes["evidence_type"]])
            self.assertEqual([row[q_col] for row in ws.iter_rows(min_row=2, values_only=True)],
                             list(quotes["question_id"]))
            ok, problems = AtlasEngine.verify_workbook_integrity(
                str(Path(tmp) / "actuarial_parameter_matrix.xlsx"), str(Path(tmp) / "provenance_manifest.json"))
            self.assertTrue(ok, problems)

    def test_reused_output_dir_drops_stale_coded_evidence_inventory(self):
        mixed_engine = AtlasEngine(str(GBI_CODEBOOK))
        mixed = mixed_engine.process_corpus([str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO),
                                            include_evidence_types=(KP, QUOTE, OBS))
        v11_engine = AtlasEngine(str(REPO / "config" / "pfl_case_study_codebook.yaml"))
        v11 = v11_engine.process_corpus([str(SAMPLES / "software_test_bilingual_interview.txt")], root_dir=str(REPO))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "software_test_unrelated_note.txt").write_text("SOFTWARE_TEST keep me", encoding="utf-8")
            mixed_engine.export_results(mixed, tmp)
            self.assertTrue((out / "coded_evidence_inventory.csv").is_file())
            self.assertTrue((out / "coded_evidence_inventory.parquet").is_file())
            v11_engine.export_results(v11, tmp)
            self.assertFalse((out / "coded_evidence_inventory.csv").exists(), "stale mixed-evidence CSV left behind")
            self.assertFalse((out / "coded_evidence_inventory.parquet").exists(), "stale mixed-evidence Parquet left behind")
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted([
                "thematic_frequencies.csv", "verbatim_quotes_inventory.csv", "verbatim_quotes_inventory.parquet",
                "actuarial_parameter_matrix.xlsx", "provenance_manifest.json", "software_test_unrelated_note.txt"]),
                "only ATLAS's own conditional outputs are removed; other files are untouched")
            verbatim = pd.read_csv(out / "verbatim_quotes_inventory.csv", keep_default_na=False)
            self.assertEqual(len(verbatim), len(v11["quotes_df"]))
            mixed_engine.export_results(mixed, tmp)
            coded = pd.read_csv(out / "coded_evidence_inventory.csv", keep_default_na=False)
            self.assertEqual(list(coded["evidence_type"]), list(mixed["quotes_df"]["evidence_type"]))

    def test_v11_exports_keep_verbatim_sheet_and_file_set(self):
        engine = AtlasEngine(str(REPO / "config" / "pfl_case_study_codebook.yaml"))
        results = engine.process_corpus([str(SAMPLES / "software_test_bilingual_interview.txt")], root_dir=str(REPO))
        with tempfile.TemporaryDirectory() as tmp:
            engine.export_results(results, tmp)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), sorted([
                "thematic_frequencies.csv", "verbatim_quotes_inventory.csv", "verbatim_quotes_inventory.parquet",
                "actuarial_parameter_matrix.xlsx", "provenance_manifest.json"]))
            wb = openpyxl.load_workbook(Path(tmp) / "actuarial_parameter_matrix.xlsx")
            header = [c.value for c in wb["Verbatim Quotes & Provenance"][1]]
            self.assertEqual(header, ["Domain ID", "Source ID", "Unit ID", "Line", "Timestamp", "Speaker",
                                      "Match Start", "Match End", "Verbatim Statement", "Source File SHA-256"])
            verbatim = pd.read_csv(Path(tmp) / "verbatim_quotes_inventory.csv", keep_default_na=False)
            self.assertEqual(len(verbatim), len(results["quotes_df"]))

    def test_detect_docx_structure(self):
        self.assertEqual(UniversalTranscriptParser.detect_docx_structure(str(TREATMENT_DOCX)), "structured_notes")
        self.assertEqual(UniversalTranscriptParser.detect_docx_structure(
            str(SAMPLES / "software_test_teams_multiline.docx")), "transcript")


# ------------------------------------------------------------------------------
# 3. Pure app helpers
# ------------------------------------------------------------------------------
class GroupHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = load_app_helpers("build_group_theme_matrix", "describe_group_prevalence_chart",
                                 "describe_group_matrix_chart", "build_group_frequency_table",
                                 "group_labels_for", "count_distinct_voices", "chart_summary_html")
        cls.results = AtlasEngine(str(GBI_CODEBOOK)).process_corpus(
            [str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO))

    def test_group_frequency_table(self):
        freq, quotes = self.results["frequencies_df"], self.results["quotes_df"]
        table = self.h["build_group_frequency_table"](freq, quotes, 2)
        self.assertEqual(list(table.columns), GROUP_TABLE_COLUMNS)
        self.assertEqual(len(table), len(freq))
        row = table.set_index("Domain ID").loc["program_enrollment_paperwork"]
        dq = quotes[quotes["domain_id"] == "program_enrollment_paperwork"]
        self.assertEqual(int(row["Groups Reporting"]), 2)
        self.assertEqual(int(row["Total Groups (G)"]), 2)
        self.assertAlmostEqual(float(row["Group Share (%)"]), 100.0)
        voices = {(s, p) for s, p in zip(dq["source_id"], dq["speaker"]) if p not in NON_VOICES}
        self.assertEqual(int(row["Distinct Participant Voices"]), len(voices))
        self.assertEqual(int(row["Verbatim Quotes"]), int((dq["evidence_type"] == QUOTE).sum()))
        self.assertEqual(int(row["Paraphrased Key Points"]), int((dq["evidence_type"] == KP).sum()))
        self.assertEqual(int(row["Matching Entries"]), len(dq))

    def test_group_theme_matrix(self):
        freq, quotes, hashes = self.results["frequencies_df"], self.results["quotes_df"], self.results["file_hashes"]
        matrix = self.h["build_group_theme_matrix"](freq, quotes, hashes)
        self.assertEqual(len(matrix), len(freq) * 2)
        for col in ("domain_name", "group_label", "present", "matching_entries", "distinct_voices", "cell_label"):
            self.assertIn(col, matrix.columns)
        self.assertEqual(set(matrix["group_label"]),
                         {"software_test_gbi_group_treatment.docx", "software_test_gbi_group_control.docx"})
        for _, r in matrix.iterrows():
            with self.subTest(domain=r["domain_name"], group=r["group_label"]):
                sid = TREATMENT_ID if "treatment" in r["group_label"] else CONTROL_ID
                name_ids = freq.loc[freq["domain_name"] == r["domain_name"], "domain_id"]
                dq = quotes[(quotes["domain_id"] == name_ids.iloc[0]) & (quotes["source_id"] == sid)]
                voices = len({p for p in dq["speaker"] if p not in NON_VOICES})
                self.assertEqual(int(r["matching_entries"]), len(dq))
                self.assertEqual(int(r["distinct_voices"]), voices)
                self.assertEqual(bool(r["present"]), len(dq) > 0)
                self.assertEqual(r["cell_label"], f"{voices}v" if voices else ("✓" if len(dq) else "—"))

    def test_matrix_unknown_only_cell_is_checkmark(self):
        freq = pd.DataFrame([{"domain_id": "d1", "domain_name": "SOFTWARE_TEST D1"}])
        quotes = pd.DataFrame([{"domain_id": "d1", "source_id": "g/a.txt", "speaker": "Unknown",
                                "evidence_type": "verbatim_turn"}])
        matrix = self.h["build_group_theme_matrix"](freq, quotes, {"g/a.txt": "0", "h/b.txt": "1"})
        labels = dict(zip(matrix["group_label"], matrix["cell_label"]))
        self.assertEqual(labels, {"a.txt": "✓", "b.txt": "—"})

    def test_group_labels_disambiguate_shared_basenames(self):
        labels = self.h["group_labels_for"](["x/notes.docx", "y/notes.docx", "z/other.docx"])
        self.assertEqual(labels, {"x/notes.docx": "x/notes.docx", "y/notes.docx": "y/notes.docx",
                                  "z/other.docx": "other.docx"})

    def test_descriptions_are_deterministic_and_use_g_of_g(self):
        freq, quotes = self.results["frequencies_df"], self.results["quotes_df"]
        table = self.h["build_group_frequency_table"](freq, quotes, 2)
        text = self.h["describe_group_prevalence_chart"](table, 2)
        self.assertEqual(text, self.h["describe_group_prevalence_chart"](table, 2))
        self.assertIn("2 of 2 focus groups", text)
        self.assertNotIn("CI", text)
        matrix = self.h["build_group_theme_matrix"](freq, quotes, self.results["file_hashes"])
        mtext = self.h["describe_group_matrix_chart"](matrix, 2)
        self.assertEqual(mtext, self.h["describe_group_matrix_chart"](matrix, 2))
        self.assertIn("2 focus groups", mtext)
        self.assertIn("software_test_gbi_group_treatment.docx", mtext)
        empty = pd.DataFrame(columns=GROUP_TABLE_COLUMNS)
        self.assertEqual(self.h["describe_group_prevalence_chart"](empty, 2),
                         "No domains defined in the active codebook.")


# ------------------------------------------------------------------------------
# 4. Live app (AppTest)
# ------------------------------------------------------------------------------
def boot():
    at = AppTest.from_file(str(REPO / "app.py"), default_timeout=120)
    at.run()
    return at


def widget(at, accessor, label):
    for w in getattr(at, accessor):
        if w.label == label:
            return w
    raise AssertionError(f"no {accessor} labelled {label!r}; have {[w.label for w in getattr(at, accessor)]}")


def has_widget(at, accessor, label):
    return any(w.label == label for w in getattr(at, accessor))


def metric(at, label):
    return int(str(widget(at, "metric", label).value).replace(",", ""))


def frames(at):
    return [el.value for el in at.dataframe if isinstance(el.value, pd.DataFrame)]


def chart_specs(at):
    return [json.loads(c.proto.spec) for c in at.get("vega_lite_chart")]


def chart_frames(at, description):
    """The Arrow datasets behind the chart whose Vega-Lite description is `description`."""
    for c in at.get("vega_lite_chart"):
        if json.loads(c.proto.spec).get("description") == description:
            return [pa.ipc.open_stream(ds.data.data).read_all().to_pandas() for ds in c.proto.datasets]
    raise AssertionError(f"no chart described {description!r}")


def choose_corpus(at, needle):
    box = widget(at, "selectbox", "Corpus Dataset")
    box.select(next(o for o in box.options if needle in o))
    at.run()
    return at


def upload(at, files, codebook=None, codebook_name=None):
    choose_corpus(at, "Upload")
    if codebook_name is not None:
        widget(at, "selectbox", "Active YAML Codebook").select(codebook_name)
        at.run()
    if codebook is not None:
        widget(at, "selectbox", "Active YAML Codebook").select("Upload Custom Codebook (.yaml)")
        at.run()
    next(u for u in at.file_uploader if u.label.startswith("Upload Transcript")).set_value(files)
    if codebook is not None:
        next(u for u in at.file_uploader if u.label.startswith("Upload Custom Codebook")).set_value(
            ("software_test_codebook.yaml", codebook, "application/x-yaml"))
    at.run()
    return at


def assert_clean(test, at):
    test.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
    test.assertEqual(len(at.error), 0, [e.value for e in at.error])


def expected_results(include=None):
    return AtlasEngine(str(GBI_CODEBOOK)).process_corpus(
        [str(TREATMENT_DOCX), str(CONTROL_DOCX)], root_dir=str(REPO), include_evidence_types=include)


class GroupModeAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = load_app_helpers("describe_group_prevalence_chart", "describe_group_matrix_chart",
                                       "build_group_frequency_table", "build_group_theme_matrix",
                                       "group_labels_for", "count_distinct_voices", "chart_summary_html")
        cls.at = choose_corpus(boot(), "Multi-Group")

    def test_sample_registered_without_moving_default(self):
        box = widget(boot(), "selectbox", "Corpus Dataset")
        self.assertIn("Bilingual", box.options[0])
        self.assertEqual(box.value, box.options[0])
        self.assertIn(CORPUS_GBI_NOTES, box.options)
        self.assertLess(box.options.index(CORPUS_GBI_NOTES), next(i for i, o in enumerate(box.options) if "Upload" in o))

    def test_default_boot_is_individual(self):
        at = boot()
        assert_clean(self, at)
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_INDIVIDUAL)
        self.assertEqual(list(widget(at, "radio", "Data Type").options), [DATA_TYPE_INDIVIDUAL, DATA_TYPE_GROUP])
        self.assertFalse(has_widget(at, "checkbox", "Include Note-Taker Observations"))
        self.assertTrue(has_widget(at, "metric", "Analytical Units (N)"))

    def test_auto_selects_group_mode_and_codebook(self):
        at = self.at
        assert_clean(self, at)
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_GROUP)
        self.assertEqual(widget(at, "selectbox", "Active YAML Codebook").value, "gbi_focus_group_starter.yaml")
        self.assertFalse(widget(at, "checkbox", "Include Note-Taker Observations").value)

    def test_group_kpis_are_group_scoped(self):
        at, res = self.at, expected_results()
        tagged = res["tagged_turns_df"]
        voices = {(s, p) for s, p in zip(tagged["source_id"], tagged["speaker"]) if p not in NON_VOICES}
        bare = {p for p in tagged["speaker"] if p not in NON_VOICES}
        self.assertEqual(metric(at, "Focus Groups (G)"), 2)
        self.assertEqual(metric(at, "Distinct Participant Voices"), len(voices))
        self.assertGreater(len(voices), len(bare), "P1 in two groups must count as two voices")
        self.assertEqual(metric(at, "Coded Notes Entries"), res["participant_turns_analyzed"])
        self.assertEqual(metric(at, "Active Domains"), len(res["frequencies_df"]))
        self.assertFalse(has_widget(at, "metric", "Analytical Units (N)"))

    def test_group_charts_are_integer_and_summarised_literally(self):
        at, res = self.at, expected_results()
        table = self.helpers["build_group_frequency_table"](res["frequencies_df"], res["quotes_df"], 2)
        matrix = self.helpers["build_group_theme_matrix"](res["frequencies_df"], res["quotes_df"], res["file_hashes"])
        g_text = self.helpers["describe_group_prevalence_chart"](table, 2)
        m_text = self.helpers["describe_group_matrix_chart"](matrix, 2)
        specs = chart_specs(at)
        descriptions = [s.get("description", "") for s in specs]
        self.assertIn(g_text, descriptions)
        self.assertIn(m_text, descriptions)
        self.assertEqual(descriptions.count(g_text), 2, "Tab 1 and Tab 2 each draw the g-of-G chart")
        summaries = [h.value for h in at.html if "atlas-chart-summary" in h.value]
        to_html = self.helpers["chart_summary_html"]
        self.assertIn(to_html(g_text), summaries)
        self.assertIn(to_html(m_text), summaries)
        self.assertFalse([c.value for c in at.caption if c.value.startswith("Chart summary:")])

        g_spec = next(s for s in specs if s.get("description") == g_text)
        dumped = json.dumps(g_spec)
        self.assertIn("Groups Reporting (out of 2 focus groups)", dumped)
        self.assertIn('"values": [0, 1, 2]', dumped)
        self.assertIn('"format": "d"', dumped)
        self.assertIn('"domain": [0, 2]', dumped)
        g_data = pd.concat(chart_frames(at, g_text))
        expected_labels = {f"{g}/2" for g in table["Groups Reporting"]}
        self.assertEqual(set(g_data["bar_label"]), expected_labels)
        self.assertIn("2/2", expected_labels)
        self.assertTrue(all(float(v).is_integer() for v in g_data["groups_reporting"]))
        m_data = pd.concat(chart_frames(at, m_text))
        self.assertEqual(sorted(m_data["cell_label"]), sorted(matrix["cell_label"]))
        m_spec = next(s for s in specs if s.get("description") == m_text)
        self.assertIn('"rect"', json.dumps(m_spec))
        self.assertIn('"text"', json.dumps(m_spec))

    def test_group_frequency_table_and_themes_reference(self):
        at = self.at
        tables = [f for f in frames(at) if list(f.columns) == GROUP_TABLE_COLUMNS]
        self.assertEqual(len(tables), 2, "Tab 1 frequency table and Tab 2 group summary matrix")
        expanders = [e.label for e in at.expander]
        self.assertIn(THEMES_EXPANDER, expanders)
        themes = expected_results()["note_taker_themes_df"]
        corpus = "\n".join(str(m.value) for m in at.markdown)
        for text in themes["text"]:
            self.assertIn(html.escape(text), corpus)

    def test_tab2_suppresses_binomial_se_and_ci(self):
        at = self.at
        for f in frames(at):
            for col in ("binomial_se", "ci95_low_pct", "ci95_high_pct", "proportion"):
                self.assertNotIn(col, f.columns)
        self.assertFalse([c.value for c in at.caption if "Whiskers show" in c.value])
        self.assertFalse([c.value for c in at.caption if "binomial standard error SE" in c.value])
        self.assertTrue([i.value for i in at.info if "Binomial" in i.value and "hidden" in i.value
                         and "Group mode" in i.value])
        self.assertNotIn("rule", json.dumps(chart_specs(at)))
        labels = {d.label for d in at.get("download_button")}
        for name in ("actuarial_parameter_matrix.xlsx", "provenance_manifest.json", "verbatim_quotes_inventory.csv"):
            self.assertTrue(any(name in label for label in labels), name)
        self.assertTrue([s.value for s in at.success if "Workbook integrity check passed" in s.value])

    def test_evidence_browser_filters_and_badges(self):
        at = choose_corpus(boot(), "Multi-Group")
        evidence = next(f for f in frames(at) if "evidence_type" in f.columns and "match_text" in f.columns)
        for col in ("evidence_type", "group_label", "question_id"):
            self.assertIn(col, evidence.columns)
        self.assertEqual(set(evidence["evidence_type"]), {KP, QUOTE})
        cards = [m.value for m in at.markdown if '<div class="quote-box">' in m.value]
        self.assertTrue(any("Verbatim Quote" in c for c in cards))
        self.assertTrue(any("Paraphrase (Key Point)" in c for c in cards))
        self.assertTrue(has_widget(at, "selectbox", "Filter by group"))
        self.assertTrue(has_widget(at, "selectbox", "Filter by question"))

        widget(at, "checkbox", "Quotable Verbatim Only").check()
        at.run()
        assert_clean(self, at)
        evidence = next(f for f in frames(at) if "evidence_type" in f.columns and "match_text" in f.columns)
        self.assertEqual(set(evidence["evidence_type"]), {QUOTE})
        cards = [m.value for m in at.markdown if '<div class="quote-box">' in m.value]
        self.assertTrue(cards)
        self.assertFalse(any("Paraphrase (Key Point)" in c for c in cards))

        group_box = widget(at, "selectbox", "Filter by group")
        group_box.select("software_test_gbi_group_control.docx")
        at.run()
        evidence = next(f for f in frames(at) if "evidence_type" in f.columns and "match_text" in f.columns)
        self.assertEqual(set(evidence["group_label"]), {"software_test_gbi_group_control.docx"})

        widget(at, "text_input", "Search verbatim text").input("zzzz-no-such-text")
        at.run()
        self.assertTrue([i.value for i in at.info if "verbatim" in i.value.lower()])

    def test_observations_checkbox_changes_entries(self):
        at = choose_corpus(boot(), "Multi-Group")
        widget(at, "checkbox", "Include Note-Taker Observations").check()
        at.run()
        assert_clean(self, at)
        res = expected_results((KP, QUOTE, OBS))
        self.assertEqual(metric(at, "Coded Notes Entries"), res["participant_turns_analyzed"])
        self.assertEqual(metric(at, "Focus Groups (G)"), 2)

    def test_individual_override_on_structured_notes_keeps_guardrail(self):
        at = choose_corpus(boot(), "Multi-Group")
        widget(at, "radio", "Data Type").set_value(DATA_TYPE_INDIVIDUAL)
        at.run()
        assert_clean(self, at)
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_INDIVIDUAL)
        self.assertTrue(has_widget(at, "metric", "Analytical Units (N)"))
        # Notes are still one unit per focus-group file, so no binomial interval is shown.
        self.assertEqual(metric(at, "Analytical Units (N)"), 2)
        for f in frames(at):
            for col in ("binomial_se", "ci95_low_pct", "ci95_high_pct", "proportion"):
                self.assertNotIn(col, f.columns)
        self.assertFalse([c.value for c in at.caption if "Whiskers show" in c.value])
        self.assertNotIn('"rule"', json.dumps(chart_specs(at)))
        self.assertTrue([i.value for i in at.info if "structured focus-group notes" in i.value
                         and "hidden" in i.value])
        # Individual-mode quote browser still labels paraphrases.
        evidence = next(f for f in frames(at) if "match_text" in f.columns)
        self.assertIn("evidence_type", evidence.columns)
        cards = [m.value for m in at.markdown if '<div class="quote-box">' in m.value]
        self.assertTrue(any("Paraphrase (Key Point)" in c for c in cards))
        at.run()
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_INDIVIDUAL,
                         "a rerun on the same corpus keeps the manual choice")

    def test_exports_offer_verbatim_only_and_labelled_coded_evidence(self):
        at = self.at
        labels = [d.label for d in at.get("download_button")]
        self.assertTrue(any("coded_evidence_inventory.csv" in label for label in labels))
        self.assertTrue(any("verbatim_quotes_inventory.csv" in label for label in labels))

    def test_topic_medoids_are_labelled_by_evidence_type(self):
        at, res = self.at, expected_results()
        self.assertFalse([c.value for c in at.caption if "real participant turn" in c.value])
        topics = next(f for f in frames(at) if "medoid_text" in f.columns)
        self.assertIn("medoid_evidence_type", topics.columns)
        by_text = {}
        for _, r in res["tagged_turns_df"].iterrows():
            by_text.setdefault(r["text"], set()).add(r["evidence_type"])
        for _, r in topics.iterrows():
            with self.subTest(medoid=r["medoid_text"]):
                self.assertIn(r["medoid_evidence_type"], by_text[r["medoid_text"]])
        topic_cards = [m.value for m in at.markdown if '<div class="quote-box topic-box">' in m.value
                       and "Top terms" in m.value]
        self.assertTrue(topic_cards)
        self.assertTrue(all("atlas-evidence-badge" in c for c in topic_cards))


class IndividualModeAppTests(unittest.TestCase):
    def test_individual_tab2_keeps_binomial_se_and_ci(self):
        at = boot()
        assert_clean(self, at)
        matrix = next(f for f in frames(at) if "binomial_se" in f.columns)
        for col in ("ci95_low_pct", "ci95_high_pct", "n_units", "proportion"):
            self.assertIn(col, matrix.columns)
        self.assertTrue([c.value for c in at.caption if "Whiskers show" in c.value])
        self.assertFalse([i.value for i in at.info if "Group mode" in i.value])
        self.assertFalse([i.value for i in at.info if "structured focus-group notes" in i.value])
        self.assertFalse(any(list(f.columns) == GROUP_TABLE_COLUMNS for f in frames(at)))
        self.assertTrue([c.value for c in at.caption if "real participant turn" in c.value])
        topics = next(f for f in frames(at) if "medoid_text" in f.columns)
        self.assertNotIn("medoid_evidence_type", topics.columns)
        labels = [d.label for d in at.get("download_button")]
        self.assertFalse(any("coded_evidence_inventory" in label for label in labels))


class UploadDetectionAppTests(unittest.TestCase):
    def test_uploaded_three_column_docx_auto_selects_group(self):
        files = [("software_test_upload_room_a.docx", notes_docx_bytes(UPLOAD_NOTES_ROWS), "application/octet-stream"),
                 ("software_test_upload_room_b.docx", notes_docx_bytes(UPLOAD_NOTES_ROWS[:1]), "application/octet-stream")]
        at = upload(boot(), files)
        assert_clean(self, at)
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_GROUP)
        self.assertEqual(metric(at, "Focus Groups (G)"), 2)
        self.assertEqual(metric(at, "Distinct Participant Voices"), 3)

    def test_plain_txt_defaults_individual_and_can_override_to_group(self):
        files = [("software_test_room_a.txt", UPLOAD_TXT_A, "text/plain"),
                 ("software_test_room_b.txt", UPLOAD_TXT_B, "text/plain")]
        at = upload(boot(), files, codebook_name="gbi_focus_group_starter.yaml")
        assert_clean(self, at)
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_INDIVIDUAL)
        widget(at, "radio", "Data Type").set_value(DATA_TYPE_GROUP)
        at.run()
        assert_clean(self, at)
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_GROUP)
        self.assertEqual(metric(at, "Focus Groups (G)"), 2)
        self.assertFalse(any("binomial_se" in f.columns for f in frames(at)))
        self.assertTrue([i.value for i in at.info if "Group mode" in i.value])
        cards = [m.value for m in at.markdown if '<div class="quote-box">' in m.value]
        self.assertTrue(cards and all("Transcript / Survey" in c for c in cards))

    def test_corrupt_docx_upload_does_not_crash_detection(self):
        files = [("software_test_corrupt.docx", b"PK\x03\x04 not really a docx", "application/octet-stream")]
        at = upload(boot(), files)
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_INDIVIDUAL)

    def test_adversarial_group_and_domain_names_are_escaped(self):
        files = [(ADVERSARIAL_GROUP_FILE, notes_docx_bytes(UPLOAD_NOTES_ROWS), "application/octet-stream"),
                 ("software_test_plain_room.docx", notes_docx_bytes(UPLOAD_NOTES_ROWS[1:]), "application/octet-stream")]
        at = upload(boot(), files, codebook=ADVERSARIAL_CODEBOOK)
        assert_clean(self, at)
        self.assertEqual(widget(at, "radio", "Data Type").value, DATA_TYPE_GROUP)
        specs = chart_specs(at)
        summaries = [h.value for h in at.html if "atlas-chart-summary" in h.value]
        self.assertGreaterEqual(len(summaries), 3)
        to_html = load_app_helpers("chart_summary_html")["chart_summary_html"]
        descriptions = [s.get("description", "") for s in specs]
        for markup in summaries:
            self.assertIn(markup, [to_html(d) for d in descriptions])
            self.assertNotIn("<b>", markup)
            self.assertNotIn("<i>", markup)
        self.assertTrue(any(ADVERSARIAL_DOMAIN in d for d in descriptions))
        self.assertTrue(any(ADVERSARIAL_GROUP_FILE in d for d in descriptions))
        for card in (m.value for m in at.markdown if '<div class="quote-box">' in m.value):
            self.assertNotIn("<b>bold</b>", card)
            self.assertNotIn("<i>", card)
            self.assertIn("&lt;b&gt;bold&lt;/b&gt;", card)


class BadgeContrastTests(unittest.TestCase):
    def test_badge_and_tile_colours_meet_wcag_aa(self):
        h = load_app_helpers("evidence_badge_html")
        pairs = h["EVIDENCE_BADGE_STYLES"]
        for etype, (fg, bg, _label) in pairs.items():
            with self.subTest(evidence_type=etype):
                self.assertGreaterEqual(contrast(fg, bg), 4.5)
        for fill, text in h["GROUP_TILE_COLOURS"].values():
            self.assertGreaterEqual(contrast(text, fill), 4.5, (fill, text))
        badge = h["evidence_badge_html"]("<script>")
        self.assertNotIn("<script>", badge)
        self.assertIn("Transcript / Survey", badge)
        self.assertIn("Verbatim Quote", h["evidence_badge_html"](QUOTE))
        self.assertIn("Paraphrase (Key Point)", h["evidence_badge_html"](KP))
        self.assertIn("Observation", h["evidence_badge_html"](OBS))


if __name__ == "__main__":
    unittest.main()
