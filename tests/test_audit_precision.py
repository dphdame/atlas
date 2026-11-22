"""Audit-precision protocol, exercised through real AtlasEngine runs.

Ported from the open_atlas reference suite. The reference version checked the
context-fence cases with standalone re.search calls; here every excerpt becomes a
participant turn in a transcript file, every root/fence pair becomes a domain in a
YAML codebook, and the match decision comes from AtlasEngine.process_corpus. The
precision arithmetic is then applied to the engine's own classifications.

Every excerpt and codebook built here is a SOFTWARE_TEST fixture that
demonstrates software mechanics only; none of its content is an empirical
finding. Scratch inputs are written under tempfile's directory.

Run: .venv/bin/python -m unittest tests/test_audit_precision.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from atlas_engine import AtlasEngine  # noqa: E402


def calculate_precision(true_positives: int, false_positives: int) -> float:
    """Calculate precision as TP / (TP + FP)."""
    total = true_positives + false_positives
    if total == 0:
        return 0.0
    return true_positives / total


# Roots and fences are engine stems: matched case-insensitively from a word
# boundary, so "delay" also covers "delays".
REPRESENTATIVE_AUDIT_EXCERPTS = [
    {
        "case_id": "REVIEW_INTAKE_POS",
        "format": "Written Online Reviews",
        "text": "The clinic staff were attentive, but the paperwork intake process had excessive delays before seeing the physician.",
        "roots": ["intake", "paperwork", "form"],
        "fences": ["delay", "wait", "slow", "hour"],
        "expected_match": True,
    },
    {
        "case_id": "REVIEW_INTAKE_NOISE",
        "format": "Written Online Reviews",
        "text": "I enjoyed the fresh morning intake of cool ocean air near the facility entrance.",
        "roots": ["intake"],
        "fences": ["paperwork", "form", "delay", "enrollment"],
        "expected_match": False,
    },
    {
        "case_id": "SOCIAL_TRANSIT_POS",
        "format": "Social Media Posts",
        "text": "Public transit delay again on route 22, going to miss my scheduled health appointment.",
        "roots": ["transit", "bus", "train"],
        "fences": ["delay", "late", "missed", "appointment"],
        "expected_match": True,
    },
    {
        "case_id": "SOCIAL_TRANSIT_NOISE",
        "format": "Social Media Posts",
        "text": "Caught the early bus today without issue, but my video stream had a slight delay.",
        "roots": ["transit", "bus"],
        "fences": ["route", "schedule", "late", "missed"],
        "expected_match": False,
    },
    {
        "case_id": "SURVEY_CLIFF_POS",
        "format": "Open-Ended Survey Responses",
        "text": "We lost our Medi-Cal coverage after a modest pay increase, causing an abrupt benefit cliff.",
        "roots": ["medi-cal", "coverage", "benefit"],
        "fences": ["lost", "cliff", "raise", "wage", "cutoff"],
        "expected_match": True,
    },
    {
        "case_id": "INTERVIEW_BILLING_POS",
        "format": "Semi-Structured Interview Transcripts",
        "text": "We cannot absorb clearinghouse technical transaction rejections for 837 claims without an administrative billing hub.",
        "roots": ["clearinghouse", "837", "edi"],
        "fences": ["rejection", "claim", "hub", "billing", "friction"],
        "expected_match": True,
    },
]

# Root "intake" at token 1 and fence "delays" at token 18: 17 tokens apart.
WINDOWED_EXCERPT = (
    "The intake desk was friendly and bright, and much later in the afternoon "
    "the parking lot had long delays."
)


def write_codebook(path, domains):
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"project": "SOFTWARE_TEST Audit Precision", "domains": domains}, fh, sort_keys=False)


def write_transcript(path, texts):
    with open(path, "w", encoding="utf-8") as fh:
        for idx, text in enumerate(texts, 1):
            fh.write(f"Respondent {idx}: {text}\n")


def run_engine(tmp, domain, texts):
    cb_path = os.path.join(tmp, f"{domain['id']}_codebook.yaml")
    tx_path = os.path.join(tmp, f"{domain['id']}_transcript.txt")
    write_codebook(cb_path, [domain])
    write_transcript(tx_path, texts)
    engine = AtlasEngine(cb_path)
    return engine.process_corpus([tx_path])


def excerpt_domain(case):
    return {
        "id": case["case_id"],
        "name": case["format"],
        "roots_en": case["roots"],
        "context_fences": case["fences"],
    }


class TestAuditPrecisionProtocol(unittest.TestCase):
    def test_precision_formula_properties(self):
        """Verify standard precision formula arithmetic and boundary conditions."""
        self.assertEqual(calculate_precision(0, 0), 0.0)
        self.assertEqual(calculate_precision(50, 0), 1.0)
        self.assertEqual(calculate_precision(0, 50), 0.0)
        self.assertAlmostEqual(calculate_precision(46, 4), 0.92, places=6)
        self.assertAlmostEqual(calculate_precision(56, 4), 56 / 60, places=6)
        self.assertAlmostEqual(calculate_precision(67, 3), 67 / 70, places=6)

    def test_macro_and_micro_precision_aggregation(self):
        """Verify unweighted (macro) and pooled (micro) aggregation arithmetic."""
        audit_samples = [
            {"tp": 46, "fp": 4},
            {"tp": 56, "fp": 4},
            {"tp": 67, "fp": 3},
            {"tp": 67, "fp": 3},
        ]
        rates = [calculate_precision(s["tp"], s["fp"]) for s in audit_samples]
        macro_precision = sum(rates) / len(rates)
        total_tp = sum(s["tp"] for s in audit_samples)
        total_fp = sum(s["fp"] for s in audit_samples)
        micro_precision = calculate_precision(total_tp, total_fp)

        self.assertEqual(round(macro_precision * 100, 1), 94.2)
        self.assertEqual(round(micro_precision * 100, 1), 94.4)


class TestContextFencingThroughEngine(unittest.TestCase):
    def test_engine_classifies_positive_and_noise_excerpts(self):
        """Each excerpt is scored by AtlasEngine; decisions must equal expected_match."""
        with tempfile.TemporaryDirectory() as tmp:
            for case in REPRESENTATIVE_AUDIT_EXCERPTS:
                with self.subTest(case=case["case_id"]):
                    results = run_engine(tmp, excerpt_domain(case), [case["text"]])
                    freq = results["frequencies_df"].set_index("domain_id")
                    matched = int(freq.loc[case["case_id"], "matching_turns"]) == 1
                    self.assertEqual(
                        matched, case["expected_match"],
                        f"[{case['format']}] {case['text']!r}: expected match={case['expected_match']}",
                    )
                    self.assertEqual(results["participant_turns_analyzed"], 1)

    def test_engine_precision_on_audit_excerpts(self):
        """Precision computed from the engine's own decisions on the labelled excerpts."""
        tp = fp = fn = 0
        with tempfile.TemporaryDirectory() as tmp:
            for case in REPRESENTATIVE_AUDIT_EXCERPTS:
                results = run_engine(tmp, excerpt_domain(case), [case["text"]])
                predicted = int(results["frequencies_df"].iloc[0]["matching_turns"]) == 1
                if predicted and case["expected_match"]:
                    tp += 1
                elif predicted and not case["expected_match"]:
                    fp += 1
                elif case["expected_match"]:
                    fn += 1
        self.assertEqual((tp, fp, fn), (4, 0, 0))
        self.assertEqual(calculate_precision(tp, fp), 1.0)

    def test_positive_matches_report_verbatim_root_span(self):
        """Every positive quote carries match_char_start/end slicing a root out of the turn text."""
        with tempfile.TemporaryDirectory() as tmp:
            for case in [c for c in REPRESENTATIVE_AUDIT_EXCERPTS if c["expected_match"]]:
                with self.subTest(case=case["case_id"]):
                    results = run_engine(tmp, excerpt_domain(case), [case["text"]])
                    quotes = results["quotes_df"]
                    self.assertEqual(len(quotes), 1)
                    q = quotes.iloc[0]
                    self.assertEqual(q["text"], case["text"])
                    self.assertIn("match_char_start", quotes.columns)
                    self.assertIn("match_char_end", quotes.columns)
                    start, end = int(q["match_char_start"]), int(q["match_char_end"])
                    self.assertTrue(0 <= start < end <= len(case["text"]))
                    span = case["text"][start:end]
                    self.assertIn(span.lower(), [r.lower() for r in case["roots"]],
                                  f"span {span!r} is not one of the domain roots")

    def test_context_window_rejects_distant_fence(self):
        """A 3-token window rejects a fence 17 tokens away; turn-level co-occurrence accepts it."""
        base = {"id": "WINDOW_CASE", "name": "Windowed intake delay", "roots_en": ["intake"], "context_fences": ["delay"]}
        with tempfile.TemporaryDirectory() as tmp:
            windowed = run_engine(tmp, dict(base, context_window=3), [WINDOWED_EXCERPT])
            self.assertEqual(int(windowed["frequencies_df"].iloc[0]["matching_turns"]), 0)
            turn_level = run_engine(tmp, base, [WINDOWED_EXCERPT])
            self.assertEqual(int(turn_level["frequencies_df"].iloc[0]["matching_turns"]), 1)


if __name__ == "__main__":
    unittest.main()
