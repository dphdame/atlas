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

The repository's provisioned .venv is reused (the guard blocks pip downloads by
design); provision it first with `run.command --check-only`. The copy gets its
own real .venv (with a copy of the dependency marker) that reads the shared
site-packages through a .pth file, so a launcher or pip in the copy installs,
rewrites or deletes only the copy's environment. After every stage, including a
failed one, the run fails if any file's content or symlink target in the shared
.venv (bytecode caches aside) was added, removed or changed.

Usage: .venv/bin/python scripts/smoke_test.py --max-stage 1
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


STAGES = {1: ("packaging, launchers, ingestion", stage1)}


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
    ap.add_argument("--max-stage", type=int, default=1, choices=sorted(STAGES),
                    help="run stages 1..N (later stages are added in later slices)")
    args = ap.parse_args()

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
