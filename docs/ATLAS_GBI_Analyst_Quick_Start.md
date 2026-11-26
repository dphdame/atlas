# ATLAS Quick-Start Guide for GBI Focus-Group Analysts

**ATLAS (`v1.2`) is a private, offline workbench that turns 3-column guaranteed basic income (GBI) focus-group notes and open-ended surveys into honest group counts, verified direct quotes, and audit-ready Word and Excel exports without uploading participant data to the cloud.** You can read this guide inside the **Reference Guides** tab or download any of the four guides as formatted Word (`.docx`) files from the sidebar.

---

## 1. Launch ATLAS Offline

ATLAS runs directly on your own computer so confidential participant records never leave your workstation.

- **Windows:** Double-click `run.bat` inside the `atlas` folder.
- **macOS:** Double-click `run.command` (or run `bash run.command` inside the folder in Terminal).

On the first run, the launcher builds an isolated local Python environment (`.venv`), installs the required libraries once, and opens the workbench in your browser at `http://localhost:8501`. Every run after that starts immediately and works with the network turned off.

---

## 2. Upload Your Focus-Group Notes (`.docx`) or Surveys (`.xlsx` / `.csv`)

Focus-group notes differ from ordinary transcripts because they mix direct participant quotes with note-taker summaries, consent boilerplate, and session headers inside a 3-column Word table (`Key Points | Notable Quotes | Observations`). If a tool reads that file as plain text, headers and summaries inflate counts and paraphrases get mistaken for direct quotes.

1. In the left sidebar, **Corpus Dataset** opens directly on **Upload Custom Files** (`Upload Files (.docx, .vtt, .srt, .txt, .md, .csv, .xlsx)`). Drag in one or more focus-group Word files (`.docx`), or an Excel/CSV survey table (1 row per person; any columns; pick the Excel tab and one open-ended question column at a time).
2. **Automatic Group Mode:** When ATLAS detects the 3-column notes layout, it automatically switches **Data Type** to **Group / summarized notes** (`1 file = 1 focus group`) and hides free-form transcript filters you do not need.
3. **Click `Run Analysis`** once you have picked your files and themes. Whenever you later change files, check extra themes, or toggle spelling tolerance in the sidebar, click **`Run Analysis`** again to refresh the results.
4. **What ATLAS separates automatically:**
   - Question prompts (`Question 1:`, `Q1:`, `Facilitator:`), session headers, consent boxes, and note-taker summary boxes are stripped before coding so question wording never inflates counts. You can verify every skipped line in the collapsed **Excluded Questions & Session Headers** drawer at the bottom of **Theme Summary**.
   - Note-taker **Themes / Topics / Patterns** rows move into a collapsed reference panel (**Note-Taker Themes Summary**) so you can compare your coding against the note-taker's impressions without counting those summaries as participant evidence.
   - Leave **Include Note-Taker Observations** unchecked unless you explicitly want note-taker observations coded alongside participant entries.

---

## 3. Where the Themes Come From — and How to Add or Change Them

ATLAS counts matches against transparent keyword rules, not AI-invented topics. The default **Core Evaluation Themes** drawer comes pre-checked with 10 standard social-policy and cash-assistance outcome domains (Housing & Rent Stability, Food Security & Basic Needs, Financial Stability/Bills & Debt, Employment, Education & Training, Transportation & Mobility, Childcare & Parenting, Healthcare, Mental Health & Stress Relief, and Legal & Justice). Each theme pairs everyday participant keywords with look-alike exclusions (for example, blocking `card` and `career` under Transportation, or `kidding` under Childcare).

1. **Pick Core or Optional Add-On Themes in the sidebar.** Open **Core Evaluation Themes** to check or uncheck any of the 10 core outcomes, or open **Optional Add-On Themes** to add up to 5 non-overlapping program delivery and policy friction themes (**Program Enrollment & Paperwork**, **Benefit Cliffs & Aid Loss**, **Utility Shutoffs & Energy Burden**, **Wait Times & Processing Backlogs**, and **Language & Translation Barriers**). You can also open **Upload Custom Themes (.yaml)** to replace or combine your own pilot theme file.
2. **Spot unlisted themes your checklist missed.** Open **Discover Unlisted Themes** (defaulting to deterministic **TF-IDF + NMF**, with **LDA** available inside collapsed **Method settings**). Each cluster shows its top keywords, its **Most representative example**, and a coverage badge showing how many entries matched none of your active themes (for example, **Mostly Uncoded by Active Themes**). Expand **View all N entries in Cluster K** to inspect every entry, or click **Add Theme to Active Themes** (using exact whole-word matching by default) to append a new pilot theme without editing YAML by hand.
3. **Run the 2-minute Spot-Check.** Open **Spot-Check Matches** to inspect any match flagged for human review:
   - **Check First (Partial-Word Match):** a keyword matched inside a longer word (such as `car` inside `card`).
   - **Check First (Spelling Match):** a 1-letter typo rescued when **Allow minor spelling typos (useful for open-ended surveys)** is checked in the sidebar.
   - **Check in Context (Negation or Short Word):** a nearby negation word (`not`, `never`, `didn't`) or short unfenced keyword.
   - Every flagged match stays counted in your charts and tables until you exclude it. Click **Exclude Selected Words from Theme** or **Switch Theme to Exact Whole-Word Matching** to tighten a rule immediately, or download `atlas_spot_check_report.csv` for team review.
4. **Save customized themes.** Whenever you add a theme, exclude words, or combine add-ons, click **Save active themes (.yaml)** in the sidebar (or **Download Active Theme Rules (.yaml)** in **Exports & Audit Files**) so your exact rules stay archived alongside your outputs.

For a full step-by-step guide to designing and testing new pilot themes, see the **Practitioner Field Guide** in **Reference Guides**.

---

## 4. Read the Group Mode Numbers Honestly

In a focus-group pilot, the number of groups is small and participants in the same room hear and influence one another. Because those observations are not independent survey draws, ATLAS hides survey error bars (`p ± 1.96·SE`) in Group Mode and organizes **Theme Summary** into three clear views whose numbers reconcile exactly:

- **Top KPI cards:** **Focus Groups** (`1 file = 1 group`), **Themes Found** (`X of Y` active themes), **Notes Entries Scanned** (`M matched · U none`), and **Theme Matches** (`1 entry can match 2+ themes`).
- **Which Focus Groups Mentioned Each Theme? (Group × Theme Grid):** Every focus group uses the same clean `✓` / `—` grid with a rightmost **Groups** summary column (`g/G`). Use the **Grid shows** toggle to switch between `Presence (✓ / —)` and `Notes entries per group`, or check **Hide 0-match themes** for compact tables.
- **How Often Each Theme Appeared in the Notes:** Horizontal bars show matched notes entries sorted highest to lowest. Remember that entry counts reflect **how much was written in the notes**, not how many individual people agreed.
- **Theme Summary Table:** Reconciles every count directly (`Verbatim Quotes + Paraphrased Key Points (+ Note-Taker Observations) = Theme Matches`).

---

## 5. Never Quote a Paraphrase by Mistake

In 3-column notes, summarized bullets (`Key Points`) sit right beside direct speech (`Notable Quotes`). Quoting a summary bullet inside quotation marks misattributes note-taker phrasing to a participant.

1. Open the **Coded Evidence** sub-tab inside **Themes & Quotes**.
2. Every entry carries an explicit badge distinguishing **Verbatim Quote** from **Paraphrase (Key Point)** and **Note-Taker Observation**. Use the **Filter by speaker**, **Filter by group**, or **Filter by question** controls to inspect specific rooms or tagged voices.
3. Before copying quotes into slides or a brief, check **`Quotable Verbatim Only`**. This hides all paraphrases and observations so only direct participant quotations remain visible.

---

## 6. Download Reports, Audited Tables, and Quotes

Right below **Theme Summary** (and inside **Exports & Audit Files**), download ready-to-share outputs matching your active run:

- **`Download Full Report (.docx)`** (`atlas_summary_report.docx`) — Printable Word report combining Run Overview, reconciled KPIs, Group × Theme Grid, Theme Summary Table, Coded Evidence separated by source type, Unlisted Clusters, Spot-Check Summary, and the Excluded Questions audit table.
- **`Download Theme Frequencies (.xlsx)`** (`actuarial_parameter_matrix.xlsx`) — Frequency sheet with an embedded `ATLAS VERIFICATION AUDIT STAMP` comment on every prevalence cell, plus the provenance sheet.
- **`Download Direct Quotes (.csv)`** (`verbatim_quotes_inventory.csv`) — Direct verbatim quotes only, safe for quotation selection.

Inside **Exports & Audit Files**, confirm the green **Workbook integrity check passed** banner and download optional **Audit & Reproducibility Files**: `coded_evidence_inventory.csv` (all coded entries labeled by source type when notes are present), `provenance_manifest.json` (SHA-256 digests of every source file), `atlas_active_codebook.yaml`, and `atlas_typo_matches_inventory.csv` (when spelling tolerance is enabled).
