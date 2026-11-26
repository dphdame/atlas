"""
ATLAS — Automated Text-to-Ledger Actuarial Synthesis
Local qualitative coding, topic discovery, and auditable frequency tables for transcripts and surveys.

Every number, quote, digest and topic on screen is computed live from the
selected corpus and codebook by UniversalTranscriptParser, AtlasEngine and
atlas_discover. Nothing is read from outside this folder; ATLAS code makes no
network requests and the page loads no remote assets. Streamlit itself serves
the page over HTTP: the desktop launchers turn off its usage statistics, and
--server.address=localhost keeps it off other network interfaces.
"""

import contextlib
import csv
import hashlib
import html
import inspect
import io
import json
import math
import os
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import altair as alt
import docx
import pandas as pd
import streamlit as st
import yaml
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor
from openpyxl.utils.exceptions import InvalidFileException

try:  # python-docx parses document.xml with lxml; a malformed part raises XMLSyntaxError.
    from lxml.etree import LxmlError
except ImportError:  # pragma: no cover - lxml ships with python-docx
    class LxmlError(Exception):
        pass

from atlas_discover import compute_topic_codebook_overlap, discover_topics, topics_to_codebook_dict
from atlas_engine import (
    AtlasEngine,
    append_topic_to_codebook,
    audit_false_alarm_risks,
    has_non_verbatim_evidence,
    merge_codebook_dicts,
    normalize_codebook_rules,
    summarize_false_alarm_risks,
    tighten_codebook_domain,
    verbatim_only as verbatim_rows,
)
from atlas_report import build_summary_report_docx
from universal_transcript_parser import (
    TABULAR_EXTENSIONS,
    TRANSCRIPT_EXTENSIONS,
    UniversalTranscriptParser,
)

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = APP_DIR / "config"
SAMPLES_DIR = APP_DIR / "data" / "samples"
DOCS_DIR = APP_DIR / "docs"

NAVY = "#1E3A8A"
TEAL = "#0F766E"
SLATE = "#334155"

CORE_THEMES_FILE = "gbi_focus_group_starter.yaml"
ADDON_THEMES_FILE = "optional_delivery_addons.yaml"

CORPUS_GBI_NOTES = "Sample: Multi-Group Focus-Group Notes (.docx)"
CORPUS_UPLOAD = "Upload Custom Files (.docx, .vtt, .srt, .txt, .md, .csv, .xlsx)"

SAMPLE_CORPORA = {
    CORPUS_GBI_NOTES: {
        "files": ["software_test_gbi_group_treatment.docx", "software_test_gbi_group_control.docx"],
        "tabular_options": None,
        "codebook": CORE_THEMES_FILE,
    },
}
CORPUS_OPTIONS = [CORPUS_UPLOAD, *SAMPLE_CORPORA]
UPLOAD_TYPES = ["docx", "vtt", "srt", "txt", "md", "csv", "xlsx"]

CODEBOOK_UPLOAD = "Upload Custom Codebook (.yaml)"
NONE_OPTION = "(none)"

# Data Type: Individual keeps the v1.1 per-unit analysis; Group treats each file as one
# focus group (G = number of files) and hides the binomial interval.
DATA_TYPE_INDIVIDUAL = "Individual transcripts / survey responses"
DATA_TYPE_GROUP = "Group / summarized notes"
DATA_TYPES = [DATA_TYPE_INDIVIDUAL, DATA_TYPE_GROUP]
NOTES_EVIDENCE_CORE = ("key_point_paraphrase", "notable_quote_verbatim")
NOTES_EVIDENCE_WITH_OBSERVATIONS = (*NOTES_EVIDENCE_CORE, "observation")
VERBATIM_EVIDENCE = "notable_quote_verbatim"
# Speakers that are not a participant voice: unattributed entries and note-taker themes.
NON_VOICE_SPEAKERS = frozenset({"", "Unknown", "NoteTaker_Themes"})
GROUP_TABLE_COLUMNS = [
    "Theme", "Focus Groups", "Theme Matches", "Verbatim Quotes", "Paraphrased Key Points",
]
GROUP_TABLE_COLUMNS_WITH_OBS = [
    *GROUP_TABLE_COLUMNS, "Note-Taker Observations",
]
THEMES_EXPANDER_LABEL = "Note-Taker Themes Summary (Reference Only — Not Counted in Prevalence)"
CODED_EVIDENCE_CSV = "coded_evidence_inventory.csv"
NOTES_STRUCTURE = "focus_group_notes"
# (text colour, background colour, label) per evidence type; every pair is >= 4.5:1.
EVIDENCE_BADGE_STYLES = {
    "notable_quote_verbatim": ("#FFFFFF", TEAL, "Source: Verbatim Quote"),
    "verbatim_turn": ("#FFFFFF", TEAL, "Source: Verbatim Quote"),
    "": ("#FFFFFF", TEAL, "Source: Verbatim Quote"),
    "key_point_paraphrase": ("#FFFFFF", SLATE, "Source: Paraphrase (Key Point)"),
    "observation": ("#334155", "#F1F5F9", "Source: Note-Taker Observation"),
}
EVIDENCE_BADGE_FALLBACK = ("#FFFFFF", "#475569", "Source: Transcript / Survey")
# Group x theme tiles: uniform visual weight across all focus groups (every pair >= 4.5:1).
GROUP_TILE_COLOURS = {
    "none": ("#F1F5F9", "#475569"),
    "present": (NAVY, "#FFFFFF"),
}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
RUN_BUTTON_LABEL = "Run Analysis"
TOP_TABS = ["Themes & Quotes", "Exports & Audit Files", "Reference Guides"]
SUB_TABS = ["Theme Summary", "Coded Evidence", "Discover Unlisted Themes", "Spot-Check Matches"]

REFERENCE_GUIDES = [
    ("GBI Analyst Quick-Start Guide (.docx)", "ATLAS_GBI_Analyst_Quick_Start.md"),
    ("User Guide (.docx)", "ATLAS_User_Guide.md"),
    ("Methodology & Reference Manual (.docx)", "ATLAS_Methodology_and_Reference_Manual.md"),
    ("Practitioner Field Guide (.docx)", "ATLAS_Practitioner_Field_Guide_Program_Evaluation.md"),
]

DISCOVERY_METHOD_NMF = "TF-IDF + NMF (Recommended — faster, sharper keywords)"
DISCOVERY_METHOD_LDA = "LDA (Classic bag-of-words)"
DISCOVERY_METHOD_MAP = {DISCOVERY_METHOD_NMF: "nmf", DISCOVERY_METHOD_LDA: "lda"}

SPOTCHECK_PRIORITY_PARTIAL = "Check First (Partial-Word Match)"
SPOTCHECK_PRIORITY_SPELLING = "Check First (Spelling Match)"
SPOTCHECK_PRIORITY_CONTEXT = "Check in Context (Negation or Short Word)"

UPLOAD_MODE_REPLACE = "Use uploaded themes only"
UPLOAD_MODE_COMBINE = "Combine with checked themes above"

DUP_ID_PER_ROW = "Keep each row as its own response (preserves Respondent ID in exports)"
DUP_ID_COMBINE = "Combine repeated rows under one Respondent ID (N = unique respondents)"

# Errors raised by reading a malformed upload: bad CSV structure or quoting (ValueError),
# invalid UTF-8, or a corrupt .xlsx / .docx package or malformed XML part inside one.
UPLOAD_READ_ERRORS = (
    ValueError, KeyError, TypeError, UnicodeDecodeError, csv.Error, OSError,
    zipfile.BadZipFile, InvalidFileException, PackageNotFoundError, ET.ParseError, LxmlError,
)

_TEXT_COLUMN_HINTS = (
    "response", "text", "comment", "answer", "narrative", "transcript",
    "utterance", "open", "feedback", "verbatim", "statement", "note",
)


# ------------------------------------------------------------------------------
# 1. Page configuration and accessible styling (WCAG 2.1 AA palette)
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="ATLAS Workbench",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    f"""
<style>
.main .block-container {{ padding-top: 1.75rem; padding-bottom: 3rem; max-width: 1240px; }}
html, body, [class*="css"] {{ font-size: 16px; }}
.brand-header {{ background: #FFFFFF; border: 1px solid #CBD5E1; border-top: 6px solid {NAVY};
  padding: 1.35rem 1.85rem; border-radius: 8px; margin-bottom: 1.1rem; }}
.brand-header h1 {{ color: {NAVY} !important; font-size: 2rem !important; font-weight: 800 !important;
  margin: 0 0 0.35rem 0 !important; }}
.brand-header p {{ color: #1E293B !important; font-size: 1.08rem !important; margin: 0 !important; }}
.provenance-banner {{ background: #F8FAFC; border: 1px solid #CBD5E1; border-left: 4px solid {NAVY};
  padding: 0.85rem 1.15rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.98rem; color: #0F172A; }}
.badge-row {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
.atlas-badge {{ display: inline-block; font-size: 0.82rem; font-weight: 700; letter-spacing: 0.02em;
  padding: 0.2rem 0.65rem; border-radius: 4px; color: #FFFFFF; background: {NAVY}; }}
.atlas-badge-teal {{ background: {TEAL}; }}
.atlas-badge-outline {{ background: #FFFFFF; color: {NAVY}; border: 2px solid {NAVY}; }}
.coverage-badge {{ display: inline-block; font-size: 0.8rem; font-weight: 700; padding: 0.16rem 0.55rem;
  border-radius: 4px; margin-right: 0.45rem; border: 1px solid #CBD5E1; }}
.coverage-uncoded {{ background: #FEF3C7; color: #92400E; border-color: #D97706; }}
.coverage-partial {{ background: #E0F2FE; color: #075985; border-color: #0284C7; }}
.coverage-covered {{ background: #F1F5F9; color: #334155; border-color: #94A3B8; }}
.quote-box {{ background: #F8FAFC; border: 1px solid #E2E8F0; border-left: 4px solid {TEAL};
  padding: 1rem 1.25rem; border-radius: 6px; margin-bottom: 0.9rem; }}
.topic-box {{ border-left-color: {NAVY}; }}
.risk-high-box {{ border-left-color: #B91C1C; }}
.risk-medium-box {{ border-left-color: #92400E; }}
.risk-badge {{ display: inline-block; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.02em;
  padding: 0.15rem 0.5rem; border-radius: 3px; color: #FFFFFF; margin-right: 0.45rem; }}
.risk-badge-high {{ background: #B91C1C; }}
.risk-badge-medium {{ background: #92400E; }}
.quote-meta {{ font-size: 0.94rem; font-weight: 700; color: {TEAL}; margin-bottom: 0.4rem; line-height: 1.45; }}
.topic-box .quote-meta {{ color: {NAVY}; }}
.quote-text {{ font-size: 1.05rem; color: #0F172A; line-height: 1.6; margin-bottom: 0.5rem; white-space: pre-wrap; }}
.quote-text mark {{ background: #FEF08A; color: #0F172A; padding: 0 0.1rem; }}
.quote-provenance {{ font-size: 0.85rem; font-family: monospace; color: #334155; background: #E2E8F0;
  padding: 0.22rem 0.55rem; border-radius: 3px; display: inline-block; }}
</style>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------------------
# 2. Live analysis helpers (all computation goes through the ATLAS modules)
# ------------------------------------------------------------------------------
def list_config_codebooks():
    if not CONFIG_DIR.is_dir():
        return []
    return sorted(p.name for p in CONFIG_DIR.glob("*.yaml") if p.is_file())


@st.cache_data(show_spinner=False)
def load_catalog_rules(filename):
    path = CONFIG_DIR / filename
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return normalize_codebook_rules(raw)


def build_catalog_codebook_dict(core_rules, selected_core_ids, addon_rules, selected_addon_ids,
                                uploaded_dict=None, uploaded_name=None, upload_mode=UPLOAD_MODE_REPLACE):
    """Build a single valid ATLAS codebook dict from checkbox selections and/or uploaded YAML."""
    checked = [
        r for r in core_rules if r["id"] in selected_core_ids
    ] + [
        r for r in addon_rules if r["id"] in selected_addon_ids
    ]
    checked_cb = {"project": "Selected Evaluation Themes", "version": "2.0", "domains": checked} if checked else None

    if uploaded_dict is not None:
        if upload_mode == UPLOAD_MODE_REPLACE or checked_cb is None:
            return uploaded_dict
        return merge_codebook_dicts([
            ("Selected Evaluation Themes", checked_cb),
            (uploaded_name or "uploaded_codebook.yaml", uploaded_dict),
        ])
    if checked_cb is None:
        return None
    return checked_cb


def is_id_column(name):
    lowered = str(name).strip().lower()
    return lowered == "id" or lowered.endswith(("_id", " id", "-id", ".id"))


def detect_text_column(frame):
    """Pick the free-text column of a table, never an id / *_id column; None if there is none."""
    columns = [str(c) for c in frame.columns]
    candidates = [c for c in columns if not is_id_column(c)]
    if not candidates:
        return None
    hinted = [c for c in candidates if any(h in c.lower() for h in _TEXT_COLUMN_HINTS)]
    pool = hinted or candidates

    def text_volume(col):
        # Total characters over all rows, so a mostly-blank column cannot win on one long cell.
        return sum(len(str(v).strip()) for v in frame[col].tolist())

    return max(pool, key=lambda c: (text_volume(c), -columns.index(c)))


def upload_path_key(name):
    """
    Collision key for a file name. APFS and NTFS ignore case, and APFS also
    ignores Unicode normalization, so 'A.txt' / 'a.txt' and NFC / NFD 'café.txt'
    each name one physical file there.
    """
    return unicodedata.normalize("NFC", str(name)).casefold()


def safe_upload_name(name, taken):
    """Basename of an upload, suffixed _2, _3, ... until no name in taken (a set of
    upload_path_key values) maps to the same physical file; the key is added to taken."""
    base = os.path.basename(str(name).replace("\\", "/")) or "upload"
    candidate, counter = base, 2
    while upload_path_key(candidate) in taken:
        stem, ext = os.path.splitext(base)
        candidate = f"{stem}_{counter}{ext}"
        counter += 1
    taken.add(upload_path_key(candidate))
    return candidate


def stretch_kwargs(widget_fn, streamlit_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Full-width sizing keyword for widget_fn. width="stretch" exists from
    Streamlit 1.50; requirements.txt allows 1.40, where these widgets only take
    use_container_width (st.dataframe's width there is an int).
    """
    parts = re.findall(r"\d+", streamlit_version or st.__version__)[:2]
    version = tuple(int(p) for p in parts) + (0,) * (2 - len(parts))
    if version >= (1, 50) and "width" in inspect.signature(widget_fn).parameters:
        return {"width": "stretch"}
    return {"use_container_width": True}


def describe_prevalence_chart(
    df: pd.DataFrame,
    total_units: int,
    *,
    include_ci: bool = False,
) -> str:
    """
    Plain-text summary of a domain-prevalence bar chart for screen readers (the Vega-Lite
    description) and the visible chart summary. Deterministic: built only from df, which needs
    domain_name, documents_reporting and prevalence_pct (plus ci95_low_pct and
    ci95_high_pct when include_ci). Lists the three highest-prevalence matched domains,
    ordered by prevalence descending, then domain name.
    """
    if df is None or len(df) == 0:
        return "No domains defined in the active codebook."
    k = len(df)
    domains = "domain" if k == 1 else "domains"
    if total_units <= 0:
        return f"Horizontal bar chart with 0 analytical units, so no prevalence is defined for the {k} coded {domains}."
    units = "unit" if total_units == 1 else "units"

    def pct(value):
        try:
            value = float(value) if pd.notna(value) else math.nan
        except (TypeError, ValueError):
            return "n/a"
        return f"{value:.1f}%" if math.isfinite(value) else "n/a"

    # A missing count (NaN or nullable pd.NA) is no reporting unit; a missing percentage
    # reads "n/a", never "nan%".
    rows = df.assign(
        _name=df["domain_name"].astype(str),
        _prevalence=pd.to_numeric(df["prevalence_pct"], errors="coerce"),
        _reporting=pd.to_numeric(df["documents_reporting"], errors="coerce").map(
            lambda v: int(v) if pd.notna(v) and math.isfinite(float(v)) else 0),
    ).sort_values(["_prevalence", "_name"], ascending=[False, True], kind="mergesort", na_position="last")
    matched = rows[rows["_reporting"] > 0]
    if matched.empty:
        return (f"Horizontal bar chart across {total_units} analytical {units} showing 0% prevalence "
                f"across all {k} coded {domains}.")
    listed = []
    for _, r in matched.head(3).iterrows():
        detail = f"{int(r['_reporting'])} of {total_units} {units}"
        if include_ci:
            detail += f", 95% CI {pct(r['ci95_low_pct'])}–{pct(r['ci95_high_pct'])}"
        listed.append(f"{r['_name']} {pct(r['_prevalence'])} ({detail})")
    text = (f"Horizontal bar chart across {total_units} analytical {units}. "
            f"Highest prevalence: {'; '.join(listed)}.")
    if len(matched) > 3:
        text += f" Other matched domains not listed: {len(matched) - 3}."
    if len(matched) < k:
        text += f" Domains with 0% prevalence: {k - len(matched)} of {k}."
    return text


def chart_summary_html(summary: str) -> str:
    """
    Literal HTML paragraph for a chart summary rendered via st.html(). Every
    HTML metacharacter (& < > " ') is escaped and line breaks collapse to one space, so text
    built from uploaded names never reaches Streamlit's Markdown, GFM autolink
    or shortcode plugins and displays verbatim. The Vega-Lite description keeps
    the plain text. Pairs #475569 text with an explicit #FFFFFF background
    (7.58:1, WCAG AA >= 4.5:1) and #64748B border (4.76:1 on white, >= 3:1 on
    dark themes) so contrast holds in both Light and Dark Streamlit themes.
    """
    single_line = re.sub(r"[\r\n\x0b\x0c\x85\u2028\u2029]+", " ", str(summary))
    return (
        '<p class="atlas-chart-summary" style="font-size:0.875rem;color:#475569;'
        'background-color:#FFFFFF;border:1px solid #64748B;border-radius:4px;'
        'padding:0.4rem 0.65rem;margin:0.25rem 0 0.5rem;line-height:1.45;">'
        f"Chart summary: {html.escape(single_line, quote=True)}</p>"
    )


def count_distinct_voices(turns_df):
    """Distinct (source_id, speaker) pairs, so P1 in two focus groups counts as two voices."""
    if turns_df is None or len(turns_df) == 0 or not {"source_id", "speaker"} <= set(turns_df.columns):
        return 0
    return len({(str(s), str(p)) for s, p in zip(turns_df["source_id"], turns_df["speaker"])
                if str(p) not in NON_VOICE_SPEAKERS})


def group_labels_for(source_ids):
    """Display label per focus-group file: its basename, or the full relative path
    when two files share a basename."""
    ids = [str(s) for s in source_ids]
    names = [os.path.basename(s) or s for s in ids]
    return {sid: (name if names.count(name) == 1 else sid) for sid, name in zip(ids, names)}


def build_group_frequency_table(freq, quotes, total_groups, *, include_observations=False):
    """
    One row per codebook theme: focus groups reporting (g of G) and reconciled
    evidence counts. Uses atlas_engine.verbatim_only so transcript/survey
    `verbatim_turn` rows and notes `notable_quote_verbatim` rows both count as
    Verbatim Quotes, ensuring Verbatim + Paraphrased (+ Observations) == Theme Matches.
    """
    has_obs = bool(include_observations) or (
        quotes is not None
        and len(quotes) > 0
        and "evidence_type" in quotes.columns
        and (quotes["evidence_type"].astype(str) == "observation").any()
    )
    cols = GROUP_TABLE_COLUMNS_WITH_OBS if has_obs else GROUP_TABLE_COLUMNS
    rows = []
    for _, r in freq.iterrows():
        dq = quotes[quotes["domain_id"].astype(str) == str(r["domain_id"])] if len(quotes) else quotes
        evidence = dq["evidence_type"].astype(str) if (len(dq) and "evidence_type" in dq.columns) else pd.Series(dtype=str)
        n_verbatim = int(len(verbatim_rows(dq))) if len(dq) else 0
        n_paraphrase = int((evidence == "key_point_paraphrase").sum()) if len(dq) else 0
        n_obs = int((evidence == "observation").sum()) if len(dq) else 0
        g_rep = int(r["documents_reporting"])
        row = {
            "Theme": str(r["domain_name"]),
            "Focus Groups": f"{g_rep} of {int(total_groups)}",
            "Theme Matches": int(len(dq)),
            "Verbatim Quotes": n_verbatim,
            "Paraphrased Key Points": n_paraphrase,
            "_groups_reporting": g_rep,
            "_domain_id": str(r["domain_id"]),
        }
        if has_obs:
            row["Note-Taker Observations"] = n_obs
        rows.append(row)
    df = pd.DataFrame(rows, columns=[*cols, "_groups_reporting", "_domain_id"])
    if len(df):
        df = df.sort_values(
            ["Theme Matches", "_groups_reporting", "Theme"],
            ascending=[False, False, True],
            kind="mergesort",
        ).reset_index(drop=True)
    return df


def build_group_theme_matrix(freq, quotes, file_hashes, *, theme_order=None):
    """
    One row per (theme, focus-group file): uniform presence/entry tile state across
    all focus groups (never mixing voice counts with checkmarks).

    Keyed strictly by `domain_id` so two valid themes that share a display name
    never overwrite each other; duplicate display names are disambiguated in
    `theme_label` while unique display names stay verbatim.
    """
    source_ids = sorted(str(s) for s in file_hashes)
    labels = group_labels_for(source_ids)
    freq_by_id = {str(r["domain_id"]): r for _, r in freq.iterrows()}
    all_ids = [str(r["domain_id"]) for _, r in freq.iterrows()]
    if theme_order is not None:
        order_list = [str(x) for x in theme_order]
        if all(x in freq_by_id for x in order_list):
            ordered_ids = order_list
        else:
            # Backward compatibility if a caller passes display names in theme_order.
            name_to_ids: dict[str, list[str]] = {}
            for _, r in freq.iterrows():
                name_to_ids.setdefault(str(r["domain_name"]), []).append(str(r["domain_id"]))
            ordered_ids = []
            seen_ids = set()
            for x in order_list:
                for did in name_to_ids.get(x, []):
                    if did not in seen_ids:
                        ordered_ids.append(did)
                        seen_ids.add(did)
            for did in all_ids:
                if did not in seen_ids:
                    ordered_ids.append(did)
                    seen_ids.add(did)
    else:
        ordered_ids = all_ids

    name_counts: dict[str, int] = {}
    for did in ordered_ids:
        r = freq_by_id.get(did)
        if r is not None:
            dn = str(r["domain_name"])
            name_counts[dn] = name_counts.get(dn, 0) + 1

    rows = []
    for did in ordered_ids:
        r = freq_by_id.get(did)
        if r is None:
            continue
        name = str(r["domain_name"])
        theme_label = f"{name} ({did})" if name_counts.get(name, 0) > 1 else name
        dq = quotes[quotes["domain_id"].astype(str) == did] if len(quotes) else quotes
        if "documents_reporting" in r and pd.notna(r["documents_reporting"]):
            g_rep = int(r["documents_reporting"])
        else:
            g_rep = sum(
                1 for sid in source_ids
                if len(dq) and len(dq[dq["source_id"].astype(str) == sid]) > 0
            )
        for sid in source_ids:
            gq = dq[dq["source_id"].astype(str) == sid] if len(dq) else dq
            n = int(len(gq))
            rows.append({
                "domain_id": did,
                "domain_name": name,
                "theme_label": theme_label,
                "source_id": sid,
                "group_label": labels[sid],
                "present": n > 0,
                "matching_entries": n,
                "groups_reporting": g_rep,
                "presence_label": "✓" if n > 0 else "—",
                "entries_label": str(n) if n > 0 else "—",
                "tile_state": "present" if n > 0 else "none",
            })
    return pd.DataFrame(rows, columns=[
        "domain_id", "domain_name", "theme_label", "source_id", "group_label", "present",
        "matching_entries", "groups_reporting", "presence_label", "entries_label", "tile_state",
    ])


def describe_group_prevalence_chart(group_df, total_groups):
    """
    Plain-text summary of Group Mode theme frequency (Vega-Lite description and
    st.html summary). Reports themes by match volume and groups reporting; never
    emits partial participant-voice counts.
    """
    if group_df is None or len(group_df) == 0:
        return "No themes selected."
    k = len(group_df)
    themes_w = "theme" if k == 1 else "themes"
    total = int(total_groups)
    if total <= 0:
        return f"Horizontal bar chart with 0 focus groups across {k} {themes_w}."
    groups = "focus group" if total == 1 else "focus groups"

    def count(value):
        number = pd.to_numeric(value, errors="coerce")
        return int(number) if pd.notna(number) and math.isfinite(float(number)) else 0

    g_col = "_groups_reporting" if "_groups_reporting" in group_df.columns else "Groups Reporting"
    m_col = "Theme Matches" if "Theme Matches" in group_df.columns else "Matching Entries"
    n_col = "Theme" if "Theme" in group_df.columns else "Domain"
    rows = group_df.assign(
        _name=group_df[n_col].astype(str),
        _groups=group_df[g_col].map(count),
        _matches=group_df[m_col].map(count),
    ).sort_values(["_matches", "_groups", "_name"], ascending=[False, False, True], kind="mergesort")
    matched = rows[rows["_groups"] > 0]
    lead = f"Horizontal bar chart of matched notes entries across {total} {groups}."
    if matched.empty:
        return f"{lead} No group reported any of the {k} active {themes_w}."
    listed = []
    for _, r in matched.head(3).iterrows():
        m_w = "match" if r["_matches"] == 1 else "matches"
        listed.append(f"{r['_name']}: {r['_matches']} {m_w} ({r['_groups']} of {total} {groups})")
    text = f"{lead} Most frequently matched in notes: {'; '.join(listed)}."
    if len(matched) > 3:
        text += f" Other matched themes not listed: {len(matched) - 3}."
    if len(matched) < k:
        text += f" Themes reported by no group: {k - len(matched)} of {k}."
    return text


def describe_group_matrix_chart(matrix_df, total_groups):
    """Plain-text summary of the Group x Theme presence grid."""
    if matrix_df is None or len(matrix_df) == 0:
        return "No themes selected."
    k = matrix_df["domain_id"].astype(str).nunique()
    themes_w = "theme" if k == 1 else "themes"
    total = int(total_groups)
    groups = "focus group" if total == 1 else "focus groups"
    present = matrix_df["present"].astype(bool)
    per_group = []
    for label in sorted(matrix_df["group_label"].astype(str).unique()):
        n = int(present[matrix_df["group_label"].astype(str) == label].sum())
        per_group.append(f"{label}: {n} of {k}")
    return (f"Focus-group grid of {k} active {themes_w} across {total} {groups}. "
            f"{int(present.sum())} of {len(matrix_df)} theme-group tiles have at least one match. "
            f"Themes reported per group: {'; '.join(per_group)}.")


def group_volume_chart(group_df, total_groups):
    """Horizontal bar chart of Theme Matches in notes, labelled `<matches> (<g>/<G>)`."""
    total = int(total_groups)
    g_col = "_groups_reporting" if "_groups_reporting" in group_df.columns else "Groups Reporting"
    m_col = "Theme Matches" if "Theme Matches" in group_df.columns else "Matching Entries"
    n_col = "Theme" if "Theme" in group_df.columns else "Domain"
    raw_names = [str(v) for v in group_df[n_col].tolist()]
    if "_domain_id" in group_df.columns:
        row_ids = [str(v) for v in group_df["_domain_id"].tolist()]
    else:
        row_ids = [f"__row_{i}" for i in range(len(group_df))]
    name_counts: dict[str, int] = {}
    for rn in raw_names:
        name_counts[rn] = name_counts.get(rn, 0) + 1
    if "_domain_id" in group_df.columns:
        disp_names = [
            f"{rn} ({did})" if name_counts.get(rn, 0) > 1 else rn
            for rn, did in zip(raw_names, row_ids)
        ]
    else:
        disp_names = raw_names
    id_to_label = dict(zip(row_ids, disp_names))
    label_expr = f"({json.dumps(id_to_label)})[datum.value]"
    data = pd.DataFrame({
        "domain_id": row_ids,
        "theme_name": disp_names,
        "theme_matches": group_df[m_col].astype(int).tolist(),
        "groups_reporting": group_df[g_col].astype(int).tolist(),
        "bar_label": [f"{int(m)} ({int(g)}/{total})" for m, g in zip(group_df[m_col], group_df[g_col])],
    })
    max_m = max(int(data["theme_matches"].max()) if len(data) else 1, 1)
    y_order = list(row_ids)
    x = alt.X(
        "theme_matches:Q",
        title="Matched Notes Entries (note volume — not participant headcount)",
        scale=alt.Scale(domain=[0, max(max_m + max(1, int(max_m * 0.22)), 2)]),
        axis=alt.Axis(tickMinStep=1, format="d"),
    )
    bars = alt.Chart(data).mark_bar(color=NAVY, cornerRadiusEnd=3).encode(
        x=x,
        y=alt.Y("domain_id:N", sort=y_order, title=None, axis=alt.Axis(labelLimit=360, labelExpr=label_expr)),
        tooltip=[
            alt.Tooltip("theme_name:N", title="Theme"),
            alt.Tooltip("domain_id:N", title="Theme ID"),
            alt.Tooltip("theme_matches:Q", title="Theme matches (notes entries)", format="d"),
            alt.Tooltip("groups_reporting:Q", title=f"Focus groups reporting (of {total})", format="d"),
        ],
    )
    labels = alt.Chart(data).mark_text(align="left", dx=6, fontSize=13, fontWeight="bold", color="#0F172A").encode(
        x="theme_matches:Q",
        y=alt.Y("domain_id:N", sort=y_order),
        text="bar_label:N",
    )
    return bars + labels


def group_matrix_chart(matrix_df, total_groups, *, show_entries=False):
    """
    Uniform Group x Theme grid: every focus group uses the exact same tile colors
    and encoding (`✓` / `—` or matching entry counts), plus a rightmost `Groups`
    summary column (`g/G`).

    Y coordinates are encoded strictly by `domain_id` (rendered with human-readable
    axis labels via `labelExpr`) so duplicate or colliding display names never merge
    or overwrite rows.
    """
    states = list(GROUP_TILE_COLOURS)
    groups_sorted = sorted(matrix_df["group_label"].astype(str).unique())
    y_col = "theme_label" if "theme_label" in matrix_df.columns else "domain_name"
    y_order = list(dict.fromkeys(matrix_df["domain_id"].astype(str)))
    id_to_label: dict[str, str] = {}
    for _, r in matrix_df.iterrows():
        did = str(r["domain_id"])
        if did not in id_to_label:
            id_to_label[did] = str(r[y_col])
    label_expr = f"({json.dumps(id_to_label)})[datum.value]"
    label_field = "entries_label" if show_entries else "presence_label"

    grid_rows = matrix_df.copy()
    grid_rows["domain_id"] = grid_rows["domain_id"].astype(str)
    grid_rows["theme_display"] = grid_rows[y_col].astype(str)
    grid_rows["col_label"] = grid_rows["group_label"].astype(str)
    grid_rows["display_text"] = grid_rows[label_field].astype(str)

    # Append a rightmost "Groups" summary column (g/G) keyed strictly by domain_id.
    summary_rows = []
    seen = set()
    for _, r in matrix_df.iterrows():
        did = str(r["domain_id"])
        if did in seen:
            continue
        seen.add(did)
        dn = str(r["domain_name"])
        disp = str(r[y_col])
        g_rep = int(r["groups_reporting"])
        summary_rows.append({
            "domain_id": did,
            "domain_name": dn,
            "theme_label": disp,
            "theme_display": disp,
            "source_id": "__groups_summary__",
            "group_label": "Groups",
            "col_label": "Groups",
            "present": g_rep > 0,
            "matching_entries": int(matrix_df.loc[matrix_df["domain_id"].astype(str) == did, "matching_entries"].sum()),
            "groups_reporting": g_rep,
            "presence_label": f"{g_rep}/{int(total_groups)}",
            "entries_label": f"{g_rep}/{int(total_groups)}",
            "display_text": f"{g_rep}/{int(total_groups)}",
            "tile_state": "none",
        })
    combined = pd.concat([grid_rows, pd.DataFrame(summary_rows)], ignore_index=True)
    col_order = [*groups_sorted, "Groups"]

    x_axis = (
        alt.Axis(labelAngle=-25, labelAlign="left", labelBaseline="bottom", labelLimit=160, labelOverlap=False, orient="top")
        if len(col_order) > 4
        else alt.Axis(labelAngle=0, labelAlign="center", labelLimit=170, labelOverlap=False, orient="top")
    )
    base = alt.Chart(combined).encode(
        x=alt.X("col_label:N", title=None, sort=col_order, axis=x_axis),
        y=alt.Y("domain_id:N", title=None, sort=y_order,
                axis=alt.Axis(labelLimit=360, labelExpr=label_expr)),
    )
    tiles = base.mark_rect(stroke="#FFFFFF", strokeWidth=2, cornerRadius=3).encode(
        color=alt.Color("tile_state:N", legend=None,
                        scale=alt.Scale(domain=states, range=[GROUP_TILE_COLOURS[s][0] for s in states])),
        tooltip=[
            alt.Tooltip("theme_display:N", title="Theme"),
            alt.Tooltip("domain_id:N", title="Theme ID"),
            alt.Tooltip("col_label:N", title="Column"),
            alt.Tooltip("matching_entries:Q", title="Matching entries", format="d"),
        ],
    )
    text = base.mark_text(fontWeight="bold", fontSize=14).encode(
        text="display_text:N",
        color=alt.Color("tile_state:N", legend=None,
                        scale=alt.Scale(domain=states, range=[GROUP_TILE_COLOURS[s][1] for s in states])),
    )
    return (tiles + text).resolve_scale(color="independent")


def light_chart_surface(chart):
    """Coordinated light chart surface with screen-share-readable typography."""
    return (chart.configure(background="#FFFFFF")
            .configure_view(fill="#FFFFFF", stroke="#64748B")
            .configure_axis(labelColor="#1E293B", titleColor="#0F172A", domainColor="#64748B",
                            tickColor="#64748B", gridColor="#E2E8F0",
                            labelFontSize=13, titleFontSize=14, titlePadding=10)
            .configure_title(color="#0F172A", fontSize=15)
            .configure_legend(labelColor="#1E293B", titleColor="#0F172A", labelFontSize=13, titleFontSize=13))


def evidence_badge_html(evidence_type):
    """High-contrast badge naming an entry's source column (escaped, never Markdown)."""
    fg, bg, label = EVIDENCE_BADGE_STYLES.get(str(evidence_type), EVIDENCE_BADGE_FALLBACK)
    border = "#94A3B8" if bg == "#F1F5F9" else bg
    return (f'<span class="atlas-evidence-badge" style="display:inline-block;font-size:0.8rem;font-weight:700;'
            f'padding:0.12rem 0.55rem;border-radius:4px;margin-right:0.45rem;color:{fg};background-color:{bg};'
            f'border:1px solid {border};">{html.escape(label)}</span>')


@st.cache_data(show_spinner=False)
def read_table_sheets(name, payload):
    """Sheet names of an uploaded .xlsx file (empty list for .csv)."""
    if os.path.splitext(str(name))[1].lower() != ".xlsx":
        return []
    with tempfile.TemporaryDirectory(prefix="atlas_sheets_") as tmp:
        path = Path(tmp) / safe_upload_name(name, set())
        path.write_bytes(payload)
        return UniversalTranscriptParser.list_excel_sheets(str(path))


@st.cache_data(show_spinner=False)
def read_table_columns(name, payload, sheet_name=0):
    """Columns and rows of an uploaded table exactly as the parser reads them."""
    ext = os.path.splitext(name)[1].lower()
    with tempfile.TemporaryDirectory(prefix="atlas_preview_") as tmp:
        path = Path(tmp) / safe_upload_name(name, set())  # parser errors name the user's file
        path.write_bytes(payload)
        if ext == ".csv":
            frame, _ = UniversalTranscriptParser()._read_csv(str(path))
        else:
            frame = pd.read_excel(
                path, sheet_name=sheet_name, dtype=str, keep_default_na=False, na_filter=False
            )
    frame.columns = [str(c) for c in frame.columns]
    return frame


@st.cache_data(show_spinner=False)
def detect_structured_notes(name, payload):
    """Whether a .docx payload holds a structured notes table; unreadable files are not notes."""
    if os.path.splitext(str(name))[1].lower() != ".docx":
        return False
    with tempfile.TemporaryDirectory(prefix="atlas_detect_") as tmp:
        path = Path(tmp) / "probe.docx"
        path.write_bytes(payload)
        try:
            return UniversalTranscriptParser.detect_docx_structure(str(path)) == "structured_notes"
        except UPLOAD_READ_ERRORS:
            return False


@st.cache_data(show_spinner=False)
def analyze_corpus(codebook_bytes, inputs, tabular_items, facilitators, prompt_patterns, notes_evidence=None,
                   group_by_source=False, spelling_tolerance=False):
    """
    Run UniversalTranscriptParser -> AtlasEngine on byte copies of the inputs.
    """
    keys = [upload_path_key(rel) for rel, _ in inputs]
    if len(set(keys)) != len(keys):
        clashing = sorted({rel for rel, _ in inputs if keys.count(upload_path_key(rel)) > 1})
        raise ValueError(f"Input paths name the same file on case-insensitive filesystems: {clashing}")
    with tempfile.TemporaryDirectory(prefix="atlas_run_") as tmp:
        root = Path(tmp) / "corpus"
        paths = []
        for rel, payload in inputs:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            paths.append(str(target))
        codebook_path = Path(tmp) / "codebook.yaml"
        codebook_path.write_bytes(codebook_bytes)

        engine = AtlasEngine(str(codebook_path))
        results = engine.process_corpus(
            paths,
            facilitator_names=list(facilitators) or None,
            interviewer_prompt_patterns=list(prompt_patterns) or None,
            root_dir=str(root),
            tabular_options=dict(tabular_items) if tabular_items else None,
            include_evidence_types=list(notes_evidence) if notes_evidence else None,
            notes_unit_level="group",
            group_by_source=group_by_source,
            spelling_tolerance=bool(spelling_tolerance),
        )

        export_dir = Path(tmp) / "export"
        with contextlib.redirect_stdout(io.StringIO()):
            engine.export_results(results, str(export_dir))
        integrity_ok, integrity_problems = AtlasEngine.verify_workbook_integrity(
            str(export_dir / "actuarial_parameter_matrix.xlsx"),
            str(export_dir / "provenance_manifest.json"),
        )
        exports = {
            name: (export_dir / name).read_bytes()
            for name in ("actuarial_parameter_matrix.xlsx", "provenance_manifest.json",
                         "verbatim_quotes_inventory.csv", CODED_EVIDENCE_CSV)
            if (export_dir / name).is_file()
        }

    results["exports"] = exports
    results["integrity_ok"] = bool(integrity_ok)
    results["integrity_problems"] = list(integrity_problems)
    results["compiled_domains"] = list(engine.domains)
    results["false_alarm_audit_df"] = audit_false_alarm_risks(
        results["quotes_df"],
        engine.domains,
        typo_matches_df=results.get("typo_matches_df"),
    )
    return results


@st.cache_data(show_spinner=False)
def run_topic_discovery(turn_records, n_topics, method="nmf"):
    return discover_topics(turn_records, n_topics=n_topics, method=method)


def dedupe_terms(terms):
    seen, ordered = set(), []
    for term in terms or []:
        key = str(term).strip().lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(str(term).strip())
    return ordered


def esc(value):
    return html.escape("" if value is None else str(value))


def highlighted_quote(text, start, end):
    text = str(text)
    try:
        start, end = int(start), int(end)
    except (TypeError, ValueError):
        return esc(text)
    if not (0 <= start < end <= len(text)):
        return esc(text)
    return f"{esc(text[:start])}<mark>{esc(text[start:end])}</mark>{esc(text[end:])}"


def format_codebook_summary(primary_label, extra_codebooks, n_domains):
    """Concise, non-redundant theme-set summary for headers."""
    unit = "theme" if int(n_domains) == 1 else "themes"
    if extra_codebooks:
        return f"{primary_label} (+{len(extra_codebooks)} stacked · {int(n_domains)} {unit})"
    if f"{int(n_domains)} {unit}" in str(primary_label):
        return str(primary_label)
    return f"{primary_label} ({int(n_domains)} {unit})"


def _update_snapshot_codebook(label, yaml_bytes):
    st.session_state.session_override_label = label
    st.session_state.session_override_bytes = yaml_bytes
    snap = st.session_state.get("run_snapshot")
    if isinstance(snap, dict):
        updated = dict(snap)
        updated["codebook_bytes"] = yaml_bytes
        updated["primary_codebook_label"] = label
        updated["is_custom_or_stacked"] = True
        updated["codebook_sha256"] = hashlib.sha256(yaml_bytes).hexdigest()
        st.session_state.run_snapshot = updated
        st.session_state.run_error = None


def apply_discovered_codebook(label, yaml_bytes):
    _update_snapshot_codebook(label, yaml_bytes)


def reset_session_override():
    st.session_state.session_override_label = None
    st.session_state.session_override_bytes = None
    snap = st.session_state.get("run_snapshot")
    if isinstance(snap, dict) and snap.get("base_codebook_bytes") is not None:
        restored = dict(snap)
        restored["codebook_bytes"] = snap["base_codebook_bytes"]
        restored["primary_codebook_label"] = snap["base_primary_codebook_label"]
        restored["is_custom_or_stacked"] = snap["base_is_custom_or_stacked"]
        restored["codebook_sha256"] = snap["base_codebook_sha256"]
        st.session_state.run_snapshot = restored


def esc_inline(value):
    collapsed = re.sub(r"[\r\n\x0b\x0c\x85\u2028\u2029]+", " ", "" if value is None else str(value))
    return html.escape(collapsed, quote=True)


def add_theme_to_active_codebook(current_bytes, topic_choices):
    if not topic_choices:
        return
    picked_label = st.session_state.get("add_topic_select")
    topic = topic_choices.get(picked_label) or next(iter(topic_choices.values()))
    custom_name = str(st.session_state.get("add_topic_name", "") or "").strip()
    match_mode = "exact" if st.session_state.get("add_topic_exact", True) else "prefix"
    current_dict = yaml.safe_load(current_bytes) or {}
    updated_dict = append_topic_to_codebook(
        current_dict,
        topic,
        domain_name=custom_name or None,
        match_mode=match_mode,
    )
    new_domain = updated_dict["domains"][-1]
    updated_bytes = yaml.safe_dump(updated_dict, allow_unicode=True, sort_keys=False).encode("utf-8")
    clean_name = re.sub(r"[\r\n]+", " ", str(new_domain["name"])).strip()
    label = f"Session edit: +{clean_name} ({len(updated_dict['domains'])} themes)"
    _update_snapshot_codebook(label, updated_bytes)
    st.session_state.add_topic_name = ""


def apply_tightened_codebook(current_bytes, domain_choice_map, rendered_fix_label, ext_key, set_exact_mode):
    if not domain_choice_map:
        return
    live_label = st.session_state.get("spotcheck_fix_domain")
    if live_label not in domain_choice_map:
        live_label = rendered_fix_label if rendered_fix_label in domain_choice_map else next(iter(domain_choice_map))
    domain_id, domain_name = domain_choice_map[live_label]

    words = []
    if not set_exact_mode:
        if live_label != rendered_fix_label or not ext_key:
            return
        words = [str(w).strip() for w in (st.session_state.get(ext_key) or []) if str(w).strip()]
        if not words:
            return

    current_dict = yaml.safe_load(current_bytes) or {}
    updated_dict = tighten_codebook_domain(
        current_dict,
        domain_id,
        add_exclude_terms=words,
        set_exact_mode=bool(set_exact_mode),
    )
    updated_bytes = yaml.safe_dump(updated_dict, allow_unicode=True, sort_keys=False).encode("utf-8")
    action = "exact matching" if set_exact_mode and not words else "excluded words"
    clean_name = re.sub(r"[\r\n]+", " ", str(domain_name)).strip()
    label = f"Session edit: {clean_name} ({action}, {len(updated_dict['domains'])} themes)"
    _update_snapshot_codebook(label, updated_bytes)


def spotcheck_priority_label(risk_level, flag_codes=""):
    codes = str(flag_codes or "")
    if "spelling_tolerance" in codes:
        return SPOTCHECK_PRIORITY_SPELLING
    if str(risk_level or "") == "High":
        return SPOTCHECK_PRIORITY_PARTIAL
    return SPOTCHECK_PRIORITY_CONTEXT


def risk_badge_html(risk_level, flag_codes=""):
    label = spotcheck_priority_label(risk_level, flag_codes)
    cls = "risk-badge-high" if str(risk_level or "") == "High" else "risk-badge-medium"
    return f'<span class="risk-badge {cls}">{html.escape(label)}</span>'


def _neutralize_relative_md_links(text):
    """Turn relative .md / #anchor Markdown links into bold text for in-app viewing,
    while preserving external scheme links and fenced code blocks."""
    link_pat = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
    scheme_pat = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)

    def _replace(match):
        label, target = match.group(1), match.group(2).strip()
        if scheme_pat.match(target):
            return match.group(0)
        return f"**{label}**"

    out_lines = []
    in_fence = False
    for line in str(text).splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        out_lines.append(line if in_fence else link_pat.sub(_replace, line))
    return "\n".join(out_lines)


def split_markdown_for_app(md_text, base_dir):
    """Split a Markdown guide into ('markdown', text) and ('image', Path, alt_text) blocks
    for formatted in-app rendering. Local images are strictly confined inside base_dir."""
    root = Path(base_dir).resolve()
    img_line_pat = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
    blocks = []
    buf = []
    in_fence = False

    def _flush():
        chunk = "\n".join(buf).strip()
        if chunk:
            blocks.append(("markdown", _neutralize_relative_md_links(chunk)))
        buf.clear()

    for line in str(md_text).splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            buf.append(line)
            continue
        if not in_fence:
            m = img_line_pat.match(line.strip())
            if m:
                alt_text, rel_target = m.group(1).strip(), m.group(2).strip()
                candidate = (root / rel_target).resolve()
                _flush()
                if (
                    candidate.is_relative_to(root)
                    and candidate.is_file()
                    and candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}
                ):
                    blocks.append(("image", candidate, alt_text))
                continue
        buf.append(line)
    _flush()
    return blocks


def _set_picture_alt_text(run, alt_text):
    """Attach descriptive alt text to an inline Word picture's wp:docPr element."""
    if not alt_text:
        return
    for elem in run._r.iter():
        if elem.tag.endswith("}docPr"):
            elem.set("descr", str(alt_text))
            elem.set("title", str(alt_text)[:120])
            break


def _png_pixel_size(path):
    """Read (width, height) from a PNG IHDR header without extra dependencies; None if not PNG."""
    raw = Path(path).read_bytes()[:24]
    if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    return None


def _add_inline_markdown_runs(paragraph, text, *, base_color=None, base_bold=False, base_italic=False, font_size=10.5):
    """Parse inline Markdown (**bold**, *italic*, `code`, [links](url)) recursively into styled Word runs."""
    token_pat = re.compile(
        r"`([^`]+)`"
        r"|\*\*\*(.+?)\*\*\*"
        r"|\*\*(.+?)\*\*"
        r"|(?<!\*)\*([^*\n]+)\*(?!\*)"
        r"|\[([^\]]+)\]\(([^)]+)\)"
    )
    scheme_pat = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
    default_rgb = base_color or RGBColor(0x0F, 0x17, 0x2A)
    navy_rgb = RGBColor(0x1E, 0x3A, 0x8A)
    slate_rgb = RGBColor(0x47, 0x55, 0x69)

    def _emit(chunk, *, bold=False, italic=False, code=False, color=None):
        if not chunk:
            return
        run = paragraph.add_run(chunk)
        run.bold = bool(base_bold or bold)
        run.italic = bool(base_italic or italic)
        run.font.size = Pt(font_size - 1.0 if code else font_size)
        run.font.name = "Consolas" if code else "Calibri"
        run.font.color.rgb = color or (navy_rgb if code else default_rgb)

    pos = 0
    src = str(text)
    for m in token_pat.finditer(src):
        if m.start() > pos:
            _emit(src[pos:m.start()])
        if m.group(1) is not None:
            _emit(m.group(1), code=True)
        elif m.group(2) is not None:
            _add_inline_markdown_runs(
                paragraph, m.group(2), base_color=default_rgb, base_bold=True, base_italic=True, font_size=font_size,
            )
        elif m.group(3) is not None:
            _add_inline_markdown_runs(
                paragraph, m.group(3), base_color=default_rgb, base_bold=True, base_italic=base_italic, font_size=font_size,
            )
        elif m.group(4) is not None:
            _add_inline_markdown_runs(
                paragraph, m.group(4), base_color=default_rgb, base_bold=base_bold, base_italic=True, font_size=font_size,
            )
        elif m.group(5) is not None:
            label, target = m.group(5), m.group(6).strip()
            if scheme_pat.match(target):
                _emit(label, bold=True, color=navy_rgb)
                _emit(f" ({target})", color=slate_rgb)
            else:
                _emit(label, bold=True)
        pos = m.end()
    if pos < len(src):
        _emit(src[pos:])


def markdown_to_docx_bytes(md_text, base_dir):
    """Convert a Markdown reference guide into a formatted, accessible Word (.docx)
    document in memory (headings, tables, lists, callouts, code blocks, and embedded figures)."""
    root = Path(base_dir).resolve()
    document = docx.Document()
    for section in document.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.85)
        section.right_margin = Inches(0.85)

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.15

    navy_rgb = RGBColor(0x1E, 0x3A, 0x8A)
    teal_rgb = RGBColor(0x0F, 0x76, 0x6E)
    slate_rgb = RGBColor(0x33, 0x41, 0x55)
    white_rgb = RGBColor(0xFF, 0xFF, 0xFF)

    def _shade_cell(cell, fill_hex):
        tc_pr = cell._tc.get_or_add_tcPr()
        tc_pr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>'))

    def _set_cell_margins(cell, top=80, bottom=80, left=120, right=120):
        tc_pr = cell._tc.get_or_add_tcPr()
        tc_mar = OxmlElement("w:tcMar")
        for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
            node = OxmlElement(f"w:{side}")
            node.set(qn("w:w"), str(val))
            node.set(qn("w:type"), "dxa")
            tc_mar.append(node)
        tc_pr.append(tc_mar)

    def _set_table_borders(table, color_hex="CBD5E1"):
        tbl_pr = table._tbl.tblPr
        tbl_pr.append(parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
            f'<w:left w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
            f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
            f'<w:right w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
            f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
            f'<w:insideV w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>'
            f"</w:tblBorders>"
        ))

    def _add_p_border(paragraph, side, color_hex, sz="12"):
        p_pr = paragraph._p.get_or_add_pPr()
        p_pr.append(parse_xml(
            f'<w:pBdr {nsdecls("w")}><w:{side} w:val="single" w:sz="{sz}" w:space="6" w:color="{color_hex}"/></w:pBdr>'
        ))

    def _split_table_row(line):
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [c.strip() for c in stripped.split("|")]

    def _is_table_sep(line):
        cells = _split_table_row(line)
        return bool(cells) and all(re.match(r"^:?-{2,}:?$", c) for c in cells)

    lines = str(md_text).splitlines()
    i = 0
    n = len(lines)
    heading_pat = re.compile(r"^(#{1,6})\s+(.*)$")
    img_pat = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
    checkbox_pat = re.compile(r"^(\s*)[-*]\s+\[([ xX])\]\s+(.*)$")
    bullet_pat = re.compile(r"^(\s*)[-*]\s+(.*)$")
    num_pat = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
    in_landscape = False

    def _ensure_portrait():
        nonlocal in_landscape
        if in_landscape:
            sec_back = document.add_section(WD_SECTION.NEW_PAGE)
            sec_back.orientation = WD_ORIENT.PORTRAIT
            sec_back.page_width = Inches(8.5)
            sec_back.page_height = Inches(11.0)
            sec_back.top_margin = Inches(0.8)
            sec_back.bottom_margin = Inches(0.8)
            sec_back.left_margin = Inches(0.85)
            sec_back.right_margin = Inches(0.85)
            in_landscape = False

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            i += 1
            continue

        # Standalone image embed: place wide figures on a US Letter Landscape page
        # (10.0" x 6.85" max image box) so 22 CSS-px labels render at >= 11.0 pt on page.
        # Handled before _ensure_portrait() so consecutive figures never insert an empty portrait page.
        im = img_pat.match(stripped)
        if im:
            alt_text, rel_target = im.group(1).strip(), im.group(2).strip()
            candidate = (root / rel_target).resolve()
            if (
                candidate.is_relative_to(root)
                and candidate.is_file()
                and candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}
            ):
                caption_text = None
                if i + 1 < n and lines[i + 1].strip().startswith("*") and not lines[i + 1].strip().startswith("**"):
                    cap_parts = []
                    j = i + 1
                    while (
                        j < n
                        and lines[j].strip()
                        and not lines[j].strip().startswith(("#", "|", ">", "```", "!["))
                    ):
                        cap_parts.append(lines[j].strip())
                        j += 1
                        if cap_parts[-1].endswith("*"):
                            break
                    if cap_parts and cap_parts[-1].endswith("*"):
                        caption_text = " ".join(cap_parts)
                        i = j - 1

                if document.paragraphs or document.tables:
                    sec_fig = document.add_section(WD_SECTION.NEW_PAGE)
                else:
                    sec_fig = document.sections[0]
                sec_fig.orientation = WD_ORIENT.LANDSCAPE
                sec_fig.page_width = Inches(11.0)
                sec_fig.page_height = Inches(8.5)
                sec_fig.top_margin = Inches(0.45)
                sec_fig.bottom_margin = Inches(0.45)
                sec_fig.left_margin = Inches(0.5)
                sec_fig.right_margin = Inches(0.5)
                in_landscape = True

                dims = _png_pixel_size(candidate)
                if dims and dims[0] > 0 and dims[1] > 0:
                    disp_w = dims[0] * min(10.0 / dims[0], 6.85 / dims[1])
                else:
                    disp_w = 9.5

                p = document.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.keep_with_next = True
                run = p.add_run()
                run.add_picture(str(candidate), width=Inches(disp_w))
                _set_picture_alt_text(run, alt_text)

                cap_source = caption_text or alt_text
                if cap_source:
                    cap = document.add_paragraph()
                    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    cap.paragraph_format.space_before = Pt(0)
                    cap.paragraph_format.space_after = Pt(4)
                    _add_inline_markdown_runs(
                        cap,
                        cap_source,
                        base_color=slate_rgb,
                        base_italic=caption_text is None,
                        font_size=10.0,
                    )
            i += 1
            continue

        _ensure_portrait()

        # Fenced code block
        if stripped.startswith("```"):
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1
            box = document.add_table(rows=1, cols=1)
            box.autofit = True
            _set_table_borders(box, "CBD5E1")
            cell = box.cell(0, 0)
            _shade_cell(cell, "F1F5F9")
            _set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.05
            run = p.add_run("\n".join(code_lines))
            run.font.name = "Consolas"
            run.font.size = Pt(8.5)
            run.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
            spacer = document.add_paragraph()
            spacer.paragraph_format.space_before = Pt(0)
            spacer.paragraph_format.space_after = Pt(4)
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$", stripped):
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(6)
            _add_p_border(p, "bottom", "CBD5E1", sz="6")
            i += 1
            continue

        # Heading
        hm = heading_pat.match(stripped)
        if hm:
            lvl = min(len(hm.group(1)), 4)
            p = document.add_heading(level=min(lvl, 3))
            p.clear()
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.space_before = Pt(14 if lvl <= 2 else 9)
            p.paragraph_format.space_after = Pt(4)
            size = {1: 18.0, 2: 14.0, 3: 11.5, 4: 10.5}[lvl]
            color = {1: navy_rgb, 2: navy_rgb, 3: teal_rgb, 4: slate_rgb}[lvl]
            _add_inline_markdown_runs(p, hm.group(2).strip(), base_color=color, base_bold=True, font_size=size)
            i += 1
            continue

        # Markdown table
        if "|" in stripped and i + 1 < n and _is_table_sep(lines[i + 1]):
            headers = _split_table_row(lines[i])
            i += 2
            rows = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                row_cells = _split_table_row(lines[i])
                if len(row_cells) < len(headers):
                    row_cells.extend([""] * (len(headers) - len(row_cells)))
                rows.append(row_cells[: len(headers)])
                i += 1
            tbl = document.add_table(rows=1 + len(rows), cols=len(headers))
            tbl.autofit = True
            _set_table_borders(tbl)
            hdr_row = tbl.rows[0]
            hdr_tr_pr = hdr_row._tr.get_or_add_trPr()
            hdr_tr_pr.append(OxmlElement("w:tblHeader"))
            hdr_tr_pr.append(OxmlElement("w:cantSplit"))
            for col_idx, h_text in enumerate(headers):
                cell = hdr_row.cells[col_idx]
                _shade_cell(cell, "1E3A8A")
                _set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
                p = cell.paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                _add_inline_markdown_runs(p, h_text, base_color=white_rgb, base_bold=True, font_size=9.5)
            for r_idx, r_cells in enumerate(rows):
                row = tbl.rows[r_idx + 1]
                row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
                fill = "F8FAFC" if r_idx % 2 == 1 else "FFFFFF"
                for col_idx, val in enumerate(r_cells):
                    cell = row.cells[col_idx]
                    _shade_cell(cell, fill)
                    _set_cell_margins(cell, top=70, bottom=70, left=100, right=100)
                    p = cell.paragraphs[0]
                    p.paragraph_format.space_after = Pt(0)
                    _add_inline_markdown_runs(p, val, font_size=9.5)
            spacer = document.add_paragraph()
            spacer.paragraph_format.space_before = Pt(0)
            spacer.paragraph_format.space_after = Pt(4)
            continue

        # Blockquote callout
        if stripped.startswith(">"):
            quote_parts = []
            while i < n and lines[i].strip().startswith(">"):
                quote_parts.append(re.sub(r"^>\s?", "", lines[i].strip()))
                i += 1
            p = document.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(6)
            _add_p_border(p, "left", "0F766E", sz="18")
            p._p.get_or_add_pPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="F8FAFC"/>'))
            _add_inline_markdown_runs(p, " ".join(part for part in quote_parts if part), base_color=slate_rgb, font_size=10.0)
            continue

        # Checklist / bullet / numbered item (with indented wrapped continuations)
        cbm = checkbox_pat.match(raw)
        bm = None if cbm else bullet_pat.match(raw)
        nm = None if (cbm or bm) else num_pat.match(raw)
        if cbm or bm or nm:
            if cbm:
                indent_spaces = len(cbm.group(1))
                prefix = "[x] " if cbm.group(2).lower() == "x" else "[ ] "
                item_parts = [cbm.group(3).strip()]
            elif bm:
                indent_spaces = len(bm.group(1))
                prefix = None
                item_parts = [bm.group(2).strip()]
            else:
                indent_spaces = len(nm.group(1))
                prefix = f"{nm.group(2)}. "
                item_parts = [nm.group(3).strip()]
            i += 1
            while (
                i < n
                and lines[i].strip()
                and lines[i].startswith("  ")
                and not checkbox_pat.match(lines[i])
                and not bullet_pat.match(lines[i])
                and not num_pat.match(lines[i])
                and not lines[i].strip().startswith((">", "```", "|", "#", "!["))
            ):
                item_parts.append(lines[i].strip())
                i += 1
            item_text = " ".join(item_parts)
            nest = min(indent_spaces // 2, 3)
            if bm:
                p = document.add_paragraph(style="List Bullet")
                if nest:
                    p.paragraph_format.left_indent = Inches(0.25 * (nest + 1))
                p.paragraph_format.space_after = Pt(3)
                _add_inline_markdown_runs(p, item_text, font_size=10.5)
            else:
                p = document.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.25 * (nest + 1))
                p.paragraph_format.first_line_indent = Inches(-0.2)
                p.paragraph_format.space_after = Pt(3)
                lead = p.add_run(prefix)
                lead.bold = True
                lead.font.name = "Calibri"
                lead.font.size = Pt(10.5)
                lead.font.color.rgb = navy_rgb
                _add_inline_markdown_runs(p, item_text, font_size=10.5)
            continue

        # Normal paragraph (coalesce wrapped prose lines)
        para_parts = [stripped]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not heading_pat.match(lines[i].strip())
            and not img_pat.match(lines[i].strip())
            and not re.match(r"^-{3,}$", lines[i].strip())
            and not lines[i].strip().startswith(("```", ">"))
            and not checkbox_pat.match(lines[i])
            and not bullet_pat.match(lines[i])
            and not num_pat.match(lines[i])
            and not ("|" in lines[i] and i + 1 < n and _is_table_sep(lines[i + 1]))
        ):
            para_parts.append(lines[i].strip())
            i += 1
        p = document.add_paragraph()
        _add_inline_markdown_runs(p, " ".join(para_parts), font_size=10.5)

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def load_guide_docx_bytes(filename, file_sha256):
    _ = file_sha256  # cache key invalidates automatically whenever guide text changes
    guide_path = DOCS_DIR / filename
    return markdown_to_docx_bytes(guide_path.read_text(encoding="utf-8"), str(DOCS_DIR))


def render_reference_guides_tab():
    st.markdown("### Reference Guides")
    st.caption(
        "Read any ATLAS guide formatted right inside the workbench, or download a formatted Word (.docx) "
        "copy to print or share with colleagues."
    )
    available_guides = [
        (label.replace(" (.docx)", ""), filename)
        for label, filename in REFERENCE_GUIDES
        if (DOCS_DIR / filename).is_file()
    ]
    if available_guides:
        guide_map = dict(available_guides)
        g_col1, g_col2 = st.columns([3, 2])
        chosen_guide_label = g_col1.selectbox(
            "Choose a guide to read",
            list(guide_map),
            index=0,
            key="tab3_guide_selector",
        )
        chosen_filename = guide_map[chosen_guide_label]
        chosen_path = DOCS_DIR / chosen_filename
        chosen_raw = chosen_path.read_bytes()
        chosen_docx = load_guide_docx_bytes(chosen_filename, hashlib.sha256(chosen_raw).hexdigest())
        g_col2.markdown("<div style='height:1.75rem;'></div>", unsafe_allow_html=True)
        g_col2.download_button(
            f"Download {chosen_path.with_suffix('.docx').name}",
            data=chosen_docx,
            file_name=chosen_path.with_suffix(".docx").name,
            mime=DOCX_MIME,
            key="tab3_guide_docx_download",
            **stretch_kwargs(st.download_button),
        )
        st.markdown("---")
        for block in split_markdown_for_app(chosen_raw.decode("utf-8"), str(DOCS_DIR)):
            if block[0] == "markdown":
                st.markdown(block[1])
            else:
                _, img_path, alt_text = block
                st.image(str(img_path), caption=alt_text or None, **stretch_kwargs(st.image))
    else:
        st.info("No reference guide files found in docs/.")


def render_footer():
    st.markdown("---")
    st.markdown(
        "<div style='text-align:center;color:#475569;font-size:0.85rem;padding:1rem 0;'>"
        "ATLAS · Automated Text-to-Ledger Actuarial Synthesis · MIT License"
        "</div>",
        unsafe_allow_html=True,
    )


if "run_snapshot" not in st.session_state:
    st.session_state.run_snapshot = None
if "run_error" not in st.session_state:
    st.session_state.run_error = None
if "session_override_label" not in st.session_state:
    st.session_state.session_override_label = None
if "session_override_bytes" not in st.session_state:
    st.session_state.session_override_bytes = None


# ------------------------------------------------------------------------------
# 3. Sidebar: files, mode, uncluttered theme drawers, Run button, guides
# ------------------------------------------------------------------------------
core_rules = load_catalog_rules(CORE_THEMES_FILE)
addon_rules = load_catalog_rules(ADDON_THEMES_FILE)
for r in core_rules:
    st.session_state.setdefault(f"core_theme_{r['id']}", True)
for r in addon_rules:
    st.session_state.setdefault(f"addon_theme_{r['id']}", False)


def _set_theme_checkboxes(prefix, rule_ids, checked):
    for rid in rule_ids:
        st.session_state[f"{prefix}_{rid}"] = bool(checked)


with st.sidebar:
    st.markdown("### 1. Files & Mode")

    corpus_choice = st.selectbox("Corpus Dataset", CORPUS_OPTIONS, index=0)

    uploaded_files = []
    tabular_options = None
    tabular_error = None
    facilitator_names = []
    prompt_patterns = []
    if corpus_choice == CORPUS_UPLOAD:
        uploaded_files = st.file_uploader(
            "Upload Files",
            type=UPLOAD_TYPES,
            accept_multiple_files=True,
        ) or []
        st.caption(
            "Upload 3-column Word focus-group notes (.docx), standard Excel/CSV surveys "
            "(1 row per person; any columns), or transcripts (.vtt, .srt, .docx, .txt)."
        )
        tabular_uploads = [f for f in uploaded_files if os.path.splitext(f.name)[1].lower() in TABULAR_EXTENSIONS]
        name_counts = {}
        for f in tabular_uploads:
            name_counts[f.name] = name_counts.get(f.name, 0) + 1
        upload_labels = [
            f"{f.name} (#{i + 1})" if name_counts[f.name] > 1 else f.name
            for i, f in enumerate(tabular_uploads)
        ]

        selected_sheet = 0
        xlsx_uploads = [
            (f, label) for f, label in zip(tabular_uploads, upload_labels)
            if os.path.splitext(f.name)[1].lower() == ".xlsx"
        ]
        if xlsx_uploads:
            sheet_lists = []
            for f, label in xlsx_uploads:
                try:
                    sheet_lists.append((label, read_table_sheets(f.name, f.getvalue())))
                except UPLOAD_READ_ERRORS as exc:
                    tabular_error = f"Could not read sheets in '{label}': {exc}"
                    break
            if not tabular_error and sheet_lists:
                if len(sheet_lists) == 1:
                    sheets = sheet_lists[0][1]
                    if len(sheets) > 1:
                        selected_sheet = st.selectbox(
                            "Choose Excel tab",
                            sheets,
                            index=0,
                            key="excel_sheet_select",
                            help="This workbook has multiple tabs. Pick the tab containing your survey responses.",
                        )
                    elif sheets:
                        selected_sheet = sheets[0]
                else:
                    common_sheets = [
                        s for s in sheet_lists[0][1]
                        if all(s in other for _, other in sheet_lists[1:])
                    ]
                    if not common_sheets:
                        tabular_error = (
                            "The uploaded Excel workbooks have different tab names, so one sheet cannot be "
                            "applied to all of them. Upload workbooks with different tab layouts one at a time."
                        )
                    elif len(common_sheets) > 1:
                        selected_sheet = st.selectbox(
                            "Choose Excel tab",
                            common_sheets,
                            index=0,
                            key="excel_sheet_select",
                        )
                    else:
                        selected_sheet = common_sheets[0]

        frames = []
        if tabular_uploads and not tabular_error:
            for f, label in zip(tabular_uploads, upload_labels):
                try:
                    ext = os.path.splitext(f.name)[1].lower()
                    frames.append(read_table_columns(f.name, f.getvalue(), sheet_name=selected_sheet if ext == ".xlsx" else 0))
                except UPLOAD_READ_ERRORS as exc:
                    tabular_error = f"Could not read '{label}': {exc}"
                    break

        if tabular_uploads and not tabular_error:
            shared = [c for c in frames[0].columns if all(c in fr.columns for fr in frames[1:])]
            text_choices = [c for c in shared if not is_id_column(c)]
            if not shared:
                tabular_error = (
                    "The uploaded tables share no column names, so one text column cannot be applied to all "
                    "of them. Upload tables with the same header, or analyze them one at a time."
                )
            elif not text_choices:
                tabular_error = (
                    "No open-ended response column found: every shared column is an ID column "
                    f"({', '.join(shared)}). Add a response column, or rename it so it is not called 'id' or '*_id'."
                )
            else:
                detected_entries = [
                    (label, detect_text_column(fr[text_choices])) for label, fr in zip(upload_labels, frames)
                ]
                if len({col for _, col in detected_entries}) > 1:
                    tabular_error = (
                        "The uploaded tables keep their open-ended text in different columns ("
                        + "; ".join(f"{label}: {col}" for label, col in detected_entries)
                        + "). ATLAS applies one response column per run, so upload these tables one at a time."
                    )
                else:
                    st.markdown("**Survey table columns** (.csv / .xlsx)")
                    detected = detected_entries[0][1]
                    text_col = st.selectbox(
                        "Open-ended question column to code",
                        text_choices,
                        index=text_choices.index(detected),
                        help="Auto-detected; pick one open-ended question column at a time.",
                    )
                    id_col = st.selectbox("Respondent ID column (optional)", [NONE_OPTION, *shared], index=0)
                    speaker_col = st.selectbox("Speaker / role column (optional)", [NONE_OPTION, *shared], index=0)
                    empty_in = [
                        label for label, fr in zip(upload_labels, frames)
                        if not any(str(v).strip() for v in fr[text_col].tolist())
                    ]
                    if empty_in:
                        tabular_error = (
                            f"The column '{text_col}' is empty in {', '.join(empty_in)}. Choose the column "
                            "that holds the written answers, or upload the tables one at a time."
                        )
                    else:
                        total_non_blank = sum(
                            sum(1 for v in fr[text_col].tolist() if str(v).strip())
                            for fr in frames
                        )
                        total_blank = sum(
                            sum(1 for v in fr[text_col].tolist() if not str(v).strip())
                            for fr in frames
                        )
                        st.caption(
                            f"Preview: {total_non_blank} written answers scanned "
                            f"({total_blank} rows left this question blank)."
                        )
                        tabular_options = {"text_col": text_col}
                        if xlsx_uploads and isinstance(selected_sheet, str):
                            tabular_options["sheet_name"] = selected_sheet
                        if id_col != NONE_OPTION:
                            tabular_options["id_col"] = id_col
                            has_dup_ids = False
                            for fr in frames:
                                non_blank_mask = fr[text_col].astype(str).str.strip() != ""
                                id_vals = [
                                    str(v).strip()
                                    for v in fr.loc[non_blank_mask, id_col].tolist()
                                    if str(v).strip()
                                ]
                                if len(id_vals) != len(set(id_vals)):
                                    has_dup_ids = True
                                    break
                            if has_dup_ids:
                                dup_choice = st.radio(
                                    "Repeated Respondent IDs detected",
                                    [DUP_ID_PER_ROW, DUP_ID_COMBINE],
                                    index=0,
                                    key="dup_id_policy_radio",
                                    help="Choose whether repeated IDs (for example across survey quarters) stay separate rows or combine under one person.",
                                )
                                tabular_options["duplicate_id_policy"] = (
                                    "per_row" if dup_choice == DUP_ID_PER_ROW else "combine"
                                )
                        if speaker_col != NONE_OPTION:
                            tabular_options["speaker_col"] = speaker_col

    # Data Type follows uploaded/selected inputs cleanly.
    selected_sample = SAMPLE_CORPORA.get(corpus_choice)
    if selected_sample is not None:
        detect_items = [(name, (SAMPLES_DIR / name).read_bytes()) for name in selected_sample["files"]]
    else:
        detect_items = [(f.name, f.getvalue()) for f in uploaded_files]
    detect_digest = tuple((name, len(payload), hashlib.sha256(payload).hexdigest()) for name, payload in detect_items)
    structured_flags = [detect_structured_notes(name, payload) for name, payload in detect_items]
    has_structured_notes = any(structured_flags)
    all_structured_notes = bool(structured_flags) and all(structured_flags)
    data_type_fingerprint = (corpus_choice, detect_digest)
    if st.session_state.get("data_type_fingerprint") != data_type_fingerprint:
        st.session_state.data_type_fingerprint = data_type_fingerprint
        st.session_state.data_type = DATA_TYPE_GROUP if has_structured_notes else DATA_TYPE_INDIVIDUAL
    data_type = st.radio(
        "Data Type", DATA_TYPES, key="data_type",
        help="Group mode treats each file as one focus group (1 file = 1 group). Chosen automatically for 3-column focus-group notes.",
    )
    draft_group_mode = data_type == DATA_TYPE_GROUP
    draft_notes_evidence = None
    include_observations = False
    if draft_group_mode:
        include_observations = st.checkbox(
            "Include Note-Taker Observations", value=False,
            help="Also code the Observations column of structured notes (Key Points and Notable Quotes are always coded).",
        )
        draft_notes_evidence = NOTES_EVIDENCE_WITH_OBSERVATIONS if include_observations else NOTES_EVIDENCE_CORE

    draft_spelling_tolerance = st.checkbox(
        "Allow minor spelling typos (useful for open-ended surveys)",
        value=False,
        key="spelling_tolerance_checkbox",
        help="Matches 1-letter typos on 5+ letter theme keywords without altering original quotes. Every typo match appears in Spot-Check Matches.",
    )
    if corpus_choice == CORPUS_UPLOAD and any(
        os.path.splitext(f.name)[1].lower() in TABULAR_EXTENSIONS for f in uploaded_files
    ) and not draft_spelling_tolerance:
        st.caption("Tip: open-ended survey responses often contain typos — turn on spelling tolerance above if needed.")

    if corpus_choice == CORPUS_UPLOAD and not (draft_group_mode and all_structured_notes):
        with st.expander("Advanced transcript filters (optional)", expanded=False):
            st.caption("Only needed for free-form interview transcripts — 3-column focus-group notes strip headers and prompts automatically.")
            names_raw = st.text_input(
                "Facilitator names (optional, comma-separated)", "",
                help="Turns by these named speakers are excluded as facilitator prompts.",
            )
            facilitator_names = [n.strip() for n in names_raw.split(",") if n.strip()]
            patterns_raw = st.text_area(
                "Interviewer prompt patterns (optional, one regular expression per line)", "",
                help="Speakerless turns matching a pattern are excluded as interviewer prompts.",
            )
            prompt_patterns = [p.strip() for p in patterns_raw.splitlines() if p.strip()]

    st.markdown("---")
    st.markdown("### 2. Themes to Code")

    selected_core_ids = [r["id"] for r in core_rules if st.session_state.get(f"core_theme_{r['id']}", True)]
    selected_addon_ids = [r["id"] for r in addon_rules if st.session_state.get(f"addon_theme_{r['id']}", False)]

    with st.expander(f"Core Evaluation Themes ({len(selected_core_ids)} of {len(core_rules)})", expanded=False):
        c_all, c_clr = st.columns(2)
        c_all.button(
            "Select all", key="core_select_all_btn",
            on_click=_set_theme_checkboxes, args=("core_theme", [r["id"] for r in core_rules], True),
            **stretch_kwargs(st.button),
        )
        c_clr.button(
            "Clear", key="core_clear_btn",
            on_click=_set_theme_checkboxes, args=("core_theme", [r["id"] for r in core_rules], False),
            **stretch_kwargs(st.button),
        )
        for r in core_rules:
            st.checkbox(r["name"], key=f"core_theme_{r['id']}", help=r.get("description", ""))

    with st.expander(f"Optional Add-On Themes ({len(selected_addon_ids)} of {len(addon_rules)})", expanded=False):
        st.caption("Program delivery and policy friction themes (no overlap with Core themes).")
        a_all, a_clr = st.columns(2)
        a_all.button(
            "Select all", key="addon_select_all_btn",
            on_click=_set_theme_checkboxes, args=("addon_theme", [r["id"] for r in addon_rules], True),
            **stretch_kwargs(st.button),
        )
        a_clr.button(
            "Clear", key="addon_clear_btn",
            on_click=_set_theme_checkboxes, args=("addon_theme", [r["id"] for r in addon_rules], False),
            **stretch_kwargs(st.button),
        )
        for r in addon_rules:
            st.checkbox(r["name"], key=f"addon_theme_{r['id']}", help=r.get("description", ""))

    # Re-read checkbox state after rendering widgets above.
    selected_core_ids = [r["id"] for r in core_rules if st.session_state.get(f"core_theme_{r['id']}", True)]
    selected_addon_ids = [r["id"] for r in addon_rules if st.session_state.get(f"addon_theme_{r['id']}", False)]

    uploaded_codebook = None
    upload_mode = UPLOAD_MODE_REPLACE
    with st.expander("Upload Custom Themes (.yaml)", expanded=False):
        st.caption("Upload your own theme file for a custom pilot or study.")
        uploaded_codebook = st.file_uploader("Upload Custom Theme File (.yaml)", type=["yaml", "yml"])
        if uploaded_codebook is not None:
            upload_mode = st.radio(
                "How to apply uploaded themes",
                [UPLOAD_MODE_REPLACE, UPLOAD_MODE_COMBINE],
                index=0,
                key="upload_codebook_mode",
            )

    n_checked = len(selected_core_ids) + len(selected_addon_ids)
    if uploaded_codebook is not None and upload_mode == UPLOAD_MODE_REPLACE:
        st.text(f"Active selection: custom file ({uploaded_codebook.name})")
    elif uploaded_codebook is not None:
        st.text(f"Active selection: {n_checked} checked themes + {uploaded_codebook.name}")
    else:
        st.text(f"Active selection: {n_checked} {'theme' if n_checked == 1 else 'themes'}")

    if st.session_state.get("session_override_bytes"):
        st.text(f"In-app edit active: {st.session_state.get('session_override_label')}")
        st.button(
            "Reset in-app theme edits",
            on_click=reset_session_override,
            key="reset_session_override_btn",
            **stretch_kwargs(st.button),
        )

    run_clicked = st.button(
        RUN_BUTTON_LABEL,
        type="primary",
        key="run_analysis_btn",
        **stretch_kwargs(st.button),
        help="Run ATLAS on the selected files and themes.",
    )


# ------------------------------------------------------------------------------
# 4. Header
# ------------------------------------------------------------------------------
st.markdown(
    """
<div class="brand-header">
<h1>ATLAS</h1>
<p>Local qualitative coding, topic discovery, and auditable frequency tables for focus-group notes, transcripts, and surveys.</p>
</div>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------------------
# 5. Commit inputs on Run Analysis click (snapshot-isolated execution)
# ------------------------------------------------------------------------------
uploaded_cb_sig = (
    (uploaded_codebook.name, hashlib.sha256(uploaded_codebook.getvalue()).hexdigest())
    if uploaded_codebook is not None else None
)
draft_tabular_items = tuple(sorted(tabular_options.items())) if tabular_options else None
draft_fingerprint = (
    corpus_choice,
    detect_digest,
    draft_tabular_items,
    tabular_error,
    tuple(facilitator_names),
    tuple(prompt_patterns),
    draft_group_mode,
    draft_notes_evidence,
    bool(draft_spelling_tolerance),
    tuple(selected_core_ids),
    tuple(selected_addon_ids),
    uploaded_cb_sig,
    upload_mode if uploaded_codebook is not None else None,
)

if run_clicked:
    # A manual Run Analysis click commits the current sidebar selections (clearing stale session edits).
    st.session_state.session_override_label = None
    st.session_state.session_override_bytes = None
    commit_error = None
    sample = SAMPLE_CORPORA.get(corpus_choice)
    commit_inputs = None
    commit_tabular = None
    commit_corpus_label = None
    commit_is_fixture = sample is not None

    if sample is not None:
        commit_inputs = tuple(
            ((SAMPLES_DIR / name).relative_to(APP_DIR).as_posix(), (SAMPLES_DIR / name).read_bytes())
            for name in sample["files"]
        )
        commit_tabular = sample["tabular_options"]
        commit_corpus_label = corpus_choice
    else:
        if not uploaded_files:
            commit_error = "Upload one or more files in the sidebar before clicking Run Analysis."
        elif tabular_error:
            commit_error = tabular_error
        elif any(os.path.splitext(f.name)[1].lower() in TABULAR_EXTENSIONS for f in uploaded_files) and not tabular_options:
            commit_error = "Choose an open-ended response column for the uploaded tables before clicking Run Analysis."
        else:
            taken = set()
            commit_inputs = tuple((f"uploads/{safe_upload_name(f.name, taken)}", f.getvalue()) for f in uploaded_files)
            unsupported = [
                rel for rel, _ in commit_inputs
                if os.path.splitext(rel)[1].lower() not in TRANSCRIPT_EXTENSIONS | TABULAR_EXTENSIONS
            ]
            if unsupported:
                commit_error = f"Unsupported file type: {', '.join(unsupported)}"
            else:
                commit_tabular = tabular_options
                commit_corpus_label = ", ".join(os.path.basename(rel) for rel, _ in commit_inputs)

    commit_cb_bytes = None
    commit_primary_label = None
    commit_is_custom = False
    if commit_error is None:
        try:
            uploaded_dict = None
            uploaded_name = None
            if uploaded_codebook is not None:
                uploaded_name = uploaded_codebook.name
                uploaded_dict = yaml.safe_load(uploaded_codebook.getvalue())
                if not isinstance(uploaded_dict, dict):
                    raise ValueError(f"Uploaded theme file {uploaded_name!r} must be a YAML mapping.")
                if not normalize_codebook_rules(uploaded_dict):
                    raise ValueError(f"Uploaded theme file {uploaded_name!r} contains no themes.")

            cb_dict = build_catalog_codebook_dict(
                core_rules,
                set(selected_core_ids),
                addon_rules,
                set(selected_addon_ids),
                uploaded_dict=uploaded_dict,
                uploaded_name=uploaded_name,
                upload_mode=upload_mode,
            )
            if cb_dict is None or not normalize_codebook_rules(cb_dict):
                commit_error = "Select at least one theme—or upload a custom theme file—before clicking Run Analysis."
            else:
                commit_cb_bytes = yaml.safe_dump(cb_dict, allow_unicode=True, sort_keys=False).encode("utf-8")
                n_sel = len(normalize_codebook_rules(cb_dict))
                if uploaded_dict is not None and upload_mode == UPLOAD_MODE_REPLACE:
                    commit_primary_label = f"{uploaded_name} ({n_sel} themes)"
                    commit_is_custom = True
                elif uploaded_dict is not None:
                    commit_primary_label = f"Selected Themes + {uploaded_name} ({n_sel} themes)"
                    commit_is_custom = True
                else:
                    parts = []
                    if selected_core_ids:
                        parts.append(f"{len(selected_core_ids)} Core")
                    if selected_addon_ids:
                        parts.append(f"{len(selected_addon_ids)} Add-On")
                    commit_primary_label = f"{' + '.join(parts)} ({n_sel} {'theme' if n_sel == 1 else 'themes'})"
                    commit_is_custom = bool(
                        len(selected_core_ids) != len(core_rules) or bool(selected_addon_ids)
                    )
        except (*UPLOAD_READ_ERRORS, yaml.YAMLError) as exc:
            commit_error = f"ATLAS could not load the selected themes: {exc}"

    if commit_error is None:
        bad_patterns = []
        for pattern in prompt_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                bad_patterns.append(f"{pattern!r} ({exc})")
        if bad_patterns:
            commit_error = "Invalid interviewer prompt pattern: " + "; ".join(bad_patterns)

    if commit_error is not None:
        st.session_state.run_snapshot = None
        st.session_state.run_error = commit_error
    else:
        st.session_state.run_snapshot = {
            "inputs": commit_inputs,
            "tabular_items": tuple(sorted(commit_tabular.items())) if commit_tabular else None,
            "facilitator_names": tuple(facilitator_names),
            "prompt_patterns": tuple(prompt_patterns),
            "notes_evidence": draft_notes_evidence,
            "include_observations": bool(include_observations),
            "group_mode": draft_group_mode,
            "spelling_tolerance": bool(draft_spelling_tolerance),
            "corpus_label": commit_corpus_label,
            "is_fixture": commit_is_fixture,
            "codebook_bytes": commit_cb_bytes,
            "primary_codebook_label": commit_primary_label,
            "is_custom_or_stacked": commit_is_custom,
            "codebook_sha256": hashlib.sha256(commit_cb_bytes).hexdigest(),
            "base_codebook_bytes": commit_cb_bytes,
            "base_primary_codebook_label": commit_primary_label,
            "base_is_custom_or_stacked": commit_is_custom,
            "base_codebook_sha256": hashlib.sha256(commit_cb_bytes).hexdigest(),
            "fingerprint": draft_fingerprint,
        }
        st.session_state.run_error = None

# Add Save Active Themes button (when customized) and Word Reference Guides to the sidebar.
snap = st.session_state.get("run_snapshot")
with st.sidebar:
    if isinstance(snap, dict) and snap.get("is_custom_or_stacked"):
        st.download_button(
            "Save active themes (.yaml)",
            data=snap["codebook_bytes"],
            file_name="atlas_active_codebook.yaml",
            mime="application/x-yaml",
            key="download_active_codebook_sidebar",
            help="Save a copy of your active theme rules alongside your export files.",
            **stretch_kwargs(st.download_button),
        )
    st.markdown("---")
    st.markdown("### Reference Guides")
    st.caption("Download formatted Word (.docx) copies, or read inside the Reference Guides tab.")
    for label, filename in REFERENCE_GUIDES:
        guide = DOCS_DIR / filename
        if guide.is_file():
            raw_bytes = guide.read_bytes()
            docx_bytes = load_guide_docx_bytes(filename, hashlib.sha256(raw_bytes).hexdigest())
            st.download_button(
                label=label,
                data=docx_bytes,
                file_name=guide.with_suffix(".docx").name,
                mime=DOCX_MIME,
                **stretch_kwargs(st.download_button),
                key=f"guide_{filename}",
            )

if st.session_state.get("run_error"):
    tab_thematic, tab_exports, tab_guides = st.tabs(TOP_TABS)
    with tab_thematic:
        st.error(st.session_state.run_error)
    with tab_exports:
        st.info("Fix the input error in the sidebar and click **Run Analysis** to generate exports.")
    with tab_guides:
        render_reference_guides_tab()
    render_footer()
    st.stop()

if not isinstance(snap, dict):
    tab_thematic, tab_exports, tab_guides = st.tabs(TOP_TABS)
    with tab_thematic:
        st.info(
            "**Ready to analyze.** Choose your files (or the built-in focus-group notes sample) and themes "
            "in the left sidebar, then click **Run Analysis**."
        )
        st.markdown(
            "1. **Load files:** Drag in 3-column Word focus-group notes (`.docx`), Excel/CSV surveys "
            "(1 row per person; any columns), or transcripts — or select the built-in sample.\n"
            "2. **Choose themes:** All 10 Core Evaluation Themes are checked by default. Open the drawers "
            "to pick a subset, add Program Delivery & Policy Friction add-ons, or upload a custom `.yaml` file.\n"
            "3. **Click Run Analysis** in the left sidebar to inspect group presence, notes volume, "
            "direct quotes, unlisted clusters, and Spot-Check matches."
        )
    with tab_exports:
        st.info("Click **Run Analysis** in the left sidebar to generate tables, reports, and audit files.")
    with tab_guides:
        render_reference_guides_tab()
    render_footer()
    st.stop()

# Unpack committed run snapshot so displayed results never mix with un-run sidebar edits.
inputs = snap["inputs"]
codebook_bytes = snap["codebook_bytes"]
corpus_label = snap["corpus_label"]
group_mode = snap["group_mode"]
spelling_tolerance = bool(snap.get("spelling_tolerance", False))
include_obs_snap = bool(snap.get("include_observations", False))
is_fixture = bool(snap.get("is_fixture", False))
is_custom_or_stacked = bool(snap.get("is_custom_or_stacked", False))
pending_changes = draft_fingerprint != snap["fingerprint"]

try:
    with st.spinner("Parsing and coding the corpus..."):
        results = analyze_corpus(
            codebook_bytes,
            inputs,
            snap["tabular_items"],
            snap["facilitator_names"],
            snap["prompt_patterns"],
            snap["notes_evidence"],
            group_mode,
            spelling_tolerance,
        )
except (*UPLOAD_READ_ERRORS, RuntimeError, yaml.YAMLError) as exc:
    err_msg = f"ATLAS could not analyze this corpus with the selected themes: {exc}"
    st.session_state.run_snapshot = None
    st.session_state.run_error = err_msg
    tab_thematic, tab_exports, tab_guides = st.tabs(TOP_TABS)
    with tab_thematic:
        st.error(err_msg)
    with tab_exports:
        st.info("Fix the input error in the sidebar and click **Run Analysis** to generate exports.")
    with tab_guides:
        render_reference_guides_tab()
    render_footer()
    st.stop()

freq = results["frequencies_df"]
quotes = results["quotes_df"]
tagged_df = results["tagged_turns_df"]
typo_df = results.get("typo_matches_df")
if typo_df is None:
    typo_df = pd.DataFrame()
audit_df = results["false_alarm_audit_df"]
tabular_stats = results.get("tabular_stats") or []
notes_metadata = results.get("notes_metadata") or {}
compiled_domains = results.get("compiled_domains") or normalize_codebook_rules(yaml.safe_load(codebook_bytes) or {})

total_documents = int(results["total_documents"])
participant_turns = int(results["participant_turns_analyzed"])
total_themes = int(len(freq))
themes_found = int((freq["documents_reporting"] > 0).sum()) if total_themes else 0
theme_matches = int(len(quotes))
if len(tagged_df) and "matched_domains" in tagged_df.columns:
    matched_entries = int(sum(1 for ds in tagged_df["matched_domains"] if ds))
else:
    matched_entries = 0
uncoded_entries = max(0, participant_turns - matched_entries)

doc_structures = set(results.get("document_structures", {}).values())
notes_present = NOTES_STRUCTURE in doc_structures
all_notes_corpus = bool(doc_structures) and doc_structures == {NOTES_STRUCTURE}
active_theme_names = [str(d["name"]) for d in compiled_domains]
domain_name_map = {str(d["id"]): str(d["name"]) for d in compiled_domains}

group_labels = group_labels_for(results["file_hashes"])
group_table = None
group_matrix = None
group_summary = ""
matrix_summary = ""
themes_df = pd.DataFrame()
if group_mode:
    group_table = build_group_frequency_table(
        freq, quotes, total_documents, include_observations=include_obs_snap
    )
    theme_order = list(group_table["_domain_id"].astype(str)) if len(group_table) else None
    group_summary = describe_group_prevalence_chart(group_table, total_documents)
    group_matrix = build_group_theme_matrix(freq, quotes, results["file_hashes"], theme_order=theme_order)
    matrix_summary = describe_group_matrix_chart(group_matrix, total_documents)
    themes_df = results.get("note_taker_themes_df")
    if themes_df is None:
        themes_df = pd.DataFrame()

# Compute default discovery once for the active snapshot so the Full Report (.docx)
# matches the Discover Unlisted Themes tab exactly.
turn_records = tagged_df.to_dict("records") if len(tagged_df) else []
active_disc_method = DISCOVERY_METHOD_MAP.get(st.session_state.get("disc_method_radio", DISCOVERY_METHOD_NMF), "nmf")
active_disc_k = int(st.session_state.get("disc_k_slider", 3))
discovery = run_topic_discovery(turn_records, active_disc_k, method=active_disc_method)
discovery_overlap = compute_topic_codebook_overlap(discovery, turn_records, domain_name_map)

full_report_docx = build_summary_report_docx(
    results,
    group_mode=group_mode,
    group_table=group_table[[c for c in group_table.columns if not c.startswith("_")]] if group_table is not None else None,
    group_matrix=group_matrix,
    discovery=discovery,
    discovery_overlap=discovery_overlap,
    audit_df=audit_df,
    active_theme_names=active_theme_names,
    corpus_label=corpus_label,
    is_fixture=is_fixture,
    spelling_tolerance=spelling_tolerance,
    include_observations=include_obs_snap,
)

if pending_changes:
    st.warning("Sidebar inputs have changed since the last run. Click **Run Analysis** in the left sidebar to refresh results.")

# ------------------------------------------------------------------------------
# 6. Three-tab interface: Themes & Quotes | Exports & Audit Files | Reference Guides
# ------------------------------------------------------------------------------
tab_thematic, tab_exports, tab_guides = st.tabs(TOP_TABS)

# ==============================================================================
# TAB 1: THEMES & QUOTES
# ==============================================================================
with tab_thematic:
    if is_fixture:
        st.info(
            "Sample practice data active — Built-in focus-group notes are loaded for demonstration only "
            "and are not real study findings."
        )

    # Plain-English provenance banner ("Where these themes come from")
    st.markdown(
        f'<div class="provenance-banner">'
        f'<strong>How these themes work:</strong> Charts count matches against the '
        f'<strong>{total_themes} predefined {"theme" if total_themes == 1 else "themes"}</strong> selected on the left '
        f'— transparent keyword rules, not AI-invented topics. To cluster entries without a preset list, '
        f'open <strong>Discover Unlisted Themes</strong>.'
        f'<br><span style="color:#475569;font-size:0.9rem;">Corpus: {esc_inline(corpus_label)} · '
        f'Themes: {esc_inline(snap["primary_codebook_label"])}'
        f'{" · Spelling tolerance: On" if spelling_tolerance else ""}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.expander(f"View active theme keywords ({total_themes} {'theme' if total_themes == 1 else 'themes'})", expanded=False):
        kw_rows = []
        for dom in compiled_domains:
            roots = list(dom.get("roots_en") or []) + list(dom.get("roots_es") or [])
            excl = list(dom.get("exclude_fences") or [])
            kw_rows.append({
                "Theme": str(dom["name"]),
                "Keywords Matched": ", ".join(roots),
                "Look-Alikes Blocked": ", ".join(excl) if excl else "—",
                "Match Mode": str(dom.get("match_mode", "prefix")),
            })
        st.dataframe(pd.DataFrame(kw_rows), **stretch_kwargs(st.dataframe), hide_index=True)

    # Four reconciled KPI cards (Points #2 & #3)
    k1, k2, k3, k4 = st.columns(4)
    if group_mode:
        scanned_label = "Notes Entries Scanned" if all_notes_corpus else "Entries Scanned"
        k1.metric("Focus Groups", total_documents, help="1 uploaded file = 1 focus group.")
        k2.metric("Themes Found", f"{themes_found} of {total_themes}", help="Active themes matched in at least one focus group.")
        k3.metric(scanned_label, participant_turns, help="Total non-facilitator entries read by ATLAS (including entries matching no theme).")
        k3.caption(f"{matched_entries} matched · {uncoded_entries} none")
        k4.metric("Theme Matches", theme_matches, help="Total (entry x theme) matches. One entry mentioning two themes counts twice.")
        k4.caption("1 entry can match 2+ themes")
    else:
        scanned_label = "Written Answers Scanned" if "tabular" in doc_structures else "Turns Scanned"
        k1.metric("Analytical Units", total_documents, help="One unit per transcript file or survey respondent unit.")
        k2.metric("Themes Found", f"{themes_found} of {total_themes}", help="Active themes matched in at least one unit.")
        k3.metric(scanned_label, participant_turns, help="Total non-facilitator entries scanned by ATLAS.")
        k3.caption(f"{matched_entries} matched · {uncoded_entries} none")
        k4.metric("Theme Matches", theme_matches, help="Total (entry x theme) matches. One entry can match multiple themes.")
        k4.caption("1 entry can match 2+ themes")

    if tabular_stats:
        total_non_blank = sum(int(s.get("non_blank_rows", 0)) for s in tabular_stats)
        total_blank = sum(int(s.get("skipped_blank_rows", 0)) for s in tabular_stats)
        total_unique = sum(int(s.get("unique_units", 0)) for s in tabular_stats)
        if not group_mode and total_unique < total_non_blank:
            st.caption(
                f"Survey counts: {total_non_blank} written answers across {total_unique} unique respondents "
                f"({total_blank} rows left this question blank)."
            )
        else:
            st.caption(
                f"Survey counts: {total_non_blank} written answers scanned "
                f"({total_blank} rows left this question blank)."
            )

    # Quiet attribution note in Group Mode only when speaker tagging varies across files.
    if group_mode and len(tagged_df) and {"source_id", "speaker"} <= set(tagged_df.columns):
        per_file_tagged = []
        for sid in sorted(results["file_hashes"]):
            sub = tagged_df[tagged_df["source_id"].astype(str) == str(sid)]
            has_spk = any(str(p) not in NON_VOICE_SPEAKERS for p in sub["speaker"].tolist())
            per_file_tagged.append(has_spk)
        if any(per_file_tagged) and not all(per_file_tagged):
            n_tagged_files = sum(1 for x in per_file_tagged if x)
            st.caption(
                f"Note: speaker tags appear in {n_tagged_files} of {len(per_file_tagged)} focus-group files. "
                "Group summaries compare across focus groups rather than individual speaker counts; "
                "use the Speaker filter in Coded Evidence to inspect tagged files."
            )

    mixed_view = bool(
        has_non_verbatim_evidence(quotes)
        and not (group_mode and st.session_state.get("verbatim_only_filter", False))
    )
    qtab_summary, qtab_quotes, qtab_topics, qtab_spotcheck = st.tabs(SUB_TABS)

    # --------------------------------------------------------------------------
    # SUB-TAB 1: THEME SUMMARY (Option A: Group Grid first, Notes Volume second)
    # --------------------------------------------------------------------------
    with qtab_summary:
        if len(freq):
            if group_mode:
                st.markdown("#### Which Focus Groups Mentioned Each Theme?")
                g_ctrl1, g_ctrl2 = st.columns([3, 1])
                grid_mode = g_ctrl1.radio(
                    "Grid shows",
                    ["Presence (✓ / —)", "Notes entries per group"],
                    horizontal=True,
                    key="group_grid_mode_radio",
                )
                hide_zero = g_ctrl2.checkbox(
                    "Hide 0-match themes",
                    value=False,
                    key="hide_zero_themes_chk",
                )
                show_entries = grid_mode == "Notes entries per group"
                visible_table = group_table[group_table["Theme Matches"] > 0] if hide_zero else group_table
                visible_ids = set(visible_table["_domain_id"].astype(str))
                visible_matrix = group_matrix[group_matrix["domain_id"].astype(str).isin(visible_ids)] if hide_zero else group_matrix

                if visible_matrix.empty:
                    st.info("No active theme matched any entry in these focus groups. Uncheck 'Hide 0-match themes' to view all themes.")
                else:
                    if show_entries:
                        st.caption("Counts show matching notes entries per file (reflects note volume, not participant headcount).")
                    else:
                        st.caption("Uniform across all focus groups: ✓ = mentioned in group notes · — = not mentioned.")
                    n_rows_vis = visible_matrix["domain_id"].nunique()
                    st.altair_chart(
                        light_chart_surface(
                            group_matrix_chart(visible_matrix, total_documents, show_entries=show_entries)
                            .properties(height=max(180, 46 * n_rows_vis), description=matrix_summary)
                        ),
                        **stretch_kwargs(st.altair_chart),
                    )
                    st.html(chart_summary_html(matrix_summary))

                    st.markdown("#### How Often Each Theme Appeared in the Notes")
                    st.caption(
                        "Bars show matched notes entries sorted highest to lowest (labelled `<matches> (<groups reporting>)`). "
                        "Entry counts reflect how much was written in the notes — not how many participants agreed."
                    )
                    st.altair_chart(
                        light_chart_surface(
                            group_volume_chart(visible_table, total_documents)
                            .properties(height=max(180, 44 * len(visible_table)), description=group_summary)
                        ),
                        **stretch_kwargs(st.altair_chart),
                    )
                    st.html(chart_summary_html(group_summary))

                st.markdown("##### Theme Summary Table")
                display_cols = [c for c in group_table.columns if not c.startswith("_")]
                st.dataframe(
                    (visible_table if hide_zero else group_table)[display_cols],
                    **stretch_kwargs(st.dataframe),
                    hide_index=True,
                )
            else:
                st.markdown("#### Theme Prevalence Across Analytical Units")
                st.caption("Prevalence = units with at least one matching entry / all analytical units.")
                ind_sorted = freq.sort_values(
                    ["prevalence_pct", "matching_turns", "domain_name", "domain_id"],
                    ascending=[False, False, True, True],
                    kind="mergesort",
                )
                y_order_ind = list(ind_sorted["domain_id"].astype(str))
                ind_id_to_label = dict(zip(y_order_ind, ind_sorted["domain_name"].astype(str)))
                ind_label_expr = f"({json.dumps(ind_id_to_label)})[datum.value]"
                chart = alt.Chart(ind_sorted).mark_bar(color=NAVY, cornerRadiusEnd=3).encode(
                    x=alt.X("prevalence_pct:Q", title="Prevalence (% of analytical units)", scale=alt.Scale(domain=[0, 105])),
                    y=alt.Y("domain_id:N", sort=y_order_ind, title=None, axis=alt.Axis(labelLimit=360, labelExpr=ind_label_expr)),
                    tooltip=[
                        alt.Tooltip("domain_name:N", title="Theme"),
                        alt.Tooltip("domain_id:N", title="Theme ID"),
                        alt.Tooltip("prevalence_pct:Q", title="Prevalence (%)"),
                        alt.Tooltip("documents_reporting:Q", title="Units reporting"),
                        alt.Tooltip("matching_turns:Q", title="Theme matches"),
                    ],
                )
                labels = alt.Chart(ind_sorted).mark_text(
                    align="left", dx=6, fontSize=13, fontWeight="bold", color="#0F172A"
                ).encode(
                    x="prevalence_pct:Q",
                    y=alt.Y("domain_id:N", sort=y_order_ind),
                    text=alt.Text("matching_turns:Q", format="d"),
                )
                ind_summary = describe_prevalence_chart(ind_sorted, total_documents, include_ci=False)
                st.altair_chart(
                    light_chart_surface(
                        (chart + labels).properties(height=max(180, 44 * len(ind_sorted)), description=ind_summary)
                    ),
                    **stretch_kwargs(st.altair_chart),
                )
                st.html(chart_summary_html(ind_summary))
                st.caption("Bar labels show total theme matches per theme.")
                st.markdown("##### Theme Summary Table")
                st.dataframe(
                    ind_sorted[["domain_name", "documents_reporting", "total_documents", "prevalence_pct", "matching_turns"]],
                    **stretch_kwargs(st.dataframe),
                    hide_index=True,
                    column_config={
                        "domain_name": "Theme",
                        "documents_reporting": "Units Reporting",
                        "total_documents": "Analytical Units (N)",
                        "prevalence_pct": st.column_config.NumberColumn("Prevalence (%)", format="%.1f"),
                        "matching_turns": "Theme Matches",
                    },
                )
        else:
            st.info("No active themes selected.")

        # Direct 3-button Download Bar right on Tab 1 (Point #9)
        st.markdown("---")
        st.markdown("##### Download Results")
        dl1, dl2, dl3 = st.columns(3)
        dl1.download_button(
            "Download Full Report (.docx)",
            data=full_report_docx,
            file_name="atlas_summary_report.docx",
            mime=DOCX_MIME,
            key="tab1_download_full_report",
            **stretch_kwargs(st.download_button),
            help="Printable Word report combining KPIs, Group Grid, Theme Summary, Quotes, Unlisted Clusters, Spot-Check, and Excluded Questions.",
        )
        dl2.download_button(
            "Download Theme Frequencies (.xlsx)",
            data=results["exports"]["actuarial_parameter_matrix.xlsx"],
            file_name="actuarial_parameter_matrix.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="tab1_download_xlsx",
            **stretch_kwargs(st.download_button),
            help="Audited Excel frequency workbook with embedded verification stamps.",
        )
        dl3.download_button(
            "Download Direct Quotes (.csv)",
            data=results["exports"]["verbatim_quotes_inventory.csv"],
            file_name="verbatim_quotes_inventory.csv",
            mime="text/csv",
            key="tab1_download_quotes_csv",
            **stretch_kwargs(st.download_button),
            help="Direct verbatim quotes only, ready for reports and slides.",
        )

        # Collapsed Excluded Questions & Session Headers drawer (Point #7)
        excl_records = []
        for sid, meta in sorted(notes_metadata.items()):
            for item in (meta or {}).get("excluded_structural_rows") or []:
                excl_records.append({
                    "Source File": group_labels.get(sid, os.path.basename(sid)),
                    "Location": f"Block {item.get('location', '')}",
                    "Exclusion Reason": str(item.get("reason", "")).replace("_", " "),
                    "Excluded Text": str(item.get("text", "")),
                })
        if excl_records:
            with st.expander(
                f"Excluded Questions & Session Headers ({len(excl_records)} skipped — click to verify)",
                expanded=False,
            ):
                st.caption(
                    "ATLAS stripped these question prompts, consent lines, and summary boxes before coding so "
                    "question wording never inflates theme counts."
                )
                st.dataframe(pd.DataFrame(excl_records), **stretch_kwargs(st.dataframe), hide_index=True)

        if group_mode and len(themes_df) and {"source_id", "question_id", "text"} <= set(themes_df.columns):
            with st.expander(THEMES_EXPANDER_LABEL, expanded=False):
                st.caption(
                    "Note-taker theme summaries, shown for reference only. They are not coded and are not "
                    "counted in any prevalence, quote, or KPI."
                )
                for sid in sorted(themes_df["source_id"].astype(str).unique()):
                    rows = themes_df[themes_df["source_id"].astype(str) == sid]
                    items = "".join(
                        f"<li><strong>{esc(q)}:</strong> {esc(t)}</li>"
                        for q, t in zip(rows["question_id"], rows["text"])
                    )
                    st.markdown(
                        f'<div class="quote-box topic-box"><div class="quote-meta">'
                        f'{esc(group_labels.get(sid, os.path.basename(sid)))}</div>'
                        f'<ul style="margin:0;color:#0F172A;">{items}</ul></div>',
                        unsafe_allow_html=True,
                    )

    # --------------------------------------------------------------------------
    # SUB-TAB 2: CODED EVIDENCE
    # --------------------------------------------------------------------------
    with qtab_quotes:
        st.markdown("#### Coded Evidence & Direct Quotes")
        if quotes.empty:
            st.info("No entry matched any of the active themes in this corpus.")
        elif group_mode:
            labelled = quotes.assign(group_label=quotes["source_id"].astype(str).map(
                lambda sid: group_labels.get(sid, os.path.basename(sid))))
            questions = sorted(q for q in labelled["question_id"].astype(str).unique() if q)
            f1, f2, f3 = st.columns([2, 1, 1])
            search = f1.text_input("Search theme matches", "")
            domain_filter = f2.selectbox("Filter by theme", ["All themes", *sorted(labelled["domain_name"].astype(str).unique())])
            speaker_filter = f3.selectbox("Filter by speaker", ["All speakers", *sorted(labelled["speaker"].astype(str).unique())])
            g1, g2, g3 = st.columns([2, 1, 1])
            verbatim_only = g1.checkbox(
                "Quotable Verbatim Only", value=False, key="verbatim_only_filter",
                help="Show direct participant quotations only (hides paraphrased key points and note-taker observations).",
            )
            group_filter = g2.selectbox("Filter by group", ["All groups", *sorted(labelled["group_label"].unique())])
            question_filter = "All questions"
            if questions:
                question_filter = g3.selectbox("Filter by question", ["All questions", *questions])
            shown = labelled
            if verbatim_only:
                shown = verbatim_rows(shown)
            if domain_filter != "All themes":
                shown = shown[shown["domain_name"].astype(str) == domain_filter]
            if speaker_filter != "All speakers":
                shown = shown[shown["speaker"].astype(str) == speaker_filter]
            if group_filter != "All groups":
                shown = shown[shown["group_label"] == group_filter]
            if question_filter != "All questions":
                shown = shown[shown["question_id"].astype(str) == question_filter]
            if search.strip():
                shown = shown[shown["text"].astype(str).str.contains(search.strip(), case=False, regex=False)]
            if mixed_view:
                st.markdown(
                    f"**Showing {len(shown)} of {len(quotes)} theme matches** "
                    "(one entry can match multiple themes; check 'Quotable Verbatim Only' for direct quotes)"
                )
            else:
                st.markdown(f"**Showing {len(shown)} of {len(quotes)} theme matches** (direct verbatim quotes only)")
            if shown.empty:
                st.info("No verbatim quote matches the current filters." if verbatim_only
                        else "No theme match fits these filters.")
            else:
                st.dataframe(
                    shown[["evidence_type", "group_label", "question_id", "domain_name", "speaker",
                           "line_number", "match_text", "text", "source_id"]],
                    **stretch_kwargs(st.dataframe), hide_index=True,
                    column_config={
                        "evidence_type": "Source Type", "group_label": "Focus Group", "question_id": "Question",
                        "domain_name": "Theme", "speaker": "Speaker", "line_number": "Line",
                        "match_text": "Matched Word", "text": "Entry Text", "source_id": "Source File",
                    },
                )
                for _, q in shown.head(25).iterrows():
                    question = f" · {esc(q['question_id'])}" if str(q["question_id"]) else ""
                    st.markdown(
                        f'<div class="quote-box">'
                        f'<div class="quote-meta">{evidence_badge_html(q["evidence_type"])}'
                        f'{esc(q["domain_name"])} · {esc(q["speaker"])} · {esc(q["group_label"])}{question}</div>'
                        f'<div class="quote-text">{highlighted_quote(q["text"], q["match_char_start"], q["match_char_end"])}</div>'
                        f'<div class="quote-provenance">SOURCE {esc(q["source_id"])} · LINE {esc(q["line_number"])} · '
                        f'CHARS {esc(q["match_char_start"])}-{esc(q["match_char_end"])} · '
                        f'SHA-256 {esc(str(q["source_sha256"])[:12])}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        else:
            f1, f2, f3 = st.columns([2, 1, 1])
            search = f1.text_input("Search theme matches", "")
            domain_filter = f2.selectbox("Filter by theme", ["All themes", *sorted(quotes["domain_name"].astype(str).unique())])
            speaker_filter = f3.selectbox("Filter by speaker", ["All speakers", *sorted(quotes["speaker"].astype(str).unique())])
            shown = quotes
            if domain_filter != "All themes":
                shown = shown[shown["domain_name"].astype(str) == domain_filter]
            if speaker_filter != "All speakers":
                shown = shown[shown["speaker"].astype(str) == speaker_filter]
            if search.strip():
                shown = shown[shown["text"].astype(str).str.contains(search.strip(), case=False, regex=False)]
            st.markdown(
                f"**Showing {len(shown)} of {len(quotes)} theme matches** "
                "(one entry can match multiple themes)"
            )
            if shown.empty:
                st.info("No theme match fits these filters.")
            else:
                cols_ind = [*(["evidence_type"] if notes_present else []), "domain_name", "speaker",
                            *(["respondent_id"] if "respondent_id" in shown.columns else []),
                            "source_id", "line_number", "match_text", "text"]
                st.dataframe(
                    shown[cols_ind],
                    **stretch_kwargs(st.dataframe), hide_index=True,
                    column_config={
                        "evidence_type": "Source Type", "domain_name": "Theme", "speaker": "Speaker",
                        "respondent_id": "Respondent ID", "source_id": "Source File",
                        "line_number": "Line", "match_text": "Matched Word", "text": "Entry Text",
                    },
                )
                for _, q in shown.head(25).iterrows():
                    badge = evidence_badge_html(q["evidence_type"]) if notes_present else ""
                    st.markdown(
                        f'<div class="quote-box">'
                        f'<div class="quote-meta">{badge}{esc(q["domain_name"])} · {esc(q["speaker"])}</div>'
                        f'<div class="quote-text">{highlighted_quote(q["text"], q["match_char_start"], q["match_char_end"])}</div>'
                        f'<div class="quote-provenance">SOURCE {esc(q["source_id"])} · LINE {esc(q["line_number"])} · '
                        f'CHARS {esc(q["match_char_start"])}-{esc(q["match_char_end"])} · '
                        f'SHA-256 {esc(str(q["source_sha256"])[:12])}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    # --------------------------------------------------------------------------
    # SUB-TAB 3: DISCOVER UNLISTED THEMES (Point #5 + safe index join)
    # --------------------------------------------------------------------------
    with qtab_topics:
        st.markdown("#### Discover Unlisted Themes")
        st.caption(
            "Groups entries by shared words without using your theme checklist — useful as a sanity check "
            "and to spot topics your selected themes may have missed."
        )
        n_topics = st.slider("Number of clusters (k)", min_value=1, max_value=10, value=3, key="disc_k_slider")
        with st.expander("Method settings", expanded=False):
            disc_choice = st.radio(
                "Clustering method",
                list(DISCOVERY_METHOD_MAP),
                index=0,
                horizontal=True,
                key="disc_method_radio",
                help="TF-IDF + NMF is deterministic and produces sharper keywords; LDA is classic bag-of-words.",
            )
        disc_method = DISCOVERY_METHOD_MAP[disc_choice]
        if disc_method != active_disc_method or n_topics != active_disc_k:
            discovery = run_topic_discovery(turn_records, n_topics, method=disc_method)
            discovery_overlap = compute_topic_codebook_overlap(discovery, turn_records, domain_name_map)

        topics = discovery["topics"]
        if not topics:
            st.info("No entries have enough content words for automatic clustering.")
        else:
            n_disc = int(discovery["n_analyzed"])
            st.caption(f"{n_disc} entries analyzed; {len(topics)} {'cluster' if len(topics) == 1 else 'clusters'} shown.")
            for topic in topics:
                tid = int(topic["topic_id"])
                terms = ", ".join(dedupe_terms(topic["top_terms"]))
                medoid = topic["medoid_text"]
                cov = discovery_overlap.get(tid, {})
                cov_status = cov.get("coverage_status", "mostly_covered")
                cov_label = cov.get("coverage_label", "")
                cov_cls = (
                    "coverage-uncoded" if cov_status == "mostly_uncoded"
                    else ("coverage-partial" if cov_status == "partially_uncoded" else "coverage-covered")
                )
                cov_badge = f'<span class="coverage-badge {cov_cls}">{esc_inline(cov_label)}</span>' if cov_label else ""

                # Determine source badge of the representative example safely via member indices.
                medoid_ev = ""
                for idx in cov.get("member_indices") or []:
                    rec = turn_records[idx]
                    if (
                        str(rec.get("unit_id")) == str(topic["medoid_unit_id"])
                        and str(rec.get("turn_id")) == str(topic["medoid_turn_id"])
                        and str(rec.get("text")) == str(topic["medoid_text"])
                    ):
                        medoid_ev = str(rec.get("evidence_type") or "")
                        break
                ev_badge = evidence_badge_html(medoid_ev) if notes_present else ""

                st.markdown(
                    f'<div class="quote-box topic-box">'
                    f'<div class="quote-meta">{cov_badge}{ev_badge}'
                    f'Cluster {esc(tid)}: {esc(topic["label"])} · '
                    f'{esc(topic["turn_count"])} of {n_disc} entries ({esc(topic["share_pct"])}%)</div>'
                    f'<div style="font-size:0.95rem;margin-bottom:0.4rem;"><strong>Top keywords:</strong> {esc(terms)}</div>'
                    f'<div style="font-size:0.88rem;font-weight:700;color:#475569;margin-bottom:0.2rem;">Most representative example:</div>'
                    f'<div class="quote-text">{esc(medoid) if medoid else "No example entry assigned."}</div>'
                    f'<div class="quote-provenance">SOURCE {esc(topic["medoid_unit_id"])} · SPEAKER {esc(topic["medoid_speaker"])}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

                member_indices = cov.get("member_indices") or []
                if member_indices:
                    with st.expander(f"View all {len(member_indices)} entries in Cluster {tid}", expanded=False):
                        cluster_rows = []
                        for idx in member_indices:
                            rec = turn_records[idx]
                            matched_names = [domain_name_map.get(str(d), str(d)) for d in (rec.get("matched_domains") or [])]
                            cluster_rows.append({
                                "Source File": group_labels.get(str(rec.get("source_id", "")), str(rec.get("source_id", ""))),
                                "Line": rec.get("line_number", ""),
                                **({"Source Type": EVIDENCE_BADGE_STYLES.get(str(rec.get("evidence_type", "")), EVIDENCE_BADGE_FALLBACK)[2]} if notes_present else {}),
                                "Active Theme Match": ", ".join(matched_names) if matched_names else "None (uncoded)",
                                "Entry Text": str(rec.get("text", "")),
                            })
                        st.dataframe(pd.DataFrame(cluster_rows), **stretch_kwargs(st.dataframe), hide_index=True)

            st.markdown("---")
            st.markdown("##### Add a discovered cluster to your active themes")
            st.caption("Appends one cluster as a new theme without editing YAML by hand.")
            topic_choices = {
                f"Cluster {t['topic_id']}: {t['label']} ({t['turn_count']} entries)": t for t in topics
            }
            if st.session_state.get("add_topic_select") not in topic_choices:
                st.session_state.pop("add_topic_select", None)
            a1, a2 = st.columns([2, 2])
            a1.selectbox("Cluster to add", list(topic_choices), key="add_topic_select")
            picked_topic = topic_choices[st.session_state.get("add_topic_select", next(iter(topic_choices)))]
            a2.text_input(
                "New theme name (optional)",
                placeholder=str(picked_topic["label"]),
                key="add_topic_name",
                help="Leave blank to use the cluster's top keywords as the theme name.",
            )
            st.checkbox(
                "Use exact whole-word matching for added theme (recommended)",
                value=True,
                key="add_topic_exact",
                help="Prevents short discovered words (such as 'car' or 'fee') from matching unrelated longer words.",
            )
            st.button(
                "Add Theme to Active Themes",
                on_click=add_theme_to_active_codebook,
                args=(codebook_bytes, topic_choices),
                key="add_topic_to_active_btn",
                **stretch_kwargs(st.button),
                help="Appends this cluster to your active themes, immediately re-codes the corpus, and lets you save the updated YAML.",
            )

    # --------------------------------------------------------------------------
    # SUB-TAB 4: SPOT-CHECK MATCHES (Point #6 + spelling exclusion)
    # --------------------------------------------------------------------------
    with qtab_spotcheck:
        st.markdown("#### Spot-Check Matches")
        st.caption(
            "Flags theme matches worth a quick human check: keywords matched inside longer words "
            "(such as 'kid' inside 'kidding'), spelling-tolerance typo matches, nearby negation words "
            "('not', 'never', 'didn\\'t'), and short keywords without exclusion words."
        )
        if quotes.empty:
            st.info("No theme matches to spot-check in the current corpus.")
        elif audit_df.empty:
            st.success(f"0 of {len(quotes)} theme matches flagged for review.")
        else:
            st.info("All flagged matches below are currently counted in your charts and tables until you exclude them.")
            n_flagged = len(audit_df)
            codes_series = audit_df["flag_codes"].astype(str) if "flag_codes" in audit_df.columns else pd.Series(dtype=str)
            n_spell = int(codes_series.str.contains("spelling_tolerance").sum())
            n_pref = int(codes_series.str.contains("prefix_extension").sum())
            n_ctx = int((audit_df["risk_level"] == "Medium").sum())
            st.markdown(
                f"**{n_flagged} of {len(quotes)} theme matches flagged for review** · "
                f"{SPOTCHECK_PRIORITY_PARTIAL}: **{n_pref}** · "
                f"{SPOTCHECK_PRIORITY_SPELLING}: **{n_spell}** · "
                f"{SPOTCHECK_PRIORITY_CONTEXT}: **{n_ctx}**"
            )

            audit_display = audit_df.copy()
            audit_display["review_priority"] = [
                spotcheck_priority_label(rl, fc)
                for rl, fc in zip(audit_display["risk_level"], audit_display["flag_codes"])
            ]
            summary_grouped = (
                audit_display.groupby(
                    ["review_priority", "domain_name", "matched_span", "full_word", "flag_reason", "suggested_fix"],
                    dropna=False,
                    as_index=False,
                )
                .size()
                .rename(columns={
                    "review_priority": "Review Priority",
                    "domain_name": "Theme",
                    "matched_span": "Matched",
                    "full_word": "Full Word",
                    "size": "Flagged Matches",
                    "flag_reason": "Why Flagged",
                    "suggested_fix": "Suggested Action",
                })
            )
            st.dataframe(summary_grouped, **stretch_kwargs(st.dataframe), hide_index=True)
            st.download_button(
                "Download Spot-Check Report (.csv)",
                data=audit_df.to_csv(index=False).encode("utf-8"),
                file_name="atlas_spot_check_report.csv",
                mime="text/csv",
                key="download_spotcheck_csv",
                **stretch_kwargs(st.download_button),
            )

            st.markdown("---")
            st.markdown("##### Exclude false matches from a theme")
            st.caption("Tighten a noisy theme right here without editing YAML. Save your updated theme file from the sidebar or Exports tab when finished.")
            flagged_domains = (
                audit_df[["domain_id", "domain_name"]]
                .drop_duplicates()
                .sort_values(["domain_name", "domain_id"])
            )
            domain_choice_map = {
                f"{r['domain_name']} ({r['domain_id']})": (str(r["domain_id"]), str(r["domain_name"]))
                for _, r in flagged_domains.iterrows()
            }
            if st.session_state.get("spotcheck_fix_domain") not in domain_choice_map:
                st.session_state.pop("spotcheck_fix_domain", None)
            sc1, sc2 = st.columns([2, 2])
            picked_fix_label = sc1.selectbox("Theme to tighten", list(domain_choice_map), key="spotcheck_fix_domain")
            fix_domain_id, fix_domain_name = domain_choice_map[picked_fix_label]
            dom_audit = audit_df[audit_df["domain_id"].astype(str) == fix_domain_id]

            # Aggregate BOTH prefix-extension words AND spelling-tolerance words for actionable exclusion.
            excludable_words = sorted({
                w.strip().lower()
                for col_name in ("extension_words", "spelling_words")
                if col_name in dom_audit.columns
                for cell in dom_audit[col_name]
                for w in str(cell).split(",")
                if w.strip()
            })

            active_rules_by_id = {r["id"]: r for r in compiled_domains}
            target_rule = active_rules_by_id.get(fix_domain_id, {})
            existing_excludes = bool(target_rule.get("exclude_fences"))
            raw_excl_win = target_rule.get("exclude_window")
            existing_excl_win = int(float(raw_excl_win)) if raw_excl_win is not None else None
            if (not existing_excludes and existing_excl_win is None) or existing_excl_win == 0:
                excl_label = "Words to exclude from this theme"
                excl_help = "Blocks only these exact words without affecting other valid matches in the same entry."
                excl_scope_note = None
            elif existing_excl_win is not None:
                excl_label = f"Words to exclude (keeps existing {existing_excl_win}-word exclusion window)"
                excl_help = f"Preserves this theme's {existing_excl_win}-word exclusion window."
                excl_scope_note = (
                    f"Note: this theme already uses a {existing_excl_win}-word exclusion window. Excluding a word "
                    f"keeps that window intact."
                )
            else:
                excl_label = "Words to exclude (keeps existing entry-level exclusion window)"
                excl_help = "Preserves this theme's entry-level exclusion window."
                excl_scope_note = (
                    "Note: this theme already uses entry-level exclusions. Excluding a word suppresses the whole "
                    "entry whenever that word appears."
                )

            selected_exclude_words = []
            ext_key = None
            if excludable_words:
                ext_sig = hashlib.sha256(",".join(excludable_words).encode("utf-8")).hexdigest()[:8]
                ext_key = f"spotcheck_excl_{fix_domain_id}_{ext_sig}"
                selected_exclude_words = sc2.multiselect(
                    excl_label,
                    excludable_words,
                    default=excludable_words,
                    key=ext_key,
                    help=excl_help,
                )
                if excl_scope_note:
                    st.caption(excl_scope_note)
            b1, b2 = st.columns(2)
            b1.button(
                "Exclude Selected Words from Theme",
                on_click=apply_tightened_codebook,
                args=(codebook_bytes, domain_choice_map, picked_fix_label, ext_key, False),
                disabled=not selected_exclude_words,
                key="spotcheck_exclude_btn",
                **stretch_kwargs(st.button),
                help="Blocks the selected words (including any flagged spelling matches) and immediately re-codes.",
            )
            b2.button(
                "Switch Theme to Exact Whole-Word Matching",
                on_click=apply_tightened_codebook,
                args=(codebook_bytes, domain_choice_map, picked_fix_label, ext_key, True),
                key="spotcheck_exact_btn",
                **stretch_kwargs(st.button),
                help="Restricts prefix stems in this theme to whole words only.",
            )

            st.markdown("---")
            st.markdown("##### Flagged matches in context")
            sc_dom_options = ["All themes", *sorted(audit_display["domain_name"].astype(str).unique())]
            if st.session_state.get("spotcheck_dom_filter") not in sc_dom_options:
                st.session_state.pop("spotcheck_dom_filter", None)
            rf1, rf2 = st.columns(2)
            priority_options = [
                "All flagged matches",
                SPOTCHECK_PRIORITY_PARTIAL,
                SPOTCHECK_PRIORITY_SPELLING,
                SPOTCHECK_PRIORITY_CONTEXT,
            ]
            priority_filter = rf1.selectbox("Filter by review priority", priority_options, key="spotcheck_risk_filter")
            dom_filter_sc = rf2.selectbox("Filter by theme", sc_dom_options, key="spotcheck_dom_filter")
            shown_audit = audit_display
            if priority_filter != "All flagged matches":
                shown_audit = shown_audit[shown_audit["review_priority"] == priority_filter]
            if dom_filter_sc != "All themes":
                shown_audit = shown_audit[shown_audit["domain_name"].astype(str) == dom_filter_sc]
            st.caption(f"Showing {min(len(shown_audit), 25)} of {len(shown_audit)} flagged matches.")
            for _, row in shown_audit.head(25).iterrows():
                box_cls = "risk-high-box" if row["risk_level"] == "High" else "risk-medium-box"
                ev_badge = evidence_badge_html(row["evidence_type"]) if notes_present else ""
                st.markdown(
                    f'<div class="quote-box {box_cls}">'
                    f'<div class="quote-meta">{risk_badge_html(row["risk_level"], row["flag_codes"])}{ev_badge}'
                    f'{esc_inline(row["domain_name"])} · {esc_inline(row["speaker"])} · '
                    f'matched <code>{esc_inline(row["matched_span"])}</code> inside <code>{esc_inline(row["full_word"])}</code></div>'
                    f'<div style="font-size:0.92rem;color:#334155;margin-bottom:0.35rem;">'
                    f'<strong>Why flagged:</strong> {esc_inline(row["flag_reason"])}</div>'
                    f'<div class="quote-text">{highlighted_quote(row["text"], row["match_char_start"], row["match_char_end"])}</div>'
                    f'<div class="quote-provenance">SOURCE {esc_inline(row["source_id"])} · LINE {esc_inline(row["line_number"])} · '
                    f'ACTION: {esc_inline(row["suggested_fix"])}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ==============================================================================
# TAB 2: EXPORTS & AUDIT FILES
# ==============================================================================
with tab_exports:
    st.markdown("### Analyst Downloads")
    st.caption(
        "Download a printable Word summary report, an audited Excel frequency table, or CSV quote inventories "
        "matching the active run."
    )
    a1, a2, a3 = st.columns(3)
    a1.download_button(
        "Download Full Report (.docx)",
        data=full_report_docx,
        file_name="atlas_summary_report.docx",
        mime=DOCX_MIME,
        key="tab2_download_full_report",
        **stretch_kwargs(st.download_button),
    )
    a2.download_button(
        "Download Theme Frequencies (.xlsx)",
        data=results["exports"]["actuarial_parameter_matrix.xlsx"],
        file_name="actuarial_parameter_matrix.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="tab2_download_xlsx",
        **stretch_kwargs(st.download_button),
        help="Each prevalence cell carries an embedded ATLAS VERIFICATION AUDIT STAMP comment.",
    )
    a3.download_button(
        "Download Direct Quotes (.csv)",
        data=results["exports"]["verbatim_quotes_inventory.csv"],
        file_name="verbatim_quotes_inventory.csv",
        mime="text/csv",
        key="tab2_download_verbatim_csv",
        **stretch_kwargs(st.download_button),
        help="Verbatim words only: direct notable quotes, transcript turns, or survey answers.",
    )
    if CODED_EVIDENCE_CSV in results["exports"]:
        st.download_button(
            "Download All Coded Entries (.csv — quotes, paraphrases & observations)",
            data=results["exports"][CODED_EVIDENCE_CSV],
            file_name=CODED_EVIDENCE_CSV,
            mime="text/csv",
            key="tab2_download_coded_csv",
            **stretch_kwargs(st.download_button),
            help="Every coded row labeled by Source Type so paraphrases are never confused with direct quotes.",
        )

    st.markdown("---")
    if group_mode:
        st.info(
            "Statistical guardrail (Group mode): normal-approximation Binomial standard errors and 95% "
            f"confidence intervals are hidden because focus groups (G = {total_documents}) are small and "
            "participants in the same room influence one another. Report focus groups (g of G) and "
            "clearly labeled notes volume instead."
        )
    elif notes_present:
        st.info(
            "Statistical guardrail (structured focus-group notes): Binomial confidence intervals are hidden "
            "because each structured notes file represents a focus group, not independent survey respondents."
        )
    elif len(freq):
        st.markdown("#### Prevalence & Binomial Standard Errors (Individual Mode)")
        st.caption(
            f"N = {total_documents} analytical units. p = units reporting / N; "
            "Binomial SE = sqrt(p(1 - p) / N) on the proportion scale."
        )
        ci_df = freq.sort_values(
            ["prevalence_pct", "matching_turns", "domain_name"],
            ascending=[False, False, True],
            kind="mergesort",
        ).copy()
        p_vals = [int(d) / total_documents if total_documents else float("nan") for d in ci_df["documents_reporting"]]
        se_vals = [math.sqrt(v * (1 - v) / total_documents) if total_documents else float("nan") for v in p_vals]
        ci_df["proportion_p"] = [round(v, 4) for v in p_vals]
        ci_df["binomial_se"] = [round(v, 4) for v in se_vals]
        ci_df["ci95_low_pct"] = [round(max(0.0, (v - 1.96 * s) * 100), 1) for v, s in zip(p_vals, se_vals)]
        ci_df["ci95_high_pct"] = [round(min(100.0, (v + 1.96 * s) * 100), 1) for v, s in zip(p_vals, se_vals)]
        st.dataframe(
            ci_df[[
                "domain_name", "documents_reporting", "total_documents", "prevalence_pct",
                "proportion_p", "binomial_se", "ci95_low_pct", "ci95_high_pct", "matching_turns",
            ]],
            **stretch_kwargs(st.dataframe),
            hide_index=True,
            column_config={
                "domain_name": "Theme",
                "documents_reporting": "Units Reporting",
                "total_documents": "Analytical Units (N)",
                "prevalence_pct": st.column_config.NumberColumn("Prevalence (%)", format="%.1f"),
                "proportion_p": st.column_config.NumberColumn("Proportion (p)", format="%.4f"),
                "binomial_se": st.column_config.NumberColumn("Binomial SE", format="%.4f"),
                "ci95_low_pct": st.column_config.NumberColumn("95% CI Low (%)", format="%.1f"),
                "ci95_high_pct": st.column_config.NumberColumn("95% CI High (%)", format="%.1f"),
                "matching_turns": "Theme Matches",
            },
        )
        y_order_ci = list(ci_df["domain_id"].astype(str))
        ci_id_to_label = dict(zip(y_order_ci, ci_df["domain_name"].astype(str)))
        ci_label_expr = f"({json.dumps(ci_id_to_label)})[datum.value]"
        ci_bars = alt.Chart(ci_df).mark_bar(color=NAVY, cornerRadiusEnd=3).encode(
            x=alt.X("prevalence_pct:Q", title="Prevalence (% of analytical units, with 95% CI)", scale=alt.Scale(domain=[0, 105])),
            y=alt.Y("domain_id:N", sort=y_order_ci, title=None, axis=alt.Axis(labelLimit=360, labelExpr=ci_label_expr)),
            tooltip=[
                alt.Tooltip("domain_name:N", title="Theme"),
                alt.Tooltip("domain_id:N", title="Theme ID"),
                alt.Tooltip("prevalence_pct:Q", title="Prevalence (%)"),
                alt.Tooltip("ci95_low_pct:Q", title="95% CI Low (%)"),
                alt.Tooltip("ci95_high_pct:Q", title="95% CI High (%)"),
            ],
        )
        ci_rules = alt.Chart(ci_df).mark_rule(color=TEAL, strokeWidth=2.2).encode(
            x="ci95_low_pct:Q",
            x2="ci95_high_pct:Q",
            y=alt.Y("domain_id:N", sort=y_order_ci),
        )
        ci_summary = describe_prevalence_chart(ci_df, total_documents, include_ci=True)
        st.altair_chart(
            light_chart_surface(
                (ci_bars + ci_rules).properties(height=max(180, 44 * len(ci_df)), description=ci_summary)
            ),
            **stretch_kwargs(st.altair_chart),
        )
        st.html(chart_summary_html(ci_summary))

    st.markdown("---")
    st.markdown("### Audit & Reproducibility Files")
    if results["integrity_ok"]:
        st.success("Workbook integrity check passed: every prevalence cell and audit stamp matches the provenance manifest.")
    else:
        st.error("Workbook integrity check failed: " + "; ".join(results["integrity_problems"]))

    au1, au2 = st.columns(2)
    au1.download_button(
        "Download Provenance Manifest (.json)",
        data=results["exports"]["provenance_manifest.json"],
        file_name="provenance_manifest.json",
        mime="application/json",
        key="tab2_download_manifest",
        **stretch_kwargs(st.download_button),
    )
    au2.download_button(
        "Download Active Theme Rules (.yaml)",
        data=codebook_bytes,
        file_name="atlas_active_codebook.yaml",
        mime="application/x-yaml",
        key="tab2_download_codebook",
        **stretch_kwargs(st.download_button),
        help="Archive this exact YAML file alongside your exports so every coding rule stays reproducible.",
    )
    if spelling_tolerance and len(typo_df):
        st.download_button(
            f"Download Spelling-Tolerance Matches Inventory (.csv — {len(typo_df)} occurrences)",
            data=typo_df.to_csv(index=False).encode("utf-8"),
            file_name="atlas_typo_matches_inventory.csv",
            mime="text/csv",
            key="tab2_download_typos",
            **stretch_kwargs(st.download_button),
        )
    with st.expander("Source files and SHA-256 digests", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [{"Source File": k, "SHA-256": v} for k, v in results["file_hashes"].items()],
                columns=["Source File", "SHA-256"],
            ),
            **stretch_kwargs(st.dataframe), hide_index=True,
        )


# ==============================================================================
# TAB 3: REFERENCE GUIDES
# ==============================================================================
with tab_guides:
    render_reference_guides_tab()


# ------------------------------------------------------------------------------
# 7. Footer
# ------------------------------------------------------------------------------
render_footer()
