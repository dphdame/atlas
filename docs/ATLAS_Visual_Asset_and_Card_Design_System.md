# ATLAS Visual Asset & Container Card Design System
### Institutional Visual Standards for Econometric Deliverables & Public Documentation

---

## 1. Executive Summary & Design Directive

Technical communication across applied microeconomics, platform engineering, and public policy evaluation requires an uncompromising standard of visual credibility. Unlike conceptual marketing diagrams, technical graphics in the ATLAS ecosystem function as **auditable empirical proofs**. 

This document establishes the official visual asset standards, card layout principles, and verification gates across all ATLAS public-facing deliverables (white papers, GitHub documentation, research blog articles, and slide decks).

---

## 2. Core Image Portfolio (The 5 Mandatory Exhibits)

Every public release of ATLAS incorporates exactly five standard visual assets, each serving a single, distinct cognitive function:

| Asset ID | File Name | Cognitive Job | Target Venues | Primary Mathematical / Algorithmic Proof |
| :--- | :--- | :--- | :--- | :--- |
| **IMG-01** | [`atlas_pipeline_architecture.png`](figures/atlas_pipeline_architecture.png) | Conceptual Mechanism | GitHub README, White Paper, TETS Article | Separation of unsupervised LDA discovery, YAML context fencing, and deterministic state execution. |
| **IMG-02** | [`atlas_labor_market_distribution.png`](figures/atlas_labor_market_distribution.png) | Empirical Proof | White Paper, LinkedIn Post 2, TETS Article | Parameterization of hedonic wage models across $n=2,500$ authentic applied micro job specifications. |
| **IMG-03** | [`atlas_audit_bridge.png`](figures/atlas_audit_bridge.png) | Auditability & Bridge | White Paper, GitHub README, LinkedIn Post 1 | Automated cell parameter injection with embedded cryptographic SHA-256 metadata comments. |
| **IMG-04** | [`atlas_dashboard_ui_walkthrough.png`](figures/atlas_dashboard_ui_walkthrough.png) | Operational Walkthrough | GitHub README, Video Walkthrough, LinkedIn Post 3 | Local offline Streamlit dashboard featuring WCAG 2.1 AA contrast and accessible tabular fallbacks. |
| **IMG-05** | [`atlas_codebook_context_fence.png`](figures/atlas_codebook_context_fence.png) | Operational Fencing | TETS Methods Article, GitHub Technical Docs | Side-by-side demonstration of YAML token window fencing eliminating false positives deterministically. |

---

## 3. The 6 Rules of Container Card Architecture

Cards are bounded cognitive contracts. In complex technical exhibits, cards prevent eye fatigue and eliminate text collisions. All ATLAS card components must adhere to six geometric rules:

```
┌────────────────────────────────────────────────────────┐
│  [BADGE]  CARD TITLE (9.5pt Bold, #1E293B)             │  <-- Top-Left Anchor Pill
│  Subtitle / Technical Scope (8pt Italic, #64748B)      │
├────────────────────────────────────────────────────────┤  <-- 0.8px Hairline Divider (#E2E8F0)
│                                                        │
│  • Rule / Feature Line 1 (8.2pt Regular, #334155)      │
│  • Rule / Feature Line 2 (8.2pt Regular, #334155)      │  <-- 1.25 Line Spacing Floor
│  • Deterministic Output / Metric (8.2pt Regular)       │
│                                                        │
└────────────────────────────────────────────────────────┘
  ▲ Aspect Ratio: 4:3 (Compact) to 16:9 (Horizontal)
  ▲ Internal Padding: >= 8% of card width/height
  ▲ Border: 1.5px Solid (#1E3A8A, #0F766E, or #B45309)
  ▲ Fill: #F8FAFC (Ultra-Light Slate)
```

1. **The Aspect Ratio Rule ($4:3$ to $16:9$):**
   * Container cards must maintain standard horizontal proportions. Needle-thin vertical boxes force awkward word wraps and must never be used.
2. **The Internal Padding Floor ($8\%$ Rule):**
   * Text must never touch a container border. Internal padding must equal at least $8\%$ of the card's dimensions on all four margins.
3. **Top-Left Metadata Anchor Badges:**
   * Place specialized module pills (`[IND-SCAN]`, `[CTX-FENCE]`, `[DET-EXEC]`, `[ECON-LEDGER]`) in the top-left corner with bold, solid fill. The reader must grasp the module category before reading technical prose.
4. **Hairline Section Dividers (0.8px):**
   * Separate card headers from body content using subtle 0.8px borders (`#E2E8F0` or 35% opacity brand border).
5. **Strict $0^\circ$ Horizontal Text Floor:**
   * Never rotate text by $-45^\circ$ or $90^\circ$. All category labels, bullet items, and frequency numbers must be oriented strictly horizontally ($0^\circ$) to eliminate neck strain and text collision.
6. **Zero Nested Cards:**
   * Never place a bordered card inside another bordered card. Sub-groups must be separated by whitespace, subtle hairline rules, or typography hierarchy.

---

## 4. Color Palette & Typography Specifications (WCAG 2.1 AA)

All visual assets must meet or exceed WCAG 2.1 AA contrast standards ($\ge 4.5:1$ for normal body text; $\ge 3.0:1$ for graphical borders and large text):

### Color Tokens
* **Deep Navy (`#1E3A8A`):** Primary brand, structural borders, main titles. Contrast ratio against white: **8.39:1**.
* **Forest Teal (`#0F766E`):** Deductive logic, action buttons, verification badges. Contrast ratio against white: **5.20:1**.
* **Amber / Ochre (`#B45309`):** State machine execution, warnings, provenance callouts. Contrast ratio against white: **4.74:1**.
* **Wine / Crimson (`#B91C1C`):** Bottlenecks, operational frictions, filtered exclusions. Contrast ratio against white: **5.89:1**.
* **Dark Slate (`#1E293B`):** Body typography, axis headers, data values. Contrast ratio against white: **12.60:1**.
* **Muted Slate (`#64748B`):** Secondary captions, file paths, subtitles. Contrast ratio against white: **4.60:1**.
* **Card Fill (`#F8FAFC`):** Neutral container background providing crisp contrast for dark slate text.

### Typography Stack
```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
```
* **Diagram Titles:** 12.0–13.0 pt Bold (`#1E3A8A`)
* **Card Titles:** 9.2–9.5 pt Bold (`#1E293B`)
* **Axis Labels & Ticks:** 9.5–10.0 pt Bold (`#1E3A8A` / `#475569`)
* **Body / Bullet Text:** 8.0–8.5 pt Regular (`#334155`)
* **Code / Hash Monospace:** 7.2–7.8 pt Monospace (`#0F766E` / `#B45309`)

---

## 5. The 4-Step Objective Verification Gate

Before any graphic is approved for publication in the manual, repository, or social campaign, it must pass four objective tests:

1. **The 5-Second Scan Test:**
   * Can an outside researcher state the core claim within 5 seconds without reading paragraph text? Titles must be complete assertions (*"Labor Market Task Unbundling: Methodological Demand Shift"*), never passive topics (*"Bar Chart"*).
2. **Explicit Denominator Verification:**
   * Every quantitative figure must state its exact sample size and unit of analysis directly on the canvas (e.g., *"$n=2,500$ authentic job specifications"*). Unanchored percentages are strictly prohibited.
3. **Typographic Floor Audit:**
   * When viewed on a standard laptop display, body text must never fall below an effective 10 pt size. Values must sit cleanly *outside* bars (`textposition='outside'`) with zero border collisions.
4. **Provenance & Zero-Synthetic-Data Gate:**
   * Visualizations demonstrating data pipelines or spreadsheets must display authentic provenance anchors (e.g., SHA-256 hash digests, file names, or line numbers) verifying that no synthetic mock data was used.
