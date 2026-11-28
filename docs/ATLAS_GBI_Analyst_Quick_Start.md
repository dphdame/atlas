# ATLAS Quick-Start Guide for Focus-Group Analysts

**Automated Text-to-Ledger Actuarial Synthesis (ATLAS, v1.2)** is a private, offline tool for qualitative notes and surveys. It turns 3-column focus-group notes and survey boxes into group counts, direct quotes, and printable Word and Excel reports. Every file stays on your laptop.

---

## 1. Open ATLAS Offline

- **Zero-Install Browser Edition (fastest):** Open `ATLAS_Workbench.html` (or `ATLAS_Workbench.aspx` on SharePoint) in Microsoft Edge or Google Chrome. Nothing installs on your laptop. Files stay in local browser memory.
- **Python Desktop App (optional):** Double-click `run.bat` on Windows or `run.command` on Mac.

---

## 2. Upload Your Notes or Survey Files

1. Under **Input Files**, click **Choose files** (or drag files into the box). You can add Word (`.docx`) notes or Excel and Comma-Separated Values (`.xlsx` / `.csv`) survey files.
2. **Automatic Group Mode:** ATLAS spots 3-column Word notes (`Key Points`, `Notable Quotes`, `Observations`). It picks **Group / summarized notes (1 file = 1 group)** on its own. Leave **Include Note-Taker Observations** off unless you want note-taker notes coded alongside participant speech.
3. **Excel surveys:** Pick one Excel tab and one text column at a time. ATLAS skips empty answers. It counts blank boxes separately and never calls them a study participation rate.
4. Click **Run Analysis** to code your files. Click it again after any later change. In the Python app, click **Save active themes (.yaml)** before switching files, because clicking **Run Analysis** there reloads the sidebar theme boxes.

ATLAS strips prompts (`Question 1:`, `Q1:`, `Facilitator:`), room headers, and consent boxes before coding. Prompt words never inflate your counts. You can check every skipped line in **Excluded Questions & Session Headers** at the bottom of **Theme Summary**.

---

## 3. Pick, Add, or Upload a Theme Library

ATLAS counts plain word rules, not topics invented by artificial intelligence (AI). You can set up your theme list in three ways.

1. **Use starter drawers:** Open **Core Evaluation Themes (10)** or **Optional Add-On Themes (5)** under **Themes to Code**. Check or uncheck any theme.
2. **Upload a custom theme file:** Open **Upload Custom Themes (.yaml)**. Pick a plain-text YAML Ain't Markup Language (`.yaml` or `.yml`) file. The Browser Edition also accepts JavaScript Object Notation (`.json`). Choose **Use uploaded themes only** or **Combine with checked themes above**.
3. **Add a new topic from your data:** Open **Discover Unlisted Themes**. Read any cluster marked **Mostly Uncoded by Active Themes**. Pick it under **Add a Discovered Cluster to Active Themes**. Type a clear name, keep exact whole-word matching checked, and press **Add Theme to Active Themes**. Click **Save Active Themes (.yaml)** in **Exports & Audit Files** to share that file with your team.

---

## 4. Check Quotes Safely and Run the 5-Minute Spot-Check

- **Read group counts honestly:** Lead with the **Group × Theme Grid (`✓` / `—`)**. Report the count of focus groups that raised each theme. Click any `✓` cell to jump straight to its quotes. Treat bar counts as note volume, not a headcount of people who agreed.
- **Never quote a paraphrase by mistake:** On **Coded Evidence**, check **Verbatim Quotes Only** (labeled **Quotable Verbatim Only** in the Python app). Do this before pasting quotes into slides or memos.
- **Spot-check flagged matches:** Open **Spot-Check Matches** before sharing counts. Flagged words stay in your tables until you exclude them. Review **Check First** (partial words and typos) and **Check in Context** (nearby "not" or "no"). Check any false hit, then click **Exclude Selected Words & Re-Run**.

---

## 5. Download Your Reports and Tables

Right under **Theme Summary**, use these one-click buttons.

- **Download Full Report (.docx):** Printable Word report (`atlas_summary_report.docx`) with counts, bar chart, grid, quotes, and a Technical Appendix.
- **Download Theme Frequencies (.xlsx):** Full Excel workbook (`atlas_theme_frequencies.xlsx` in Browser; `actuarial_parameter_matrix.xlsx` in Python) with all coded rows.
- **Download Direct Quotes (.csv):** Direct quotes file (`direct_quotes_inventory.csv` or `verbatim_entries_inventory.csv` in Browser; `verbatim_quotes_inventory.csv` in Python).
- **Download Chart (.svg)** *(Browser Edition)*: Sharp Scalable Vector Graphics (SVG) chart (`atlas_theme_chart.svg`) for slides. In Python, save charts from the chart `...` menu or use the chart inside the Word report.

*Technical note: Offline topic discovery uses Term Frequency–Inverse Document Frequency and Non-Negative Matrix Factorization (`TF-IDF + NMF`). Open the **Reference Guides** tab in the Python app or see [ATLAS User Guide](ATLAS_User_Guide.md) for screenshots and YAML rule syntax.*

**Questions or help adapting ATLAS:** Contact **Victoria Cholette** on GitHub ([@dphdame](https://github.com/dphdame)) or at [hello@tooearlytosay.com](mailto:hello@tooearlytosay.com).
