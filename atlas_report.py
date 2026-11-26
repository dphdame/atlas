"""
ATLAS Printable Summary Report (.docx)

Builds a clean, accessible, offline Word (.docx) summary report directly from an
active ATLAS run snapshot so every KPI, group grid cell, theme count, quote,
discovered cluster, Spot-Check count, and excluded-question record matches the
on-screen workbench and downloadable Excel/CSV tables exactly.
"""

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence

import docx
import pandas as pd
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

NAVY_HEX = "1E3A8A"
TEAL_HEX = "0F766E"
SLATE_HEX = "334155"
BORDER_HEX = "CBD5E1"
LIGHT_BG_HEX = "F8FAFC"
WARN_BG_HEX = "FEF3C7"
WARN_BORDER_HEX = "D97706"

NAVY_RGB = RGBColor(0x1E, 0x3A, 0x8A)
TEAL_RGB = RGBColor(0x0F, 0x76, 0x6E)
SLATE_RGB = RGBColor(0x33, 0x41, 0x55)
INK_RGB = RGBColor(0x0F, 0x17, 0x2A)

EVIDENCE_REPORT_LABELS = {
    "notable_quote_verbatim": "Source: Verbatim Quote",
    "verbatim_turn": "Source: Verbatim Quote",
    "": "Source: Verbatim Quote",
    "key_point_paraphrase": "Source: Paraphrase (Key Point)",
    "observation": "Source: Note-Taker Observation",
}


def _shade_cell(cell, fill_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_pr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>'))


def _set_cell_margins(cell, top: int = 70, bottom: int = 70, left: int = 100, right: int = 100) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tc_mar.append(node)
    tc_pr.append(tc_mar)


def _set_table_borders(table, color_hex: str = BORDER_HEX) -> None:
    tbl_pr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
        f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
        f'<w:left w:val="none"/><w:right w:val="none"/><w:insideV w:val="none"/>'
        f"</w:tblBorders>"
    )
    tbl_pr.append(borders)


def _add_callout(doc: docx.Document, title: str, body: str, fill_hex: str = LIGHT_BG_HEX, border_hex: str = NAVY_HEX) -> None:
    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = True
    cell = tbl.cell(0, 0)
    _shade_cell(cell, fill_hex)
    _set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_pr.append(
        parse_xml(
            f'<w:tcBorders {nsdecls("w")}>'
            f'<w:left w:val="single" w:sz="18" w:space="0" w:color="{border_hex}"/>'
            f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{BORDER_HEX}"/>'
            f'<w:right w:val="single" w:sz="4" w:space="0" w:color="{BORDER_HEX}"/>'
            f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{BORDER_HEX}"/>'
            f"</w:tcBorders>"
        )
    )
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    r_title = p.add_run(title)
    r_title.bold = True
    r_title.font.size = Pt(10.5)
    r_title.font.color.rgb = NAVY_RGB if border_hex == NAVY_HEX else RGBColor(0x92, 0x40, 0x0E)
    if body:
        p2 = cell.add_paragraph()
        p2.paragraph_format.space_before = Pt(2)
        p2.paragraph_format.space_after = Pt(0)
        r_body = p2.add_run(body)
        r_body.font.size = Pt(9.5)
        r_body.font.color.rgb = INK_RGB
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(4)


def _add_section_heading(doc: docx.Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(13)
    r.font.color.rgb = NAVY_RGB


def _add_body(doc: docx.Document, text: str, *, italic: bool = False, color: RGBColor = INK_RGB, size: float = 10.0) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run(text)
    r.italic = italic
    r.font.size = Pt(size)
    r.font.color.rgb = color


def _add_styled_table(doc: docx.Document, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.autofit = True
    _set_table_borders(tbl)

    hdr_row = tbl.rows[0]
    tr_pr = hdr_row._tr.get_or_add_trPr()
    tr_pr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
    for c_idx, h in enumerate(headers):
        cell = hdr_row.cells[c_idx]
        _shade_cell(cell, NAVY_HEX)
        _set_cell_margins(cell, top=80, bottom=80, left=90, right=90)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(str(h))
        r.bold = True
        r.font.size = Pt(9.0)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    for r_idx, row_vals in enumerate(rows):
        row = tbl.rows[r_idx + 1]
        bg = LIGHT_BG_HEX if r_idx % 2 == 1 else None
        for c_idx, val in enumerate(row_vals):
            cell = row.cells[c_idx]
            if bg:
                _shade_cell(cell, bg)
            _set_cell_margins(cell, top=60, bottom=60, left=90, right=90)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(str(val))
            r.font.size = Pt(9.0)
            r.font.color.rgb = INK_RGB

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(4)


def build_summary_report_docx(
    results: Dict[str, Any],
    *,
    group_mode: bool,
    group_table: Optional[pd.DataFrame],
    group_matrix: Optional[pd.DataFrame],
    discovery: Optional[Dict[str, Any]],
    discovery_overlap: Optional[Dict[int, Dict[str, Any]]],
    audit_df: pd.DataFrame,
    active_theme_names: Sequence[str],
    corpus_label: str,
    is_fixture: bool = False,
    spelling_tolerance: bool = False,
    include_observations: bool = False,
    max_quotes_per_theme: int = 25,
) -> bytes:
    """
    Build a formatted Word (.docx) summary report directly from an active ATLAS
    run snapshot. Every count is computed strictly from `results`, `group_table`,
    `group_matrix`, `discovery`, and `audit_df` so it reconciles with the UI and
    Excel/CSV downloads.
    """
    doc = docx.Document()
    for sec in doc.sections:
        sec.page_width = Inches(8.5)
        sec.page_height = Inches(11.0)
        sec.top_margin = Inches(0.8)
        sec.bottom_margin = Inches(0.8)
        sec.left_margin = Inches(0.8)
        sec.right_margin = Inches(0.8)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.0)
    normal.font.color.rgb = INK_RGB

    # Title block
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(2)
    rt = p_title.add_run("ATLAS Analysis Summary Report")
    rt.bold = True
    rt.font.size = Pt(18)
    rt.font.color.rgb = NAVY_RGB

    generated_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _add_body(
        doc,
        f"Generated {generated_utc}  |  Mode: {'Group / summarized notes' if group_mode else 'Individual transcripts / surveys'}  |  Corpus: {corpus_label}",
        color=SLATE_RGB,
        size=9.5,
    )

    if is_fixture:
        _add_callout(
            doc,
            "SOFTWARE_TEST FIXTURE ACTIVE",
            "Built-in sample files demonstrate software mechanics only and are not empirical research findings.",
            fill_hex=WARN_BG_HEX,
            border_hex=WARN_BORDER_HEX,
        )

    freq = results["frequencies_df"]
    quotes = results["quotes_df"]
    tagged = results["tagged_turns_df"]
    typo_df = results.get("typo_matches_df")
    if typo_df is None:
        typo_df = pd.DataFrame()
    file_hashes = results.get("file_hashes") or {}
    tabular_stats = results.get("tabular_stats") or []
    notes_meta = results.get("notes_metadata") or {}

    total_units = int(results["total_documents"])
    scanned_count = int(results["participant_turns_analyzed"])
    total_themes = int(len(freq))
    themes_found = int((freq["documents_reporting"] > 0).sum()) if total_themes else 0
    theme_matches = int(len(quotes))
    if len(tagged) and "matched_domains" in tagged.columns:
        matched_entries = int(sum(1 for ds in tagged["matched_domains"] if ds))
    else:
        matched_entries = 0
    uncoded_entries = max(0, scanned_count - matched_entries)

    # 1. Run Overview & Provenance
    _add_section_heading(doc, "1. Run Overview & Source Provenance")
    overview_rows = [
        ("Active Themes", f"{total_themes}: " + (", ".join(active_theme_names) if active_theme_names else "None")),
        ("Spelling Tolerance", "Enabled (1-typo fallback on 5+ letter single-word keywords)" if spelling_tolerance else "Off"),
    ]
    if group_mode:
        overview_rows.append(
            ("Note-Taker Observations", "Included in coding" if include_observations else "Excluded (Key Points & Quotes only)")
        )
    if tabular_stats:
        sheets = sorted({str(s.get("sheet_name")) for s in tabular_stats if s.get("sheet_name")})
        total_non_blank = sum(int(s.get("non_blank_rows", 0)) for s in tabular_stats)
        total_blank = sum(int(s.get("skipped_blank_rows", 0)) for s in tabular_stats)
        if sheets:
            overview_rows.append(("Excel Sheet(s)", ", ".join(sheets)))
        overview_rows.append(
            ("Written Answers Scanned", f"{total_non_blank} written answers scanned ({total_blank} rows left this question blank)")
        )
    _add_styled_table(doc, ["Setting", "Value"], overview_rows)

    if file_hashes:
        src_rows = [(sid, f"{str(digest)[:12]}...") for sid, digest in sorted(file_hashes.items())]
        _add_styled_table(doc, ["Source File", "SHA-256 Digest (prefix)"], src_rows)

    # 2. Reconciled KPI Summary
    _add_section_heading(doc, "2. Reconciled KPI Summary")
    unit_label = "Focus Groups" if group_mode else "Analytical Units"
    doc_structs = set((results.get("document_structures") or {}).values())
    all_notes = bool(doc_structs) and doc_structs == {"focus_group_notes"}
    if group_mode:
        scanned_label = "Notes Entries Scanned" if all_notes else "Entries Scanned"
    else:
        scanned_label = "Written Answers Scanned" if "tabular" in doc_structs else "Turns Scanned"

    kpi_rows = [
        (unit_label, str(total_units), "1 file = 1 focus group" if group_mode else "1 per transcript file or non-blank survey unit"),
        ("Themes Found", f"{themes_found} of {total_themes}", "Active themes with at least one matching entry"),
        (scanned_label, str(scanned_count), f"{matched_entries} matched at least one theme; {uncoded_entries} matched none"),
        ("Theme Matches", str(theme_matches), "Total (entry x theme) matches; one entry can match multiple themes"),
    ]
    _add_styled_table(doc, ["Metric", "Value", "Definition"], kpi_rows)

    # 3. Theme Presence & Summary Tables
    _add_section_heading(doc, "3. Theme Presence & Summary")
    if group_mode and group_matrix is not None and len(group_matrix):
        _add_body(
            doc,
            "Focus-Group Presence Grid: ✓ = mentioned in group notes (with matching entry count in parentheses); "
            "— = not mentioned. Entry counts reflect note volume, not participant headcount.",
            italic=True,
            color=SLATE_RGB,
            size=9.5,
        )
        groups_ordered = sorted(group_matrix["group_label"].astype(str).unique())
        has_id = "domain_id" in group_matrix.columns
        label_col = "theme_label" if "theme_label" in group_matrix.columns else "domain_name"
        if has_id:
            # Key strictly by domain_id so two themes sharing a display name never overwrite each other.
            ordered_pairs: list[tuple[str, str]] = []
            seen_ids = set()
            for _, r in group_matrix.iterrows():
                did = str(r["domain_id"])
                if did not in seen_ids:
                    seen_ids.add(did)
                    ordered_pairs.append((did, str(r[label_col])))
            name_counts: dict[str, int] = {}
            for _, lbl in ordered_pairs:
                name_counts[lbl] = name_counts.get(lbl, 0) + 1
            ordered_pairs = [
                (did, f"{lbl} ({did})" if name_counts.get(lbl, 0) > 1 else lbl)
                for did, lbl in ordered_pairs
            ]
            lookup = {
                (str(r["domain_id"]), str(r["group_label"])): (bool(r["present"]), int(r["matching_entries"]))
                for _, r in group_matrix.iterrows()
            }
            grid_rows = []
            for did, theme_disp in ordered_pairs:
                row_cells = [theme_disp]
                g_present = 0
                for grp in groups_ordered:
                    pres, n_ent = lookup.get((did, grp), (False, 0))
                    if pres:
                        g_present += 1
                        row_cells.append(f"✓ ({n_ent})")
                    else:
                        row_cells.append("—")
                row_cells.append(f"{g_present}/{total_units}")
                grid_rows.append(row_cells)
        else:
            themes_ordered = list(dict.fromkeys(group_matrix["domain_name"].astype(str)))
            lookup_name = {
                (str(r["domain_name"]), str(r["group_label"])): (bool(r["present"]), int(r["matching_entries"]))
                for _, r in group_matrix.iterrows()
            }
            grid_rows = []
            for theme in themes_ordered:
                row_cells = [theme]
                g_present = 0
                for grp in groups_ordered:
                    pres, n_ent = lookup_name.get((theme, grp), (False, 0))
                    if pres:
                        g_present += 1
                        row_cells.append(f"✓ ({n_ent})")
                    else:
                        row_cells.append("—")
                row_cells.append(f"{g_present}/{total_units}")
                grid_rows.append(row_cells)
        _add_styled_table(doc, ["Theme", *groups_ordered, "Groups"], grid_rows)

        if group_table is not None and len(group_table):
            cols = list(group_table.columns)
            tbl_rows = [[r[c] for c in cols] for _, r in group_table.iterrows()]
            _add_styled_table(doc, cols, tbl_rows)
    elif len(freq):
        ind_rows = [
            (
                str(r["domain_name"]),
                int(r["documents_reporting"]),
                int(r["total_documents"]),
                f"{float(r['prevalence_pct']):.1f}%",
                int(r["matching_turns"]),
            )
            for _, r in freq.iterrows()
        ]
        _add_styled_table(
            doc,
            ["Theme", "Units Reporting", "Analytical Units (N)", "Prevalence (%)", "Theme Matches"],
            ind_rows,
        )
    else:
        _add_body(doc, "No active themes were evaluated.")

    # 4. Coded Evidence & Direct Quotes by Theme
    _add_section_heading(doc, "4. Coded Evidence & Direct Quotes by Theme")
    if quotes.empty:
        _add_body(doc, "No entries matched the active themes.")
    else:
        _add_body(
            doc,
            "Every entry below carries its source label so direct participant quotations are never confused with paraphrased key points or note-taker observations.",
            italic=True,
            color=SLATE_RGB,
            size=9.5,
        )
        for theme in list(dict.fromkeys(freq["domain_name"].astype(str))) if len(freq) else sorted(quotes["domain_name"].astype(str).unique()):
            dq = quotes[quotes["domain_name"].astype(str) == theme]
            if dq.empty:
                continue
            p_sub = doc.add_paragraph()
            p_sub.paragraph_format.space_before = Pt(8)
            p_sub.paragraph_format.space_after = Pt(3)
            p_sub.paragraph_format.keep_with_next = True
            r_sub = p_sub.add_run(f"{theme} ({len(dq)} theme {'match' if len(dq) == 1 else 'matches'})")
            r_sub.bold = True
            r_sub.font.size = Pt(11.0)
            r_sub.font.color.rgb = TEAL_RGB

            # Order verbatim quotes first, then paraphrases, then observations.
            ev_rank = {"notable_quote_verbatim": 0, "verbatim_turn": 0, "": 0, "key_point_paraphrase": 1, "observation": 2}
            ordered = dq.assign(_rank=dq["evidence_type"].astype(str).map(lambda x: ev_rank.get(x, 3))).sort_values(
                ["_rank", "source_id", "line_number"], kind="mergesort"
            )
            shown = ordered.head(max_quotes_per_theme)
            ev_rows = []
            for _, q in shown.iterrows():
                ev_label = EVIDENCE_REPORT_LABELS.get(str(q.get("evidence_type", "")), "Source: Coded Entry")
                src_parts = [str(q.get("source_id", "")), f"Line {q.get('line_number', '')}"]
                if str(q.get("question_id", "")):
                    src_parts.append(str(q["question_id"]))
                if str(q.get("speaker", "")) and str(q.get("speaker", "")) != "Unknown":
                    src_parts.append(f"Speaker: {q['speaker']}")
                ev_rows.append((ev_label, " | ".join(src_parts), str(q.get("text", ""))))
            _add_styled_table(doc, ["Evidence Label", "Provenance", "Text"], ev_rows)
            if len(ordered) > max_quotes_per_theme:
                _add_body(
                    doc,
                    f"Showing first {max_quotes_per_theme} of {len(ordered)} matches for {theme}. See the CSV export for the complete inventory.",
                    italic=True,
                    color=SLATE_RGB,
                    size=9.0,
                )

    # 5. Discover Unlisted Themes
    _add_section_heading(doc, "5. Discover Unlisted Themes (Unsupervised Clusters)")
    topics = (discovery or {}).get("topics") or []
    if not topics:
        _add_body(doc, "No unsupervised clusters were generated for this run.")
    else:
        n_disc = int((discovery or {}).get("n_analyzed", 0))
        method_label = str((discovery or {}).get("method", "nmf")).upper()
        _add_body(
            doc,
            f"Clustered {n_disc} entries without using your theme checklist ({method_label}). Coverage labels report how many entries in each cluster matched none of your active themes.",
            italic=True,
            color=SLATE_RGB,
            size=9.5,
        )
        disc_rows = []
        for t in topics:
            tid = int(t["topic_id"])
            cov = (discovery_overlap or {}).get(tid, {})
            cov_label = cov.get("coverage_label", "")
            disc_rows.append((
                f"Cluster {tid}: {t.get('label', '')}",
                f"{int(t.get('turn_count', 0))} of {n_disc} ({float(t.get('share_pct', 0.0)):.1f}%)",
                cov_label,
                ", ".join(t.get("top_terms") or []),
                str(t.get("medoid_text") or ""),
            ))
        _add_styled_table(
            doc,
            ["Cluster", "Entries", "Coverage vs. Active Themes", "Top Keywords", "Most Representative Example"],
            disc_rows,
        )

    # 6. Spot-Check Matches Summary
    _add_section_heading(doc, "6. Spot-Check Matches Summary")
    if quotes.empty:
        _add_body(doc, "No theme matches to spot-check.")
    elif audit_df is None or audit_df.empty:
        _add_body(doc, f"0 of {theme_matches} theme matches flagged for review.")
    else:
        n_flagged = int(len(audit_df))
        codes_col = audit_df["flag_codes"].astype(str) if "flag_codes" in audit_df.columns else pd.Series(dtype=str)
        n_spell = int(codes_col.str.contains("spelling_tolerance").sum())
        n_pref = int(codes_col.str.contains("prefix_extension").sum())
        n_ctx = int((audit_df["risk_level"] == "Medium").sum())
        _add_body(
            doc,
            f"{n_flagged} of {theme_matches} theme matches flagged for review "
            f"(Check First — Partial-Word Match: {n_pref}; Check First — Spelling Match: {n_spell}; "
            f"Check in Context — Negation or Short Word: {n_ctx}). "
            "All flagged matches are currently included in counts until excluded.",
            size=9.5,
        )
        if spelling_tolerance and len(typo_df):
            _add_body(
                doc,
                f"Spelling tolerance rescued {n_spell} theme match(es) across {len(typo_df)} typo token occurrence(s).",
                italic=True,
                color=SLATE_RGB,
                size=9.5,
            )
        sc_rows = []
        for _, r in audit_df.head(40).iterrows():
            f_codes = str(r.get("flag_codes", ""))
            if "spelling_tolerance" in f_codes:
                bucket = "Check First (Spelling Match)"
            elif r.get("risk_level") == "High":
                bucket = "Check First (Partial-Word Match)"
            else:
                bucket = "Check in Context"
            sc_rows.append((
                bucket,
                str(r.get("domain_name", "")),
                str(r.get("matched_span", "")),
                str(r.get("full_word", "")),
                str(r.get("flag_reason", "")),
                f"{r.get('source_id', '')} (Line {r.get('line_number', '')})",
            ))
        _add_styled_table(
            doc,
            ["Review Priority", "Theme", "Matched", "Full Word", "Why Flagged", "Source"],
            sc_rows,
        )

    # 7. Excluded Questions & Session Headers Audit Table
    _add_section_heading(doc, "7. Excluded Questions & Session Headers (Not Coded)")
    excl_rows = []
    for sid, meta in sorted(notes_meta.items()):
        for item in (meta or {}).get("excluded_structural_rows") or []:
            excl_rows.append((
                sid,
                f"Block {item.get('location', '')}",
                str(item.get("reason", "")).replace("_", " "),
                str(item.get("text", "")),
            ))
    if excl_rows:
        _add_body(
            doc,
            f"{len(excl_rows)} structural prompt/header item(s) were excluded before coding so question text never enters theme counts.",
            italic=True,
            color=SLATE_RGB,
            size=9.5,
        )
        _add_styled_table(doc, ["Source File", "Location", "Exclusion Reason", "Excluded Text"], excl_rows)
    else:
        _add_body(doc, "No focus-group structural headers or question rows were excluded in this run.")

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
