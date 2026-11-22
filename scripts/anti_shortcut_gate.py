#!/usr/bin/env python3
"""Slice-scoped mechanical anti-shortcut and repo-hygiene gate for ATLAS.

Note: AST/static checks block obvious shortcuts (skips, bare excepts, unbacked
study literals, stale binary figures, external URLs, subprocess escapes, missing
imports); live behavioral wiring must always be proved separately by functional
and browser tests.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path
import re
import sys


STRAY_DOCS = [
    "docs/elevenlabs_video_script.md",
    "docs/linkedin_announcement_sequence.md",
    "docs/ATLAS_Visual_Asset_and_Card_Design_System.md",
    "docs/tooearlytosay_methods_article.md",
    "docs/tooearlytosay_methods_article.html",
    "docs/atlas_v1.0.0.zip",
]

STALE_N2500_GIT_BLOB_PREFIXES = {
    "docs/figures/atlas_audit_bridge.png": "59c95f20",
    "docs/figures/atlas_codebook_context_fence.png": "3bf61bf7",
    "docs/figures/atlas_dashboard_ui_walkthrough.png": "52c36d53",
    "docs/figures/atlas_labor_market_distribution.png": "39f72ad1",
    "docs/ATLAS_Methodology_and_Reference_Manual.docx": "83fadc88",
    "docs/ATLAS_Methodology_and_Reference_Manual.pdf": "0fba6aa3",
    "docs/ATLAS_Practitioner_Field_Guide_Program_Evaluation.pdf": "97d151f3",
}

FORBIDDEN_UNBACKED_PATTERNS = [
    re.compile(r"\bn\s*=\s*2,?500\b", re.IGNORECASE),
    re.compile(r"\b2,?105\b"),
    re.compile(r"\b1,?912\b"),
    re.compile(r"\b1,?570\b"),
    re.compile(r"\b1,?285\b"),
    re.compile(r"\b1,?078\b"),
    re.compile(r"\bKII-0[1-9]\b"),
    re.compile(r"Turnover kills community trust", re.IGNORECASE),
    re.compile(r"/Users/"),
]

SKIP_DECORATOR_NAMES = {"skip", "skipIf", "skipUnless", "xfail", "expectedFailure"}
SKIP_CALL_SUFFIXES = (".skipTest", ".skip", ".xfail")
SKIP_CALL_EXACT = {"skip", "xfail", "pytest.skip", "pytest.xfail", "unittest.skip"}


def git_blob_sha1(path: Path) -> str:
    raw = path.read_bytes()
    header = f"blob {len(raw)}\0".encode("utf-8")
    return hashlib.sha1(header + raw).hexdigest()


def check_python_ast_prod(path: Path, errors: list[str]) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        errors.append(f"{path}: SyntaxError: {exc}")
        return

    for lineno, line in enumerate(source.splitlines(), 1):
        if re.search(r"#\s*(TODO|FIXME)\b", line):
            errors.append(f"{path}:{lineno}: contains TODO/FIXME comment")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = [alias.name for alias in node.names]
            for banned_mod in ("subprocess", "urllib", "requests", "httpx", "aiohttp"):
                if mod == banned_mod or mod.startswith(f"{banned_mod}.") or banned_mod in names:
                    errors.append(f"{path}:{node.lineno}: network/process module '{banned_mod}' forbidden in core ATLAS module")
        if isinstance(node, ast.Call):
            fn_src = ast.unparse(node.func)
            if fn_src in {"os.system", "os.popen"}:
                errors.append(f"{path}:{node.lineno}: shell execution '{fn_src}' forbidden in core ATLAS module")
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc_src = ast.unparse(node.exc)
            if "NotImplementedError" in exc_src:
                errors.append(f"{path}:{node.lineno}: raises NotImplementedError")
        if isinstance(node, ast.ExceptHandler):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass) and node.type is None:
                errors.append(f"{path}:{node.lineno}: bare 'except: pass' is forbidden")


def check_python_ast_tests(path: Path, errors: list[str]) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        errors.append(f"{path}: SyntaxError: {exc}")
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                dec_src = ast.unparse(dec)
                for bad in SKIP_DECORATOR_NAMES:
                    if re.search(rf"\b{bad}\b", dec_src):
                        errors.append(f"{path}:{node.lineno}: test skip/xfail decorator forbidden ({dec_src})")
        if isinstance(node, ast.Call):
            call_src = ast.unparse(node.func)
            if call_src in SKIP_CALL_EXACT or call_src.endswith(SKIP_CALL_SUFFIXES):
                errors.append(f"{path}:{node.lineno}: runtime skip/xfail call forbidden ({call_src})")
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc_src = ast.unparse(node.exc)
            if "SkipTest" in exc_src:
                errors.append(f"{path}:{node.lineno}: raising SkipTest is forbidden ({exc_src})")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = [alias.name for alias in node.names]
            if "unittest.mock" in mod or "mock" in names or "MagicMock" in names or "patch" in names:
                errors.append(f"{path}:{node.lineno}: mocking is forbidden in ATLAS test files ({path.as_posix()})")


def check_unbacked_literals(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        for pat in FORBIDDEN_UNBACKED_PATTERNS:
            if pat.search(line):
                errors.append(f"{path}:{lineno}: forbidden unbacked literal matching {pat.pattern!r}")


def check_app_wiring(app_path: Path, errors: list[str]) -> None:
    source = app_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(app_path))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    for req_mod in ("atlas_engine", "universal_transcript_parser", "atlas_discover"):
        if req_mod not in imported_modules:
            errors.append(f"{app_path}: missing required import of '{req_mod}'")

    for lineno, line in enumerate(source.splitlines(), 1):
        if re.search(r"https?://", line):
            for m in re.finditer(r"https?://([^\s\"')>]+)", line):
                host = m.group(1).split("/")[0].lower()
                if not (host.startswith("localhost") or host.startswith("127.0.0.1")):
                    errors.append(f"{app_path}:{lineno}: external URL forbidden in offline app ({m.group(0)})")
        if "../" in line or "..\\" in line:
            errors.append(f"{app_path}:{lineno}: parent-directory traversal ('../') forbidden in app.py")


def run_gate(repo: Path, slice_num: int) -> list[str]:
    errors: list[str] = []

    if slice_num == 0:
        if not (repo / "atlas_engine.py").exists():
            errors.append("Repository root missing atlas_engine.py")
        return errors

    lic = repo / "LICENSE"
    if not lic.is_file():
        errors.append("LICENSE file is missing")
    else:
        lic_txt = lic.read_text(encoding="utf-8")
        if "MIT License" not in lic_txt or "Victoria E. Cholette" not in lic_txt:
            errors.append("LICENSE missing 'MIT License' or 'Victoria E. Cholette'")

    req = repo / "requirements.txt"
    if not req.is_file():
        errors.append("requirements.txt is missing")
    else:
        req_txt = req.read_text(encoding="utf-8").lower()
        for pkg in ("python-docx", "pyarrow", "streamlit", "scikit-learn", "pyyaml", "openpyxl"):
            if pkg not in req_txt:
                errors.append(f"requirements.txt missing required package '{pkg}'")

    gitignore = repo / ".gitignore"
    if gitignore.is_file():
        gi_txt = gitignore.read_text(encoding="utf-8")
        if ".venv/" not in gi_txt and ".venv" not in gi_txt.splitlines():
            errors.append(".gitignore must ignore .venv/")

    for stray in STRAY_DOCS:
        if (repo / stray).exists():
            errors.append(f"Stray artifact still present: {stray}")

    data_dir = repo / "data"
    if data_dir.is_dir():
        for dfile in sorted(data_dir.rglob("*")):
            if dfile.is_file() and dfile.suffix.lower() in {".csv", ".txt", ".md", ".vtt", ".srt", ".yaml", ".yml"}:
                content = dfile.read_text(encoding="utf-8", errors="replace")
                if "SOFTWARE_TEST" not in content and "software_test" not in dfile.name.lower():
                    errors.append(f"{dfile.relative_to(repo)}: sample data file must carry explicit SOFTWARE_TEST label")
            elif dfile.is_file() and dfile.suffix.lower() in {".docx", ".xlsx"}:
                if "software_test" not in dfile.name.lower():
                    errors.append(f"{dfile.relative_to(repo)}: binary sample file name must include 'software_test'")

    tests_dir = repo / "tests"
    if not tests_dir.is_dir():
        errors.append("tests/ directory missing")
    else:
        py_tests = sorted(p for p in tests_dir.rglob("*.py") if "__pycache__" not in p.parts)
        if not py_tests:
            errors.append("No Python files found under tests/")
        for tfile in py_tests:
            check_python_ast_tests(tfile, errors)

    prod_files = [repo / "universal_transcript_parser.py"]
    if slice_num >= 2:
        prod_files.extend([repo / "atlas_engine.py", repo / "atlas_discover.py"])
    if slice_num >= 3:
        prod_files.append(repo / "app.py")

    for pfile in prod_files:
        if not pfile.is_file():
            errors.append(f"Required module missing for slice {slice_num}: {pfile.name}")
        else:
            check_python_ast_prod(pfile, errors)
            check_unbacked_literals(pfile, errors)

    if slice_num >= 3:
        app_path = repo / "app.py"
        if app_path.is_file():
            check_app_wiring(app_path, errors)

        for doc_md in [repo / "README.md", *sorted((repo / "docs").rglob("*.md")), *sorted((repo / "docs").rglob("*.html"))]:
            if doc_md.is_file():
                check_unbacked_literals(doc_md, errors)

        for rel_bin, stale_prefix in STALE_N2500_GIT_BLOB_PREFIXES.items():
            bpath = repo / rel_bin
            if bpath.is_file():
                blob_id = git_blob_sha1(bpath)
                if blob_id.startswith(stale_prefix):
                    errors.append(
                        f"{rel_bin}: still matches stale 9ec00d24 binary ({stale_prefix}) containing unbacked n=2,500 claims"
                    )

    if slice_num >= 4:
        wf = repo / ".github" / "workflows" / "test-windows-install.yml"
        if not wf.is_file():
            errors.append("Missing .github/workflows/test-windows-install.yml")
        else:
            wf_txt = wf.read_text(encoding="utf-8")
            if "setup.bat" in wf_txt or "spellchecker" in wf_txt or "wordcloud" in wf_txt:
                errors.append(".github/workflows/test-windows-install.yml still contains legacy setup.bat/wordcloud/spellchecker")
        if not (repo / "scripts" / "smoke_test.py").is_file():
            errors.append("Missing scripts/smoke_test.py")

    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".", help="Path to ATLAS repository root")
    ap.add_argument("--slice", type=int, required=True, choices=[0, 1, 2, 3, 4])
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    errors = run_gate(repo, args.slice)
    if errors:
        print(f"ANTI-SHORTCUT GATE FAILED (slice={args.slice}, {len(errors)} issue(s)):")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(f"ANTI-SHORTCUT GATE PASSED (slice={args.slice})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
