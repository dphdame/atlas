"""Integration test for ATLAS execution of config/labor_market_codebook.yaml.

Ported from the open_atlas reference suite and pointed at the public codebook,
which uses the benchmarking schema: four `themes` plus three `frictions`, keyword
roots, no context fences. Verifies codebook compilation (themes and frictions),
facilitator-turn filtering, and export of every deliverable, including
provenance_manifest.json, with the exported values read back from disk.

Every transcript built here is a SOFTWARE_TEST fixture that demonstrates
software mechanics only; none of its content is an empirical finding.

Run: .venv/bin/python -m unittest tests/test_labor_market_pipeline.py -v
"""

import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from atlas_engine import AtlasEngine  # noqa: E402

CODEBOOK = REPO_ROOT / "config" / "labor_market_codebook.yaml"

EXPECTED_RULE_IDS = [
    "causal_identification",
    "empirical_pipelines",
    "market_design_pricing",
    "frontier_ai_governance",
    "credential_fragmentation",
    "data_access_bottlenecks",
    "toolchain_silos",
]

# Each participant turn hits exactly one rule. The moderator's opening question
# names a causal_identification keyword so an unfiltered facilitator turn would
# double that rule's count.
TRANSCRIPT_LINES = [
    "Moderator: Welcome. How does causal inference show up in the postings you review?",
    "Respondent A [10:01]: Our group relies on quasi-experimental designs and difference-in-differences for labor policy work.",
    "Respondent B [10:03]: We maintain an automated pipeline in Python and BigQuery for the team.",
    "Respondent A [10:05]: On the product side we study dynamic pricing and auction rules on two-sided market platforms.",
    "Respondent B [10:07]: We are building AI governance benchmarks that track labor substitution by frontier models.",
    "Respondent A [10:09]: Most postings say PhD required plus five years of experience.",
    "Respondent B [10:11]: Access to proprietary data and GPU access is the real constraint.",
    "Respondent A [10:13]: The hardest step was the SAS migration and the code translation that followed.",
    "Moderator: Thank you, that concludes our discussion today.",
]
EXPECTED_RULE_BY_LINE = dict(zip(EXPECTED_RULE_IDS, TRANSCRIPT_LINES[1:8]))

EXPORTS = [
    "thematic_frequencies.csv",
    "verbatim_quotes_inventory.csv",
    "verbatim_quotes_inventory.parquet",
    "actuarial_parameter_matrix.xlsx",
    "provenance_manifest.json",
]


def line_text(line):
    return line.split(":", 1)[1].strip() if "]:" not in line else line.split("]:", 1)[1].strip()


class TestLaborMarketCodebookCompilation(unittest.TestCase):
    def test_themes_and_frictions_compile_in_order(self):
        engine = AtlasEngine(str(CODEBOOK))
        self.assertEqual([r["id"] for r in engine.compiled_rules], EXPECTED_RULE_IDS)
        for rule in engine.compiled_rules:
            with self.subTest(rule=rule["id"]):
                self.assertIsNotNone(rule["root_regex"], "every theme/friction has keywords")
                self.assertIsNone(rule["fence_regex"], "the public codebook defines no context fences")
                self.assertIsNone(rule["context_window"])

    def test_friction_keywords_are_live(self):
        engine = AtlasEngine(str(CODEBOOK))
        rules = {r["id"]: r for r in engine.compiled_rules}
        self.assertIn("toolchain_silos", rules)
        self.assertTrue(rules["toolchain_silos"]["root_regex"].search("the SAS migration stalled"))
        self.assertTrue(rules["data_access_bottlenecks"]["root_regex"].search("no GPU access this year"))


class TestLaborMarketEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = cls._tmp.name
        cls.transcript = os.path.join(tmp, "software_test_labor_seminar.txt")
        with open(cls.transcript, "w", encoding="utf-8") as fh:
            fh.write("\n".join(TRANSCRIPT_LINES) + "\n")
        with open(cls.transcript, "rb") as fh:
            cls.transcript_sha = hashlib.sha256(fh.read()).hexdigest()

        cls.engine = AtlasEngine(str(CODEBOOK))
        cls.results = cls.engine.process_corpus([cls.transcript], facilitator_names=["Moderator"])
        cls.out_dir = os.path.join(tmp, "export_output")
        cls.engine.export_results(cls.results, cls.out_dir)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_facilitator_turns_are_filtered(self):
        self.assertEqual(self.results["total_turns_parsed"], 9)
        self.assertEqual(self.results["participant_turns_analyzed"], 7)
        self.assertNotIn("Moderator", set(self.results["quotes_df"]["speaker"]))

    def test_each_rule_matches_its_single_participant_turn(self):
        freq = self.results["frequencies_df"].set_index("domain_id")
        self.assertEqual(list(freq.index), EXPECTED_RULE_IDS)
        quotes = self.results["quotes_df"]
        for rule_id in EXPECTED_RULE_IDS:
            with self.subTest(rule=rule_id):
                self.assertEqual(int(freq.loc[rule_id, "matching_turns"]), 1)
                self.assertEqual(int(freq.loc[rule_id, "documents_reporting"]), 1)
                self.assertEqual(int(freq.loc[rule_id, "total_documents"]), 1)
                self.assertAlmostEqual(float(freq.loc[rule_id, "prevalence_pct"]), 100.0)
                texts = list(quotes.loc[quotes["domain_id"] == rule_id, "text"])
                self.assertEqual(texts, [line_text(EXPECTED_RULE_BY_LINE[rule_id])])

    def test_all_deliverables_exported(self):
        for name in EXPORTS:
            with self.subTest(file=name):
                path = os.path.join(self.out_dir, name)
                self.assertTrue(os.path.isfile(path), f"missing export {name}")
                self.assertGreater(os.path.getsize(path), 0)

    def test_frequency_csv_round_trips(self):
        disk = pd.read_csv(os.path.join(self.out_dir, "thematic_frequencies.csv"))
        mem = self.results["frequencies_df"]
        self.assertEqual(list(disk["domain_id"]), list(mem["domain_id"]))
        self.assertEqual(list(disk["matching_turns"]), list(mem["matching_turns"]))
        self.assertEqual(list(disk["prevalence_pct"]), list(mem["prevalence_pct"]))

    def test_quote_inventory_csv_and_parquet_agree_and_carry_provenance(self):
        csv_df = pd.read_csv(os.path.join(self.out_dir, "verbatim_quotes_inventory.csv"))
        pq_df = pd.read_parquet(os.path.join(self.out_dir, "verbatim_quotes_inventory.parquet"))
        self.assertEqual(len(csv_df), 7)
        self.assertEqual(len(pq_df), 7)
        for col in ("source_id", "unit_id", "match_char_start", "match_char_end", "source_sha256"):
            self.assertIn(col, pq_df.columns, f"quote inventory missing {col}")
        self.assertEqual(list(csv_df["text"]), list(pq_df["text"]))
        self.assertEqual(set(pq_df["source_sha256"]), {self.transcript_sha})
        for _, q in pq_df.iterrows():
            span = q["text"][int(q["match_char_start"]):int(q["match_char_end"])]
            self.assertTrue(span, "empty match span")

    def test_provenance_manifest_contents(self):
        manifest_path = os.path.join(self.out_dir, "provenance_manifest.json")
        self.assertTrue(os.path.isfile(manifest_path), "provenance_manifest.json not exported")
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["total_documents"], 1)
        self.assertEqual(manifest["total_turns_parsed"], 9)
        self.assertEqual(manifest["participant_turns_analyzed"], 7)
        self.assertEqual(list(manifest["file_hashes"].values()), [self.transcript_sha])
        self.assertIn("exported_at_utc", manifest)
        self.assertEqual([d["domain_id"] for d in manifest["domains"]], EXPECTED_RULE_IDS)
        for dom in manifest["domains"]:
            with self.subTest(domain=dom["domain_id"]):
                self.assertEqual(dom["matching_turns"], 1)
                self.assertEqual(dom["documents_reporting"], 1)
                self.assertEqual(dom["total_documents"], 1)
                self.assertAlmostEqual(dom["prevalence_pct"], 100.0)
                self.assertRegex(dom["audit_sha256"], r"^[0-9a-f]{64}$")

    def test_workbook_rows_match_frequencies(self):
        wb = openpyxl.load_workbook(os.path.join(self.out_dir, "actuarial_parameter_matrix.xlsx"))
        ws = wb["Empirical Frequencies"]
        ids = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
        self.assertEqual(ids, EXPECTED_RULE_IDS)
        for r in range(2, ws.max_row + 1):
            self.assertEqual(ws.cell(row=r, column=5).value, 100.0)
            self.assertIsNotNone(ws.cell(row=r, column=5).comment)
            self.assertTrue(re.search(r"[0-9a-f]{64}", ws.cell(row=r, column=5).comment.text))


if __name__ == "__main__":
    unittest.main()
