# ATLAS User Guide
## Automated Text-to-Ledger Actuarial Synthesis: the local workbench

> Examples in this guide use the built-in `SOFTWARE_TEST` fixtures in `data/samples/`. They demonstrate
> software mechanics only; no number here is a research finding.

---

## Table of Contents

1. [What ATLAS does](#1-what-atlas-does)
2. [Installing and launching](#2-installing-and-launching)
3. [Preparing data](#3-preparing-data)
4. [The sidebar](#4-the-sidebar)
5. [Tab 1: thematic discovery and coding](#5-tab-1-thematic-discovery-and-coding)
6. [Tab 2: parameter matrix and exports](#6-tab-2-parameter-matrix-and-exports)
7. [Writing a codebook](#7-writing-a-codebook)
8. [Troubleshooting](#8-troubleshooting)
9. [Glossary](#9-glossary)

---

## 1. What ATLAS does

* Splits transcripts and response tables into **turns**, each with a speaker, line number and
  character offsets.
* Removes facilitator turns, then codes each participant turn against a **YAML codebook**.
* Counts, per domain, how many **analytical units** (transcripts or table rows) report it, and lists
  every matching turn verbatim with its source line, character span and the source file's SHA-256.
* Suggests emergent topics with LDA and shows a real **medoid** turn for each.
* Exports an Excel workbook with audit-stamp comments, a provenance manifest and a quote inventory,
  and checks that the workbook still matches the manifest.

ATLAS does **not** paraphrase, summarise, translate, correct spelling or score sentiment. ATLAS code
makes no network requests and the page loads no remote assets; see
[Privacy and network use](../README.md#privacy-and-network-use) for what Streamlit and the operating
system do around it.

![ATLAS pipeline](figures/atlas_pipeline_architecture.png)

---

## 2. Installing and launching

* **macOS / Linux:** double-click `run.command`. **Windows:** double-click `run.bat`.
  The launcher needs Python 3.10+, builds `.venv`, installs `requirements.txt` when needed and opens
  the app at `http://localhost:8501`.
* **Check without launching:** `./run.command --check-only` or `run.bat --check-only` (or set
  `ATLAS_NO_LAUNCH=1`) provisions and verifies the environment, then exits.
* **Command line:** `.venv/bin/streamlit run app.py --server.address=localhost --browser.gatherUsageStats=false`.
* **Network exposure.** The launchers turn off Streamlit usage statistics but do not set
  `--server.address`, so Streamlit also listens on the computer's network interfaces. On a shared network,
  use the command-line form above so only this computer can open the page.

---

## 3. Preparing data

| Format | How it is read |
| :--- | :--- |
| `.txt`, `.md` | One turn per speaker label such as `Name [00:01:12]: text` or `Name: text`. |
| `.vtt`, `.srt` | Caption cues; `<v Speaker>` voice tags or `Speaker:` prefixes give the speaker. |
| `.docx` | Paragraphs or speaker/text tables, including Teams exports with multi-line turns. |
| `.csv`, `.xlsx` | One response per row; header row required; leading `#` comment lines in a CSV are skipped. |

For tables, choose the **text column** (auto-detected; columns named `id` or ending in `_id` are never
picked automatically), and optionally a **respondent ID column** and a **speaker / role column**.
Blank responses are skipped. Duplicate respondent ids stop the run with an error, because each row must
be a distinct unit.

**Data protection.** Remove names and identifiers that are not needed before analysis. Files stay on the
machine, but exports contain verbatim text.

---

## 4. The sidebar

![SOFTWARE_TEST workbench walkthrough](figures/atlas_dashboard_ui_walkthrough.png)

**Corpus Dataset**

| Option | Files loaded |
| :--- | :--- |
| Sample: Bilingual Interview Transcripts (SOFTWARE_TEST) | `software_test_bilingual_interview.txt` + `software_test_zoom_session.vtt` |
| Sample: Community Health Survey CSV (SOFTWARE_TEST) | `software_test_survey.csv` (text `response`, id `respondent_id`, speaker `role`) |
| Sample: Teams Multiline Transcript DOCX (SOFTWARE_TEST) | `software_test_teams_multiline.docx` |
| Upload Custom Files (.docx, .vtt, .srt, .txt, .md, .csv, .xlsx) | One or more uploaded files |

With **Upload Custom Files** selected, the sidebar also offers the table-column selectors, a
**facilitator names** box (comma-separated; those speakers' turns are excluded) and an **interviewer
prompt patterns** box (one regular expression per line; speakerless turns matching a pattern are
excluded). Without facilitator names, a named speaker who asked more than half of at least three
questions in a transcript is treated as the facilitator.

**Active YAML Codebook** lists every `.yaml` file in `config/`, any discovered codebook applied in this
session, and **Upload Custom Codebook (.yaml)**. Choosing a sample selects a suitable codebook; any
other can be chosen.

A blue `SOFTWARE_TEST FIXTURE ACTIVE` notice appears whenever a built-in sample is loaded.

---

## 5. Tab 1: thematic discovery and coding

### KPI cards

| Card | Meaning | SOFTWARE_TEST survey × `pfl_case_study_codebook.yaml` |
| :--- | :--- | ---: |
| Analytical Units (N) | Transcripts plus respondent rows | 6 |
| Participant Turns | Turns coded after facilitator turns are removed | 6 |
| Active Domains | Domains in the codebook | 5 |
| Matched Turn Mentions | Matching participant turns, summed over domains | 1 |

### Thematic Prevalence & Distribution
A bar chart of prevalence (% of units) with matching-turn labels, and a table with domain id and name,
units reporting, N, prevalence, matching turns and mentions.

### Verbatim Quote & Provenance Browser
Search the verbatim text, filter by domain or speaker, and read each matching turn with the matched
span highlighted, plus `source_id`, `unit_id`, line, `match_char_start`–`match_char_end` and
`source_sha256`. For the SOFTWARE_TEST survey sample the single quote is R001, line 2, span 7–28
(`se agotó el beneficio`), file SHA-256 beginning `02a7a3c8239a`.

![SOFTWARE_TEST context fence](figures/atlas_codebook_context_fence.png)

### Unsupervised Topic Discovery (Medoids)
Set **Number of topics (k)**. ATLAS fits LDA on the participant turns and shows, per topic, its top
terms (each term belongs to one topic only), its turn count and share, and its medoid: the real turn
closest to the topic's TF-IDF centroid, with its `unit_id` and speaker.

* **📥 Download Discovered Codebook (.yaml)** saves the topics as a draft `domains` codebook whose roots
  are the top terms.
* **⚡ Apply Discovered Codebook to Engine** adds that draft to the codebook list and re-codes the corpus
  with it.

Discovered codebooks have no fences and use raw top terms; rename, prune and fence them in a text editor
before reporting counts, then load the edited file with **Upload Custom Codebook (.yaml)**.

---

## 6. Tab 2: parameter matrix and exports

The matrix lists, per domain: units reporting, **N (analytical units)**, prevalence (%), p, the
binomial SE √(p(1 − p)/N), a 95% interval p ± 1.96·SE (clipped to 0–100%), and matching turns.

SOFTWARE_TEST survey × `pfl_case_study_codebook.yaml`:

| Domain ID | Units reporting | N | Prevalence (%) | Binomial SE | Matching turns |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `PFL_GAP` | 1 | 6 | 16.7 | 0.152 | 1 |
| `PFL_REPLACE` | 0 | 6 | 0.0 | 0.000 | 0 |
| `PFL_WAGE` | 0 | 6 | 0.0 | 0.000 | 0 |
| `PFL_PORTAL` | 0 | 6 | 0.0 | 0.000 | 0 |
| `PFL_STIGMA` | 0 | 6 | 0.0 | 0.000 | 0 |

**Downloads** (all produced by `AtlasEngine.export_results` for the current run):

| File | Contents |
| :--- | :--- |
| `actuarial_parameter_matrix.xlsx` | Frequency sheet whose prevalence cells carry `ATLAS VERIFICATION AUDIT STAMP` comments, and a quote sheet with full provenance |
| `provenance_manifest.json` | Run counts, per-domain values and digests, SHA-256 of every source file |
| `verbatim_quotes_inventory.csv` | One row per matching turn and domain |

A green banner confirms that `verify_workbook_integrity` found the workbook consistent with the manifest;
a red banner lists the mismatches. The **Source files and SHA-256 digests** expander lists every input
file's hash for comparison with the originals.

![SOFTWARE_TEST audit bridge](figures/atlas_audit_bridge.png)

---

## 7. Writing a codebook

```yaml
project: "Example SOFTWARE_TEST codebook"
domains:
  - id: TRANSIT
    name: Transit barriers
    roots_en: ["bus", "transit", "fare"]
    roots_es: ["autobús", "transporte"]
    context_fences: ["appointment", "clinic", "cita"]
    context_window: 8          # fence within 8 tokens of the root
  - id: CHILDCARE
    name: Childcare access
    roots_en: ["childcare"]
    exclude_fences: ["not a problem"]
    exclude_window: 3          # veto roots within 3 tokens of the exclusion
```

* Roots match case-insensitively at the start of a word and ignore accents (`autobus` = `autobús`).
* Fences without a window only need to appear somewhere in the same turn; a window without fences does
  nothing.
* An exclusion fence without a window vetoes the domain for the whole turn.
* The `topics` layout (`label`, `keywords`, `required_context`, `context_window`) is also accepted; see
  the shipped files in `config/`.

The [Methodology & Reference Manual](ATLAS_Methodology_and_Reference_Manual.md) gives the full rules.

---

## 8. Troubleshooting

| Message or symptom | Cause and fix |
| :--- | :--- |
| `The uploaded tables share no column names` | Several tables were uploaded with different headers; one text column must exist in all of them. |
| `Duplicate unit id` | Two rows share a respondent id; fix the ids or choose no id column. |
| `... must be a nonnegative whole token count` | A `context_window` or `exclude_window` is negative, fractional or text; use a whole number. |
| `Duplicate codebook rule id` | Two domains share an `id`; rename one. |
| All counts are 0 | The roots or fences do not occur in the turns; check spelling against the quote browser with a fence-free copy of the rule. |
| A speaker's turns are missing | The speaker was detected as a facilitator; enter the real facilitator names in the sidebar. |
| Integrity banner is red | The exported workbook and manifest disagree; regenerate both from the same run. |

---

## 9. Glossary

| Term | Meaning |
| :--- | :--- |
| Turn | One speaker's contiguous contribution, or one table response. |
| Analytical unit | A transcript, or a respondent row of a table; the prevalence denominator N. |
| `source_id` | A file's path relative to the corpus root. |
| `unit_id` | An analytical unit's id: `source_id` for transcripts, `source_id::id` for rows. |
| Root | A codebook term matched at word starts, ignoring case and accents. |
| Context fence | A term that must also occur (within `context_window` tokens, if set) for a root to count. |
| Exclusion fence | A term that vetoes a root (within `exclude_window` tokens, or the whole turn). |
| Medoid | The real turn closest to a discovered topic's TF-IDF centroid. |
| Audit stamp | The comment on each prevalence cell holding counts and a verification digest. |
| `SOFTWARE_TEST` | Label on built-in fixtures that demonstrate mechanics, not findings. |
