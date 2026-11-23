# ATLAS Practitioner Field Guide
## Writing Clear Program Evaluations with Community Voices (`v1.2`)

**Victoria Cholette**  
*Open ATLAS Toolkit for Community Programs and Applied Evaluation*

**Strong program evaluations pair human stories with exact, verifiable scale—and ATLAS (`v1.2`) lets community evaluation teams produce both offline on their own workstation.** This guide shows how to move from raw interviews, surveys, or 3-column focus-group notes to clear, audit-ready evaluation narratives without uploading confidential community records to the cloud.

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
* **Accountability:** Reviewers need to know how themes were defined, whether negative or counter-examples were checked, and whether quoted remarks are authentic participant speech rather than staff paraphrases.

Pairing exact denominators, verified verbatim quotes, and a saved codebook resolves all three gaps at once.

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
|  STEP 1: PICK OR STACK STARTER CODEBOOKS (Sidebar)                |
|  * Start with gbi_focus_group_starter.yaml or another starter.    |
|  * Stack extra packs via Stack Additional Starter Codebooks.      |
+--------------------------------+----------------------------------+
                                 |
                                 v
+-------------------------------------------------------------------+
|  STEP 2: SPOT MISSED THEMES & ADD THEM IN ONE CLICK (Tab 1)       |
|  * Run TF-IDF + NMF discovery (or classic LDA) and read medoids.  |
|  * Click Add Theme to Active Codebook (exact whole-word default). |
+--------------------------------+----------------------------------+
                                 |
                                 v
+-------------------------------------------------------------------+
|  STEP 3: RUN FALSE-ALARM SPOT-CHECK & EXPORT (Tab 1 -> Tab 2)     |
|  * Review prefix extensions and nearby negations in 2 minutes.    |
|  * Filter Quotable Verbatim Only, then export audited files.      |
+-------------------------------------------------------------------+
```

### Step A: Load Your Files and Check Individual vs. Group Mode

In the sidebar, choose **Corpus Dataset → Upload Custom Files** and drag in your transcripts, survey tables, or 3-column Word focus-group notes (`Key Points | Notable Quotes | Observations`). If ATLAS detects 3-column focus-group notes, it automatically switches **Data Type** to **Group / summarized notes** (**Group Mode**).

Why does **Group Mode** matter? In a focus-group pilot, each file represents one room of people who hear and react to one another, and total group counts (`G`) are typically small. Reporting individual-level survey error bars on small, clustered focus groups overstates statistical precision. Group Mode therefore counts `1 file = 1 focus group`, reports exact integer **Groups Reporting (`g of G`)** counts alongside a **Group × Theme Matrix**, keeps `P1` in separate rooms counted as distinct voices, and hides invalid Binomial error bars.

### Step B: Start from a Starter Pack, Stack Extras, and Click `▶ Run Analysis`

**Active YAML Codebook** starts on **`gbi_focus_group_starter.yaml`** (for guaranteed basic income or cash-assistance pilots). If your evaluation spans two areas—such as cash-assistance stability and clinic access—select a second pack under **Stack Additional Starter Codebooks (optional)** (for example, stack `sdoh_basic_needs.yaml` or `workforce_and_mobility.yaml`). ATLAS combines their rules automatically without duplicating domain IDs or losing existing fences. Once your files and codebooks are selected, click **`▶ Run Analysis`** in the sidebar to run the coding pass.

### Step C: Discover Local Themes and Add Them in One Click

Open **Tab 1 → 💡 Unsupervised Topic Discovery (Medoids)** and leave **Discovery method** on **`TF-IDF + NMF`** (faster, repeatable across runs, and sharper non-overlapping keywords; classic **LDA** remains available for comparison). Choose **Number of topics (k)** between `1` and `10` and read each topic's top terms alongside its **medoid**—the real participant turn or coded notes entry closest to that topic's center.

If discovery surfaces an unexpected local issue (such as prepaid card fees or a local housing waitlist), you do not have to edit YAML by hand: pick that topic under **Add a discovered theme to your active codebook**, type a clear program label, leave exact whole-word matching checked, and click **`➕ Add Theme to Active Codebook`**. ATLAS appends the new theme onto your active codebook using `match_mode: exact` so short words like `car` or `fee` never spill into `career` or `feedback`. *(You can still click **`📥 Download Discovered Codebook (.yaml)`** or **`⚡ Apply Discovered Codebook to Engine`** if you prefer to explore a full draft codebook from scratch.)*

### Step D: Run the 2-Minute False-Alarm Spot-Check

Before trusting counts, open **Tab 1 → 🔎 False-Alarm Spot-Check**. ATLAS automatically flags matches most likely to be false alarms: short or non-inflectional prefix extensions (such as `car` firing inside `card` or `career`), nearby negation words (`not`, `never`, `didn't`), and short unfenced stems. Right inside that tab, you can click **`🛡️ Exclude Selected Words from Domain`** or **`🎯 Switch Domain to Exact Whole-Word Matching`** to tighten a noisy rule immediately and watch the false alarms drop away, or download `atlas_false_alarm_spot_check.csv` for team review.

### Step E: Separate Direct Quotes from Paraphrases and Export

Before pulling direct quotations for slides or leadership briefs, open the Evidence Browser and check **`Quotable Verbatim Only`**. In focus-group notes, that single checkbox hides paraphrased `Key Points` and staff `Observations` so you only quote participants' own words. Then move to **Tab 2** to confirm the green integrity banner and download your Excel workbook, JSON provenance manifest, quote CSVs (`verbatim_quotes_inventory.csv` and, when mixed evidence is present, `coded_evidence_inventory.csv`), and your final customized **`atlas_active_codebook.yaml`**.

---

## 5. How ATLAS Protects Confidentiality and Auditability

Many commercial qualitative tools upload transcripts to external cloud servers, which can conflict with participant consent agreements or agency data policies. **ATLAS executes locally on your workstation.** Input files remain on your disk during parsing, discovery, coding, and export without being transmitted to external APIs (subject to your local computer's security). Both desktop launchers (`run.bat` and `run.command`) pass `--server.address=localhost` by default so other devices on a shared network cannot view the local web page (see [Privacy and network use](../README.md#privacy-and-network-use)).

Keeping core measurement deterministic rather than relying on a generative language model provides three practical advantages for program evaluation:

1. **No paraphrasing drift:** Instead of summarizing remarks in an AI voice, ATLAS extracts exact verbatim text paired with source file, speaker, line number, character offsets, evidence type, and source file SHA-256 hash.
2. **Exact repeatability:** Running the same codebook on the same files yields identical counts and percentages every time—eliminating run-to-run randomness during board or funder audits.
3. **Clear role for upstream brainstorming:** If your team uses a separate general-purpose AI tool to brainstorm candidate synonyms during early design, keep it strictly abstract (never upload raw participant transcripts or identifiable notes). Once you vet candidate words and place them in a local YAML codebook, ATLAS performs every search, fence check, and count offline.

**Choosing the right unit of measurement.** Always state your denominator explicitly in reports:

* **Individual transcripts or survey tables:** Report analytical units (one per transcript or survey respondent row) alongside matching turns.
* **Focus-group notes (Group Mode):** Report focus groups (`g of G` groups) alongside distinct participant voices and coded entries, and do not report individual-sample survey error bars.

---

## 6. Setting Up an Evaluation Checklist (The Codebook)

When building a checklist from scratch, organize your core evaluation questions into a focused set of domains (typically 4 to 8 clear categories). Below is an example checklist for a community health navigation initiative:

| Domain | Evaluation Target | Words and Context Rules |
| :--- | :--- | :--- |
| **Transit Access** | Travel barriers causing missed clinic visits | `bus`, `transit`, `route`, `ride`, `car trouble`, `fare` (with clinic/appointment context or `match_mode: exact` on short stems) |
| **Intake Burden** | Paperwork delays during program signup | `forms`, `documentation`, `pay stub`, `verification`, `delay` |
| **Benefit Cliffs** | Loss of public aid after modest wage gains | `cliff`, `threshold`, `medi-cal`, `calfresh`, `lost coverage` |
| **Staff Support** | Positive rapport and care from navigators | `navigator`, `listened`, `advocate`, `patient` (excluding `patients` / `patient portal`), `answered` |

Notice the exclusion note on `patient`: because *"patient"* can mean either a respectful staff member or a medical clinic patient, fencing out `patients` and `patient portal` (or adding a staff context fence) prevents false matches before they ever enter your tables.

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
2. **Line, Character-Span, and Evidence-Type Receipts:** Every exported quote lists its source file, line number, character offsets, and evidence type (`verbatim` vs. `paraphrase`), making every citation verifiable in seconds.
3. **Deterministic Reproducibility:** Archiving your final `.yaml` codebook alongside `provenance_manifest.json` allows any reviewer to re-run ATLAS on the same files and obtain identical counts.
4. **Tamper-Evident Excel Audit Stamps:** Each prevalence cell in `actuarial_parameter_matrix.xlsx` carries an `ATLAS VERIFICATION AUDIT STAMP` comment, and Tab 2 verifies that the workbook still agrees with the manifest before download.

![Four-step SOFTWARE_TEST audit bridge diagram tracing a highlighted verbatim survey quote with file SHA-256 to its coded frequency row, Excel cell audit-stamp comment, and verify_workbook_integrity PASS check](figures/atlas_audit_bridge.png)
*SOFTWARE_TEST illustration of the audit trail on a built-in sample; mechanics only.*

---

## 10. Evaluation Report Pre-Flight Checklist

Before submitting an evaluation report, grant renewal, or board brief, confirm each item:

- [ ] **Dual Grounding:** Does every major qualitative claim pair an exact count and denominator with a verified verbatim quote?
- [ ] **Denominator Honesty:** Are individual counts (`N` transcripts/respondents) kept strictly separate from focus-group counts (`g of G` groups), with survey error bars omitted on small focus-group pilots?
- [ ] **Verbatim Integrity:** Did you filter by `Quotable Verbatim Only` (or export `verbatim_quotes_inventory.csv`) so no note-taker paraphrase is presented inside quotation marks?
- [ ] **False-Alarm Review:** Did you review **False-Alarm Spot-Check** and tighten any short-stem collisions or negated hits?
- [ ] **Inductive & Deductive Balance:** Did you run TF-IDF + NMF topic discovery to check for unexpected community themes missing from your initial checklist?
- [ ] **Confidentiality & Archiving:** Are personal identifiers removed from public deliverables, and are your final `.yaml` codebook and `provenance_manifest.json` archived together?

---

## Appendix: Developing and Refining a YAML Codebook

A **codebook** is the explicit rule set telling ATLAS which words belong to each domain, whether short stems require whole-word boundaries (`match_mode: exact`), and which phrases should require context or be excluded.

### Option A: Customize Inside ATLAS (No YAML Editor Required)

1. Load your files and pick a starter pack (such as `gbi_focus_group_starter.yaml`), optionally stacking additional starter packs via **Stack Additional Starter Codebooks (optional)**.
2. Run **💡 Unsupervised Topic Discovery (Medoids)** with **TF-IDF + NMF** and click **`➕ Add Theme to Active Codebook`** on any local theme your starter pack missed.
3. Open **🔎 False-Alarm Spot-Check** and click **`🛡️ Exclude Selected Words from Domain`** or **`🎯 Switch Domain to Exact Whole-Word Matching`** on any noisy domain.
4. Click **`📥 Download Active Codebook (.yaml)`** in the sidebar or Tab 2 to archive your finished rules.

### Option B: Author a Custom YAML Codebook Step-by-Step

1. **Start from grant goals and real transcripts:** List the 4 to 8 core outcomes you must track, then scan 5 sample transcripts or focus-group notes to capture the everyday phrases participants actually use (for example, *"ran out of groceries"* alongside *"food insecure"*).
2. **Write a plain definition for each domain:** Spell out what counts and what does not count so every team member interprets the rule identically.
3. **Add roots, matching mode, and fences:** Use `match_mode: exact` on short words (`car`, `bus`, `pay`, `fee`) or add `exclude_fences` (with `exclude_window: 0`) so prefix stems never collide with unrelated words (`card`, `career`, `busy`). Add `context_fences` with `context_window` when a broad word like `ride` or `delay` only counts near `clinic`, `bus`, or `intake`.
4. **Pilot and tighten:** Run your draft on sample files, inspect **False-Alarm Spot-Check**, and revise before running the full dataset.
5. **Save as UTF-8 YAML (`.yaml`):** ATLAS accepts both the Practitioner layout (`topics` with `label`, `keywords`, `required_context`, `context_window`) and the Researcher layout (`domains` with `roots_en`, `roots_es`, `match_mode`, `context_fences`, `exclude_fences`, `exclude_window`).

```yaml
# Family Support Program Evaluation Codebook (Practitioner Layout)
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

  paperwork_delays:
    label: "Enrollment & Paperwork Friction"
    description: "Administrative delays during program intake"
    keywords:
      - "forms"
      - "documentation"
      - "pay stubs"
      - "proof of income"
      - "verification"
      - "delayed"
    context_window: 8
    required_context:
      - "intake"
      - "application"
      - "sign up"
      - "enrollment"
      - "weeks"

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

### Public Topic Libraries and Shipped ATLAS Starter Packs

You rarely need to write domain definitions from scratch. Public standards provide vetted definitions you can pair with everyday participant phrasing:

1. **The 2-1-1 Community Needs Directory ([211taxonomy.org](https://211taxonomy.org)):** Standardized definitions for over 10,000 community needs (rent assistance, food pantries, bus passes, utility relief).
2. **The PRAPARE® Community Clinic Tool ([prapare.org](https://prapare.org)):** Vetted social-determinants categories for housing stress, food security, transit barriers, and clinic access.
3. **The IRIS+ Impact Catalog ([iris.thegiin.org](https://iris.thegiin.org)):** Structured social-outcome definitions covering youth programs, schooling, health access, and family nutrition.
4. **The O*NET Job Skills System ([onetonline.org](https://www.onetonline.org)):** U.S. Department of Labor vocabulary for job training, workplace tasks, and career mobility barriers.
5. **ATLAS Starter Packs (shipped inside `config/`):**
   * `gbi_focus_group_starter.yaml`: 8 pre-fenced GBI and cash-assistance focus-group domains (housing, groceries, debt/bills, employment/education, transportation, caregiving, stress/autonomy, and program paperwork).
   * `sdoh_basic_needs.yaml`: Housing, food, transportation, and utility barriers with short-stem exclusion fences.
   * `intake_and_enrollment.yaml`: Paperwork delays, wait times, language access, and staff navigation rapport.
   * `workforce_and_mobility.yaml`: Benefit cliffs, wage progression, job training, and workplace scheduling.
   * `youth_and_family.yaml`: School attendance, family support, childcare, and youth engagement.
   * `pfl_case_study_codebook.yaml` and `labor_market_codebook.yaml`: Paid family leave and labor-market research packs.

*(Read any ATLAS guide formatted right inside **Tab 3: Reference Guides**, or download formatted Word `.docx` copies from the sidebar.)*

---

*ATLAS is open-source software distributed under the MIT License. Documentation, sample codebooks, and implementation guides are available at [github.com/dphdame/atlas](https://github.com/dphdame/atlas).*
