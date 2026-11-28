"""Regression tests ensuring the public ATLAS repository contains zero agency/local-path leakage."""

from __future__ import annotations

import hashlib
import re
import subprocess
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _decode(hex_str: str) -> str:
    return bytes.fromhex(hex_str).decode("utf-8")


# Hex-encoded patterns so every tracked file (including this test) can be scanned with zero skips.
BANNED_PATTERNS = [
    re.compile(_decode("7068645c2e736363676f76"), re.IGNORECASE),
    re.compile(_decode("7075626c69635c732b6865616c74685c732b6465706172746d656e74"), re.IGNORECASE),
    re.compile(_decode("73616e74615c732b636c617261"), re.IGNORECASE),
    re.compile(_decode("736363706864"), re.IGNORECASE),
    re.compile(_decode("736363676f76"), re.IGNORECASE),
    re.compile(_decode("736369656e63655c732b6272616e6368"), re.IGNORECASE),
    re.compile(r"/[Uu]sers/[^/\r\n\"'`|<>]+/", re.IGNORECASE),
    re.compile(r"[Cc]:\\[Uu]sers\\[^\\\r\n\"'`|<>]+\\", re.IGNORECASE),
]

OFFICE_ZIP_EXTENSIONS = {".docx", ".xlsx"}
BINARY_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf"}

CONTACT_FILES = [
    "README.md",
    "app.py",
    "docs/ATLAS_User_Guide.md",
    "docs/ATLAS_GBI_Analyst_Quick_Start.md",
    "standalone/src/ui.js",
    "standalone/ATLAS_Workbench.html",
    "standalone/ATLAS_Workbench.aspx",
    "docs/index.html",
]


def _scan_text(label: str, text: str, hits: list[str]) -> None:
    for pat in BANNED_PATTERNS:
        m = pat.search(text)
        if m:
            hits.append(f"{label}: matched {m.group(0)!r}")


class TestPublicPrivacyHygiene(unittest.TestCase):
    """Gate 1 & Gate 2: Zero agency/local-path references (all tracked text + Office ZIP XML) and byte-identical bundles."""

    def test_zero_agency_or_local_path_references_across_all_tracked_files_and_office_zips(self):
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=REPO_ROOT, text=True
        ).splitlines()
        self.assertGreater(len(tracked), 20)
        hits: list[str] = []
        for rel in tracked:
            path = REPO_ROOT / rel
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext in OFFICE_ZIP_EXTENSIONS:
                with zipfile.ZipFile(path) as zf:
                    for member in zf.namelist():
                        if member.lower().endswith((".xml", ".rels", ".txt")):
                            raw = zf.read(member).decode("utf-8", errors="ignore")
                            _scan_text(f"{rel}!{member}", raw, hits)
            elif ext in BINARY_IMAGE_EXTENSIONS:
                continue
            else:
                _scan_text(rel, path.read_text(encoding="utf-8", errors="ignore"), hits)
        head_msg = subprocess.check_output(
            ["git", "log", "-n", "1", "--format=%B"], cwd=REPO_ROOT, text=True
        )
        _scan_text("HEAD commit message", head_msg, hits)
        self.assertEqual(hits, [], "Forbidden agency/local references found:\n" + "\n".join(hits))

    def test_public_contact_attribution_uses_github_and_tooearlytosay(self):
        for rel in CONTACT_FILES:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("https://github.com/dphdame", text, f"{rel} missing GitHub handle URL")
            self.assertIn("@dphdame", text, f"{rel} missing @dphdame handle")
            self.assertIn("hello@tooearlytosay.com", text, f"{rel} missing hello@tooearlytosay.com")

    def test_hosted_browser_edition_has_local_privacy_notice_favicon_and_byte_parity(self):
        targets = [
            REPO_ROOT / "standalone" / "ATLAS_Workbench.html",
            REPO_ROOT / "standalone" / "ATLAS_Workbench.aspx",
            REPO_ROOT / "docs" / "index.html",
        ]
        digests = {}
        for p in targets:
            data = p.read_bytes()
            digests[p.name] = hashlib.sha256(data).hexdigest()
            text = data.decode("utf-8")
            self.assertIn("Runs 100% locally in your browser", text, f"{p} missing browser privacy banner")
            self.assertIn("never sent to GitHub", text, f"{p} missing zero-upload guarantee")
            self.assertIn('rel="icon"', text, f"{p} missing inline favicon (prevents GitHub Pages 404)")
        self.assertEqual(len(set(digests.values())), 1, f"Browser bundles diverged: {digests}")


if __name__ == "__main__":
    unittest.main()
