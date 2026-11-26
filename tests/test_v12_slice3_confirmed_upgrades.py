"""v1.2 Slice 3 tests: TF-IDF + NMF discovery default, H3-confirmed exact-word
matching mode, tightened English starter codebook fences, and the GBI Analyst
Quick-Start Guide.

All inputs here are SOFTWARE_TEST fixtures demonstrating software mechanics only.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import atlas_discover  # noqa: E402
from atlas_engine import AtlasEngine  # noqa: E402

APP_PATH = REPO_ROOT / "app.py"
CONFIG_DIR = REPO_ROOT / "config"
DOCS_DIR = REPO_ROOT / "docs"
QUICK_START = DOCS_DIR / "ATLAS_GBI_Analyst_Quick_Start.md"


class DiscoveryMethodTests(unittest.TestCase):
    CORPUS = [
        {"turn_id": 1, "unit_id": "u1", "speaker": "P1", "text": "rent landlord eviction lease notice"},
        {"turn_id": 2, "unit_id": "u2", "speaker": "P2", "text": "rent deposit landlord apartment lease"},
        {"turn_id": 3, "unit_id": "u3", "speaker": "P3", "text": "bus transit fare commute schedule"},
        {"turn_id": 4, "unit_id": "u4", "speaker": "P4", "text": "bus driver commute transfer route"},
    ]

    def test_nmf_is_default_deterministic_and_separates_clusters(self):
        r1 = atlas_discover.discover_topics(self.CORPUS, n_topics=2, random_state=42)
        r2 = atlas_discover.discover_topics(self.CORPUS, n_topics=2, random_state=42, method="nmf")
        self.assertEqual(r1["method"], "nmf")
        self.assertEqual(r1, r2)
        self.assertEqual(len(r1["topics"]), 2)
        self.assertEqual(sum(t["turn_count"] for t in r1["topics"]), 4)
        sets = [set(t["top_terms"]) for t in r1["topics"]]
        self.assertEqual(sets[0] & sets[1], set())

    def test_lda_remains_available_explicitly(self):
        r = atlas_discover.discover_topics(self.CORPUS, n_topics=2, random_state=42, method="lda")
        self.assertEqual(r["method"], "lda")
        self.assertEqual(len(r["topics"]), 2)
        self.assertEqual(sum(t["turn_count"] for t in r["topics"]), 4)

    def test_single_turn_and_tiny_corpora_work_under_nmf(self):
        single = atlas_discover.discover_topics(["rent landlord eviction"], n_topics=3, method="nmf")
        self.assertEqual(single["method"], "nmf")
        self.assertEqual(len(single["topics"]), 1)
        self.assertEqual(single["topics"][0]["medoid_text"], "rent landlord eviction")

    def test_rank_deficient_duplicate_turns_produce_finite_nmf_outputs(self):
        import math
        import warnings
        cases = (
            (["rent landlord", "rent landlord"], 2, 1),
            (["rent", "rent", "rent"], 3, 1),
            (["rent", "Rent.", "RENT!"], 3, 1),
            (["rent", "rent", "bus"], 3, 2),
            (["rent eviction landlord lease", "bus commute transit fare"] * 3, 2, 2),
        )
        for method in ("nmf", "lda"):
            for texts, k, expected_topics in cases:
                with self.subTest(method=method, texts=texts, k=k):
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", RuntimeWarning)
                        res = atlas_discover.discover_topics(texts, n_topics=k, method=method)
                    self.assertEqual(res["n_analyzed"], len(texts))
                    self.assertEqual(len(res["topics"]), expected_topics)
                    self.assertEqual(sum(t["turn_count"] for t in res["topics"]), len(texts))
                    self.assertTrue(all(t["turn_count"] >= 1 for t in res["topics"]))
                    self.assertEqual([t["topic_id"] for t in res["topics"]], list(range(1, expected_topics + 1)))
                    all_terms = [w for t in res["topics"] for w in t["top_terms"]]
                    self.assertTrue(all_terms)
                    self.assertEqual(len(all_terms), len(set(all_terms)), "top terms must stay exclusive across topics")
                    for row in res["doc_topics"]:
                        self.assertEqual(len(row), len(res["topics"]))
                        self.assertTrue(all(math.isfinite(v) for v in row), row)
                    for a in res["assignments"]:
                        self.assertIn(a["topic_id"], range(1, expected_topics + 1))
                        self.assertTrue(math.isfinite(a["topic_weight"]), a)
                    cb = atlas_discover.topics_to_codebook_dict(res)
                    self.assertEqual(len(cb["domains"]), expected_topics)

    def test_unknown_discovery_method_fails_closed(self):
        with self.assertRaises(ValueError):
            atlas_discover.discover_topics(self.CORPUS, n_topics=2, method="bogus")


class ExactMatchModeTests(unittest.TestCase):
    def _run(self, codebook_dict, texts):
        with tempfile.TemporaryDirectory() as tmp:
            cb_path = Path(tmp) / "cb.yaml"
            cb_path.write_text(yaml.safe_dump(codebook_dict, sort_keys=False), encoding="utf-8")
            tx_path = Path(tmp) / "software_test_exact.txt"
            tx_path.write_text("\n".join(f"P{i}: {t}" for i, t in enumerate(texts, 1)) + "\n", encoding="utf-8")
            eng = AtlasEngine(str(cb_path))
            return eng, eng.process_corpus([str(tx_path)], root_dir=tmp)

    def test_codebook_level_exact_mode_blocks_prefix_collisions(self):
        cb = {
            "project": "SOFTWARE_TEST Exact Mode",
            "match_mode": "exact",
            "domains": [
                {"id": "car_dom", "name": "Car", "roots": ["car", "c++"]},
                {"id": "rent_dom", "name": "Rent", "roots_en": ["rent", "late fee"]},
            ],
        }
        texts = [
            "I lost my debit card on my new career path with cargo care.",
            "The dealer repaired my car and I learned c++ last week.",
            "My parent said the current situation feels different.",
            "Our rent increased and they charged a late fee.",
        ]
        _, res = self._run(cb, texts)
        quotes = res["quotes_df"]
        car_texts = set(quotes.loc[quotes["domain_id"] == "car_dom", "text"])
        rent_texts = set(quotes.loc[quotes["domain_id"] == "rent_dom", "text"])
        self.assertEqual(car_texts, {"The dealer repaired my car and I learned c++ last week."})
        self.assertEqual(rent_texts, {"Our rent increased and they charged a late fee."})

    def test_per_domain_match_mode_overrides_default(self):
        cb = {
            "project": "SOFTWARE_TEST Mixed Modes",
            "match_mode": "exact",
            "domains": [
                {"id": "exact_car", "name": "Exact Car", "roots_en": ["car"]},
                {"id": "prefix_evict", "name": "Prefix Evict", "match_mode": "prefix", "roots_en": ["evict"]},
            ],
        }
        texts = [
            "My career is going well.",
            "We received an eviction notice.",
        ]
        _, res = self._run(cb, texts)
        quotes = res["quotes_df"]
        self.assertEqual(set(quotes["domain_id"]), {"prefix_evict"})

    def test_invalid_match_mode_fails_closed(self):
        cb = {
            "project": "SOFTWARE_TEST Bad Mode",
            "match_mode": "fuzzy",
            "domains": [{"id": "x", "name": "X", "roots_en": ["car"]}],
        }
        with self.assertRaises(ValueError):
            self._run(cb, ["My car broke."])


class StarterCodebookFenceTests(unittest.TestCase):
    def _matches(self, codebook_file, text):
        eng = AtlasEngine(str(CONFIG_DIR / codebook_file))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "software_test_fence.txt"
            p.write_text(f"P1: {text}\n", encoding="utf-8")
            res = eng.process_corpus([str(p)], root_dir=tmp)
        return set(res["quotes_df"]["domain_id"])

    def test_sdoh_fences_block_false_prefix_collisions(self):
        self.assertNotIn("housing_insecurity", self._matches("sdoh_basic_needs.yaml", "We picked up a rental car for my parent."))
        self.assertIn("housing_insecurity", self._matches("sdoh_basic_needs.yaml", "We fell behind on rent this month."))
        self.assertNotIn("food_insecurity", self._matches("sdoh_basic_needs.yaml", "Took a quick snapshot of a wicked storm."))
        self.assertIn("food_insecurity", self._matches("sdoh_basic_needs.yaml", "We applied for SNAP and WIC benefits."))
        self.assertNotIn("transportation_barrier", self._matches("sdoh_basic_needs.yaml", "Busy business clinic farewell visit."))
        self.assertIn("transportation_barrier", self._matches("sdoh_basic_needs.yaml", "Missed the clinic visit because the bus never came."))

    def test_workforce_and_intake_fences_block_false_collisions(self):
        self.assertNotIn("wage_progression", self._matches("workforce_and_mobility.yaml", "She packed raisin bread for the fundraiser."))
        self.assertIn("wage_progression", self._matches("workforce_and_mobility.yaml", "I earned a raise after six months."))
        self.assertNotIn("staff_navigation_rapport", self._matches("intake_and_enrollment.yaml", "Other patients waited outside the patient portal."))
        self.assertIn("staff_navigation_rapport", self._matches("intake_and_enrollment.yaml", "The navigator was patient and respectful."))


class DiscoveryUIAndQuickStartTests(unittest.TestCase):
    def test_quick_start_guide_exists_is_clean_and_offered_in_sidebar(self):
        self.assertTrue(QUICK_START.is_file(), f"missing {QUICK_START}")
        text = QUICK_START.read_text(encoding="utf-8")
        for required in ("run.bat", "run.command", "Group", "Quotable Verbatim Only", "TF-IDF + NMF", "actuarial_parameter_matrix.xlsx"):
            self.assertIn(required, text)
        for forbidden in ("2,500", "KII-01", "YET", "file and codebook"):
            self.assertNotIn(forbidden, text)
        self.assertIn("alongside", text.lower())

        at = AppTest.from_file(str(APP_PATH), default_timeout=20)
        at.run()
        self.assertFalse(list(at.exception))
        labels = [d.label for d in at.get("download_button")]
        self.assertTrue(any("GBI Analyst Quick-Start Guide" in lbl for lbl in labels), labels)

    def test_app_discovery_defaults_to_nmf_and_allows_lda_toggle(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=20)
        at.run()
        corpus_box = next(s for s in at.selectbox if s.label == "Corpus Dataset")
        corpus_box.set_value(next(o for o in corpus_box.options if "Focus-Group Notes" in str(o)))
        at.run()
        next(b for b in at.button if b.label == "Run Analysis").click()
        at.run()
        self.assertFalse(list(at.exception))
        radios = [r for r in at.radio if r.label == "Clustering method"]
        self.assertEqual(len(radios), 1, [r.label for r in at.radio])
        self.assertIn("TF-IDF + NMF", str(radios[0].value))
        self.assertTrue(any("Cluster 1:" in m.value for m in at.markdown))

        lda_opt = next(opt for opt in radios[0].options if "LDA" in str(opt))
        radios[0].set_value(lda_opt)
        at.run()
        self.assertFalse(list(at.exception))
        self.assertIn("LDA", str(next(r for r in at.radio if r.label == "Clustering method").value))
        self.assertTrue(any("Cluster 1:" in m.value for m in at.markdown))


if __name__ == "__main__":
    unittest.main()
