"""v1.2 Slice 5 tests: Formatted in-app Reference Guides tab, dynamic Word (.docx)
guide downloads, and v1.2 accuracy alignment across all four guides in docs/.

All inputs here are SOFTWARE_TEST fixtures or repository documentation files.
"""

import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

APP_PATH = REPO_ROOT / "app.py"
DOCS_DIR = REPO_ROOT / "docs"
GUIDE_FILES = (
    "ATLAS_GBI_Analyst_Quick_Start.md",
    "ATLAS_User_Guide.md",
    "ATLAS_Methodology_and_Reference_Manual.md",
    "ATLAS_Practitioner_Field_Guide_Program_Evaluation.md",
)
EXPECTED_DOCX_IMAGES = {
    "ATLAS_GBI_Analyst_Quick_Start.md": 0,
    "ATLAS_User_Guide.md": 4,
    "ATLAS_Methodology_and_Reference_Manual.md": 5,
    "ATLAS_Practitioner_Field_Guide_Program_Evaluation.md": 1,
}


def _load_app_guide_helpers():
    import ast
    import hashlib
    import html
    import inspect
    import re
    import unicodedata

    source = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted_funcs = {
        "markdown_to_docx_bytes",
        "split_markdown_for_app",
        "_add_inline_markdown_runs",
        "_set_picture_alt_text",
        "_png_pixel_size",
        "_neutralize_relative_md_links",
        "format_codebook_summary",
    }
    wanted_assigns = {"REFERENCE_GUIDES", "DOCX_MIME"}
    ns = {
        "Path": Path,
        "io": io,
        "re": re,
        "html": html,
        "hashlib": hashlib,
        "inspect": inspect,
        "unicodedata": unicodedata,
        "docx": docx,
        "NAVY": "#1E3A8A",
        "TEAL": "#0F766E",
        "SLATE": "#334155",
    }
    # Pull helper imports from python-docx used by markdown_to_docx_bytes
    from docx.enum.section import WD_ORIENT, WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement, parse_xml
    from docx.oxml.ns import nsdecls, qn
    from docx.shared import Inches, Pt, RGBColor

    ns.update({
        "WD_ORIENT": WD_ORIENT,
        "WD_SECTION": WD_SECTION,
        "WD_ALIGN_PARAGRAPH": WD_ALIGN_PARAGRAPH,
        "Inches": Inches,
        "Pt": Pt,
        "RGBColor": RGBColor,
        "OxmlElement": OxmlElement,
        "parse_xml": parse_xml,
        "nsdecls": nsdecls,
        "qn": qn,
    })

    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            node.decorator_list = []
            nodes.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in wanted_assigns for t in targets):
                nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec"), ns)
    return ns


class GuideDocxConversionTests(unittest.TestCase):
    def test_all_four_guides_convert_to_formatted_word_docx_with_tables_and_figures(self):
        helpers = _load_app_guide_helpers()
        self.assertIn("markdown_to_docx_bytes", helpers)
        convert = helpers["markdown_to_docx_bytes"]

        for filename in GUIDE_FILES:
            with self.subTest(guide=filename):
                md_path = DOCS_DIR / filename
                md_text = md_path.read_text(encoding="utf-8")
                payload = convert(md_text, str(DOCS_DIR))
                self.assertTrue(payload.startswith(b"PK\x03\x04"), "output must be a valid OOXML .docx zip")

                doc = docx.Document(io.BytesIO(payload))
                all_para_text = "\n".join(p.text for p in doc.paragraphs)
                self.assertGreater(len(all_para_text.strip()), 500)
                # Headings should be converted, leaving no raw Markdown heading prefixes.
                self.assertFalse(
                    any(p.text.lstrip().startswith("##") for p in doc.paragraphs),
                    f"{filename}: raw ## heading leaked into Word paragraphs",
                )
                # Bold syntax should be converted into Word bold runs, leaving no literal ** markers.
                self.assertNotIn("**", all_para_text, f"{filename}: raw ** bold marker leaked into .docx")
                # Embedded pictures match expected figure counts and stay >= 10.5 pt effective label size
                # inside landscape figure pages (never overflowing 10.0" x 6.85").
                self.assertEqual(
                    len(doc.inline_shapes),
                    EXPECTED_DOCX_IMAGES[filename],
                    f"{filename}: expected {EXPECTED_DOCX_IMAGES[filename]} embedded figures in .docx",
                )
                fig_targets = re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", md_text)
                self.assertEqual(len(fig_targets), len(doc.inline_shapes))
                png_size = helpers["_png_pixel_size"]
                for shape, rel_fig in zip(doc.inline_shapes, fig_targets):
                    px_w, px_h = png_size(DOCS_DIR / rel_fig)
                    disp_w_in = shape.width / 914400.0
                    disp_h_in = shape.height / 914400.0
                    self.assertLessEqual(disp_w_in, 10.01, f"{filename} {rel_fig}: width {disp_w_in:.2f}in")
                    self.assertLessEqual(disp_h_in, 6.86, f"{filename} {rel_fig}: height {disp_h_in:.2f}in")
                    # Committed figures render 22 CSS-px labels at 2x DPR (logical width = px_w / 2).
                    eff_pt = 22.0 / (px_w / 2.0) * (disp_w_in * 72.0)
                    self.assertGreaterEqual(
                        eff_pt,
                        10.5,
                        f"{filename} {rel_fig}: effective label font {eff_pt:.2f}pt < 10.5pt floor",
                    )
                if doc.inline_shapes:
                    from docx.enum.section import WD_ORIENT
                    from docx.oxml.ns import qn

                    self.assertTrue(
                        any(s.orientation == WD_ORIENT.LANDSCAPE for s in doc.sections),
                        f"{filename}: figures must be placed on landscape pages",
                    )
                    # Every OOXML section must contain real content (no empty portrait pages
                    # between consecutive figures or trailing blank sections).
                    sections_content = []
                    cur = []
                    for child in doc.element.body:
                        tag = child.tag.split("}")[-1]
                        if tag == "sectPr":
                            sections_content.append(cur)
                            cur = []
                            continue
                        has_drawing = any(e.tag.endswith("}drawing") for e in child.iter())
                        text = "".join(child.itertext()).strip()
                        if tag == "tbl" or has_drawing or text:
                            cur.append((tag, has_drawing, text))
                        p_pr = child.find(qn("w:pPr"))
                        if p_pr is not None and p_pr.find(qn("w:sectPr")) is not None:
                            sections_content.append(cur)
                            cur = []
                    self.assertEqual(len(sections_content), len(doc.sections), filename)
                    for idx, items in enumerate(sections_content):
                        self.assertTrue(items, f"{filename}: section {idx} is empty (blank page regression)")
                # Guides with Markdown tables must produce native Word tables.
                if "| :--- |" in md_text:
                    self.assertGreater(len(doc.tables), 0, f"{filename}: Markdown tables not converted to Word tables")

    def test_markdown_helpers_block_path_traversal_images_and_neutralize_relative_md_links(self):
        helpers = _load_app_guide_helpers()
        self.assertIn("split_markdown_for_app", helpers)
        split_fn = helpers["split_markdown_for_app"]
        convert = helpers["markdown_to_docx_bytes"]

        valid_png_bytes = (DOCS_DIR / "figures" / "atlas_audit_bridge.png").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            outside_png = tmp_root / "outside_secret.png"
            outside_png.write_bytes(valid_png_bytes)
            docs_box = tmp_root / "docs_box"
            (docs_box / "figures").mkdir(parents=True)
            inside_png = docs_box / "figures" / "inside.png"
            inside_png.write_bytes(valid_png_bytes)
            symlink_png = docs_box / "figures" / "escape_link.png"
            symlink_created = False
            try:
                os.symlink(outside_png, symlink_png)
                symlink_created = True
            except OSError:
                pass

            sample = (
                "# Title\n\n"
                "See [Manual](ATLAS_Methodology_and_Reference_Manual.md#3) and "
                "[GitHub](https://github.com/dphdame/atlas).\n\n"
                "![escape md](../../README.md)\n\n"
                "![escape outside png](../outside_secret.png)\n\n"
                + ("![escape symlink png](figures/escape_link.png)\n\n" if symlink_created else "")
                + "![valid figure](figures/inside.png)\n"
            )
            blocks = split_fn(sample, str(docs_box))
            img_blocks = [b for b in blocks if b[0] == "image"]
            self.assertEqual(len(img_blocks), 1, "only in-directory valid PNG figures should become image blocks")
            self.assertTrue(str(img_blocks[0][1]).endswith("inside.png"))

            md_joined = "\n".join(b[1] for b in blocks if b[0] == "markdown")
            self.assertNotIn("ATLAS_Methodology_and_Reference_Manual.md", md_joined)
            self.assertIn("https://github.com/dphdame/atlas", md_joined)

            payload = convert(sample, str(docs_box))
            doc = docx.Document(io.BytesIO(payload))
            self.assertEqual(len(doc.inline_shapes), 1)


class GuideTabsAndDownloadsUITests(unittest.TestCase):
    def test_app_renders_tab3_formatted_guides_and_docx_downloads_before_and_after_run(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=25)
        at.run()
        self.assertFalse(list(at.exception), [e.value for e in at.exception])
        # Boot opens cleanly on Upload with 0 metrics until Run Analysis is clicked,
        # while Tab 3 Reference Guides and .docx sidebar downloads are immediately available.
        self.assertEqual(len(at.metric), 0)
        self.assertTrue(any("Reference Guides" in t.label for t in at.tabs), [t.label for t in at.tabs])

        # Sidebar download buttons should offer Word (.docx) guides rather than raw Markdown.
        dl_labels = [d.label for d in at.get("download_button")]
        for title in ("GBI Analyst Quick-Start Guide", "User Guide", "Methodology & Reference Manual", "Practitioner Field Guide"):
            matches = [lbl for lbl in dl_labels if title in lbl]
            self.assertTrue(matches, f"Missing download button for {title!r}; got {dl_labels}")
            self.assertTrue(any(".docx" in lbl for lbl in matches), f"Expected .docx download for {title!r}: {matches}")
            self.assertFalse(any("(Markdown)" in lbl for lbl in matches), f"Stale Markdown label: {matches}")

        # Switching guides inside Tab 3 works on boot before clicking Run.
        guide_select = next((s for s in at.selectbox if s.label == "Choose a guide to read"), None)
        self.assertIsNotNone(guide_select, [s.label for s in at.selectbox])
        self.assertEqual(len(guide_select.options), 4)
        for opt in guide_select.options:
            guide_select.set_value(opt)
            at.run()
            self.assertFalse(list(at.exception), f"Exception rendering guide {opt!r}: {[e.value for e in at.exception]}")

        # After selecting a sample and clicking Run Analysis, KPIs render and stay intact across guide switches.
        corpus_box = next(s for s in at.selectbox if s.label == "Corpus Dataset")
        corpus_box.set_value(next(o for o in corpus_box.options if "Focus-Group Notes" in str(o)))
        at.run()
        next(b for b in at.button if b.label == "▶ Run Analysis").click()
        at.run()
        self.assertFalse(list(at.exception), [e.value for e in at.exception])
        self.assertEqual(len(at.metric), 4)
        guide_select = next(s for s in at.selectbox if s.label == "Choose a guide to read")
        guide_select.set_value(guide_select.options[1])
        at.run()
        self.assertFalse(list(at.exception))
        self.assertEqual(len(at.metric), 4)


class OwnerUXSimplificationTests(unittest.TestCase):
    def _widget(self, at, accessor, label):
        for w in getattr(at, accessor):
            if w.label == label:
                return w
        self.fail(f"Widget {accessor} {label!r} not found")

    def test_manual_run_button_isolates_pending_sidebar_edits_and_validates_empty_upload(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=25)
        at.run()
        self.assertEqual(len(at.metric), 0)
        self.assertTrue(any("Ready to analyze" in str(i.value) for i in at.info))

        # Clicking Run with no uploaded files shows a clean error and keeps Tab 3 available.
        self._widget(at, "button", "▶ Run Analysis").click()
        at.run()
        self.assertFalse(list(at.exception))
        self.assertEqual(len(at.error), 1)
        self.assertEqual(len(at.metric), 0)
        self.assertTrue(any("Reference Guides" in t.label for t in at.tabs))

        # Selecting Focus-Group Notes and clicking Run commits 8 starter domains.
        corpus_box = self._widget(at, "selectbox", "Corpus Dataset")
        corpus_box.set_value(next(o for o in corpus_box.options if "Focus-Group Notes" in str(o)))
        at.run()
        self._widget(at, "button", "▶ Run Analysis").click()
        at.run()
        self.assertFalse(list(at.exception))
        self.assertEqual(len(at.error), 0)
        self.assertEqual(int(next(m.value for m in at.metric if m.label == "Active Domains")), 8)
        self.assertEqual(len(at.warning), 0)

        # Stacking an extra codebook in the sidebar without clicking Run preserves old results and shows pending warning.
        self._widget(at, "multiselect", "Stack Additional Starter Codebooks (optional)").set_value(["sdoh_basic_needs.yaml"])
        at.run()
        self.assertEqual(int(next(m.value for m in at.metric if m.label == "Active Domains")), 8)
        self.assertTrue(any("▶ Run Analysis" in str(w.value) for w in at.warning))

        # Clicking Run refreshes to 12 domains and clears the warning.
        self._widget(at, "button", "▶ Run Analysis").click()
        at.run()
        self.assertEqual(int(next(m.value for m in at.metric if m.label == "Active Domains")), 12)
        self.assertEqual(len(at.warning), 0)

    def test_zero_software_test_jargon_in_ui_across_samples(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=25)
        at.run()
        corpus_box = self._widget(at, "selectbox", "Corpus Dataset")
        for opt in corpus_box.options:
            self.assertNotIn("SOFTWARE_TEST", str(opt))
        for sample_needle in ("Focus-Group Notes", "Bilingual"):
            corpus_box = self._widget(at, "selectbox", "Corpus Dataset")
            corpus_box.set_value(next(o for o in corpus_box.options if sample_needle in str(o)))
            at.run()
            self._widget(at, "button", "▶ Run Analysis").click()
            at.run()
            alerts = [str(x.value) for x in (*at.info, *at.warning, *at.error, *at.success)]
            for msg in alerts:
                self.assertNotIn("SOFTWARE_TEST", msg)

    def test_transcript_filters_hidden_on_3col_notes_and_available_for_freeform_upload(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=25)
        at.run()
        # Before uploading structured notes, collapsed advanced filters expander is present on Upload view.
        self.assertTrue(any("Advanced transcript filters" in e.label for e in at.expander))

        # Uploading a 3-column focus-group notes .docx hides Facilitator/Regex filters completely.
        sample_notes = (REPO_ROOT / "data" / "samples" / "software_test_gbi_group_treatment.docx").read_bytes()
        uploader = next(u for u in at.file_uploader if "docx" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        uploader.set_value(("notes_group_a.docx", sample_notes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        at.run()
        self.assertFalse(any("Advanced transcript filters" in e.label for e in at.expander))
        self.assertFalse(any("Facilitator names" in t.label for t in at.text_input))
        self.assertFalse(any("Interviewer prompt patterns" in t.label for t in at.text_area))

        # Uploading a mixed corpus (3-column notes .docx + free-form .txt) MUST keep the collapsed
        # transcript filters available so facilitator lines in the free-form file can still be excluded.
        mixed_txt = b"Moderator: How did the bus affect your rent?\nP9: Groceries went up this month.\n"
        uploader = next(u for u in at.file_uploader if "docx" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        uploader.set_value([
            ("notes_group_a.docx", sample_notes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("freeform_group_b.txt", mixed_txt, "text/plain"),
        ])
        at.run()
        self.assertTrue(any("Advanced transcript filters" in e.label for e in at.expander))
        self._widget(at, "text_input", "Facilitator names (optional, comma-separated)").set_value("Moderator")
        at.run()
        self._widget(at, "button", "▶ Run Analysis").click()
        at.run()
        self.assertFalse(list(at.exception))
        # Moderator's prompt must NOT appear in any coded quote / evidence table.
        for df_el in at.dataframe:
            if hasattr(df_el.value, "columns") and "text" in df_el.value.columns:
                self.assertFalse(
                    df_el.value["text"].astype(str).str.contains("How did the bus affect your rent", regex=False).any(),
                    "Moderator turn leaked into coded evidence on mixed upload",
                )

        # Uploading a plain .txt transcript exposes the collapsed filters and honors facilitator exclusion on Run.
        txt_payload = b"Moderator: How is rent?\nP1: Rent went up this month.\n"
        uploader = next(u for u in at.file_uploader if "txt" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])})
        uploader.set_value(("interview.txt", txt_payload, "text/plain"))
        at.run()
        self.assertTrue(any("Advanced transcript filters" in e.label for e in at.expander))
        self._widget(at, "text_input", "Facilitator names (optional, comma-separated)").set_value("Moderator")
        at.run()
        self._widget(at, "button", "▶ Run Analysis").click()
        at.run()
        self.assertEqual(int(next(m.value for m in at.metric if m.label == "Participant Turns")), 1)

    def test_stacked_codebook_header_is_concise_and_avoids_duplicate_domain_counts(self):
        helpers = _load_app_guide_helpers()
        fmt = helpers["format_codebook_summary"]
        self.assertEqual(fmt("gbi_focus_group_starter.yaml", (), 8), "gbi_focus_group_starter.yaml (8 domains)")
        self.assertEqual(
            fmt("gbi_focus_group_starter.yaml", ("a.yaml", "b.yaml"), 14),
            "gbi_focus_group_starter.yaml (+2 stacked · 14 domains)",
        )
        self.assertEqual(
            fmt("Custom: +Local Program Cards (13 domains)", (), 13),
            "Custom: +Local Program Cards (13 domains)",
        )

        at = AppTest.from_file(str(APP_PATH), default_timeout=25)
        at.run()
        corpus_box = self._widget(at, "selectbox", "Corpus Dataset")
        corpus_box.set_value(next(o for o in corpus_box.options if "Focus-Group Notes" in str(o)))
        at.run()
        stack_box = self._widget(at, "multiselect", "Stack Additional Starter Codebooks (optional)")
        all_extras = list(stack_box.options)
        self.assertGreaterEqual(len(all_extras), 5)
        stack_box.set_value(all_extras)
        at.run()
        self._widget(at, "button", "▶ Run Analysis").click()
        at.run()
        self.assertFalse(list(at.exception))
        meta_lines = [str(t.value) for t in at.text]
        self.assertTrue(
            any(f"gbi_focus_group_starter.yaml (+{len(all_extras)} stacked · " in line for line in meta_lines),
            meta_lines,
        )
        for line in meta_lines:
            self.assertNotIn("Project: Stacked Codebook", line)
            self.assertLess(len(line), 200, f"Header still overly verbose: {line!r}")


class GuidesV12AlignmentTests(unittest.TestCase):
    def test_all_four_guides_and_readme_reflect_v12_features_without_stale_v11_drift(self):
        user_guide = (DOCS_DIR / "ATLAS_User_Guide.md").read_text(encoding="utf-8")
        for req in ("TF-IDF + NMF", "Group / summarized notes", "Quotable Verbatim Only",
                    "Stack Additional Starter Codebooks", "Add Theme to Active Codebook",
                    "False-Alarm Spot-Check", "match_mode", "Reference Guides", "▶ Run Analysis"):
            self.assertIn(req, user_guide, f"User Guide missing v1.2 feature {req!r}")
        for stale in ("Suggests emergent topics with LDA", "updates the workbench live", "and project name"):
            self.assertNotIn(stale, user_guide, f"User Guide still carries stale wording {stale!r}")

        method_manual = (DOCS_DIR / "ATLAS_Methodology_and_Reference_Manual.md").read_text(encoding="utf-8")
        for req in ("TF-IDF", "NMF", "match_mode", "group_by_source", "coded_evidence_inventory",
                    "audit_false_alarm_risks", "merge_codebook_dicts", "append_topic_to_codebook"):
            self.assertIn(req, method_manual, f"Methodology Manual missing v1.2 feature {req!r}")
        for unbacked in ("Holm-adjusted", "+3.5"):
            self.assertNotIn(unbacked, method_manual, f"Methodology Manual carries unbacked benchmark claim {unbacked!r}")

        field_guide = (DOCS_DIR / "ATLAS_Practitioner_Field_Guide_Program_Evaluation.md").read_text(encoding="utf-8")
        for req in ("gbi_focus_group_starter.yaml", "Group Mode", "Quotable Verbatim Only",
                    "TF-IDF + NMF", "Add Theme to Active Codebook", "False-Alarm Spot-Check",
                    "Stack Additional Starter Codebooks", "match_mode: exact"):
            self.assertIn(req, field_guide, f"Practitioner Field Guide missing v1.2 feature {req!r}")

        quick_start = (DOCS_DIR / "ATLAS_GBI_Analyst_Quick_Start.md").read_text(encoding="utf-8")
        for req in ("Tab 3: Reference Guides", ".docx", "Stack Additional Starter Codebooks",
                    "Add Theme to Active Codebook", "False-Alarm Spot-Check"):
            self.assertIn(req, quick_start, f"Quick-Start Guide missing {req!r}")

        readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
        for req in ("Group Mode", "Focus Groups (G)", "Distinct Participant Voices", "coded_evidence_inventory.csv",
                    "Quotable Verbatim Only", "TF-IDF + NMF", "False-Alarm Spot-Check", "▶ Run Analysis"):
            self.assertIn(req, readme, f"README.md missing v1.2 feature {req!r}")


if __name__ == "__main__":
    unittest.main()
