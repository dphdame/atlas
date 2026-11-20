#!/usr/bin/env python3
"""Progressive ATLAS smoke suite.

Each stage runs against a fresh copy of the repository in a temporary
directory, with every child process under the ATLAS offline guard
(scripts/offline_guard/sitecustomize.py, ATLAS_OFFLINE_GUARD=1). Any blocked
network call recorded in the guard log fails the stage.

Stage 1 (Slice 1 - packaging, launchers, ingestion):
  1. confirm the offline guard is loaded in child Python processes
  2. launcher --check-only (run.command on macOS/Linux, run.bat on Windows)
  3. python -m unittest discover -s tests
  4. scripts/anti_shortcut_gate.py --slice 1

Stage 2 (Slice 2 - engine, discovery, provenance):
  1. a guarded child (this script with --pipeline-check DIR) writes SOFTWARE_TEST
     .docx, .vtt, accented .txt (NFC/NFD marks, ligature, sharp s), same-basename
     .txt files in two folders and a .csv into DIR, then runs
     UniversalTranscriptParser -> atlas_discover -> AtlasEngine.export_results and
     checks denominators, verbatim spans, .xlsx audit comments, .parquet,
     provenance_manifest.json, semantic rerun equality and tamper detection by
     verify_workbook_integrity
  2. scripts/anti_shortcut_gate.py --slice 2

The repository's provisioned .venv is reused (the guard blocks pip downloads by
design); provision it first with `run.command --check-only`. The copy gets its
own real .venv (with a copy of the dependency marker) that reads the shared
site-packages through a .pth file, so a launcher or pip in the copy installs,
rewrites or deletes only the copy's environment. After every stage, including a
failed one, the run fails if any file's content or symlink target in the shared
.venv (bytecode caches aside) was added, removed or changed.

Usage: .venv/bin/python scripts/smoke_test.py --max-stage 2
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unicodedata


REPO = Path(__file__).resolve().parent.parent
COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "venv", ".codex", "thoughts", "__pycache__", "*.pyc", "*.pyo",
    ".pytest_cache", "output", "*.log", ".DS_Store",
)
IS_WINDOWS = os.name == "nt"
MARKER_NAME = ".atlas_deps.sha256"


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
    shutil.copytree(REPO, work, ignore=COPY_IGNORE)
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


def stage1(work: Path, env: dict, net_log: Path, tmp: Path) -> None:
    verify_guard_active(work, env, tmp)
    launcher = ["cmd", "/c", "run.bat", "--check-only"] if IS_WINDOWS else ["bash", "run.command", "--check-only"]
    run_step("launcher --check-only", launcher, work, env, net_log)
    py = str(venv_python(work))
    run_step("unit tests", [py, "-m", "unittest", "discover", "-s", "tests", "-v"], work, env, net_log)
    run_step("anti-shortcut gate", [py, "scripts/anti_shortcut_gate.py", "--repo", ".", "--slice", "1"], work, env, net_log)


# ----------------------------------------------------------------------
# Stage 2: multi-format pipeline (runs inside a guarded child process)
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
# (domain_id) -> (documents_reporting, matching_turns). 10 units = 7 transcripts (including
# one with only facilitator turns and one that parses to no turns) + 3 CSV respondent rows;
# the blank CSV row and the CSV interviewer-prompt row are not respondents.
SMOKE_EXPECTED_TOTAL = 10
SMOKE_PARTICIPANT_ONLY_UNITS = 8
PROMPT_PATTERNS = [r"^PROMPT:"]
SMOKE_EXPECTED = {"PROTECCION": (1, 3), "CHILDCARE": (2, 2), "TRANSIT": (3, 3)}
ACCENTED_LINES = [
    ("Trabajadora A", NFC("Perdí la protección laboral cuando pedí permiso en el trabajo.")),
    ("Trabajadora B", "Perdí la " + NFD_PROTECCION + " durante el permiso."),
    ("Trabajadora C", NFC("The ﬁnancial leave ended; luego se agotó el beneficio at my job.")),
    ("Trabajadora D", NFC("Die Straße war lang; perdí la protección laboral en el trabajo.")),
]
TABULAR_OPTIONS = {"text_col": "response", "id_col": "respondent_id"}
EMPTY_TRANSCRIPT = "software_test_empty.txt"


def write_stage2_fixtures(corpus: Path) -> list[Path]:
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
    import json
    import openpyxl
    import pandas as pd
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
    files = write_stage2_fixtures(corpus)
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
    check("facilitator and prompt turns flagged", sum(t["is_facilitator"] for t in turns) == 4)
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


def stage2(work: Path, env: dict, net_log: Path, tmp: Path) -> None:
    py = str(venv_python(work))
    scratch = tmp / "stage2_pipeline"
    run_step("pipeline check", [py, "scripts/smoke_test.py", "--pipeline-check", str(scratch)], work, env, net_log)
    run_step("anti-shortcut gate", [py, "scripts/anti_shortcut_gate.py", "--repo", ".", "--slice", "2"], work, env, net_log)


STAGES = {
    1: ("packaging, launchers, ingestion", stage1),
    2: ("engine, discovery, provenance", stage2),
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-stage", type=int, default=2, choices=sorted(STAGES),
                    help="run stages 1..N (later stages are added in later slices)")
    ap.add_argument("--pipeline-check", metavar="DIR", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.pipeline_check:
        scratch = Path(args.pipeline_check)
        scratch.mkdir(parents=True, exist_ok=False)
        failures = pipeline_check(scratch)
        if failures:
            print(f"PIPELINE CHECK FAILED ({len(failures)} check(s))")
            return 1
        print("PIPELINE CHECK PASSED")
        return 0

    with tempfile.TemporaryDirectory(prefix="atlas_smoke_") as tmp_name:
        tmp = Path(tmp_name)
        net_log = tmp / "net_log.jsonl"
        before = repo_venv_fingerprint()
        try:
            try:
                work = prepare_copy(tmp)
            except StageFailure as exc:
                problem = shared_venv_problem(before)
                raise StageFailure(f"{exc}; {problem}" if problem else str(exc)) from exc
            env = guarded_env(work, net_log)
            stages = [(num, *STAGES[num]) for num in range(1, args.max_stage + 1)]
            run_stages(stages, work, env, net_log, tmp, before)
        except StageFailure as exc:
            print(f"\nSMOKE TEST FAILED: {exc}")
            return 1
    print(f"\nSMOKE TEST PASSED (stages 1..{args.max_stage})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
