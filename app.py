"""
From Spoken Words to Countable Data: Meet ATLAS
A fast, private way to organize transcripts, count patterns, and trace every quote right on your laptop.

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
import io
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

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
from atlas_engine import AtlasEngine
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

CORPUS_BILINGUAL = "Sample: Bilingual Interview Transcripts (SOFTWARE_TEST)"
CORPUS_SURVEY = "Sample: Community Health Survey CSV (SOFTWARE_TEST)"
CORPUS_DOCX = "Sample: Teams Multiline Transcript DOCX (SOFTWARE_TEST)"
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
}
CORPUS_OPTIONS = [*SAMPLE_CORPORA, CORPUS_UPLOAD]
UPLOAD_TYPES = ["docx", "vtt", "srt", "txt", "md", "csv", "xlsx"]

CODEBOOK_UPLOAD = "Upload Custom Codebook (.yaml)"
NONE_OPTION = "(none)"

SOFTWARE_TEST_BANNER = (
    "🧪 SOFTWARE_TEST FIXTURE ACTIVE — Built-in sample files demonstrate software "
    "mechanics only and are not empirical research findings."
)

REFERENCE_GUIDES = [
    ("📘 User Guide (Markdown)", "ATLAS_User_Guide.md"),
    ("📗 Methodology & Reference Manual (Markdown)", "ATLAS_Methodology_and_Reference_Manual.md"),
    ("📙 Practitioner Field Guide (Markdown)", "ATLAS_Practitioner_Field_Guide_Program_Evaluation.md"),
]

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
    page_title="From Spoken Words to Countable Data: Meet ATLAS",
    page_icon="⚖️",
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


def safe_upload_name(name, taken):
    base = os.path.basename(str(name).replace("\\", "/")) or "upload"
    candidate, counter = base, 2
    while candidate in taken:
        stem, ext = os.path.splitext(base)
        candidate = f"{stem}_{counter}{ext}"
        counter += 1
    taken.add(candidate)
    return candidate


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
def analyze_corpus(codebook_bytes, inputs, tabular_items, facilitators, prompt_patterns):
    """
    Run UniversalTranscriptParser -> AtlasEngine on byte copies of the inputs.

    inputs is a tuple of (relative_path, bytes); the files are written under a
    fresh temporary root with those relative paths, so each source_id equals the
    relative path and each source_sha256 is the SHA-256 of the exact bytes.
    The engine's own export (xlsx with audit-stamp comments, provenance manifest,
    quotes CSV) is produced in the same temporary root and returned as bytes.
    """
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
                         "verbatim_quotes_inventory.csv")
        }

    results["exports"] = exports
    results["integrity_ok"] = bool(integrity_ok)
    results["integrity_problems"] = list(integrity_problems)
    return results


@st.cache_data(show_spinner=False)
def run_topic_discovery(turn_records, n_topics):
    return discover_topics(turn_records, n_topics=n_topics)


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


if "discovered_codebooks" not in st.session_state:
    st.session_state.discovered_codebooks = {}


# ------------------------------------------------------------------------------
# 3. Sidebar: corpus, codebook and parser controls
# ------------------------------------------------------------------------------
config_codebooks = list_config_codebooks()

with st.sidebar:
    st.markdown(
        '<div class="badge-row" aria-label="ATLAS Workbench">'
        '<span class="atlas-badge">ATLAS</span><span class="atlas-badge atlas-badge-teal">Workbench</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("### Operational Controls")

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

    st.markdown("---")
    st.markdown("### Operational Guarantees")
    st.markdown(
        "🔒 **Local processing**  \nFiles are parsed and coded on this computer; ATLAS code makes no network "
        "requests and loads no remote assets. The desktop launchers turn off Streamlit usage statistics."
    )
    st.markdown("⚖️ **Line-level provenance**  \nEvery coded quote carries its source line, character span and file SHA-256.")
    st.markdown("⚡ **Deterministic coding**  \nThe same files and codebook give the same counts on every run.")

    st.markdown("---")
    st.markdown("### Reference Guides")
    for label, filename in REFERENCE_GUIDES:
        guide = DOCS_DIR / filename
        if guide.is_file():
            st.download_button(
                label=label, data=guide.read_bytes(), file_name=filename,
                mime="text/markdown", width="stretch", key=f"guide_{filename}",
            )


# ------------------------------------------------------------------------------
# 4. Header and fixture notice
# ------------------------------------------------------------------------------
st.markdown(
    f"""
<div class="brand-header">
<h1>From Spoken Words to Countable Data: Meet ATLAS</h1>
<p>A fast, private way to organize transcripts, count patterns, and trace every quote right on your laptop.</p>
<div class="badge-row">
<span class="atlas-badge">Local processing</span>
<span class="atlas-badge">SHA-256 source digests</span>
<span class="atlas-badge atlas-badge-teal">Deterministic coding</span>
<span class="atlas-badge atlas-badge-outline">WCAG 2.1 AA palette</span>
</div>
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
    codebook_bytes = uploaded_codebook.getvalue()
elif codebook_choice in st.session_state.discovered_codebooks:
    codebook_bytes = st.session_state.discovered_codebooks[codebook_choice]
else:
    codebook_bytes = (CONFIG_DIR / codebook_choice).read_bytes()

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
        )
except (*UPLOAD_READ_ERRORS, RuntimeError, yaml.YAMLError) as exc:
    st.error(f"ATLAS could not analyse this corpus with this codebook: {exc}")
    st.stop()

freq = results["frequencies_df"]
quotes = results["quotes_df"]
total_documents = int(results["total_documents"])
participant_turns = int(results["participant_turns_analyzed"])
matched_mentions = int(freq["matching_turns"].sum()) if len(freq) else 0


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
    st.caption(f"Corpus: {corpus_label} · Codebook: {codebook_choice} · Project: {results['project_name']}")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Analytical Units (N)", total_documents,
              help="Distinct analytical units: one per transcript, one per tabular respondent row.")
    k2.metric("Participant Turns", participant_turns, help="Turns coded after facilitator turns are removed.")
    k3.metric("Active Domains", len(freq), help="Domains defined in the active codebook.")
    k4.metric("Matched Turn Mentions", matched_mentions, help="Participant turns matched to a domain, summed over domains.")

    qtab_freq, qtab_quotes, qtab_topics = st.tabs([
        "📈 Thematic Prevalence & Distribution",
        "💬 Verbatim Quote & Provenance Browser",
        "💡 Unsupervised Topic Discovery (Medoids)",
    ])

    with qtab_freq:
        st.markdown("#### Domain prevalence across analytical units")
        st.caption("Prevalence = units with at least one matching participant turn ÷ all analytical units.")
        if len(freq):
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
            st.altair_chart((chart + labels).properties(height=max(160, 42 * len(freq))), width="stretch")
            st.caption("Bar labels show matching participant turns per domain.")
            st.markdown("##### Domain frequency table")
            st.dataframe(
                freq[["domain_id", "domain_name", "documents_reporting", "total_documents",
                      "prevalence_pct", "matching_turns", "total_mentions"]],
                width="stretch", hide_index=True,
                column_config={
                    "domain_id": "Domain ID", "domain_name": "Domain",
                    "documents_reporting": "Units reporting", "total_documents": "Analytical units (N)",
                    "prevalence_pct": st.column_config.NumberColumn("Prevalence (%)", format="%.1f"),
                    "matching_turns": "Matching turns", "total_mentions": "Mentions",
                },
            )
        else:
            st.info("The active codebook defines no domains.")

    with qtab_quotes:
        st.markdown("#### Verbatim evidence with line-level provenance")
        if quotes.empty:
            st.info("No participant turn matched a domain of the active codebook in this corpus.")
        else:
            f1, f2, f3 = st.columns([2, 1, 1])
            search = f1.text_input("Search verbatim text", "")
            domain_filter = f2.selectbox("Filter by domain", ["All domains", *sorted(quotes["domain_name"].astype(str).unique())])
            speaker_filter = f3.selectbox("Filter by speaker", ["All speakers", *sorted(quotes["speaker"].astype(str).unique())])
            shown = quotes
            if domain_filter != "All domains":
                shown = shown[shown["domain_name"].astype(str) == domain_filter]
            if speaker_filter != "All speakers":
                shown = shown[shown["speaker"].astype(str) == speaker_filter]
            if search.strip():
                shown = shown[shown["text"].astype(str).str.contains(search.strip(), case=False, regex=False)]
            st.markdown(f"**{len(shown)} of {len(quotes)} matched quotes shown**")
            if shown.empty:
                st.info("No quote matches these filters.")
            else:
                st.dataframe(
                    shown[["domain_name", "speaker", "source_id", "unit_id", "line_number",
                           "match_char_start", "match_char_end", "match_text", "text", "source_sha256"]],
                    width="stretch", hide_index=True,
                    column_config={
                        "domain_name": "Domain", "speaker": "Speaker", "source_id": "Source ID",
                        "unit_id": "Unit ID", "line_number": "Line", "match_char_start": "Match start",
                        "match_char_end": "Match end", "match_text": "Matched span",
                        "text": "Verbatim turn", "source_sha256": "Source SHA-256",
                    },
                )
                for _, q in shown.head(25).iterrows():
                    st.markdown(
                        f'<div class="quote-box">'
                        f'<div class="quote-meta">{esc(q["domain_name"])} · {esc(q["speaker"])}</div>'
                        f'<div class="quote-text">{highlighted_quote(q["text"], q["match_char_start"], q["match_char_end"])}</div>'
                        f'<div class="quote-provenance">SOURCE {esc(q["source_id"])} · LINE {esc(q["line_number"])} · '
                        f'CHARS {esc(q["match_char_start"])}–{esc(q["match_char_end"])} · '
                        f'SHA-256 {esc(q["source_sha256"])}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    with qtab_topics:
        st.markdown("#### Unsupervised topic discovery (LDA topics, TF-IDF cosine medoids)")
        st.caption("Each medoid is the real participant turn closest to its topic's TF-IDF centroid.")
        n_topics = st.slider("Number of topics (k)", min_value=1, max_value=10, value=3)
        turn_records = results["tagged_turns_df"].to_dict("records")
        discovery = run_topic_discovery(turn_records, n_topics)
        topics = discovery["topics"]
        if not topics:
            st.info("No participant turn has enough content words for topic discovery.")
        else:
            st.caption(f"{discovery['n_analyzed']} participant turns analysed; k clamped to {len(topics)}.")
            for topic in topics:
                terms = ", ".join(dedupe_terms(topic["top_terms"]))
                medoid = topic["medoid_text"]
                st.markdown(
                    f'<div class="quote-box topic-box">'
                    f'<div class="quote-meta">Topic {esc(topic["topic_id"])}: {esc(topic["label"])} · '
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
                    }
                    for t in topics
                ]),
                width="stretch", hide_index=True,
                column_config={
                    "topic_id": "Topic", "top_terms": "Top terms", "turn_count": "Turns",
                    "share_pct": st.column_config.NumberColumn("Share (%)", format="%.1f"),
                    "medoid_unit_id": "Medoid unit", "medoid_text": "Medoid turn (verbatim)",
                },
            )
            corpus_digest = hashlib.sha256(b"".join(p for _, p in inputs)).hexdigest()[:8]
            discovered_label = f"Discovered: {len(topics)} topics · corpus {corpus_digest} (session)"
            codebook_yaml = yaml.safe_dump(
                topics_to_codebook_dict(discovery, project_name=f"Discovered Codebook ({corpus_label})"),
                allow_unicode=True, sort_keys=False,
            ).encode("utf-8")
            d1, d2 = st.columns(2)
            d1.download_button(
                "📥 Download Discovered Codebook (.yaml)", data=codebook_yaml,
                file_name="atlas_discovered_codebook.yaml", mime="application/x-yaml",
                width="stretch",
            )
            d2.button(
                "⚡ Apply Discovered Codebook to Engine", on_click=apply_discovered_codebook,
                args=(discovered_label, codebook_yaml), width="stretch",
                help="Adds this draft to the codebook list and re-codes the corpus with it.",
            )


# ==============================================================================
# TAB 2: ECONOMETRIC & ACTUARIAL LEDGER EXPORT
# ==============================================================================
with tab_econometric:
    st.markdown("### Econometric parameter matrix")
    st.caption(
        f"N = {total_documents} analytical units (documents / respondent rows). "
        "p = units reporting ÷ N; binomial standard error SE = √(p(1 − p) / N), on the proportion scale."
    )

    matrix = pd.DataFrame({
        "domain_id": freq["domain_id"].astype(str) if len(freq) else pd.Series(dtype=str),
        "domain_name": freq["domain_name"].astype(str) if len(freq) else pd.Series(dtype=str),
    })
    if len(freq):
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

        bars = alt.Chart(matrix).mark_bar(color=TEAL).encode(
            x=alt.X("prevalence_pct:Q", title="Prevalence (% of analytical units)", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("domain_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
            tooltip=[
                alt.Tooltip("domain_name:N", title="Domain"),
                alt.Tooltip("prevalence_pct:Q", title="Prevalence (%)"),
                alt.Tooltip("documents_reporting:Q", title="Units reporting"),
                alt.Tooltip("n_units:Q", title="N"),
                alt.Tooltip("binomial_se:Q", title="SE"),
            ],
        )
        whiskers = alt.Chart(matrix).mark_rule(color="#0F172A").encode(
            x="ci95_low_pct:Q", x2="ci95_high_pct:Q", y=alt.Y("domain_name:N", sort="-x"),
        )
        st.altair_chart((bars + whiskers).properties(height=max(160, 42 * len(matrix))), width="stretch")
        st.caption("Whiskers show the normal-approximation 95% interval p ± 1.96·SE, clipped to 0–100%.")
        st.dataframe(
            matrix, width="stretch", hide_index=True,
            column_config={
                "domain_id": "Domain ID", "domain_name": "Domain",
                "documents_reporting": "Units reporting", "n_units": "N (analytical units)",
                "prevalence_pct": st.column_config.NumberColumn("Prevalence (%)", format="%.1f"),
                "proportion": "p", "binomial_se": "Binomial SE",
                "ci95_low_pct": "95% CI low (%)", "ci95_high_pct": "95% CI high (%)",
                "matching_turns": "Matching turns",
            },
        )
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
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
        help="Each prevalence cell carries an ATLAS VERIFICATION AUDIT STAMP comment.",
    )
    e2.download_button(
        "📥 provenance_manifest.json", data=results["exports"]["provenance_manifest.json"],
        file_name="provenance_manifest.json", mime="application/json", width="stretch",
    )
    e3.download_button(
        "📥 verbatim_quotes_inventory.csv", data=results["exports"]["verbatim_quotes_inventory.csv"],
        file_name="verbatim_quotes_inventory.csv", mime="text/csv", width="stretch",
    )
    with st.expander("Source files and SHA-256 digests"):
        st.dataframe(
            pd.DataFrame(
                [{"source_id": k, "sha256": v} for k, v in results["file_hashes"].items()],
                columns=["source_id", "sha256"],
            ),
            width="stretch", hide_index=True,
        )


# ------------------------------------------------------------------------------
# 7. Footer
# ------------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#475569;font-size:0.85rem;padding:1rem 0;'>"
    "From Spoken Words to Countable Data: Meet ATLAS · MIT License"
    "</div>",
    unsafe_allow_html=True,
)
