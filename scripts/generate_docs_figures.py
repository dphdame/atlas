#!/usr/bin/env python3
"""Regenerate the documentation figures in docs/figures/ from live ATLAS output.

Every number, quote, span and digest drawn in a figure is computed here, at
generation time, by UniversalTranscriptParser -> AtlasEngine (and
AtlasEngine.export_results / verify_workbook_integrity) on the built-in
SOFTWARE_TEST fixtures in data/samples/. The fixtures demonstrate software
mechanics only; the figures carry the label
"[SOFTWARE_TEST ILLUSTRATION — MECHANICS DEMO ONLY]" and are not findings.

Figures are HTML/CSS (grid/flexbox) plus inline SVG, rendered by Playwright's
headless Chromium at device_scale_factor=2. Before each screenshot the page is
checked in the browser and generation fails if any text sits outside a
data-node element, a node holds more than 10 words or more than one sentence,
rendered text is smaller than 22px, a text colour is outside the WCAG 2.1 AA
palette (navy #1E3A8A, teal #0F766E, slate #0F172A / #334155, red #B91C1C,
white on navy/teal fills), the canvas is wider than 1250px (so a PNG stays
legible in GitHub's ~890px README column), any element or SVG label overflows
its box, or a card border / bar track misses the slate #64748B outline that
gives 4.76:1 non-text contrast on white (WCAG 1.4.11).

Usage:
  .venv/bin/python scripts/generate_docs_figures.py            # write PNGs
  .venv/bin/python scripts/generate_docs_figures.py --tables   # print the
      SOFTWARE_TEST walkthrough tables used in README.md and docs/*.md

Playwright browsers are taken from PLAYWRIGHT_BROWSERS_PATH, defaulting to
~/code/playwright-browsers when that folder exists.
"""

from __future__ import annotations

import argparse
import contextlib
import html
import io
import math
import os
import re
import sys
import tempfile
from pathlib import Path

import openpyxl
import yaml

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from atlas_discover import discover_topics  # noqa: E402
from atlas_engine import AtlasEngine, fold_accents  # noqa: E402

CONFIG = REPO / "config"
SAMPLES = REPO / "data" / "samples"
FIG_DIR = REPO / "docs" / "figures"

NAVY = "#1E3A8A"
TEAL = "#0F766E"
INK = "#0F172A"
SLATE = "#334155"
RED = "#B91C1C"
OUTLINE = "#64748B"  # slate-500: 4.76:1 on white, for card borders and bar tracks (WCAG 1.4.11)
TRACK = "#F1F5F9"
ALLOWED_TEXT_COLORS = {
    "rgb(30, 58, 138)", "rgb(15, 118, 110)", "rgb(15, 23, 42)", "rgb(51, 65, 85)",
    "rgb(185, 28, 28)", "rgb(255, 255, 255)",
}
LABEL = "[SOFTWARE_TEST ILLUSTRATION — MECHANICS DEMO ONLY]"

SURVEY_FILES = ["software_test_survey.csv"]
SURVEY_OPTIONS = {"text_col": "response", "id_col": "respondent_id", "speaker_col": "role"}
BILINGUAL_FILES = ["software_test_bilingual_interview.txt", "software_test_zoom_session.vtt"]
DOCX_FILES = ["software_test_teams_multiline.docx"]
PFL = "pfl_case_study_codebook.yaml"
INTAKE = "intake_and_enrollment.yaml"
TOPICS_K = 3


# ----------------------------------------------------------------------
# Live computation
# ----------------------------------------------------------------------
def run(codebook: str | Path, files, options=None, export_dir: Path | None = None):
    engine = AtlasEngine(str(codebook if isinstance(codebook, Path) else CONFIG / codebook))
    results = engine.process_corpus(
        [str(SAMPLES / f) for f in files], root_dir=str(REPO), tabular_options=options,
    )
    if export_dir is not None:
        with contextlib.redirect_stdout(io.StringIO()):
            engine.export_results(results, str(export_dir))
    return engine, results


def binomial_se(reporting: int, n: int) -> float:
    p = reporting / n
    return math.sqrt(p * (1 - p) / n)


def fence_hit(text: str, fences) -> str | None:
    folded = fold_accents(text)
    for fence in fences:
        if re.search(r"\b" + re.escape(fold_accents(fence)), folded, re.IGNORECASE):
            return fence
    return None


def compute(tmp: Path) -> dict:
    export_dir = tmp / "export"
    engine, survey = run(PFL, SURVEY_FILES, SURVEY_OPTIONS, export_dir)
    ok, problems = AtlasEngine.verify_workbook_integrity(
        str(export_dir / "actuarial_parameter_matrix.xlsx"), str(export_dir / "provenance_manifest.json"),
    )
    if not ok:
        raise SystemExit(f"workbook integrity check failed on the fixture export: {problems}")
    wb = openpyxl.load_workbook(export_dir / "actuarial_parameter_matrix.xlsx")
    ws = wb.worksheets[0]
    comments = {}
    for row in range(2, ws.max_row + 1):
        cell = ws.cell(row=row, column=5)
        comments[str(ws.cell(row=row, column=1).value)] = cell.comment.text if cell.comment else ""

    _, bilingual = run(PFL, BILINGUAL_FILES)
    _, docx = run(INTAKE, DOCX_FILES)

    # Context-fence contrast: rerun the same survey with PFL_GAP's fences removed.
    codebook = yaml.safe_load((CONFIG / PFL).read_text(encoding="utf-8"))
    gap = next(d for d in codebook["domains"] if d["id"] == "PFL_GAP")
    fences = list(gap.get("context_fences", []))
    unfenced = dict(codebook, domains=[dict(gap, context_fences=[])])
    unfenced_path = tmp / "pfl_gap_unfenced.yaml"
    unfenced_path.write_text(yaml.safe_dump(unfenced, allow_unicode=True), encoding="utf-8")
    _, survey_unfenced = run(unfenced_path, SURVEY_FILES, SURVEY_OPTIONS)

    fenced_units = set(survey["quotes_df"].query("domain_id == 'PFL_GAP'")["unit_id"])
    fence_rows = []
    for _, q in survey_unfenced["quotes_df"].iterrows():
        fence_rows.append({
            "unit_id": q["unit_id"], "line_number": int(q["line_number"]), "text": q["text"],
            "match_char_start": int(q["match_char_start"]), "match_char_end": int(q["match_char_end"]),
            "fence": fence_hit(q["text"], fences), "counted": q["unit_id"] in fenced_units,
        })

    topics = {
        name: discover_topics(res["tagged_turns_df"].to_dict("records"), n_topics=TOPICS_K)["topics"]
        for name, res in (("survey", survey), ("bilingual", bilingual))
    }
    return {
        "survey": survey, "bilingual": bilingual, "docx": docx, "comments": comments,
        "integrity_ok": ok, "fences": fences, "fence_rows": fence_rows, "topics": topics,
        "gap_roots": list(gap.get("roots_es", [])) + list(gap.get("roots_en", [])),
    }


# ----------------------------------------------------------------------
# HTML building blocks
# ----------------------------------------------------------------------
def e(value) -> str:
    return html.escape("" if value is None else str(value))


def page(body: str, width: int) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #FFFFFF; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: {INK}; }}
#figure {{ width: {width}px; padding: 36px 44px 32px; background: #FFFFFF; }}
.label {{ display: inline-block; font-size: 22px; font-weight: 700; letter-spacing: 0.04em; color: #FFFFFF;
  background: {TEAL}; padding: 6px 14px; border-radius: 4px; margin-bottom: 14px; }}
h1 {{ font-size: 36px; font-weight: 800; color: {NAVY}; margin-bottom: 6px; }}
.sub {{ font-size: 22px; color: {SLATE}; margin-bottom: 26px; }}
.card {{ border: 2px solid {OUTLINE}; border-radius: 10px; padding: 18px 20px; background: #FFFFFF; }}
.card.navy {{ border-top: 8px solid {NAVY}; }}
.card.teal {{ border-top: 8px solid {TEAL}; }}
.kicker {{ font-size: 22px; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; color: {TEAL};
  margin-bottom: 8px; }}
.big {{ font-size: 40px; font-weight: 800; color: {NAVY}; }}
.line {{ font-size: 22px; color: {SLATE}; margin-top: 6px; }}
.mono {{ font-family: Menlo, Consolas, monospace; font-size: 22px; color: {SLATE}; margin-top: 6px; }}
.quote {{ font-size: 24px; color: {INK}; font-style: italic; line-height: 1.4; }}
mark {{ background: #FEF08A; color: {INK}; padding: 0 3px; border-radius: 3px; font-style: normal; font-weight: 700; }}
.chip {{ display: inline-block; font-size: 22px; font-weight: 700; padding: 5px 12px; border-radius: 999px;
  margin: 4px 6px 4px 0; color: #FFFFFF; background: {NAVY}; }}
.chip.teal {{ background: {TEAL}; }}
.chip.outline {{ background: #FFFFFF; color: {NAVY}; border: 2px solid {NAVY}; }}
.ok {{ color: {TEAL}; font-weight: 800; }}
.no {{ color: {RED}; font-weight: 800; }}
.arrow {{ font-size: 40px; color: {SLATE}; display: flex; align-items: center; justify-content: center; }}
.verdict {{ font-size: 30px; font-weight: 800; text-align: center; }}
.foot {{ font-size: 22px; color: {SLATE}; margin-top: 22px; }}
</style></head><body><div id="figure">{body}</div></body></html>"""


def header(title: str, subtitle: str) -> str:
    return (f'<div class="label" data-node>{e(LABEL)}</div>'
            f'<h1 data-node>{e(title)}</h1><div class="sub" data-node>{e(subtitle)}</div>')


def highlight(text: str, start: int, end: int) -> str:
    return f"{e(text[:start])}<mark>{e(text[start:end])}</mark>{e(text[end:])}"


def short_sha(sha: str) -> str:
    return f"{sha[:12]}…"


# ----------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------
def fig_context_fence(d: dict) -> str:
    survey = d["survey"]
    rows_html = []
    for r in sorted(d["fence_rows"], key=lambda r: r["line_number"]):
        rid = r["unit_id"].split("::")[-1]
        fence = (f'<div class="line ok" data-node>✓ Fence word in turn: {e(r["fence"])}</div>' if r["fence"]
                 else '<div class="line no" data-node>✕ No fence word in turn</div>')
        verdict = ('<div class="verdict ok" data-node>✓ Counted</div>' if r["counted"]
                   else '<div class="verdict no" data-node>✕ Not counted</div>')
        rows_html.append(f"""
<div style="display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:18px;margin-bottom:18px;">
  <div class="card teal"><div class="kicker" data-node>Row {e(rid)} · line {r['line_number']}</div>
    <div class="quote" data-node>{highlight(r['text'], r['match_char_start'], r['match_char_end'])}</div></div>
  <div class="card"><div class="line ok" data-node>✓ Root matched</div>{fence}</div>
  <div class="card" style="display:flex;align-items:center;justify-content:center;">{verdict}</div>
</div>""")
    roots = "".join(f'<span class="chip" data-node>{e(t)}</span>' for t in d["gap_roots"][:6])
    fences = "".join(f'<span class="chip teal" data-node>{e(t)}</span>' for t in d["fences"])
    n = survey["total_documents"]
    body = header(
        "Context fences: a root counts only with a fence word",
        f"PFL_GAP rule · {PFL} · SOFTWARE_TEST survey CSV, N = {n}",
    ) + f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:22px;">
  <div class="card navy"><div class="kicker" data-node>Roots (sample)</div>{roots}</div>
  <div class="card teal"><div class="kicker" data-node>Context fences</div>{fences}</div>
</div>
{''.join(rows_html)}
<div class="foot" data-node>Highlighted span = match_char_start to match_char_end.</div>
<div class="foot" data-node>Accents fold before matching: agotó matches root agoto.</div>"""
    return page(body, 1200)


def fig_distribution(d: dict) -> str:
    survey = d["survey"]
    freq = survey["frequencies_df"]
    n = int(survey["total_documents"])
    # Inner width 1220 - 2 * 44 padding = 1132: track 28..728, value text from 744.
    svg_w, x0, bar_w, row_h = 1132, 28, 700, 92
    svg_rows = []
    for i, (_, r) in enumerate(freq.iterrows()):
        y = i * row_h
        w = bar_w * float(r["prevalence_pct"]) / 100.0
        se = binomial_se(int(r["documents_reporting"]), n)
        svg_rows.append(
            f'<text data-node x="{x0}" y="{y + 26}" font-size="22" fill="{INK}">{e(r["domain_name"])}</text>'
            f'<rect x="{x0}" y="{y + 38}" width="{bar_w}" height="34" fill="{TRACK}" '
            f'stroke="{OUTLINE}" stroke-width="1.5"/>'
            f'<rect x="{x0}" y="{y + 38}" width="{w:.1f}" height="34" fill="{NAVY}"/>'
            f'<text data-node x="{x0 + bar_w + 16}" y="{y + 63}" font-size="22" fill="{SLATE}">'
            f'{int(r["documents_reporting"])} of {n} units · {float(r["prevalence_pct"]):.1f}% · SE {se:.3f}</text>'
        )
    height = row_h * len(freq) + 40
    axis = "".join(
        f'<text data-node x="{x0 + bar_w * t / 100:.0f}" y="{height - 6}" text-anchor="middle" '
        f'font-size="22" fill="{SLATE}">{t}%</text>'
        for t in (0, 25, 50, 75, 100)
    )
    svg = (f'<svg width="{svg_w}" height="{height}" xmlns="http://www.w3.org/2000/svg" role="img">'
           f'{"".join(svg_rows)}{axis}</svg>')
    body = header(
        "Domain prevalence on the SOFTWARE_TEST survey",
        f"{PFL} · N = {n} respondent rows · SE = √(p(1−p)/N)",
    ) + svg + (
        f'<div class="foot" data-node>Prevalence = units with a matching turn ÷ N.</div>'
        f'<div class="foot" data-node>Zero bars mean no fixture turn matched that rule.</div>'
    )
    return page(body, 1220)


def fig_audit_bridge(d: dict) -> str:
    survey = d["survey"]
    q = survey["quotes_df"].iloc[0]
    row = survey["frequencies_df"].set_index("domain_id").loc[q["domain_id"]]
    comment = d["comments"][q["domain_id"]]
    digest = re.search(r"Verification SHA-256: ([0-9a-f]{64})", comment).group(1)
    stamp_title = comment.splitlines()[0]
    status = "PASS" if d["integrity_ok"] else "FAIL"
    cards = [
        ("1. Verbatim quote", "teal",
         f'<div class="quote" data-node>{highlight(q["text"], int(q["match_char_start"]), int(q["match_char_end"]))}</div>'
         f'<div class="line" data-node>{e(Path(q["source_id"]).name)} · line {int(q["line_number"])}</div>'
         f'<div class="line" data-node>chars {int(q["match_char_start"])}–{int(q["match_char_end"])}</div>'
         f'<div class="mono" data-node>file SHA-256 {e(short_sha(q["source_sha256"]))}</div>'),
        ("2. Frequency row", "navy",
         f'<div class="line" data-node>{e(q["domain_id"])}</div>'
         f'<div class="big" data-node>{float(row["prevalence_pct"]):.1f}%</div>'
         f'<div class="line" data-node>{int(row["documents_reporting"])} of {int(row["total_documents"])} units</div>'
         f'<div class="line" data-node>{int(row["matching_turns"])} matching turn</div>'),
        ("3. Excel cell comment", "navy",
         f'<div class="line" data-node>{e(stamp_title)}</div>'
         f'<div class="mono" data-node>digest {e(short_sha(digest))}</div>'
         f'<div class="line" data-node>Prevalence cell, actuarial_parameter_matrix.xlsx</div>'),
        ("4. Integrity check", "teal",
         f'<div class="line" data-node>verify_workbook_integrity()</div>'
         f'<div class="big {"ok" if d["integrity_ok"] else "no"}" data-node>{"✓" if d["integrity_ok"] else "✕"} {status}</div>'
         f'<div class="line" data-node>Recomputes digest from manifest</div>'),
    ]
    boxes = [f'<div class="card {tone}"><div class="kicker" data-node>{e(kicker)}</div>{inner}</div>'
             for kicker, tone, inner in cards]
    right = '<div class="arrow" data-node>→</div>'
    # Inner width 1200 - 2 * 44 = 1112; columns 524 | 64 | 524, so step 2 is centred at x = 850
    # and step 3 at x = 262. The elbow runs down from step 2, left, and down into step 3.
    elbow = (f'<svg width="1112" height="64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="display:block;">'
             f'<path d="M850 4 V30 H262 V48" fill="none" stroke="{SLATE}" stroke-width="4"/>'
             f'<path d="M250 46 L262 62 L274 46 Z" fill="{SLATE}"/></svg>')
    parts = [boxes[0], right, boxes[1], f'<div style="grid-column:1 / -1;">{elbow}</div>',
             boxes[2], right, boxes[3]]
    body = header(
        "Audit bridge: quote to verified spreadsheet cell",
        f"SOFTWARE_TEST survey CSV · {PFL} · AtlasEngine.export_results",
    ) + (f'<div style="display:grid;grid-template-columns:1fr 64px 1fr;'
         f'align-items:stretch;">{"".join(parts)}</div>'
         '<div class="foot" data-node>Editing a count or comment makes the check fail.</div>')
    return page(body, 1200)


def fig_dashboard(d: dict) -> str:
    survey = d["survey"]
    freq = survey["frequencies_df"]
    kpis = [
        ("Analytical Units (N)", survey["total_documents"]),
        ("Participant Turns", survey["participant_turns_analyzed"]),
        ("Active Domains", len(freq)),
        ("Matched Turn Mentions", int(freq["matching_turns"].sum())),
    ]
    kpi_html = "".join(
        f'<div class="card navy" style="text-align:center;"><div class="big" data-node>{v}</div>'
        f'<div class="line" data-node>{e(k)}</div></div>' for k, v in kpis
    )
    topics = d["topics"]["survey"]

    def step(num):
        return (f'<span class="chip" style="background:{TEAL};min-width:40px;text-align:center;" data-node>'
                f'{num}</span>')

    body = header(
        "ATLAS workbench walkthrough",
        f"Survey CSV sample · {PFL} · values computed by AtlasEngine",
    ) + f"""
<div style="display:grid;grid-template-columns:420px 1fr;gap:24px;">
  <div class="card" style="background:#F1F5F9;align-self:start;">
    <div class="kicker" data-node>Sidebar</div>
    <div style="margin-top:10px;">{step(1)}<span class="line" data-node>Corpus Dataset</span></div>
    <div class="mono" style="margin:6px 0 14px 0;" data-node>Survey CSV (SOFTWARE_TEST)</div>
    <div>{step(2)}<span class="line" data-node>Active YAML Codebook</span></div>
    <div class="mono" style="margin:6px 0 14px 0;" data-node>{e(PFL)}</div>
    <div class="line" data-node>Uploads: .docx .vtt .srt .txt .md .csv .xlsx</div>
  </div>
  <div>
    <div style="margin-bottom:12px;">{step(3)}<span class="line" data-node>Tab 1 KPI cards, live per run</span></div>
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-bottom:18px;">{kpi_html}</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px;">
      <div class="card teal">{step(4)}<span class="line" data-node>Prevalence chart and table</span></div>
      <div class="card teal">{step(5)}<span class="line" data-node>Quote browser with SHA-256</span></div>
      <div class="card teal">{step(6)}<span class="line" data-node>{len(topics)} topics with verbatim medoids</span></div>
    </div>
    <div class="card navy">{step(7)}<span class="line" data-node>Tab 2: N, prevalence, binomial SE</span>
      <div style="margin-top:10px;">
        <span class="chip outline" data-node>actuarial_parameter_matrix.xlsx</span>
        <span class="chip outline" data-node>provenance_manifest.json</span>
        <span class="chip outline" data-node>verbatim_quotes_inventory.csv</span>
      </div>
    </div>
  </div>
</div>"""
    return page(body, 1220)


def fig_pipeline(_: dict) -> str:
    def box(kicker, tone, lines):
        inner = "".join(f'<div class="line" data-node>{e(t)}</div>' for t in lines)
        return f'<div class="card {tone}"><div class="kicker" data-node>{e(kicker)}</div>{inner}</div>'

    down = '<div class="arrow" style="height:46px;" data-node>↓</div>'
    body = (
        f'<h1 data-node>ATLAS pipeline: transcripts to audited counts</h1>'
        f'<div class="sub" data-node>Modules and what each one adds</div>'
        + box("Inputs", "navy", [".docx .vtt .srt .txt .md transcripts", ".csv .xlsx tables, one response per row"])
        + down
        + box("UniversalTranscriptParser", "navy", [
            "Speaker turns, line numbers, character offsets",
            "source_id per file; unit_id per transcript or row",
            "Facilitator turns flagged and excluded"])
        + down
        + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">'
        + box("atlas_discover (inductive)", "teal", [
            "LDA topics over participant turns",
            "TF-IDF cosine medoid: one real turn",
            "Draft YAML codebook for coder review"])
        + box("AtlasEngine (deductive)", "navy", [
            "YAML roots, context fences, exclusion fences",
            "Accent-insensitive matching, exact verbatim spans",
            "Prevalence over analytical units"])
        + "</div>" + down
        + box("Exports and verification", "teal", [
            "xlsx with audit-stamp comments; manifest; quotes CSV",
            "verify_workbook_integrity recomputes every digest"])
    )
    return page(body, 1160)


FIGURES = {
    "atlas_codebook_context_fence.png": fig_context_fence,
    "atlas_labor_market_distribution.png": fig_distribution,
    "atlas_audit_bridge.png": fig_audit_bridge,
    "atlas_dashboard_ui_walkthrough.png": fig_dashboard,
    "atlas_pipeline_architecture.png": fig_pipeline,
}

QA_SCRIPT = """
(allowed) => {
  const problems = [];
  const words = (t) => t.split(/\\s+/).filter(w => /[\\p{L}\\p{N}]/u.test(w)).length;
  document.querySelectorAll('[data-node]').forEach(el => {
    const t = el.textContent.replace(/\\s+/g, ' ').trim();
    if (words(t) > 10) problems.push(`node over 10 words (${words(t)}): ${t}`);
    const ends = (t.match(/[.!?](\\s|$)/g) || []).length;
    if (ends > 1) problems.push(`multi-sentence node: ${t}`);
  });
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode;
    const t = n.textContent.trim();
    if (!t || n.parentElement.closest('style')) continue;
    const el = n.parentElement;
    if (!el.closest('[data-node]')) problems.push(`text outside a data-node: ${t}`);
    const cs = getComputedStyle(el);
    const size = parseFloat(cs.fontSize);
    if (size < 22) problems.push(`font ${size}px < 22px: ${t}`);
    const color = el.namespaceURI === 'http://www.w3.org/2000/svg' ? cs.fill : cs.color;
    if (!allowed.includes(color)) problems.push(`text colour ${color} outside palette: ${t}`);
  }
  const describe = (el) => `<${el.tagName.toLowerCase()}${typeof el.className === 'string' && el.className.trim()
    ? '.' + el.className.trim().replace(/\\s+/g, '.') : ''}> ${el.textContent.replace(/\\s+/g, ' ').trim().slice(0, 60)}`;
  const figure = document.getElementById('figure');
  const figureWidth = figure.getBoundingClientRect().width;
  if (figureWidth > 1250) problems.push(`#figure width ${figureWidth}px > 1250px`);
  [figure, ...figure.querySelectorAll('*')].forEach(el => {
    if (!(el instanceof HTMLElement) || getComputedStyle(el).display === 'inline') return;
    if (el.scrollWidth > el.clientWidth + 2)
      problems.push(`horizontal overflow (${el.scrollWidth} > ${el.clientWidth}): ${describe(el)}`);
  });
  document.querySelectorAll('.card').forEach(el => {
    const cs = getComputedStyle(el);
    for (const side of ['Left', 'Right', 'Bottom']) {
      const c = cs[`border${side}Color`];
      if (c !== 'rgb(100, 116, 139)')
        problems.push(`card border ${side.toLowerCase()} colour ${c} is not rgb(100, 116, 139): ${describe(el)}`);
    }
  });
  document.querySelectorAll('svg rect').forEach(r => {
    if ((r.getAttribute('fill') || '').toUpperCase() === '#F1F5F9'
        && (r.getAttribute('stroke') || '').toUpperCase() !== '#64748B')
      problems.push('bar track rect without stroke #64748B');
  });
  document.querySelectorAll('svg').forEach(svg => {
    const w = svg.width.baseVal.value, h = svg.height.baseVal.value;
    const boxes = [...svg.querySelectorAll('text')].map(t => ({t: t.textContent.trim(), b: t.getBBox()}));
    boxes.forEach(({t, b}) => {
      if (b.x < 0 || b.y < 0 || b.x + b.width > w + 0.5 || b.y + b.height > h + 0.5)
        problems.push(`SVG text past the SVG bounds (${w}x${h}): ${t}`);
    });
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i].b, b = boxes[j].b;
      if (a.x < b.x + b.width - 1 && b.x < a.x + a.width - 1 && a.y < b.y + b.height - 1 && b.y < a.y + a.height - 1)
        problems.push(`SVG text overlap: ${boxes[i].t} / ${boxes[j].t}`);
    }
  });
  return problems;
}
"""


DEFAULT_BROWSERS = Path.home() / "code" / "playwright-browsers"


def launch_chromium(pw):
    """Launch headless Chromium. If the pinned build is absent, use the newest headless
    shell already installed under PLAYWRIGHT_BROWSERS_PATH rather than downloading one."""
    launch_args = {}
    if not Path(pw.chromium.executable_path).exists():
        root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", DEFAULT_BROWSERS))
        shells = sorted(root.glob("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell"))
        if not shells:
            raise SystemExit(f"no Chromium headless shell under {root}; run `playwright install chromium`")
        launch_args["executable_path"] = str(shells[-1])
        print(f"using installed browser {shells[-1].parent.parent.name}")
    return pw.chromium.launch(**launch_args)


def render(figures: dict, out_dir: Path) -> None:
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and DEFAULT_BROWSERS.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(DEFAULT_BROWSERS)
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    with sync_playwright() as pw:
        browser = launch_chromium(pw)
        context = browser.new_context(viewport={"width": 1800, "height": 1200}, device_scale_factor=2)
        page_ = context.new_page()
        for name, markup in figures.items():
            page_.set_content(markup)
            problems = page_.evaluate(QA_SCRIPT, sorted(ALLOWED_TEXT_COLORS))
            if problems:
                failures.extend(f"{name}: {p}" for p in problems)
                continue
            page_.locator("#figure").screenshot(path=str(out_dir / name), animations="disabled")
            print(f"wrote {out_dir / name}")
        browser.close()
    if failures:
        raise SystemExit("figure QA failed:\n  " + "\n  ".join(failures))


# ----------------------------------------------------------------------
# Walkthrough tables for the docs
# ----------------------------------------------------------------------
def md_frequency_table(results) -> str:
    n = int(results["total_documents"])
    lines = ["| Domain ID | Domain | Units reporting | N | Prevalence (%) | Binomial SE | Matching turns |",
             "| :--- | :--- | ---: | ---: | ---: | ---: | ---: |"]
    for _, r in results["frequencies_df"].iterrows():
        se = binomial_se(int(r["documents_reporting"]), n) if n else float("nan")
        lines.append(f"| `{r['domain_id']}` | {r['domain_name']} | {int(r['documents_reporting'])} | {n} | "
                     f"{float(r['prevalence_pct']):.1f} | {se:.3f} | {int(r['matching_turns'])} |")
    return "\n".join(lines)


def print_tables(d: dict) -> None:
    for title, key in (("Survey CSV x pfl", "survey"), ("Bilingual x pfl", "bilingual"), ("DOCX x intake", "docx")):
        r = d[key]
        f = r["frequencies_df"]
        print(f"\n### {title}: units={r['total_documents']} participant_turns={r['participant_turns_analyzed']} "
              f"turns_parsed={r['total_turns_parsed']} domains={len(f)} matched={int(f['matching_turns'].sum())}")
        print(md_frequency_table(r))
        for _, q in r["quotes_df"].iterrows():
            print(f"QUOTE {q['domain_id']} | {q['source_id']} | unit {q['unit_id']} | line {q['line_number']} | "
                  f"{q['speaker']} | {q['match_char_start']}-{q['match_char_end']} {q['match_text']!r} | "
                  f"{q['source_sha256'][:12]} | {q['text']!r}")
    print("\n### Fence rows", d["fence_rows"])
    for key, topics in d["topics"].items():
        print(f"\n### Topics {key} k={TOPICS_K}")
        for t in topics:
            print(f"{t['topic_id']} | {', '.join(t['top_terms'])} | {t['turn_count']} ({t['share_pct']}%) | "
                  f"{t['medoid_unit_id']} | {t['medoid_text']!r}")
    print("\n### Comments", d["comments"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", action="store_true", help="print the SOFTWARE_TEST walkthrough tables and exit")
    ap.add_argument("--out", default=str(FIG_DIR), help="output folder (default docs/figures)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="atlas_figures_") as tmp:
        data = compute(Path(tmp))
    if args.tables:
        print_tables(data)
        return 0
    render({name: build(data) for name, build in FIGURES.items()}, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
