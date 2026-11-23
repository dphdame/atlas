# ATLAS Quick-Start Guide for GBI Focus-Group Analysts

**ATLAS (`v1.2`) is a private, 100% offline workbench that turns 3-column guaranteed basic income (GBI) focus-group notes into honest group counts, verified verbatim quotes, and audit-ready exports—without uploading participant data to the cloud.** You can read this guide right inside **Tab 3: Reference Guides** or download any of the four guides as formatted Word (`.docx`) files from the sidebar.

---

## 1. Launch ATLAS Offline

ATLAS runs directly on your own computer so confidential participant records never leave your workstation.

- **Windows:** Double-click `run.bat` inside the `atlas` folder.
- **macOS:** Double-click `run.command` (or run `bash run.command` inside the folder in Terminal).

On the first run, the launcher builds an isolated local Python environment (`.venv`), installs the required libraries once, and opens the workbench in your browser at `http://localhost:8501`. Every run after that starts immediately and works with the network turned off.

---

## 2. Upload Your Focus-Group Notes (`.docx`)

Focus-group notes differ from ordinary transcripts because they mix direct participant quotes with note-taker summaries, consent boilerplate, and session headers inside a 3-column Word table (`Key Points | Notable Quotes | Observations`). If a tool reads that file as plain text, headers and summaries inflate participant counts and paraphrases get mistaken for direct quotes.

1. In the left sidebar, **Corpus Dataset** opens directly on **Upload Custom Files** with **`gbi_focus_group_starter.yaml`** already selected. Drag in one or more focus-group Word files (`.docx`), such as your treatment and control session notes.
2. **Automatic Group Mode:** As soon as ATLAS detects the 3-column notes layout, it switches **Data Type** to **Group / summarized notes**, treating each file as one focus group (`1 file = 1 focus group`), and hides free-form transcript filters you do not need.
3. **Click `▶ Run Analysis`** once you have picked your files and codebook(s). Whenever you later change files or stack extra codebooks in the sidebar, click **`▶ Run Analysis`** again to refresh the results.
4. **What the parser separates automatically:**
   - Session headers, consent boxes, question prompts, and note-taker summary boxes are excluded so they never inflate counts.
   - Participant IDs (`P1`, `P2`, ...) are scoped to their own file, which ensures that `P1` in Group 1 and `P1` in Group 2 count as two distinct participant voices rather than one person.
   - Note-taker **Themes / Topics / Patterns** rows move into a collapsed reference panel below the prevalence table so you can compare your coding against the note-taker's impressions without counting those summaries as participant evidence.
   - Leave **Include Note-Taker Observations** unchecked unless you explicitly want facilitator or note-taker observations coded alongside participant entries.

---

## 3. Pick a Codebook, Add Local Themes, and Spot-Check False Alarms (10-Minute Workflow)

Coding accuracy depends more on how cleanly your codebook matches local language—and blocks word collisions—than on adding complex software. ATLAS gives you a three-step loop inside the interface so you can tailor a codebook without editing YAML files by hand:

1. **Start from the fenced GBI starter pack (and stack extras if needed).** Select **`gbi_focus_group_starter.yaml`** in **Active YAML Codebook**. It ships with 8 pre-fenced GBI domains (Housing, Food/Groceries, Debt/Bills, Employment/Education, Transportation, Family/Caregiving, Stress/Autonomy, and Program Enrollment/Paperwork) whose exclusion rules already block common short-word collisions.
   - If your pilot also tracks broader topics (such as clinic access or wage progression), select extra codebooks under **Stack Additional Starter Codebooks (optional)** in the sidebar (for example, stack `sdoh_basic_needs.yaml` or `workforce_and_mobility.yaml`). ATLAS combines their domains automatically, keeps each domain's matching mode and fences intact, and disambiguates any overlapping domain IDs or names.
2. **Spot local themes missing from the starter pack.** Open **💡 Unsupervised Topic Discovery (Medoids)** and leave **Discovery method** on **`TF-IDF + NMF`** (faster, repeatable across runs, and sharper non-overlapping keywords than classic **LDA**, which remains available if you want to compare).
   - Scan each topic's top terms and example medoid entry to catch pilot-specific issues the starter pack does not cover (such as prepaid debit card fees, childcare waitlists, or local licensing rules).
   - Under **Add a discovered theme to your active codebook**, pick that topic, type a plain-English domain name, leave **Use exact whole-word matching** checked, and click **`➕ Add Theme to Active Codebook`**. ATLAS appends the theme on top of your active codebook (keeping any stacked domains) and immediately re-codes the corpus. Defaulting added themes to exact whole-word matching (`match_mode: exact`) stops short discovered words like `car` or `fee` from misfiring on `career` or `feedback`.
3. **Run the 2-minute False-Alarm Spot-Check.** Open **`🔎 False-Alarm Spot-Check`** to review matches most likely to be false positives: short or non-inflectional prefix extensions (such as `car` matching inside `card` or `career`), nearby negation cues (`not`, `never`, `didn't`, including curly Word apostrophes), and short unfenced stems.
   - Right inside that tab, you can click **`🛡️ Exclude Selected Words from Domain`** to block specific false-alarm words or **`🎯 Switch Domain to Exact Whole-Word Matching`** to restrict a noisy domain to exact whole words. If a domain already carries a wider exclusion window, ATLAS labels that preserved window explicitly so you know whether excluding a word affects nearby matches. You can also download `atlas_false_alarm_spot_check.csv` for team review.
4. **Archive your finished codebook.** Whenever you stack codebooks, add a discovered theme, or tighten a rule, click **`📥 Download Active Codebook (.yaml)`** (available in the sidebar and in Tab 2) and store that file beside your exports so your exact coding rules stay reproducible.

---

## 4. Read the Group Mode Charts Honestly

In a focus-group pilot, the number of groups (`G`) is small and participants inside the same room hear and influence one another. Because those observations are neither independent nor large-sample Binomial draws, normal-approximation survey error bars (`p ± 1.96·SE`) would overstate precision. ATLAS therefore hides Binomial error bars in Group Mode and replaces them with two honest views:

- **Groups Reporting (`g of G`):** Shows the exact integer number of focus-group files that mentioned each domain, alongside the count of distinct tagged participant voices within those groups.
- **Group × Theme Matrix:** Displays every focus group side by side against every domain so you can compare cohorts (such as treatment vs. control rooms) at a glance.

---

## 5. Never Quote a Paraphrase by Mistake

In 3-column notes, summarized bullets (`Key Points`) sit right beside direct speech (`Notable Quotes`). Quoting a summary bullet in a leadership brief as though a participant spoke those exact words creates a misquotation.

1. Open the **💬 Coded Evidence & Provenance Browser** tab.
2. Every row carries an explicit badge distinguishing **Verbatim Quote** (`Notable Quotes`) from **Paraphrase (Key Point)** (`Key Points`) and **Note-Taker Observation** (`Observations`).
3. Before copying quotes into slides or a report, check **`Quotable Verbatim Only`**. This hides all paraphrases and observations so only direct participant quotations remain visible.

---

## 6. Export Audited Tables and Quotes

Open **📊 Tab 2: Econometric & Actuarial Ledger Export**, confirm the green **Workbook integrity check passed** banner, and download:

- **`actuarial_parameter_matrix.xlsx`** — Domain prevalence sheet with an embedded `ATLAS VERIFICATION AUDIT STAMP` comment on every prevalence cell, plus the provenance sheet.
- **`verbatim_quotes_inventory.csv`** — Direct verbatim quotes only, safe for quotation selection and review.
- **`coded_evidence_inventory.csv`** — Every coded entry (quotes, paraphrases, and observations when included) with explicit `Evidence Type` and `Question` columns so reviewers can trace every group count.
- **`provenance_manifest.json`** — Cryptographic SHA-256 hashes of every uploaded source file so input files can be independently verified later. Save a copy of the exact `.yaml` codebook you used alongside the export folder so your coding rules stay archived with the results.
- **`atlas_active_codebook.yaml`** (shown whenever you stacked or customized rules) — Your exact final codebook ready to archive beside the manifest.
