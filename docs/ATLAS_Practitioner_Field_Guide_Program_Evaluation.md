# ATLAS Practitioner Field Guide
## Writing Clear Program Evaluations with Community Voices (`v1.2`)

**Victoria Cholette**  
*Open ATLAS Toolkit for Community Programs and Applied Evaluation*

**Strong program evaluations pair human stories with exact, verifiable scale—and ATLAS (`v1.2`) lets community evaluation teams produce both offline on their own workstation.** This guide explains where ATLAS's starter themes come from, how to develop and add new pilot themes without writing code, and how to turn transcripts, surveys, or 3-column focus-group notes into clear, audit-ready evaluation narratives without uploading confidential records to the cloud.

---

## 1. Communicating Program Value

Community programs connect families to healthcare, food, housing stability, cash assistance, and job training. When grants come up for renewal or boards review pilot outcomes, decision-makers ask one central question: **"Did the program achieve its intended impact, and what evidence supports that conclusion?"**

Direct participant quotes show what services feel like on the ground, while counts show how widespread each experience actually was. When an evaluation report relies only on general summaries, readers cannot tell whether a barrier affected 3 families out of 50 or 35 families out of 50. Pairing verified verbatim quotes with exact counts closes that gap so funders see both the human reality and the operational scale.

---

## 2. How Evaluators Report Findings (And Where Information Gaps Emerge)

Evaluation teams draw on intake logs, focus-group notes, interviews, and open-ended survey comments. Summarizing that feedback in broad prose often yields statements such as:

> *"Participants reported that clinic hours helped, while several families faced travel barriers and paperwork delays."*

That sentence reflects real observations, yet it leaves three gaps that review committees notice immediately:

* **Scope and prevalence:** Words like *"several"* hide whether an issue was isolated or systemic, which makes resource decisions difficult.
* **Mechanism:** General labels like *"travel barriers"* blur distinct operational causes—hourly bus schedules, transit fares, and car repairs require different fixes.
* **Accountability:** Reviewers need to know how themes were defined, whether look-alike words or negations were checked, and whether quoted remarks are authentic participant speech rather than staff paraphrases.

Pairing exact denominators, verified verbatim quotes, and a saved theme file resolves all three gaps at once.

---

## 3. Two Ways to Learn from Stories: Inductive and Deductive Evaluation

Reliable evaluations combine two complementary ways of working with text: **inductive discovery** (listening openly for surprises) and **deductive measurement** (counting defined program goals consistently across every record).

```
+--------------------------------------------------------+
|                   COMMUNITY DATA                       |
|   (Interviews, Survey Comments, Focus-Group Notes)     |
+---------------------------+----------------------------+
                            |
              +-------------+-------------+
              |                           |
              v                           v
    [INDUCTIVE DISCOVERY]       [DEDUCTIVE MEASUREMENT]
     "Listening to Learn"        "Measuring What Matters"
     * Uncovers surprise needs   * Checks defined goals
     * Catches blind spots       * Counts exact frequencies
              |                           |
              +-------------+-------------+
                            |
                            v
              [EVALUATION REPORT EVIDENCE]
              Human Context  +  Verified Scale
```

**Inductive evaluation ("Listening to Learn")** starts without a closed checklist so staff catch blind spots they did not anticipate. For example, a nutrition program may assume low workshop turnout reflects a lack of cooking tools, while open reading of participant comments reveals that families work evening shifts and cannot attend daytime sessions.

**Deductive evaluation ("Measuring What Matters")** starts from clear program outcomes and applies consistent rules across every document. For example, if a grant tracks benefit cliffs, the team defines the exact terms that signal losing public aid after a wage gain and counts how many participants or focus groups raised that barrier. Combining both approaches ensures the report answers funders' required questions without missing unexpected community needs.

---

## 4. The Practical ATLAS `v1.2` Evaluation Loop

Historically, combining discovery with measurement meant juggling separate tools or hand-editing codebooks in a text editor. ATLAS `v1.2` puts the full workflow inside one offline workbench:

```
+-------------------------------------------------------------------+
|                        YOUR RAW DATA                              |
|     (Interviews, surveys, or 3-column Word focus-group notes)     |
+--------------------------------+----------------------------------+
                                 |
                                 v
+-------------------------------------------------------------------+
|  STEP 1: PICK CORE & ADD-ON THEMES (Sidebar)                      |
|  * 10 Core Evaluation Themes pre-checked (expand to pick subset). |
|  * Add 5 Optional Add-On Themes or Upload Custom Themes (.yaml).  |
+--------------------------------+----------------------------------+
                                 |
                                 v
+-------------------------------------------------------------------+
|  STEP 2: SPOT UNLISTED THEMES & ADD THEM IN ONE CLICK             |
|  * Open Discover Unlisted Themes (TF-IDF + NMF, or LDA).          |
|  * Check Mostly Uncoded clusters; click Add Theme to Active.      |
+--------------------------------+----------------------------------+
                                 |
                                 v
+-------------------------------------------------------------------+
|  STEP 3: SPOT-CHECK MATCHES & DOWNLOAD REPORTS                    |
|  * Review partial-word, typo, and negation flags in 2 minutes.    |
|  * Filter Quotable Verbatim Only; download Word, Excel & CSVs.    |
+-------------------------------------------------------------------+
```

### Step A: Load Your Files and Confirm Data Type

In the sidebar, **Corpus Dataset** opens on **Upload Custom Files**. Drag in your transcripts, Excel/CSV survey tables (1 row per person; any columns; pick the worksheet tab and one open-ended question column at a time), or 3-column Word focus-group notes (`Key Points | Notable Quotes | Observations`). If ATLAS detects 3-column focus-group notes, it automatically switches **Data Type** to **Group / summarized notes** (**Group Mode**).

Why does **Group Mode** matter? In a focus-group pilot, each file represents one room of people who hear and react to one another, and total group counts are typically small. Reporting individual-level survey error bars on small, clustered focus groups overstates statistical precision. Group Mode therefore counts `1 file = 1 focus group`, leads with a uniform **Group × Theme Grid** (`✓` / `—` plus a `Groups` column `g/G`) and a clearly labeled **Notes Volume** bar chart, and hides invalid Binomial error bars.

For open-ended Excel or CSV surveys, you can also check **Allow minor spelling typos (useful for open-ended surveys)** so 1-letter misspellings on longer theme words (such as `gorceries` or `chldcare`) are caught without editing the participant's original text.

### Step B: Choose Core Themes, Optional Add-Ons, and Click `Run Analysis`

Under **2. Themes to Code**, ATLAS organizes themes into three collapsible drawers:

* **Core Evaluation Themes (10 of 10 checked by default, backed by `gbi_focus_group_starter.yaml`):** Covers ten foundational social-policy and cash-assistance household outcomes—Housing & Rent Stability, Food Security & Basic Needs, Financial Stability/Bills & Debt, Employment, Education & Training, Transportation & Mobility, Childcare & Parenting, Healthcare, Mental Health & Stress Relief, and Legal & Justice.
* **Optional Add-On Themes (0 of 5 checked by default, backed by `optional_delivery_addons.yaml`):** Adds non-overlapping program delivery and policy friction themes—Program Enrollment & Paperwork, Benefit Cliffs & Aid Loss, Utility Shutoffs & Energy Burden, Wait Times & Processing Backlogs, and Language & Translation Barriers.
* **Upload Custom Themes (.yaml):** Lets you replace checked themes with your own pilot file or combine them together.

Click **`Run Analysis`** once your files and themes are selected.

### Step C: Discover Unlisted Themes and Add Them in One Click

Open **Themes & Quotes → Discover Unlisted Themes**. ATLAS defaults to deterministic **TF-IDF + NMF** clustering (classic **LDA** remains available inside collapsed **Method settings**). Each cluster shows its exclusive top keywords, its **Most representative example**, and a coverage badge telling you how many entries in that cluster matched none of your active themes (for example, **Mostly Uncoded by Active Themes**). Expand **View all N entries in Cluster K** to read every entry in the cluster.

If discovery surfaces a pilot-specific topic (such as prepaid card fees or a local housing waitlist), pick that cluster under **Add a discovered cluster to your active themes**, type a clear program label, leave exact whole-word matching checked, and click **`Add Theme to Active Themes`**. ATLAS appends the new theme onto your active rules using `match_mode: exact` so short words like `car` or `fee` never spill into `career` or `feedback`.

### Step D: Run the 2-Minute Spot-Check

Before trusting counts, open **Themes & Quotes → Spot-Check Matches**. Remember that every flagged match remains counted in your charts and tables until you exclude it. ATLAS groups items into three clear priorities: **Check First (Partial-Word Match)**, **Check First (Spelling Match)** (when spelling tolerance is enabled), and **Check in Context (Negation or Short Word)**. Right inside that tab, click **`Exclude Selected Words from Theme`** or **`Switch Theme to Exact Whole-Word Matching`** to tighten a noisy rule immediately, or download `atlas_spot_check_report.csv` for team review.

### Step E: Separate Direct Quotes from Paraphrases and Download Reports

Before pulling direct quotations for slides or leadership briefs, open **Coded Evidence** and check **`Quotable Verbatim Only`**. In focus-group notes, that single checkbox hides paraphrased `Key Points` and staff `Observations` so you only quote participants' own words. Then download the printable Word report (**Download Full Report (.docx)**), audited Excel frequencies (**Download Theme Frequencies (.xlsx)**), and **Download Direct Quotes (.csv)** right from the bottom of **Theme Summary**, or open **Exports & Audit Files** for the provenance manifest and your saved **`atlas_active_codebook.yaml`**.

---

## 5. How to Develop, Test, and Add New Themes

Where do starter themes come from, and how should an evaluation team design new ones for a fresh pilot or cohort?

Starter themes in ATLAS are **transparent keyword checklists** built from standard program-evaluation outcome domains—not hidden AI categories. Every theme is a short list of everyday words participants actually use (for example, `rent`, `landlord`, `eviction`, `lease`), paired with **look-alike exclusions** (`parent`, `current`, `different`, `rental car`) so partial-word matching never miscounts unrelated words.

When a new pilot needs custom themes, follow a four-step workflow:

1. **Start from your evaluation plan, not a blank screen.** Keep the default **Core Evaluation Themes** that match your pilot's main outcome goals, and turn on any relevant **Optional Add-On Themes** for program administration or policy friction. Uncheck themes you do not intend to report if you want a cleaner summary table.
2. **Let participants' own words reveal what is missing.** Run **Discover Unlisted Themes** on your first batch of notes or survey answers. Look first at clusters tagged **Mostly Uncoded by Active Themes**—those are real topics people talked about that your starting checklist did not measure.
3. **Add and name the theme in-app—or author a clean `.yaml` file.**
   * *Fastest path (no file editing):* Click **Add Theme to Active Themes** inside **Discover Unlisted Themes** with exact whole-word matching checked, then click **Save active themes (.yaml)** in the sidebar to save that rule set for the rest of the study.
   * *Team-wide codebook path:* Open the saved `.yaml` file in any plain-text editor, add everyday synonyms (including Spanish phrasing when applicable), set `match_mode: exact` for short 3-to-4-letter words (`car`, `bus`, `pay`, `fee`), and add `exclude_fences` with `exclude_window: 0` for any look-alike words. Upload it under **Upload Custom Themes (.yaml)** and choose **Combine with checked themes above** or **Use uploaded themes only**.
4. **Pilot-test with Spot-Check before locking the rules.** Run your new theme on one or two real files, open **Spot-Check Matches**, and check every flagged partial-word, typo, or negation hit. Once counts are clean, freeze the `.yaml` file and archive it alongside your exported reports so every later quarterly wave uses the exact same definition.

---

## 6. How ATLAS Protects Confidentiality and Auditability

Many commercial qualitative tools upload transcripts to external cloud servers, which can conflict with participant consent agreements or agency data policies. **ATLAS executes locally on your workstation.** Input files remain on your disk during parsing, discovery, coding, and export without being transmitted to external APIs (subject to your local computer's security). Both desktop launchers (`run.bat` and `run.command`) pass `--server.address=localhost` by default so other devices on a shared network cannot view the local web page (see [Privacy and network use](../README.md#privacy-and-network-use)).

Keeping core measurement deterministic rather than relying on a generative language model provides three practical advantages for program evaluation:

1. **No paraphrasing drift:** Instead of summarizing remarks in an AI voice, ATLAS extracts exact verbatim text paired with source file, speaker, line number, character offsets, source type, and source file SHA-256 hash.
2. **Exact repeatability:** Running the same theme file on the same documents yields identical counts every time—eliminating run-to-run randomness during board or funder audits.
3. **Clear role for upstream brainstorming:** If your team uses a separate general-purpose AI tool to brainstorm candidate synonyms during early design, keep it strictly abstract (never upload raw participant transcripts or identifiable notes). Once you vet candidate words and place them in a local YAML file, ATLAS performs every search, fence check, and count offline.

**Choosing the right unit of measurement.** Always state your denominator explicitly in reports:

* **Individual transcripts or survey tables:** Report analytical units (one per transcript or survey respondent unit) alongside written answers scanned (`X written answers scanned, Y rows left this question blank`—never calling optional text-box completion the study's "response rate").
* **Focus-group notes (Group Mode):** Report focus groups (`g of G` groups) alongside clearly labeled notes volume (`Theme Matches` in notes entries), and never present notes volume as participant headcount or report survey error bars on small focus-group pilots.

---

## 7. Writing the Evaluation Section: 4 Core Elements

Evaluation narratives read most clearly when each finding moves through four connected steps:

1. **The Context:** State the specific community condition or service hurdle being examined.
2. **The Program Activity:** Explain what the program delivered to address that condition.
3. **The Evidence (Verified Scale Paired with Direct Quotes):** State the exact count and denominator (`29 of 45 individual transcripts` or `3 of 4 focus groups`), followed immediately by a verbatim quote (never a paraphrase presented as direct speech) that illustrates the mechanism.
4. **The Action Plan:** State the concrete operational adjustment the team made—or recommends—in response to that evidence.

---

## 8. Writing Models: From General Descriptions to Verifiable Findings

The models below show how moving from vague prose to denominator-clear counts and traceable quotes makes an evaluation immediately actionable.

> **Hypothetical writing models.** The counts, quotes and line numbers in Models 1 and 2 are invented to
> show sentence structure. They are not ATLAS output and not findings. For real ATLAS output on the
> built-in `SOFTWARE_TEST` fixtures see the [Methodology & Reference Manual](ATLAS_Methodology_and_Reference_Manual.md#5-software_test-walkthrough).

### Model 1: Transportation Barriers

* **General Description:**
  > *"Transportation continues to be a major obstacle for our community members. Many participants reported that buses were unreliable, which led to missed clinic visits."*

* **Verifiable Evaluation Narrative:**
  > *"Transportation barriers directly affected clinic attendance across the cohort. Out of 45 individual interview transcripts (one per participant), 29 transcripts (64.4%) reported that transit delays caused late arrivals or missed medical appointments across 38 matching dialogue turns. As one participant explained: 'The cross-town bus only runs once an hour. If an appointment is at 9:00 AM, my family has to leave home before 7:00 AM, and any transfer delay causes a missed visit' (Intake Log, Line 114). In response to this measured prevalence, the program shifted funds to provide guaranteed ride-share vouchers for morning specialty visits."*

### Model 2: Enrollment Administrative Friction

* **General Description:**
  > *"Participants expressed appreciation for navigator staff, although paperwork requirements created frustration during the initial enrollment period."*

* **Verifiable Evaluation Narrative:**
  > *"Participant feedback reflected strong satisfaction with staff navigation alongside measurable paperwork delays during onboarding. Across 45 individual interview transcripts (one per participant), 41 transcripts (91.1%) recorded positive, respectful interactions with community navigators, while 16 transcripts (35.6%) noted that assembling three consecutive months of pay stubs delayed enrollment by more than two weeks. One participant noted: 'Finding old pay stubs from two past jobs took three weeks, during which my application sat waiting' (Interview 08, Line 62). Based on these findings, the team updated the intake protocol to permit self-attestation for seasonal income, cutting onboarding time from 18 days to 4 days."*

---

## 9. Verifying Evaluation Findings: The Audit Receipt

Funders and evaluation monitors want assurance that reported numbers and quotes match the underlying files. ATLAS builds an automated verification trail for every run:

1. **Cryptographic File Fingerprints (SHA-256):** `provenance_manifest.json` records the SHA-256 digest of every uploaded source file so reviewers can confirm whether local originals match the files analyzed.
2. **Line, Character-Span, and Source-Type Receipts:** Every exported quote lists its source file, line number, character offsets, and source type (`Verbatim Quote` vs. `Paraphrase`), making every citation verifiable in seconds.
3. **Deterministic Reproducibility:** Archiving your final `.yaml` theme file alongside `provenance_manifest.json` allows any reviewer to re-run ATLAS on the same files and obtain identical counts.
4. **Tamper-Evident Excel Audit Stamps:** Each prevalence cell in `actuarial_parameter_matrix.xlsx` carries an `ATLAS VERIFICATION AUDIT STAMP` comment, and **Exports & Audit Files** verifies that the workbook still agrees with the manifest before download.

![Four-step SOFTWARE_TEST audit bridge diagram tracing a highlighted verbatim survey quote with file SHA-256 to its coded frequency row, Excel cell audit-stamp comment, and verify_workbook_integrity PASS check](figures/atlas_audit_bridge.png)
*SOFTWARE_TEST illustration of the audit trail on a built-in sample; mechanics only.*

---

## 10. Evaluation Report Pre-Flight Checklist

Before submitting an evaluation report, grant renewal, or board brief, confirm each item:

- [ ] **Dual Grounding:** Does every major qualitative claim pair an exact count and denominator with a verified verbatim quote?
- [ ] **Denominator Honesty:** Are individual counts (`N` transcripts/survey units) kept strictly separate from focus-group counts (`g of G` groups), with survey error bars omitted on small focus-group pilots and optional open-ended skip counts never mislabeled as study "response rates"?
- [ ] **Verbatim Integrity:** Did you filter by `Quotable Verbatim Only` (or export `verbatim_quotes_inventory.csv`) so no note-taker paraphrase is presented inside quotation marks?
- [ ] **Spot-Check Review:** Did you review **Spot-Check Matches** and exclude any partial-word collisions, spelling-tolerance misfires, or negated hits?
- [ ] **Inductive & Deductive Balance:** Did you inspect **Discover Unlisted Themes** (TF-IDF + NMF) to check for unexpected community themes missing from your initial checklist?
- [ ] **Confidentiality & Archiving:** Are personal identifiers removed from public deliverables, and are your final `.yaml` theme file and `provenance_manifest.json` archived together?

---

## Appendix: Example Custom YAML Theme File & Public Topic Libraries

Below is a clean, ready-to-adapt YAML theme file showing exact matching (`match_mode: exact`), context windows, and `exclude_window: 0` look-alike fences:

```yaml
# Family Support Program Evaluation Theme File (Practitioner Layout)
program_name: "Community Health and Navigation"
version: "1.2"

topics:
  transit_access:
    label: "Transportation Barriers"
    description: "Difficulties traveling to appointments or work"
    match_mode: exact
    keywords:
      - "bus"
      - "transit"
      - "route"
      - "no ride"
      - "car trouble"
      - "fare"
    context_window: 10
    required_context:
      - "clinic"
      - "doctor"
      - "visit"
      - "job"
      - "appointment"

  staff_advocacy:
    label: "Staff Navigation & Support"
    description: "Positive support and navigation provided by staff"
    keywords:
      - "navigator"
      - "advocate"
      - "patient"
      - "listened"
      - "helped me"
      - "clear answers"
    exclude_fences:
      - "patients"
      - "patient portal"
    exclude_window: 0
    context_window: 6
    required_context:
      - "clinic"
      - "staff"
      - "caseworker"
      - "office"
      - "appointment"
```

### Public Topic Libraries and Shipped Theme Packs

You rarely need to write theme definitions from scratch. Public standards provide vetted definitions you can pair with everyday participant phrasing:

1. **The 2-1-1 Community Needs Directory ([211taxonomy.org](https://211taxonomy.org)):** Standardized definitions for over 10,000 community needs (rent assistance, food pantries, bus passes, utility relief).
2. **The PRAPARE® Community Clinic Tool ([prapare.org](https://prapare.org)):** Vetted social-determinants categories for housing stress, food security, transit barriers, and clinic access.
3. **The IRIS+ Impact Catalog ([iris.thegiin.org](https://iris.thegiin.org)):** Structured social-outcome definitions covering youth programs, schooling, health access, and family nutrition.
4. **The O*NET Job Skills System ([onetonline.org](https://www.onetonline.org)):** U.S. Department of Labor vocabulary for job training, workplace tasks, and career mobility barriers.
5. **ATLAS Built-In Theme Drawers (shipped inside `config/`):**
   * `gbi_focus_group_starter.yaml` (**Core Evaluation Themes**, 10 themes): Housing & Rent Stability, Food Security & Basic Needs, Financial Stability/Bills & Debt, Employment, Education & Training, Transportation & Mobility, Childcare & Parenting, Healthcare, Mental Health & Stress Relief, and Legal & Justice.
   * `optional_delivery_addons.yaml` (**Optional Add-On Themes**, 5 non-overlapping themes): Program Enrollment & Paperwork, Benefit Cliffs & Aid Loss, Utility Shutoffs & Energy Burden, Wait Times & Processing Backlogs, and Language & Translation Barriers.
   * Additional specialized YAML templates inside `config/` (`sdoh_basic_needs.yaml`, `intake_and_enrollment.yaml`, `workforce_and_mobility.yaml`, `youth_and_family.yaml`) can also be uploaded anytime via **Upload Custom Themes (.yaml)**.

*(Read any ATLAS guide formatted right inside **Reference Guides**, or download formatted Word `.docx` copies from the sidebar.)*

---

*ATLAS is open-source software distributed under the MIT License. Documentation, sample theme files, and implementation guides are available at [github.com/dphdame/atlas](https://github.com/dphdame/atlas).*
