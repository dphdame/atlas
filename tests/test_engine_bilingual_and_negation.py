"""Slice 2a RED: hardened AtlasEngine behaviour (anchor element A3).

Contract under test (.codex/contracts/slice_2b_green.md, item 1):
  * prevalence denominators count distinct analytical unit_ids, and file_hashes
    never collide on duplicate basenames;
  * combining-mark-insensitive matching (NFC and NFD input, accented or
    unaccented codebook roots) reporting match_char_start / match_char_end as
    0-based indices into the unmodified turn text;
  * exclude_fences (aliases negative_fences, exclude_terms) with exclude_window;
  * consistency-bound .xlsx audit comments, provenance_manifest.json,
    AtlasEngine.verify_workbook_integrity, and semantic reproducibility.

Every transcript, CSV and codebook built here is a SOFTWARE_TEST fixture that
demonstrates software mechanics only; none of its content is an empirical
finding. Scratch inputs are written under tempfile's directory.

Run: .venv/bin/python -m unittest tests/test_engine_bilingual_and_negation.py -v
"""

import csv
import hashlib
import inspect
import json
import os
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

import openpyxl
import pandas as pd
import yaml
from openpyxl.comments import Comment

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from atlas_engine import AtlasEngine  # noqa: E402
from universal_transcript_parser import UniversalTranscriptParser  # noqa: E402

PFL_CODEBOOK = REPO_ROOT / "config" / "pfl_case_study_codebook.yaml"


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_codebook(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)


def freq_row(results, domain_id):
    freq = results["frequencies_df"].set_index("domain_id")
    return freq.loc[domain_id]


class ScratchMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)


# ---------------------------------------------------------------------------
# Source identity versus analytical unit identity
# ---------------------------------------------------------------------------
CHILDCARE_CODEBOOK = {
    "project": "SOFTWARE_TEST Unit Denominators",
    "domains": [{"id": "CHILDCARE", "name": "Childcare access", "roots_en": ["childcare"]}],
}

CSV_ROWS = [
    ("R01", "We could not find childcare and the childcare waitlist is long."),
    ("R02", "The bus was late."),
    ("R03", "Childcare costs more than rent."),
    ("R04", "   "),
    ("R05", "Our clinic hours changed."),
    ("R06", "The pharmacy closed early."),
    ("R07", "Nothing else to add."),
]
TABULAR_OPTIONS = {"text_col": "response", "id_col": "respondent_id"}


class TestSourceAndUnitDenominators(ScratchMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.codebook = self.path("childcare.yaml")
        write_codebook(self.codebook, CHILDCARE_CODEBOOK)
        self.file_a = self.path("dir_a", "interview.txt")
        self.file_b = self.path("dir_b", "interview.txt")
        write_text(self.file_a, "Respondent A: We could not find childcare near the clinic.\n")
        write_text(self.file_b, "Respondent B: The bus was late again this week.\n")
        self.sha_a = sha256_file(self.file_a)
        self.sha_b = sha256_file(self.file_b)
        self.assertNotEqual(self.sha_a, self.sha_b)

        self.csv_path = self.path("software_test_survey.csv")
        with open(self.csv_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["respondent_id", "response"])
            writer.writerows(CSV_ROWS)

    def assert_process_corpus_accepts(self, *names):
        params = inspect.signature(AtlasEngine.process_corpus).parameters
        for name in names:
            self.assertIn(name, params, f"process_corpus has no {name!r} parameter")

    def test_same_basename_files_are_two_documents_with_both_hashes(self):
        results = AtlasEngine(self.codebook).process_corpus([self.file_a, self.file_b])
        self.assertEqual(results["total_documents"], 2)
        self.assertEqual(len(results["file_hashes"]), 2, "dir_b/interview.txt overwrote dir_a/interview.txt")
        self.assertEqual(set(results["file_hashes"].values()), {self.sha_a, self.sha_b})

        row = freq_row(results, "CHILDCARE")
        self.assertEqual(int(row["documents_reporting"]), 1)
        self.assertEqual(int(row["total_documents"]), 2)
        self.assertAlmostEqual(float(row["prevalence_pct"]), 50.0)

        quotes = results["quotes_df"]
        self.assertEqual(len(quotes), 1)
        q = quotes.iloc[0]
        self.assertEqual(q["source_sha256"], self.sha_a, "quote is stamped with the other file's hash")
        self.assertTrue(q["source_id"].endswith("dir_a/interview.txt"))
        self.assertTrue(q["unit_id"].endswith("dir_a/interview.txt"))

    def test_root_dir_keys_hashes_by_relative_source_id(self):
        self.assert_process_corpus_accepts("root_dir")
        results = AtlasEngine(self.codebook).process_corpus([self.file_a, self.file_b], root_dir=self.tmp)
        self.assertEqual(
            results["file_hashes"],
            {"dir_a/interview.txt": self.sha_a, "dir_b/interview.txt": self.sha_b},
        )
        self.assertEqual(results["quotes_df"].iloc[0]["source_id"], "dir_a/interview.txt")

    def test_csv_respondent_rows_are_the_denominator(self):
        self.assert_process_corpus_accepts("tabular_options")
        results = AtlasEngine(self.codebook).process_corpus([self.csv_path], tabular_options=TABULAR_OPTIONS)

        self.assertEqual(results["total_documents"], 6, "six non-empty respondent rows, not one CSV file")
        self.assertEqual(results["participant_turns_analyzed"], 6)
        self.assertEqual(list(results["file_hashes"].values()), [sha256_file(self.csv_path)])

        row = freq_row(results, "CHILDCARE")
        self.assertEqual(int(row["documents_reporting"]), 2)
        self.assertEqual(int(row["matching_turns"]), 2)
        self.assertEqual(int(row["total_documents"]), 6)
        self.assertAlmostEqual(float(row["prevalence_pct"]), round(2 / 6 * 100, 1))

        parsed = UniversalTranscriptParser().parse_tabular(self.csv_path, **TABULAR_OPTIONS)
        source_id = parsed[0]["source_id"]
        self.assertEqual(set(results["quotes_df"]["unit_id"]), {f"{source_id}::R01", f"{source_id}::R03"})

    def test_mixed_transcript_and_csv_denominator(self):
        self.assert_process_corpus_accepts("tabular_options")
        results = AtlasEngine(self.codebook).process_corpus(
            [self.file_a, self.csv_path], tabular_options=TABULAR_OPTIONS
        )
        self.assertEqual(results["total_documents"], 7)
        row = freq_row(results, "CHILDCARE")
        self.assertEqual(int(row["documents_reporting"]), 3)
        self.assertAlmostEqual(float(row["prevalence_pct"]), round(3 / 7 * 100, 1))

    def test_process_turns_matches_process_corpus(self):
        self.assertTrue(callable(getattr(AtlasEngine, "process_turns", None)), "AtlasEngine.process_turns missing")
        self.assert_process_corpus_accepts("tabular_options")
        engine = AtlasEngine(self.codebook)
        via_corpus = engine.process_corpus([self.csv_path], tabular_options=TABULAR_OPTIONS)
        turns = UniversalTranscriptParser().parse_tabular(self.csv_path, **TABULAR_OPTIONS)
        via_turns = engine.process_turns(turns, dict(via_corpus["file_hashes"]))
        self.assertEqual(via_turns["total_documents"], 6)
        pd.testing.assert_frame_equal(via_turns["frequencies_df"], via_corpus["frequencies_df"])

    def test_process_transcripts_alias_is_kept(self):
        self.assertTrue(hasattr(AtlasEngine, "process_transcripts"), "process_transcripts alias missing")
        self.assertIs(AtlasEngine.process_transcripts, AtlasEngine.process_corpus)


# ---------------------------------------------------------------------------
# Combining-mark-insensitive matching with exact verbatim spans
# ---------------------------------------------------------------------------
NFC = lambda s: unicodedata.normalize("NFC", s)  # noqa: E731

# (speaker, turn text, exact verbatim PFL_GAP span inside the turn text)
UNICODE_TURNS = [
    ("Trabajadora A", NFC("Perdí la protección laboral cuando pedí permiso en el trabajo."), NFC("protección laboral")),
    ("Trabajadora B", "Perdí la protección laboral durante el permiso.", "protección laboral"),
    ("Trabajadora C", NFC("The ﬁnancial leave ended; luego se agotó el beneficio at my job."), NFC("se agotó el beneficio")),
    ("Trabajadora D", NFC("Die Straße war lang; perdí la protección laboral en el trabajo."), NFC("protección laboral")),
    ("Trabajadora E", "ﬁn de la Straße: se agotó el beneficio y perdí el trabajo.", "se agotó el beneficio"),
    ("Trabajadora F", NFC("PERDÍ LA PROTECCIÓN LABORAL EN EL TRABAJO."), NFC("PROTECCIÓN LABORAL")),
]


class TestCombiningMarkInsensitiveSpans(ScratchMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.transcript = self.path("software_test_bilingual.txt")
        write_text(self.transcript, "".join(f"{spk}: {text}\n" for spk, text, _ in UNICODE_TURNS))
        parsed = UniversalTranscriptParser().parse_file(self.transcript)
        self.original_texts = [t["text"] for t in parsed]

    def test_fixture_is_lossless_through_parser(self):
        self.assertEqual(self.original_texts, [text for _, text, _ in UNICODE_TURNS])
        self.assertIn("́", self.original_texts[1])
        self.assertIn("ﬁ", self.original_texts[2])
        self.assertIn("ß", self.original_texts[3])

    def test_unaccented_codebook_roots_match_accented_text_with_exact_spans(self):
        results = AtlasEngine(str(PFL_CODEBOOK)).process_corpus([self.transcript])
        quotes = results["quotes_df"]
        self.assertIn("match_char_start", quotes.columns)
        self.assertIn("match_char_end", quotes.columns)
        gap = quotes[quotes["domain_id"] == "PFL_GAP"].reset_index(drop=True)
        self.assertEqual(len(gap), len(UNICODE_TURNS), "every accented/decomposed variant must match PFL_GAP")
        self.assertEqual(int(freq_row(results, "PFL_GAP")["matching_turns"]), len(UNICODE_TURNS))

        by_text = {row["text"]: row for _, row in gap.iterrows()}
        for speaker, text, verbatim in UNICODE_TURNS:
            with self.subTest(speaker=speaker):
                self.assertIn(text, by_text, "quote text must be the unmodified turn text")
                q = by_text[text]
                start, end = int(q["match_char_start"]), int(q["match_char_end"])
                self.assertEqual(start, text.index(verbatim))
                self.assertEqual(end, text.index(verbatim) + len(verbatim))
                self.assertEqual(text[start:end], verbatim)
                self.assertEqual(q["speaker"], speaker)

    def test_quote_text_keeps_original_diacritics_and_forms(self):
        quotes = AtlasEngine(str(PFL_CODEBOOK)).process_corpus([self.transcript])["quotes_df"]
        self.assertFalse(quotes.empty, "no quotes matched the accented/decomposed fixture")
        texts = set(quotes.loc[quotes["domain_id"] == "PFL_GAP", "text"])
        self.assertEqual(texts, set(self.original_texts))
        self.assertTrue(any("protección" in t for t in texts), "NFD form was rewritten")
        self.assertTrue(any("ﬁnancial" in t for t in texts), "ligature was expanded")
        self.assertTrue(any("Straße" in t for t in texts), "sharp s was case-folded")

    def test_accented_codebook_roots_match_unaccented_and_decomposed_text(self):
        codebook = self.path("accented_roots.yaml")
        write_codebook(codebook, {
            "project": "SOFTWARE_TEST Accented Roots",
            "domains": [{
                "id": "PROTECCION",
                "name": "Protección laboral",
                "roots_es": [NFC("protección laboral")],
                "context_fences": ["trabajo"],
            }],
        })
        lines = [
            ("Respondent A", "perdi la proteccion laboral en el trabajo", "proteccion laboral"),
            ("Respondent B", "perdi la protección laboral en el trabajo", "protección laboral"),
        ]
        transcript = self.path("software_test_unaccented.txt")
        write_text(transcript, "".join(f"{spk}: {text}\n" for spk, text, _ in lines))
        quotes = AtlasEngine(codebook).process_corpus([transcript])["quotes_df"]
        self.assertEqual(len(quotes), 2)
        for (_, text, verbatim), (_, q) in zip(lines, quotes.iterrows()):
            self.assertEqual(q["text"], text)
            self.assertEqual(q["text"][int(q["match_char_start"]):int(q["match_char_end"])], verbatim)


# ---------------------------------------------------------------------------
# Negative fences
# ---------------------------------------------------------------------------
EXCLUDE_TERMS = ["model inference", "latency", "not", "without"]
TURN_DESIGN = "We need a quasi-experimental causal inference design for the rollout."
TURN_WITHOUT = "They ran causal inference without identification of any kind."
TURN_LATENCY = "The model inference latency was the bottleneck."
# "without" sits 12 tokens after "inference".
TURN_FAR_WITHOUT = "Causal inference is the goal, and the team works hard every single day without pause."
# The first "inference" is fenced off; the second sits 14 tokens after "latency".
TURN_SECOND_ROOT = (
    "Model inference latency aside, over many later months of fieldwork our team "
    "kept refining a causal inference design."
)
FENCE_TURNS = [TURN_DESIGN, TURN_WITHOUT, TURN_LATENCY, TURN_FAR_WITHOUT, TURN_SECOND_ROOT]


def domains_codebook(window, key="exclude_fences"):
    rule = {"id": "CAUSAL_ID", "name": "Causal identification", "roots_en": ["inference"], key: EXCLUDE_TERMS}
    if window is not None:
        rule["exclude_window"] = window
    return {"project": "SOFTWARE_TEST Negative Fences", "domains": [rule]}


class TestExcludeFences(ScratchMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.transcript = self.path("software_test_methods.txt")
        write_text(self.transcript, "".join(f"Respondent {i}: {t}\n" for i, t in enumerate(FENCE_TURNS, 1)))

    def matched_texts(self, payload):
        cb = self.path("fence_codebook.yaml")
        write_codebook(cb, payload)
        results = AtlasEngine(cb).process_corpus([self.transcript])
        quotes = results["quotes_df"]
        if quotes.empty:
            return results, quotes, set()
        return results, quotes, set(quotes.loc[quotes["domain_id"] == "CAUSAL_ID", "text"])

    def test_windowed_exclusion_suppresses_nearby_terms_only(self):
        results, _, texts = self.matched_texts(domains_codebook(5))
        self.assertEqual(texts, {TURN_DESIGN, TURN_FAR_WITHOUT, TURN_SECOND_ROOT})
        self.assertEqual(int(freq_row(results, "CAUSAL_ID")["matching_turns"]), 3)

    def test_whole_turn_exclusion_when_window_is_none(self):
        _, _, texts = self.matched_texts(domains_codebook(None))
        self.assertEqual(texts, {TURN_DESIGN})

    def test_reported_span_is_the_unexcluded_root_occurrence(self):
        _, quotes, _ = self.matched_texts(domains_codebook(5))
        self.assertIn("match_char_start", quotes.columns)
        self.assertIn(TURN_SECOND_ROOT, set(quotes["text"]))
        q = quotes[quotes["text"] == TURN_SECOND_ROOT].iloc[0]
        expected_start = TURN_SECOND_ROOT.index("causal inference") + len("causal ")
        self.assertEqual(int(q["match_char_start"]), expected_start)
        self.assertEqual(int(q["match_char_end"]), expected_start + len("inference"))

    def test_exclusion_aliases_across_schemas(self):
        rule_body = {"name": "Causal identification", "keywords": ["inference"], "exclude_window": 5}
        payloads = {
            "domains+negative_fences": domains_codebook(5, key="negative_fences"),
            "topics+exclude_terms": {
                "project": "SOFTWARE_TEST Negative Fences",
                "topics": {"CAUSAL_ID": dict(rule_body, label="Causal identification", exclude_terms=EXCLUDE_TERMS)},
            },
            "themes+exclude_fences": {
                "project": "SOFTWARE_TEST Negative Fences",
                "themes": [dict(rule_body, id="CAUSAL_ID", exclude_fences=EXCLUDE_TERMS)],
            },
        }
        for label, payload in payloads.items():
            with self.subTest(schema=label):
                _, _, texts = self.matched_texts(payload)
                self.assertEqual(texts, {TURN_DESIGN, TURN_FAR_WITHOUT, TURN_SECOND_ROOT})


# ---------------------------------------------------------------------------
# Consistency-bound workbook, manifest, tamper detection, reproducibility
# ---------------------------------------------------------------------------
def expected_audit_digest(dom, file_hashes):
    shas = "+".join(sorted(file_hashes.values()))
    payload = (
        f"{dom['domain_id']}|{dom['documents_reporting']}|{dom['total_documents']}|"
        f"{dom['matching_turns']}|{float(dom['prevalence_pct']):.1f}|{shas}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TestWorkbookAuditAndReproducibility(ScratchMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.inputs = [
            self.path("corpus", "software_test_bilingual.txt"),
            self.path("corpus", "dir_a", "interview.txt"),
            self.path("corpus", "dir_b", "interview.txt"),
        ]
        write_text(self.inputs[0], "".join(f"{spk}: {text}\n" for spk, text, _ in UNICODE_TURNS))
        write_text(self.inputs[1], "Respondent A: The wage replacement at 70 percent does not cover rent.\n")
        write_text(self.inputs[2], "Respondent B: Our small business had to pay overtime cost to cover shifts for the staff.\n")
        self.shas = {sha256_file(p) for p in self.inputs}

    def export(self, name):
        engine = AtlasEngine(str(PFL_CODEBOOK))
        results = engine.process_corpus(self.inputs)
        out = self.path(name)
        engine.export_results(results, out)
        return results, out

    def load_manifest(self, out):
        manifest_path = os.path.join(out, "provenance_manifest.json")
        self.assertTrue(os.path.isfile(manifest_path), "provenance_manifest.json not exported")
        with open(manifest_path, encoding="utf-8") as fh:
            return json.load(fh)

    def assert_verifier_present(self):
        self.assertTrue(
            callable(getattr(AtlasEngine, "verify_workbook_integrity", None)),
            "AtlasEngine.verify_workbook_integrity missing",
        )

    def test_manifest_binds_hashes_and_denominators(self):
        results, out = self.export("run")
        manifest = self.load_manifest(out)
        self.assertEqual(set(manifest["file_hashes"].values()), self.shas)
        self.assertEqual(len(manifest["file_hashes"]), 3)
        self.assertEqual(manifest["total_documents"], 3)
        self.assertIn("exported_at_utc", manifest)
        freq = results["frequencies_df"].set_index("domain_id")
        self.assertEqual([d["domain_id"] for d in manifest["domains"]], list(freq.index))
        gap = next(d for d in manifest["domains"] if d["domain_id"] == "PFL_GAP")
        self.assertEqual((gap["documents_reporting"], gap["total_documents"]), (1, 3))
        self.assertEqual(gap["matching_turns"], len(UNICODE_TURNS))
        for dom in manifest["domains"]:
            with self.subTest(domain=dom["domain_id"]):
                self.assertEqual(dom["audit_sha256"], expected_audit_digest(dom, manifest["file_hashes"]))

    def test_prevalence_cells_carry_consistency_bound_comments(self):
        _, out = self.export("run")
        manifest = self.load_manifest(out)
        ws = openpyxl.load_workbook(os.path.join(out, "actuarial_parameter_matrix.xlsx"))["Empirical Frequencies"]
        self.assertEqual(ws.max_row - 1, len(manifest["domains"]))
        for row_idx, dom in enumerate(manifest["domains"], 2):
            with self.subTest(domain=dom["domain_id"]):
                self.assertEqual(ws.cell(row=row_idx, column=1).value, dom["domain_id"])
                self.assertEqual(ws.cell(row=row_idx, column=3).value, dom["documents_reporting"])
                self.assertEqual(ws.cell(row=row_idx, column=4).value, dom["total_documents"])
                self.assertEqual(ws.cell(row=row_idx, column=6).value, dom["matching_turns"])
                cell = ws.cell(row=row_idx, column=5)
                self.assertAlmostEqual(float(cell.value), float(dom["prevalence_pct"]))
                self.assertIsNotNone(cell.comment, "prevalence cell has no audit comment")
                self.assertIn("SHA-256", cell.comment.text)
                self.assertIn(expected_audit_digest(dom, manifest["file_hashes"]), cell.comment.text)

    def test_verify_workbook_integrity_passes_untouched_export(self):
        self.assert_verifier_present()
        _, out = self.export("run")
        ok, reasons = AtlasEngine.verify_workbook_integrity(
            os.path.join(out, "actuarial_parameter_matrix.xlsx"), os.path.join(out, "provenance_manifest.json")
        )
        self.assertEqual((ok, reasons), (True, []))

    def test_verify_workbook_integrity_detects_prevalence_tamper(self):
        self.assert_verifier_present()
        _, out = self.export("run")
        xlsx = os.path.join(out, "actuarial_parameter_matrix.xlsx")
        tampered = self.path("tampered_value.xlsx")
        wb = openpyxl.load_workbook(xlsx)
        cell = wb["Empirical Frequencies"].cell(row=2, column=5)
        cell.value = float(cell.value) + 5.0
        wb.save(tampered)
        ok, reasons = AtlasEngine.verify_workbook_integrity(tampered, os.path.join(out, "provenance_manifest.json"))
        self.assertFalse(ok)
        self.assertIsInstance(reasons, list)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertTrue(all(isinstance(r, str) and r for r in reasons))

    def test_verify_workbook_integrity_detects_comment_tamper(self):
        self.assert_verifier_present()
        _, out = self.export("run")
        manifest = self.load_manifest(out)
        xlsx = os.path.join(out, "actuarial_parameter_matrix.xlsx")
        tampered = self.path("tampered_comment.xlsx")
        wb = openpyxl.load_workbook(xlsx)
        cell = wb["Empirical Frequencies"].cell(row=2, column=5)
        digest = manifest["domains"][0]["audit_sha256"]
        self.assertIn(digest, cell.comment.text)
        cell.comment = Comment(cell.comment.text.replace(digest, "0" * 64), "SOFTWARE_TEST tamper")
        wb.save(tampered)
        ok, reasons = AtlasEngine.verify_workbook_integrity(tampered, os.path.join(out, "provenance_manifest.json"))
        self.assertFalse(ok)
        self.assertGreaterEqual(len(reasons), 1)

    def test_two_runs_are_semantically_identical(self):
        res1, out1 = self.export("run_1")
        res2, out2 = self.export("run_2")
        pd.testing.assert_frame_equal(res1["frequencies_df"], res2["frequencies_df"])
        pd.testing.assert_frame_equal(res1["quotes_df"], res2["quotes_df"])
        for name in ("thematic_frequencies.csv", "verbatim_quotes_inventory.csv"):
            with open(os.path.join(out1, name), "rb") as f1, open(os.path.join(out2, name), "rb") as f2:
                self.assertEqual(f1.read(), f2.read(), f"{name} differs between runs")
        m1, m2 = self.load_manifest(out1), self.load_manifest(out2)
        self.assertIn("exported_at_utc", m1)
        self.assertIn("exported_at_utc", m2)
        m1.pop("exported_at_utc")
        m2.pop("exported_at_utc")
        self.assertEqual(m1, m2)


if __name__ == "__main__":
    unittest.main()
