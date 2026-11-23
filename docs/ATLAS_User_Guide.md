# ATLAS User Guide
## Automated Text-to-Ledger Actuarial Synthesis: the local workbench (`v1.2`)

**ATLAS is a local qualitative coding and topic-discovery workbench that turns transcripts, 3-column Word focus-group notes, and open-ended survey tables into line-auditable counts and verified exports.** Every step runs on your own machine using deterministic keyword rules and local topic models, so participant text stays private and repeated runs with the same files and codebook always produce the exact same counts.

> Examples in this guide use the built-in `SOFTWARE_TEST` fixtures in `data/samples/`. They demonstrate
> software mechanics only; no number here is a research finding.

---

## Table of Contents

1. [What ATLAS does](#1-what-atlas-does)
2. [Installing and launching](#2-installing-and-launching)
3. [Preparing data](#3-preparing-data)
4. [The sidebar](#4-the-sidebar)
5. [Tab 1: thematic discovery, coding, and false-alarm spot-check](#5-tab-1-thematic-discovery-coding-and-false-alarm-spot-check)
6. [Tab 2: parameter matrix and exports](#6-tab-2-parameter-matrix-and-exports)
7. [Tab 3: formatted reference guides](#7-tab-3-formatted-reference-guides)
8. [Writing and customizing a codebook](#8-writing-and-customizing-a-codebook)
9. [Troubleshooting](#9-troubleshooting)
10. [Glossary](#10-glossary)

---

## 1. What ATLAS does

Qualitative analysis often breaks down at the handoff between reading text and reporting numbers: hand-coded spreadsheets drift across sessions, while black-box summaries lose line-level traceability. ATLAS resolves that gap by separating parsing, theme discovery, deterministic coding, and cryptographic verification into four linked steps:

* **Parses transcripts, 3-column focus-group notes, and survey tables into turns.** Each parsed turn records its speaker, source file, line number, character offsets, and—for structured focus-group notes—its evidence type (verbatim quote, paraphrased key point, or observation).
* **Codes participant turns against an explicit YAML codebook.** After excluding facilitator turns and prompt patterns, ATLAS matches each remaining turn against root terms (using either word-start prefix matching or strict whole-word `match_mode: exact`), optional context fences, and optional exclusion fences.
* **Measures prevalence on the right denominator.** In Individual Mode, ATLAS counts analytical units (one per transcript or survey row) and reports Binomial standard errors. In Group Mode (chosen automatically for 3-column focus-group notes), ATLAS counts focus groups (`1 file = 1 group`), reports integer groups reporting (`g of G`) plus distinct participant voices, and hides normal-approximation Binomial intervals that are invalid for small, clustered groups.
* **Discovers emergent themes offline and audits false alarms.** ATLAS defaults to **TF-IDF + NMF** topic discovery (with classic **LDA** selectable), pairs each topic with its representative **medoid** turn, lets you append any discovered theme straight onto your active codebook in one click, and includes a **False-Alarm Spot-Check** tab to flag prefix collisions and nearby negations.
* **Exports verified spreadsheets and manifests.** ATLAS writes an Excel workbook whose prevalence cells carry `ATLAS VERIFICATION AUDIT STAMP` comments, a JSON provenance manifest with source-file SHA-256 hashes, and separate CSV quote/evidence inventories, then verifies that the workbook matches the manifest before showing download buttons.

ATLAS does **not** paraphrase, summarize, translate, correct spelling, or score sentiment. ATLAS code makes no network requests and the page loads no remote assets; see [Privacy and network use](../README.md#privacy-and-network-use) for what Streamlit and the operating system do around it.

![Flow diagram of the ATLAS pipeline from transcript and table inputs through UniversalTranscriptParser, then atlas_discover topic discovery alongside AtlasEngine codebook matching, to exports checked by verify_workbook_integrity](figures/atlas_pipeline_architecture.png)

---

## 2. Installing and launching

You do not need to install packages manually or configure Python paths. Each desktop launcher checks for Python 3.10+, builds a local `.venv` folder inside the `atlas` directory, installs `requirements.txt` only when `.venv` is missing or dependencies changed, verifies core imports, and opens the app at `http://localhost:8501`.

* **macOS / Linux:** Double-click `run.command` (or run `bash run.command` in Terminal).
* **Windows:** Double-click `run.bat`.
* **Verify setup without launching the browser:** Run `./run.command --check-only` or `run.bat --check-only` (or set `ATLAS_NO_LAUNCH=1`) to provision and verify `.venv`, then exit cleanly.
* **Bind strictly to this machine on a shared network:** The desktop launchers disable Streamlit usage statistics (`--browser.gatherUsageStats=false`) but leave Streamlit listening on local network interfaces so you can preview on another device if desired. On an untrusted or shared Wi-Fi network, launch from the command line with `--server.address=localhost`:
  `.venv/bin/streamlit run app.py --server.address=localhost --browser.gatherUsageStats=false`.

---

## 3. Preparing data

ATLAS reads six common qualitative file formats without requiring reformatting into a proprietary schema. Because the parser preserves exact line numbers and character positions, keep original files clean and strip unnecessary personal identifiers before uploading.

| Format | How ATLAS reads it |
| :--- | :--- |
| `.txt`, `.md` | One turn per speaker label such as `Name [00:01:12]: text` or `Name: text`. |
| `.vtt`, `.srt` | Caption cues from Zoom or video tools; `<v Speaker>` voice tags or `Speaker:` prefixes identify speakers. |
| `.docx` (ordinary transcripts) | Paragraphs or speaker/text tables, including Microsoft Teams exports with multi-line turns. |
| `.docx` (3-column focus-group notes) | Tables with `Key Points`, `Notable Quotes`, and `Observations` columns (in any order). Session headers, consent rows, prompts, and summary boxes are excluded; note-taker `Themes` rows are separated into a reference panel; participant labels (`P1`, `P2`, ...) are scoped per file. |
| `.csv`, `.xlsx` | One response per row; header row required; leading `#` comment lines in a CSV are skipped. |

For tabular uploads (`.csv` / `.xlsx`), ATLAS auto-detects the free-text column—never choosing columns named `id` or ending in `_id`—and lets you pick optional **Respondent ID** and **Speaker / role** columns. Blank responses are skipped automatically. Duplicate respondent IDs stop the run with an error because each row in Individual Mode must represent one distinct unit.

**Data protection.** Files stay on your local machine during analysis, but exported CSV and Excel inventories contain coded participant text. Remove direct names or contact details you do not need before creating shareable exports.

---

## 4. The sidebar

Every analysis choice lives in the left sidebar and takes effect when you click **`▶ Run Analysis`**.

![SOFTWARE_TEST walkthrough of the ATLAS workbench showing the sidebar corpus and codebook selectors, four Tab 1 KPI cards for the survey sample, the prevalence, quote and topic panels, and the Tab 2 export files](figures/atlas_dashboard_ui_walkthrough.png)

### Corpus Dataset

| Option | Files loaded |
| :--- | :--- |
| Upload Custom Files (.docx, .vtt, .srt, .txt, .md, .csv, .xlsx) | Default on launch: upload one or more files from your workstation |
| Sample: Multi-Group Focus-Group Notes (.docx) | `software_test_gbi_group_treatment.docx` + `software_test_gbi_group_control.docx` |
| Sample: Bilingual Interview Transcripts | `software_test_bilingual_interview.txt` + `software_test_zoom_session.vtt` |
| Sample: Community Health Survey (.csv) | `software_test_survey.csv` (text `response`, id `respondent_id`, speaker `role`) |
| Sample: Teams Multiline Transcript (.docx) | `software_test_teams_multiline.docx` |

When **Upload Custom Files** is selected, table-column selectors appear automatically for `.csv` / `.xlsx` uploads. Optional **Facilitator names** and **Interviewer prompt patterns** sit tucked inside a collapsed **Advanced transcript filters (optional)** expander for free-form or mixed uploads—and stay completely hidden when every uploaded file is a 3-column focus-group `.docx` notes table in Group Mode, because the structured notes parser already strips headers, prompts, and summary boxes automatically. When no facilitator names are entered on a free-form transcript, any named speaker who asks more than half of at least three questions is treated as the facilitator.

### Data Type (Individual vs. Group Mode)

Directly below the corpus controls, **Data Type** switches between **Individual transcripts / survey responses** and **Group / summarized notes**. Whenever any uploaded `.docx` contains a 3-column focus-group notes table, ATLAS automatically selects **Group / summarized notes** (`1 file = 1 group`), though you can override the toggle at any time. In Group Mode, **Include Note-Taker Observations** stays unchecked by default so only participant-attributed key points and notable quotes are coded unless you explicitly opt in.

### Active YAML Codebook, Stacking, and `▶ Run Analysis`

**Active YAML Codebook** defaults to **`gbi_focus_group_starter.yaml`** and lists every `.yaml` starter codebook in `config/`, any discovered or customized codebook created during the session, and **Upload Custom Codebook (.yaml)**. Selecting a built-in sample picks its matching starter codebook automatically.

Below that selector, **Stack Additional Starter Codebooks (optional)** lets you combine domains from two or more starter packs (for example, `gbi_focus_group_starter.yaml` plus `sdoh_basic_needs.yaml`) without merging YAML files by hand. ATLAS preserves each domain's own matching mode and fences and disambiguates any colliding IDs or display names.

Click **`▶ Run Analysis`** when your files and codebooks are ready. Because ATLAS waits for **`▶ Run Analysis`** instead of re-coding on every click, you can upload multiple files and stack several starter packs smoothly before running once. If you later change sidebar inputs, a notice reminds you to click **`▶ Run Analysis`** again to refresh the results. Whenever you have stacked codebooks or a session-customized codebook active, a **`📥 Download Active Codebook (.yaml)`** button appears in the sidebar so you can archive the exact rules used.

### Reference Guides (Word `.docx`)

The bottom of the sidebar offers one-click formatted **Word (`.docx`)** downloads for all four guides, generated live from `docs/*.md` so they never fall out of sync. You can also read every guide formatted right inside **Tab 3: Reference Guides**.

---

## 5. Tab 1: thematic discovery, coding, and false-alarm spot-check

The top of Tab 1 displays a concise, literal plain-text run summary (`Corpus: ... · Codebook: <primary> (+N stacked · K domains)`) followed by four KPI cards that adapt to the selected Data Type.

### KPI cards

In **Individual Mode**, the four cards count independent units and turns:

| Card | Meaning | SOFTWARE_TEST survey × `pfl_case_study_codebook.yaml` |
| :--- | :--- | ---: |
| Analytical Units (N) | Transcripts plus respondent rows | 6 |
| Participant Turns | Turns coded after facilitator turns are removed | 6 |
| Active Domains | Domains in the active codebook | 5 |
| Matched Turn Mentions | Matching participant turns, summed over domains | 1 |

In **Group Mode**, the four cards reflect focus-group structure instead: **Focus Groups (G)** (`1 file = 1 group`), **Distinct Participant Voices** (counting `(source_id, speaker)` pairs so `P1` in two rooms counts as two voices), **Coded Notes Entries**, and **Active Domains**.

### Thematic Prevalence & Distribution

In Individual Mode, this sub-tab plots a horizontal bar chart of unit prevalence (`%`) labeled by matching turns, paired with a full-width accessible summary and domain table. In Group Mode, it shows two views: an integer **Groups Reporting (`g of G`)** bar chart and a **Group × Theme Matrix** showing distinct participant voices per group (`2v`, `✓` for unattributed matches, or `—` when absent). When structured focus-group notes contain note-taker `Themes` rows, those rows appear inside a collapsed **Note-Taker Themes Summary (Reference Only)** expander below the table so they never inflate participant counts.

### Verbatim Quote / Coded Evidence & Provenance Browser

Search text, filter by domain or speaker (and by group or question in Group Mode), and inspect each match with its highlighted span, `source_id`, `unit_id`, line number, `match_char_start`–`match_char_end`, and `source_sha256`. On the built-in `SOFTWARE_TEST` survey sample, the single match is `R001`, line 2, span `7–28` (`se agotó el beneficio`), file SHA-256 beginning `02a7a3c8239a`.

When paraphrased key points or note-taker observations are present (such as in 3-column focus-group notes), the tab title switches to **Coded Evidence & Provenance Browser**, every card carries an evidence-type badge (**Verbatim Quote** vs. **Paraphrase (Key Point)** vs. **Note-Taker Observation**), and Group Mode provides a **`Quotable Verbatim Only`** checkbox that hides all paraphrases and observations so you never misquote a note-taker's summary.

![SOFTWARE_TEST context-fence diagram listing PFL_GAP roots and fence words, then two survey rows where a matched root counts only when a fence word appears in the same turn](figures/atlas_codebook_context_fence.png)

### Unsupervised Topic Discovery (Medoids)

Topic discovery helps you surface themes your current codebook does not yet cover. Choose **Discovery method**—defaulting to **`TF-IDF + NMF`** (faster, deterministic across runs, and sharper non-overlapping keywords) with classic **`LDA`** still selectable—and set **Number of topics (k)** between `1` and `10`. ATLAS automatically clamps `k` to the supported unique-pattern rank and drops empty or ownerless components so topics never duplicate keywords. Each topic displays its exclusive top terms, turn count and share, and its **medoid**: the real turn (or coded notes entry, tagged with its evidence type) closest to that topic's TF-IDF centroid.

From the discovered topics, you have three options:

* **`📥 Download Discovered Codebook (.yaml)`** exports all discovered topics as a standalone draft `domains` codebook.
* **`⚡ Apply Discovered Codebook to Engine`** replaces the active codebook with that full discovered draft for exploratory inspection.
* **`➕ Add Theme to Active Codebook`** keeps every domain in your current codebook (including any stacked starter packs) and appends one chosen topic as a new domain—with an optional custom name and **exact whole-word matching** enabled by default so short discovered words do not create prefix false alarms.

### False-Alarm Spot-Check

Keyword rules can produce subtle false matches when short stems match longer unrelated words or when a speaker explicitly negates a barrier. The fourth sub-tab, **`🔎 False-Alarm Spot-Check`**, automatically audits every coded match against three transparent checks:

1. **Prefix extension (High risk):** A root matched only the start of a different longer word (for example, `car` matching inside `card` or `career`), while ignoring benign plurals (`cars`, `bills`) and routine inflections on longer stems (`evicted`, `benefits`).
2. **Nearby negation (Medium risk):** A negation word (`not`, `never`, `no`, `without`, `didn't`, including curly Word apostrophes) appears within 5 tokens of the match.
3. **Short unfenced prefix root (Medium risk):** A 4-character-or-shorter single-word stem matched in prefix mode on a rule that has neither context fences nor exclusion fences.

Right inside that tab, you can download **`atlas_false_alarm_spot_check.csv`** for team review or tighten a noisy domain without editing YAML using two buttons: **`🛡️ Exclude Selected Words from Domain`** (which adds selected false-alarm words to `exclude_fences` and discloses whether a `0`-token or existing wider exclusion window applies) or **`🎯 Switch Domain to Exact Whole-Word Matching`** (which sets `match_mode: exact` on that domain and immediately re-codes).

---

## 6. Tab 2: parameter matrix and exports

Tab 2 presents the exportable summary table and integrity-checked downloads.

In **Individual Mode** (ordinary transcripts and surveys), the matrix reports per domain: units reporting, **N (analytical units)**, prevalence (`%`), proportion `p`, Binomial standard error `SE = √(p(1 − p)/N)`, a normal-approximation 95% interval `p ± 1.96·SE` (clipped to `0–100%`), and matching turns.

SOFTWARE_TEST survey × `pfl_case_study_codebook.yaml`:

| Domain ID | Units reporting | N | Prevalence (%) | Binomial SE | Matching turns |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `PFL_GAP` | 1 | 6 | 16.7 | 0.152 | 1 |
| `PFL_REPLACE` | 0 | 6 | 0.0 | 0.000 | 0 |
| `PFL_WAGE` | 0 | 6 | 0.0 | 0.000 | 0 |
| `PFL_PORTAL` | 0 | 6 | 0.0 | 0.000 | 0 |
| `PFL_STIGMA` | 0 | 6 | 0.0 | 0.000 | 0 |

In **Group Mode** (and whenever structured focus-group notes are loaded), ATLAS displays an explicit statistical guardrail banner and hides Binomial SE and 95% confidence intervals because small group counts (`G`) and clustered group discussions violate independent Binomial sampling. Instead, Tab 2 shows the exact **Groups Reporting (`g of G`)** bar chart and group frequency table.

**Downloads** (generated live by `AtlasEngine.export_results` for the active run):

| File | Contents |
| :--- | :--- |
| `actuarial_parameter_matrix.xlsx` | Frequency sheet whose prevalence cells carry `ATLAS VERIFICATION AUDIT STAMP` comments, plus a quote/evidence sheet with full provenance |
| `provenance_manifest.json` | Run counts, per-domain values and digests, and SHA-256 hash of every source file |
| `verbatim_quotes_inventory.csv` | Direct verbatim words only (transcript/survey turns and `Notable Quotes` from notes) |
| `coded_evidence_inventory.csv` | Written whenever paraphrases or observations are present: all coded entries with explicit `evidence_type` and `question_id` columns |
| `atlas_active_codebook.yaml` | Offered whenever you stacked or customized a codebook in the session, so you can archive your exact coding rules alongside the manifest |

A green banner confirms that `AtlasEngine.verify_workbook_integrity` verified every prevalence cell and audit stamp against `provenance_manifest.json`; a red banner lists any discrepancy. The **Source files and SHA-256 digests** expander lists every input file's cryptographic fingerprint for comparison against your originals.

![Four-step SOFTWARE_TEST audit bridge diagram tracing a highlighted verbatim survey quote with file SHA-256 to its coded frequency row, Excel cell audit-stamp comment, and verify_workbook_integrity PASS check](figures/atlas_audit_bridge.png)

---

## 7. Tab 3: formatted reference guides

Instead of forcing analysts to read raw Markdown text in Notepad, **📚 Tab 3: Reference Guides** renders all four guides—the GBI Analyst Quick-Start Guide, this User Guide, the Methodology & Reference Manual, and the Practitioner Field Guide—formatted cleanly inside ATLAS with tables and diagrams displayed inline. A download button at the top of Tab 3 (and in the sidebar) exports the selected guide as a formatted Word (`.docx`) file for printing or sharing.

---

## 8. Writing and customizing a codebook

You can customize rules inside the workbench (via stacking, one-click topic addition, and False-Alarm Spot-Check) or author a YAML codebook directly in any text editor. Every codebook compiles through the same normalizer in `atlas_engine.py`:

```yaml
project: "Example SOFTWARE_TEST codebook"
match_mode: prefix             # optional codebook default: "prefix" (default) or "exact"
domains:
  - id: TRANSIT
    name: Transit barriers
    match_mode: exact          # optional per-domain override: prevents "car" hitting "card" or "career"
    roots_en: ["bus", "transit", "fare", "car"]
    roots_es: ["autobús", "transporte"]
    context_fences: ["appointment", "clinic", "cita"]
    context_window: 8          # fence within 8 tokens of the root
  - id: CHILDCARE
    name: Childcare access
    roots_en: ["childcare"]
    exclude_fences: ["not a problem"]
    exclude_window: 3          # veto roots within 3 tokens of the exclusion
```

* **Prefix vs. exact matching:** By default (`match_mode: prefix`), roots match case- and accent-insensitively at word starts (`evict` matches `eviction`; `autobus` matches `autobús`). Setting `match_mode: exact` at the codebook or domain level enforces whole-word boundaries on both ends so short stems never spill into unrelated words.
* **Context fences:** A rule with `context_fences` counts a root only when a fence term also appears in the turn (or within `context_window` tokens when set). A `context_window` without fences has no effect.
* **Exclusion fences:** An exclusion fence without `exclude_window` vetoes the domain for the whole turn. With `exclude_window: 0`, it vetoes only matches overlapping that same word (ideal for excluding `card` or `career` on a prefix rule without blocking a real `car` elsewhere in the turn); with `exclude_window: N`, it vetoes roots within `N` tokens of the excluded phrase.
* **Equivalent schemas:** ATLAS accepts `domains` (with `roots_en`, `roots_es`, or `roots`), `topics` (`label`, `keywords`, `required_context`, `context_window`), and `themes` + `frictions`. Inspect the seven shipped packs in `config/` for ready-to-adapt examples, and see the [Methodology & Reference Manual](ATLAS_Methodology_and_Reference_Manual.md) for the complete specification.

---

## 9. Troubleshooting

| Message or symptom | Cause and fix |
| :--- | :--- |
| `The uploaded tables share no column names` | Several tables were uploaded with different headers; one free-text column must exist across all uploaded tables, or analyze them one at a time. |
| `Duplicate unit id` | Two rows share a respondent ID; make respondent IDs unique or leave the Respondent ID column set to `(none)`. |
| `... must be a nonnegative whole token count` | A `context_window` or `exclude_window` is negative, fractional, or text; supply a whole number such as `0`, `5`, or `8`. |
| `Invalid match_mode ...` | `match_mode` must be either `prefix` or `exact`. |
| `Duplicate codebook rule id` | Two domains inside one YAML file share an `id`; give each domain a distinct ID. |
| Unexpected false matches on short words | Open **🔎 False-Alarm Spot-Check** and click **Exclude Selected Words from Domain** or **Switch Domain to Exact Whole-Word Matching**. |
| All counts are 0 | None of the roots (or required context fences) occurred in participant turns; test a fence-free copy or inspect discovered topics to see the vocabulary participants actually used. |
| A speaker's turns are missing | That speaker was auto-detected as the facilitator; enter the true facilitator names in the sidebar. |
| Integrity banner is red | The exported workbook and manifest disagree; regenerate both from the same run. |

---

## 10. Glossary

| Term | Meaning |
| :--- | :--- |
| Turn | One speaker's contiguous contribution, one structured-notes entry, or one table response. |
| Analytical unit | The prevalence denominator: a transcript or survey row in Individual Mode, or one focus-group file (`1 file = 1 group`) in Group Mode. |
| `source_id` | A file's POSIX path relative to the corpus root. |
| `unit_id` | An analytical unit's identifier (`source_id` for transcripts/group notes, `source_id::id` for table rows). |
| Root | A codebook term matched case- and accent-insensitively at word starts (`prefix`) or on both word boundaries (`exact`). |
| Context fence | A term that must also occur (within `context_window` tokens, if set) for a root match to count. |
| Exclusion fence | A term that vetoes a root match (within `exclude_window` tokens, or across the whole turn when no window is set). |
| Medoid | The real turn or coded notes entry closest to a discovered topic's TF-IDF centroid. |
| Evidence type | Provenance tag separating direct speech (`notable_quote_verbatim`, `verbatim_turn`) from note-taker summaries (`key_point_paraphrase`, `observation`). |
| Audit stamp | The Excel comment on each prevalence cell holding exact counts and a verification SHA-256 digest. |
| `SOFTWARE_TEST` | Label on built-in synthetic fixtures that demonstrate software mechanics, never empirical findings. |
