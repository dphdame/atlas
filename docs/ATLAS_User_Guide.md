# ATLAS User Guide
## Automated Thematic Labeling and Analysis System

**Version:** 2.0
**Last Updated:** February 2026

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Quick Start](#2-quick-start)
3. [Preparing Your Data](#3-preparing-your-data)
4. [Analysis Modes](#4-analysis-modes)
5. [Configuration Options](#5-configuration-options)
6. [Understanding Your Results](#6-understanding-your-results)
7. [Exporting and Reporting](#7-exporting-and-reporting)
8. [Troubleshooting](#8-troubleshooting)

**Appendices**
- [A. What is Thematic Analysis?](#appendix-a-what-is-thematic-analysis)
- [B. Understanding Topic Modeling (LDA)](#appendix-b-understanding-topic-modeling-lda)
- [C. Understanding Dictionary-Based Analysis](#appendix-c-understanding-dictionary-based-analysis)
- [D. Understanding Sentiment Analysis](#appendix-d-understanding-sentiment-analysis)
- [E. Interpreting Fit Measures](#appendix-e-interpreting-fit-measures)
- [F. Sample Report Write-Ups](#appendix-f-sample-report-write-ups)
- [G. Glossary](#appendix-g-glossary)

---

## 1. Introduction

ATLAS is a tool for analyzing open-ended survey responses and focus group transcripts. It helps researchers identify themes (recurring topics) and sentiment (positive/negative tone) in qualitative data.

### What ATLAS Does

- **Identifies themes**: Groups similar responses together based on content
- **Assigns multiple themes**: Can identify primary, secondary, and tertiary themes per response
- **Measures fit**: Shows how well each response matches its assigned theme(s)
- **Analyzes sentiment**: Determines if responses are positive, negative, or neutral
- **Checks spelling**: Optionally corrects typos before analysis
- **Flags short responses**: Identifies responses that may be too brief for reliable analysis
- **Exports results**: Creates spreadsheets with coded data for further analysis

### What ATLAS Does NOT Do

- Replace human judgment in interpreting findings
- Work with languages other than English
- Analyze images, audio, or video
- Guarantee perfect accuracy (all automated tools require human validation)

---

## 2. Quick Start

### Step 1: Prepare Your Data

Create a CSV or Excel file with your responses. At minimum, you need one column containing text:

| response |
|----------|
| The program helped me pay rent... |
| I could afford groceries... |

### Step 2: Upload and Configure

1. Open ATLAS in your browser (typically http://localhost:8501 or http://localhost:8502)
2. Upload your file using the sidebar
3. Enter your text column name (default: "response")
4. Optionally enter a group column for grouping (e.g., "site", "cohort") and a display label
5. Select your analysis mode (Guided or Automatic)
6. Choose how many themes to assign (1-3)
7. Set your preprocessing options (spell check, minimum words)
8. Preview spell check corrections if enabled (expand the preview panel)
9. Click "Run Analysis"

### Step 3: Review Results

- View theme distribution charts and topic weight explanations
- Explore sentiment patterns
- Check for flagged responses (too short)
- Browse individual responses by theme, with coded/uncoded filtering
- Analyze uncoded responses to discover missing themes
- Download your coded data

---

## 3. Preparing Your Data

### Required Format

Your file must be CSV or Excel (.xlsx) with at least one text column.

### Recommended Columns

| Column | Required | Description |
|--------|----------|-------------|
| response | Yes | The text to analyze |
| participant_id | No | For tracking individuals |
| stratifier (e.g., site, cohort, program) | No | For grouping and filtering results |
| question | No | If responses come from different questions |

### Data Quality Tips

- **Minimum length**: Responses should be at least 5 words for reliable analysis
- **One response per row**: Do not combine multiple responses in one cell
- **Consistent formatting**: Avoid mixing languages or heavy abbreviations

### Example Data

| response_id | site | response |
|-------------|------|----------|
| 1 | North Clinic | Rent keeps going up and I've almost been evicted twice this year |
| 2 | South Center | I have to take two buses to get to a doctor and it takes half a day |
| 3 | East Health Hub | The closest grocery store with fresh produce is 20 minutes away |

---

## 4. Analysis Modes

### Guided (Dictionary) Mode

**Best for:** When you already know what themes you're looking for

This mode searches for specific keywords associated with predefined themes. For example, the "Housing" theme looks for words like "rent," "apartment," "eviction," etc.

**Advantages:**
- Transparent: You can see exactly which keywords triggered each theme
- Customizable: Add your own themes and keywords
- Consistent: Same keywords always produce same results

**Limitations:**
- May miss themes expressed with unexpected vocabulary
- Requires good keyword lists

**Default Themes (Social Determinants of Health):**

Organized by the Healthy People 2030 SDOH framework.

*Economic Stability:*
- Employment & Income
- Financial Stability
- Food Security

*Education Access & Quality:*
- Education & Training

*Health Care Access & Quality:*
- Healthcare Access
- Mental Health

*Neighborhood & Built Environment:*
- Housing
- Transportation

*Social & Community Context:*
- Family & Caregiving
- Community & Safety

### Automatic (LDA) Mode

**Best for:** Exploring data without preconceptions

This mode uses a statistical algorithm (Latent Dirichlet Allocation) to discover themes based on which words tend to appear together.

**Advantages:**
- Discovers unexpected themes
- No predefined categories needed
- Good for exploratory analysis

**Limitations:**
- Results can vary slightly between runs
- Themes may not always be interpretable
- Requires enough data (50+ responses recommended)

---

## 5. Configuration Options

### Themes Per Response (1-3)

| Setting | When to Use |
|---------|-------------|
| **1 theme** | When responses clearly belong to single categories |
| **2 themes** | When responses often touch on multiple topics |
| **3 themes** | When responses are long and cover many topics |

### Spell Check

| Level | Effect | When to Use |
|-------|--------|-------------|
| **Off** | No changes | Preserve dialect, slang, intentional variations |
| **Light** | Fix obvious typos only | Most focus group data (recommended) |
| **Strict** | Fix all detected misspellings | Clean survey responses |

**Note:** Spell check runs before analysis. "Light" mode is conservative and will not change words that might be intentional (slang, names, technical terms).

### Minimum Words

Responses shorter than this threshold will be flagged as "Below minimum length" rather than assigned themes.

- **Default: 5 words**
- Set to 0 to disable length filtering
- Short responses often lack enough context for reliable theme assignment

### Sentiment Analysis

When enabled, calculates a sentiment score from -1 (very negative) to +1 (very positive) for each response using the VADER algorithm.

### Group Column

Use this optional setting to group and filter your results by a categorical variable. Enter the column name in the **Group column** field.

| Example Values | Use Case |
|----------------|----------|
| site | Compare responses from different locations or clinics |
| cohort | Compare waves of data collection over time |
| program | Compare results across programs or interventions |
| question | Filter results by survey question |

### Group Label

When a group column is specified, the **Group label** field controls how the grouping variable is displayed in charts and tables. It defaults to "Group" but can be customized (e.g., "Site", "Cohort", "Program").

When a group column is specified:
- A metric shows how many distinct groups exist
- Heatmaps show topic distribution across groups
- Filter dropdowns let you focus on a single group
- The data explorer can filter by group

### Spell Check Preview

Before running analysis, if spell check is set to "Light" or "Strict", you can expand the **Preview Spell Check Corrections** panel to see:
- Which words will be corrected
- What they will be corrected to
- The original context (surrounding words)

This helps you decide whether spell check is appropriate for your data. Some corrections may be incorrect (e.g., slang, proper nouns, domain terms).

### Settings Workflow

ATLAS settings remain editable at all times:

1. **Before analysis**: Configure settings and click "Run Analysis"
2. **After analysis**: Results remain visible while you adjust settings
3. **Settings changed**: A warning banner appears when settings differ from the current results
4. **Update results**: Click "Update Results" to re-run with new settings

This allows you to iterate and refine your analysis without losing your previous results.

---

## 6. Understanding Your Results

### Theme Columns

| Column | Description |
|--------|-------------|
| primary_theme | Best-matching theme |
| primary_fit | How well it matches (see Appendix E) |
| secondary_theme | Second-best theme (if n_themes ≥ 2) |
| secondary_fit | Fit score for secondary theme |
| tertiary_theme | Third-best theme (if n_themes = 3) |
| tertiary_fit | Fit score for tertiary theme |

### Fit Measures (Dictionary Mode)

| Column | Description |
|--------|-------------|
| primary_fit_count | Number of keywords matched |
| primary_fit_pct | Percentage of theme's keywords found |

### Sentiment Columns

| Column | Description |
|--------|-------------|
| sentiment_score | -1.0 to +1.0 |
| sentiment_label | "Positive" (>0.05), "Neutral", or "Negative" (<-0.05) |

### Quality Columns

| Column | Description |
|--------|-------------|
| word_count | Number of words in response |
| meets_length_min | True/False |
| length_flag | Warning message if too short |

### Topic Details

The Topic Details section shows the top terms for each discovered or defined theme. In LDA mode, each term is followed by a **topic weight** in parentheses (e.g., "housing (23.19)"). This weight indicates how strongly the word characterizes the topic: higher values mean the word is more distinctive to that topic. Compare weights within a topic to see which words define it most; the scale varies by dataset, so cross-topic comparisons are less meaningful.

In LDA mode, each word appears in only one topic (the one where it has the highest weight), so there is no overlap between themes.

### Explore Responses

The data explorer includes:

- **Response status filter**: Toggle between All, Coded (assigned to a theme), and Uncoded (no theme match or below minimum word count) with counts for each
- **Column definitions**: A collapsible table explaining every variable in the data table, including fit measures and their interpretive ranges
- **Topic and group filters**: Narrow results by theme or grouping variable

### Uncoded Response Analysis

When uncoded responses exist, ATLAS provides tools to investigate them:

1. **Frequent words**: A bar chart and table showing the most common words in uncoded responses (after filtering stopwords). Use this to spot patterns the dictionary missed and decide whether to add keywords to existing themes or create new ones.

2. **LDA discovery** (available when 20+ uncoded responses): Run automatic topic modeling on just the uncoded subset to discover hidden patterns. The discovered topics and their top words are displayed with a suggestion to add them as new themes via the sidebar.

---

## 7. Exporting and Reporting

### Excel Export

The Excel download includes multiple sheets:

1. **Coded Responses**: All data with theme and sentiment columns
2. **Theme Summary**: Counts and percentages for each theme (primary, secondary, tertiary)
3. **Sentiment Summary**: Overall sentiment statistics
4. **Data Quality**: Word count statistics and flagged responses

### Using Results in Reports

See **Appendix F** for sample write-ups showing how to present ATLAS findings in reports.

---

## 8. Troubleshooting

### "Column not found" error
Your text column has a different name. Use the dropdown to select the correct column.

### Many responses show "Uncategorized"
In Dictionary mode, responses without keyword matches get this label. Consider:
- Scrolling to the **Uncoded Response Analysis** section to see frequent words in these responses
- Adding those frequent words to existing themes in the sidebar
- Running LDA on uncoded responses (if 20+) to discover new themes
- Switching to Automatic mode for exploratory analysis

### Many responses show "Below minimum length"
Responses with fewer than the minimum words (default: 5) are flagged. Consider:
- Lowering the minimum if short responses are expected
- Setting minimum to 0 to disable filtering
- Reviewing flagged responses separately

### Sentiment seems wrong
VADER sentiment analysis works best on conversational text. Very formal or domain-specific language may not score accurately. Always validate a sample manually.

### Analysis is slow
LDA topic modeling can take time with large datasets (1000+ responses). This is normal.

---

# Appendices

---

## Appendix A: What is Thematic Analysis?

Thematic analysis is a method for identifying patterns (themes) in qualitative data. Think of it as sorting responses into categories based on what they're about.

### Traditional Approach

Traditionally, researchers read through every response and manually assign category codes. For example:

| Response | Code |
|----------|------|
| "The money helped me pay rent" | Housing |
| "I bought groceries for my kids" | Food |
| "I felt less stressed about bills" | Mental Health |

This works well but becomes impractical with hundreds or thousands of responses.

### Computational Approach

ATLAS uses computational methods to assist with this process:

1. **Dictionary-based**: Looks for specific keywords associated with each theme
2. **Statistical (LDA)**: Discovers patterns in word co-occurrence

### Important Caveats

Computational thematic analysis is a **supplement to**, not a **replacement for**, human judgment. Always:

- Review automated assignments for accuracy
- Read responses within each theme to verify coherence
- Consider themes the algorithm may have missed
- Interpret findings in context

---

## Appendix B: Understanding Topic Modeling (LDA)

### What is LDA?

Latent Dirichlet Allocation (LDA) is a statistical method that discovers hidden topics in a collection of documents by analyzing which words tend to appear together.

### How It Works (Simplified)

Imagine you have a bag of marbles, but you can only see them through frosted glass. You can tell that some marbles cluster together, even if you can't see them clearly. LDA works similarly - it detects word clusters without knowing what they mean.

**Step 1**: The algorithm looks at all responses and counts which words appear together frequently.

**Step 2**: It groups words that tend to co-occur into "topics."

**Step 3**: Each response is scored on how much it belongs to each topic.

### Toy Example

Given these three responses:

| Response |
|----------|
| "I paid rent and avoided eviction from my apartment" |
| "The money helped with groceries and food for my kids" |
| "I could afford childcare while I looked for work" |

LDA might discover these word clusters:

**Topic 1**: rent, apartment, eviction, housing
**Topic 2**: groceries, food, kids, meals
**Topic 3**: childcare, work, job, afford

### Interpreting LDA Output

The "fit" score (probability) tells you how strongly a response belongs to its assigned topic:

| Probability | Interpretation |
|-------------|----------------|
| > 0.70 | Strong fit - clearly about this topic |
| 0.40 - 0.70 | Moderate fit - primarily this topic but mentions others |
| < 0.40 | Weak fit - may belong to multiple topics equally |

### Word Exclusivity

ATLAS assigns each word to only one topic (the topic where it has the highest weight). This means words will not repeat across multiple topics, making themes easier to distinguish and interpret.

### Limitations

- Topics are just word clusters; humans must interpret their meaning
- Results can vary slightly between runs
- Works poorly with very short texts (< 10 words)
- May not find themes that don't have distinct vocabulary

---

## Appendix C: Understanding Dictionary-Based Analysis

### What is Dictionary-Based Analysis?

Instead of discovering themes statistically, dictionary-based analysis uses predefined lists of keywords to identify themes. It's like having a checklist for each category.

### How It Works

**Step 1**: Define themes with keyword lists

```
Housing: rent, apartment, eviction, lease, landlord
Food: groceries, food, meals, hungry, eating
Healthcare: doctor, medicine, hospital, health, prescription
```

**Step 2**: For each response, count keyword matches

**Step 3**: Assign the theme with the most matches

### Toy Example

**Response**: "I paid rent and bought groceries for my family"

**Matching:**
- Housing: 1 match (rent)
- Food: 1 match (groceries)
- Healthcare: 0 matches

**Result**: Tie between Housing and Food. ATLAS assigns Housing as primary (higher in list), Food as secondary.

### Interpreting Fit Measures

In Dictionary mode, you get two measures:

**fit_count** (raw keyword matches):
| Count | Interpretation |
|-------|----------------|
| 4+ | Very strong match - multiple relevant terms |
| 2-3 | Strong match - clear theme presence |
| 1 | Weak match - may be incidental |
| 0 | No match - "Uncategorized" |

**fit_pct** (percentage of theme keywords found):
| Percentage | Interpretation |
|------------|----------------|
| > 20% | Strong - response heavily uses theme vocabulary |
| 10-20% | Moderate - clear theme presence |
| < 10% | Weak - may be incidental mention |

### When to Use Dictionary Mode

- You have specific themes you're investigating
- You want transparent, reproducible results
- Your domain has established vocabulary
- You need to compare results across studies

---

## Appendix D: Understanding Sentiment Analysis

### What is Sentiment Analysis?

Sentiment analysis determines the emotional tone of text - whether it expresses positive, negative, or neutral feelings.

### How VADER Works

ATLAS uses VADER (Valence Aware Dictionary and sEntiment Reasoner), which:

1. **Looks up words** in a sentiment dictionary (e.g., "love" = positive, "terrible" = negative)
2. **Considers modifiers**: "very good" is more positive than "good"
3. **Handles negation**: "not good" becomes negative
4. **Accounts for punctuation**: "Great!!!" is more positive than "Great"

### Interpreting Sentiment Scores

| Score Range | Label | Meaning |
|-------------|-------|---------|
| +0.05 to +1.0 | Positive | Expresses satisfaction, gratitude, hope |
| -0.05 to +0.05 | Neutral | Factual, descriptive, no strong emotion |
| -1.0 to -0.05 | Negative | Expresses frustration, disappointment, distress |

### Toy Examples

| Response | Score | Label |
|----------|-------|-------|
| "The program has been wonderful for my family!" | +0.75 | Positive |
| "I received payments on the 15th of each month." | +0.02 | Neutral |
| "This was frustrating and the amount wasn't enough." | -0.62 | Negative |
| "It helped with rent but I still worry about bills." | +0.15 | Positive (mixed) |

### Limitations

- May miss sarcasm or irony ("Oh great, another bill")
- Domain-specific terms may not be in the dictionary
- Cultural expressions may not score accurately
- Very short responses are less reliable

---

## Appendix E: Interpreting Fit Measures

### For LDA (Automatic Mode)

The fit score is a **probability** (0 to 1) representing how likely the response belongs to each topic.

| Primary Fit | What It Means |
|-------------|---------------|
| > 0.80 | Very strong fit. Response clearly belongs to this topic. |
| 0.60 - 0.80 | Strong fit. Topic is dominant but others may be present. |
| 0.40 - 0.60 | Moderate fit. Response may span multiple topics. |
| < 0.40 | Weak fit. Assignment is uncertain; review manually. |

**Tip**: When primary + secondary fit together ≈ 0.90+, the response spans two topics roughly equally.

### For Dictionary Mode

**fit_count** (keyword matches):
| Count | Interpretation |
|-------|----------------|
| 5+ | Very strong match - response is clearly about this theme |
| 3-4 | Strong match - theme is well-represented |
| 2 | Moderate match - theme is present |
| 1 | Weak match - may be coincidental |

**fit_pct** (percentage of keywords):
| Percentage | Interpretation |
|------------|----------------|
| > 20% | Strong - response uses much of theme's vocabulary |
| 10-20% | Moderate - clear connection to theme |
| < 10% | Weak - minimal vocabulary overlap |

### Using Fit Measures for Quality Control

1. **Flag weak assignments**: Review responses with primary_fit < 0.40 (LDA) or fit_count = 1 (Dictionary)
2. **Identify multi-theme responses**: When primary and secondary fits are close
3. **Validate themes**: Randomly sample responses from each theme and verify assignments make sense

---

## Appendix F: Sample Report Write-Ups

### Example 1: Theme Distribution Summary

> Thematic analysis of 127 participant responses revealed five primary themes. **Housing** was the most frequently identified theme (28% of responses), followed by **Healthcare Access** (22%), **Food Security** (18%), **Transportation** (15%), and **Mental Health** (11%). The majority of responses (69%) were assigned to a single theme, while 31% touched on multiple SDOH domains.

### Example 2: Describing a Specific Theme

> The **Mental Health** theme captured responses describing stress, anxiety, and emotional well-being. Characteristic terms included *stress*, *anxiety*, *worry*, *sleep*, and *overwhelmed*. A typical response in this category: *"The stress of bills and childcare is constant. I haven't slept a full night in months and I know it's affecting my mental health."* This theme appeared as the primary theme in 19 responses (15%) and as a secondary theme in an additional 12 responses (9%).

### Example 3: Sentiment Analysis Summary

> Overall sentiment across responses was slightly negative (M = -0.08, SD = 0.46). Roughly a third of responses (32%) expressed positive sentiment, while 41% were negative and 27% were neutral. Positive responses typically described access to services, community support, or concrete resources that helped participants. Negative responses most commonly cited cost barriers, long travel times, and chronic stress from unmet basic needs.

### Example 4: Multi-Theme Analysis

> Analysis assigning up to two themes per response revealed common theme pairings. **Housing** and **Financial Stability** co-occurred most frequently, appearing together in 18% of multi-theme responses. This pattern reflects participants' interconnected concerns about rent affordability and overall financial security. **Transportation** and **Healthcare Access** co-occurred in 14% of multi-theme responses, illustrating how mobility barriers shape access to care.

### Example 5: Methodological Note

> Thematic coding was conducted using ATLAS, a computational text analysis tool employing dictionary-based classification. Each response was assigned up to two themes based on keyword matching with predefined theme dictionaries. Theme assignments were validated through manual review of a 20% random sample, yielding 94% agreement between automated and human coding. Responses shorter than five words (n=7) were excluded from thematic analysis due to insufficient context. Sentiment scores were calculated using the VADER algorithm.

### Example 6: Data Quality Statement

> Of 150 collected responses, 143 (95%) met the minimum length requirement of 5 words for thematic analysis. Seven responses were flagged as too brief for reliable coding (M = 2.1 words). These brief responses were retained in the dataset but excluded from theme analysis. Average response length was 24.3 words (SD = 15.2, range = 0-89).

---

## Appendix G: Glossary

| Term | Definition |
|------|------------|
| **Coded response** | A response that was assigned to a theme |
| **Compound score** | A single number (-1 to +1) summarizing overall sentiment |
| **Dictionary-based analysis** | Classification using predefined keyword lists |
| **Fit measure** | How well a response matches its assigned theme |
| **Group column** | An optional column used to group and filter results (e.g., site, cohort) |
| **Group label** | The display name for the grouping variable in charts and tables |
| **fit_count** | Number of theme keywords found in a response (Dictionary mode) |
| **fit_pct** | Percentage of a theme's keywords found in a response (Dictionary mode) |
| **LDA** | Latent Dirichlet Allocation; a statistical topic modeling method |
| **Lemmatization** | Reducing words to their base form (e.g., "running" → "run") |
| **Primary theme** | The best-matching theme for a response |
| **Secondary theme** | The second-best matching theme |
| **Tertiary theme** | The third-best matching theme |
| **Sentiment** | The emotional tone (positive/negative/neutral) of text |
| **Spell check** | Optional correction of misspellings before analysis |
| **Stopwords** | Common words (the, a, is) excluded from analysis |
| **Theme** | A recurring pattern or topic in the data |
| **Topic modeling** | Statistical methods for discovering themes in text |
| **Topic weight** | In LDA mode, how strongly a word characterizes a topic; higher = more distinctive |
| **Uncoded response** | A response not assigned to any theme (Uncategorized or below minimum length) |
| **VADER** | A rule-based sentiment analysis tool optimized for social media text |
| **Word count** | Number of words in a response |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.2 | Feb 2026 | LDA word deduplication (no cross-topic overlap), chart label fixes, "Group" terminology (replaces "Stratifier"/"Pilot") with customizable display label, uncoded response analysis (frequent words + LDA discovery), coded/uncoded response filter, column definitions table, topic weight explanations, fit measure interpretive ranges, removed domain-specific stopwords for project-agnostic use |
| 2.1 | Feb 2026 | Added stratifier column for flexible grouping, spell check preview, improved settings workflow (persistent results), filtering for heatmaps and sentiment |
| 2.0 | Feb 2026 | Added multi-theme assignment, spell check, sentiment analysis, response length handling |
| 1.0 | Dec 2024 | Initial release with LDA and Dictionary modes |
