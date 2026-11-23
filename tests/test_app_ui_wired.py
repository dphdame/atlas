"""Slice 3a (RED): live-wired Streamlit workbench and documentation/figure hygiene.

These tests drive the real app.py through streamlit.testing.v1.AppTest and
compute every expected value independently from the real modules
(UniversalTranscriptParser via AtlasEngine.process_corpus, AtlasEngine and
atlas_discover.discover_topics). The built-in-fixture checks require the
rendered domains, KPI counts, quotes, SHA-256 digests and topic medoids to
change with the selected codebook and corpus as the engine says they should;
on their own they could still be met by output hardcoded per fixture. The
upload tests close that gap: each run generates a fresh random table and
computes its expected KPIs, quotes and medoids at test time.

Rendering contract the app must satisfy (Slice 3b spec, .codex/contracts/slice_3b_green.md):

- Sidebar selectboxes labelled "Corpus Dataset" and "Active YAML Codebook".
  Corpus options include one bilingual-interview sample (label contains
  "Bilingual") that loads software_test_bilingual_interview.txt +
  software_test_zoom_session.vtt, and one survey sample (label contains
  "Survey") that loads software_test_survey.csv with text_col="response",
  id_col="respondent_id", speaker_col="role". Codebook options include the
  config/*.yaml file names.
- Each KPI ("Analytical Units (N)", "Participant Turns", "Active Domains",
  "Matched Turn Mentions") is an st.metric, or its own st.markdown card
  holding the label and exactly one number. Analytical Units (N) is
  results["total_documents"]; Participant Turns is
  results["participant_turns_analyzed"]; Active Domains is the number of
  domains in the active codebook (rows of frequencies_df); Matched Turn
  Mentions is frequencies_df["matching_turns"].sum() (== len(quotes_df)).
- A domain table (st.dataframe / st.table) has one row per codebook domain,
  keyed by domain_name or domain_id, with columns holding prevalence_pct and
  matching_turns; the Tab 2 parameter matrix additionally holds
  N = total_documents and the binomial SE sqrt(p(1-p)/N),
  p = documents_reporting / total_documents.
- The quote browser shows each quote's verbatim turn text and its
  source_sha256 (at least the first 12 hex characters).
- Topic discovery runs discover_topics(participant turns, n_topics=<slider>)
  with the defaults otherwise; the slider (or number input) label contains
  "topic". Each discovered topic's verbatim medoid_text is rendered.
- A corpus option whose label contains "Upload" reveals an st.file_uploader
  accepting .csv. For an uploaded table the free-text column is chosen
  automatically, never an id / *_id column; if a text-column selector is shown
  (label mentions "text" and "column") its default is that free-text column.

Every input here is a SOFTWARE_TEST fixture that demonstrates software
mechanics only; nothing rendered or asserted is an empirical finding.

Run: .venv/bin/python -m unittest tests/test_app_ui_wired.py -v
"""

import hashlib
import html
import math
import os
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from atlas_discover import discover_topics  # noqa: E402
from atlas_engine import AtlasEngine  # noqa: E402

APP_PATH = REPO_ROOT / "app.py"
CONFIG_DIR = REPO_ROOT / "config"
SAMPLES_DIR = REPO_ROOT / "data" / "samples"

CORPUS_LABEL = "Corpus Dataset"
CODEBOOK_LABEL = "Active YAML Codebook"
RUN_LABEL = "▶ Run Analysis"

BILINGUAL_FILES = [
    SAMPLES_DIR / "software_test_bilingual_interview.txt",
    SAMPLES_DIR / "software_test_zoom_session.vtt",
]
SURVEY_FILES = [SAMPLES_DIR / "software_test_survey.csv"]
SURVEY_OPTIONS = {"text_col": "response", "id_col": "respondent_id", "speaker_col": "role"}

CODEBOOK_A = "pfl_case_study_codebook.yaml"
CODEBOOK_B = "intake_and_enrollment.yaml"

KPI_UNITS = "Analytical Units (N)"
KPI_TURNS = "Participant Turns"
KPI_DOMAINS = "Active Domains"
KPI_MATCHED = "Matched Turn Mentions"

# Unbacked literals from the 9ec00d24 static mock-up (n=2,500 labor-market table,
# hardcoded KII counts and medoids). None may be rendered or documented.
STALE_LITERAL_PATTERNS = [
    re.compile(r"\bn\s*=\s*2,?500\b", re.IGNORECASE),
    re.compile(r"\b2,500\b"),
    re.compile(r"\b2,?105\b"),
    re.compile(r"\b1,?912\b"),
    re.compile(r"\b1,?570\b"),
    re.compile(r"\b1,?285\b"),
    re.compile(r"\b1,?078\b"),
    re.compile(r"\b3,892\b"),
    re.compile(r"\bKII-0[1-9]\b"),
    re.compile(r"Turnover kills community trust", re.IGNORECASE),
]

# Git blob SHA-1 prefixes of the 9ec00d24 binaries that carry n=2,500 content.
STALE_BINARY_BLOB_PREFIXES = {
    "docs/figures/atlas_audit_bridge.png": "59c95f20",
    "docs/figures/atlas_codebook_context_fence.png": "3bf61bf7",
    "docs/figures/atlas_dashboard_ui_walkthrough.png": "52c36d53",
    "docs/figures/atlas_labor_market_distribution.png": "39f72ad1",
    "docs/ATLAS_Methodology_and_Reference_Manual.docx": "83fadc88",
    "docs/ATLAS_Methodology_and_Reference_Manual.pdf": "0fba6aa3",
    "docs/ATLAS_Practitioner_Field_Guide_Program_Evaluation.pdf": "97d151f3",
}

_TAG = re.compile(r"<[^>]+>")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_EXTERNAL_URL = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)
_MD_IMG_URL = re.compile(r"!\[[^\]]*\]\(\s*<?(https?://[^)\s>]+)", re.IGNORECASE)
_HTML_IMG_URL = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"'](https?://[^\"']+)", re.IGNORECASE)
_MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*[\"'])?\s*\)")
_HTML_REF = re.compile(r"\b(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


# ----------------------------------------------------------------------
# Helpers: independent expectations from the real modules
# ----------------------------------------------------------------------
def engine_results(codebook_name, files, tabular_options=None):
    engine = AtlasEngine(str(CONFIG_DIR / codebook_name))
    results = engine.process_corpus(
        [str(f) for f in files], root_dir=str(REPO_ROOT), tabular_options=tabular_options
    )
    return engine, results


def expected_topics(results, n_topics):
    turns = results["tagged_turns_df"].to_dict("records")
    return discover_topics(turns, n_topics=n_topics)["topics"]


def git_blob_sha1(path):
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode("utf-8") + raw).hexdigest()


def to_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if isinstance(value, float) and math.isnan(value) else float(value)
    match = _NUMBER.search(str(value))
    return float(match.group(0).replace(",", "")) if match else None


def plain(text):
    return html.unescape(_TAG.sub(" ", str(text)))


# ----------------------------------------------------------------------
# Helpers: reading the rendered app
# ----------------------------------------------------------------------
def boot():
    at = AppTest.from_file(str(APP_PATH), default_timeout=20)
    at.run()
    return at


def walk(node):
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, dict):
        for child in children.values():
            yield from walk(child)


def raw_display_texts(at):
    """Body text of every non-widget display element (widget labels excluded)."""
    texts = []
    for accessor in ("markdown", "caption", "info", "warning", "success", "error",
                     "text", "title", "header", "subheader", "code"):
        for el in getattr(at, accessor):
            texts.append(str(el.value))
    for m in at.metric:
        texts.append(f"{m.label} {m.value}")
    return texts


def rendered_frames(at):
    frames = [el.value for el in at.dataframe]
    frames.extend(el.value for el in at.table)
    return [f for f in frames if isinstance(f, pd.DataFrame)]


def rendered_corpus(at):
    """All display text (tags stripped, entities unescaped) plus every table cell."""
    parts = [plain(t) for t in raw_display_texts(at)]
    for frame in rendered_frames(at):
        parts.extend(str(c) for c in frame.columns)
        parts.extend(str(v) for v in frame.astype(str).to_numpy().ravel())
    return "\n".join(parts)


def find_widget(at, accessor, label):
    for widget in getattr(at, accessor):
        if widget.label == label:
            return widget
    raise AssertionError(f"No {accessor} labelled {label!r} rendered")


def option_containing(selectbox, *needles):
    for opt in selectbox.options:
        if all(n.lower() in str(opt).lower() for n in needles):
            return opt
    raise AssertionError(f"No {selectbox.label!r} option contains {needles}; options: {selectbox.options}")


def select(at, label, value):
    box = find_widget(at, "selectbox", label)
    if value not in box.options:
        raise AssertionError(f"{value!r} not offered by {label!r}; options: {box.options}")
    box.set_value(value)
    at.run()
    return at


def run_analysis(at):
    find_widget(at, "button", RUN_LABEL).click()
    at.run()
    return at


def topic_count_control(at):
    for accessor in ("slider", "number_input"):
        for widget in getattr(at, accessor):
            if "topic" in str(widget.label).lower():
                return int(widget.value)
    raise AssertionError("No slider/number_input whose label mentions 'topic' (n_topics control) is rendered")


def kpi_value(at, label):
    for m in at.metric:
        if str(m.label).strip() == label:
            return to_number(m.value)
    for md in at.markdown:
        text = plain(md.value)
        if label in text:
            numbers = _NUMBER.findall(text.replace(label, " "))
            if len(numbers) == 1:
                return to_number(numbers[0])
    raise AssertionError(f"KPI {label!r} is not rendered as st.metric or a single-number markdown card")


def column_matches(frame, key_col, expected_by_key, tol):
    for col in frame.columns:
        if col == key_col:
            continue
        ok = True
        for _, row in frame.iterrows():
            got = to_number(row[col])
            want = expected_by_key.get(str(row[key_col]))
            if got is None or want is None or abs(got - want) > tol:
                ok = False
                break
        if ok:
            return col
    return None


def find_domain_table(at, frequencies, metrics):
    """Return (frame, key_col, matched_cols) for a rendered table that lists exactly
    the codebook's domains and carries every expected per-domain metric column.

    metrics maps a name to ({domain_name: value}, tolerance)."""
    names = [str(n) for n in frequencies["domain_name"]]
    ids = [str(i) for i in frequencies["domain_id"]]
    id_to_name = dict(zip(ids, names))
    for frame in rendered_frames(at):
        for key_col in frame.columns:
            cells = [str(v) for v in frame[key_col]]
            if sorted(cells) == sorted(names):
                to_key = {n: n for n in names}
            elif sorted(cells) == sorted(ids):
                to_key = {i: id_to_name[i] for i in ids}
            else:
                continue
            matched = {}
            for metric, (by_name, tol) in metrics.items():
                by_key = {k: by_name[n] for k, n in to_key.items()}
                col = column_matches(frame, key_col, by_key, tol)
                if col is None:
                    break
                matched[metric] = col
            else:
                return frame, key_col, matched
    return None


def domain_metric(frequencies, column):
    return {str(r["domain_name"]): float(r[column]) for _, r in frequencies.iterrows()}


def assert_no_exceptions(testcase, at, context):
    testcase.assertEqual(
        len(at.exception), 0,
        f"{context}: app raised {[getattr(e, 'value', e) for e in at.exception]}",
    )


# ======================================================================
# 1. Clean boot, zero external assets, zero missing-file warnings
# ======================================================================
class TestCleanBootAndOfflineAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.at = boot()

    def test_boots_without_exceptions(self):
        assert_no_exceptions(self, self.at, "default boot")

    def test_no_missing_data_warnings(self):
        for w in self.at.warning:
            for stale in ("No frequency data found", "No quote inventory found"):
                self.assertNotIn(stale, str(w.value), "app still depends on absent ../ datasets")

    def test_clean_upload_onboarding_and_no_software_test_ui_jargon(self):
        # Owner-approved v1.2 UI contract: opens on Upload Custom Files with a manual
        # Run Analysis button and keeps internal SOFTWARE_TEST fixture labels out of the UI.
        corpus = find_widget(self.at, "selectbox", CORPUS_LABEL)
        self.assertIn("Upload", str(corpus.value),
                      "default corpus should open on Upload Custom Files")
        self.assertEqual(find_widget(self.at, "selectbox", CODEBOOK_LABEL).value, "gbi_focus_group_starter.yaml")
        self.assertIsNotNone(find_widget(self.at, "button", RUN_LABEL))
        self.assertEqual(len(self.at.metric), 0, "analysis should wait until Run Analysis is clicked")
        for opt in corpus.options:
            self.assertNotIn("SOFTWARE_TEST", str(opt), f"internal test label leaked into dropdown: {opt!r}")
        for t in raw_display_texts(self.at):
            self.assertNotIn("SOFTWARE_TEST", t, f"internal test label leaked into UI: {t[:120]!r}")

    def test_no_external_image_urls(self):
        for node in walk(self.at._tree):
            proto = str(getattr(node, "proto", "") or "")
            self.assertNotIn("img.shields.io", proto, f"external badge in {getattr(node, 'type', node)}")
            if getattr(node, "type", None) in ("image", "imgs"):
                self.assertIsNone(_EXTERNAL_URL.search(proto), f"external image URL rendered: {proto[:200]}")
        for text in raw_display_texts(self.at):
            self.assertNotIn("img.shields.io", text)
            self.assertIsNone(_MD_IMG_URL.search(text), f"external markdown image: {text[:200]}")
            self.assertIsNone(_HTML_IMG_URL.search(text), f"external <img> source: {text[:200]}")

    def test_no_stale_mockup_literals_rendered(self):
        corpus_text = rendered_corpus(self.at)
        for widget in self.at.selectbox:
            corpus_text += "\n" + "\n".join(str(o) for o in widget.options)
        for pattern in STALE_LITERAL_PATTERNS:
            self.assertIsNone(pattern.search(corpus_text), f"stale mock-up literal {pattern.pattern!r} rendered")


# ======================================================================
# 2. Codebook switching proves live AtlasEngine execution
# ======================================================================
class TestDynamicCodebookSwitching(unittest.TestCase):
    """Survey corpus held fixed; pfl codebook matches one survey turn, intake none."""

    def _run_with(self, at, codebook):
        select(at, CODEBOOK_LABEL, codebook)
        run_analysis(at)
        assert_no_exceptions(self, at, f"codebook {codebook}")
        self.assertEqual(find_widget(at, "selectbox", CODEBOOK_LABEL).value, codebook)
        return at

    def _assert_engine_rendered(self, at, codebook):
        engine, results = engine_results(codebook, SURVEY_FILES, SURVEY_OPTIONS)
        freq = results["frequencies_df"]
        found = find_domain_table(at, freq, {
            "prevalence_pct": (domain_metric(freq, "prevalence_pct"), 0.051),
            "matching_turns": (domain_metric(freq, "matching_turns"), 0.0),
        })
        self.assertIsNotNone(
            found, f"{codebook}: no rendered table lists exactly the domains {list(freq['domain_name'])} "
                   "with matching prevalence_pct and matching_turns columns")
        self.assertEqual(kpi_value(at, KPI_DOMAINS), float(len(freq)))
        self.assertEqual(kpi_value(at, KPI_MATCHED), float(freq["matching_turns"].sum()))
        self.assertEqual(kpi_value(at, KPI_UNITS), float(results["total_documents"]))
        return engine, results

    def test_switching_codebook_changes_domains_and_metrics(self):
        at = boot()
        select(at, CORPUS_LABEL, option_containing(find_widget(at, "selectbox", CORPUS_LABEL), "Survey"))

        self._run_with(at, CODEBOOK_A)
        _, res_a = self._assert_engine_rendered(at, CODEBOOK_A)
        names_a = set(res_a["frequencies_df"]["domain_name"])
        text_a = rendered_corpus(at)
        matched_a = kpi_value(at, KPI_MATCHED)
        self.assertGreater(matched_a, 0, "pfl codebook should match at least one SOFTWARE_TEST survey turn")
        for _, q in res_a["quotes_df"].iterrows():
            self.assertIn(str(q["text"]), text_a, "matched quote text missing from quote browser")
            self.assertIn(str(q["source_sha256"])[:12], text_a, "quote source_sha256 not displayed")

        self._run_with(at, CODEBOOK_B)
        _, res_b = self._assert_engine_rendered(at, CODEBOOK_B)
        names_b = set(res_b["frequencies_df"]["domain_name"])
        text_b = rendered_corpus(at)
        self.assertTrue(names_a.isdisjoint(names_b))
        for name in names_a:
            self.assertNotIn(name, text_b, f"stale domain {name!r} from {CODEBOOK_A} still rendered")
        self.assertNotEqual(kpi_value(at, KPI_MATCHED), matched_a)
        self.assertNotEqual(kpi_value(at, KPI_DOMAINS), float(len(res_a["frequencies_df"])))

    def test_parameter_matrix_reports_live_n_and_binomial_se(self):
        at = boot()
        select(at, CORPUS_LABEL, option_containing(find_widget(at, "selectbox", CORPUS_LABEL), "Survey"))
        self._run_with(at, CODEBOOK_A)
        _, results = engine_results(CODEBOOK_A, SURVEY_FILES, SURVEY_OPTIONS)
        freq = results["frequencies_df"]
        n = int(results["total_documents"])
        se = {}
        for _, r in freq.iterrows():
            p = r["documents_reporting"] / n
            se[str(r["domain_name"])] = math.sqrt(p * (1 - p) / n)
        self.assertTrue(any(v > 0 for v in se.values()), "fixture should give one non-zero SE")
        found = find_domain_table(at, freq, {
            "prevalence_pct": (domain_metric(freq, "prevalence_pct"), 0.051),
            "N": ({k: float(n) for k in se}, 0.0),
            "se": (se, 0.0006),
        })
        self.assertIsNotNone(found, "no rendered parameter matrix with live prevalence, N and SE=sqrt(p(1-p)/N)")


# ======================================================================
# 3. Corpus switching proves live parser + atlas_discover execution
# ======================================================================
class TestDynamicCorpusSwitching(unittest.TestCase):

    def _load(self, at, needle, codebook=CODEBOOK_A):
        select(at, CORPUS_LABEL, option_containing(find_widget(at, "selectbox", CORPUS_LABEL), needle))
        select(at, CODEBOOK_LABEL, codebook)
        run_analysis(at)
        assert_no_exceptions(self, at, f"corpus {needle}")
        self.assertNotIn("SOFTWARE_TEST", str(find_widget(at, "selectbox", CORPUS_LABEL).value))
        return at

    def test_switching_corpus_updates_counts_quotes_and_medoids(self):
        at = boot()

        self._load(at, "Bilingual")
        _, res_bil = engine_results(CODEBOOK_A, BILINGUAL_FILES)
        k_bil = topic_count_control(at)
        topics_bil = expected_topics(res_bil, k_bil)
        text_bil = rendered_corpus(at)
        self.assertEqual(kpi_value(at, KPI_UNITS), float(res_bil["total_documents"]))
        self.assertEqual(kpi_value(at, KPI_TURNS), float(res_bil["participant_turns_analyzed"]))
        self.assertTrue(topics_bil, "discover_topics found no topics on the bilingual fixture")
        for topic in topics_bil:
            if topic["medoid_text"]:
                self.assertIn(topic["medoid_text"], text_bil, f"bilingual medoid of topic {topic['topic_id']} not rendered")
        self.assertFalse(any("SOFTWARE_TEST FIXTURE ACTIVE" in t for t in raw_display_texts(at)))

        self._load(at, "Survey")
        _, res_sur = engine_results(CODEBOOK_A, SURVEY_FILES, SURVEY_OPTIONS)
        k_sur = topic_count_control(at)
        topics_sur = expected_topics(res_sur, k_sur)
        text_sur = rendered_corpus(at)
        self.assertEqual(kpi_value(at, KPI_UNITS), float(res_sur["total_documents"]))
        self.assertEqual(kpi_value(at, KPI_TURNS), float(res_sur["participant_turns_analyzed"]))
        self.assertNotEqual(
            (res_bil["total_documents"], res_bil["participant_turns_analyzed"]),
            (res_sur["total_documents"], res_sur["participant_turns_analyzed"]),
        )
        for topic in topics_sur:
            if topic["medoid_text"]:
                self.assertIn(topic["medoid_text"], text_sur, f"survey medoid of topic {topic['topic_id']} not rendered")
        for _, q in res_sur["quotes_df"].iterrows():
            self.assertIn(str(q["text"]), text_sur, "survey quote missing from quote browser")
            self.assertIn(str(q["source_sha256"])[:12], text_sur, "survey quote source_sha256 not displayed")
            self.assertNotIn(str(q["text"]), text_bil, "survey quote leaked into bilingual corpus view")

        bil_medoids = {t["medoid_text"] for t in topics_bil if t["medoid_text"]}
        sur_medoids = {t["medoid_text"] for t in topics_sur if t["medoid_text"]}
        self.assertTrue(bil_medoids.isdisjoint(sur_medoids))
        for medoid in bil_medoids:
            self.assertNotIn(medoid, text_sur, "stale bilingual medoid still rendered after corpus switch")


# ======================================================================
# 4. Uploaded tables: text-column auto-detection skips id columns
#    (UI path, on a table generated afresh for every run)
# ======================================================================
UPLOAD_NAME = "software_test_random_upload.csv"
UPLOAD_ANCHOR = "Cuando se agotó el beneficio, busqué otro trabajo."  # matches PFL_GAP
_UPLOAD_VOCAB = (
    "clinic shift evening appointments childcare bus schedule paperwork weeks caseworker "
    "forms neighbor temporary rent hours pharmacy transit interpreter office morning "
    "wait line phone letter"
).split()


def random_upload_table(rng, id_cols, text_col):
    """SOFTWARE_TEST table with long unique ids and unique free-text answers; one
    answer is the anchor sentence so the pfl codebook always matches a row."""
    n_rows = rng.randint(5, 9)
    texts = {UPLOAD_ANCHOR}
    while len(texts) < n_rows:
        texts.add(" ".join(rng.sample(_UPLOAD_VOCAB, rng.randint(5, 9))).capitalize() + ".")
    texts = sorted(texts)
    rng.shuffle(texts)
    rows = []
    for i, text in enumerate(texts, 1):
        row = {c: f"{c[:3].upper()}-{rng.getrandbits(64):016x}-{i:02d}" for c in id_cols}
        row[text_col] = text
        rows.append(row)
    return pd.DataFrame(rows, columns=[*id_cols, text_col])


class TestUploadedTableTextColumnDetection(unittest.TestCase):
    """Drives the upload path in the real UI. Either implementation passes: a
    text-column selector (label mentions "text" and "column") whose default is
    the free-text column, or internal auto-detection. Either way the rendered
    KPIs, quotes and medoids must equal the engine's output for the free-text
    column, computed here at test time on a freshly generated table."""

    def _upload_and_check(self, id_cols, text_col):
        seed = int.from_bytes(os.urandom(4), "big")
        ctx = f"(random table seed={seed}, columns={[*id_cols, text_col]})"
        frame = random_upload_table(random.Random(seed), id_cols, text_col)
        payload = frame.to_csv(index=False).encode("utf-8")

        at = boot()
        select(at, CORPUS_LABEL, option_containing(find_widget(at, "selectbox", CORPUS_LABEL), "Upload"))
        uploaders = [
            u for u in at.file_uploader
            if "csv" in {str(t).lstrip(".").lower() for t in (u.allowed_type or [])}
        ]
        self.assertTrue(uploaders, f"no file_uploader accepting .csv after choosing the upload corpus {ctx}")
        uploaders[0].set_value((UPLOAD_NAME, payload, "text/csv"))
        at.run()
        select(at, CODEBOOK_LABEL, CODEBOOK_A)
        run_analysis(at)
        assert_no_exceptions(self, at, f"uploaded table {ctx}")

        for box in at.selectbox:
            label = str(box.label).lower()
            if "text" in label and "column" in label:
                self.assertEqual(box.value, text_col, f"text-column selector defaulted to an id column {ctx}")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / UPLOAD_NAME
            path.write_bytes(payload)
            _, results = engine_results(CODEBOOK_A, [path], {"text_col": text_col})
        self.assertGreaterEqual(len(results["quotes_df"]), 1, f"generator precondition failed {ctx}")
        topics = expected_topics(results, topic_count_control(at))
        text = rendered_corpus(at)

        self.assertEqual(kpi_value(at, KPI_UNITS), float(results["total_documents"]), ctx)
        self.assertEqual(kpi_value(at, KPI_TURNS), float(results["participant_turns_analyzed"]), ctx)
        self.assertEqual(kpi_value(at, KPI_MATCHED), float(results["frequencies_df"]["matching_turns"].sum()), ctx)
        for _, q in results["quotes_df"].iterrows():
            self.assertIn(str(q["text"]), text, f"uploaded-table quote not rendered {ctx}")
        for topic in topics:
            if topic["medoid_text"]:
                self.assertIn(topic["medoid_text"], text, f"medoid of topic {topic['topic_id']} not rendered {ctx}")

    def test_skips_id_columns_before_response(self):
        self._upload_and_check(["response_id", "participant_id"], "response")

    def test_skips_bare_and_uppercase_id_columns(self):
        self._upload_and_check(["id", "Respondent_ID"], "open_comment")


# ======================================================================
# 5. Documentation and binary figure hygiene
# ======================================================================
def doc_files():
    files = [REPO_ROOT / "README.md"]
    files.extend(sorted((REPO_ROOT / "docs").rglob("*.md")))
    files.extend(sorted((REPO_ROOT / "docs").rglob("*.html")))
    return [f for f in files if f.is_file()]


class TestDocumentationAndFigureHygiene(unittest.TestCase):

    def test_stale_n2500_binaries_regenerated_or_removed(self):
        for rel, stale_prefix in STALE_BINARY_BLOB_PREFIXES.items():
            with self.subTest(binary=rel):
                path = REPO_ROOT / rel
                if path.exists():
                    self.assertFalse(
                        git_blob_sha1(path).startswith(stale_prefix),
                        f"{rel} is still the stale 9ec00d24 n=2,500 binary ({stale_prefix})",
                    )

    def test_relative_links_and_images_resolve(self):
        for doc in doc_files():
            text = doc.read_text(encoding="utf-8", errors="replace")
            targets = _MD_LINK.findall(text) + _HTML_REF.findall(text)
            for target in targets:
                target = target.strip()
                if not target or target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                    continue
                rel = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not rel:
                    continue
                with self.subTest(doc=doc.relative_to(REPO_ROOT).as_posix(), link=target):
                    resolved = (doc.parent / rel).resolve()
                    self.assertTrue(resolved.is_relative_to(REPO_ROOT), f"link escapes repository: {target}")
                    self.assertTrue(resolved.exists(), f"broken relative link: {target}")

    def test_no_unbacked_mockup_literals_in_docs(self):
        for doc in doc_files():
            text = doc.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                for pattern in STALE_LITERAL_PATTERNS:
                    with self.subTest(doc=doc.relative_to(REPO_ROOT).as_posix(), pattern=pattern.pattern):
                        self.assertIsNone(
                            pattern.search(line),
                            f"{doc.name}:{lineno}: unbacked literal {pattern.pattern!r}: {line.strip()[:120]}",
                        )


if __name__ == "__main__":
    unittest.main()
