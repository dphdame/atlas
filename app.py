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
import pandas as pd
import streamlit as st
import yaml
from docx.opc.exceptions import PackageNotFoundError
from openpyxl.utils.exceptions import InvalidFileException

try:  # python-docx parses document.xml with lxml; a malformed part raises XMLSyntaxError.
    from lxml.etree import LxmlError
except ImportError:  # pragma: no cover - lxml ships with python-docx
    class LxmlError(Exception):
        pass

from atlas_discover import discover_topics, topics_to_codebook_dict
from atlas_engine import (
    AtlasEngine,
    append_topic_to_codebook,
    audit_false_alarm_risks,
    has_non_verbatim_evidence,
    merge_codebook_dicts,
    summarize_false_alarm_risks,
    tighten_codebook_domain,
    verbatim_only as verbatim_rows,
)
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

CORPUS_BILINGUAL = "Sample: Bilingual Interview Transcripts (SOFTWARE_TEST)"
CORPUS_SURVEY = "Sample: Community Health Survey CSV (SOFTWARE_TEST)"
CORPUS_DOCX = "Sample: Teams Multiline Transcript DOCX (SOFTWARE_TEST)"
CORPUS_GBI_NOTES = "Sample: Multi-Group Focus-Group Notes DOCX (SOFTWARE_TEST)"
CORPUS_UPLOAD = "Upload Custom Files (.docx, .vtt, .srt, .txt, .md, .csv, .xlsx)"

SAMPLE_CORPORA = {
    CORPUS_BILINGUAL: {
        "files": ["software_test_bilingual_interview.txt", "software_test_zoom_session.vtt"],
        "tabular_options": None,
        "codebook": "pfl_case_study_codebook.yaml",
    },
    CORPUS_SURVEY: {
        "files": ["software_test_survey.csv"],
        "tabular_options": {"text_col": "response", "id_col": "respondent_id", "speaker_col": "role"},
        "codebook": "pfl_case_study_codebook.yaml",
    },
    CORPUS_DOCX: {
        "files": ["software_test_teams_multiline.docx"],
        "tabular_options": None,
        "codebook": "intake_and_enrollment.yaml",
    },
    CORPUS_GBI_NOTES: {
        "files": ["software_test_gbi_group_treatment.docx", "software_test_gbi_group_control.docx"],
        "tabular_options": None,
        "codebook": "gbi_focus_group_starter.yaml",
    },
}
CORPUS_OPTIONS = [*SAMPLE_CORPORA, CORPUS_UPLOAD]
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
    "Domain ID", "Domain", "Groups Reporting", "Total Groups (G)", "Group Share (%)",
    "Distinct Participant Voices", "Verbatim Quotes", "Paraphrased Key Points", "Matching Entries",
]
THEMES_EXPANDER_LABEL = "Note-Taker Themes Summary (Reference Only — Not Counted in Prevalence)"
CODED_EVIDENCE_CSV = "coded_evidence_inventory.csv"
NOTES_STRUCTURE = "focus_group_notes"
# (text colour, background colour, label) per evidence type; every pair is >= 4.5:1.
EVIDENCE_BADGE_STYLES = {
    "notable_quote_verbatim": ("#FFFFFF", TEAL, "Verbatim Quote"),
    "key_point_paraphrase": ("#FFFFFF", SLATE, "Paraphrase (Key Point)"),
    "observation": (NAVY, "#FFFFFF", "Observation"),
}
EVIDENCE_BADGE_FALLBACK = ("#FFFFFF", "#475569", "Transcript / Survey")
# Group x theme tiles: state -> (fill, text colour), each text/fill pair >= 4.5:1.
GROUP_TILE_COLOURS = {
    "none": ("#F1F5F9", "#475569"),
    "unknown_only": ("#CCFBF1", TEAL),
    "voices": (NAVY, "#FFFFFF"),
}

SOFTWARE_TEST_BANNER = (
    "🧪 SOFTWARE_TEST FIXTURE ACTIVE — Built-in sample files demonstrate software "
    "mechanics only and are not empirical research findings."
)

REFERENCE_GUIDES = [
    ("📋 GBI Analyst Quick-Start Guide (Markdown)", "ATLAS_GBI_Analyst_Quick_Start.md"),
    ("📘 User Guide (Markdown)", "ATLAS_User_Guide.md"),
    ("📗 Methodology & Reference Manual (Markdown)", "ATLAS_Methodology_and_Reference_Manual.md"),
    ("📙 Practitioner Field Guide (Markdown)", "ATLAS_Practitioner_Field_Guide_Program_Evaluation.md"),
]

DISCOVERY_METHOD_NMF = "TF-IDF + NMF (Recommended — faster, sharper keywords)"
DISCOVERY_METHOD_LDA = "LDA (Classic bag-of-words)"
DISCOVERY_METHOD_MAP = {DISCOVERY_METHOD_NMF: "nmf", DISCOVERY_METHOD_LDA: "lda"}

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
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    f"""
<style>
.main .block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px; }}
.brand-header {{ background: #FFFFFF; border: 1px solid #CBD5E1; border-top: 6px solid {NAVY};
  padding: 1.5rem 2rem; border-radius: 8px; margin-bottom: 1.25rem; }}
.brand-header h1 {{ color: {NAVY} !important; font-size: 1.85rem !important; font-weight: 800 !important;
  margin: 0 0 0.4rem 0 !important; }}
.brand-header p {{ color: #1E293B !important; font-size: 1.05rem !important; margin: 0 0 0.9rem 0 !important; }}
.badge-row {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
.atlas-badge {{ display: inline-block; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.03em;
  padding: 0.25rem 0.7rem; border-radius: 4px; color: #FFFFFF; background: {NAVY}; }}
.atlas-badge-teal {{ background: {TEAL}; }}
.atlas-badge-outline {{ background: #FFFFFF; color: {NAVY}; border: 2px solid {NAVY}; }}
.quote-box {{ background: #F8FAFC; border: 1px solid #E2E8F0; border-left: 4px solid {TEAL};
  padding: 1rem 1.25rem; border-radius: 6px; margin-bottom: 0.9rem; }}
.topic-box {{ border-left-color: {NAVY}; }}
.risk-high-box {{ border-left-color: #B91C1C; }}
.risk-medium-box {{ border-left-color: #92400E; }}
.risk-badge {{ display: inline-block; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.03em;
  padding: 0.12rem 0.45rem; border-radius: 3px; color: #FFFFFF; margin-right: 0.45rem; }}
.risk-badge-high {{ background: #B91C1C; }}
.risk-badge-medium {{ background: #92400E; }}
.quote-meta {{ font-size: 0.85rem; font-weight: 700; color: {TEAL}; margin-bottom: 0.35rem; }}
.topic-box .quote-meta {{ color: {NAVY}; }}
.quote-text {{ font-size: 1rem; color: #0F172A; line-height: 1.6; margin-bottom: 0.5rem; white-space: pre-wrap; }}
.quote-text mark {{ background: #FEF08A; color: #0F172A; padding: 0 0.1rem; }}
.quote-provenance {{ font-size: 0.8rem; font-family: monospace; color: #334155; background: #E2E8F0;
  padding: 0.2rem 0.5rem; border-radius: 3px; display: inline-block; }}
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


def build_group_frequency_table(freq, quotes, total_groups):
    """One row per codebook domain: groups reporting (g of G) and the evidence behind it."""
    rows = []
    for _, r in freq.iterrows():
        dq = quotes[quotes["domain_id"].astype(str) == str(r["domain_id"])]
        evidence = dq["evidence_type"].astype(str) if "evidence_type" in dq.columns else pd.Series(dtype=str)
        rows.append({
            "Domain ID": str(r["domain_id"]),
            "Domain": str(r["domain_name"]),
            "Groups Reporting": int(r["documents_reporting"]),
            "Total Groups (G)": int(total_groups),
            "Group Share (%)": float(r["prevalence_pct"]),
            "Distinct Participant Voices": count_distinct_voices(dq),
            "Verbatim Quotes": int((evidence == "notable_quote_verbatim").sum()),
            "Paraphrased Key Points": int((evidence == "key_point_paraphrase").sum()),
            "Matching Entries": len(dq),
        })
    return pd.DataFrame(rows, columns=GROUP_TABLE_COLUMNS)


def build_group_theme_matrix(freq, quotes, file_hashes):
    """
    One row per (domain, focus-group file): whether the group reported the domain,
    its matching entries, its distinct participant voices and the tile label
    ("<n>v" voices, "✓" matched only by unattributed entries, "—" not reported).
    """
    source_ids = sorted(str(s) for s in file_hashes)
    labels = group_labels_for(source_ids)
    rows = []
    for _, r in freq.iterrows():
        dq = quotes[quotes["domain_id"].astype(str) == str(r["domain_id"])]
        for sid in source_ids:
            gq = dq[dq["source_id"].astype(str) == sid]
            n = len(gq)
            voices = len({str(p) for p in gq["speaker"] if str(p) not in NON_VOICE_SPEAKERS})
            state = "voices" if voices else ("unknown_only" if n else "none")
            rows.append({
                "domain_id": str(r["domain_id"]),
                "domain_name": str(r["domain_name"]),
                "source_id": sid,
                "group_label": labels[sid],
                "present": n > 0,
                "matching_entries": n,
                "distinct_voices": voices,
                "cell_label": f"{voices}v" if voices else ("✓" if n else "—"),
                "tile_state": state,
            })
    return pd.DataFrame(rows, columns=["domain_id", "domain_name", "source_id", "group_label", "present",
                                       "matching_entries", "distinct_voices", "cell_label", "tile_state"])


def describe_group_prevalence_chart(group_df, total_groups):
    """
    Plain-text summary of the Groups Reporting (g of G) bar chart, for the Vega-Lite
    description and the visible st.html summary. Deterministic: built only from
    group_df (GROUP_TABLE_COLUMNS); lists the three domains reported by the most
    groups, ordered by groups reporting descending, then domain name.
    """
    if group_df is None or len(group_df) == 0:
        return "No domains defined in the active codebook."
    k = len(group_df)
    domains = "domain" if k == 1 else "domains"
    total = int(total_groups)
    if total <= 0:
        return f"Horizontal bar chart with 0 focus groups, so no group count is defined for the {k} coded {domains}."
    groups = "focus group" if total == 1 else "focus groups"

    def count(value):
        number = pd.to_numeric(value, errors="coerce")
        return int(number) if pd.notna(number) and math.isfinite(float(number)) else 0

    rows = group_df.assign(
        _name=group_df["Domain"].astype(str),
        _groups=group_df["Groups Reporting"].map(count),
        _voices=group_df["Distinct Participant Voices"].map(count),
    ).sort_values(["_groups", "_name"], ascending=[False, True], kind="mergesort")
    matched = rows[rows["_groups"] > 0]
    lead = f"Horizontal bar chart of focus groups reporting each domain, out of {total} {groups}."
    if matched.empty:
        return f"{lead} No group reported any of the {k} coded {domains}."
    listed = []
    for _, r in matched.head(3).iterrows():
        voices = "voice" if r["_voices"] == 1 else "voices"
        listed.append(f"{r['_name']} {r['_groups']} of {total} {groups} ({r['_voices']} distinct participant {voices})")
    text = f"{lead} Reported by the most groups: {'; '.join(listed)}."
    if len(matched) > 3:
        text += f" Other reported domains not listed: {len(matched) - 3}."
    if len(matched) < k:
        text += f" Domains reported by no group: {k - len(matched)} of {k}."
    return text


def describe_group_matrix_chart(matrix_df, total_groups):
    """
    Plain-text summary of the group x theme tile matrix (Vega-Lite description and
    st.html summary). Deterministic: built only from matrix_df
    (build_group_theme_matrix); groups are listed in label order.
    """
    if matrix_df is None or len(matrix_df) == 0:
        return "No domains defined in the active codebook."
    k = matrix_df["domain_id"].astype(str).nunique()
    domains = "domain" if k == 1 else "domains"
    total = int(total_groups)
    groups = "focus group" if total == 1 else "focus groups"
    present = matrix_df["present"].astype(bool)
    per_group = []
    for label in sorted(matrix_df["group_label"].astype(str).unique()):
        n = int(present[matrix_df["group_label"].astype(str) == label].sum())
        per_group.append(f"{label} {n} of {k}")
    return (f"Tile matrix of {k} coded {domains} by {total} {groups}. "
            f"{int(present.sum())} of {len(matrix_df)} domain-group tiles have at least one matching entry. "
            f"Domains reported per group: {'; '.join(per_group)}.")


def group_prevalence_chart(group_df, total_groups):
    """Integer Groups Reporting (g of G) bar chart, labelled g/G."""
    total = int(total_groups)
    top = max(total, 1)
    data = pd.DataFrame({
        "domain_name": group_df["Domain"].astype(str),
        "groups_reporting": group_df["Groups Reporting"].astype(int),
        "distinct_voices": group_df["Distinct Participant Voices"].astype(int),
        "bar_label": [f"{int(g)}/{total}" for g in group_df["Groups Reporting"]],
    })
    x = alt.X("groups_reporting:Q", title=f"Groups Reporting (out of {total} focus groups)",
              scale=alt.Scale(domain=[0, top]), axis=alt.Axis(values=list(range(0, top + 1)), format="d"))
    bars = alt.Chart(data).mark_bar(color=NAVY).encode(
        x=x,
        y=alt.Y("domain_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
        tooltip=[
            alt.Tooltip("domain_name:N", title="Domain"),
            alt.Tooltip("groups_reporting:Q", title="Groups reporting", format="d"),
            alt.Tooltip("distinct_voices:Q", title="Distinct participant voices", format="d"),
        ],
    )
    labels = alt.Chart(data).mark_text(align="left", dx=4, color="#0F172A").encode(
        x="groups_reporting:Q", y=alt.Y("domain_name:N", sort="-x"), text="bar_label:N",
    )
    return bars + labels


def group_matrix_chart(matrix_df):
    """Group x theme tile matrix: fill and text colour encode the tile state."""
    states = list(GROUP_TILE_COLOURS)
    base = alt.Chart(matrix_df).encode(
        x=alt.X("group_label:N", title="Focus group", sort=sorted(matrix_df["group_label"].astype(str).unique()),
                axis=alt.Axis(labelAngle=0, labelLimit=240, orient="top")),
        y=alt.Y("domain_name:N", title=None, sort=list(dict.fromkeys(matrix_df["domain_name"].astype(str))),
                axis=alt.Axis(labelLimit=320)),
    )
    tiles = base.mark_rect(stroke="#FFFFFF", strokeWidth=2).encode(
        color=alt.Color("tile_state:N", legend=None,
                        scale=alt.Scale(domain=states, range=[GROUP_TILE_COLOURS[s][0] for s in states])),
        tooltip=[
            alt.Tooltip("domain_name:N", title="Domain"),
            alt.Tooltip("group_label:N", title="Focus group"),
            alt.Tooltip("matching_entries:Q", title="Matching entries", format="d"),
            alt.Tooltip("distinct_voices:Q", title="Distinct participant voices", format="d"),
        ],
    )
    text = base.mark_text(fontWeight="bold").encode(
        text="cell_label:N",
        color=alt.Color("tile_state:N", legend=None,
                        scale=alt.Scale(domain=states, range=[GROUP_TILE_COLOURS[s][1] for s in states])),
    )
    return (tiles + text).resolve_scale(color="independent")


def light_chart_surface(chart):
    """Coordinated light chart surface so marks and labels keep their contrast on any app theme."""
    return (chart.configure(background="#FFFFFF")
            .configure_view(fill="#FFFFFF", stroke="#64748B")
            .configure_axis(labelColor="#1E293B", titleColor="#0F172A", domainColor="#64748B",
                            tickColor="#64748B", gridColor="#E2E8F0")
            .configure_title(color="#0F172A")
            .configure_legend(labelColor="#1E293B", titleColor="#0F172A"))


def evidence_badge_html(evidence_type):
    """High-contrast badge naming a quote's evidence type (escaped, never Markdown)."""
    fg, bg, label = EVIDENCE_BADGE_STYLES.get(str(evidence_type), EVIDENCE_BADGE_FALLBACK)
    border = fg if bg == "#FFFFFF" else bg
    return (f'<span class="atlas-evidence-badge" style="display:inline-block;font-size:0.75rem;font-weight:700;'
            f'padding:0.1rem 0.5rem;border-radius:4px;margin-right:0.4rem;color:{fg};background-color:{bg};'
            f'border:2px solid {border};">{html.escape(label)}</span>')


@st.cache_data(show_spinner=False)
def read_table_columns(name, payload):
    """Columns and rows of an uploaded table exactly as the parser reads them."""
    ext = os.path.splitext(name)[1].lower()
    with tempfile.TemporaryDirectory(prefix="atlas_preview_") as tmp:
        path = Path(tmp) / safe_upload_name(name, set())  # parser errors name the user's file
        path.write_bytes(payload)
        if ext == ".csv":
            frame, _ = UniversalTranscriptParser()._read_csv(str(path))
        else:
            frame = pd.read_excel(path, dtype=str, keep_default_na=False, na_filter=False)
    frame.columns = [str(c) for c in frame.columns]
    return frame


@st.cache_data(show_spinner=False)
def detect_structured_notes(name, payload):
    """Whether a .docx payload holds a structured notes table; unreadable files are not notes."""
    if os.path.splitext(str(name))[1].lower() != ".docx":
        return False
    with tempfile.TemporaryDirectory(prefix="atlas_detect_") as tmp:
        path = Path(tmp) / safe_upload_name(name, set())
        path.write_bytes(payload)
        try:
            return UniversalTranscriptParser.detect_docx_structure(str(path)) == "structured_notes"
        except UPLOAD_READ_ERRORS:
            return False


@st.cache_data(show_spinner=False)
def analyze_corpus(codebook_bytes, inputs, tabular_items, facilitators, prompt_patterns, notes_evidence=None,
                   group_by_source=False):
    """
    Run UniversalTranscriptParser -> AtlasEngine on byte copies of the inputs.
    notes_evidence (Group mode) is the tuple of notes evidence types to code;
    None keeps the parser defaults.

    inputs is a tuple of (relative_path, bytes); the files are written under a
    fresh temporary root with those relative paths, so each source_id equals the
    relative path and each source_sha256 is the SHA-256 of the exact bytes.
    The engine's own export (xlsx with audit-stamp comments, provenance manifest,
    quotes CSV) is produced in the same temporary root and returned as bytes.
    Two relative paths that one case- or normalization-insensitive filesystem
    maps to the same file are refused, so no payload can overwrite another.
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
    results["false_alarm_audit_df"] = audit_false_alarm_risks(results["quotes_df"], engine.domains)
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


def apply_discovered_codebook(label, yaml_bytes):
    st.session_state.discovered_codebooks[label] = yaml_bytes
    st.session_state.codebook_choice = label
    st.session_state.stacked_codebooks = []


def add_theme_to_active_codebook(current_bytes, topic, custom_name, match_mode):
    current_dict = yaml.safe_load(current_bytes) or {}
    updated_dict = append_topic_to_codebook(
        current_dict,
        topic,
        domain_name=str(custom_name or "").strip() or None,
        match_mode=match_mode,
    )
    new_domain = updated_dict["domains"][-1]
    updated_bytes = yaml.safe_dump(updated_dict, allow_unicode=True, sort_keys=False).encode("utf-8")
    base = f"Custom: +{new_domain['name']} ({len(updated_dict['domains'])} domains)"
    label, idx = base, 2
    while label in st.session_state.discovered_codebooks:
        label = f"{base} #{idx}"
        idx += 1
    st.session_state.discovered_codebooks[label] = updated_bytes
    st.session_state.codebook_choice = label
    st.session_state.stacked_codebooks = []
    st.session_state.add_topic_name = ""


def apply_tightened_codebook(current_bytes, domain_id, domain_name, exclude_words, set_exact_mode):
    words = [str(w).strip() for w in (exclude_words or []) if str(w).strip()]
    if not words and not set_exact_mode:
        return
    current_dict = yaml.safe_load(current_bytes) or {}
    updated_dict = tighten_codebook_domain(
        current_dict,
        domain_id,
        add_exclude_terms=words,
        set_exact_mode=bool(set_exact_mode),
    )
    updated_bytes = yaml.safe_dump(updated_dict, allow_unicode=True, sort_keys=False).encode("utf-8")
    action = "exact" if set_exact_mode and not words else "fenced"
    base = f"Custom: {domain_name} ({action}, {len(updated_dict['domains'])} domains)"
    label, idx = base, 2
    while label in st.session_state.discovered_codebooks:
        label = f"{base} #{idx}"
        idx += 1
    st.session_state.discovered_codebooks[label] = updated_bytes
    st.session_state.codebook_choice = label
    st.session_state.stacked_codebooks = []


def risk_badge_html(risk_level):
    level = str(risk_level or "")
    cls = "risk-badge-high" if level == "High" else "risk-badge-medium"
    label = "HIGH RISK" if level == "High" else "MEDIUM RISK"
    return f'<span class="risk-badge {cls}">{label}</span>'


if "discovered_codebooks" not in st.session_state:
    st.session_state.discovered_codebooks = {}
if "stacked_codebooks" not in st.session_state:
    st.session_state.stacked_codebooks = []


# ------------------------------------------------------------------------------
# 3. Sidebar: corpus, codebook and parser controls
# ------------------------------------------------------------------------------
config_codebooks = list_config_codebooks()

with st.sidebar:
    st.markdown("### Inputs & Codebook")

    corpus_choice = st.selectbox("Corpus Dataset", CORPUS_OPTIONS, index=0)

    uploaded_files = []
    tabular_options = None
    tabular_error = None
    facilitator_names = []
    prompt_patterns = []
    if corpus_choice == CORPUS_UPLOAD:
        uploaded_files = st.file_uploader(
            "Upload Transcript or Tabular Files",
            type=UPLOAD_TYPES,
            accept_multiple_files=True,
        ) or []
        tabular_uploads = [f for f in uploaded_files if os.path.splitext(f.name)[1].lower() in TABULAR_EXTENSIONS]
        # Uploads that share a filename are labelled by position so each keeps its own entry.
        name_counts = {}
        for f in tabular_uploads:
            name_counts[f.name] = name_counts.get(f.name, 0) + 1
        upload_labels = [f"{f.name} (#{idx + 1})" if name_counts[f.name] > 1 else f.name
                         for idx, f in enumerate(tabular_uploads)]
        frames = []
        for f, label in zip(tabular_uploads, upload_labels):
            try:
                frames.append(read_table_columns(f.name, f.getvalue()))
            except UPLOAD_READ_ERRORS as exc:
                tabular_error = f"Could not read '{label}': {exc}"
                break
        if tabular_uploads and not tabular_error:
            shared = [c for c in frames[0].columns if all(c in fr.columns for fr in frames[1:])]
            text_choices = [c for c in shared if not is_id_column(c)]
            if not shared:
                tabular_error = (
                    "The uploaded tables share no column names, so one text column cannot be applied to all "
                    "of them. Upload tables with the same header, or analyse them one at a time."
                )
            elif not text_choices:
                tabular_error = (
                    "No free-text column found: every shared column is an id column "
                    f"({', '.join(shared)}). Add a response column, or rename it so it is not called 'id' "
                    "or '*_id'."
                )
            else:
                # One text column is applied to every table, so each table must agree on it.
                detected_entries = [
                    (label, detect_text_column(fr[text_choices])) for label, fr in zip(upload_labels, frames)
                ]
                if len({col for _, col in detected_entries}) > 1:
                    tabular_error = (
                        "The uploaded tables keep their free text in different columns ("
                        + "; ".join(f"{label}: {col}" for label, col in detected_entries)
                        + "). ATLAS applies one text column to every table, so upload these tables one at a time."
                    )
                else:
                    st.markdown("**Table columns** (.csv / .xlsx)")
                    detected = detected_entries[0][1]
                    text_col = st.selectbox(
                        "Text column (free-text responses)", text_choices, index=text_choices.index(detected),
                        help="Auto-detected; id and *_id columns are never offered as the text column.",
                    )
                    id_col = st.selectbox("Respondent ID column (optional)", [NONE_OPTION, *shared], index=0)
                    speaker_col = st.selectbox("Speaker / role column (optional)", [NONE_OPTION, *shared], index=0)
                    empty_in = [label for label, fr in zip(upload_labels, frames)
                                if not any(str(v).strip() for v in fr[text_col].tolist())]
                    if empty_in:
                        tabular_error = (
                            f"The text column '{text_col}' is empty in {', '.join(empty_in)}. Choose the column "
                            "that holds the responses in every table, or upload the tables one at a time."
                        )
                    else:
                        tabular_options = {"text_col": text_col}
                        if id_col != NONE_OPTION:
                            tabular_options["id_col"] = id_col
                        if speaker_col != NONE_OPTION:
                            tabular_options["speaker_col"] = speaker_col
        names_raw = st.text_input(
            "Facilitator names (optional, comma-separated)", "",
            help="Turns by these speakers are treated as facilitator prompts and excluded from coding.",
        )
        facilitator_names = [n.strip() for n in names_raw.split(",") if n.strip()]
        patterns_raw = st.text_area(
            "Interviewer prompt patterns (optional, one regular expression per line)", "",
            help="Speakerless turns matching a pattern are excluded as interviewer prompts.",
        )
        prompt_patterns = [p.strip() for p in patterns_raw.splitlines() if p.strip()]

    # Data Type follows the inputs: whenever the selected corpus changes, Group mode is
    # chosen if any .docx holds a structured notes table. The user may override it.
    selected_sample = SAMPLE_CORPORA.get(corpus_choice)
    if selected_sample is not None:
        detect_items = [(name, (SAMPLES_DIR / name).read_bytes()) for name in selected_sample["files"]]
    else:
        detect_items = [(f.name, f.getvalue()) for f in uploaded_files]
    data_type_fingerprint = (
        corpus_choice,
        tuple((name, len(payload), hashlib.sha256(payload).hexdigest()) for name, payload in detect_items),
    )
    if st.session_state.get("data_type_fingerprint") != data_type_fingerprint:
        st.session_state.data_type_fingerprint = data_type_fingerprint
        st.session_state.data_type = (
            DATA_TYPE_GROUP if any(detect_structured_notes(name, payload) for name, payload in detect_items)
            else DATA_TYPE_INDIVIDUAL
        )
    data_type = st.radio(
        "Data Type", DATA_TYPES, key="data_type",
        help="Group mode treats each file as one focus group (1 file = 1 group). It is chosen automatically "
             "for structured focus-group notes and can be switched at any time.",
    )
    group_mode = data_type == DATA_TYPE_GROUP
    notes_evidence = None
    if group_mode:
        include_observations = st.checkbox(
            "Include Note-Taker Observations", value=False,
            help="Also code the Observations column of structured notes (key points and notable quotes are "
                 "always coded).",
        )
        notes_evidence = NOTES_EVIDENCE_WITH_OBSERVATIONS if include_observations else NOTES_EVIDENCE_CORE

    # Default the codebook to the one suited to the selected sample whenever the corpus changes.
    if st.session_state.get("last_corpus_choice") != corpus_choice:
        st.session_state.last_corpus_choice = corpus_choice
        suggested = SAMPLE_CORPORA.get(corpus_choice, {}).get("codebook")
        if suggested in config_codebooks:
            st.session_state.codebook_choice = suggested
    codebook_options = [*config_codebooks, *st.session_state.discovered_codebooks, CODEBOOK_UPLOAD]
    if st.session_state.get("codebook_choice") not in codebook_options:
        st.session_state.codebook_choice = codebook_options[0]
    codebook_choice = st.selectbox("Active YAML Codebook", codebook_options, key="codebook_choice")

    uploaded_codebook = None
    if codebook_choice == CODEBOOK_UPLOAD:
        uploaded_codebook = st.file_uploader("Upload Custom Codebook (.yaml)", type=["yaml", "yml"])

    extra_choices = [cb for cb in config_codebooks if cb != codebook_choice]
    st.session_state.stacked_codebooks = [
        cb for cb in st.session_state.get("stacked_codebooks", []) if cb in extra_choices
    ]
    extra_codebooks = st.multiselect(
        "Stack Additional Starter Codebooks (optional)",
        extra_choices,
        key="stacked_codebooks",
        help="Combine domains from additional starter codebooks with the active codebook without editing YAML by hand.",
    )

    st.markdown("---")
    st.markdown("### Reference Guides")
    for label, filename in REFERENCE_GUIDES:
        guide = DOCS_DIR / filename
        if guide.is_file():
            st.download_button(
                label=label, data=guide.read_bytes(), file_name=filename,
                mime="text/markdown", **stretch_kwargs(st.download_button), key=f"guide_{filename}",
            )


# ------------------------------------------------------------------------------
# 4. Header and fixture notice
# ------------------------------------------------------------------------------
st.markdown(
    """
<div class="brand-header">
<h1>ATLAS</h1>
<p>Local qualitative coding, topic discovery, and auditable frequency tables for transcripts and surveys.</p>
</div>
""",
    unsafe_allow_html=True,
)

sample = SAMPLE_CORPORA.get(corpus_choice)
uploaded_fixture = any("software_test" in f.name.lower() for f in uploaded_files)
if sample is not None or uploaded_fixture:
    st.info(SOFTWARE_TEST_BANNER)


# ------------------------------------------------------------------------------
# 5. Resolve inputs and run the live engine
# ------------------------------------------------------------------------------
if sample is not None:
    inputs = tuple(
        ((SAMPLES_DIR / name).relative_to(APP_DIR).as_posix(), (SAMPLES_DIR / name).read_bytes())
        for name in sample["files"]
    )
    tabular_options = sample["tabular_options"]
    corpus_label = corpus_choice
else:
    if not uploaded_files:
        st.info("Upload one or more transcript or tabular files in the sidebar to start the analysis.")
        st.stop()
    if tabular_error:
        st.error(tabular_error)
        st.stop()
    if any(os.path.splitext(f.name)[1].lower() in TABULAR_EXTENSIONS for f in uploaded_files) and not tabular_options:
        st.error("Choose a text column for the uploaded tables before analysis.")
        st.stop()
    taken = set()
    inputs = tuple((f"uploads/{safe_upload_name(f.name, taken)}", f.getvalue()) for f in uploaded_files)
    unsupported = [rel for rel, _ in inputs
                   if os.path.splitext(rel)[1].lower() not in TRANSCRIPT_EXTENSIONS | TABULAR_EXTENSIONS]
    if unsupported:
        st.error(f"Unsupported file type: {', '.join(unsupported)}")
        st.stop()
    corpus_label = ", ".join(os.path.basename(rel) for rel, _ in inputs)

if codebook_choice == CODEBOOK_UPLOAD:
    if uploaded_codebook is None:
        st.info("Upload a YAML codebook in the sidebar, or choose one from the list.")
        st.stop()
    primary_codebook_bytes = uploaded_codebook.getvalue()
    primary_codebook_label = uploaded_codebook.name
elif codebook_choice in st.session_state.discovered_codebooks:
    primary_codebook_bytes = st.session_state.discovered_codebooks[codebook_choice]
    primary_codebook_label = codebook_choice
else:
    primary_codebook_bytes = (CONFIG_DIR / codebook_choice).read_bytes()
    primary_codebook_label = codebook_choice

if extra_codebooks:
    try:
        primary_dict = yaml.safe_load(primary_codebook_bytes)
        if not isinstance(primary_dict, dict):
            raise ValueError(f"Primary codebook {primary_codebook_label!r} must be a YAML mapping.")
        to_merge = [(primary_codebook_label, primary_dict)]
        for extra_name in extra_codebooks:
            extra_dict = yaml.safe_load((CONFIG_DIR / extra_name).read_bytes())
            if not isinstance(extra_dict, dict):
                raise ValueError(f"Stacked codebook {extra_name!r} must be a YAML mapping.")
            to_merge.append((extra_name, extra_dict))
        merged_dict = merge_codebook_dicts(to_merge)
        codebook_bytes = yaml.safe_dump(merged_dict, allow_unicode=True, sort_keys=False).encode("utf-8")
    except (*UPLOAD_READ_ERRORS, yaml.YAMLError) as exc:
        st.error(f"ATLAS could not combine the selected codebooks: {exc}")
        st.stop()
    active_codebook_label = " + ".join([primary_codebook_label, *extra_codebooks])
else:
    codebook_bytes = primary_codebook_bytes
    active_codebook_label = primary_codebook_label

is_custom_or_stacked = bool(extra_codebooks or codebook_choice in st.session_state.discovered_codebooks)
if is_custom_or_stacked:
    with st.sidebar:
        st.download_button(
            "📥 Download Active Codebook (.yaml)",
            data=codebook_bytes,
            file_name="atlas_active_codebook.yaml",
            mime="application/x-yaml",
            key="download_active_codebook_sidebar",
            help="Save a copy of the exact stacked or customized YAML codebook alongside your export files.",
            **stretch_kwargs(st.download_button),
        )

bad_patterns = []
for pattern in prompt_patterns:
    try:
        re.compile(pattern)
    except re.error as exc:
        bad_patterns.append(f"{pattern!r} ({exc})")
if bad_patterns:
    st.error("Invalid interviewer prompt pattern: " + "; ".join(bad_patterns))
    st.stop()

try:
    with st.spinner("Parsing and coding the corpus..."):
        results = analyze_corpus(
            codebook_bytes,
            inputs,
            tuple(sorted(tabular_options.items())) if tabular_options else None,
            tuple(facilitator_names),
            tuple(prompt_patterns),
            notes_evidence,
            group_mode,
        )
except (*UPLOAD_READ_ERRORS, RuntimeError, yaml.YAMLError) as exc:
    st.error(f"ATLAS could not analyse this corpus with this codebook: {exc}")
    st.stop()

freq = results["frequencies_df"]
quotes = results["quotes_df"]
total_documents = int(results["total_documents"])
participant_turns = int(results["participant_turns_analyzed"])
matched_mentions = int(freq["matching_turns"].sum()) if len(freq) else 0
# Structured notes are always counted one unit per focus-group file, so the binomial
# interval is withheld for them whatever the Data Type, and their coded entries are
# labelled by evidence type wherever verbatim words could be implied.
notes_present = NOTES_STRUCTURE in set(results.get("document_structures", {}).values())

if group_mode:
    group_labels = group_labels_for(results["file_hashes"])
    group_table = build_group_frequency_table(freq, quotes, total_documents)
    group_summary = describe_group_prevalence_chart(group_table, total_documents)
    group_matrix = build_group_theme_matrix(freq, quotes, results["file_hashes"])
    matrix_summary = describe_group_matrix_chart(group_matrix, total_documents)
    group_table_config = {
        "Group Share (%)": st.column_config.NumberColumn("Group Share (%)", format="%.1f"),
    }
    themes_df = results.get("note_taker_themes_df")
    if themes_df is None:
        themes_df = pd.DataFrame()


# ------------------------------------------------------------------------------
# 6. Dual-track interface
# ------------------------------------------------------------------------------
tab_thematic, tab_econometric = st.tabs([
    "🔍 Tab 1: Standalone Thematic Discovery & Qualitative Coding",
    "📊 Tab 2: Econometric & Actuarial Ledger Export",
])

# ==============================================================================
# TAB 1: STANDALONE THEMATIC DISCOVERY & QUALITATIVE CODING
# ==============================================================================
with tab_thematic:
    st.markdown("### Qualitative Thematic Workbench")
    st.caption(f"Corpus: {corpus_label} · Codebook: {active_codebook_label} · Project: {results['project_name']}")

    k1, k2, k3, k4 = st.columns(4)
    if group_mode:
        k1.metric("Focus Groups (G)", total_documents, help="One focus group per file (1 file = 1 group).")
        k2.metric("Distinct Participant Voices", count_distinct_voices(results["tagged_turns_df"]),
                  help="Distinct participant labels per group, so P1 in two groups counts as two voices. "
                       "Unattributed entries are not counted.")
        k3.metric("Coded Notes Entries", participant_turns,
                  help="Key points, notable quotes (and observations, when included) coded against the codebook.")
        k4.metric("Active Domains", len(freq), help="Domains defined in the active codebook.")
    else:
        k1.metric("Analytical Units (N)", total_documents,
                  help="Distinct analytical units: one per transcript, one per tabular respondent row.")
        k2.metric("Participant Turns", participant_turns, help="Turns coded after facilitator turns are removed.")
        k3.metric("Active Domains", len(freq), help="Domains defined in the active codebook.")
        k4.metric("Matched Turn Mentions", matched_mentions,
                  help="Participant turns matched to a domain, summed over domains.")

    # Mixed evidence (paraphrases/observations) is shown in either mode unless
    # Group mode's "Quotable Verbatim Only" filter is checked.
    mixed_view = bool(has_non_verbatim_evidence(quotes)
                      and not (group_mode and st.session_state.get("verbatim_only_filter", False)))
    qtab_freq, qtab_quotes, qtab_topics, qtab_spotcheck = st.tabs([
        "📈 Thematic Prevalence & Distribution",
        "💬 Coded Evidence & Provenance Browser" if mixed_view else "💬 Verbatim Quote & Provenance Browser",
        "💡 Unsupervised Topic Discovery (Medoids)",
        "🔎 False-Alarm Spot-Check",
    ])

    with qtab_freq:
        if group_mode:
            st.markdown("#### Focus groups reporting each domain")
            st.caption("Groups reporting (g of G) = focus groups with at least one matching coded entry; "
                       "G = all focus groups (1 file = 1 group).")
        else:
            st.markdown("#### Domain prevalence across analytical units")
            st.caption("Prevalence = units with at least one matching participant turn ÷ all analytical units.")
        if len(freq):
            if group_mode:
                panels = [
                    (group_prevalence_chart(group_table, total_documents), group_summary, max(160, 42 * len(freq)),
                     "Bar labels show g/G: focus groups reporting the domain out of all focus groups."),
                    (group_matrix_chart(group_matrix), matrix_summary, max(160, 42 * len(freq)),
                     "Tiles show distinct participant voices per group (for example 2v); ✓ = matched only by "
                     "unattributed entries; — = not reported."),
                ]
            else:
                chart = alt.Chart(freq).mark_bar(color=NAVY).encode(
                    x=alt.X("prevalence_pct:Q", title="Prevalence (% of analytical units)", scale=alt.Scale(domain=[0, 100])),
                    y=alt.Y("domain_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
                    tooltip=[
                        alt.Tooltip("domain_name:N", title="Domain"),
                        alt.Tooltip("prevalence_pct:Q", title="Prevalence (%)"),
                        alt.Tooltip("documents_reporting:Q", title="Units reporting"),
                        alt.Tooltip("matching_turns:Q", title="Matching turns"),
                    ],
                )
                labels = alt.Chart(freq).mark_text(align="left", dx=4, color="#0F172A").encode(
                    x="prevalence_pct:Q",
                    y=alt.Y("domain_name:N", sort="-x"),
                    text=alt.Text("matching_turns:Q", format="d"),
                )
                panels = [(chart + labels, describe_prevalence_chart(freq, total_documents, include_ci=False),
                           max(160, 42 * len(freq)), "Bar labels show matching participant turns per domain.")]
            for panel_chart, freq_summary, panel_height, panel_note in panels:
                st.altair_chart(
                    light_chart_surface(panel_chart.properties(height=panel_height, description=freq_summary)),
                    **stretch_kwargs(st.altair_chart),
                )
                st.html(chart_summary_html(freq_summary))
                st.caption(panel_note)
            if group_mode:
                st.markdown("##### Group frequency table")
                st.dataframe(group_table, **stretch_kwargs(st.dataframe), hide_index=True,
                             column_config=group_table_config)
            else:
                st.markdown("##### Domain frequency table")
                st.dataframe(
                    freq[["domain_id", "domain_name", "documents_reporting", "total_documents",
                          "prevalence_pct", "matching_turns", "total_mentions"]],
                    **stretch_kwargs(st.dataframe), hide_index=True,
                    column_config={
                        "domain_id": "Domain ID", "domain_name": "Domain",
                        "documents_reporting": "Units reporting", "total_documents": "Analytical units (N)",
                        "prevalence_pct": st.column_config.NumberColumn("Prevalence (%)", format="%.1f"),
                        "matching_turns": "Matching turns", "total_mentions": "Mentions",
                    },
                )
        else:
            st.info("The active codebook defines no domains.")

        if group_mode and len(themes_df) and {"source_id", "question_id", "text"} <= set(themes_df.columns):
            with st.expander(THEMES_EXPANDER_LABEL, expanded=False):
                st.caption("Note-taker theme summaries, shown for reference. They are not coded and are not "
                           "counted in any prevalence, quote or KPI.")
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

    with qtab_quotes:
        if mixed_view:
            st.markdown("#### Coded evidence with source provenance")
        else:
            st.markdown("#### Verbatim evidence with line-level provenance")
        if quotes.empty:
            st.info("No participant turn matched a domain of the active codebook in this corpus.")
        elif group_mode:
            labelled = quotes.assign(group_label=quotes["source_id"].astype(str).map(
                lambda sid: group_labels.get(sid, os.path.basename(sid))))
            questions = sorted(q for q in labelled["question_id"].astype(str).unique() if q)
            f1, f2, f3 = st.columns([2, 1, 1])
            search = f1.text_input("Search coded entries" if mixed_view else "Search verbatim text", "")
            domain_filter = f2.selectbox("Filter by domain", ["All domains", *sorted(labelled["domain_name"].astype(str).unique())])
            speaker_filter = f3.selectbox("Filter by speaker", ["All speakers", *sorted(labelled["speaker"].astype(str).unique())])
            g1, g2, g3 = st.columns([2, 1, 1])
            verbatim_only = g1.checkbox(
                "Quotable Verbatim Only", value=False, key="verbatim_only_filter",
                help="Show only verbatim words: notable quotes from notes and transcript or survey turns. "
                     "Paraphrased key points and observations are hidden.",
            )
            group_filter = g2.selectbox("Filter by group", ["All groups", *sorted(labelled["group_label"].unique())])
            question_filter = "All questions"
            if questions:
                question_filter = g3.selectbox("Filter by question", ["All questions", *questions])
            shown = labelled
            if verbatim_only:
                shown = verbatim_rows(shown)
            if domain_filter != "All domains":
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
                st.markdown(f"**{len(shown)} of {len(quotes)} coded entries shown (includes paraphrases/"
                            f"observations; check 'Quotable Verbatim Only' for direct quotes)**")
            else:
                st.markdown(f"**{len(shown)} of {len(quotes)} matched entries shown**")
            if shown.empty:
                st.info("No verbatim quote matches the current filters." if verbatim_only
                        else "No quote matches these filters.")
            else:
                st.dataframe(
                    shown[["evidence_type", "group_label", "question_id", "domain_name", "speaker", "source_id",
                           "unit_id", "line_number", "match_char_start", "match_char_end", "match_text", "text",
                           "source_sha256"]],
                    **stretch_kwargs(st.dataframe), hide_index=True,
                    column_config={
                        "evidence_type": "Evidence Type", "group_label": "Group", "question_id": "Question",
                        "domain_name": "Domain", "speaker": "Speaker", "source_id": "Source ID",
                        "unit_id": "Unit ID", "line_number": "Line", "match_char_start": "Match start",
                        "match_char_end": "Match end", "match_text": "Matched span",
                        "text": "Coded entry (see Evidence Type)" if mixed_view else "Verbatim quote",
                        "source_sha256": "Source SHA-256",
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
                        f'CHARS {esc(q["match_char_start"])}–{esc(q["match_char_end"])} · '
                        f'SHA-256 {esc(q["source_sha256"])}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        else:
            f1, f2, f3 = st.columns([2, 1, 1])
            search = f1.text_input("Search coded entries" if mixed_view else "Search verbatim text", "")
            domain_filter = f2.selectbox("Filter by domain", ["All domains", *sorted(quotes["domain_name"].astype(str).unique())])
            speaker_filter = f3.selectbox("Filter by speaker", ["All speakers", *sorted(quotes["speaker"].astype(str).unique())])
            shown = quotes
            if domain_filter != "All domains":
                shown = shown[shown["domain_name"].astype(str) == domain_filter]
            if speaker_filter != "All speakers":
                shown = shown[shown["speaker"].astype(str) == speaker_filter]
            if search.strip():
                shown = shown[shown["text"].astype(str).str.contains(search.strip(), case=False, regex=False)]
            if mixed_view:
                st.markdown(f"**{len(shown)} of {len(quotes)} coded entries shown (includes paraphrases/observations)**")
            else:
                st.markdown(f"**{len(shown)} of {len(quotes)} matched quotes shown**")
            if shown.empty:
                st.info("No entry matches these filters." if mixed_view else "No quote matches these filters.")
            else:
                st.dataframe(
                    shown[[*(["evidence_type"] if notes_present else []), "domain_name", "speaker", "source_id",
                           "unit_id", "line_number", "match_char_start", "match_char_end", "match_text", "text",
                           "source_sha256"]],
                    **stretch_kwargs(st.dataframe), hide_index=True,
                    column_config={
                        "evidence_type": "Evidence Type",
                        "domain_name": "Domain", "speaker": "Speaker", "source_id": "Source ID",
                        "unit_id": "Unit ID", "line_number": "Line", "match_char_start": "Match start",
                        "match_char_end": "Match end", "match_text": "Matched span",
                        "text": "Coded entry (see Evidence Type)" if mixed_view else "Verbatim turn",
                        "source_sha256": "Source SHA-256",
                    },
                )
                for _, q in shown.head(25).iterrows():
                    badge = evidence_badge_html(q["evidence_type"]) if notes_present else ""
                    st.markdown(
                        f'<div class="quote-box">'
                        f'<div class="quote-meta">{badge}{esc(q["domain_name"])} · {esc(q["speaker"])}</div>'
                        f'<div class="quote-text">{highlighted_quote(q["text"], q["match_char_start"], q["match_char_end"])}</div>'
                        f'<div class="quote-provenance">SOURCE {esc(q["source_id"])} · LINE {esc(q["line_number"])} · '
                        f'CHARS {esc(q["match_char_start"])}–{esc(q["match_char_end"])} · '
                        f'SHA-256 {esc(q["source_sha256"])}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    with qtab_topics:
        disc_choice = st.radio(
            "Discovery method",
            list(DISCOVERY_METHOD_MAP),
            index=0,
            horizontal=True,
            help="TF-IDF + NMF is faster, deterministic across runs, and produces more distinct topic keywords; "
                 "LDA is the classic bag-of-words topic model.",
        )
        disc_method = DISCOVERY_METHOD_MAP[disc_choice]
        disc_label = "TF-IDF + NMF topics" if disc_method == "nmf" else "LDA topics"
        st.markdown(f"#### Unsupervised topic discovery ({disc_label}, TF-IDF cosine medoids)")
        if notes_present:
            st.caption("Each medoid is the coded notes entry closest to its topic's TF-IDF centroid. A medoid "
                       "can be a verbatim quote, a paraphrased key point or a note-taker observation; its "
                       "evidence type is shown on every card and in the table.")
        else:
            st.caption("Each medoid is the real participant turn closest to its topic's TF-IDF centroid.")
        n_topics = st.slider("Number of topics (k)", min_value=1, max_value=10, value=3)
        turn_records = results["tagged_turns_df"].to_dict("records")
        discovery = run_topic_discovery(turn_records, n_topics, method=disc_method)
        topics = discovery["topics"]
        medoid_evidence = {
            (str(r.get("unit_id")), str(r.get("turn_id")), str(r.get("text"))): str(r.get("evidence_type") or "")
            for r in turn_records
        }
        for topic in topics:
            topic["medoid_evidence_type"] = medoid_evidence.get(
                (str(topic["medoid_unit_id"]), str(topic["medoid_turn_id"]), str(topic["medoid_text"])), "")
        if not topics:
            st.info("No participant turn has enough content words for topic discovery.")
        else:
            st.caption(f"{discovery['n_analyzed']} participant turns analysed; k clamped to {len(topics)}.")
            for topic in topics:
                terms = ", ".join(dedupe_terms(topic["top_terms"]))
                medoid = topic["medoid_text"]
                badge = evidence_badge_html(topic["medoid_evidence_type"]) if notes_present else ""
                st.markdown(
                    f'<div class="quote-box topic-box">'
                    f'<div class="quote-meta">{badge}Topic {esc(topic["topic_id"])}: {esc(topic["label"])} · '
                    f'{esc(topic["turn_count"])} turns ({esc(topic["share_pct"])}%)</div>'
                    f'<div style="font-size:0.9rem;margin-bottom:0.4rem;"><strong>Top terms:</strong> {esc(terms)}</div>'
                    f'<div class="quote-text">{esc(medoid) if medoid else "No medoid turn assigned."}</div>'
                    f'<div class="quote-provenance">MEDOID UNIT {esc(topic["medoid_unit_id"])} · '
                    f'SPEAKER {esc(topic["medoid_speaker"])}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            st.dataframe(
                pd.DataFrame([
                    {
                        "topic_id": t["topic_id"],
                        "top_terms": ", ".join(dedupe_terms(t["top_terms"])),
                        "turn_count": t["turn_count"],
                        "share_pct": t["share_pct"],
                        "medoid_unit_id": t["medoid_unit_id"],
                        "medoid_text": t["medoid_text"],
                        **({"medoid_evidence_type": t["medoid_evidence_type"]} if notes_present else {}),
                    }
                    for t in topics
                ]),
                **stretch_kwargs(st.dataframe), hide_index=True,
                column_config={
                    "topic_id": "Topic", "top_terms": "Top terms", "turn_count": "Turns",
                    "share_pct": st.column_config.NumberColumn("Share (%)", format="%.1f"),
                    "medoid_unit_id": "Medoid unit",
                    "medoid_text": "Medoid entry (see evidence type)" if notes_present else "Medoid turn (verbatim)",
                    "medoid_evidence_type": "Medoid evidence type",
                },
            )
            corpus_digest = hashlib.sha256(b"".join(p for _, p in inputs)).hexdigest()[:8]
            discovered_label = f"Discovered: {len(topics)} topics ({disc_method.upper()}) · corpus {corpus_digest} (session)"
            codebook_yaml = yaml.safe_dump(
                topics_to_codebook_dict(discovery, project_name=f"Discovered Codebook ({corpus_label})"),
                allow_unicode=True, sort_keys=False,
            ).encode("utf-8")
            d1, d2 = st.columns(2)
            d1.download_button(
                "📥 Download Discovered Codebook (.yaml)", data=codebook_yaml,
                file_name="atlas_discovered_codebook.yaml", mime="application/x-yaml",
                **stretch_kwargs(st.download_button),
            )
            d2.button(
                "⚡ Apply Discovered Codebook to Engine", on_click=apply_discovered_codebook,
                args=(discovered_label, codebook_yaml), **stretch_kwargs(st.button),
                help="Adds this draft to the codebook list and re-codes the corpus with it.",
            )

            st.markdown("---")
            st.markdown("##### Add a discovered theme to your active codebook")
            st.caption(
                "Keeps all domains in your active codebook and appends one discovered topic as a new "
                "domain—no YAML editing required."
            )
            topic_choices = {
                f"Topic {t['topic_id']}: {t['label']} ({t['turn_count']} turns)": t for t in topics
            }
            if st.session_state.get("add_topic_select") not in topic_choices:
                st.session_state.pop("add_topic_select", None)
            a1, a2 = st.columns([2, 2])
            picked_topic_label = a1.selectbox("Topic to add", list(topic_choices), key="add_topic_select")
            picked_topic = topic_choices[picked_topic_label]
            custom_theme_name = a2.text_input(
                "New domain name (optional)",
                placeholder=str(picked_topic["label"]),
                key="add_topic_name",
                help="Leave blank to use the topic's top terms as the domain name.",
            )
            exact_mode_add = st.checkbox(
                "Use exact whole-word matching for added theme (recommended)",
                value=True,
                key="add_topic_exact",
                help="Prevents short discovered words (such as 'car' or 'fee') from matching unrelated longer words.",
            )
            st.button(
                "➕ Add Theme to Active Codebook",
                on_click=add_theme_to_active_codebook,
                args=(codebook_bytes, picked_topic, custom_theme_name, "exact" if exact_mode_add else "prefix"),
                key="add_topic_to_active_btn",
                **stretch_kwargs(st.button),
                help="Appends this topic to the active codebook, immediately re-codes the corpus, and lets you download the updated YAML.",
            )

    with qtab_spotcheck:
        st.markdown("#### False-alarm spot-check")
        st.caption(
            "Flags coded matches that commonly create false alarms: short or non-inflectional prefix extensions "
            "(for example, 'car' inside 'card' or 'career'), nearby negation cues ('not', 'never', 'didn\\'t'), "
            "and short unfenced prefix roots."
        )
        audit_df = results["false_alarm_audit_df"]
        if quotes.empty:
            st.info("No coded matches to spot-check in the current corpus.")
        elif audit_df.empty:
            st.success("No high- or medium-risk false-alarm patterns detected across all current matches.")
        else:
            n_flagged = len(audit_df)
            n_high = int((audit_df["risk_level"] == "High").sum())
            n_med = int((audit_df["risk_level"] == "Medium").sum())
            st.markdown(
                f"**{n_flagged} of {len(quotes)} coded matches flagged for review** · "
                f"High risk: **{n_high}** · Medium risk: **{n_med}**"
            )
            summary_df = summarize_false_alarm_risks(audit_df)
            st.dataframe(summary_df, **stretch_kwargs(st.dataframe), hide_index=True)
            st.download_button(
                "📥 Download Spot-Check Report (.csv)",
                data=audit_df.to_csv(index=False).encode("utf-8"),
                file_name="atlas_false_alarm_spot_check.csv",
                mime="text/csv",
                key="download_spotcheck_csv",
                **stretch_kwargs(st.download_button),
            )

            st.markdown("---")
            st.markdown("##### Quick-fix a flagged domain in your active codebook")
            st.caption(
                "Tighten a noisy domain right here without editing YAML. Download the updated codebook from "
                "the sidebar or Tab 2 when finished."
            )
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
            picked_fix_label = sc1.selectbox("Domain to tighten", list(domain_choice_map), key="spotcheck_fix_domain")
            fix_domain_id, fix_domain_name = domain_choice_map[picked_fix_label]
            dom_audit = audit_df[audit_df["domain_id"].astype(str) == fix_domain_id]
            ext_words = sorted({
                w.strip().lower()
                for cell in dom_audit["extension_words"]
                for w in str(cell).split(",")
                if w.strip()
            })
            selected_exclude_words = []
            if ext_words:
                ext_sig = hashlib.sha256(",".join(ext_words).encode("utf-8")).hexdigest()[:8]
                selected_exclude_words = sc2.multiselect(
                    "False-alarm words to exclude (0-token fence)",
                    ext_words,
                    default=ext_words,
                    key=f"spotcheck_excl_{fix_domain_id}_{ext_sig}",
                    help="Adds these words to exclude_fences so they stop matching this domain.",
                )
            b1, b2 = st.columns(2)
            b1.button(
                "🛡️ Exclude Selected Words from Domain",
                on_click=apply_tightened_codebook,
                args=(codebook_bytes, fix_domain_id, fix_domain_name, selected_exclude_words, False),
                disabled=not selected_exclude_words,
                key="spotcheck_exclude_btn",
                **stretch_kwargs(st.button),
                help="Adds the selected false-alarm words to exclude_fences and immediately re-codes.",
            )
            b2.button(
                "🎯 Switch Domain to Exact Whole-Word Matching",
                on_click=apply_tightened_codebook,
                args=(codebook_bytes, fix_domain_id, fix_domain_name, [], True),
                key="spotcheck_exact_btn",
                **stretch_kwargs(st.button),
                help="Switches this domain to match_mode: exact so short stems only match whole words.",
            )

            st.markdown("---")
            st.markdown("##### Flagged matches in context")
            sc_dom_options = ["All domains", *sorted(audit_df["domain_name"].astype(str).unique())]
            if st.session_state.get("spotcheck_dom_filter") not in sc_dom_options:
                st.session_state.pop("spotcheck_dom_filter", None)
            rf1, rf2 = st.columns(2)
            risk_filter = rf1.selectbox("Filter by risk", ["All risk levels", "High", "Medium"], key="spotcheck_risk_filter")
            dom_filter_sc = rf2.selectbox(
                "Filter flagged domain",
                sc_dom_options,
                key="spotcheck_dom_filter",
            )
            shown_audit = audit_df
            if risk_filter != "All risk levels":
                shown_audit = shown_audit[shown_audit["risk_level"] == risk_filter]
            if dom_filter_sc != "All domains":
                shown_audit = shown_audit[shown_audit["domain_name"].astype(str) == dom_filter_sc]
            st.caption(f"Showing {min(len(shown_audit), 25)} of {len(shown_audit)} flagged matches.")
            for _, row in shown_audit.head(25).iterrows():
                box_cls = "risk-high-box" if row["risk_level"] == "High" else "risk-medium-box"
                ev_badge = evidence_badge_html(row["evidence_type"]) if notes_present else ""
                st.markdown(
                    f'<div class="quote-box {box_cls}">'
                    f'<div class="quote-meta">{risk_badge_html(row["risk_level"])}{ev_badge}'
                    f'{esc(row["domain_name"])} · {esc(row["speaker"])} · '
                    f'matched <code>{esc(row["matched_span"])}</code> inside <code>{esc(row["full_word"])}</code></div>'
                    f'<div style="font-size:0.88rem;color:#334155;margin-bottom:0.35rem;">'
                    f'<strong>Why flagged:</strong> {esc(row["flag_reason"])}</div>'
                    f'<div class="quote-text">{highlighted_quote(row["text"], row["match_char_start"], row["match_char_end"])}</div>'
                    f'<div class="quote-provenance">SOURCE {esc(row["source_id"])} · LINE {esc(row["line_number"])} · '
                    f'FIX: {esc(row["suggested_fix"])}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ==============================================================================
# TAB 2: ECONOMETRIC & ACTUARIAL LEDGER EXPORT
# ==============================================================================
with tab_econometric:
    if group_mode:
        st.markdown("### Group summary matrix")
        st.caption(
            f"G = {total_documents} focus groups (1 file = 1 group). "
            "Groups reporting = focus groups with at least one matching coded entry."
        )
        st.info(
            "Statistical guardrail (Group mode): normal-approximation Binomial standard errors and 95% "
            "confidence intervals (p ± 1.96·SE) are hidden. With a small number of focus groups "
            f"(G = {total_documents}) and participants in the same room shaping one another's answers, "
            "the counts are not independent Binomial samples, so such an interval would overstate precision. "
            "Report groups reporting (g of G) and distinct participant voices instead."
        )
    elif notes_present:
        st.markdown("### Econometric parameter matrix")
        st.caption(
            f"N = {total_documents} analytical units; each structured notes file is one focus group, "
            "so its unit is the group, not an individual respondent."
        )
        st.info(
            "Statistical guardrail (structured focus-group notes): normal-approximation Binomial standard "
            "errors and 95% confidence intervals (p ± 1.96·SE) are hidden for this corpus. Structured notes "
            "are counted one unit per focus-group file, and participants in the same room are not independent, "
            "so the units are not independent Binomial samples of individuals."
        )
    else:
        st.markdown("### Econometric parameter matrix")
        st.caption(
            f"N = {total_documents} analytical units (documents / respondent rows). "
            "p = units reporting ÷ N; binomial standard error SE = √(p(1 − p) / N), on the proportion scale."
        )

    if len(freq):
        if group_mode:
            tab2_chart, ci_summary = group_prevalence_chart(group_table, total_documents), group_summary
            tab2_note = "Bar labels show g/G: focus groups reporting the domain out of all focus groups."
            tab2_table, tab2_config = group_table, group_table_config
        else:
            matrix = pd.DataFrame({
                "domain_id": freq["domain_id"].astype(str),
                "domain_name": freq["domain_name"].astype(str),
            })
            p = [int(d) / total_documents if total_documents else float("nan") for d in freq["documents_reporting"]]
            se = [math.sqrt(v * (1 - v) / total_documents) if total_documents else float("nan") for v in p]
            matrix["documents_reporting"] = freq["documents_reporting"].astype(int)
            matrix["n_units"] = total_documents
            matrix["prevalence_pct"] = freq["prevalence_pct"].astype(float)
            matrix["proportion"] = [round(v, 4) for v in p]
            matrix["binomial_se"] = [round(v, 4) for v in se]
            matrix["ci95_low_pct"] = [round(max(0.0, (v - 1.96 * s) * 100), 1) for v, s in zip(p, se)]
            matrix["ci95_high_pct"] = [round(min(1.0, v + 1.96 * s) * 100, 1) for v, s in zip(p, se)]
            matrix["matching_turns"] = freq["matching_turns"].astype(int)
            if notes_present:
                matrix = matrix.drop(columns=["proportion", "binomial_se", "ci95_low_pct", "ci95_high_pct"])

            bars = alt.Chart(matrix).mark_bar(color=TEAL).encode(
                x=alt.X("prevalence_pct:Q", title="Prevalence (% of analytical units)", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("domain_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
                tooltip=[
                    alt.Tooltip("domain_name:N", title="Domain"),
                    alt.Tooltip("prevalence_pct:Q", title="Prevalence (%)"),
                    alt.Tooltip("documents_reporting:Q", title="Units reporting"),
                    alt.Tooltip("n_units:Q", title="N"),
                    *([] if notes_present else [alt.Tooltip("binomial_se:Q", title="SE")]),
                ],
            )
            if notes_present:
                tab2_chart = bars
                ci_summary = describe_prevalence_chart(matrix, total_documents, include_ci=False)
                tab2_note = "Bars show the share of focus-group files with a matching entry; no interval is drawn."
            else:
                whiskers = alt.Chart(matrix).mark_rule(color="#0F172A").encode(
                    x="ci95_low_pct:Q", x2="ci95_high_pct:Q", y=alt.Y("domain_name:N", sort="-x"),
                )
                tab2_chart = bars + whiskers
                ci_summary = describe_prevalence_chart(matrix, total_documents, include_ci=True)
                tab2_note = "Whiskers show the normal-approximation 95% interval p ± 1.96·SE, clipped to 0–100%."
            tab2_table = matrix
            tab2_config = {
                "domain_id": "Domain ID", "domain_name": "Domain",
                "documents_reporting": "Units reporting", "n_units": "N (analytical units)",
                "prevalence_pct": st.column_config.NumberColumn("Prevalence (%)", format="%.1f"),
                "proportion": "p", "binomial_se": "Binomial SE",
                "ci95_low_pct": "95% CI low (%)", "ci95_high_pct": "95% CI high (%)",
                "matching_turns": "Matching turns",
            }
        st.altair_chart(
            light_chart_surface(tab2_chart.properties(height=max(160, 42 * len(freq)), description=ci_summary)),
            **stretch_kwargs(st.altair_chart),
        )
        st.html(chart_summary_html(ci_summary))
        st.caption(tab2_note)
        st.dataframe(tab2_table, **stretch_kwargs(st.dataframe), hide_index=True, column_config=tab2_config)
    else:
        st.info("The active codebook defines no domains.")

    st.markdown("---")
    st.markdown("#### Auditable exports (generated by AtlasEngine.export_results)")
    if results["integrity_ok"]:
        st.success("Workbook integrity check passed: every prevalence cell and audit stamp matches the manifest.")
    else:
        st.error("Workbook integrity check failed: " + "; ".join(results["integrity_problems"]))
    e1, e2, e3 = st.columns(3)
    e1.download_button(
        "📥 actuarial_parameter_matrix.xlsx", data=results["exports"]["actuarial_parameter_matrix.xlsx"],
        file_name="actuarial_parameter_matrix.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", **stretch_kwargs(st.download_button),
        help="Each prevalence cell carries an ATLAS VERIFICATION AUDIT STAMP comment.",
    )
    e2.download_button(
        "📥 provenance_manifest.json", data=results["exports"]["provenance_manifest.json"],
        file_name="provenance_manifest.json", mime="application/json", **stretch_kwargs(st.download_button),
    )
    e3.download_button(
        "📥 verbatim_quotes_inventory.csv", data=results["exports"]["verbatim_quotes_inventory.csv"],
        file_name="verbatim_quotes_inventory.csv", mime="text/csv", **stretch_kwargs(st.download_button),
        help="Verbatim words only: transcript / survey turns and notable quotes from notes.",
    )
    if CODED_EVIDENCE_CSV in results["exports"]:
        st.download_button(
            f"📥 {CODED_EVIDENCE_CSV}", data=results["exports"][CODED_EVIDENCE_CSV],
            file_name=CODED_EVIDENCE_CSV, mime="text/csv", **stretch_kwargs(st.download_button),
            help="Every coded entry with its evidence_type: verbatim quotes, paraphrased key points and "
                 "note-taker observations. Paraphrases and observations are not participant quotations.",
        )
    if is_custom_or_stacked:
        st.download_button(
            "📥 atlas_active_codebook.yaml (stacked / customized rules)",
            data=codebook_bytes,
            file_name="atlas_active_codebook.yaml",
            mime="application/x-yaml",
            key="download_active_codebook_tab2",
            **stretch_kwargs(st.download_button),
            help="Archive this exact YAML codebook alongside your export folder so coding rules stay reproducible.",
        )
    with st.expander("Source files and SHA-256 digests"):
        st.dataframe(
            pd.DataFrame(
                [{"source_id": k, "sha256": v} for k, v in results["file_hashes"].items()],
                columns=["source_id", "sha256"],
            ),
            **stretch_kwargs(st.dataframe), hide_index=True,
        )


# ------------------------------------------------------------------------------
# 7. Footer
# ------------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#475569;font-size:0.85rem;padding:1rem 0;'>"
    "ATLAS · Automated Text-to-Ledger Actuarial Synthesis · MIT License"
    "</div>",
    unsafe_allow_html=True,
)
