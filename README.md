# ATLAS

**Automated Thematic Labeling and Analysis System**

A Python tool for thematic analysis of qualitative responses (focus groups, open-ended survey items, interview transcripts). Built for public health researchers, with default themes organized by the **Social Determinants of Health** framework (Healthy People 2030).

## What it does

- Loads a CSV or Excel file of text responses
- Assigns each response to one or more themes using either:
  - **Guided mode** — a predefined SDOH theme dictionary (editable)
  - **Automatic mode** — Latent Dirichlet Allocation (LDA) topic discovery
- Produces sentiment scores (VADER), topic distributions, word clouds, and heatmaps by site/cohort/group
- Exports results to Excel or CSV
- Runs entirely on the user's machine (no cloud, no API calls, no data leaves the computer)

## Install (Windows)

See [`INSTALL.md`](INSTALL.md).

Quick version:
1. Install Python 3.12 with **"Add python.exe to PATH"** checked
2. Double-click `setup.bat` (one-time, ~5 minutes)
3. Double-click `run.bat` to launch the dashboard at http://localhost:8501

## Default themes (SDOH)

Organized by the five Healthy People 2030 domains:

| SDOH Domain | Themes |
|-------------|--------|
| Economic Stability | Employment & Income, Financial Stability, Food Security |
| Education Access & Quality | Education & Training |
| Health Care Access & Quality | Healthcare Access, Mental Health |
| Neighborhood & Built Environment | Housing, Transportation |
| Social & Community Context | Family & Caregiving, Community & Safety |

All themes and keywords are editable from the dashboard sidebar.

## Files

```
ATLAS/
├── README.md             This file
├── INSTALL.md            Windows install guide
├── setup.bat             One-time setup (installs Python packages)
├── run.bat               Launch the dashboard
├── app.py                Streamlit dashboard
├── topic_modeling.py     NLP analysis (LDA + dictionary)
├── requirements.txt      Python package list
├── _pip_helper.py        Pip wrapper (handles a known Windows registry bug)
├── data/
│   └── test_sample.csv   Sample CHNA-style responses for first-run test
└── docs/
    └── ATLAS_User_Guide.md   Full user guide
```

## Using your own data

Expected format: a CSV or Excel file with at least one column of text responses.

| Column | Required | Description |
|--------|----------|-------------|
| response | Yes | The text to analyze |
| participant_id | No | For tracking individuals across rows |
| site / cohort / program | No | Optional grouping variable |
| question | No | If responses come from different prompts |

See [`docs/ATLAS_User_Guide.md`](docs/ATLAS_User_Guide.md) for full details.
