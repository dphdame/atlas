"""[SOFTWARE_TEST FIXTURE — DEMONSTRATES SOFTWARE MECHANICS ONLY, NOT EMPIRICAL FINDINGS]

ATLAS v1.2 post-walkthrough acceptance suite (Points #1–#9, Rev 3 contract).

Covers:
- Zero decorative icons/emojis across app.py, atlas_report.py, and rendered widgets.
- Point #1: Collapsible 10 Core Evaluation Themes + 5 Optional Add-On Themes + Upload Custom YAML
  (Replace vs. Combine), Clear -> Run empty-codebook guardrail, schema-stable empty frequencies_df,
  provenance banner + View active theme keywords expander.
- Points #2–#4: Reconciled KPIs, Group x Theme Grid first (uniform ✓/—, Groups column, Notes entries
  toggle, Hide 0-match themes), Notes Volume bar second, verbatim_only reconciliation across
  notes-only, notes+obs, transcript-only, and mixed Group-mode corpora.
- Point #5: Discover Unlisted Themes index-safe compute_topic_codebook_overlap (including colliding
  turn_id==1 across files), participant-ID stopwords, bullet-prefixed `- P1:` stripping.
- Point #6: Opt-in pure-Python DL=1 spelling tolerance (genuine rescues, prefix-shadowed no-double-row,
  <=4-char zero false positives, context/exclude fences, multi-occurrence cardinality, benign inflections
  vs. <=3-char strict stems, and UI Spot-Check exclusion of flagged spelling matches).
- Point #7: Safe Q#/Facilitator structural-row exclusion + Notable Quotes/P#/quoted-speech guards +
  Excluded Questions & Session Headers drawer.
- Point #8: Multi-sheet Excel selection, incompatible-sheet error, exact written-answers/blank-rows
  wording (never "response rate"), duplicate_id_policy="per_row" vs. "combine" preserving
  respondent_id while allow_duplicate_ids=False still raises ValueError.
- Point #9: Full printable summary report (atlas_summary_report.docx) programmatically parsed and
  reconciled cell-for-cell with frequencies_df, quotes_df, discovery, audit_df, and exports.
- Public-repo privacy guardrail (zero private agency/pilot/staff identifiers or local paths).

Run: .venv/bin/python -W error::RuntimeWarning -m unittest tests/test_v12_post_walkthrough.py -v
"""

import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import docx
import openpyxl
import pandas as pd
import yaml
from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import atlas_discover  # noqa: E402
import atlas_engine  # noqa: E402
import atlas_report  # noqa: E402
from atlas_engine import AtlasEngine, FREQUENCY_COLUMNS  # noqa: E402
from universal_transcript_parser import UniversalTranscriptParser  # noqa: E402

APP_PATH = REPO / "app.py"
CONFIG_DIR = REPO / "config"
SAMPLES_DIR = REPO / "data" / "samples"
CORE_YAML = CONFIG_DIR / "gbi_focus_group_starter.yaml"
ADDONS_YAML = CONFIG_DIR / "optional_delivery_addons.yaml"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _has_decorative_icon(text: str) -> list[str]:
    hits = []
    for ch in str(text):
        cp = ord(ch)
        if (
            (0x1F300 <= cp <= 0x1FAFF)
            or (0x2600 <= cp <= 0x27BF and cp != 0x2713)
            or (cp in (0x25B6, 0x25BA, 0x25C0, 0x25BC, 0x25B2, 0xFE0F))
        ):
            hits.append(f"{ch} ({hex(cp)})")
    return hits


def _widget(at, accessor: str, label: str):
    for w in getattr(at, accessor):
        if w.label == label:
            return w
    raise AssertionError(f"Widget {accessor} {label!r} not found; have {[w.label for w in getattr(at, accessor)]}")


def _corpus_uploader(at):
    return next(
        u for u in at.file_uploader
        if "csv" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])}
    )


def _codebook_uploader(at):
    return next(
        u for u in at.file_uploader
        if "yaml" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])}
    )


def _run(at):
    _widget(at, "button", "Run Analysis").click()
    at.run()
    return at


def _make_xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    first = True
    for sheet_name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(title=sheet_name)
        ws.title = sheet_name
        first = False
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_notes_docx_bytes(rows: list[tuple[str, str, str]], title: str = "SOFTWARE_TEST Focus Group Notes") -> bytes:
    document = docx.Document()
    document.add_paragraph(title)
    document.add_paragraph("Question 1: How has the program affected your household?")
    table = document.add_table(rows=1 + len(rows), cols=3)
    for idx, hdr in enumerate(("Key Points", "Notable Quotes", "Observations")):
        table.rows[0].cells[idx].text = hdr
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, val in enumerate(row):
            table.rows[r_idx].cells[c_idx].text = val
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


# ==============================================================================
# 1. Zero Decorative Icons & Emojis
# ==============================================================================
class ZeroDecorativeIconsTests(unittest.TestCase):
    def test_zero_decorative_icons_in_app_and_report_source(self):
        for path in (APP_PATH, REPO / "atlas_report.py"):
            hits = _has_decorative_icon(path.read_text(encoding="utf-8"))
            self.assertEqual(hits, [], f"{path.name} contains decorative icons/emojis: {hits[:10]}")

    def test_zero_decorative_icons_in_rendered_ui_labels(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        corpus_box = _widget(at, "selectbox", "Corpus Dataset")
        corpus_box.set_value(next(o for o in corpus_box.options if "Focus-Group Notes" in str(o)))
        at.run()
        _run(at)
        self.assertFalse(list(at.exception), [e.value for e in at.exception])
        labels = [
            *[t.label for t in at.tabs],
            *[b.label for b in at.button],
            *[e.label for e in at.expander],
            *[m.label for m in at.metric],
            *[d.label for d in at.get("download_button")],
        ]
        for lbl in labels:
            self.assertEqual(_has_decorative_icon(lbl), [], f"Decorative icon in widget label: {lbl!r}")


# ==============================================================================
# 2. Point #1: Collapsible Theme Drawers, Clear->Run Guardrail, Custom Upload
# ==============================================================================
class CollapsibleThemeMenuAndGuardrailTests(unittest.TestCase):
    def test_core_10_and_addons_5_have_zero_overlap_and_exact_structure(self):
        core = yaml.safe_load(CORE_YAML.read_text(encoding="utf-8"))["domains"]
        addons = yaml.safe_load(ADDONS_YAML.read_text(encoding="utf-8"))["domains"]
        self.assertEqual(len(core), 10)
        self.assertEqual(len(addons), 5)
        core_ids = {d["id"] for d in core}
        addon_ids = {d["id"] for d in addons}
        self.assertEqual(core_ids & addon_ids, set())
        self.assertEqual(addons[0]["id"], "program_enrollment_paperwork")
        self.assertIn("healthcare_medical", core_ids)
        self.assertIn("legal_justice", core_ids)
        self.assertIn("employment_work", core_ids)
        self.assertIn("education_training", core_ids)

    def test_sidebar_hides_pfl_and_labor_market_and_blocks_zero_theme_run(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        corpus_box = _widget(at, "selectbox", "Corpus Dataset")
        self.assertEqual(len(corpus_box.options), 2)
        all_labels = " ".join(
            [str(o) for s in at.selectbox for o in s.options]
            + [c.label for c in at.checkbox]
            + [e.label for e in at.expander]
        )
        self.assertNotIn("Paid Family Leave", all_labels)
        self.assertNotIn("pfl_case_study", all_labels)
        self.assertNotIn("labor_market_codebook", all_labels)

        # Clear all 10 Core themes and click Run Analysis -> clean error, zero crash.
        corpus_box.set_value(next(o for o in corpus_box.options if "Focus-Group Notes" in str(o)))
        at.run()
        clear_btns = [b for b in at.button if b.label == "Clear"]
        self.assertGreaterEqual(len(clear_btns), 1)
        clear_btns[0].click()
        at.run()
        _run(at)
        self.assertFalse(list(at.exception), [e.value for e in at.exception])
        self.assertEqual(len(at.error), 1)
        self.assertIn("Select at least one theme", str(at.error[0].value))
        self.assertEqual(len(at.metric), 0)

    def test_engine_empty_codebook_returns_schema_stable_frequencies_df(self):
        with tempfile.TemporaryDirectory() as tmp:
            cb_path = Path(tmp) / "empty.yaml"
            cb_path.write_text("project: SOFTWARE_TEST Empty\ndomains: []\n", encoding="utf-8")
            eng = AtlasEngine(str(cb_path))
            res = eng.process_turns(
                [{"source_id": "a.txt", "unit_id": "a.txt", "document_name": "a.txt", "speaker": "P1", "text": "Rent."}],
                {"a.txt": "0" * 64},
            )
            self.assertEqual(list(res["frequencies_df"].columns), FREQUENCY_COLUMNS)
            self.assertEqual(len(res["frequencies_df"]), 0)

    def test_upload_custom_yaml_replace_vs_combine_modes(self):
        custom_yaml = yaml.safe_dump({
            "project": "SOFTWARE_TEST Pilot Extra",
            "domains": [{"id": "pet_care", "name": "Pet Care Costs", "roots_en": ["veterinarian", "pet food"]}],
        }).encode("utf-8")
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value((
            "software_test_custom.txt",
            b"P1: Rent went up and the veterinarian visit got expensive.\n",
            "text/plain",
        ))
        _codebook_uploader(at).set_value(("pilot_extra.yaml", custom_yaml, "application/x-yaml"))
        at.run()
        # Default mode: Replace checked themes => 1 active theme total.
        _run(at)
        self.assertFalse(list(at.exception))
        self.assertEqual(str(_widget(at, "metric", "Themes Found").value), "1 of 1")

        # Switch to Combine with checked themes => 10 Core + 1 Custom = 11 active themes total.
        mode_radio = _widget(at, "radio", "How to apply uploaded themes")
        mode_radio.set_value("Combine with checked themes above")
        at.run()
        _run(at)
        self.assertFalse(list(at.exception))
        self.assertEqual(str(_widget(at, "metric", "Themes Found").value), "2 of 11")
        self.assertTrue(any("Save active themes (.yaml)" in d.label for d in at.get("download_button")))
        self.assertTrue(any("How these themes work:" in str(m.value) for m in at.markdown))
        self.assertTrue(any("View active theme keywords" in e.label for e in at.expander))


# ==============================================================================
# 3. Points #2–#4: Reconciled KPIs, Verbatim Parity, Option A Grid
# ==============================================================================
class ReconciledKPIsAndOptionAGridTests(unittest.TestCase):
    def _verify_group_reconciliation(self, at, expected_obs: bool = False):
        self.assertFalse(list(at.exception), [e.value for e in at.exception])
        self.assertFalse(list(at.error), [e.value for e in at.error])
        matches_kpi = int(str(_widget(at, "metric", "Theme Matches").value).replace(",", ""))
        expected_cols = (
            ["Theme", "Focus Groups", "Theme Matches", "Verbatim Quotes", "Paraphrased Key Points", "Note-Taker Observations"]
            if expected_obs
            else ["Theme", "Focus Groups", "Theme Matches", "Verbatim Quotes", "Paraphrased Key Points"]
        )
        summary_df = next(df.value for df in at.dataframe if list(df.value.columns) == expected_cols)
        self.assertEqual(int(summary_df["Theme Matches"].sum()), matches_kpi)
        for _, row in summary_df.iterrows():
            parts_sum = int(row["Verbatim Quotes"]) + int(row["Paraphrased Key Points"])
            if expected_obs:
                parts_sum += int(row["Note-Taker Observations"])
            self.assertEqual(parts_sum, int(row["Theme Matches"]), dict(row))

    def test_group_reconciliation_holds_across_notes_transcripts_and_mixed_corpora(self):
        notes_bytes = _make_notes_docx_bytes([
            ("P1: Rent went up this quarter.", '"The rent increase hurt our budget."', "Looked stressed about rent."),
            ("P2: Groceries cost more every week.", "", "Nodded in agreement."),
        ])
        tx_bytes = b"P1: My landlord raised the rent.\nP2: The bus route changed.\n"

        # 1. Notes-only (no observations)
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value([("room_a.docx", notes_bytes, DOCX_MIME)])
        at.run()
        _run(at)
        self._verify_group_reconciliation(at, expected_obs=False)

        # 2. Notes-only WITH observations enabled
        _widget(at, "checkbox", "Include Note-Taker Observations").check()
        at.run()
        _run(at)
        self._verify_group_reconciliation(at, expected_obs=True)

        # 3. Transcript-only in Group Mode (verbatim_turn MUST count in Verbatim Quotes!)
        at_tx = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at_tx.run()
        _corpus_uploader(at_tx).set_value([
            ("session_1.txt", tx_bytes, "text/plain"),
            ("session_2.txt", b"P1: Groceries and rent were both covered.\n", "text/plain"),
        ])
        at_tx.run()
        _widget(at_tx, "radio", "Data Type").set_value("Group / summarized notes")
        at_tx.run()
        _run(at_tx)
        self.assertTrue(any(m.label == "Entries Scanned" for m in at_tx.metric))
        self._verify_group_reconciliation(at_tx, expected_obs=False)

        # 4. Mixed notes + transcript in Group Mode
        at_mix = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at_mix.run()
        _corpus_uploader(at_mix).set_value([
            ("room_notes.docx", notes_bytes, DOCX_MIME),
            ("room_transcript.txt", tx_bytes, "text/plain"),
        ])
        at_mix.run()
        _run(at_mix)
        self.assertTrue(any(m.label == "Entries Scanned" for m in at_mix.metric))
        self._verify_group_reconciliation(at_mix, expected_obs=False)

    def test_grid_controls_toggle_entries_and_hide_zero_match_themes(self):
        notes_a = _make_notes_docx_bytes([("P1: Rent was high.", '"Rent doubled."', "")])
        notes_b = _make_notes_docx_bytes([("P1: Groceries were expensive.", "", "")])
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value([
            ("group_a.docx", notes_a, DOCX_MIME),
            ("group_b.docx", notes_b, DOCX_MIME),
        ])
        at.run()
        _run(at)
        self.assertFalse(list(at.exception))
        # All 10 themes visible by default; hiding 0-match themes leaves only the 2 matched themes.
        full_tbl = next(df.value for df in at.dataframe if "Focus Groups" in df.value.columns)
        self.assertEqual(len(full_tbl), 10)
        _widget(at, "radio", "Grid shows").set_value("Notes entries per group")
        _widget(at, "checkbox", "Hide 0-match themes").check()
        at.run()
        self.assertFalse(list(at.exception))
        filtered_tbl = next(df.value for df in at.dataframe if "Focus Groups" in df.value.columns)
        self.assertEqual(len(filtered_tbl), 2)
        self.assertTrue((filtered_tbl["Theme Matches"] > 0).all())


# ==============================================================================
# 4. Point #5: Discover Unlisted Themes (Index-Safe Join & Speaker Stopwords)
# ==============================================================================
class DiscoverUnlistedThemesAndOverlapTests(unittest.TestCase):
    def test_overlap_joins_by_index_with_colliding_turn_ids_and_exact_thresholds(self):
        # Two files BOTH have turn_id == 1: file_a is coded (housing), file_b is uncoded!
        turns = [
            {"source_id": "file_a.txt", "unit_id": "file_a.txt", "turn_id": 1, "speaker": "P1",
             "text": "rent landlord eviction lease apartment", "matched_domains": ["housing"]},
            {"source_id": "file_a.txt", "unit_id": "file_a.txt", "turn_id": 2, "speaker": "P2",
             "text": "rent deposit lease apartment landlord", "matched_domains": ["housing"]},
            {"source_id": "file_b.txt", "unit_id": "file_b.txt", "turn_id": 1, "speaker": "P1",
             "text": "debit prepaid ATM banking kiosk fee", "matched_domains": []},
            {"source_id": "file_b.txt", "unit_id": "file_b.txt", "turn_id": 2, "speaker": "P2",
             "text": "debit prepaid ATM banking reload fee", "matched_domains": []},
            {"source_id": "file_c.txt", "unit_id": "file_c.txt", "turn_id": 1, "speaker": "P1",
             "text": "workshop mentoring cohort coaching peers", "matched_domains": ["employment"]},
            {"source_id": "file_c.txt", "unit_id": "file_c.txt", "turn_id": 2, "speaker": "P2",
             "text": "workshop mentoring cohort coaching peers", "matched_domains": []},
        ]
        disc = atlas_discover.discover_topics(turns, n_topics=3, random_state=42)
        overlap = atlas_discover.compute_topic_codebook_overlap(disc, turns, {"housing": "Housing", "employment": "Employment"})
        self.assertEqual(len(overlap), 3)
        # Conservation across every cluster and across the full corpus.
        self.assertEqual(sum(v["total_count"] for v in overlap.values()), len(turns))
        self.assertEqual(sum(v["uncoded_count"] for v in overlap.values()), 3)
        self.assertEqual(sum(v["covered_count"] for v in overlap.values()), 3)
        statuses = {v["coverage_status"] for v in overlap.values()}
        self.assertEqual(statuses, {"mostly_covered", "partially_uncoded", "mostly_uncoded"})
        labels = " ".join(v["coverage_label"] for v in overlap.values())
        self.assertIn("Mostly Covered by Active Themes", labels)
        self.assertIn("Partially Uncoded", labels)
        self.assertIn("Mostly Uncoded by Active Themes", labels)

    def test_speaker_id_stopwords_and_bullet_prefixed_speaker_stripping(self):
        turns = [
            {"turn_id": 1, "unit_id": "u1", "speaker": "P1", "text": "P1 P2 participant rent landlord apartment"},
            {"turn_id": 2, "unit_id": "u2", "speaker": "P2", "text": "P12 participant groceries food pantry"},
        ]
        disc = atlas_discover.discover_topics(turns, n_topics=2, random_state=42)
        all_terms = {w.lower() for t in disc["topics"] for w in t["top_terms"]}
        for forbidden in ("p1", "p2", "p12", "participant"):
            self.assertNotIn(forbidden, all_terms)

        notes_bytes = _make_notes_docx_bytes([
            ("- P1: Groceries cost less this month.", "", ""),
            ("• P2: Rent stayed on time.", "", ""),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bullet_speakers.docx"
            p.write_bytes(notes_bytes)
            parsed = UniversalTranscriptParser().parse_file(str(p))
        self.assertEqual([(t["speaker"], t["text"]) for t in parsed], [
            ("P1", "Groceries cost less this month."),
            ("P2", "Rent stayed on time."),
        ])


# ==============================================================================
# 5. Point #6: Bounded Spelling Tolerance & Spot-Check Cleanup
# ==============================================================================
class SpotCheckAndBoundedSpellingToleranceTests(unittest.TestCase):
    def test_spelling_tolerance_rescues_genuine_typos_and_blocks_short_roots_and_fences(self):
        engine = AtlasEngine(str(CORE_YAML))
        genuine_typos = [
            ("t1", "We bought gorceries at the store.", "food_groceries_basic_needs"),
            ("t2", "Finding chldcare was hard.", "family_caregiving_wellbeing"),
            ("t3", "Our housng stayed secure.", "housing_rent_stability"),
            ("t4", "We avoided an evction notice.", "housing_rent_stability"),
            ("t5", "Health insurace covered visits.", "healthcare_medical"),
            ("t6", "My paychek arrived on Friday.", "employment_work"),
            ("t7", "La educacoin de mis hijos mejoró.", "education_training"),
        ]
        turns = [
            {"source_id": f"{tid}.txt", "unit_id": f"{tid}.txt", "document_name": f"{tid}.txt", "speaker": "P1", "text": txt}
            for tid, txt, _ in genuine_typos
        ]
        hashes = {t["source_id"]: "0" * 64 for t in turns}

        res_off = engine.process_turns(turns, hashes, spelling_tolerance=False)
        self.assertEqual(len(res_off["quotes_df"]), 0)
        self.assertEqual(len(res_off["typo_matches_df"]), 0)

        res_on = engine.process_turns(turns, hashes, spelling_tolerance=True)
        matched = dict(zip(res_on["quotes_df"]["source_id"], res_on["quotes_df"]["domain_id"]))
        for tid, txt, expected_dom in genuine_typos:
            with self.subTest(tid=tid):
                self.assertEqual(matched.get(f"{tid}.txt"), expected_dom)
                # Original text and char span are never rewritten.
                qrow = res_on["quotes_df"][res_on["quotes_df"]["source_id"] == f"{tid}.txt"].iloc[0]
                self.assertEqual(qrow["text"], txt)
                span = qrow["text"][int(qrow["match_char_start"]):int(qrow["match_char_end"])]
                self.assertEqual(span, qrow["match_text"])
        self.assertEqual(len(res_on["typo_matches_df"]), len(genuine_typos))

        # Prefix-shadowed typos (`grocereis` starts with `grocer`, `childcre` starts with `child`)
        # match via the normal prefix rule and emit ZERO rows in typo_matches_df!
        shadowed = [
            {"source_id": "sh1.txt", "unit_id": "sh1.txt", "document_name": "sh1.txt", "speaker": "P1",
             "text": "We bought grocereis and paid for childcre."},
        ]
        res_shadow = engine.process_turns(shadowed, {"sh1.txt": "0" * 64}, spelling_tolerance=True)
        self.assertEqual(set(res_shadow["quotes_df"]["domain_id"]),
                         {"food_groceries_basic_needs", "family_caregiving_wellbeing"})
        self.assertEqual(len(res_shadow["typo_matches_df"]), 0)

        # <=4-char roots must NEVER fire typo matches on near-neighbors (went/rent, can/car, will/bill, good/food).
        short_negs = [
            {"source_id": "sn.txt", "unit_id": "sn.txt", "document_name": "sn.txt", "speaker": "P1",
             "text": "I went there and can do what will feel good."},
        ]
        res_sn = engine.process_turns(short_negs, {"sn.txt": "0" * 64}, spelling_tolerance=True)
        self.assertEqual(len(res_sn["quotes_df"]), 0)
        self.assertEqual(len(res_sn["typo_matches_df"]), 0)

    def test_spelling_tolerance_enforces_context_and_exclude_fences_and_cardinality(self):
        cb = {
            "project": "SOFTWARE_TEST Fenced Typos",
            "domains": [
                {
                    "id": "food", "name": "Food", "roots_en": ["groceries", "pantry"],
                    "context_fences": ["store", "market"], "context_window": 4,
                },
                {
                    "id": "hous", "name": "Housing", "roots_en": ["housing"],
                    "exclude_fences": ["housng"], "exclude_window": 0,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cb_p = Path(tmp) / "cb.yaml"
            cb_p.write_text(yaml.safe_dump(cb, sort_keys=False), encoding="utf-8")
            eng = AtlasEngine(str(cb_p))
            turns = [
                # Missing context fence -> blocked!
                {"source_id": "u1.txt", "unit_id": "u1.txt", "document_name": "u1.txt", "speaker": "P1",
                 "text": "We bought gorceries yesterday."},
                # Two typo tokens in ONE entry/domain WITH context fence -> 2 typo_matches rows, 1 audit row!
                {"source_id": "u2.txt", "unit_id": "u2.txt", "document_name": "u2.txt", "speaker": "P1",
                 "text": "The store had gorceries and the market had patnry items."},
                # Exclude fence blocks 'housng'!
                {"source_id": "u3.txt", "unit_id": "u3.txt", "document_name": "u3.txt", "speaker": "P1",
                 "text": "Our housng stayed fine."},
            ]
            res = eng.process_turns(turns, {t["source_id"]: "0" * 64 for t in turns}, spelling_tolerance=True)
            self.assertEqual(list(res["quotes_df"]["source_id"]), ["u2.txt"])
            self.assertEqual(len(res["typo_matches_df"]), 2)
            audit = atlas_engine.audit_false_alarm_risks(
                res["quotes_df"], eng.domains, typo_matches_df=res["typo_matches_df"]
            )
            self.assertEqual(len(audit), 1)
            self.assertLessEqual(len(audit), len(res["quotes_df"]))
            self.assertEqual(
                {w.strip() for w in audit.iloc[0]["spelling_words"].split(",") if w.strip()},
                {"gorceries", "patnry"},
            )

    def test_benign_inflections_unflagged_while_short_stems_stay_strict(self):
        cb = {
            "project": "SOFTWARE_TEST Inflections",
            "domains": [
                {"id": "food", "name": "Food", "roots_en": ["grocery"]},
                {"id": "rent_d", "name": "Rent", "roots_en": ["rent"]},
                {"id": "kid_d", "name": "Kids", "roots_en": ["kid"]},
                {"id": "car_d", "name": "Car", "roots_en": ["car"]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cb_p = Path(tmp) / "cb.yaml"
            cb_p.write_text(yaml.safe_dump(cb, sort_keys=False), encoding="utf-8")
            eng = AtlasEngine(str(cb_p))
            turns = [
                {"source_id": "a.txt", "unit_id": "a.txt", "document_name": "a.txt", "speaker": "P1",
                 "text": "We bought groceries and rented a room."},
                {"source_id": "b.txt", "unit_id": "b.txt", "document_name": "b.txt", "speaker": "P2",
                 "text": "Stop kidding around; caring matters."},
            ]
            res = eng.process_turns(turns, {"a.txt": "0" * 64, "b.txt": "0" * 64})
            audit = atlas_engine.audit_false_alarm_risks(res["quotes_df"], eng.domains)
            # 'groceries' (-ies/-y on 7-char root) and 'rented' (-ed on 4-char root) must NOT be High prefix_extension.
            for dom in ("food", "rent_d"):
                sub = audit[audit["domain_id"] == dom]
                self.assertFalse(sub["flag_codes"].str.contains("prefix_extension").any(), sub.to_dict("records"))
            # <=3-char stems 'kid'->'kidding' and 'car'->'caring' MUST stay flagged as High prefix_extension!
            for dom in ("kid_d", "car_d"):
                sub = audit[audit["domain_id"] == dom]
                self.assertTrue(sub["flag_codes"].str.contains("prefix_extension").any(), dom)

    def test_ui_spotcheck_excludes_flagged_spelling_match_while_keeping_valid_match(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value((
            "software_test_typos.csv",
            b"respondent_id,response\nR1,We bought gorceries for the week.\nR2,We bought groceries today.\n",
            "text/csv",
        ))
        at.run()
        _widget(at, "checkbox", "Allow minor spelling typos (useful for open-ended surveys)").check()
        at.run()
        _run(at)
        self.assertFalse(list(at.exception))
        self.assertEqual(int(str(_widget(at, "metric", "Theme Matches").value)), 2)
        self.assertTrue(any("Check First (Spelling Match)" in str(m.value) for m in at.markdown))
        self.assertTrue(any("currently counted in your charts" in str(i.value) for i in at.info))

        # Click Exclude Selected Words from Theme -> blocks 'gorceries' while preserving 'groceries'!
        excl_btn = _widget(at, "button", "Exclude Selected Words from Theme")
        self.assertFalse(excl_btn.disabled)
        excl_btn.click()
        at.run()
        self.assertFalse(list(at.exception))
        self.assertEqual(int(str(_widget(at, "metric", "Theme Matches").value)), 1)


# ==============================================================================
# 6. Point #7: Safe Structural-Row Exclusion & Audit Drawer
# ==============================================================================
class SafeStructuralRowExclusionTests(unittest.TestCase):
    def test_excludes_unlabelled_prompts_but_protects_notable_quotes_p_labels_and_quoted_speech(self):
        notes_bytes = _make_notes_docx_bytes([
            ("Q2: What changed with your rent?", "", ""),
            ("Facilitator: Let us talk about groceries next.", "", ""),
            ("Q1: Participant repeated the question.", '"Facilitator: tell me about rent?"', ""),
            ("P1: Rent went up after Q1: January.", "", ""),
            ('"Facilitator: we heard that at the meeting about rent."', "", ""),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "structural_test.docx"
            p.write_bytes(notes_bytes)
            parser = UniversalTranscriptParser()
            turns = parser.parse_file(str(p))
            meta = next(iter(parser.last_document_metadata.values()))
        texts = [t["text"] for t in turns]
        # Rows 1 & 2 (unlabelled Q2:/Facilitator: with empty Notable Quotes) MUST be excluded & logged.
        self.assertFalse(any("What changed with your rent?" in t for t in texts))
        self.assertFalse(any("Let us talk about groceries next." in t for t in texts))
        excluded = meta.get("excluded_structural_rows") or []
        self.assertGreaterEqual(len(excluded), 2, excluded)
        # Rows 3, 4, 5 (Notable Quotes present, P1: label, quoted speech) MUST survive!
        self.assertTrue(any("tell me about rent" in t for t in texts), texts)
        self.assertTrue(any("Rent went up after Q1: January." in t for t in texts), texts)
        self.assertTrue(any("we heard that at the meeting about rent." in t for t in texts), texts)

        # Live UI exposes collapsed Excluded Questions & Session Headers drawer.
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value([("structural_room.docx", notes_bytes, DOCX_MIME)])
        at.run()
        _run(at)
        self.assertFalse(list(at.exception))
        self.assertTrue(
            any("Excluded Questions & Session Headers" in e.label for e in at.expander),
            [e.label for e in at.expander],
        )


# ==============================================================================
# 7. Point #8: Multi-Sheet Excel, Blank-Row Copy, Repeated Respondent IDs
# ==============================================================================
class ExcelSurveyContractTests(unittest.TestCase):
    def test_multisheet_xlsx_selection_blank_rows_and_never_response_rate(self):
        wb_bytes = _make_xlsx_bytes({
            "Q1_Housing": [
                ["respondent_id", "open_answer"],
                ["R01", "Rent increased this spring."],
                ["R02", ""],
                ["R03", "   "],
            ],
            "Q2_Food": [
                ["respondent_id", "open_answer"],
                ["R01", "Groceries cost more every week."],
                ["R02", "Food pantry helped our family."],
                ["R03", ""],
            ],
        })
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value([("quarterly.xlsx", wb_bytes, XLSX_MIME)])
        at.run()
        sheet_box = _widget(at, "selectbox", "Choose Excel tab")
        self.assertEqual(list(sheet_box.options), ["Q1_Housing", "Q2_Food"])
        _run(at)
        self.assertFalse(list(at.exception))
        self.assertEqual(int(str(_widget(at, "metric", "Written Answers Scanned").value)), 1)
        all_ui = " ".join([str(c.value) for c in at.caption] + [str(m.value) for m in at.markdown])
        self.assertIn("1 written answers scanned (2 rows left this question blank)", all_ui)
        self.assertNotIn("response rate", all_ui.lower())

        # Switch to Q2_Food tab and re-run -> 2 written answers, 1 blank.
        _widget(at, "selectbox", "Choose Excel tab").set_value("Q2_Food")
        at.run()
        _run(at)
        self.assertEqual(int(str(_widget(at, "metric", "Written Answers Scanned").value)), 2)

    def test_incompatible_multisheet_workbooks_fail_closed(self):
        wb1 = _make_xlsx_bytes({"Q1": [["id", "response"], ["R1", "Rent was high."]]})
        wb2 = _make_xlsx_bytes({"Summary": [["id", "response"], ["R2", "Food was high."]]})
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value([
            ("a.xlsx", wb1, XLSX_MIME),
            ("b.xlsx", wb2, XLSX_MIME),
        ])
        at.run()
        _run(at)
        self.assertFalse(list(at.exception))
        self.assertEqual(len(at.error), 1)
        self.assertIn("different tab names", str(at.error[0].value))

    def test_duplicate_id_policy_per_row_vs_combine_and_locked_error_default(self):
        csv_body = (
            "respondent_id,quarter,response\n"
            "R01,Q1,Rent went up in January.\n"
            "R01,Q2,Groceries went up in April.\n"
            "R02,Q1,The bus was late.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "panel.csv"
            p.write_text(csv_body, encoding="utf-8")
            parser = UniversalTranscriptParser()
            # Locked v1.1 default STILL raises ValueError!
            with self.assertRaises(ValueError):
                parser.parse_tabular(str(p), text_col="response", id_col="respondent_id")

            # per_row: 3 unique units, respondent_id preserved!
            per_row = parser.parse_tabular(str(p), text_col="response", id_col="respondent_id", duplicate_id_policy="per_row")
            self.assertEqual(len(per_row), 3)
            self.assertEqual(len({t["unit_id"] for t in per_row}), 3)
            self.assertEqual([t["respondent_id"] for t in per_row], ["R01", "R01", "R02"])

            # combine: 2 unique units (R01 merged), 3 turns total!
            combined = parser.parse_tabular(str(p), text_col="response", id_col="respondent_id", duplicate_id_policy="combine")
            self.assertEqual(len(combined), 3)
            self.assertEqual(len({t["unit_id"] for t in combined}), 2)

            # Engine preserves respondent_id in quotes_df AND exported XLSX under per_row!
            res = AtlasEngine(str(CORE_YAML)).process_corpus(
                [str(p)], root_dir=tmp,
                tabular_options={"text_col": "response", "id_col": "respondent_id", "duplicate_id_policy": "per_row"},
            )
            self.assertEqual(res["total_documents"], 3)
            self.assertIn("respondent_id", res["quotes_df"].columns)
            self.assertEqual(set(res["quotes_df"]["respondent_id"]), {"R01", "R02"})
            out_dir = Path(tmp) / "exports"
            AtlasEngine(str(CORE_YAML)).export_results(res, str(out_dir))
            wb = openpyxl.load_workbook(out_dir / "actuarial_parameter_matrix.xlsx")
            ws_q = wb["Verbatim Quotes & Provenance"]
            q_hdr = [c.value for c in ws_q[1]]
            self.assertIn("Respondent ID", q_hdr)
            rid_idx = q_hdr.index("Respondent ID")
            xlsx_rids = [row[rid_idx] for row in ws_q.iter_rows(min_row=2, values_only=True)]
            self.assertEqual(set(xlsx_rids), {"R01", "R02"})
            ok, problems = AtlasEngine.verify_workbook_integrity(
                str(out_dir / "actuarial_parameter_matrix.xlsx"),
                str(out_dir / "provenance_manifest.json"),
            )
            self.assertTrue(ok, problems)

        # Live UI detects duplicate IDs and defaults to per_row vs combine cleanly.
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value([("panel.csv", csv_body.encode("utf-8"), "text/csv")])
        at.run()
        _widget(at, "selectbox", "Respondent ID column (optional)").set_value("respondent_id")
        at.run()
        dup_radio = _widget(at, "radio", "Repeated Respondent IDs detected")
        self.assertIn("Keep each row as its own response", dup_radio.value)
        _run(at)
        self.assertEqual(int(str(_widget(at, "metric", "Analytical Units").value)), 3)

        _widget(at, "radio", "Repeated Respondent IDs detected").set_value(
            "Combine repeated rows under one Respondent ID (N = unique respondents)"
        )
        at.run()
        _run(at)
        self.assertEqual(int(str(_widget(at, "metric", "Analytical Units").value)), 2)


# ==============================================================================
# 8. Point #9: Full Summary Report (.docx) Programmatic Reconciliation
# ==============================================================================
class FullSummaryReportDocxReconciliationTests(unittest.TestCase):
    def test_group_mode_docx_report_reconciles_every_table_and_banner(self):
        notes_a = _make_notes_docx_bytes([
            ("Q2: What changed?", "", ""),
            ("P1: Rent went up this quarter.", '"The rent increase hurt our budget."', ""),
            ("P2: Groceries cost more.", "", ""),
        ])
        notes_b = _make_notes_docx_bytes([
            ("P1: The bus route was reliable.", '"The bus gets me to work."', ""),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            pa = Path(tmp) / "group_alpha.docx"
            pb = Path(tmp) / "group_beta.docx"
            pa.write_bytes(notes_a)
            pb.write_bytes(notes_b)
            eng = AtlasEngine(str(CORE_YAML))
            res = eng.process_corpus([str(pa), str(pb)], root_dir=tmp, group_by_source=True)
            turns = res["tagged_turns_df"].to_dict("records")
            disc = atlas_discover.discover_topics(turns, n_topics=2, random_state=42)
            names_map = {str(d["id"]): str(d["name"]) for d in eng.domains}
            overlap = atlas_discover.compute_topic_codebook_overlap(disc, turns, names_map)
            audit = atlas_engine.audit_false_alarm_risks(res["quotes_df"], eng.domains)

            # Build Group summary table identically to app.py.
            rows = []
            for _, r in res["frequencies_df"].iterrows():
                dq = res["quotes_df"][res["quotes_df"]["domain_id"] == r["domain_id"]]
                n_v = int(len(atlas_engine.verbatim_only(dq)))
                n_p = int((dq["evidence_type"] == "key_point_paraphrase").sum())
                rows.append({
                    "Theme": str(r["domain_name"]),
                    "Focus Groups": f"{int(r['documents_reporting'])} of 2",
                    "Theme Matches": int(len(dq)),
                    "Verbatim Quotes": n_v,
                    "Paraphrased Key Points": n_p,
                })
            group_tbl = pd.DataFrame(rows)
            grid_rows = []
            for _, r in res["frequencies_df"].iterrows():
                for sid in sorted(res["file_hashes"]):
                    dq = res["quotes_df"][(res["quotes_df"]["domain_id"] == r["domain_id"]) & (res["quotes_df"]["source_id"] == sid)]
                    grid_rows.append({
                        "domain_name": str(r["domain_name"]),
                        "group_label": Path(sid).name,
                        "present": len(dq) > 0,
                        "matching_entries": int(len(dq)),
                        "groups_reporting": int(r["documents_reporting"]),
                    })
            grid_df = pd.DataFrame(grid_rows)

            raw_docx = atlas_report.build_summary_report_docx(
                res,
                group_mode=True,
                group_table=group_tbl,
                group_matrix=grid_df,
                discovery=disc,
                discovery_overlap=overlap,
                audit_df=audit,
                active_theme_names=[d["name"] for d in eng.domains],
                corpus_label="Sample Notes",
                is_fixture=True,
                spelling_tolerance=False,
            )
            self.assertTrue(raw_docx.startswith(b"PK\x03\x04"))
            doc = docx.Document(io.BytesIO(raw_docx))
            para_text = "\n".join(p.text for p in doc.paragraphs)
            table_text = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
            full_text = para_text + "\n" + table_text
            self.assertIn("SOFTWARE_TEST FIXTURE", full_text)
            self.assertIn("1. Run Overview & Source Provenance", para_text)
            self.assertIn("7. Excluded Questions & Session Headers (Not Coded)", para_text)
            self.assertNotIn("response rate", full_text.lower())

            # Verify KPI table matches engine exactly.
            kpi_tbl = next(t for t in doc.tables if [c.text.strip() for c in t.rows[0].cells] == ["Metric", "Value", "Definition"])
            kpi_map = {row.cells[0].text.strip(): row.cells[1].text.strip() for row in kpi_tbl.rows[1:]}
            self.assertEqual(kpi_map["Focus Groups"], "2")
            self.assertEqual(kpi_map["Theme Matches"], str(len(res["quotes_df"])))
            self.assertEqual(kpi_map["Notes Entries Scanned"], str(res["participant_turns_analyzed"]))

            # Verify Theme Summary table inside .docx matches group_tbl row-for-row.
            summary_tbl_doc = next(
                t for t in doc.tables
                if [c.text.strip() for c in t.rows[0].cells] == list(group_tbl.columns)
            )
            self.assertEqual(len(summary_tbl_doc.rows) - 1, len(group_tbl))
            doc_matches_sum = sum(int(r.cells[2].text.strip()) for r in summary_tbl_doc.rows[1:])
            self.assertEqual(doc_matches_sum, len(res["quotes_df"]))

            # Verify Excluded Questions audit table captured Q2: row.
            excl_tbl_doc = next(
                t for t in doc.tables
                if [c.text.strip() for c in t.rows[0].cells] == ["Source File", "Location", "Exclusion Reason", "Excluded Text"]
            )
            self.assertTrue(any("What changed?" in r.cells[-1].text for r in excl_tbl_doc.rows[1:]))

    def test_individual_excel_docx_report_reconciles_and_omits_fixture_banner(self):
        wb_bytes = _make_xlsx_bytes({
            "Q1": [
                ["respondent_id", "open_answer"],
                ["R01", "We bought gorceries this week."],
                ["R02", "Rent went up on the first."],
                ["R03", ""],
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "survey.xlsx"
            p.write_bytes(wb_bytes)
            eng = AtlasEngine(str(CORE_YAML))
            res = eng.process_corpus(
                [str(p)], root_dir=tmp,
                tabular_options={"text_col": "open_answer", "id_col": "respondent_id", "sheet_name": "Q1"},
                spelling_tolerance=True,
            )
            turns = res["tagged_turns_df"].to_dict("records")
            disc = atlas_discover.discover_topics(turns, n_topics=2, random_state=42)
            overlap = atlas_discover.compute_topic_codebook_overlap(disc, turns, {d["id"]: d["name"] for d in eng.domains})
            audit = atlas_engine.audit_false_alarm_risks(
                res["quotes_df"], eng.domains, typo_matches_df=res["typo_matches_df"]
            )
            raw_docx = atlas_report.build_summary_report_docx(
                res,
                group_mode=False,
                group_table=None,
                group_matrix=None,
                discovery=disc,
                discovery_overlap=overlap,
                audit_df=audit,
                active_theme_names=[d["name"] for d in eng.domains],
                corpus_label="survey.xlsx",
                is_fixture=False,
                spelling_tolerance=True,
            )
            doc = docx.Document(io.BytesIO(raw_docx))
            full_text = "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
                c.text for t in doc.tables for row in t.rows for c in row.cells
            )
            self.assertNotIn("SOFTWARE_TEST FIXTURE", full_text)
            self.assertNotIn("response rate", full_text.lower())
            self.assertIn("2 written answers scanned (1 rows left this question blank)", full_text)
            self.assertIn("gorceries", full_text)
            kpi_tbl = next(t for t in doc.tables if [c.text.strip() for c in t.rows[0].cells] == ["Metric", "Value", "Definition"])
            kpi_map = {row.cells[0].text.strip(): row.cells[1].text.strip() for row in kpi_tbl.rows[1:]}
            self.assertEqual(kpi_map["Analytical Units"], "2")
            self.assertEqual(kpi_map["Written Answers Scanned"], "2")
            self.assertEqual(kpi_map["Theme Matches"], "2")


# ==============================================================================
# 9. Codex Adversarial Regressions (Duplicate Names, Merged-Cell Guards, Hygiene)
# ==============================================================================
class CodexAdversarialRegressionTests(unittest.TestCase):
    def test_duplicate_theme_display_names_never_overwrite_each_other_in_grid_or_docx(self):
        # Includes Codex's three-way label collision: ("a", "Costs"), ("b", "Costs"), ("c", "Costs (a)").
        dup_yaml = yaml.safe_dump({
            "project": "SOFTWARE_TEST Duplicate Display Names",
            "domains": [
                {"id": "a", "name": "Costs", "roots_en": ["rent"]},
                {"id": "b", "name": "Costs", "roots_en": ["tuition"]},
                {"id": "c", "name": "Costs (a)", "roots_en": ["grocery"]},
            ],
        }).encode("utf-8")
        notes_bytes = _make_notes_docx_bytes([
            ("P1: Rent went up this quarter.", '"Rent doubled."', ""),
            ("P2: Grocery bill climbed.", "", ""),
        ])
        at = AppTest.from_file(str(APP_PATH), default_timeout=30)
        at.run()
        _corpus_uploader(at).set_value([("room_dup.docx", notes_bytes, DOCX_MIME)])
        _codebook_uploader(at).set_value(("dup_names.yaml", dup_yaml, "application/x-yaml"))
        at.run()
        _run(at)
        self.assertFalse(list(at.exception), [e.value for e in at.exception])
        self.assertEqual(int(str(_widget(at, "metric", "Theme Matches").value)), 3)

        # Verify Group Grid AND Volume charts encode Y strictly by domain_id (3 distinct rows, labelExpr set).
        import pyarrow as pa
        charts = list(at.get("vega_lite_chart"))
        grid_chart = next(
            c for c in charts
            if "Focus-group grid" in json.loads(c.proto.spec).get("description", "")
        )
        grid_spec = json.loads(grid_chart.proto.spec)
        grid_y = grid_spec["layer"][0]["encoding"]["y"]
        self.assertEqual(grid_y["field"], "domain_id")
        self.assertEqual(set(grid_y["sort"]), {"a", "b", "c"})
        self.assertIn("labelExpr", grid_y["axis"])
        grid_df = pd.concat([pa.ipc.open_stream(ds.data.data).read_all().to_pandas() for ds in grid_chart.proto.datasets])
        data_tiles = grid_df[grid_df["col_label"] != "Groups"]
        by_id = dict(zip(data_tiles["domain_id"], data_tiles["matching_entries"]))
        self.assertEqual(by_id, {"a": 2, "b": 0, "c": 1})

        vol_chart = next(
            c for c in charts
            if "Focus-group grid" not in json.loads(c.proto.spec).get("description", "")
        )
        vol_spec = json.loads(vol_chart.proto.spec)
        vol_y = vol_spec["layer"][0]["encoding"]["y"]
        self.assertEqual(vol_y["field"], "domain_id")
        self.assertEqual(set(vol_y["sort"]), {"a", "b", "c"})
        self.assertIn("labelExpr", vol_y["axis"])

        # Verify DOCX report grid also preserves all 3 distinct rows without collision.
        with tempfile.TemporaryDirectory() as tmp:
            cb_p = Path(tmp) / "dup.yaml"
            cb_p.write_bytes(dup_yaml)
            n_p = Path(tmp) / "room_dup.docx"
            n_p.write_bytes(notes_bytes)
            eng = AtlasEngine(str(cb_p))
            res = eng.process_corpus([str(n_p)], root_dir=tmp, group_by_source=True)
            docx_bytes = atlas_report.build_summary_report_docx(
                res,
                group_mode=True,
                group_table=None,
                group_matrix=data_tiles[["domain_id", "domain_name", "theme_label", "group_label", "present", "matching_entries", "groups_reporting"]],
                discovery=None,
                discovery_overlap=None,
                audit_df=pd.DataFrame(),
                active_theme_names=["Costs", "Costs", "Costs (a)"],
                corpus_label="room_dup.docx",
            )
            doc = docx.Document(io.BytesIO(docx_bytes))
            grid_tbl = next(t for t in doc.tables if [c.text.strip() for c in t.rows[0].cells][0] == "Theme" and "Groups" in [c.text.strip() for c in t.rows[0].cells])
            row_pairs = [(r.cells[0].text.strip(), r.cells[1].text.strip()) for r in grid_tbl.rows[1:]]
            self.assertEqual(len(row_pairs), 3, row_pairs)
            self.assertCountEqual([val for _, val in row_pairs], ["✓ (2)", "—", "✓ (1)"])

    def test_vertically_merged_cells_preserve_participant_and_notable_quote_guards(self):
        # Case A: P1 tag in col 0 vertically merged across rows 1 & 2; row 2 col 2 starts with "Facilitator:".
        # Case B: Notable Quote in col 1 vertically merged across rows 3 & 4; row 4 col 0 starts with "Facilitator:".
        document = docx.Document()
        document.add_paragraph("SOFTWARE_TEST Merged Guard Notes")
        document.add_paragraph("Question 1: Tell us about your experience.")
        tbl = document.add_table(rows=5, cols=3)
        for idx, hdr in enumerate(("Key Points", "Notable Quotes", "Observations")):
            tbl.rows[0].cells[idx].text = hdr
        # Case A (merged P1 key point cell spans rows 1 and 2)
        tbl.rows[1].cells[0].text = "P1: Rent went up this winter."
        tbl.rows[1].cells[2].text = "Spoke calmly."
        tbl.rows[1].cells[0].merge(tbl.rows[2].cells[0])
        tbl.rows[2].cells[2].text = "Facilitator: participant nodded during rent discussion."
        # Case B (merged Notable Quote spans rows 3 and 4)
        tbl.rows[3].cells[0].text = "Groceries cost more."
        tbl.rows[3].cells[1].text = '"We stretched every dollar for groceries."'
        tbl.rows[3].cells[1].merge(tbl.rows[4].cells[1])
        tbl.rows[4].cells[0].text = "Facilitator: echoed by another participant about rent."

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "merged_guards.docx"
            document.save(str(p))
            parser = UniversalTranscriptParser(
                include_evidence_types=("key_point_paraphrase", "notable_quote_verbatim", "observation")
            )
            turns = parser.parse_file(str(p))
        texts = [t["text"] for t in turns]
        self.assertTrue(any("participant nodded during rent discussion" in t for t in texts), texts)
        self.assertTrue(any("echoed by another participant about rent" in t for t in texts), texts)

    def test_no_local_filesystem_paths_in_public_repo_files(self):
        local_path_pat = re.compile(r"/Users/|C:\\Users\\")
        scan_paths = [
            REPO / "app.py",
            REPO / "atlas_engine.py",
            REPO / "atlas_discover.py",
            REPO / "atlas_report.py",
            REPO / "universal_transcript_parser.py",
            REPO / "README.md",
            *sorted((REPO / "config").glob("*.yaml")),
            *sorted((REPO / "docs").glob("*.md")),
        ]
        for path in scan_paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            with self.subTest(file=path.relative_to(REPO).as_posix()):
                self.assertIsNone(local_path_pat.search(text), f"{path.name} leaked local filesystem path")


if __name__ == "__main__":
    unittest.main()
