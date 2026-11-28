#!/usr/bin/env python3
"""
End-to-end Python-vs-Browser Parity & Live Chromium Verification for
ATLAS_Workbench.html (Zero-Install Browser Edition v1.2).
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import docx
import openpyxl
import yaml
from playwright.sync_api import sync_playwright

ATLAS_REPO = Path(__file__).resolve().parent.parent
STANDALONE_DIR = Path(__file__).resolve().parent
HTML_PATH = STANDALONE_DIR / "ATLAS_Workbench.html"
ASPX_PATH = STANDALONE_DIR / "ATLAS_Workbench.aspx"

sys.path.insert(0, str(ATLAS_REPO))
from atlas_engine import AtlasEngine, audit_false_alarm_risks  # noqa: E402
from universal_transcript_parser import UniversalTranscriptParser  # noqa: E402


def _py_run_sample(include_addons: bool = False, include_obs: bool = False) -> dict:
    core = yaml.safe_load((ATLAS_REPO / "config" / "gbi_focus_group_starter.yaml").read_text(encoding="utf-8"))
    domains = list(core["domains"])
    if include_addons:
        addons = yaml.safe_load((ATLAS_REPO / "config" / "optional_delivery_addons.yaml").read_text(encoding="utf-8"))
        domains.extend(addons["domains"])
    with tempfile.TemporaryDirectory() as tmp:
        cb = Path(tmp) / "cb.yaml"
        cb.write_text(yaml.safe_dump({"project": "Parity", "domains": domains}, sort_keys=False), encoding="utf-8")
        eng = AtlasEngine(str(cb))
        ev = ("key_point_paraphrase", "notable_quote_verbatim", "observation") if include_obs else ("key_point_paraphrase", "notable_quote_verbatim")
        samples = [
            str(ATLAS_REPO / "data" / "samples" / "software_test_gbi_group_treatment.docx"),
            str(ATLAS_REPO / "data" / "samples" / "software_test_gbi_group_control.docx"),
        ]
        res = eng.process_corpus(samples, root_dir=str(ATLAS_REPO), include_evidence_types=ev, group_by_source=True)
        audit = audit_false_alarm_risks(res["quotes_df"], eng.compiled_rules, typo_matches_df=res["typo_matches_df"])
        manifest = AtlasEngine.build_manifest(res)
        return {"res": res, "audit": audit, "manifest": manifest}


def _make_merged_guard_docx(path: Path) -> None:
    doc = docx.Document()
    doc.add_paragraph("SOFTWARE_TEST Merged Guard Notes")
    doc.add_paragraph("Question 1: Tell us about your experience.")
    tbl = doc.add_table(rows=6, cols=3)
    for idx, hdr in enumerate(("Key Points", "Notable Quotes", "Observations")):
        tbl.rows[0].cells[idx].text = hdr
    tbl.rows[1].cells[0].text = "P1: Rent went up this winter."
    tbl.rows[1].cells[2].text = "Spoke calmly."
    tbl.rows[1].cells[0].merge(tbl.rows[2].cells[0])
    tbl.rows[2].cells[2].text = "Facilitator: participant nodded during rent discussion."
    tbl.rows[3].cells[0].text = "Groceries cost more."
    tbl.rows[3].cells[1].text = '"We stretched every dollar for groceries."'
    tbl.rows[3].cells[1].merge(tbl.rows[4].cells[1])
    tbl.rows[4].cells[0].text = "Facilitator: echoed by another participant about rent."
    tbl.rows[5].cells[0].text = "Facilitator: Next question about transit."
    doc.save(str(path))


def _make_multisheet_survey_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Overview"
    ws1.append(["Metric", "Notes"])
    ws1.append(["Wave", "Q1"])

    ws2 = wb.create_sheet("Open_Ended")
    ws2.append(["Respondent_ID", "Open_Feedback", "Group"])
    ws2.append(["R01", "Our gorceries cost twice as much this month.", "Treatment"])
    ws2.append(["R01", "We went to the store and were kidding around.", "Treatment"])
    ws2.append(["R02", "Chldcare and educacoin expenses keep climbing.", "Control"])
    ws2.append(["R03", "", "Control"])
    ws2.append(["R04", "   ", "Control"])
    wb.save(str(path))


def run_parity_suite() -> None:
    assert HTML_PATH.is_file() and ASPX_PATH.is_file(), "Missing built standalone files"
    assert HTML_PATH.read_bytes() == ASPX_PATH.read_bytes(), ".html and .aspx must be byte-identical"

    # Zero decorative emojis check (allow only functional ✓, —, –, …, ×, −, ·, •)
    html_text = HTML_PATH.read_text(encoding="utf-8")
    emoji_pat = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF]")
    found_emojis = [m.group(0) for m in emoji_pat.finditer(html_text) if m.group(0) != "✓"]
    assert not found_emojis, f"Found decorative emoji(s) in standalone HTML: {found_emojis}"
    print("[ok] Zero decorative emojis & byte-identical .html / .aspx")

    # External script/link check in raw HTML
    assert not re.search(r"<script[^>]+src=|<link[^>]+href=['\"]https?://", html_text, re.I), "External script/CSS link found!"
    print("[ok] Zero external script/CSS references in HTML source")

    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and Path.home().joinpath("code/playwright-browsers").exists(): os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path.home() / "code/playwright-browsers")
    external_reqs: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        merged_docx = tmp / "merged_guards.docx"
        _make_merged_guard_docx(merged_docx)
        survey_xlsx = tmp / "survey_multi.xlsx"
        _make_multisheet_survey_xlsx(survey_xlsx)
        adv_yaml = tmp / "adv.yaml"
        adv_yaml.write_text(yaml.safe_dump({
            "project": "Adv Test",
            "domains": [{
                "id": "adv_xss",
                "name": "Costs <b>bold</b> <img src=x onerror=window.__xss=1>",
                "roots_en": ["rent", "paperwork"],
            }]
        }), encoding="utf-8")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True, viewport={"width": 1380, "height": 1100})
            context.on("request", lambda req: external_reqs.append(req.url) if not req.url.startswith(("file://", "blob:", "data:")) else None)
            page = context.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: page_errors.append(str(e)))

            page.goto(HTML_PATH.as_uri(), wait_until="domcontentloaded")
            page.get_by_text("Ready to analyze.").wait_for(timeout=15000)
            print("[ok] Booted ATLAS_Workbench.html cleanly via file://")

            # -----------------------------------------------------------------
            # Test 1: Sample Focus-Group Notes — Core 10, Core 10 + Add-Ons 5, + Observations
            # -----------------------------------------------------------------
            page.locator("#btn-load-sample").click()
            page.locator("#btn-run").click()
            page.locator('[data-kpi="matches"]').wait_for(timeout=10000)

            for label, inc_addons, inc_obs in [
                ("Sample Core 10 (no obs)", False, False),
                ("Sample Core 10 + Add-Ons 5 (no obs)", True, False),
                ("Sample Core 10 + Add-Ons 5 (with obs)", True, True),
            ]:
                py = _py_run_sample(include_addons=inc_addons, include_obs=inc_obs)
                br = page.evaluate(f"""() => {{
                    const api = window.__ATLAS_API__;
                    api.state.selectedCore = new Set(ATLAS_CORE_THEMES.map(r => r.id));
                    api.state.selectedAddon = {('new Set(ATLAS_ADDON_THEMES.map(r => r.id))' if inc_addons else 'new Set()')};
                    api.state.includeObservations = {str(inc_obs).lower()};
                    api.executeAnalysis(false);
                    return {{
                        results: api.state.results,
                        manifest: api.buildProvenanceManifest(api.state.results, api.state.runMeta),
                    }};
                }}""")
                py_m = py["manifest"]
                br_m = br["manifest"]
                assert br_m["total_documents"] == py_m["total_documents"], f"{label}: total_documents mismatch"
                assert br_m["participant_turns_analyzed"] == py_m["participant_turns_analyzed"], f"{label}: entries mismatch {br_m['participant_turns_analyzed']} != {py_m['participant_turns_analyzed']}"
                assert br_m["file_hashes"] == py_m["file_hashes"], f"{label}: SHA-256 file_hashes mismatch!"
                assert len(br["results"]["quotes"]) == len(py["res"]["quotes_df"]), f"{label}: quotes len mismatch"
                assert len(br["results"]["audit_rows"]) == len(py["audit"]), f"{label}: spotcheck len mismatch ({len(br['results']['audit_rows'])} vs {len(py['audit'])})"
                py_dom = {d["domain_id"]: d for d in py_m["domains"]}
                br_dom = {d["domain_id"]: d for d in br_m["domains"]}
                assert set(py_dom) == set(br_dom)
                for did, pd_row in py_dom.items():
                    bd_row = br_dom[did]
                    for k in ("documents_reporting", "total_documents", "prevalence_pct", "matching_turns", "audit_sha256"):
                        assert bd_row[k] == pd_row[k], f"{label} [{did}.{k}]: browser={bd_row[k]!r} != python={pd_row[k]!r}"
                print(f"[ok] 100% Python-vs-Browser parity: {label} (matches={len(br['results']['quotes'])}, spotcheck={len(br['results']['audit_rows'])}, SHA-256 exact)")

            # Capture live screenshots of Core 10 + Add-Ons 5 view for visual inspection!
            page.screenshot(path=str(STANDALONE_DIR / "preview_summary.png"), full_page=True)

            # Test clicking a ✓ tile jumps to filtered Coded Evidence + Question filter works!
            page.locator("td.tile.present").first.click()
            page.locator("#ev-theme").wait_for(timeout=5000)
            assert page.locator(".ed-evidence-row").count() > 0
            page.locator("#ev-theme").select_option("__all__")
            page.locator("#ev-file").select_option("__all__")
            q_opts = page.locator("#ev-question option").all_inner_texts()
            assert len(q_opts) >= 2 and q_opts[0] == "All questions", f"Expected Question filter options, got {q_opts}"
            first_q = q_opts[1]
            page.locator("#ev-question").select_option(first_q)
            q_provs = page.locator(".ed-evidence-row .ed-provenance").all_inner_texts()
            assert q_provs and all(first_q in p for p in q_provs), f"Question filter leaked rows: {q_provs}"
            print(f"[ok] Coded Evidence Question filter works ({first_q}: {len(q_provs)} rows verified)")

            # Test Spot-Check shows exact highlighted flagged sentences in context + filters!
            page.locator('[data-subtab="spotcheck"]').click()
            sc_examples = page.locator('[data-spotcheck-example="1"]')
            assert sc_examples.count() == 3, f"Expected 3 exact flagged sentences in Spot-Check, got {sc_examples.count()}"
            assert sc_examples.first.locator("mark").count() >= 1
            page.locator("#sc-filter-prio").select_option("Check in Context (Negation or Short Word)")
            assert sc_examples.count() > 0
            page.locator("#sc-filter-prio").select_option("__all__")
            print("[ok] Spot-Check renders exact highlighted flagged sentences in context with priority/theme filters")

            # Test Discover Unlisted Themes + Add Theme to Active Themes
            page.locator('[data-subtab="discover"]').click()
            page.locator("#btn-add-topic").wait_for(timeout=5000)
            before_n = page.evaluate("() => window.__ATLAS_API__.state.results.frequencies.length")
            page.locator("#btn-add-topic").click()
            after_n = page.evaluate("() => window.__ATLAS_API__.state.results.frequencies.length")
            assert after_n == before_n + 1, f"Expected theme count +1, got {before_n} -> {after_n}"
            page.locator("#btn-reset-edits").click()
            reset_n = page.evaluate("() => window.__ATLAS_API__.state.results.frequencies.length")
            assert reset_n == before_n
            print("[ok] Discover Unlisted Themes offline NMF + 1-click Add Theme + Reset works")

            # Download real .docx, .xlsx, .csv (Direct Quotes only), and .svg chart and validate with Python!
            page.locator('[data-subtab="summary"]').click()
            assert page.locator("#btn-dl-csv").inner_text().strip() == "Download Direct Quotes (.csv)"
            with page.expect_download() as dl_csv_notes:
                page.locator("#btn-dl-csv").click()
            csv_notes_out = tmp / "direct_quotes.csv"
            dl_csv_notes.value.save_as(str(csv_notes_out))
            with open(csv_notes_out, encoding="utf-8-sig", newline="") as fh:
                dq_rows = list(csv.DictReader(fh))
            assert len(dq_rows) == 6 and all(r["evidence_type"] == "notable_quote_verbatim" for r in dq_rows), dq_rows
            print("[ok] Notes Tab 1 'Download Direct Quotes (.csv)' exports strictly notable_quote_verbatim rows (6/6)")

            with page.expect_download() as dl_svg:
                page.locator("#btn-dl-svg").click()
            svg_out = tmp / "atlas_theme_chart.svg"
            dl_svg.value.save_as(str(svg_out))
            svg_root = ET.fromstring(svg_out.read_text(encoding="utf-8"))
            assert svg_root.tag.endswith("svg")
            assert any(el.tag.endswith("title") and (el.text or "").strip() for el in svg_root)
            assert any(el.tag.endswith("desc") and (el.text or "").strip() for el in svg_root)
            print("[ok] 1-click 'Download Chart (.svg)' exports valid WCAG-accessible SVG with <title> and <desc>")

            with page.expect_download() as dl_docx:
                page.locator("#btn-dl-docx").click()
            docx_out = tmp / "br_report.docx"
            dl_docx.value.save_as(str(docx_out))
            d_obj = docx.Document(str(docx_out))
            d_txt = "\n".join(p.text for p in d_obj.paragraphs) + "\n" + "\n".join(c.text for t in d_obj.tables for r in t.rows for c in r.cells)
            assert "SOFTWARE_TEST FIXTURE" in d_txt and "1. Summary at a Glance" in d_txt and "Technical and Audit Appendix" in d_txt and "Appendix D. Skipped Questions and Session Headers" in d_txt
            assert len(d_obj.inline_shapes) >= 1, "Expected embedded bar chart PNG in Browser Word report!"
            assert abs(d_obj.sections[0].left_margin.inches - 0.9) < 0.02
            assert "header_or_summary_table" not in d_txt, "Raw internal parser code leaked into report!"
            # Verify short group headers (Control, Treatment) & descending sort in Theme Counts Breakdown
            grid_tbl = next(t for t in d_obj.tables if [c.text.strip() for c in t.rows[0].cells][0] == "Theme" and "Groups" in [c.text.strip() for c in t.rows[0].cells])
            grid_hdrs = [c.text.strip() for c in grid_tbl.rows[0].cells]
            assert "Control" in grid_hdrs and "Treatment" in grid_hdrs, f"Expected short group headers, got {grid_hdrs}"
            sum_tbl = next(t for t in d_obj.tables if [c.text.strip() for c in t.rows[0].cells][:3] == ["Theme", "Focus Groups", "Theme Matches"])
            sum_counts = [int(r.cells[2].text.strip()) for r in sum_tbl.rows[1:]]
            assert sum_counts == sorted(sum_counts, reverse=True), f"Theme Counts Breakdown not sorted descending: {sum_counts}"
            print("[ok] Browser-generated two-layer Word Summary Report (.docx) verified: embedded PNG chart, 0.9in margins, short labels, descending sort, Technical Appendix")

            with page.expect_download() as dl_xlsx:
                page.locator("#btn-dl-xlsx").click()
            xlsx_out = tmp / "br_freq.xlsx"
            dl_xlsx.value.save_as(str(xlsx_out))
            wb_obj = openpyxl.load_workbook(str(xlsx_out))
            assert wb_obj.sheetnames == ["Empirical Frequencies", "Coded Evidence", "Methodology & Audit"], wb_obj.sheetnames
            print("[ok] Browser-generated Excel workbook (.xlsx) opens cleanly in openpyxl with all 3 sheets")

            # -----------------------------------------------------------------
            # Test 2: Vertically Merged Continuation-Cell Structural-Row Guards
            # -----------------------------------------------------------------
            page.locator("#file-input").set_input_files(str(merged_docx))
            page.locator("#chk-obs").check()
            page.locator("#btn-run").click()
            py_parser = UniversalTranscriptParser(include_evidence_types=("key_point_paraphrase", "notable_quote_verbatim", "observation"))
            py_turns = py_parser.parse_file(str(merged_docx))
            br_turns = page.evaluate("() => window.__ATLAS_API__.state.results.tagged_turns")
            assert [t["text"] for t in br_turns] == [t["text"] for t in py_turns], (
                f"Merged-cell guard mismatch!\nBR: {[t['text'] for t in br_turns]}\nPY: {[t['text'] for t in py_turns]}"
            )
            print("[ok] 100% Python-vs-Browser parity on vertically merged continuation-cell structural guards")

            # -----------------------------------------------------------------
            # Test 3: Multi-Sheet Excel Survey + Blank Rows + Repeated IDs + Spelling Tolerance + Spot-Check Exclude
            # -----------------------------------------------------------------
            page.locator("#file-input").set_input_files(str(survey_xlsx))
            page.locator("#sel-sheet").select_option("Open_Ended")
            page.locator("#sel-id-col").select_option("Respondent_ID")
            page.locator("#chk-spelling").check()
            page.locator("#btn-run").click()
            body_text = page.locator("body").inner_text()
            assert "3 written answers scanned (2 rows left this question blank)" in body_text, "Missing exact blank-row summary!"
            assert "response rate" not in body_text.lower() or "rather than a study response rate" in body_text.lower()

            # Compare Python AtlasEngine on exact same multi-sheet Excel (per_row + spelling_tolerance=True)
            py_eng = AtlasEngine(str(ATLAS_REPO / "config" / "gbi_focus_group_starter.yaml"))
            py_ex = py_eng.process_corpus(
                [str(survey_xlsx)],
                tabular_options={"text_col": "Open_Feedback", "id_col": "Respondent_ID", "sheet_name": "Open_Ended", "duplicate_id_policy": "per_row"},
                group_by_source=False,
                spelling_tolerance=True,
            )
            br_ex = page.evaluate("""() => {
                const api = window.__ATLAS_API__;
                api.state.selectedCore = new Set(ATLAS_CORE_THEMES.map(r => r.id));
                api.state.selectedAddon = new Set();
                api.executeAnalysis(false);
                return api.state.results;
            }""")
            assert br_ex["total_documents"] == py_ex["total_documents"] == 3
            assert len(br_ex["quotes"]) == len(py_ex["quotes_df"]) == 3, (len(br_ex["quotes"]), len(py_ex["quotes_df"]))
            assert sorted(t["matched_span"].lower() for t in br_ex["typo_matches"]) == ["chldcare", "educacoin", "gorceries"]
            assert sorted(py_ex["typo_matches_df"]["matched_span"].str.lower().tolist()) == ["chldcare", "educacoin", "gorceries"]
            assert br_ex["quotes"][0].get("respondent_id") == "R01"
            assert page.locator("#btn-dl-csv").inner_text().strip() == "Download Verbatim Entries (.csv)"
            with page.expect_download() as dl_csv_ex:
                page.locator("#btn-dl-csv").click()
            csv_ex_out = tmp / "verbatim_entries.csv"
            dl_csv_ex.value.save_as(str(csv_ex_out))
            with open(csv_ex_out, encoding="utf-8-sig", newline="") as fh:
                ex_rows = list(csv.DictReader(fh))
            assert len(ex_rows) == 3 and all(r["evidence_type"] == "verbatim_turn" for r in ex_rows), ex_rows
            print("[ok] 100% Python-vs-Browser parity on multi-sheet Excel + DL=1 spelling tolerance + 'Download Verbatim Entries (.csv)' exact label/row parity")

            # Verify exported .xlsx preserves Respondent ID under per_row
            with page.expect_download() as dl_ex_xlsx:
                page.locator("#btn-dl-xlsx").click()
            ex_xlsx_out = tmp / "ex_per_row.xlsx"
            dl_ex_xlsx.value.save_as(str(ex_xlsx_out))
            wb_ex = openpyxl.load_workbook(str(ex_xlsx_out))
            ev_sheet = wb_ex["Verbatim Quotes"]
            hdrs = [ev_sheet.cell(1, c).value for c in range(1, ev_sheet.max_column + 1)]
            assert "Respondent ID" in hdrs, hdrs
            print("[ok] Browser-exported .xlsx preserves Respondent ID column under per_row")

            # Spot-Check 1-click exclude on spelling match ('gorceries') removes it cleanly
            page.locator('[data-subtab="spotcheck"]').click()
            page.locator("#sc-domain").select_option("food_groceries_basic_needs")
            page.locator('[data-excl-word="gorceries"]').check()
            page.locator("#btn-apply-spotcheck").click()
            after_excl = page.evaluate("() => window.__ATLAS_API__.state.results.quotes.length")
            assert after_excl == 2, f"Expected 2 matches after excluding gorceries, got {after_excl}"
            print("[ok] Spot-Check 1-click exclusion removes flagged spelling match and recodes instantly")

            # Switch to combine repeated IDs -> N drops from 3 to 2 unique respondents
            page.locator('input[name="dup-policy"][value="combine"]').check()
            page.locator("#btn-run").click()
            comb_n = page.evaluate("() => window.__ATLAS_API__.state.results.total_documents")
            assert comb_n == 2, f"Expected 2 unique respondents under combine, got {comb_n}"
            print("[ok] Repeated Respondent IDs combine mode reduces N from 3 rows to 2 unique respondents")

            # -----------------------------------------------------------------
            # Test 4: Clear -> Run Guardrail & Adversarial XSS Escaping
            # -----------------------------------------------------------------
            page.evaluate("""() => {
                const api = window.__ATLAS_API__;
                api.state.selectedCore = new Set();
                api.state.selectedAddon = new Set();
                api.executeAnalysis(false);
            }""")
            assert "Select at least one theme" in page.locator('[role="alert"]').inner_text()
            print("[ok] Clear -> Run guardrail blocks 0-theme run cleanly")

            page.locator("summary", has_text="Upload Custom Themes").click()
            page.locator("#yaml-input").set_input_files(str(adv_yaml))
            page.locator("#drawer-custom summary", has_text="adv.yaml").wait_for(timeout=5000)
            page.locator("#btn-run").click()
            page.locator('[data-kpi="matches"]').wait_for(timeout=10000)
            xss_fired = page.evaluate("() => Boolean(window.__xss)")
            assert not xss_fired, "XSS FIRED on adversarial theme name!"
            loaded_adv_names = page.evaluate("() => window.__ATLAS_API__.state.results.frequencies.map(f => f.domain_name)")
            assert loaded_adv_names == ["Costs <b>bold</b> <img src=x onerror=window.__xss=1>"], loaded_adv_names
            print("[ok] PyYAML custom theme file parsed cleanly & adversarial HTML/XSS theme name safely escaped (0 script execution)")

            # -----------------------------------------------------------------
            # Test 5: Large-Corpus Pagination (> 200 Coded Evidence & > 150 Spot-Check Flags)
            # -----------------------------------------------------------------
            large_csv = tmp / "large_corpus_220.csv"
            with open(large_csv, "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["Respondent_ID", "Response"])
                for idx in range(1, 221):
                    w.writerow([f"R{idx:03d}", f"Entry {idx:03d}: We stopped by the carpet shop today."])

            page.locator("summary", has_text="Upload Custom Themes").click()
            page.locator("#btn-clear-yaml").click()
            page.locator("summary", has_text="Core Evaluation Themes").click()
            page.locator("#btn-core-all").click()
            page.locator("#file-input").set_input_files(str(large_csv))
            page.locator("#sel-text-col").select_option("Response")
            page.locator("#sel-id-col").select_option("Respondent_ID")
            page.locator("#chk-spelling").uncheck()
            page.locator("#btn-run").click()
            page.locator('[data-kpi="matches"]').wait_for(timeout=10000)

            # 5a. Coded Evidence pagination (> 200 rows)
            page.locator('[data-subtab="evidence"]').click()
            assert page.locator(".ed-evidence-row").count() == 50, "Expected 50 rows on Evidence page 1"
            assert "Showing 1–50 of 220 coded matches (Page 1 of 5)" in page.locator('[data-pager="ev-top"]').inner_text()
            assert page.locator("#ev-prev").is_disabled()
            assert "Entry 001:" in page.locator(".ed-evidence-row").first.inner_text()

            for _ in range(4):
                page.locator("#ev-next").click()
            assert page.locator(".ed-evidence-row").count() == 20, "Expected 20 rows on Evidence page 5"
            assert "Showing 201–220 of 220 coded matches (Page 5 of 5)" in page.locator('[data-pager="ev-top"]').inner_text()
            assert page.locator("#ev-next").is_disabled()
            assert "Entry 220:" in page.locator(".ed-evidence-row").last.inner_text()

            page.locator("#ev-prev").click()
            assert "Showing 151–200 of 220 coded matches (Page 4 of 5)" in page.locator('[data-pager="ev-top"]').inner_text()

            # Filtering reaches row 220 immediately and hides pager when <= 50 matches
            page.locator("#ev-search").fill("Entry 220")
            assert page.locator(".ed-evidence-row").count() == 1
            assert "Entry 220:" in page.locator(".ed-evidence-row").first.inner_text()
            assert page.locator('[data-pager="ev-top"]').count() == 0

            # Clear filter and test Show all (220) + Back to pages
            page.locator("#ev-search").fill("")
            page.locator("#ev-show-all").click()
            assert page.locator(".ed-evidence-row").count() == 220, "Expected all 220 rows when Show all is active"
            assert "Showing all 220 coded matches" in page.locator('[data-pager="ev-top"]').inner_text()
            assert "Entry 220:" in page.locator(".ed-evidence-row").last.inner_text()
            page.locator("#ev-show-all").click()
            assert page.locator(".ed-evidence-row").count() == 50
            print("[ok] Large-corpus Coded Evidence pagination (220 > 200): Next/Prev to row 220, search, and Show all verified")

            # 5b. Spot-Check Flagged Sentences pagination (> 150 rows)
            page.locator('[data-subtab="spotcheck"]').click()
            sc_rows = page.locator('[data-spotcheck-example="1"]')
            assert sc_rows.count() == 50, f"Expected 50 Spot-Check rows on page 1, got {sc_rows.count()}"
            assert "Showing 1–50 of 220 flagged sentences (Page 1 of 5)" in page.locator('[data-pager="sc-top"]').inner_text()
            assert page.locator("#sc-prev").is_disabled()

            for _ in range(4):
                page.locator("#sc-next").click()
            assert sc_rows.count() == 20, f"Expected 20 Spot-Check rows on page 5, got {sc_rows.count()}"
            assert "Showing 201–220 of 220 flagged sentences (Page 5 of 5)" in page.locator('[data-pager="sc-top"]').inner_text()
            assert page.locator("#sc-next").is_disabled()
            assert "Entry 220:" in sc_rows.last.inner_text()
            assert sc_rows.last.locator("mark").inner_text().lower() == "car"

            page.locator("#sc-show-all").click()
            assert sc_rows.count() == 220, f"Expected all 220 Spot-Check rows on Show all, got {sc_rows.count()}"
            assert "Showing all 220 flagged sentences" in page.locator('[data-pager="sc-top"]').inner_text()
            assert "Entry 220:" in sc_rows.last.inner_text()
            page.locator("#sc-show-all").click()
            assert sc_rows.count() == 50
            print("[ok] Large-corpus Spot-Check pagination (220 > 150): Next/Prev to row 220 with <mark>, and Show all verified")

            # 5c. Printable Word summary discloses preview caps while Excel keeps all 220 rows
            page.locator('[data-subtab="summary"]').click()
            with page.expect_download() as dl_lg_docx:
                page.locator("#btn-dl-docx").click()
            lg_docx = tmp / "large_summary.docx"
            dl_lg_docx.value.save_as(str(lg_docx))
            lg_doc = docx.Document(str(lg_docx))
            lg_txt = "\n".join(p.text for p in lg_doc.paragraphs)
            assert "Showing the first 25 of 220 matches" in lg_txt
            assert "Showing the first 50 of 220 flagged matches" in lg_txt

            with page.expect_download() as dl_lg_xlsx:
                page.locator("#btn-dl-xlsx").click()
            lg_xlsx = tmp / "large_freq.xlsx"
            dl_lg_xlsx.value.save_as(str(lg_xlsx))
            lg_wb = openpyxl.load_workbook(str(lg_xlsx))
            assert lg_wb["Verbatim Quotes"].max_row == 221, f"Expected 1 header + 220 rows in Excel, got {lg_wb['Verbatim Quotes'].max_row}"
            print("[ok] Large-corpus exports verified: printable Word discloses preview cap; Excel exports all 220 rows")

            # -----------------------------------------------------------------
            # Test 6: Codex Round-1 Regression Guards (Run preserves edits,
            #         collision-free labels after normalization, chart >= 11pt)
            # -----------------------------------------------------------------
            # 6a. Verify embedded chart PNG in Word report is 1360px wide with un-squashed aspect ratio (32px = 11.01pt >= 10.5pt)
            import io
            import re as _re
            import zipfile
            from PIL import Image
            with zipfile.ZipFile(lg_docx) as zf:
                chart_bytes = zf.read("word/media/chart1.png")
                doc_xml_txt = zf.read("word/document.xml").decode("utf-8")
            with Image.open(io.BytesIO(chart_bytes)) as cim:
                cw, ch = cim.size
            assert cw == 1360 and ch >= 180, f"Unexpected report chart dimensions: {cw}x{ch}"
            ext_m = _re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"/>', doc_xml_txt)
            assert ext_m, "Missing wp:extent for report chart"
            cx_emu, cy_emu = int(ext_m.group(1)), int(ext_m.group(2))
            disp_w_in = cx_emu / 914400.0
            disp_h_in = cy_emu / 914400.0
            assert abs(disp_w_in - 6.5) < 0.01, f"Expected 6.5in chart width, got {disp_w_in:.3f}in"
            assert abs((disp_h_in / disp_w_in) - (ch / cw)) < 0.02, f"Chart aspect ratio squashed: {disp_h_in/disp_w_in:.4f} vs {ch/cw:.4f}"
            eff_pt = 32.0 * 72.0 / (cw / disp_w_in)
            assert eff_pt >= 10.5, f"Effective chart label font {eff_pt:.2f}pt < 10.5pt floor"
            print(f"[ok] Embedded report chart PNG verified ({cw}x{ch}px -> {disp_w_in:.2f}x{disp_h_in:.2f} in, 32px text = {eff_pt:.2f}pt >= 10.5pt)")

            # 6b. friendlyGroupLabels, 3-way duplicate theme disambiguation, and long chart label suffix preservation
            lbl_map = page.evaluate('() => friendlyGroupLabels(["room_one.docx", "room__one.docx"])')
            assert len(set(lbl_map.values())) == 2, f"friendlyGroupLabels collided: {lbl_map}"
            dup_map = page.evaluate('() => Object.fromEntries(disambiguateThemeLabels([["a","Costs"],["b","Costs"],["c","Costs (a)"]]))')
            assert len(set(dup_map.values())) == 3, f"3-way theme collision: {dup_map}"
            short_lbls = page.evaluate('() => shortenChartLabels([{domain_id:"a",label:"Housing affordability and stability (a)"},{domain_id:"b",label:"Housing affordability and stability (b)"}], 34)')
            assert len(set(short_lbls)) == 2 and short_lbls[0].endswith("(a)") and short_lbls[1].endswith("(b)"), f"Long chart labels collided: {short_lbls}"
            print(f"[ok] Labels collision-free: groups={lbl_map}, 3-way={dup_map}, chart={short_lbls}")

            # 6c. Spot-Check exclusion MUST survive ordinary Run Analysis click & reset on explicit Reset
            page.locator('[data-subtab="spotcheck"]').click()
            page.locator('input[data-excl-word="carpet"]').check()
            page.locator("#btn-apply-spotcheck").click()
            assert page.locator('[data-kpi="matches"]').inner_text().strip() == "0"
            page.locator("#btn-run").click()
            assert page.locator('[data-kpi="matches"]').inner_text().strip() == "0", "Run Analysis wiped Spot-Check exclusion!"
            page.locator("#btn-reset-edits").click()
            assert page.locator('[data-kpi="matches"]').inner_text().strip() == "220", "Reset did not restore base themes!"
            print("[ok] Ordinary Run Analysis preserves Spot-Check exclusions; Reset in-app edits restores cleanly")

            browser.close()

    assert not external_reqs, f"Unexpected external network requests: {external_reqs}"
    assert not console_errors, f"Console errors: {console_errors}"
    assert not page_errors, f"Uncaught page errors: {page_errors}"
    print("\nALL STANDALONE PARITY & CHROMIUM CHECKS PASSED (0 external requests, 0 console/page errors)")


if __name__ == "__main__":
    run_parity_suite()
