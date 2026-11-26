"""v1.2 Slice 4 tests: Analyst Workflow Add-Ons A, B, and C.

- Add-on A: Stack 2+ codebooks (`merge_codebook_dicts` + sidebar multiselect).
- Add-on B: One-click add discovered theme to active codebook (`append_topic_to_codebook` + Discovery UI).
- Add-on C: False-alarm spot-check audit (`audit_false_alarm_risks`, `summarize_false_alarm_risks`,
  `tighten_codebook_domain` + Spot-Check UI).

All inputs here are SOFTWARE_TEST fixtures demonstrating software mechanics only.
"""

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
import atlas_engine  # noqa: E402
from atlas_engine import AtlasEngine  # noqa: E402

APP_PATH = REPO_ROOT / "app.py"
CONFIG_DIR = REPO_ROOT / "config"
QUICK_START = REPO_ROOT / "docs" / "ATLAS_GBI_Analyst_Quick_Start.md"


def _run_codebook_dict(cb_dict, texts):
    with tempfile.TemporaryDirectory() as tmp:
        cb_path = Path(tmp) / "software_test_cb.yaml"
        cb_path.write_text(yaml.safe_dump(cb_dict, allow_unicode=True, sort_keys=False), encoding="utf-8")
        tx_path = Path(tmp) / "software_test_corpus.txt"
        tx_path.write_text("\n".join(f"P{i}: {t}" for i, t in enumerate(texts, 1)) + "\n", encoding="utf-8")
        engine = AtlasEngine(str(cb_path))
        results = engine.process_corpus([str(tx_path)], root_dir=tmp)
        return engine, results


class AddonACodebookStackingTests(unittest.TestCase):
    def test_merge_two_starter_codebooks_combines_all_domains_and_compiles(self):
        cb_gbi = yaml.safe_load((CONFIG_DIR / "gbi_focus_group_starter.yaml").read_text(encoding="utf-8"))
        cb_sdoh = yaml.safe_load((CONFIG_DIR / "sdoh_basic_needs.yaml").read_text(encoding="utf-8"))

        merged = atlas_engine.merge_codebook_dicts([
            ("gbi_focus_group_starter.yaml", cb_gbi),
            ("sdoh_basic_needs.yaml", cb_sdoh),
        ])
        self.assertEqual(len(merged["domains"]), 14)
        ids = [d["id"] for d in merged["domains"]]
        names = [d["name"] for d in merged["domains"]]
        self.assertEqual(len(ids), len(set(ids)), "merged domain IDs must be unique")
        self.assertEqual(len(names), len(set(names)), "merged domain names must be unique")

        engine, results = _run_codebook_dict(
            merged,
            ["We fell behind on rent and needed WIC groceries."],
        )
        self.assertEqual(len(engine.compiled_rules), 14)
        matched_ids = set(results["quotes_df"]["domain_id"])
        self.assertIn("housing_rent_stability", matched_ids)
        self.assertIn("food_insecurity", matched_ids)

    def test_merge_disambiguates_colliding_ids_names_and_preserves_mixed_match_modes(self):
        cb_exact = {
            "project": "SOFTWARE_TEST Exact",
            "match_mode": "exact",
            "domains": [
                {"id": "shared_id", "name": "Transit", "roots_en": ["car"]},
            ],
        }
        cb_prefix = {
            "project": "SOFTWARE_TEST Prefix",
            "topics": {
                "shared_id": {
                    "name": "Transit",
                    "roots_en": ["evict"],
                    "exclude_fences": ["eviction moratorium"],
                    "exclude_window": 2,
                },
            },
        }
        merged = atlas_engine.merge_codebook_dicts([("exact.yaml", cb_exact), ("prefix.yaml", cb_prefix)])
        self.assertEqual(len(merged["domains"]), 2)
        d0, d1 = merged["domains"]
        self.assertEqual(d0["id"], "shared_id")
        self.assertNotEqual(d1["id"], "shared_id")
        self.assertNotEqual(d0["name"], d1["name"])
        self.assertEqual(d0["match_mode"], "exact")
        self.assertEqual(d1["match_mode"], "prefix")
        self.assertEqual(d1["exclude_window"], 2)

        _, res = _run_codebook_dict(
            merged,
            [
                "My career card cares little about cargo.",
                "Our car broke down.",
                "The landlord filed an eviction notice.",
            ],
        )
        quotes = res["quotes_df"]
        d0_texts = set(quotes.loc[quotes["domain_id"] == d0["id"], "text"])
        d1_texts = set(quotes.loc[quotes["domain_id"] == d1["id"], "text"])
        self.assertEqual(d0_texts, {"Our car broke down."})
        self.assertEqual(d1_texts, {"The landlord filed an eviction notice."})

    def test_merge_fails_closed_on_empty_or_invalid_inputs(self):
        with self.assertRaises(ValueError):
            atlas_engine.merge_codebook_dicts([])
        with self.assertRaises(ValueError):
            atlas_engine.merge_codebook_dicts([("bad.yaml", ["not", "a", "dict"])])


class AddonBAppendDiscoveredTopicTests(unittest.TestCase):
    def test_append_topic_adds_exact_domain_cumulatively_without_mutating_existing(self):
        base_cb = yaml.safe_load((CONFIG_DIR / "gbi_focus_group_starter.yaml").read_text(encoding="utf-8"))
        topic1 = {"topic_id": 1, "label": "prepaid / card / fee", "top_terms": ["prepaid", "card", "fee", "Card"], "turn_count": 4}
        topic2 = {"topic_id": 2, "label": "voucher / waitlist", "top_terms": ["voucher", "waitlist"], "turn_count": 3}

        cb1 = atlas_engine.append_topic_to_codebook(base_cb, topic1, domain_name="Prepaid Debit Cards")
        self.assertEqual(len(cb1["domains"]), 11)
        added1 = cb1["domains"][-1]
        self.assertEqual(added1["name"], "Prepaid Debit Cards")
        self.assertEqual(added1["match_mode"], "exact")
        self.assertEqual(added1["roots_en"], ["prepaid", "card", "fee"])

        # Appending again with same name disambiguates cleanly and accumulates to 12 domains.
        cb2 = atlas_engine.append_topic_to_codebook(cb1, topic2, domain_name="Prepaid Debit Cards")
        self.assertEqual(len(cb2["domains"]), 12)
        ids = [d["id"] for d in cb2["domains"]]
        names = [d["name"] for d in cb2["domains"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))

        # Verify exact mode blocks 'feedback' / 'cards' false prefix collisions on 'fee' / 'card'.
        _, res = _run_codebook_dict(
            cb1,
            [
                "The program gave useful feedback about the workshop.",
                "The prepaid card charged a monthly fee.",
            ],
        )
        matched = set(res["quotes_df"].loc[res["quotes_df"]["domain_id"] == added1["id"], "text"])
        self.assertEqual(matched, {"The prepaid card charged a monthly fee."})

    def test_append_topic_fails_closed_on_empty_terms_or_bad_mode(self):
        base_cb = {"project": "SOFTWARE_TEST", "domains": []}
        with self.assertRaises(ValueError):
            atlas_engine.append_topic_to_codebook(base_cb, {"topic_id": 1, "top_terms": []})
        with self.assertRaises(ValueError):
            atlas_engine.append_topic_to_codebook(base_cb, {"topic_id": 1, "top_terms": ["rent"]}, match_mode="fuzzy")
        with self.assertRaises(ValueError):
            atlas_engine.append_topic_to_codebook(base_cb, {"topic_id": 1, "top_terms": ["voucher"]}, domain_id="交通")

        # Non-ASCII display name with omitted domain_id must still generate a non-empty valid domain id.
        non_ascii_name_cb = atlas_engine.append_topic_to_codebook(
            base_cb, {"topic_id": 1, "top_terms": ["voucher"]}, domain_name="交通"
        )
        added = non_ascii_name_cb["domains"][0]
        self.assertTrue(added["id"], "auto-generated domain id must be non-empty")
        self.assertEqual(added["name"], "交通")


class AddonCFalseAlarmSpotCheckTests(unittest.TestCase):
    def test_audit_flags_prefix_extension_negation_and_short_unfenced_and_clears_when_tightened(self):
        cb = {
            "project": "SOFTWARE_TEST Spot-Check",
            "domains": [
                {"id": "trans", "name": "Transportation", "roots_en": ["car"]},
                {"id": "housing", "name": "Housing", "roots_en": ["eviction"]},
                {"id": "exact_clean", "name": "Clean Exact", "match_mode": "exact", "roots_en": ["mortgage"]},
            ],
        }
        texts = [
            "My debit card fell out during my new career workshop.",
            "We didn\u2019t receive an eviction notice at all.",
            "The cars were parked outside.",
            "Our mortgage payment stayed predictable.",
        ]
        engine, res = _run_codebook_dict(cb, texts)
        audit = atlas_engine.audit_false_alarm_risks(res["quotes_df"], engine.domains)
        self.assertFalse(audit.empty)
        self.assertLessEqual(len(audit), len(res["quotes_df"]))

        # Prefix extension 'car' inside BOTH 'card' and 'career' collapses to 1 audit row listing both words.
        trans_rows = audit[audit["domain_id"] == "trans"]
        card_row = trans_rows[trans_rows["full_word"].str.lower().isin({"card", "career"})]
        self.assertEqual(len(card_row), 1, audit.to_dict("records"))
        self.assertTrue((card_row["risk_level"] == "High").all())
        self.assertTrue(card_row["flag_codes"].str.contains("prefix_extension").all())
        self.assertEqual(
            {w.strip() for w in card_row.iloc[0]["extension_words"].split(",") if w.strip()},
            {"card", "career"},
        )

        # Simple plural 'cars' should NOT be flagged as a High-risk prefix_extension.
        cars_rows = trans_rows[trans_rows["full_word"].str.lower() == "cars"]
        self.assertFalse(cars_rows["flag_codes"].str.contains("prefix_extension").any())

        # Nearby negation ('not' before 'eviction') must be flagged.
        housing_rows = audit[audit["domain_id"] == "housing"]
        self.assertEqual(len(housing_rows), 1)
        self.assertIn("negation_nearby", housing_rows.iloc[0]["flag_codes"])

        # Clean exact match with no negation must produce 0 flags.
        self.assertTrue(audit[audit["domain_id"] == "exact_clean"].empty)

        # Summary aggregates flagged patterns cleanly.
        summary = atlas_engine.summarize_false_alarm_risks(audit)
        self.assertFalse(summary.empty)
        self.assertIn("Flagged Matches", summary.columns)

        # Tightening Transportation with exclude_fences blocks card/career while preserving 'cars' or 'car'.
        tightened = atlas_engine.tighten_codebook_domain(cb, "trans", add_exclude_terms=["card", "career"])
        eng_t, res_t = _run_codebook_dict(tightened, texts)
        self.assertNotIn(
            "My debit card fell out during my new career workshop.",
            set(res_t["quotes_df"].loc[res_t["quotes_df"]["domain_id"] == "trans", "text"]),
        )
        # Switching Transportation to exact mode blocks all prefix extensions.
        exact_cb = atlas_engine.tighten_codebook_domain(cb, "trans", set_exact_mode=True)
        eng_e, res_e = _run_codebook_dict(exact_cb, texts + ["I repaired my car yesterday."])
        self.assertEqual(
            set(res_e["quotes_df"].loc[res_e["quotes_df"]["domain_id"] == "trans", "text"]),
            {"I repaired my car yesterday."},
        )

    def test_tighten_preserves_existing_nonzero_exclude_window_and_fails_closed_on_unknown_domain(self):
        cb = {
            "project": "SOFTWARE_TEST Window Preserve",
            "domains": [
                {
                    "id": "housing",
                    "name": "Housing",
                    "roots_en": ["rent"],
                    "exclude_fences": ["rental car"],
                    "exclude_window": 4,
                },
            ],
        }
        updated = atlas_engine.tighten_codebook_domain(cb, "housing", add_exclude_terms=["rental"])
        dom = updated["domains"][0]
        self.assertEqual(dom["exclude_window"], 4)
        self.assertIn("rental", dom["exclude_fences"])
        self.assertIn("rental car", dom["exclude_fences"])

        with self.assertRaises(ValueError):
            atlas_engine.tighten_codebook_domain(cb, "missing_domain", set_exact_mode=True)
        with self.assertRaises(ValueError):
            atlas_engine.tighten_codebook_domain(cb, "housing")


class AnalystAddonsUIWiringTests(unittest.TestCase):
    def _widget(self, at, accessor, label):
        for w in getattr(at, accessor):
            if w.label == label:
                return w
        self.fail(f"Widget {accessor} {label!r} not found")

    def _run(self, at):
        self._widget(at, "button", "Run Analysis").click()
        at.run()

    def _total_themes(self, at):
        val = str(next(m.value for m in at.metric if m.label == "Themes Found"))
        return int(val.split("of")[-1].strip())

    def test_sidebar_stack_and_add_theme_and_spotcheck_work_together_cleanly(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=25)
        at.run()
        self.assertFalse(list(at.exception), [e.value for e in at.exception])
        self.assertEqual(len(at.metric), 0)

        # Switch to Multi-Group Focus-Group Notes sample (10 Core Evaluation Themes) and Run Analysis.
        corpus_box = self._widget(at, "selectbox", "Corpus Dataset")
        gbi_opt = next(o for o in corpus_box.options if "Focus-Group Notes" in str(o))
        corpus_box.set_value(gbi_opt)
        at.run()
        self._run(at)
        self.assertFalse(list(at.exception))
        # Metric count must stay strictly 4.
        self.assertEqual(len(at.metric), 4)
        self.assertTrue(any("Spot-Check Matches" in t.label for t in at.tabs))
        self.assertEqual(self._total_themes(at), 10)

        # Add-on A: check Optional Add-On theme 'Program Enrollment & Paperwork' => 11 active themes.
        self._widget(at, "checkbox", "Program Enrollment & Paperwork").check()
        at.run()
        self._run(at)
        self.assertFalse(list(at.exception))
        self.assertEqual(len(at.metric), 4)
        self.assertEqual(self._total_themes(at), 11)
        self.assertTrue(
            any("Save active themes (.yaml)" in d.label for d in at.get("download_button")),
            "Sidebar must offer download of the customized active themes",
        )

        # Add-on B: append one discovered cluster on top of the 11 active themes => 12 themes.
        name_input = self._widget(at, "text_input", "New theme name (optional)")
        name_input.set_value("Local Program Cards")
        add_btn = self._widget(at, "button", "Add Theme to Active Themes")
        add_btn.click()
        at.run()
        self.assertFalse(list(at.exception))
        self.assertEqual(len(at.metric), 4)
        self.assertEqual(self._total_themes(at), 12)

    def test_spotcheck_ui_flags_and_tightens_domain_live(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=25)
        at.run()
        corpus_box = self._widget(at, "selectbox", "Corpus Dataset")
        up_opt = next(o for o in corpus_box.options if "Upload" in str(o))
        corpus_box.set_value(up_opt)
        at.run()
        uploader = next(u for u in at.file_uploader if "txt" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        sample_txt = (
            "# SOFTWARE_TEST\n"
            "P1: My debit card fell out during my new career workshop.\n"
            "P2: Our car broke down on the way to work.\n"
        ).encode("utf-8")
        uploader.set_value(("software_test_spotcheck.txt", sample_txt, "text/plain"))
        at.run()

        # Upload a minimal unfenced codebook with short root 'car' so Spot-Check flags 'card'/'career'.
        cb_uploader = next(u for u in at.file_uploader if "yaml" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        cb_yaml = yaml.safe_dump({
            "project": "SOFTWARE_TEST Unfenced",
            "domains": [{"id": "car_dom", "name": "Car Access", "roots_en": ["car"]}],
        }).encode("utf-8")
        cb_uploader.set_value(("software_test_unfenced.yaml", cb_yaml, "application/x-yaml"))
        at.run()
        self._run(at)
        self.assertFalse(list(at.exception))
        self.assertEqual(len(at.metric), 4)
        self.assertEqual(int(next(m.value for m in at.metric if m.label == "Theme Matches")), 2)

        # Spot-Check UI should surface Check First priority and offer BOTH quick-fix buttons.
        self.assertTrue(any("Check First (Partial-Word Match)" in str(m.value) for m in at.markdown))

        # Changing uploaded text so ext_words shifts from {'card','career'} to {'cargo'} must not crash on stale widget state.
        alt_txt = (
            "# SOFTWARE_TEST\n"
            "P1: The cargo van arrived late.\n"
        ).encode("utf-8")
        uploader = next(u for u in at.file_uploader if "txt" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        uploader.set_value(("software_test_spotcheck_alt.txt", alt_txt, "text/plain"))
        at.run()
        self._run(at)
        self.assertFalse(list(at.exception))

        # Restore original text and test Exclude Selected Words button removes 'card'/'career' hit while keeping 'car'.
        uploader = next(u for u in at.file_uploader if "txt" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        uploader.set_value(("software_test_spotcheck.txt", sample_txt, "text/plain"))
        at.run()
        self._run(at)
        self.assertFalse(list(at.exception))

        excl_btn = self._widget(at, "button", "Exclude Selected Words from Theme")
        self.assertFalse(excl_btn.disabled)
        excl_btn.click()
        at.run()
        self.assertFalse(list(at.exception))
        self.assertEqual(int(next(m.value for m in at.metric if m.label == "Theme Matches")), 1)
        # Re-run with original uploaded unfenced codebook and test Exact Whole-Word Matching button.
        self._run(at)
        self.assertEqual(int(next(m.value for m in at.metric if m.label == "Theme Matches")), 2)
        exact_btn = self._widget(at, "button", "Switch Theme to Exact Whole-Word Matching")
        exact_btn.click()
        at.run()
        self.assertFalse(list(at.exception))
        self.assertEqual(int(next(m.value for m in at.metric if m.label == "Theme Matches")), 1)
        self.assertTrue(any("0 of 1 theme matches flagged for review" in str(s.value) for s in at.success))

    def test_quick_start_guide_documents_all_three_addons(self):
        text = QUICK_START.read_text(encoding="utf-8")
        for required in ("Optional Add-On", "Spot-Check", "Discover"):
            self.assertIn(required, text)

    def test_same_update_callbacks_markdown_literal_meta_and_preserved_window_disclosure(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=25)
        at.run()
        corpus_box = self._widget(at, "selectbox", "Corpus Dataset")
        up_opt = next(o for o in corpus_box.options if "Upload" in str(o))
        corpus_box.set_value(up_opt)
        at.run()
        uploader = next(u for u in at.file_uploader if "txt" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        uploader.set_value((
            "software_test_r1.txt",
            b"# SOFTWARE_TEST\nP1: My car and card sat near the bus stop.\n",
            "text/plain",
        ))
        cb_uploader = next(u for u in at.file_uploader if "yaml" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        cb_yaml = yaml.safe_dump({
            "project": "SOFTWARE_TEST Windowed",
            "domains": [{
                "id": "car_dom",
                "name": "Car Access",
                "roots_en": ["car"],
                "exclude_fences": ["zebra"],
                "exclude_window": 4,
            }],
        }).encode("utf-8")
        cb_uploader.set_value(("software_test_windowed.yaml", cb_yaml, "application/x-yaml"))
        at.run()
        self._run(at)
        self.assertFalse(list(at.exception))

        # Exclusion multiselect must advertise the actual preserved 4-word window.
        excl_ms = next((m for m in at.multiselect if "Words to exclude" in m.label), None)
        self.assertIsNotNone(excl_ms)
        self.assertIn("4-word", excl_ms.label)

        # Clearing exclusions and clicking Exclude in the same update must NOT apply stale words.
        excl_ms.set_value([])
        excl_btn = self._widget(at, "button", "Exclude Selected Words from Theme")
        excl_btn.click()
        at.run()
        self.assertFalse(list(at.exception))
        self.assertIsNone(
            at.session_state["session_override_bytes"],
            "Empty exclusion selection in the same update must be a no-op, not apply stale words",
        )

        # Unchecking exact mode, entering Markdown image syntax as custom name, and clicking Add in one update
        # must apply match_mode='prefix' AND never render the custom name via unescaped Markdown.
        img_name = "![x](https://example.invalid/pixel.png)"
        self._widget(at, "checkbox", "Use exact whole-word matching for added theme (recommended)").uncheck()
        self._widget(at, "text_input", "New theme name (optional)").set_value(img_name)
        self._widget(at, "button", "Add Theme to Active Themes").click()
        at.run()
        self.assertFalse(list(at.exception))
        active_cb = yaml.safe_load(at.session_state["session_override_bytes"])
        self.assertEqual(active_cb["domains"][-1]["match_mode"], "prefix")
        self.assertEqual(active_cb["domains"][-1]["name"], img_name)
        self.assertFalse(
            any(img_name in str(c.value) for c in (*at.caption, *at.info)),
            "Custom domain name with Markdown syntax must not be interpolated into Markdown caption/info",
        )
        self.assertTrue(
            any(img_name in str(t.value) for t in at.text),
            "In-app edit label must render literally via st.text",
        )


if __name__ == "__main__":
    unittest.main()
