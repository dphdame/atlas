#!/usr/bin/env python3
"""Progressive 5-stage ATLAS smoke suite.

Every stage runs against a fresh copy of the repository in a temporary
directory, with every child process under the ATLAS offline guard
(scripts/offline_guard/sitecustomize.py, ATLAS_OFFLINE_GUARD=1,
ATLAS_NET_LOG=<tmp>/net_attempts.jsonl). Any blocked network call recorded in
the guard log fails the step, and the run fails unless the log is still empty
at the end.

Stage 1 (clean-temp copy and subprocess offline monitor):
  1. the copy holds no .git / .codex / thoughts and no path that resolves
     outside it
  2. guarded children block and log a DNS lookup, a sitecustomize-bypassing
     `python -I` launch and a curl launch

Stage 2 (launcher --check-only and broken-venv recovery):
  1. launcher --check-only (run.command on macOS/Linux, run.bat on Windows)
  2. in scratch directories holding only the launcher and requirements.txt, an
     empty .venv/ without the dependency marker, a .venv/ with a stale marker
     and a damaged interpreter, and a .venv/ with a stale marker and a real
     interpreter whose site initialization exits -1073741819 (0xC0000005) all
     take the rebuild path; with pip offline (PIP_NO_INDEX=1) the launcher fails
     fast and removes the incomplete .venv

Stage 3 (end-to-end multi-format CLI, reproducibility, tamper detection):
  a guarded child (this script with --pipeline-check DIR) writes SOFTWARE_TEST
  .docx (speaker labels, and a speakerless Teams export with a multiline turn
  and an interviewer prompt), .vtt, accented .txt (NFC/NFD marks, ligature,
  sharp s), same-basename .txt files in two folders and a multi-row .csv into
  DIR, then runs UniversalTranscriptParser -> atlas_discover ->
  AtlasEngine.export_results and checks denominators, verbatim spans, .xlsx
  audit comments, .parquet (pyarrow), provenance_manifest.json, semantic rerun
  identity and tamper detection by verify_workbook_integrity

Stage 4 (unit tests, AppTest and a real headless browser):
  1. python -m unittest discover -s tests
  2. a guarded child (this script with --app-check) drives app.py through
     streamlit.testing.v1.AppTest and compares the KPIs with AtlasEngine output
  3. `streamlit run app.py --server.headless=true` on a free loopback port in the
     copy, under the guard; a guarded child (this script with --browser-check)
     drives headless Playwright Chromium (PLAYWRIGHT_BROWSERS_PATH is honoured):
     zero non-local browser requests, zero uncaught page errors, SOFTWARE_TEST
     notice and engine-matching KPI cards on boot, a transcript upload whose KPI
     cards and domain table update to the engine's counts, and downloaded
     .xlsx / manifest files that carry audit stamps and pass
     verify_workbook_integrity, and a custom codebook whose domain names are
     Markdown (image, link, math, color directive) shown verbatim in both
     chart captions. The server is then stopped with a signal and must shut
     down by itself.
  Skipping the browser check needs an explicit --skip-playwright.

Stage 5 (anti-shortcut gate and codebook audit):
  1. scripts/anti_shortcut_gate.py --repo <copy> --slice 4
  2. a guarded child (this script with --codebook-audit) compiles every
     config/*.yaml codebook in AtlasEngine

The repository's provisioned .venv is reused (the guard blocks pip downloads by
design); provision it first with `run.command --check-only` and add Playwright
(`pip install playwright` + `python -m playwright install chromium`). The copy
gets its own real .venv (with a copy of the dependency marker) that reads the
shared site-packages through a .pth file, so a launcher or pip in the copy
installs, rewrites or deletes only the copy's environment. After every stage,
including a failed one, the run fails if any file's content or symlink target in
the shared .venv (bytecode caches aside) was added, removed or changed.

Usage: .venv/bin/python scripts/smoke_test.py [--max-stage 5] [--skip-playwright]
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
from urllib.parse import urlsplit
import urllib.request
import venv as venv_module


REPO = Path(__file__).resolve().parent.parent
COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "venv", ".codex", "thoughts", "__pycache__", "*.pyc", "*.pyo",
    ".pytest_cache", "output", "*.log", ".DS_Store",
)
EXCLUDED_FROM_COPY = (".git", ".codex", "thoughts", "venv")
IS_WINDOWS = os.name == "nt"
MARKER_NAME = ".atlas_deps.sha256"
NET_LOG_NAME = "net_attempts.jsonl"
SMOKE_SCRIPT = "scripts/smoke_test.py"


class StageFailure(Exception):
    pass


def venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def guarded_env(work: Path, net_log: Path) -> dict:
    env = dict(os.environ)
    guard_dir = str(work / "scripts" / "offline_guard")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{guard_dir}{os.pathsep}{existing}" if existing else guard_dir
    env["ATLAS_OFFLINE_GUARD"] = "1"
    env["ATLAS_NET_LOG"] = str(net_log)
    env["BROWSER"] = "true"
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # never write caches into the shared site-packages
    env.pop("ATLAS_NO_LAUNCH", None)
    return env


def read_log(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def run_step(name: str, argv: list[str], work: Path, env: dict, net_log: Path) -> None:
    print(f"\n--- {name}: {' '.join(argv)}", flush=True)
    before = len(read_log(net_log))
    proc = subprocess.run(argv, cwd=str(work), env=env, stdin=subprocess.DEVNULL)
    blocked = read_log(net_log)[before:]
    if blocked:
        for entry in blocked:
            print(f"    blocked network call: {entry[:300]}")
        raise StageFailure(f"{name}: {len(blocked)} network call(s) blocked by the offline guard")
    if proc.returncode != 0:
        raise StageFailure(f"{name}: exited {proc.returncode}")
    print(f"--- {name}: PASS", flush=True)


def _python_output(argv: list[str]) -> str:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(argv, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise StageFailure(f"preparing the smoke environment failed: {' '.join(argv)}\n{proc.stderr}")
    return proc.stdout.strip()


def copy_repo(src: Path, dst: Path) -> None:
    """
    Copy the working tree, keeping symlinks as links: a followed link would bring
    external content in as an ordinary file, while a kept one is rejected by
    copy_problems() when its target lies outside the copy.
    """
    shutil.copytree(src, dst, ignore=COPY_IGNORE, symlinks=True)


def prepare_copy(tmp: Path) -> Path:
    """
    Copy the repository and give the copy its own real virtual environment.
    The shared .venv's site-packages are appended to the copy's sys.path through a
    .pth file, so they are importable but never an install target: pip installs
    into the copy's own site-packages and refuses to uninstall anything outside
    the copy's environment.
    """
    shared_py = venv_python(REPO)
    if not shared_py.exists():
        raise StageFailure(f"{shared_py} not found; provision it with run.command --check-only (or run.bat)")
    work = tmp / "atlas"
    copy_repo(REPO, work)
    wrapper = work / ".venv"
    _python_output([str(shared_py), "-m", "venv", str(wrapper)])

    site_code = "import sysconfig; p = sysconfig.get_paths(); print(p['purelib']); print(p['platlib'])"
    shared_sites = list(dict.fromkeys(_python_output([str(shared_py), "-c", site_code]).splitlines()))
    own_site = Path(_python_output([str(venv_python(work)), "-c", site_code]).splitlines()[0])
    pth_lines = [f"import site; site.addsitedir({path!r})\n" for path in shared_sites]
    (own_site / "atlas_shared_site_packages.pth").write_text("".join(pth_lines), encoding="utf-8")

    marker = REPO / ".venv" / MARKER_NAME
    if marker.is_file():
        shutil.copy2(marker, wrapper / MARKER_NAME)
    return work


def venv_fingerprint(root: Path) -> dict:
    """
    Content identity of an environment tree: the SHA-256 of every regular file and
    the target of every symlink, keyed by POSIX path relative to root. Bytecode
    caches (__pycache__, *.pyc, *.pyo) are excluded; smoke children run with
    PYTHONDONTWRITEBYTECODE=1 so they do not write them.
    """
    files: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        entries = list(filenames) + [d for d in dirnames if (Path(dirpath) / d).is_symlink()]
        for name in sorted(entries):
            if name.endswith((".pyc", ".pyo")):
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                files[rel] = f"symlink:{os.readlink(path)}"
            else:
                files[rel] = sha256_file(path)
    return {"path": str(root), "files": files}


def sha256_file(path: Path) -> str:
    """Chunked SHA-256 of a file; works on Python 3.10 (no 3.11-only hashlib helpers)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_venv_fingerprint() -> dict:
    return venv_fingerprint(REPO / ".venv")


def venv_changes(before: dict, after: dict) -> list[str]:
    """Relative paths added, removed or changed in content between two fingerprints."""
    old, new = before["files"], after["files"]
    return sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path))


def shared_venv_problem(before: dict) -> str | None:
    changed = venv_changes(before, repo_venv_fingerprint())
    if not changed:
        return None
    shown = ", ".join(changed[:20]) + (f" (+{len(changed) - 20} more)" if len(changed) > 20 else "")
    return f"shared environment {before['path']} changed during the smoke run: {shown}"


def check_repo_venv_unchanged(before: dict) -> None:
    problem = shared_venv_problem(before)
    if problem:
        raise StageFailure(problem)


def verify_guard_active(work: Path, env: dict, tmp: Path) -> None:
    """The empty-log check is meaningful only if the guard really loads in children."""
    probe_log = tmp / "guard_probe.jsonl"
    probe_env = dict(env)
    probe_env["ATLAS_NET_LOG"] = str(probe_log)
    probe = "import socket; socket.getaddrinfo('atlas-guard-probe.invalid', 80)"
    print("\n--- offline guard probe", flush=True)
    proc = subprocess.run(
        [str(venv_python(work)), "-c", probe],
        cwd=str(work), env=probe_env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
    )
    if proc.returncode == 0 or not read_log(probe_log):
        raise StageFailure("offline guard probe: guard did not block a lookup; it is not active in child processes")
    print("--- offline guard probe: PASS (lookup blocked and logged)", flush=True)


def copy_problems(root: Path) -> list[str]:
    """
    Reasons the temp copy at root is not a clean, self-contained copy: a top-level
    directory that must be excluded, or any path (symlink or not) that resolves
    outside root. The copy's own .venv, created by prepare_copy after the copy,
    links to the base interpreter by design and is not walked.
    """
    root = Path(os.path.realpath(root))
    problems = [f"excluded directory copied: {name}" for name in EXCLUDED_FROM_COPY if (root / name).exists()]
    for dirpath, dirnames, filenames in os.walk(root):
        if Path(dirpath) == root:
            dirnames[:] = [d for d in dirnames if d != ".venv"]
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            resolved = Path(os.path.realpath(path))
            if resolved != root and root not in resolved.parents:
                problems.append(f"path escapes the copy: {path.relative_to(root).as_posix()} -> {resolved}")
    return problems


def probe_guard_blocks(name: str, code: str, expect_function: str, work: Path, env: dict, tmp: Path) -> None:
    """A guarded child running code must fail, with a blocked call to expect_function logged."""
    probe_log = tmp / f"guard_probe_{name.replace(' ', '_')}.jsonl"
    probe_env = dict(env, ATLAS_NET_LOG=str(probe_log))
    print(f"\n--- offline monitor probe ({name})", flush=True)
    proc = subprocess.run(
        [str(venv_python(work)), "-c", code],
        cwd=str(work), env=probe_env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
    )
    functions = [json.loads(line).get("function", "") for line in read_log(probe_log)]
    if proc.returncode == 0 or not any(fn.startswith(expect_function) for fn in functions):
        raise StageFailure(
            f"offline monitor probe ({name}): expected a blocked {expect_function} call, "
            f"got exit {proc.returncode} and log {functions}")
    print(f"--- offline monitor probe ({name}): PASS (blocked and logged: {expect_function})", flush=True)


def stage1(work: Path, env: dict, net_log: Path, tmp: Path) -> None:
    print(f"\n--- clean temp copy: {work}", flush=True)
    problems = copy_problems(work)
    if problems:
        raise StageFailure("clean temp copy: " + "; ".join(problems[:20]))
    print("--- clean temp copy: PASS (no .git/.codex/thoughts, no path outside the copy)", flush=True)
    print(f"    ATLAS_OFFLINE_GUARD={env['ATLAS_OFFLINE_GUARD']} ATLAS_NET_LOG={env['ATLAS_NET_LOG']}")
    print(f"    PYTHONPATH={env['PYTHONPATH']}", flush=True)
    verify_guard_active(work, env, tmp)
    probe_guard_blocks(
        "isolated python child", "import subprocess, sys; subprocess.run([sys.executable, '-I', '-c', 'pass'])",
        "subprocess.Popen(sitecustomize-bypass)", work, env, tmp)
    probe_guard_blocks(
        "curl child", "import subprocess; subprocess.run(['curl', '--version'])", "subprocess.Popen", work, env, tmp)


def launcher_argv() -> list[str]:
    return ["cmd", "/c", "run.bat", "--check-only"] if IS_WINDOWS else ["bash", "run.command", "--check-only"]


def broken_venv_scenarios() -> dict:
    """
    name -> function that damages a fresh scratch .venv in place. On every
    platform the launcher must recreate the environment from scratch in the same
    run; a reinstall into the damaged interpreter does not count as recovery.
    """
    def empty_venv(venv: Path) -> None:
        venv.mkdir()

    def stale_marker_damaged_python(venv: Path) -> None:
        exe = venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"SOFTWARE_TEST damaged interpreter, not a program\n")
        (venv / MARKER_NAME).write_text("0" * 64 + "\n", encoding="utf-8")

    def stale_marker_negative_exit_python(venv: Path) -> None:
        # A real interpreter whose site initialization exits with STATUS_ACCESS_VIOLATION
        # (0xC0000005): cmd.exe sees -1073741819, which `if errorlevel 1` treats as success.
        venv_module.create(venv, symlinks=not IS_WINDOWS, with_pip=False)
        exe = venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
        purelib = subprocess.check_output(
            [str(exe), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip()
        (Path(purelib) / "_atlas_neg_exit.pth").write_text("import os; os._exit(-1073741819)\n", encoding="utf-8")
        (venv / MARKER_NAME).write_text("0" * 64 + "\n", encoding="utf-8")

    return {"empty .venv without marker": empty_venv,
            "stale marker and damaged interpreter": stale_marker_damaged_python,
            "stale marker and negative-exit interpreter": stale_marker_negative_exit_python}


def broken_venv_check(work: Path, env: dict, net_log: Path, tmp: Path) -> None:
    """
    In scratch directories holding only the launcher files, a damaged .venv must
    take the rebuild path; with pip offline the launcher must fail fast, print
    the install error and remove the incomplete .venv (and its marker).
    """
    launcher_files = ["run.bat", "_pip_helper.py"] if IS_WINDOWS else ["run.command"]
    offline_env = dict(env, PIP_NO_INDEX="1", PIP_NO_CACHE_DIR="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    for idx, (name, damage) in enumerate(broken_venv_scenarios().items(), 1):
        scratch = tmp / f"launcher_recovery_{idx}"
        scratch.mkdir()
        for rel in [*launcher_files, "requirements.txt"]:
            shutil.copy2(work / rel, scratch / rel)
        damage(scratch / ".venv")
        print(f"\n--- broken-venv recovery ({name}): {' '.join(launcher_argv())} in {scratch}", flush=True)
        before = len(read_log(net_log))
        proc = subprocess.run(launcher_argv(), cwd=str(scratch), env=offline_env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        output = proc.stdout + proc.stderr
        blocked = read_log(net_log)[before:]
        problems = []
        if blocked:
            problems.append(f"{len(blocked)} network call(s) blocked by the offline guard")
        if proc.returncode == 0:
            problems.append("launcher exited 0 with no installable dependencies")
        if "Installing dependencies into local environment" not in output:
            problems.append("launcher did not take the provisioning path")
        if "Creating local isolated environment" not in output:
            problems.append("launcher did not recreate the damaged .venv")
        if "Dependency installation failed" not in output:
            problems.append("launcher did not report the failed install")
        if (scratch / ".venv").exists():
            problems.append("incomplete .venv was left behind")
        if problems:
            print(output[-3000:])
            raise StageFailure(f"broken-venv recovery ({name}): " + "; ".join(problems))
        print(f"--- broken-venv recovery ({name}): PASS (rebuilt, failed fast offline with exit "
              f"{proc.returncode}, incomplete .venv removed)", flush=True)


def stage2(work: Path, env: dict, net_log: Path, tmp: Path) -> None:
    run_step("launcher --check-only", launcher_argv(), work, env, net_log)
    broken_venv_check(work, env, net_log, tmp)


# ----------------------------------------------------------------------
# Stage 3: multi-format pipeline (runs inside a guarded child process)
# ----------------------------------------------------------------------
NFC = lambda text: unicodedata.normalize("NFC", text)  # noqa: E731
NFD_PROTECCION = "protecc" + "ió" + "n laboral"

SMOKE_CODEBOOK = {
    "project": "SOFTWARE_TEST Smoke Codebook",
    "domains": [
        {"id": "PROTECCION", "name": "Job protection", "roots_es": [NFC("protección laboral")],
         "roots_en": ["job protection"], "context_fences": ["trabajo", "permiso", "leave", "job"]},
        {"id": "CHILDCARE", "name": "Childcare access", "roots_en": ["childcare"],
         "exclude_fences": ["not a problem"], "exclude_window": 3},
        {"id": "TRANSIT", "name": "Transit barriers", "keywords": ["bus", "transit"]},
    ],
}
# (domain_id) -> (documents_reporting, matching_turns). 11 units = 8 transcripts (including
# one with only facilitator turns and one that parses to no turns) + 3 CSV respondent rows;
# the blank CSV row and the CSV interviewer-prompt row are not respondents.
SMOKE_EXPECTED_TOTAL = 11
SMOKE_PARTICIPANT_ONLY_UNITS = 9
SMOKE_FACILITATOR_TURNS = 5  # 3 Moderator turns + the speakerless .docx prompt + the CSV prompt row
PROMPT_PATTERNS = [r"^PROMPT:"]
SMOKE_EXPECTED = {"PROTECCION": (1, 3), "CHILDCARE": (2, 2), "TRANSIT": (4, 4)}
# Speakerless Teams-style .docx: each paragraph is a timestamp, then line breaks and the text.
TEAMS_DOCX = "software_test_teams_export.docx"
TEAMS_PROMPT = "PROMPT: Does the bus or transit schedule work for you?"
TEAMS_MULTILINE = ("The bus comes once an hour.", "The transit pass costs more now.")
ACCENTED_LINES = [
    ("Trabajadora A", NFC("Perdí la protección laboral cuando pedí permiso en el trabajo.")),
    ("Trabajadora B", "Perdí la " + NFD_PROTECCION + " durante el permiso."),
    ("Trabajadora C", NFC("The ﬁnancial leave ended; luego se agotó el beneficio at my job.")),
    ("Trabajadora D", NFC("Die Straße war lang; perdí la protección laboral en el trabajo.")),
]
TABULAR_OPTIONS = {"text_col": "response", "id_col": "respondent_id"}
EMPTY_TRANSCRIPT = "software_test_empty.txt"


def write_pipeline_fixtures(corpus: Path) -> list[Path]:
    """SOFTWARE_TEST inputs: they demonstrate software mechanics only, not findings."""
    import docx  # python-docx
    from universal_transcript_parser import SOFTWARE_TEST_BANNER

    def write(rel: str, text: str) -> Path:
        path = corpus / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    files = []
    document = docx.Document()
    document.add_paragraph(SOFTWARE_TEST_BANNER)
    document.add_paragraph("Moderator: Does the bus work for you?")
    document.add_paragraph("Respondent C: The bus is late and transit fares went up.")
    docx_path = corpus / "software_test_session.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(docx_path))
    files.append(docx_path)

    teams = docx.Document()
    teams.add_paragraph(SOFTWARE_TEST_BANNER)
    teams.add_paragraph("\n0:00\n" + TEAMS_PROMPT)
    teams.add_paragraph("\n0:05\n" + "\n".join(TEAMS_MULTILINE))
    teams.save(str(corpus / TEAMS_DOCX))
    files.append(corpus / TEAMS_DOCX)

    files.append(write("software_test_session.vtt", (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:05.000\n<v Moderator>How do you get to the clinic?</v>\n\n"
        "00:00:06.000 --> 00:00:10.000\n<v Respondent D>I take the bus, and the schedule changed.</v>\n"
    )))
    files.append(write("software_test_accented.txt",
                       SOFTWARE_TEST_BANNER + "\n" + "".join(f"{spk}: {text}\n" for spk, text in ACCENTED_LINES)))
    files.append(write("dir_a/interview.txt",
                       SOFTWARE_TEST_BANNER + "\nRespondent A: We could not find childcare near the clinic.\n"))
    files.append(write("dir_b/interview.txt",
                       SOFTWARE_TEST_BANNER + "\nRespondent B: Childcare is not a problem for us.\n"))
    files.append(write("software_test_facilitator_only.txt",
                       SOFTWARE_TEST_BANNER + "\nModerator: Does the bus stop near your clinic?\n"))
    files.append(write(EMPTY_TRANSCRIPT, SOFTWARE_TEST_BANNER + "\n"))
    files.append(write("software_test_survey.csv", (
        f"# {SOFTWARE_TEST_BANNER}\n"
        "respondent_id,response\n"
        "R01,Childcare costs more than rent.\n"
        "R02,The bus was late.\n"
        "R03,   \n"
        "R04,Nothing else to add.\n"
        "R05,PROMPT: Does the bus or childcare matter most?\n"
    )))
    return files


def pipeline_check(scratch: Path) -> list[str]:
    """Run the Stage 2 pipeline in scratch; return a list of failed checks."""
    sys.path.insert(0, str(REPO))
    import openpyxl
    import pandas as pd
    import pyarrow.parquet
    import yaml
    import atlas_discover
    from atlas_engine import AtlasEngine, fold_accents
    from universal_transcript_parser import TABULAR_EXTENSIONS, UniversalTranscriptParser

    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        print(f"    [{'ok' if condition else 'FAIL'}] {label}" + (f": {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(f"{label}{': ' + detail if detail else ''}")

    corpus = scratch / "corpus"
    files = write_pipeline_fixtures(corpus)
    paths = [str(p) for p in files]
    codebook_path = scratch / "software_test_smoke_codebook.yaml"
    with open(codebook_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(SMOKE_CODEBOOK, fh, allow_unicode=True, sort_keys=False)

    # 1. UniversalTranscriptParser over every format
    parser = UniversalTranscriptParser(facilitator_names=["Moderator"], interviewer_prompt_patterns=PROMPT_PATTERNS,
                                       root_dir=str(corpus))
    turns, file_hashes = [], {}
    for path in files:
        if path.suffix.lower() in TABULAR_EXTENSIONS:
            parsed = parser.parse_tabular(str(path), **TABULAR_OPTIONS)
        else:
            parsed = parser.parse_file(str(path))
        check(f"parsed {path.relative_to(corpus).as_posix()}", bool(parsed) != (path.name == EMPTY_TRANSCRIPT))
        check(f"no banner turns in {path.relative_to(corpus).as_posix()}", not any("SOFTWARE_TEST" in t["text"] for t in parsed))
        file_hashes[path.relative_to(corpus).as_posix()] = sha256_file(path)
        turns.extend(parsed)
    participants = [t for t in turns if not t["is_facilitator"]]
    check("facilitator and prompt turns flagged", sum(t["is_facilitator"] for t in turns) == SMOKE_FACILITATOR_TURNS,
          str(sum(t["is_facilitator"] for t in turns)))
    teams_turns = [t for t in turns if t["source_id"] == TEAMS_DOCX]
    check("speakerless .docx prompt excluded by pattern",
          [(t["text"], t["is_facilitator"], t.get("exclusion_reason")) for t in teams_turns if t["is_facilitator"]]
          == [(TEAMS_PROMPT, True, f"matched_prompt_pattern:{PROMPT_PATTERNS[0]}")], repr(teams_turns))
    teams_answers = [t["text"] for t in teams_turns if not t["is_facilitator"]]
    check("speakerless .docx multiline turn keeps every line",
          len(teams_answers) == 1 and all(line in teams_answers[0] for line in TEAMS_MULTILINE), repr(teams_answers))
    check("accented text kept verbatim",
          [t["text"] for t in turns if t["speaker"].startswith("Trabajadora")] == [x for _, x in ACCENTED_LINES])

    # 2. atlas_discover: deterministic topics and a compilable codebook draft
    disc = atlas_discover.discover_topics(turns, n_topics=3, random_state=42)
    disc_again = atlas_discover.discover_topics(turns, n_topics=3, random_state=42)
    check("discovery analyzed every participant turn", disc["n_analyzed"] == len(participants),
          f"{disc['n_analyzed']} vs {len(participants)}")
    check("discovery found topics", len(disc["topics"]) == 3)
    check("discovery is reproducible", disc == disc_again)
    discovered = atlas_discover.topics_to_codebook_dict(disc, project_name="SOFTWARE_TEST Discovered")
    discovered_path = scratch / "software_test_discovered_codebook.yaml"
    with open(discovered_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(discovered, fh, allow_unicode=True, sort_keys=False)
    disc_engine = AtlasEngine(str(discovered_path))
    disc_results = disc_engine.process_corpus(paths, facilitator_names=["Moderator"], root_dir=str(corpus),
                                              interviewer_prompt_patterns=PROMPT_PATTERNS,
                                              tabular_options=TABULAR_OPTIONS)
    check("discovered codebook compiles and matches", len(disc_engine.compiled_rules) == 3
          and not disc_results["quotes_df"].empty)

    # 3. AtlasEngine: denominators, spans, exports
    def run(out_name: str):
        engine = AtlasEngine(str(codebook_path))
        res = engine.process_corpus(paths, facilitator_names=["Moderator"], root_dir=str(corpus),
                                    interviewer_prompt_patterns=PROMPT_PATTERNS, tabular_options=TABULAR_OPTIONS)
        out = scratch / out_name
        engine.export_results(res, str(out))
        return engine, res, out

    engine, results, out = run("export_1")
    check("file_hashes keyed by relative source_id", results["file_hashes"] == file_hashes,
          f"{sorted(results['file_hashes'])}")
    check("same-basename files kept apart",
          {"dir_a/interview.txt", "dir_b/interview.txt"} <= set(results["file_hashes"]))
    check("total_documents counts units", results["total_documents"] == SMOKE_EXPECTED_TOTAL,
          str(results["total_documents"]))
    participant_units = {t["unit_id"] for t in participants}
    check("facilitator-only and empty transcripts stay in the denominator",
          len(participant_units) == SMOKE_PARTICIPANT_ONLY_UNITS
          and {"software_test_facilitator_only.txt", EMPTY_TRANSCRIPT} <= set(results["file_hashes"])
          and not participant_units & {"software_test_facilitator_only.txt", EMPTY_TRANSCRIPT})
    freq = results["frequencies_df"].set_index("domain_id")
    for dom_id, (docs, matched) in SMOKE_EXPECTED.items():
        got = (int(freq.loc[dom_id, "documents_reporting"]), int(freq.loc[dom_id, "matching_turns"]))
        check(f"{dom_id} documents/turns", got == (docs, matched), f"{got} != {(docs, matched)}")
        check(f"{dom_id} prevalence", float(freq.loc[dom_id, "prevalence_pct"])
              == round(docs / SMOKE_EXPECTED_TOTAL * 100, 1))
    via_turns = engine.process_turns(turns, file_hashes)
    check("process_turns equals process_corpus", via_turns["frequencies_df"].equals(results["frequencies_df"]))

    quotes = results["quotes_df"]
    prot = quotes[quotes["domain_id"] == "PROTECCION"]
    spans = [q["text"][int(q["match_char_start"]):int(q["match_char_end"])] for _, q in prot.iterrows()]
    check("accented spans are verbatim", all(fold_accents(s).lower() == "proteccion laboral" for s in spans)
          and NFD_PROTECCION in spans and NFC("protección laboral") in spans, repr(spans))
    check("CHILDCARE exclusion fence applied", "dir_b/interview.txt" not in set(
        quotes.loc[quotes["domain_id"] == "CHILDCARE", "source_id"]))

    pq = pd.read_parquet(out / "verbatim_quotes_inventory.parquet")
    check("parquet round-trips quote inventory", pq.reset_index(drop=True).equals(quotes.reset_index(drop=True)))
    arrow = pyarrow.parquet.read_table(out / "verbatim_quotes_inventory.parquet")
    check("pyarrow reads the parquet schema and rows",
          arrow.num_rows == len(quotes) and arrow.column_names == list(quotes.columns),
          f"{arrow.num_rows} rows, {arrow.column_names}")
    with open(out / "provenance_manifest.json", encoding="utf-8") as fh:
        manifest = json.load(fh)
    check("manifest binds file hashes", manifest["file_hashes"] == file_hashes)
    check("manifest totals", manifest["total_documents"] == SMOKE_EXPECTED_TOTAL)
    ws = openpyxl.load_workbook(out / "actuarial_parameter_matrix.xlsx")["Empirical Frequencies"]
    comments_ok = all(
        ws.cell(row=i, column=5).comment is not None
        and dom["audit_sha256"] in ws.cell(row=i, column=5).comment.text
        for i, dom in enumerate(manifest["domains"], 2)
    )
    check("xlsx prevalence cells carry manifest digests", comments_ok and ws.max_row - 1 == len(manifest["domains"]))

    # 4. Semantic rerun equality
    _, results_2, out_2 = run("export_2")
    check("rerun frequencies_df identical", results_2["frequencies_df"].equals(results["frequencies_df"]))
    check("rerun quotes_df identical", results_2["quotes_df"].equals(results["quotes_df"]))
    for name in ("thematic_frequencies.csv", "verbatim_quotes_inventory.csv"):
        check(f"rerun {name} byte-identical", (out / name).read_bytes() == (out_2 / name).read_bytes())
    with open(out_2 / "provenance_manifest.json", encoding="utf-8") as fh:
        manifest_2 = json.load(fh)
    strip = lambda m: {k: v for k, v in m.items() if k != "exported_at_utc"}  # noqa: E731
    check("rerun manifest equal apart from timestamp", strip(manifest) == strip(manifest_2))

    # 5. Integrity verification and tamper detection
    xlsx, manifest_path = out / "actuarial_parameter_matrix.xlsx", out / "provenance_manifest.json"
    ok, reasons = AtlasEngine.verify_workbook_integrity(str(xlsx), str(manifest_path))
    check("untouched workbook verifies", (ok, reasons) == (True, []), "; ".join(reasons))
    tampers = (
        ("prevalence", 5, lambda v: v + 5.0),
        ("reporting count", 3, lambda v: v + 1),
        ("domain name", 2, lambda v: v + " (edited)"),
        ("empirical statement", 7, lambda v: v.replace("% of documents", "% of all documents")),
    )
    for label, column, edit in tampers:
        wb = openpyxl.load_workbook(xlsx)
        cell = wb["Empirical Frequencies"].cell(row=2, column=column)
        cell.value = edit(cell.value)
        tampered = scratch / f"tampered_{column}.xlsx"
        wb.save(tampered)
        ok, reasons = AtlasEngine.verify_workbook_integrity(str(tampered), str(manifest_path))
        check(f"tampered {label} cell detected", not ok and bool(reasons))

    # 5b. Malformed manifests are reported, never raised
    def verify_safely(xlsx_path: Path, manifest_obj) -> tuple:
        path = scratch / "software_test_malformed_manifest.json"
        path.write_text(json.dumps(manifest_obj), encoding="utf-8")
        try:
            return AtlasEngine.verify_workbook_integrity(str(xlsx_path), str(path))
        except Exception as exc:  # the contract is (False, reasons), so any raise is a failure
            return "raised", [f"{type(exc).__name__}: {exc}"]

    def mutated(edit):
        copy = json.loads(json.dumps(manifest))
        edit(copy)
        return copy

    malformed = {
        "nonnumeric total_documents": mutated(lambda m: m.update(total_documents="ten")),
        "boolean total_turns_parsed": mutated(lambda m: m.update(total_turns_parsed=True)),
        "manifest is a list": [manifest],
        "non-string file hash": mutated(lambda m: m["file_hashes"].update({"dir_a/interview.txt": 7})),
        "domains not a list": mutated(lambda m: m.update(domains={"x": 1})),
        "domain entry not an object": mutated(lambda m: m["domains"].__setitem__(0, "PROTECCION")),
        "domain missing counts": mutated(lambda m: m["domains"][0].pop("matching_turns")),
        "string domain count": mutated(lambda m: m["domains"][0].update(documents_reporting="1")),
    }
    for label, bad_manifest in malformed.items():
        ok, reasons = verify_safely(xlsx, bad_manifest)
        check(f"malformed manifest ({label}) reported", ok is False and bool(reasons), f"{ok}: {reasons[:2]}")

    # 5c. Impossible counts fail even when workbook and manifest are forged consistently
    def forged_export(name: str, docs: int, total: int, turns: int):
        forged = dict(results)
        freq_df = results["frequencies_df"].copy()
        prev = round((docs / total * 100.0) if total > 0 else 0.0, 1)
        freq_df.loc[0, ["documents_reporting", "total_documents", "matching_turns", "prevalence_pct"]] = [
            docs, total, turns, prev]
        freq_df.loc[0, "reporting_statement"] = (
            f"{prev}% of documents ({docs} of {total}) across {turns} matching turns reported "
            f"{str(freq_df.loc[0, 'domain_name']).lower()}.")
        forged.update(frequencies_df=freq_df)
        if total != results["total_documents"]:
            forged.update(total_documents=total)
            freq_df["total_documents"] = total
        out_dir = scratch / name
        engine.export_results(forged, str(out_dir))
        return AtlasEngine.verify_workbook_integrity(
            str(out_dir / "actuarial_parameter_matrix.xlsx"), str(out_dir / "provenance_manifest.json"))

    total = SMOKE_EXPECTED_TOTAL
    impossible = {
        "documents_reporting > total_documents": (total + 2, total, total + 2),
        "negative documents_reporting": (-1, total, 0),
        "documents_reporting > matching_turns": (3, total, 1),
        "matching turns without reporting documents": (0, total, 2),
        "matching_turns > participant turns": (2, total, len(participants) + 1),
    }
    for label, (docs, tot, turns) in impossible.items():
        ok, reasons = forged_export(f"forged_{label.split()[0]}_{docs}_{turns}", docs, tot, turns)
        check(f"consistently forged {label} rejected", ok is False and bool(reasons), "; ".join(reasons[:2]))
    ok, reasons = forged_export("forged_control", 2, total, 4)
    check("consistently forged possible counts still verify (control)", (ok, reasons) == (True, []),
          "; ".join(reasons[:2]))

    # 6. Token windows must be nonnegative whole numbers
    def window_codebook(value):
        path = scratch / "software_test_window_codebook.yaml"
        rule = {"id": "W", "name": "Window", "roots_en": ["bus"], "context_fences": ["late"], "context_window": value}
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"project": "SOFTWARE_TEST Windows", "domains": [rule]}, fh, sort_keys=False)
        return str(path)

    for bad in (-1, 1.9, "-1", "8 tokens", True):
        try:
            AtlasEngine(window_codebook(bad))
            rejected = False
        except ValueError:
            rejected = True
        check(f"window {bad!r} rejected", rejected)
    for good, expected in ((0, 0), (8, 8), (8.0, 8), ("8", 8)):
        compiled = AtlasEngine(window_codebook(good)).compiled_rules[0]["context_window"]
        check(f"window {good!r} accepted", compiled == expected, repr(compiled))
    return failures


def stage3(work: Path, env: dict, net_log: Path, tmp: Path) -> None:
    py = str(venv_python(work))
    scratch = tmp / "stage3_pipeline"
    run_step("pipeline check", [py, SMOKE_SCRIPT, "--pipeline-check", str(scratch)], work, env, net_log)


# ----------------------------------------------------------------------
# Stage 4a: live-wired workbench through AppTest (runs inside a guarded child)
# ----------------------------------------------------------------------
APP_UPLOAD_CSV = (
    "response_id,participant_id,response\n"
    "RID-01,P-01,\"Cuando se agotó el beneficio, busqué otro trabajo.\"\n"
    "RID-02,P-02,The evening bus schedule made clinic visits hard.\n"
    "RID-03,P-03,Paperwork for the caseworker took two weeks.\n"
    "RID-04,P-04,Childcare costs went up after the rent increase.\n"
)


def app_check() -> list[str]:
    """
    Drive app.py through streamlit.testing.v1.AppTest, mutating every sidebar
    control and the topic controls, and compare the rendered KPIs with
    AtlasEngine output computed here on the same SOFTWARE_TEST inputs.
    """
    sys.path.insert(0, str(REPO))
    import pandas as pd
    from streamlit.testing.v1 import AppTest
    from atlas_engine import AtlasEngine

    failures: list[str] = []
    samples, config = REPO / "data" / "samples", REPO / "config"

    def check(label: str, condition: bool, detail: str = "") -> None:
        print(f"    [{'ok' if condition else 'FAIL'}] {label}" + (f": {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(f"{label}{': ' + detail if detail else ''}")

    def widget(at, accessor: str, label: str):
        return next((w for w in getattr(at, accessor) if w.label == label), None)

    def metrics(at) -> dict:
        return {m.label: float(str(m.value).replace(",", "")) for m in at.metric}

    def expected(codebook: str, files, options=None) -> dict:
        res = AtlasEngine(str(config / codebook)).process_corpus(
            [str(f) for f in files], root_dir=str(REPO), tabular_options=options)
        freq = res["frequencies_df"]
        return {
            "Analytical Units (N)": float(res["total_documents"]),
            "Participant Turns": float(res["participant_turns_analyzed"]),
            "Active Domains": float(len(freq)),
            "Matched Turn Mentions": float(freq["matching_turns"].sum()),
        }

    def no_exceptions(at, context: str) -> None:
        check(f"{context}: no exceptions", len(at.exception) == 0, str([e.value for e in at.exception]))

    def select(at, label: str, needle: str) -> None:
        box = widget(at, "selectbox", label)
        option = next((o for o in (box.options if box else []) if needle in str(o)), None)
        check(f"{label!r} offers {needle!r}", option is not None)
        if option is not None:
            box.set_value(option)
            at.run()

    at = AppTest.from_file(str(REPO / "app.py"), default_timeout=60)
    at.run()
    no_exceptions(at, "boot")
    check("SOFTWARE_TEST notice on boot", any("SOFTWARE_TEST" in str(i.value) for i in at.info))
    bilingual = [samples / "software_test_bilingual_interview.txt", samples / "software_test_zoom_session.vtt"]
    check("boot KPIs match engine (bilingual x pfl)",
          metrics(at) == expected("pfl_case_study_codebook.yaml", bilingual), str(metrics(at)))

    survey_opts = {"text_col": "response", "id_col": "respondent_id", "speaker_col": "role"}
    select(at, "Corpus Dataset", "Survey")
    for codebook in ("pfl_case_study_codebook.yaml", "intake_and_enrollment.yaml", "sdoh_basic_needs.yaml"):
        select(at, "Active YAML Codebook", codebook)
        no_exceptions(at, f"survey x {codebook}")
        check(f"survey x {codebook}: KPIs match engine",
              metrics(at) == expected(codebook, [samples / "software_test_survey.csv"], survey_opts),
              str(metrics(at)))

    select(at, "Corpus Dataset", "DOCX")
    select(at, "Active YAML Codebook", "intake_and_enrollment.yaml")
    no_exceptions(at, "docx x intake")
    check("docx x intake: KPIs match engine",
          metrics(at) == expected("intake_and_enrollment.yaml", [samples / "software_test_teams_multiline.docx"]),
          str(metrics(at)))

    slider = next((s for s in at.slider if "topic" in str(s.label).lower()), None)
    check("topic-count slider rendered", slider is not None)
    if slider is not None:
        slider.set_value(2)
        at.run()
        no_exceptions(at, "topic slider = 2")
        apply = next((b for b in at.button if "Apply Discovered Codebook" in str(b.label)), None)
        check("apply-discovered-codebook button rendered", apply is not None)
        if apply is not None:
            apply.click()
            at.run()
            no_exceptions(at, "apply discovered codebook")
            active = str(widget(at, "selectbox", "Active YAML Codebook").value)
            check("discovered codebook becomes active", active.startswith("Discovered:"), active)
            domains = metrics(at).get("Active Domains", 0.0)
            check("discovered codebook drives the engine", 1.0 <= domains <= 2.0, str(domains))

    select(at, "Corpus Dataset", "Upload")
    uploader = next((u for u in at.file_uploader if ".csv" in (u.allowed_type or [])), None)
    check("file uploader accepts .csv", uploader is not None)
    if uploader is not None:
        uploader.set_value(("software_test_app_upload.csv", APP_UPLOAD_CSV.encode("utf-8"), "text/csv"))
        at.run()
        select(at, "Active YAML Codebook", "pfl_case_study_codebook.yaml")
        no_exceptions(at, "uploaded csv")
        text_box = widget(at, "selectbox", "Text column (free-text responses)")
        check("text column auto-detected as 'response'", text_box is not None and text_box.value == "response",
              str(text_box.value if text_box else None))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "software_test_app_upload.csv"
            path.write_text(APP_UPLOAD_CSV, encoding="utf-8")
            want = expected("pfl_case_study_codebook.yaml", [path], {"text_col": "response"})
        check("uploaded csv: KPIs match engine", metrics(at) == want, f"{metrics(at)} != {want}")
        frames = [f.value for f in at.dataframe if isinstance(f.value, pd.DataFrame)]
        check("uploaded csv: matched quote rendered",
              any("busqué otro trabajo" in str(v) for fr in frames for v in fr.astype(str).to_numpy().ravel()))

    # Uploads with no usable text column must stop with a validation error, never
    # fall back to an id column or to the parser's default "response" column.
    # Each case: (tables, text column to force in the selector or None, selector expected?).
    rejected_uploads = {
        "id-only table": (
            [("software_test_ids_only.csv", "id,respondent_id\nA-1,R-1\nA-2,R-2\n")], None, False),
        "tables with no shared column": (
            [("software_test_left.csv", "respondent_id,comment\nR-1,The bus was late.\n"),
             ("software_test_right.csv", "case_id,note\nC-1,Paperwork took weeks.\n")], None, False),
        "shared headers, different populated text columns": (
            [("software_test_resp.csv",
              "respondent_id,comment,response\nR-1,,The evening bus schedule made clinic visits hard.\n"
              "R-2,,Paperwork for the caseworker took two weeks.\n"),
             ("software_test_comm.csv",
              "respondent_id,comment,response\nR-3,Childcare costs went up after the rent increase.,\n"
              "R-4,Cuando se agotó el beneficio busqué otro trabajo.,\n")], None, False),
        "chosen text column empty in one table": (
            [("software_test_noted.csv",
              "respondent_id,response,note\nR-1,The evening bus schedule made clinic visits hard.,ok\n"),
             ("software_test_unnoted.csv",
              "respondent_id,response,note\nR-2,Paperwork for the caseworker took two weeks.,\n")], "note", True),
    }
    for case, (tables, force_col, selector_expected) in rejected_uploads.items():
        at = AppTest.from_file(str(REPO / "app.py"), default_timeout=60)
        at.run()
        select(at, "Corpus Dataset", "Upload")
        uploader = next((u for u in at.file_uploader if ".csv" in (u.allowed_type or [])), None)
        if uploader is None:
            check(f"{case}: file uploader rendered", False)
            continue
        uploader.set_value([(name, body.encode("utf-8"), "text/csv") for name, body in tables])
        at.run()
        text_box = widget(at, "selectbox", "Text column (free-text responses)")
        if force_col is not None and text_box is not None:
            check(f"{case}: detection agrees on 'response' before override", text_box.value == "response",
                  str(text_box.value))
            check(f"{case}: agreeing tables are analysed before override",
                  len(at.error) == 0 and len(at.metric) == 4, f"{len(at.error)} errors, {len(at.metric)} metrics")
            text_box.set_value(force_col)
            at.run()
            text_box = widget(at, "selectbox", "Text column (free-text responses)")
        no_exceptions(at, case)
        check(f"{case}: validation error shown", len(at.error) == 1, str([e.value for e in at.error]))
        check(f"{case}: no analysis run", len(at.metric) == 0 and len(at.dataframe) == 0,
              f"{len(at.metric)} metrics, {len(at.dataframe)} tables rendered")
        check(f"{case}: text-column selector {'shown' if selector_expected else 'not offered'}",
              (text_box is not None) == selector_expected, str(text_box.options if text_box else None))
    return failures


# ----------------------------------------------------------------------
# Stage 4b: real headless browser against `streamlit run` (guarded child)
# ----------------------------------------------------------------------
BROWSER_UPLOAD_NAME = "software_test_browser_upload.txt"
BROWSER_UPLOAD_LINES = [
    "Respondent A: Cuando se agotó el beneficio, perdí la protección laboral en el trabajo.",
    "Respondent B: The EDD portal kept rejecting my claim.",
    "Respondent C: My manager was fine with the schedule.",
]
UPLOAD_OPTION = re.compile(r"^Upload Custom Files")
CODEBOOK_UPLOAD_OPTION = "Upload Custom Codebook (.yaml)"
# Domain names a custom codebook can carry. Streamlit's Markdown and shortcode plugins would
# turn them into an image, logo, icon, link, math, color or emphasis; the st.html chart
# summaries must display each one verbatim.
MARKDOWN_DOMAINS = {
    "portal": "Transit ![marker](https://example.invalid/pixel.png) :streamlit:",
    "schedule": ("Housing :material_home: Income >= poverty line [link](https://example.invalid/a) "
                 "www.example.invalid someone@example.invalid $x+y$ :red[alert] :smile: *emph* <b>bold</b>"),
}
SUMMARY_SELECTOR = '[data-testid="stHtml"] p.atlas-chart-summary'
SUMMARY_MARKUP = 'img, [role="img"], a, b, em, strong, code, .katex, [style*="color"], script'
MARKDOWN_CODEBOOK_NAME = "software_test_markdown_domains.yaml"
KPI_LABELS = ("Analytical Units (N)", "Participant Turns", "Active Domains", "Matched Turn Mentions")
AUDIT_STAMP = "ATLAS VERIFICATION AUDIT STAMP"
UI_WAIT_SECONDS = 90


def is_local_request_url(url: str) -> bool:
    """
    True for browser requests that stay on this machine: http(s)/ws(s) to a
    loopback host, in-page data: URLs, about:blank / about:srcdoc, and blob: URLs
    whose origin is itself local. Every other URL counts as an external request.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme == "data":
        return True
    if scheme == "about":
        return parts.path in ("blank", "srcdoc")
    if scheme == "blob":
        return is_local_request_url(parts.path)
    if scheme not in ("http", "https", "ws", "wss"):
        return False
    host = (parts.hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def streamlit_server_argv(py: str, port: int) -> list[str]:
    return [
        py, "-m", "streamlit", "run", "app.py",
        "--server.headless=true", f"--server.port={port}", "--server.address=127.0.0.1",
        "--browser.gatherUsageStats=false", "--server.fileWatcherType=none",
    ]


def workbook_stamp_problems(xlsx_path: Path) -> list[str]:
    """
    Reasons a workbook is not an ATLAS export: the Empirical Frequencies sheet,
    its prevalence column or its domain rows are missing, or a prevalence cell
    lacks its ATLAS VERIFICATION AUDIT STAMP comment.
    """
    sys.path.insert(0, str(REPO))
    import openpyxl
    from atlas_engine import FREQUENCY_HEADERS, FREQUENCY_SHEET

    wb = openpyxl.load_workbook(xlsx_path)
    if FREQUENCY_SHEET not in wb.sheetnames:
        return [f"sheet {FREQUENCY_SHEET!r} missing (sheets: {wb.sheetnames})"]
    ws = wb[FREQUENCY_SHEET]
    header = [cell.value for cell in ws[1]]
    if header[: len(FREQUENCY_HEADERS)] != FREQUENCY_HEADERS:
        return [f"unexpected header row {header}"]
    if ws.max_row < 2:
        return ["no domain rows"]
    column = FREQUENCY_HEADERS.index("Prevalence Rate (%)") + 1
    problems = []
    for row in range(2, ws.max_row + 1):
        comment = ws.cell(row=row, column=column).comment
        if comment is None or AUDIT_STAMP not in comment.text:
            problems.append(f"row {row}: prevalence cell has no {AUDIT_STAMP} comment")
    return problems


def engine_results(codebook: Path, files, root: Path, options=None) -> dict:
    sys.path.insert(0, str(REPO))
    from atlas_engine import AtlasEngine

    return AtlasEngine(str(codebook)).process_corpus([str(f) for f in files], root_dir=str(root),
                                                     tabular_options=options)


def engine_kpis(results: dict) -> dict:
    freq = results["frequencies_df"]
    return {
        "Analytical Units (N)": float(results["total_documents"]),
        "Participant Turns": float(results["participant_turns_analyzed"]),
        "Active Domains": float(len(freq)),
        "Matched Turn Mentions": float(freq["matching_turns"].sum()),
    }


def engine_domain_counts(results: dict) -> dict:
    freq = results["frequencies_df"]
    return {str(r.domain_id): (int(r.documents_reporting), int(r.matching_turns)) for r in freq.itertuples()}


def browser_check(url: str, scratch: Path) -> list[str]:
    """
    Drive the live app at url in headless Chromium: boot render, a transcript
    upload that recomputes the KPIs and domain table, the .xlsx / manifest
    downloads, and Markdown/shortcode domain names that both st.html chart
    summaries must show verbatim. Every expected number comes from AtlasEngine run here on the same
    SOFTWARE_TEST inputs.
    """
    sys.path.insert(0, str(REPO))
    import yaml
    from atlas_engine import AtlasEngine
    from universal_transcript_parser import SOFTWARE_TEST_BANNER

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return [f"playwright is not importable ({exc}); install it into .venv with `pip install playwright` and "
                "`python -m playwright install chromium`, or pass --skip-playwright explicitly"]

    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        print(f"    [{'ok' if condition else 'FAIL'}] {label}" + (f": {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(f"{label}{': ' + detail if detail else ''}")

    scratch.mkdir(parents=True, exist_ok=False)
    upload = scratch / BROWSER_UPLOAD_NAME
    upload_text = SOFTWARE_TEST_BANNER + "\n" + "".join(line + "\n" for line in BROWSER_UPLOAD_LINES)
    with open(upload, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(upload_text)
    markdown_codebook = scratch / MARKDOWN_CODEBOOK_NAME
    with open(markdown_codebook, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(yaml.safe_dump({
            "program_name": "SOFTWARE_TEST Markdown Domains",
            "version": "1.0",
            "topics": {f"markdown_{i}": {"label": name, "keywords": [keyword]}
                       for i, (keyword, name) in enumerate(MARKDOWN_DOMAINS.items())},
        }, allow_unicode=True, sort_keys=False))

    requested: list[str] = []
    page_errors: list[str] = []

    def kpis(page) -> dict:
        values = {}
        for card in page.locator('[data-testid="stMetric"]').all():
            label = card.locator('[data-testid="stMetricLabel"]').inner_text().strip()
            value = card.locator('[data-testid="stMetricValue"]').inner_text().strip()
            values[label] = float(value.replace(",", ""))
        return values

    def caption_codebook(page) -> str:
        for caption in page.locator('[data-testid="stCaptionContainer"]').all_inner_texts():
            found = re.search(r"Codebook: (\S+\.ya?ml)", caption)
            if found:
                return found.group(1)
        return ""

    def summary_caption(page) -> str:
        """Visible text of the st.html chart-summary paragraph in the open tab, unmodified."""
        for summary in page.locator(SUMMARY_SELECTOR).all():
            if summary.is_visible():
                text = summary.inner_text().strip()
                if text.startswith("Chart summary:"):
                    return text
        return ""

    def domain_table(page) -> dict:
        """{domain_id: (units reporting, matching turns)} from the visible thematic-prevalence grid."""
        # Each grid paints to a canvas; its cell text lives in a visually hidden accessibility table.
        for frame in page.locator('[data-testid="stDataFrame"]').all():
            if not frame.is_visible() or frame.locator("table").count() == 0:
                continue
            table = frame.locator("table").first
            headers = [h.strip() for h in table.locator("th").all_inner_texts()]
            if not {"Domain ID", "Units reporting", "Matching turns"} <= set(headers):
                continue
            rows = {}
            for tr in table.locator("tr").all()[1:]:
                cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
                if len(cells) == len(headers):
                    row = dict(zip(headers, cells))
                    rows[row["Domain ID"]] = (int(row["Units reporting"]), int(row["Matching turns"]))
            return rows
        return {}

    def wait_for(page, label: str, probe, want) -> object:
        """Poll the live DOM until probe() == want (the app reruns asynchronously); return the last value."""
        deadline = time.monotonic() + UI_WAIT_SECONDS
        seen = None
        while time.monotonic() < deadline:
            try:
                seen = probe(page)
            except (PlaywrightError, ValueError) as exc:
                seen = f"{type(exc).__name__}: {exc}"
            if seen == want:
                break
            page.wait_for_timeout(250)
        check(label, seen == want, f"{seen!r} != {want!r}")
        return seen

    def download(page, button: re.Pattern, target: Path) -> Path:
        with page.expect_download() as info:
            page.get_by_role("button", name=button).click()
        info.value.save_as(str(target))
        return target

    print(f"    PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '(Playwright default cache)')}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(accept_downloads=True)
            context.on("request", lambda req: requested.append(req.url))
            # Recorded above and then refused, so an external asset can never load.
            context.route("**/*", lambda route: route.continue_() if is_local_request_url(route.request.url)
                          else route.abort())
            page = context.new_page()
            page.on("websocket", lambda ws: requested.append(ws.url))
            page.on("pageerror", lambda err: page_errors.append(str(err)))
            page.goto(url, wait_until="domcontentloaded")
            page.locator('[data-testid="stMetric"]').first.wait_for(timeout=UI_WAIT_SECONDS * 1000)

            # 1. Boot render: SOFTWARE_TEST notice and KPI cards matching the engine.
            alerts = " ".join(page.locator('[data-testid="stAlert"]').all_inner_texts())
            check("boot: SOFTWARE_TEST notice rendered", "SOFTWARE_TEST" in alerts, alerts[:200])
            boot_codebook = caption_codebook(page)
            check("boot: active codebook shown", bool(boot_codebook))
            samples = REPO / "data" / "samples"
            boot = engine_results(REPO / "config" / (boot_codebook or "missing.yaml"),
                                  [samples / "software_test_bilingual_interview.txt",
                                   samples / "software_test_zoom_session.vtt"], REPO)
            boot_kpis = wait_for(page, "boot: KPI cards match engine", kpis, engine_kpis(boot))
            check("boot: four KPI cards", isinstance(boot_kpis, dict) and set(boot_kpis) == set(KPI_LABELS),
                  repr(boot_kpis))

            # 2. Upload a custom transcript; KPIs and the domain table recompute in the live DOM.
            page.get_by_role("combobox", name="Corpus Dataset").click()
            page.get_by_role("option", name=UPLOAD_OPTION).click()
            page.locator("input[type='file']").first.set_input_files(str(upload))
            page.get_by_text(f"Corpus: {BROWSER_UPLOAD_NAME}").wait_for(timeout=UI_WAIT_SECONDS * 1000)
            codebook = caption_codebook(page)
            uploaded_root = scratch / "engine_root"
            (uploaded_root / "uploads").mkdir(parents=True)
            shutil.copy2(upload, uploaded_root / "uploads" / BROWSER_UPLOAD_NAME)
            want = engine_results(REPO / "config" / (codebook or "missing.yaml"),
                                  [uploaded_root / "uploads" / BROWSER_UPLOAD_NAME], uploaded_root)
            want_kpis = engine_kpis(want)
            check("upload: engine finds matches in the SOFTWARE_TEST upload",
                  want_kpis["Matched Turn Mentions"] > 0, repr(want_kpis))
            check("upload: expected KPIs differ from boot", want_kpis != engine_kpis(boot))
            wait_for(page, "upload: KPI cards recomputed to engine values", kpis, want_kpis)
            wait_for(page, "upload: domain table recomputed to engine values", domain_table,
                     engine_domain_counts(want))
            alerts = " ".join(page.locator('[data-testid="stAlert"]').all_inner_texts())
            check("upload: SOFTWARE_TEST notice for the bannered upload", "SOFTWARE_TEST" in alerts)
            check("upload: workbook integrity passes in the app", "integrity check passed" in alerts, alerts[:300])

            # 3. Download the engine's workbook and manifest and verify them offline.
            page.get_by_role("tab", name=re.compile(r"Tab 2")).click()
            xlsx = download(page, re.compile(r"actuarial_parameter_matrix\.xlsx"), scratch / "downloaded.xlsx")
            manifest_path = download(page, re.compile(r"provenance_manifest\.json"), scratch / "downloaded.json")

            # 4. A custom codebook whose domain names are Markdown and Streamlit shortcodes: both
            #    st.html chart summaries show them verbatim.
            page.get_by_role("combobox", name="Active YAML Codebook").click()
            page.get_by_role("option", name=CODEBOOK_UPLOAD_OPTION).click()
            page.get_by_test_id("stFileUploader").filter(has_text=CODEBOOK_UPLOAD_OPTION).locator(
                "input[type='file']").set_input_files(str(markdown_codebook))
            for tab in ("Tab 1", "Tab 2"):
                page.get_by_role("tab", name=re.compile(tab)).click()
                wait_for(page, f"markdown domains: {tab} chart summary shows both names verbatim",
                         lambda p: all(name in summary_caption(p) for name in MARKDOWN_DOMAINS.values()), True)
                caption = summary_caption(page)
                check(f"markdown domains: {tab} summary has no escape backslashes", "\\" not in caption, caption)
                check(f"markdown domains: {tab} summary has no invisible U+2060", "⁠" not in caption, caption)
                markup = page.evaluate(
                    "([sel, bad]) => [...document.querySelectorAll(sel)]"
                    ".filter(c => c.innerText.startsWith('Chart summary:') && c.offsetParent !== null)"
                    ".map(c => c.querySelectorAll(bad).length)", [SUMMARY_SELECTOR, SUMMARY_MARKUP])
                check(f"markdown domains: {tab} summary renders no image, icon, link, math, color, emphasis or script",
                      markup == [0], repr(markup))
            leaked = page.locator("img[src*='example.invalid'], a[href*='example.invalid']").count()
            check("markdown domains: no example.invalid image or link anywhere in the page", leaked == 0, str(leaked))
        finally:
            browser.close()

    stamp_problems = workbook_stamp_problems(xlsx)
    check(f"download: Empirical Frequencies carries {AUDIT_STAMP} comments", stamp_problems == [],
          "; ".join(stamp_problems[:3]))
    ok, reasons = AtlasEngine.verify_workbook_integrity(str(xlsx), str(manifest_path))
    check("download: workbook verifies against the downloaded manifest", (ok, reasons) == (True, []),
          "; ".join(reasons[:3]))
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    check("download: manifest binds the uploaded bytes",
          manifest.get("file_hashes") == {f"uploads/{BROWSER_UPLOAD_NAME}": sha256_file(upload)},
          repr(manifest.get("file_hashes")))
    check("download: manifest counts match engine", manifest.get("total_documents") == want["total_documents"]
          and {d["domain_id"]: (d["documents_reporting"], d["matching_turns"]) for d in manifest.get("domains", [])}
          == engine_domain_counts(want))

    external = [u for u in requested if not is_local_request_url(u)]
    check("browser: requests recorded", len(requested) > 0)
    check("browser: 0 external requests", external == [], "; ".join(external[:5]))
    check("browser: 0 uncaught page errors", page_errors == [], "; ".join(page_errors[:3]))
    print(f"    browser requests: {len(requested)} total, {len(external)} external; page errors: {len(page_errors)}")
    return failures


def wait_for_server(proc: subprocess.Popen, url: str, log_path: Path) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback only, never a proxy
    deadline = time.monotonic() + UI_WAIT_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise StageFailure(f"streamlit server exited early ({proc.returncode}):\n{tail(log_path)}")
        try:
            with opener.open(f"{url}/_stcore/health", timeout=5) as resp:
                if resp.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise StageFailure(f"streamlit server did not answer {url}/_stcore/health:\n{tail(log_path)}")


def stop_server(proc: subprocess.Popen) -> str | None:
    """Ask the server to shut down with a signal; return a problem if it was already gone or had to be killed."""
    if proc.poll() is not None:
        return f"streamlit server had already exited ({proc.returncode})"
    proc.send_signal(signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGTERM)
    try:
        code = proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return "streamlit server ignored the shutdown signal and was killed"
    if code != 0 and not IS_WINDOWS:
        return f"streamlit server exited {code} after SIGTERM"
    print(f"--- streamlit server stopped (exit {code})", flush=True)
    return None


def tail(path: Path, lines: int = 40) -> str:
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def browser_stage(work: Path, env: dict, net_log: Path, tmp: Path) -> None:
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    log_path = tmp / "streamlit_server.log"
    argv = streamlit_server_argv(str(venv_python(work)), port)
    print(f"\n--- streamlit server: {' '.join(argv)}", flush=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(argv, cwd=str(work), env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=flags)
    problems = []
    try:
        wait_for_server(proc, url, log_path)
        print(f"--- streamlit server: serving {url}", flush=True)
        run_step("headless browser check", [str(venv_python(work)), SMOKE_SCRIPT, "--browser-check", url,
                                            str(tmp / "stage4_browser")], work, env, net_log)
    except StageFailure as exc:
        problems.append(str(exc))
    finally:
        stop_problem = stop_server(proc)
    if stop_problem:
        problems.append(stop_problem)
    elif "Stopping..." not in tail(log_path):
        problems.append("streamlit server did not report a clean shutdown ('Stopping...')")
    if problems:
        print(tail(log_path))
        raise StageFailure("; ".join(problems))
    print("--- streamlit server: clean shutdown", flush=True)


def require_empty_net_log(net_log: Path, when: str) -> None:
    entries = read_log(net_log)
    if entries:
        raise StageFailure(f"{net_log.name} {when}: {len(entries)} outbound network attempt(s): {entries[0][:300]}")
    print(f"--- {net_log.name} {when}: empty (0 outbound Python network attempts)", flush=True)


def stage4(work: Path, env: dict, net_log: Path, tmp: Path, skip_playwright: bool = False) -> None:
    py = str(venv_python(work))
    run_step("unit tests", [py, "-m", "unittest", "discover", "-s", "tests", "-v"], work, env, net_log)
    run_step("app widget check (AppTest)", [py, SMOKE_SCRIPT, "--app-check"], work, env, net_log)
    if skip_playwright:
        print("\n--- headless browser check: SKIPPED (--skip-playwright was passed explicitly)", flush=True)
    else:
        browser_stage(work, env, net_log, tmp)
    require_empty_net_log(net_log, "after stage 4")


# ----------------------------------------------------------------------
# Stage 5: anti-shortcut gate and codebook compilation audit
# ----------------------------------------------------------------------
def codebook_audit(config_dir: Path) -> dict:
    """{codebook file name: compiled rule count} for every YAML codebook in config_dir; StageFailure otherwise."""
    sys.path.insert(0, str(REPO))
    import yaml
    from atlas_engine import AtlasEngine

    paths = sorted([*Path(config_dir).glob("*.yaml"), *Path(config_dir).glob("*.yml")])
    if not paths:
        raise StageFailure(f"codebook audit: no YAML codebooks in {config_dir}")
    compiled = {}
    for path in paths:
        try:
            rules = AtlasEngine(str(path)).compiled_rules
        except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
            raise StageFailure(f"codebook audit: {path.name} does not compile: {type(exc).__name__}: {exc}") from exc
        if not rules:
            raise StageFailure(f"codebook audit: {path.name} compiled to no rules")
        compiled[path.name] = len(rules)
    return compiled


def stage5(work: Path, env: dict, net_log: Path, tmp: Path) -> None:
    py = str(venv_python(work))
    run_step("anti-shortcut gate", [py, "scripts/anti_shortcut_gate.py", "--repo", str(work), "--slice", "4"],
             work, env, net_log)
    run_step("codebook compilation audit", [py, SMOKE_SCRIPT, "--codebook-audit"], work, env, net_log)


STAGES = {
    1: ("clean-temp copy and subprocess offline monitor", stage1),
    2: ("launcher --check-only and broken-venv recovery", stage2),
    3: ("end-to-end multi-format CLI, reproducibility and tamper detection", stage3),
    4: ("unit tests, AppTest and headless Playwright Chromium", stage4),
    5: ("anti-shortcut gate (slice 4) and codebook compilation audit", stage5),
}


def run_stages(stages, work: Path, env: dict, net_log: Path, tmp: Path, before: dict) -> None:
    """
    Run (num, title, fn) stages in order. The shared .venv is re-fingerprinted after
    every stage in a finally block, so a change is reported even when the stage
    itself fails, alongside that failure.
    """
    for num, title, fn in stages:
        print(f"\n=== STAGE {num}: {title} (copy: {work})", flush=True)
        stage_error = None
        venv_problem = None
        try:
            fn(work, env, net_log, tmp)
        except StageFailure as exc:
            stage_error = str(exc)
        finally:
            venv_problem = shared_venv_problem(before)
            if venv_problem:
                print(f"=== STAGE {num}: {venv_problem}", flush=True)
        problems = [p for p in (stage_error, venv_problem) if p]
        if problems:
            raise StageFailure(f"stage {num}: " + "; ".join(problems))
        print(f"=== STAGE {num}: PASS", flush=True)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-stage", type=int, default=max(STAGES), choices=sorted(STAGES),
                    help="run stages 1..N (default: all five)")
    ap.add_argument("--skip-playwright", action="store_true",
                    help="skip only the headless-browser check in stage 4 (it runs by default and in CI)")
    ap.add_argument("--pipeline-check", metavar="DIR", help=argparse.SUPPRESS)
    ap.add_argument("--app-check", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--browser-check", nargs=2, metavar=("URL", "DIR"), help=argparse.SUPPRESS)
    ap.add_argument("--codebook-audit", action="store_true", help=argparse.SUPPRESS)
    return ap


def report(name: str, failures: list[str]) -> int:
    if failures:
        print(f"{name} FAILED ({len(failures)} check(s))")
        for failure in failures:
            print(f"    - {failure}")
        return 1
    print(f"{name} PASSED")
    return 0


def main() -> int:
    args = build_parser().parse_args()

    if args.app_check:
        return report("APP CHECK", app_check())
    if args.pipeline_check:
        scratch = Path(args.pipeline_check)
        scratch.mkdir(parents=True, exist_ok=False)
        return report("PIPELINE CHECK", pipeline_check(scratch))
    if args.browser_check:
        url, scratch = args.browser_check
        return report("BROWSER CHECK", browser_check(url, Path(scratch)))
    if args.codebook_audit:
        try:
            compiled = codebook_audit(REPO / "config")
        except StageFailure as exc:
            return report("CODEBOOK AUDIT", [str(exc)])
        for name, n_rules in compiled.items():
            print(f"    [ok] {name}: {n_rules} domain rule(s) compiled")
        print(f"    {len(compiled)} codebook(s) compiled")
        return report("CODEBOOK AUDIT", [])

    with tempfile.TemporaryDirectory(prefix="atlas_smoke_") as tmp_name:
        tmp = Path(tmp_name)
        net_log = tmp / NET_LOG_NAME
        before = repo_venv_fingerprint()
        try:
            try:
                work = prepare_copy(tmp)
            except StageFailure as exc:
                problem = shared_venv_problem(before)
                raise StageFailure(f"{exc}; {problem}" if problem else str(exc)) from exc
            env = guarded_env(work, net_log)
            fns = {**{num: fn for num, (_, fn) in STAGES.items()},
                   4: functools.partial(stage4, skip_playwright=args.skip_playwright)}
            stages = [(num, STAGES[num][0], fns[num]) for num in range(1, args.max_stage + 1)]
            run_stages(stages, work, env, net_log, tmp, before)
            require_empty_net_log(net_log, "at the end of the run")
        except StageFailure as exc:
            print(f"\nSMOKE TEST FAILED: {exc}")
            return 1
    skipped = " (headless browser check SKIPPED by --skip-playwright)" if args.skip_playwright and args.max_stage >= 4 else ""
    print(f"\nSMOKE TEST PASSED (stages 1..{args.max_stage}){skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
