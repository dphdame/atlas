"""
ATLAS Two-Layer Printable Summary Report (.docx)

Builds a clean, accessible, offline Word (.docx) summary report directly from an
active ATLAS run snapshot:
  - Front Half (Executive Summary): Plain-English overview, Headline Counts,
    embedded horizontal bar chart PNG, Group x Theme Presence Grid (short group
    labels, descending match order), Theme Counts Breakdown, and Direct Quotes /
    Coded Evidence separated by source type.
  - Back Half (Technical and Audit Appendix, starting on a fresh page): Run
    settings, SHA-256 source file fingerprints, unlisted topic clusters (NMF/LDA),
    Spot-Check review log, and skipped structural questions / session headers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence

import docx
import pandas as pd
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

NAVY_HEX = "1B2A4A"
TEAL_HEX = "0B5F5A"
SLATE_HEX = "3E5872"
BORDER_HEX = "CBD5E1"
ZEBRA_HEX = "F1F5F9"
WARN_BG_HEX = "FDF3F0"
WARN_BORDER_HEX = "B4472E"

NAVY_RGB = RGBColor(0x1B, 0x2A, 0x4A)
TEAL_RGB = RGBColor(0x0B, 0x5F, 0x5A)
SLATE_RGB = RGBColor(0x4A, 0x4A, 0x5A)
INK_RGB = RGBColor(0x1A, 0x1A, 0x2E)
RUST_RGB = RGBColor(0x7A, 0x32, 0x1E)

EVIDENCE_REPORT_LABELS = {
    "notable_quote_verbatim": "Direct Quote",
    "verbatim_turn": "Direct Response",
    "": "Direct Response",
    "key_point_paraphrase": "Key Point Summary",
    "observation": "Note-Taker Observation",
}

EXCLUDED_REASON_LABELS = {
    "header_or_summary_table": "Session header or summary box",
    "question_heading": "Discussion question heading",
    "question_prompt_paragraph": "Follow-up prompt",
    "consent_row": "Consent notice",
    "facilitator_row": "Facilitator line",
    "facilitator_turn": "Facilitator line",
    "note_taker_themes_row": "Note-taker themes summary",
}


def friendly_group_labels(source_ids: Sequence[str]) -> Dict[str, str]:
    """Produce concise, collision-free short labels from file paths."""
    sids = [str(s) for s in source_ids]
    stems = [Path(s).stem for s in sids]
    out: Dict[str, str] = {}
    if len(sids) >= 2:
        token_lists = [[tok for tok in re.split(r"[_\-\s]+", st) if tok] for st in stems]
        if all(token_lists):
            min_len = min(len(t) for t in token_lists)
            pref = 0
            while pref < min_len - 1 and all(t[pref].lower() == token_lists[0][pref].lower() for t in token_lists):
                pref += 1
            candidates = [" ".join(t[pref:]).strip() for t in token_lists]
            if all(candidates) and len({c.lower() for c in candidates}) == len(candidates):
                for sid, cand in zip(sids, candidates):
                    out[sid] = " ".join(w[0].upper() + w[1:] if w else "" for w in cand.split())
                return out
    # Normalize first, then detect collisions AFTER normalization (e.g. room_one vs room__one)
    normalized = [re.sub(r"[_\s]+", " ", st).strip() for st in stems]
    norm_counts: Dict[str, int] = {}
    for nm in normalized:
        k = nm.lower()
        norm_counts[k] = norm_counts.get(k, 0) + 1
    for sid, nm in zip(sids, normalized):
        out[sid] = sid if (not nm or norm_counts[nm.lower()] > 1) else nm
    return out


def _disambiguate_theme_labels(pairs: Sequence[tuple[str, str]]) -> Dict[str, str]:
    """Return strictly unique display labels for (domain_id, domain_name) pairs."""
    labels: Dict[str, str] = {did: name for did, name in pairs}
    for _ in range(3):
        counts: Dict[str, int] = {}
        for lbl in labels.values():
            counts[lbl] = counts.get(lbl, 0) + 1
        dups = {lbl for lbl, c in counts.items() if c > 1}
        if not dups:
            break
        changed = False
        for did, lbl in list(labels.items()):
            if lbl in dups:
                suffix = f" ({did})"
                if not lbl.endswith(suffix):
                    labels[did] = f"{lbl}{suffix}"
                    changed = True
        if not changed:
            for did, lbl in list(labels.items()):
                if lbl in dups:
                    labels[did] = f"{lbl} [id: {did}]"
            break
    return labels


def _shorten_chart_labels(items: Sequence[Dict[str, Any]], max_len: int = 34) -> List[str]:
    """Truncate long bar labels while preserving any trailing disambiguation ID suffix."""
    suffix_re = re.compile(r"(\s+(?:\([^()]{1,20}\)|\[id:\s*[^\]]{1,20}\]))$")

    def _one(label: str) -> str:
        s = str(label or "")
        if len(s) <= max_len:
            return s
        m = suffix_re.search(s)
        if m:
            suf = m.group(1)
            keep = max(4, max_len - len(suf) - 1)
            return s[:keep].rstrip() + "…" + suf
        return s[: max_len - 1].rstrip() + "…"

    out = [_one(str(it.get("label", ""))) for it in items]
    counts: Dict[str, int] = {}
    for lbl in out:
        counts[lbl] = counts.get(lbl, 0) + 1
    for idx, lbl in enumerate(list(out)):
        if counts[lbl] > 1:
            did = str(items[idx].get("domain_id") or (idx + 1))
            suf = f" ({did})"
            keep = max(4, max_len - len(suf) - 1)
            out[idx] = str(items[idx].get("label", ""))[:keep].rstrip() + "…" + suf
    return out


def _friendly_excluded_reason(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    if key in EXCLUDED_REASON_LABELS:
        return EXCLUDED_REASON_LABELS[key]
    spaced = key.replace("_", " ").strip()
    return (spaced[0].upper() + spaced[1:]) if spaced else "Skipped header"


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold
        else [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _render_theme_bar_chart_png(
    items: Sequence[Dict[str, Any]],
    title_text: str,
    subtitle_text: str,
) -> Optional[BytesIO]:
    """Render a crisp measurement-first horizontal bar chart PNG using Pillow.
    At width=1360px displayed at 6.5 in, 32px text = 11.01pt on-page (>= 10.5pt floor).
    """
    if not items:
        return None
    width = 1360
    row_h = 66
    top_pad = 118
    bottom_pad = 28
    height = top_pad + len(items) * row_h + bottom_pad
    left_w = 590
    right_w = 270
    bar_area_w = width - left_w - right_w - 28
    max_val = max((float(it["value"]) for it in items), default=1.0)
    if max_val <= 0:
        max_val = 1.0

    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    f_title = _load_font(38, bold=True)
    f_sub = _load_font(32, bold=False)
    f_lbl = _load_font(32, bold=False)
    f_val = _load_font(32, bold=True)

    draw.rectangle([1, 1, width - 2, height - 2], outline=(203, 213, 225), width=2)
    draw.text((24, 16), title_text, fill=(27, 42, 74), font=f_title)
    draw.text((24, 66), subtitle_text, fill=(74, 74, 90), font=f_sub)
    draw.line([(24, top_pad - 10), (width - 24, top_pad - 10)], fill=(27, 42, 74), width=2)

    disp_labels = _shorten_chart_labels(items, max_len=34)
    for idx, it in enumerate(items):
        y = top_pad + idx * row_h
        cy = y + row_h // 2
        if idx % 2 == 1:
            draw.rectangle([16, y + 2, width - 16, y + row_h - 2], fill=(248, 250, 252))

        lbl = disp_labels[idx]
        bbox = draw.textbbox((0, 0), lbl, font=f_lbl)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((left_w - 18 - tw, cy - th // 2 - 2), lbl, fill=(26, 26, 46), font=f_lbl)

        bar_y0 = y + 14
        bar_y1 = y + 50
        draw.rectangle([left_w, bar_y0, left_w + bar_area_w, bar_y1], fill=(226, 232, 240))
        bw = max(6, int(round((float(it["value"]) / max_val) * bar_area_w)))
        draw.rectangle([left_w, bar_y0, left_w + bw, bar_y1], fill=(27, 42, 74))

        val_txt = str(it["value_label"])
        vbbox = draw.textbbox((0, 0), val_txt, font=f_val)
        vh = vbbox[3] - vbbox[1]
        draw.text((left_w + bar_area_w + 16, cy - vh // 2 - 2), val_txt, fill=(27, 42, 74), font=f_val)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _shade_cell(cell, fill_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_pr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>'))


def _set_cell_margins(cell, top: int = 120, bottom: int = 120, left: int = 130, right: int = 130) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tc_mar.append(node)
    tc_pr.append(tc_mar)


def _set_cell_v_align_top(cell) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_pr.append(parse_xml(f'<w:vAlign {nsdecls("w")} w:val="top"/>'))


def _set_table_borders(table, color_hex: str = BORDER_HEX) -> None:
    tbl_pr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="8" w:space="0" w:color="{NAVY_HEX}"/>'
        f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="{NAVY_HEX}"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
        f'<w:left w:val="none"/><w:right w:val="none"/><w:insideV w:val="none"/>'
        f"</w:tblBorders>"
    )
    tbl_pr.append(borders)


def _add_callout(
    doc: docx.Document,
    title: str,
    body: str,
    fill_hex: str = WARN_BG_HEX,
    border_hex: str = WARN_BORDER_HEX,
) -> None:
    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = True
    row = tbl.rows[0]
    row._tr.get_or_add_trPr().append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
    cell = row.cells[0]
    _shade_cell(cell, fill_hex)
    _set_cell_margins(cell, top=120, bottom=120, left=160, right=140)
    _set_cell_v_align_top(cell)
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
    r_title.font.size = Pt(11.0)
    r_title.font.color.rgb = RUST_RGB if border_hex == WARN_BORDER_HEX else NAVY_RGB
    if body:
        p2 = cell.add_paragraph()
        p2.paragraph_format.space_before = Pt(2)
        p2.paragraph_format.space_after = Pt(0)
        r_body = p2.add_run(body)
        r_body.font.size = Pt(11.0)
        r_body.font.color.rgb = INK_RGB
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(4)


def _add_section_heading(doc: docx.Document, text: str, *, page_break_before: bool = False, size: float = 14.0) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0 if page_break_before else 12)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    if page_break_before:
        p.paragraph_format.page_break_before = True
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(size)
    r.font.color.rgb = NAVY_RGB


def _add_subheading(doc: docx.Document, text: str, *, color: RGBColor = SLATE_RGB) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(11.5)
    r.font.color.rgb = color


def _add_body(
    doc: docx.Document,
    text: str,
    *,
    italic: bool = False,
    color: RGBColor = INK_RGB,
    size: float = 11.0,
    keep_with_next: bool = False,
) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.25
    if keep_with_next:
        p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    if italic:
        r.italic = True
    r.font.size = Pt(size)
    r.font.color.rgb = color


def _add_styled_table(doc: docx.Document, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.autofit = True
    _set_table_borders(tbl)

    hdr_row = tbl.rows[0]
    tr_pr = hdr_row._tr.get_or_add_trPr()
    tr_pr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
    tr_pr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
    for c_idx, h in enumerate(headers):
        cell = hdr_row.cells[c_idx]
        _shade_cell(cell, NAVY_HEX)
        _set_cell_margins(cell, top=120, bottom=120, left=130, right=130)
        _set_cell_v_align_top(cell)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(str(h))
        r.bold = True
        r.font.size = Pt(10.0)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    for r_idx, row_vals in enumerate(rows):
        row = tbl.rows[r_idx + 1]
        row._tr.get_or_add_trPr().append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
        bg = ZEBRA_HEX if r_idx % 2 == 1 else None
        for c_idx, val in enumerate(row_vals):
            cell = row.cells[c_idx]
            if bg:
                _shade_cell(cell, bg)
            _set_cell_margins(cell, top=120, bottom=120, left=130, right=130)
            _set_cell_v_align_top(cell)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(str(val))
            r.font.size = Pt(10.0)
            r.font.color.rgb = INK_RGB

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(5)


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
    Build a two-layer printable Word (.docx) summary report directly from an
    active ATLAS run snapshot:
      - Front Half: Plain-English Executive Summary (Grade 6–7 prose, Headline
        Counts, embedded horizontal bar chart PNG, short-label Group x Theme
        Presence Grid, descending Theme Counts, and Direct Quotes / Coded Evidence).
      - Back Half: Technical and Audit Appendix (Run settings, SHA-256 digests,
        unlisted clusters, Spot-Check review log, skipped headers/questions).
    """
    doc = docx.Document()
    for sec in doc.sections:
        sec.page_width = Inches(8.5)
        sec.page_height = Inches(11.0)
        sec.top_margin = Inches(0.9)
        sec.bottom_margin = Inches(0.9)
        sec.left_margin = Inches(0.9)
        sec.right_margin = Inches(0.9)

    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11.0)
    normal.font.color.rgb = INK_RGB

    freq = results["frequencies_df"]
    quotes = results["quotes_df"]
    tagged = results["tagged_turns_df"]
    typo_df = results.get("typo_matches_df")
    if typo_df is None:
        typo_df = pd.DataFrame()
    file_hashes = results.get("file_hashes") or {}
    tabular_stats = results.get("tabular_stats") or []
    notes_meta = results.get("notes_metadata") or {}

    short_labels = friendly_group_labels(sorted(file_hashes.keys()))

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

    sorted_freq = (
        freq.sort_values(
            ["matching_turns", "documents_reporting", "domain_name"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        if len(freq)
        else freq
    )

    now_utc = datetime.now(timezone.utc)
    date_only = now_utc.strftime("%Y-%m-%d")
    utc_stamp = now_utc.strftime("%Y-%m-%d %H:%M:%S Coordinated Universal Time (UTC)")

    # =========================================================================
    # FRONT HALF — EXECUTIVE SUMMARY (Plain English, Grade 6–7, Impersonal)
    # =========================================================================
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(2)
    p_title.paragraph_format.keep_with_next = True
    rt = p_title.add_run("ATLAS Qualitative Summary Report")
    rt.bold = True
    rt.font.size = Pt(18)
    rt.font.color.rgb = NAVY_RGB

    mode_label = "Focus-Group Notes" if group_mode else "Individual Responses"
    _add_body(
        doc,
        f"Automated Text-to-Ledger Actuarial Synthesis (ATLAS)  |  Date: {date_only}  |  Mode: {mode_label}",
        color=SLATE_RGB,
        size=10.0,
    )

    if is_fixture:
        _add_callout(
            doc,
            "SOFTWARE_TEST FIXTURE — Practice Data Notice",
            "This report used built-in sample files. These counts show how the tool works. They are not real study findings.",
            fill_hex=WARN_BG_HEX,
            border_hex=WARN_BORDER_HEX,
        )

    # 1. Summary at a Glance
    _add_section_heading(doc, "1. Summary at a Glance")
    unit_noun = ("focus group" if total_units == 1 else "focus groups") if group_mode else ("response unit" if total_units == 1 else "response units")
    doc_structs = set((results.get("document_structures") or {}).values())
    all_notes = bool(doc_structs) and doc_structs == {"focus_group_notes"}
    entry_noun = "notes entries" if group_mode else ("written answers" if "tabular" in doc_structs else "spoken turns")

    _add_body(
        doc,
        f"This run read {scanned_count} {entry_noun} across {total_units} {unit_noun}. "
        f"{themes_found} of {total_themes} active themes matched at least one entry, for {theme_matches} total theme matches. "
        "Full run settings, file fingerprints, and quality checks sit in the Technical Appendix at the back of this report.",
    )

    if tabular_stats:
        total_non_blank = sum(int(s.get("non_blank_rows", 0)) for s in tabular_stats)
        total_blank = sum(int(s.get("skipped_blank_rows", 0)) for s in tabular_stats)
        _add_body(
            doc,
            f"Survey coverage: {total_non_blank} written answers scanned ({total_blank} rows left this question blank). "
            "Skipped blank cells count empty boxes on this question only, not overall study participation.",
        )

    _add_subheading(doc, "Headline Counts")
    unit_label = "Focus Groups" if group_mode else "Analytical Units"
    if group_mode:
        scanned_label = "Notes Entries Scanned" if all_notes else "Entries Scanned"
    else:
        scanned_label = "Written Answers Scanned" if "tabular" in doc_structs else "Turns Scanned"

    kpi_rows = [
        (unit_label, str(total_units), "1 file = 1 focus group" if group_mode else "One unit per transcript or non-blank survey response"),
        ("Themes Found", f"{themes_found} of {total_themes}", "Active themes with at least one match"),
        (scanned_label, str(scanned_count), f"{matched_entries} matched a theme; {uncoded_entries} matched none"),
        ("Theme Matches", str(theme_matches), "Total entry-theme matches; one entry can match 2 or more themes"),
    ]
    _add_styled_table(doc, ["Metric", "Value", "What It Counts"], kpi_rows)

    # 2. Theme Summary and Chart
    _add_section_heading(doc, "2. Theme Summary and Chart")
    freq_pairs = [
        (str(r.get("domain_id", "")), str(r["domain_name"]))
        for _, r in sorted_freq.iterrows()
    ] if len(sorted_freq) and "domain_id" in sorted_freq.columns else []
    freq_label_map = _disambiguate_theme_labels(freq_pairs)

    def _freq_disp_label(row) -> str:
        did = str(row.get("domain_id", ""))
        return freq_label_map.get(did, str(row["domain_name"]))

    chart_items: List[Dict[str, Any]] = []
    for _, r in sorted_freq.iterrows():
        mt = int(r["matching_turns"])
        if mt <= 0:
            continue
        if group_mode:
            chart_items.append({
                "domain_id": str(r.get("domain_id", "")),
                "label": _freq_disp_label(r),
                "value": mt,
                "value_label": f"{mt} ({int(r['documents_reporting'])}/{int(r['total_documents'])} groups)",
            })
        else:
            pct = float(r["prevalence_pct"])
            chart_items.append({
                "domain_id": str(r.get("domain_id", "")),
                "label": _freq_disp_label(r),
                "value": pct,
                "value_label": f"{pct:.1f}% ({mt})",
            })
    chart_items = chart_items[:12]
    if chart_items:
        chart_title = "Matched Entries by Theme" if group_mode else "Share of Units Mentioning Each Theme"
        chart_sub = (
            "Shows note volume per theme, not a count of individual people"
            if group_mode
            else f"Percent of {total_units} analytical units mentioning each theme"
        )
        chart_buf = _render_theme_bar_chart_png(chart_items, chart_title, chart_sub)
        if chart_buf is not None:
            p_img = doc.add_paragraph()
            p_img.paragraph_format.space_before = Pt(4)
            p_img.paragraph_format.space_after = Pt(8)
            run_img = p_img.add_run()
            inline_shape = run_img.add_picture(chart_buf, width=Inches(6.5))
            alt_text = f"Horizontal bar chart showing {chart_title.lower()}. Top themes: " + "; ".join(
                f"{it['label']} ({it['value_label']})" for it in chart_items[:5]
            )
            doc_pr = inline_shape._inline.docPr
            doc_pr.set("descr", alt_text)
    else:
        _add_body(doc, "No active themes matched any entry in this run.", italic=True, color=SLATE_RGB)

    if group_mode and group_matrix is not None and len(group_matrix):
        _add_subheading(doc, "Which Focus Groups Mentioned Each Theme")
        _add_body(
            doc,
            "A checkmark (✓) shows that a group raised the theme, with the number of matching entries in parentheses. "
            "A dash (—) means no match. Entry counts show note detail, not how many people agreed.",
            italic=True,
            color=SLATE_RGB,
            size=10.5,
            keep_with_next=True,
        )
        raw_groups = sorted(group_matrix["group_label"].astype(str).unique())
        grid_short = friendly_group_labels(raw_groups) if any("." in g or "_" in g for g in raw_groups) else {g: g for g in raw_groups}
        has_id = "domain_id" in group_matrix.columns
        label_col = "theme_label" if "theme_label" in group_matrix.columns else "domain_name"

        if has_id:
            raw_pairs: list[tuple[str, str]] = []
            seen_ids = set()
            for _, r in group_matrix.iterrows():
                did = str(r["domain_id"])
                if did not in seen_ids:
                    seen_ids.add(did)
                    raw_pairs.append((did, str(r.get("domain_name", r[label_col]))))
            grid_label_map = _disambiguate_theme_labels(raw_pairs)
            ordered_pairs = [(did, freq_label_map.get(did, grid_label_map[did])) for did, _ in raw_pairs]
            lookup = {
                (str(r["domain_id"]), str(r["group_label"])): (bool(r["present"]), int(r["matching_entries"]))
                for _, r in group_matrix.iterrows()
            }
            grid_rows = []
            for did, theme_disp in ordered_pairs:
                row_cells = [theme_disp]
                g_present = 0
                for grp in raw_groups:
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
                for grp in raw_groups:
                    pres, n_ent = lookup_name.get((theme, grp), (False, 0))
                    if pres:
                        g_present += 1
                        row_cells.append(f"✓ ({n_ent})")
                    else:
                        row_cells.append("—")
                row_cells.append(f"{g_present}/{total_units}")
                grid_rows.append(row_cells)
        _add_styled_table(doc, ["Theme", *[grid_short[g] for g in raw_groups], "Groups"], grid_rows)

        if group_table is not None and len(group_table):
            _add_subheading(doc, "Theme Counts Breakdown")
            gt_work = group_table.copy()
            id_col = "_domain_id" if "_domain_id" in gt_work.columns else ("domain_id" if "domain_id" in gt_work.columns else None)
            if id_col and "Theme" in gt_work.columns:
                gt_work["Theme"] = gt_work[id_col].astype(str).map(
                    lambda did: freq_label_map.get(did, did)
                )
            elif "Theme" in gt_work.columns and gt_work["Theme"].astype(str).duplicated().any() and len(gt_work) == len(sorted_freq):
                gt_work["Theme"] = [_freq_disp_label(r) for _, r in sorted_freq.iterrows()]
            cols = [c for c in gt_work.columns if not str(c).startswith("_") and c != "domain_id"]
            tbl_rows = [[r[c] for c in cols] for _, r in gt_work.iterrows()]
            _add_styled_table(doc, cols, tbl_rows)
    elif len(sorted_freq):
        _add_subheading(doc, "Theme Counts Breakdown")
        ind_rows = [
            (
                _freq_disp_label(r),
                f"{int(r['documents_reporting'])} of {int(r['total_documents'])}",
                f"{float(r['prevalence_pct']):.1f}%",
                int(r["matching_turns"]),
            )
            for _, r in sorted_freq.iterrows()
        ]
        _add_styled_table(
            doc,
            ["Theme", "Units Mentioning", "Prevalence (%)", "Theme Matches"],
            ind_rows,
        )
    else:
        _add_body(doc, "No active themes were evaluated.")

    # 3. Direct Quotes and Coded Evidence by Theme
    _add_section_heading(doc, "3. Direct Quotes and Coded Evidence by Theme")
    if quotes.empty:
        _add_body(doc, "No entries matched the active themes in this run.", italic=True, color=SLATE_RGB)
    else:
        _add_body(
            doc,
            "Each row shows whether the text is a direct quote or a note-taker summary so summaries are not placed in quote marks by mistake.",
            italic=True,
            color=SLATE_RGB,
            size=10.5,
            keep_with_next=True,
        )
        # Key evidence strictly by domain_id so two themes sharing a display name never merge!
        ordered_domains: List[tuple[str, str]] = []
        if len(sorted_freq) and "domain_id" in sorted_freq.columns:
            seen_dids = set()
            for _, r in sorted_freq.iterrows():
                did = str(r["domain_id"])
                if did not in seen_dids:
                    seen_dids.add(did)
                    ordered_domains.append((did, str(r["domain_name"])))
        elif "domain_id" in quotes.columns:
            seen_dids = set()
            for _, r in quotes.iterrows():
                did = str(r["domain_id"])
                if did not in seen_dids:
                    seen_dids.add(did)
                    ordered_domains.append((did, str(r.get("domain_name", did))))
        ev_label_map = _disambiguate_theme_labels(ordered_domains)

        for did, dname in ordered_domains:
            dq = quotes[quotes["domain_id"].astype(str) == did] if "domain_id" in quotes.columns else quotes[quotes["domain_name"].astype(str) == dname]
            if dq.empty:
                continue
            disp_theme = ev_label_map.get(did, dname)
            _add_subheading(
                doc,
                f"{disp_theme} ({len(dq)} {'match' if len(dq) == 1 else 'matches'})",
                color=TEAL_RGB,
            )
            ev_rank = {"notable_quote_verbatim": 0, "verbatim_turn": 0, "": 0, "key_point_paraphrase": 1, "observation": 2}
            ordered = dq.assign(_rank=dq["evidence_type"].astype(str).map(lambda x: ev_rank.get(x, 3))).sort_values(
                ["_rank", "source_id", "line_number"], kind="mergesort"
            )
            shown = ordered.head(max_quotes_per_theme)
            ev_rows = []
            for _, q in shown.iterrows():
                ev_label = EVIDENCE_REPORT_LABELS.get(str(q.get("evidence_type", "")), "Coded Entry")
                sid = str(q.get("source_id", ""))
                src_parts = [short_labels.get(sid, sid), f"Line {q.get('line_number', '')}"]
                if str(q.get("question_id", "")):
                    src_parts.append(str(q["question_id"]))
                if str(q.get("speaker", "")) and str(q.get("speaker", "")) != "Unknown":
                    src_parts.append(f"Speaker: {q['speaker']}")
                ev_rows.append((ev_label, " | ".join(src_parts), str(q.get("text", ""))))
            _add_styled_table(doc, ["Source Type", "Location", "Entry Text"], ev_rows)
            if len(ordered) > max_quotes_per_theme:
                _add_body(
                    doc,
                    f"Showing the first {max_quotes_per_theme} of {len(ordered)} matches for {disp_theme}. "
                    "Open the Excel workbook or Comma-Separated Values (CSV) file to inspect all rows.",
                    italic=True,
                    color=SLATE_RGB,
                    size=10.0,
                )

    # =========================================================================
    # BACK HALF — TECHNICAL AND AUDIT APPENDIX (Clean Page Break)
    # =========================================================================
    _add_section_heading(doc, "Technical and Audit Appendix", page_break_before=True, size=16.0)
    _add_body(
        doc,
        "This appendix records run settings, source file fingerprints, unlisted topic clusters, spot-check flags, and skipped lines for method review.",
        color=SLATE_RGB,
        size=10.5,
    )

    # Appendix A: Run Settings & Source File Fingerprints
    _add_section_heading(doc, "Appendix A. Run Settings and Source File Fingerprints", size=13.0)
    overview_rows = [
        ("Analysis Mode", "Group / Summarized Notes (1 file = 1 focus group)" if group_mode else "Individual Analytical Units"),
        ("Run Timestamp", utc_stamp),
        ("Corpus Label", corpus_label),
        ("Active Themes", f"{total_themes}: " + (", ".join(active_theme_names) if active_theme_names else "None")),
        (
            "Spelling Check",
            "On — 1-letter typo check (Damerau-Levenshtein distance 1 on 5+ letter single-word keywords)"
            if spelling_tolerance
            else "Off",
        ),
    ]
    if group_mode:
        overview_rows.append(
            ("Note-Taker Observations", "Included in coding" if include_observations else "Excluded (Direct Quotes and Key Point Summaries only)")
        )
    if tabular_stats:
        sheets = sorted({str(s.get("sheet_name")) for s in tabular_stats if s.get("sheet_name")})
        if sheets:
            overview_rows.append(("Excel Tab(s)", ", ".join(sheets)))
    _add_styled_table(doc, ["Setting", "Value"], overview_rows)

    if file_hashes:
        _add_body(
            doc,
            "Each input file below carries a Secure Hash Algorithm 256-bit (SHA-256) digital fingerprint so reviewers can confirm the exact files used.",
            italic=True,
            color=SLATE_RGB,
            size=10.0,
            keep_with_next=True,
        )
        src_rows = [(short_labels.get(sid, sid), sid, f"{str(digest)[:16]}...") for sid, digest in sorted(file_hashes.items())]
        _add_styled_table(doc, ["Short Label", "Full Source File Path", "SHA-256 Fingerprint Prefix"], src_rows)

    # Appendix B: Unlisted Topic Clusters
    _add_section_heading(doc, "Appendix B. Unlisted Topic Clusters", size=13.0)
    topics = (discovery or {}).get("topics") or []
    if not topics:
        _add_body(doc, "No unsupervised topic clusters were computed for this run.", italic=True, color=SLATE_RGB, size=10.0)
    else:
        n_disc = int((discovery or {}).get("n_analyzed", 0))
        method_raw = str((discovery or {}).get("method", "nmf")).lower()
        method_full = (
            "Non-Negative Matrix Factorization (NMF)"
            if method_raw == "nmf"
            else "Latent Dirichlet Allocation (LDA)"
            if method_raw == "lda"
            else method_raw.upper()
        )
        _add_body(
            doc,
            f"ATLAS grouped {n_disc} scanned entries by shared words using {method_full}, without using the active theme checklist. "
            "Coverage labels report how many entries in each cluster matched none of the active themes.",
            italic=True,
            color=SLATE_RGB,
            size=10.0,
            keep_with_next=True,
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

    # Appendix C: Spot-Check Review Log
    _add_section_heading(doc, "Appendix C. Spot-Check Review Log", size=13.0)
    if quotes.empty:
        _add_body(doc, "No theme matches to spot-check.", italic=True, color=SLATE_RGB, size=10.0)
    elif audit_df is None or audit_df.empty:
        _add_body(doc, f"0 of {theme_matches} theme matches were flagged for review.", color=TEAL_RGB, size=10.0)
    else:
        n_flagged = int(len(audit_df))
        codes_col = audit_df["flag_codes"].astype(str) if "flag_codes" in audit_df.columns else pd.Series(dtype=str)
        n_spell = int(codes_col.str.contains("spelling_tolerance").sum())
        n_pref = int(codes_col.str.contains("prefix_extension").sum())
        n_ctx = int((audit_df["risk_level"] == "Medium").sum())
        _add_body(
            doc,
            f"{n_flagged} of {theme_matches} theme matches were flagged for review "
            f"(Check First — Partial-Word Match: {n_pref}; Check First — Spelling Match: {n_spell}; "
            f"Check in Context — Negation or Short Word: {n_ctx}). "
            "All flagged matches remain counted in the summary tables above until excluded.",
            size=10.0,
            keep_with_next=True,
        )
        if spelling_tolerance and len(typo_df):
            _add_body(
                doc,
                f"The 1-letter spelling check rescued {n_spell} theme match(es) across {len(typo_df)} typo word occurrence(s).",
                italic=True,
                color=SLATE_RGB,
                size=10.0,
                keep_with_next=True,
            )
        max_spotcheck_rows = 50
        sc_rows = []
        for _, r in audit_df.head(max_spotcheck_rows).iterrows():
            f_codes = str(r.get("flag_codes", ""))
            if "spelling_tolerance" in f_codes:
                bucket = "Check First (Spelling Match)"
            elif r.get("risk_level") == "High":
                bucket = "Check First (Partial-Word Match)"
            else:
                bucket = "Check in Context"
            sid = str(r.get("source_id", ""))
            sc_rows.append((
                bucket,
                str(r.get("domain_name", "")),
                str(r.get("matched_span", "")),
                str(r.get("full_word", "")),
                str(r.get("flag_reason", "")),
                f"{short_labels.get(sid, sid)} (Line {r.get('line_number', '')})",
            ))
        _add_styled_table(
            doc,
            ["Review Priority", "Theme", "Matched", "Full Word", "Why Flagged", "Source"],
            sc_rows,
        )
        if len(audit_df) > max_spotcheck_rows:
            _add_body(
                doc,
                f"Showing the first {max_spotcheck_rows} of {len(audit_df)} flagged matches in this printable summary. "
                "Download the Spot-Check Comma-Separated Values (CSV) file for the complete list.",
                italic=True,
                color=SLATE_RGB,
                size=10.0,
            )

    # Appendix D: Skipped Questions & Session Headers
    _add_section_heading(doc, "Appendix D. Skipped Questions and Session Headers", size=13.0)
    excl_rows = []
    for sid, meta in sorted(notes_meta.items()):
        for item in (meta or {}).get("excluded_structural_rows") or []:
            excl_rows.append((
                short_labels.get(sid, sid),
                f"Block {item.get('location', '')}",
                _friendly_excluded_reason(item.get("reason", "")),
                str(item.get("text", "")),
            ))
    if excl_rows:
        _add_body(
            doc,
            f"{len(excl_rows)} structural header or question rows were skipped before coding so facilitator prompts do not enter theme counts.",
            italic=True,
            color=SLATE_RGB,
            size=10.0,
            keep_with_next=True,
        )
        _add_styled_table(doc, ["Source Group", "Location", "Why Skipped", "Skipped Text"], excl_rows)
    else:
        _add_body(doc, "No focus-group headers or question prompts were skipped in this run.", italic=True, color=SLATE_RGB, size=10.0)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
