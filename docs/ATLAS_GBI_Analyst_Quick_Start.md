# ATLAS Quick-Start Guide for GBI Focus-Group Analysts

**What ATLAS is:** A private, 100% offline workbench for coding guaranteed basic income (GBI) and cash-assistance focus-group notes, discovering unexpected themes, and exporting audit-ready tables and quotes. Nothing is uploaded to the cloud.

---

## 1. Launch ATLAS Offline

- **Windows:** Double-click `run.bat` inside the `atlas` folder.
- **macOS:** Double-click `run.command` (or run `bash run.command` in Terminal).
- On first launch, ATLAS creates a local `.venv` folder and opens in your browser at `http://localhost:8501`. After setup, it runs completely offline.

---

## 2. Upload Your Focus-Group Notes (`.docx`)

1. In the left sidebar, set **Corpus Dataset** to **Upload Custom Files**.
2. Drag in one or more focus-group Word files (`.docx`), such as your treatment and control session notes.
3. **Automatic Group Mode:** When ATLAS detects the standard 3-column notes layout (`Key Points | Notable Quotes | Observations`), it automatically switches **Data Type** to **Group / summarized notes** (`1 file = 1 focus group`).
   - Session headers, consent boxes, question prompts, and note-taker summary boxes are kept out of participant counts.
   - Participant labels (`P1`, `P2`, ...) are scoped to each file, so `P1` in Group 1 and `P1` in Group 2 are counted as two distinct voices.
   - Leave **Include Note-Taker Observations** unchecked unless you explicitly want facilitator/note-taker observations coded alongside participant entries.
   - Note-taker **Themes / Topics / Patterns** rows stay in a collapsed reference expander and are never mixed into participant counts.

---

## 3. Pick a Codebook and Spot Missed Themes (10-Minute Workflow)

1. Select **`gbi_focus_group_starter.yaml`** in **Active YAML Codebook** to start with 8 pre-fenced GBI domains (Housing, Food/Groceries, Debt/Bills, Employment/Education, Transportation, Family/Caregiving, Stress/Autonomy, and Program Enrollment/Paperwork).
2. Open **Unsupervised Topic Discovery (Medoids)** and leave **Discovery method** on **`TF-IDF + NMF`** (faster, deterministic, and sharper non-overlapping keywords; classic **LDA** is also available).
   - Scan the top terms and example medoid entries to spot any local themes your starter codebook does not yet cover (for example, program-specific debit cards, childcare vouchers, or local licensing rules).
   - Download the discovered `.yaml` draft or add those terms to a copy of the starter `.yaml` stored in your private study folder.
3. **Keep false alarms low:** When editing your custom `.yaml`, add `exclude_fences` (with `exclude_window: 0`) for any short prefix word (such as `car` excluding `card`, `career`, `care`, `cargo`), or set `match_mode: exact` on a domain or codebook for strict whole-word matching.

---

## 4. Read the Group Mode Charts Honestly

- **Groups Reporting (`g of G`):** Shows the exact integer count of focus-group files that mentioned each domain, alongside the number of distinct tagged participant voices within those groups.
- **Group × Theme Matrix:** Shows which themes surfaced in each focus group side by side so you can compare cohorts at a glance.
- **Why no Binomial error bars in Group mode?** Focus groups have small group counts (`G`) and clustered participants within each room, which violate independent-sample Binomial confidence interval assumptions. ATLAS intentionally hides normal-approximation `p ± 1.96·SE` whiskers in Group mode.

---

## 5. Never Quote a Paraphrase by Mistake

1. Open the **Coded Evidence & Provenance Browser** tab.
2. Every row carries an explicit badge: **Verbatim Quote** (`Notable Quotes` column) vs. **Paraphrase (Key Point)** (`Key Points` column).
3. Before pulling direct quotations for a slide deck or leadership brief, check **`Quotable Verbatim Only`**. This hides all paraphrases and observations so only direct participant quotes remain on screen.

---

## 6. Export Audited Tables and Quotes

Open **Tab 2: Econometric & Actuarial Ledger Export**, confirm **Workbook integrity check passed**, and download:

- **`actuarial_parameter_matrix.xlsx`** — Domain prevalence sheet with embedded `ATLAS VERIFICATION AUDIT STAMP` comments on every prevalence cell plus full provenance.
- **`verbatim_quotes_inventory.csv`** — Direct verbatim quotes only (safe for quotation review).
- **`coded_evidence_inventory.csv`** — All coded entries (quotes + paraphrases/observations) with explicit `Evidence Type` and `Question` columns.
- **`provenance_manifest.json`** — Cryptographic SHA-256 hashes of every uploaded source file so input files can be independently verified later. Save a copy of the exact `.yaml` codebook you used alongside the export folder so your coding rules stay archived with the results.
