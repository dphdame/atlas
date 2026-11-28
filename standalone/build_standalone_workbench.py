#!/usr/bin/env python3
"""
Build the self-contained Zero-Install Browser Edition of ATLAS v1.2:
  - ATLAS_Workbench.html (double-click from synced OneDrive / desktop)
  - ATLAS_Workbench.aspx (identical copy for SharePoint Document Libraries)

Reads authoritative starter theme YAML files and built-in SOFTWARE_TEST sample
.docx fixtures directly from the ATLAS v1.2 repo so zero drift is possible.
"""

from __future__ import annotations

import base64
import json
import shutil
import sys
from pathlib import Path

import yaml

ATLAS_REPO = Path(__file__).resolve().parent.parent
STANDALONE_DIR = Path(__file__).resolve().parent
SRC_DIR = STANDALONE_DIR / "src"

sys.path.insert(0, str(ATLAS_REPO))
from atlas_engine import normalize_codebook_rules  # noqa: E402


def _load_normalized_yaml(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return normalize_codebook_rules(data)


def _embed_json(obj) -> str:
    # Escape `</` so no embedded string can prematurely close a `<script>` tag.
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def build() -> tuple[Path, Path]:
    core_themes = _load_normalized_yaml(ATLAS_REPO / "config" / "gbi_focus_group_starter.yaml")
    addon_themes = _load_normalized_yaml(ATLAS_REPO / "config" / "optional_delivery_addons.yaml")

    sample_dir = ATLAS_REPO / "data" / "samples"
    sample_names = [
        "software_test_gbi_group_treatment.docx",
        "software_test_gbi_group_control.docx",
    ]
    sample_files = []
    for name in sample_names:
        p = sample_dir / name
        sample_files.append({
            "name": name,
            "source_id": f"data/samples/{name}",
            "base64": base64.b64encode(p.read_bytes()).decode("ascii"),
        })

    css = (SRC_DIR / "styles.css").read_text(encoding="utf-8")
    parsers_js = (SRC_DIR / "parsers.js").read_text(encoding="utf-8")
    engine_js = (SRC_DIR / "engine.js").read_text(encoding="utf-8")
    exporters_js = (SRC_DIR / "exporters.js").read_text(encoding="utf-8")
    ui_js = (SRC_DIR / "ui.js").read_text(encoding="utf-8")

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ATLAS Qualitative Coding Workbench (Zero-Install Browser Edition v1.2)</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%230F172A'/%3E%3Ctext x='16' y='22' text-anchor='middle' font-family='system-ui,sans-serif' font-size='18' font-weight='700' fill='%23FFFFFF'%3EA%3C/text%3E%3C/svg%3E">
  <style>
{css}
  </style>
</head>
<body>
  <div id="atlas-app"></div>
  <script>
const ATLAS_CORE_THEMES = {_embed_json(core_themes)};
const ATLAS_ADDON_THEMES = {_embed_json(addon_themes)};
const ATLAS_SAMPLE_FILES = {_embed_json(sample_files)};

{parsers_js}

{engine_js}

{exporters_js}

{ui_js}
  </script>
</body>
</html>
"""
    html_path = STANDALONE_DIR / "ATLAS_Workbench.html"
    aspx_path = STANDALONE_DIR / "ATLAS_Workbench.aspx"
    html_path.write_text(html_out, encoding="utf-8")
    shutil.copy2(html_path, aspx_path)
    print(f"Built {html_path} ({html_path.stat().st_size:,} bytes)")
    print(f"Built {aspx_path} ({aspx_path.stat().st_size:,} bytes)")
    return html_path, aspx_path


if __name__ == "__main__":
    build()
