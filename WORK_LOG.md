# ATLAS Work Log

## 2026-04-20: Generic SDOH build + Windows CI + OneDrive distribution

### Completed
- Identified generic (non-GBI) ATLAS source as `gbi/ATLAS_v2.2/`; code was already generic but help text, default theme dictionary, sample data, and example tables were GBI/cash-transfer flavored
- Rebuilt default theme dictionary around Healthy People 2030 SDOH framework (10 themes grouped under 5 domains: Economic Stability, Education Access, Health Care Access, Neighborhood & Built Environment, Social & Community Context)
- Replaced GBI pilot sample CSV with CHNA-style focus group responses (preserves edge cases: empty row, typos, short response)
- Fixed `app.py` help text, stratifier examples, and data-format example table; rewrote User Guide Appendix F to use CHNA examples
- Stood up private GitHub repo `dphdame/atlas` with `.github/workflows/test-windows-install.yml` running on `windows-latest`
- Fixed Windows `cmd.exe` paren bug in `setup.bat` (`echo (...)` inside `if/else` closed block early, causing "... was unexpected at this time.")
- CI green on second run (2m3s): setup.bat clean, 10 imports verified, Streamlit health endpoint returned 200
- Exported clean distribution to `~/Downloads/ATLAS/` + `~/Downloads/ATLAS.zip`

### Files Modified
- `topic_modeling.py` — DEFAULT_THEME_DICTIONARY rewritten as SDOH-organized
- `app.py` — help text, stratifier examples, expected-data-format table
- `docs/ATLAS_User_Guide.md` — theme list regrouped by SDOH domain, Appendix F rewritten
- `data/test_sample.csv` — CHNA sample responses
- `setup.bat` — paren fix on two echo lines, error message wording
- `INSTALL.md` (renamed from INSTALL_WINDOWS.md) — generic folder name
- `README.md` — new, describes public-health framing and SDOH defaults
- `.gitignore`, `.github/workflows/test-windows-install.yml` — new

### Decisions Made
- **Granular 10-theme SDOH dict (Path B)** over 5-domain rollup — preserves existing keyword work, more actionable for qual researchers, SDOH framing applies at the parent level
- **Sample CSV = CHNA** over patient experience — broader public-health applicability
- **Distribution via OneDrive folder + zip** — GitHub repo is dev-only (private); users get a self-contained folder
- **New private repo `dphdame/atlas`** over orphan branch in `gbi/` — cleaner separation from the divergent `gbi` repo state
- **SSH remote for push** — HTTPS gh token lacked `workflow` scope; SSH uses local key
- **Kept `setup.bat` default to user-scope Python install** — no admin needed for "Install Now" path; only locked-down enterprise policy would trigger `_pip_helper.py` fallback

### Next Steps
- User to upload `~/Downloads/ATLAS/` (or `ATLAS.zip`) to OneDrive and share with team
- Collect actual failure modes from last attempted install (admin vs pip vs SmartScreen vs firewall) to decide whether `INSTALL.md` needs a "Install for me only" clarification or we ship portable Python
- If team hits the platformdirs group-policy crash, `_pip_helper.py` already patches it
- Optional: add `QUICKSTART.md` at folder root with the 5-step first-run flow for team members who skip `INSTALL.md`

### Extracted Artifacts
None this session.
