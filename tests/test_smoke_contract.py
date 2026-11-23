"""Slice 4 (RED first): smoke-suite, launcher and CI workflow contracts.

These tests pin the structure that the cross-platform CI workflow and the
5-stage smoke suite (scripts/smoke_test.py) must keep:

- .github/workflows/test-windows-install.yml (filename kept for GitHub history)
  is renamed away from the legacy "Test Windows Install" and runs on
  windows-latest and ubuntu-latest with Python 3.12. Each job provisions .venv
  through the real launcher in check-only mode (run.bat under shell: cmd on
  Windows, bash run.command on Ubuntu), installs Playwright Chromium into .venv,
  then runs the unit tests and `scripts/smoke_test.py --max-stage 5`, in that
  order, with no --skip-playwright and no legacy setup.bat / venv / wordcloud.
- run.bat and run.command honour --check-only: they exit 0 before launching
  Streamlit, never pause on that path, and write the dependency marker only
  after pip succeeds.
- smoke_test.py defaults to all five stages with Playwright on; skipping the
  browser stage needs an explicit --skip-playwright. Its helpers classify
  browser request URLs (only loopback hosts and in-page schemes are local),
  start Streamlit headless on a free loopback port, verify the downloaded
  workbook's audit-stamp comments, reject a temp copy holding excluded
  directories or paths that escape it, and compile every config/*.yaml codebook.

Live behaviour (launcher recovery, the browser flow, the offline monitor) is
proved by running the smoke suite itself; these tests pin its contracts.
Every input here is a SOFTWARE_TEST fixture that demonstrates software
mechanics only; nothing asserted is an empirical finding.

Run: .venv/bin/python -m unittest tests/test_smoke_contract.py -v
"""

import ast
import hashlib
import html
import importlib.util
import inspect
import os
import re
import socket
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

import openpyxl
import streamlit as st
import yaml
from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "test-windows-install.yml"
sys.path.insert(0, str(REPO))


def load_smoke():
    spec = importlib.util.spec_from_file_location("atlas_smoke_test", REPO / "scripts" / "smoke_test.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def job_for(workflow: dict, runner: str) -> dict:
    jobs = [job for job in workflow["jobs"].values() if job.get("runs-on") == runner]
    if len(jobs) != 1:
        raise AssertionError(f"expected exactly one job with runs-on: {runner}, found {len(jobs)}")
    return jobs[0]


def step_index(steps: list, predicate, what: str) -> int:
    for idx, step in enumerate(steps):
        if predicate(step):
            return idx
    raise AssertionError(f"no workflow step {what}")


def runs(step: dict) -> str:
    return str(step.get("run", ""))


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.wf = load_workflow()
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_renamed_and_triggered(self):
        name = str(self.wf.get("name", ""))
        self.assertTrue(name.strip(), "workflow needs a name")
        self.assertNotEqual(name, "Test Windows Install", "workflow still carries the legacy Windows-only name")
        self.assertIn("Windows", name)
        self.assertIn("Ubuntu", name)
        triggers = self.wf.get("on", self.wf.get(True))  # PyYAML reads a bare `on:` key as True
        for trigger in ("push", "pull_request", "workflow_dispatch"):
            self.assertIn(trigger, triggers)

    def test_runs_on_windows_and_ubuntu_with_python_312(self):
        runners = sorted(job.get("runs-on") for job in self.wf["jobs"].values())
        self.assertEqual(runners, ["ubuntu-latest", "windows-latest"])
        for runner in runners:
            steps = job_for(self.wf, runner)["steps"]
            setup = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python@")]
            self.assertEqual(len(setup), 1, runner)
            self.assertEqual(str(setup[0]["with"]["python-version"]), "3.12", runner)
            self.assertTrue(any(str(s.get("uses", "")).startswith("actions/checkout@") for s in steps), runner)

    def test_no_legacy_or_skip_flags(self):
        for legacy in ("setup.bat", "wordcloud", "spellchecker", "nltk", "--skip-playwright"):
            self.assertNotIn(legacy, self.text)
        self.assertIsNone(re.search(r"(?<![.\w])venv[\\/]", self.text), "legacy venv\\ path (not .venv) in workflow")

    def test_windows_job_order(self):
        steps = job_for(self.wf, "windows-latest")["steps"]
        py = r".venv\Scripts\python.exe"
        launcher = step_index(steps, lambda s: s.get("shell") == "cmd" and "call run.bat --check-only" in runs(s),
                              "running `call run.bat --check-only` under shell: cmd")
        self.assertNotIn("pause", runs(steps[launcher]).lower())
        marker = step_index(steps, lambda s: r".venv\.atlas_deps.sha256" in runs(s),
                            r"checking .venv\.atlas_deps.sha256")
        pip_pw = step_index(steps, lambda s: f"{py} -m pip install" in runs(s) and "playwright" in runs(s),
                            "installing playwright into .venv")
        chromium = step_index(steps, lambda s: f"{py} -m playwright install chromium" in runs(s),
                              "installing Playwright Chromium")
        unit = step_index(steps, lambda s: f"{py} -m unittest discover -s tests -v" in runs(s), "running unit tests")
        smoke = step_index(steps, lambda s: rf"{py} scripts\smoke_test.py --max-stage 5" in runs(s),
                           "running the 5-stage smoke suite")
        self.assertLess(launcher, marker)
        self.assertLess(marker, pip_pw)
        self.assertLess(pip_pw, chromium)
        self.assertLess(chromium, unit)
        self.assertLess(unit, smoke)

    def test_ubuntu_job_order(self):
        steps = job_for(self.wf, "ubuntu-latest")["steps"]
        py = ".venv/bin/python"
        launcher = step_index(steps, lambda s: "bash run.command --check-only" in runs(s),
                              "running `bash run.command --check-only`")
        marker = step_index(steps, lambda s: ".venv/.atlas_deps.sha256" in runs(s), "checking .venv/.atlas_deps.sha256")
        pip_pw = step_index(steps, lambda s: f"{py} -m pip install" in runs(s) and "playwright" in runs(s),
                            "installing playwright into .venv")
        chromium = step_index(steps, lambda s: f"{py} -m playwright install --with-deps chromium" in runs(s),
                              "installing Playwright Chromium with system deps")
        unit = step_index(steps, lambda s: f"{py} -m unittest discover -s tests -v" in runs(s), "running unit tests")
        smoke = step_index(steps, lambda s: f"{py} scripts/smoke_test.py --max-stage 5" in runs(s),
                           "running the 5-stage smoke suite")
        self.assertLess(launcher, marker)
        self.assertLess(marker, pip_pw)
        self.assertLess(pip_pw, chromium)
        self.assertLess(chromium, unit)
        self.assertLess(unit, smoke)


class LauncherFlagTests(unittest.TestCase):
    def test_run_command_check_only_exits_before_launch(self):
        text = (REPO / "run.command").read_text(encoding="utf-8")
        self.assertIn('"$arg" = "--check-only"', text)
        ok = text.index("ATLAS check-only: OK")
        exit0 = text.index("exit 0", ok)
        launch = text.index("streamlit run app.py")
        self.assertLess(exit0, launch)
        self.assertLess(text.index("pip install"), text.index('> "$MARKER"'))

    def test_run_bat_check_only_never_pauses(self):
        text = (REPO / "run.bat").read_text(encoding="utf-8")
        self.assertIn('if /i "%~1"=="--check-only" set "CHECK_ONLY=1"', text)
        verify = text.index(":verify")
        self.assertLess(text.index('if "%CHECK_ONLY%"=="1" goto check_only_done', verify),
                        text.index("streamlit run app.py", verify))
        block = text[text.index(":check_only_done"):]
        block = block[: block.index("\n:", 1)]
        self.assertIn("exit /b 0", block)
        self.assertNotIn("pause", block.lower())
        fail = text[text.index(":fail"):]
        pauses = [ln.strip() for ln in fail.splitlines() if "pause" in ln.lower()]
        self.assertEqual(pauses, ['if not "%CHECK_ONLY%"=="1" pause'])
        self.assertLess(text.index(":install_ok"), text.index('> "%MARKER%"'))


class SmokeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.smoke = load_smoke()

    def test_defaults_run_all_five_stages_with_playwright(self):
        args = self.smoke.build_parser().parse_args([])
        self.assertEqual(args.max_stage, 5)
        self.assertFalse(args.skip_playwright)
        self.assertTrue(self.smoke.build_parser().parse_args(["--skip-playwright"]).skip_playwright)
        self.assertEqual(sorted(self.smoke.STAGES), [1, 2, 3, 4, 5])
        for num, (title, fn) in self.smoke.STAGES.items():
            self.assertTrue(title.strip())
            self.assertTrue(callable(fn), num)

    def test_net_log_name(self):
        self.assertEqual(self.smoke.NET_LOG_NAME, "net_attempts.jsonl")

    def test_local_request_classification(self):
        local = [
            "http://127.0.0.1:8765/", "http://127.0.0.1:8765/_stcore/health", "ws://127.0.0.1:8765/_stcore/stream",
            "http://localhost:8501/static/js/main.js", "http://[::1]:8501/", "data:image/png;base64,AAAA",
            "blob:http://127.0.0.1:8765/1234-5678", "about:blank",
        ]
        external = [
            "https://fonts.googleapis.com/css2?family=Inter", "http://example.com/", "https://127.0.0.1.example.com/",
            "http://localhost.evil.test/", "https://webhooks.fivetran.com/x", "//cdn.jsdelivr.net/npm/x",
            "http://10.0.0.5:8501/", "ftp://127.0.0.2.nip.io/",
        ]
        for url in local:
            self.assertTrue(self.smoke.is_local_request_url(url), url)
        for url in external:
            self.assertFalse(self.smoke.is_local_request_url(url), url)

    def test_free_port_is_bindable_on_loopback(self):
        port = self.smoke.free_port()
        self.assertIsInstance(port, int)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))

    def test_streamlit_server_argv(self):
        argv = self.smoke.streamlit_server_argv("PY", 8765)
        self.assertEqual(argv[:4], ["PY", "-m", "streamlit", "run"])
        self.assertIn("app.py", argv)
        for flag in ("--server.headless=true", "--server.port=8765", "--browser.gatherUsageStats=false",
                     "--server.address=127.0.0.1"):
            self.assertIn(flag, argv)

    def test_launcher_argv(self):
        argv = self.smoke.launcher_argv()
        if os.name == "nt":
            self.assertEqual(argv, ["cmd", "/c", "run.bat", "--check-only"])
        else:
            self.assertEqual(argv, ["bash", "run.command", "--check-only"])

    def test_codebook_audit_compiles_all_seven(self):
        compiled = self.smoke.codebook_audit(REPO / "config")
        expected = sorted(p.name for p in (REPO / "config").glob("*.yaml"))
        self.assertEqual(len(expected), 7)
        self.assertIn("gbi_focus_group_starter.yaml", expected)
        self.assertEqual(sorted(compiled), expected)
        for name, n_rules in compiled.items():
            self.assertGreater(n_rules, 0, name)

    def test_codebook_audit_rejects_broken_codebook(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "software_test_broken.yaml").write_text(
                "project: SOFTWARE_TEST Broken\ndomains:\n  - id: X\n    name: X\n    context_window: -1\n"
                "    roots_en: [bus]\n", encoding="utf-8")
            with self.assertRaises(self.smoke.StageFailure):
                self.smoke.codebook_audit(Path(tmp))
            with self.assertRaises(self.smoke.StageFailure):
                self.smoke.codebook_audit(Path(tmp) / "empty_dir_that_does_not_exist")

    def test_audit_stamp_check_on_real_export(self):
        from atlas_engine import AtlasEngine

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            transcript = tmp / "software_test_stamp.txt"
            transcript.write_text("Respondent A: The bus was late again.\nRespondent B: Childcare is far.\n",
                                  encoding="utf-8")
            engine = AtlasEngine(str(REPO / "config" / "sdoh_basic_needs.yaml"))
            results = engine.process_corpus([str(transcript)], root_dir=str(tmp))
            engine.export_results(results, str(tmp / "out"))
            xlsx = tmp / "out" / "actuarial_parameter_matrix.xlsx"
            problems = self.smoke.workbook_stamp_problems(xlsx)
            self.assertEqual(problems, [])

            wb = openpyxl.load_workbook(xlsx)
            ws = wb["Empirical Frequencies"]
            ws.cell(row=2, column=5).comment = None
            stripped = tmp / "stripped.xlsx"
            wb.save(stripped)
            self.assertTrue(self.smoke.workbook_stamp_problems(stripped))

            wb = openpyxl.Workbook()
            wb.active.title = "Other"
            other = tmp / "other.xlsx"
            wb.save(other)
            self.assertTrue(self.smoke.workbook_stamp_problems(other))

    def test_copy_problems_flags_excluded_dirs_and_escapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root, outside = tmp / "copy", tmp / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "app.py").write_text("# SOFTWARE_TEST\n", encoding="utf-8")
            self.assertEqual(self.smoke.copy_problems(root), [])
            for name in (".git", ".codex", "thoughts"):
                (root / name).mkdir()
            os.symlink(outside, root / "escape")
            problems = " ".join(self.smoke.copy_problems(root))
            for name in (".git", ".codex", "thoughts", "escape"):
                self.assertIn(name, problems)

    def test_copied_source_symlink_to_outside_is_kept_and_flagged(self):
        # copytree must not follow a source link and copy the external file in as an ordinary one.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src, outside, dst = tmp / "src", tmp / "outside", tmp / "dst"
            src.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("SOFTWARE_TEST external content\n", encoding="utf-8")
            (src / "app.py").write_text("# SOFTWARE_TEST\n", encoding="utf-8")
            os.symlink(outside / "secret.txt", src / "linked.txt")
            self.smoke.copy_repo(src, dst)
            self.assertTrue((dst / "linked.txt").is_symlink())
            self.assertIn("linked.txt", " ".join(self.smoke.copy_problems(dst)))

    def test_broken_venv_scenarios_damage_the_interpreter_on_every_platform(self):
        scenarios = self.smoke.broken_venv_scenarios()
        self.assertEqual(sorted(scenarios), ["empty .venv without marker", "stale marker and damaged interpreter",
                                             "stale marker and negative-exit interpreter"])
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / ".venv"
            scenarios["stale marker and damaged interpreter"](venv)
            exe = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            self.assertTrue(exe.is_file())
            self.assertTrue((venv / ".atlas_deps.sha256").is_file())
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / ".venv"
            scenarios["stale marker and negative-exit interpreter"](venv)
            exe = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            self.assertTrue(exe.is_file())
            self.assertEqual((venv / ".atlas_deps.sha256").read_text(encoding="utf-8"), "0" * 64 + "\n")
            env = dict(os.environ, PYTHONPATH=str(REPO / "scripts" / "offline_guard"), ATLAS_OFFLINE_GUARD="1",
                       ATLAS_NET_LOG=str(Path(tmp) / "net_attempts.jsonl"), PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.run([str(exe), "-c", "import sys"], env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True)
            self.assertNotEqual(proc.returncode, 0, "the interpreter must crash during site initialization")
            if os.name == "nt":
                # GetExitCodeProcess reports the DWORD; cmd.exe shows the same value signed as -1073741819.
                self.assertEqual(proc.returncode & 0xFFFFFFFF, 0xC0000005)
        source = (REPO / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
        check = source[source.index("def broken_venv_check"):source.index("def stage2")]
        self.assertIn('if "Creating local isolated environment" not in output:', check,
                      "every damaged .venv must be recreated in the same run, on every platform")

    def test_workflow_sets_no_elapsed_time_ceiling(self):
        self.assertNotIn("timeout-minutes", WORKFLOW.read_text(encoding="utf-8"))


def load_app_helpers(*names):
    """Compile app.py's top-level imports and the named helper functions, without
    running the Streamlit page script itself."""
    tree = ast.parse((REPO / "app.py").read_text(encoding="utf-8"))
    body = [node for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            or (isinstance(node, ast.FunctionDef) and node.name in names)]
    missing = set(names) - {node.name for node in body if isinstance(node, ast.FunctionDef)}
    if missing:
        raise AssertionError(f"app.py defines no top-level function(s): {sorted(missing)}")
    namespace = {"__name__": "atlas_app_helpers", "__file__": str(REPO / "app.py")}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(REPO / "app.py"), "exec"), namespace)
    return namespace


FULL_WIDTH_WIDGETS = ("download_button", "button", "dataframe", "altair_chart")


def cmd_if_goto(line: str, status: int) -> bool:
    """Whether cmd.exe takes `line`'s goto when the last command exited with `status`.
    `if errorlevel N` is true when the status is >= N; `"%ERRORLEVEL%"=="N"` is an exact
    string comparison of the expanded signed status."""
    m = re.fullmatch(r'if (not )?errorlevel (-?\d+) goto \w+', line, re.IGNORECASE)
    if m:
        return (status >= int(m.group(2))) != bool(m.group(1))
    m = re.fullmatch(r'if (not )?"%ERRORLEVEL%"=="(-?\d+)" goto \w+', line)
    if m:
        return (str(status) == m.group(2)) != bool(m.group(1))
    raise AssertionError(f"unrecognized exit-status check: {line!r}")


class LauncherDamagedInterpreterTests(unittest.TestCase):
    """A .venv interpreter that exists on disk but cannot run must be rebuilt, not handed to pip."""

    def test_run_bat_probes_interpreter_before_install(self):
        text = (REPO / "run.bat").read_text(encoding="utf-8")
        block = text[text.index(":provision"):text.index(":install_deps")]
        self.assertNotIn('if exist "%VENV_PY%" goto install_deps', block,
                         "an existing interpreter must not skip straight to pip")
        probe = block.index('"%VENV_PY%" -c "import sys"')
        usable = block.index('if "%ERRORLEVEL%"=="0" goto install_deps', probe)
        remove = block.index('if exist ".venv" rmdir /s /q ".venv"', usable)
        create = block.index("python -m venv .venv", remove)
        self.assertLess(probe, usable)
        self.assertLess(usable, remove)
        self.assertLess(remove, create)
        self.assertIn("Creating local isolated environment", block[remove:create])

    def test_run_bat_rejects_negative_and_positive_nonzero_exit_codes(self):
        text = (REPO / "run.bat").read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()]
        code = [ln for ln in lines if ln and not ln.lower().startswith("rem") and not ln.startswith("::")]
        setlocal = lines.index("setlocal EnableExtensions")
        self.assertIn('set "ERRORLEVEL="', lines, "a static ERRORLEVEL variable would shadow the real exit code")
        clear = lines.index('set "ERRORLEVEL="')
        self.assertLess(setlocal, clear)
        self.assertLess(clear, lines.index("where python >nul 2>nul"))
        self.assertEqual([ln for ln in code if "errorlevel 1" in ln.lower()], [],
                         "`if errorlevel 1` means >= 1, so negative crash codes pass as success")
        # A negative crash code slips through the old predicate; the emulator must show that.
        self.assertTrue(cmd_if_goto("if not errorlevel 1 goto install_deps", -1073741819))
        # (command prefix, exact check on the next line, True if the goto is the success path)
        checks = [
            ("where python", 'if not "%ERRORLEVEL%"=="0" goto no_python', False),
            ('python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10)', 'if not "%ERRORLEVEL%"=="0" goto old_python', False),
            ('python -c "import hashlib', 'if not "%ERRORLEVEL%"=="0" goto hash_failed', False),
            ('"%VENV_PY%" -c "import sys"', 'if "%ERRORLEVEL%"=="0" goto install_deps', True),
            ("python -m venv .venv", 'if not "%ERRORLEVEL%"=="0" goto venv_failed', False),
            ('"%VENV_PY%" -m pip install', 'if "%ERRORLEVEL%"=="0" goto install_ok', True),
            ('"%VENV_PY%" _pip_helper.py install', 'if not "%ERRORLEVEL%"=="0" goto install_failed', False),
            ('"%VENV_PY%" -c "import streamlit', 'if not "%ERRORLEVEL%"=="0" goto imports_failed', False),
        ]
        for prefix, expected, goto_is_success in checks:
            with self.subTest(command=prefix):
                hits = [i for i, ln in enumerate(code) if ln.startswith(prefix)]
                self.assertEqual(len(hits), 1, f"expected one {prefix!r} line in run.bat")
                self.assertEqual(code[hits[0] + 1], expected)
                for status in (0, -1073741819, -1, 1, 9009):
                    taken = cmd_if_goto(expected, status)
                    self.assertEqual(taken == goto_is_success, status == 0,
                                     f"exit status {status} misclassified by {expected!r}")

    def test_run_command_probes_interpreter_before_install(self):
        text = (REPO / "run.command").read_text(encoding="utf-8")
        block = text[text.index("provision() {"):]
        block = block[:block.index("\n}\n")]
        probe = block.index('"$VENV_PY" -c "import sys"')
        remove = block.index("rm -rf .venv", probe)
        create = block.index("python3 -m venv .venv", remove)
        install = block.index("pip install", create)
        self.assertLess(probe, remove)
        self.assertLess(remove, create)
        self.assertLess(create, install)


UPLOAD_CODEBOOK = "sdoh_basic_needs.yaml"
UPLOAD_MATCHING = b"Participant: The bus was late again and I missed work.\n"
UPLOAD_NON_MATCHING = b"Participant: The weather was pleasant on the walk over.\n"
# Domain names that Streamlit's Markdown and post-parse shortcode plugins would rewrite
# (image, logo shortcode, material icon, >= ligature, link, autolinks, math, color, HTML).
MARKDOWN_IMAGE_DOMAIN = "Transit ![marker](https://example.invalid/pixel.png) :streamlit:"
SHORTCODE_DOMAIN = ("Housing :material_home: Income >= poverty line [link](https://example.invalid/a) "
                    "www.example.invalid someone@example.invalid $x+y$ :red[alert] :smile: *emph* <b>bold</b>")
WORD_JOINER = "\u2060"
MARKDOWN_DOMAIN_CODEBOOK = yaml.safe_dump({
    "program_name": "SOFTWARE_TEST Markdown Domain",
    "version": "1.0",
    "topics": {
        "transit_markdown": {"label": MARKDOWN_IMAGE_DOMAIN, "keywords": ["bus"]},
        "housing_shortcode": {"label": SHORTCODE_DOMAIN, "keywords": ["work"]},
    },
}, allow_unicode=True, sort_keys=False).encode("utf-8")


class UploadNameCollisionTests(unittest.TestCase):
    """Names that a case- or normalization-insensitive filesystem (APFS, NTFS) maps to one
    physical file must be disambiguated so every upload keeps its own bytes.
    SOFTWARE_TEST fixtures: they demonstrate software mechanics only."""

    @classmethod
    def setUpClass(cls):
        cls.safe_upload_name = staticmethod(load_app_helpers("safe_upload_name", "upload_path_key")["safe_upload_name"])

    def assert_distinct_on_disk(self, names):
        taken = set()
        out = [self.safe_upload_name(name, taken) for name in names]
        keys = {unicodedata.normalize("NFC", n).casefold() for n in out}
        self.assertEqual(len(keys), len(names), f"{names} -> {out} share a physical file")
        return out

    def test_case_variants_are_disambiguated(self):
        self.assertEqual(self.assert_distinct_on_disk(["A.txt", "a.txt"]), ["A.txt", "a_2.txt"])
        self.assert_distinct_on_disk(["Notes.TXT", "notes.txt", "NOTES.txt"])

    def test_unicode_normalization_variants_are_disambiguated(self):
        first, second = self.assert_distinct_on_disk(["café.txt", "café.txt"])
        self.assertEqual(first, "café.txt")
        self.assertTrue(second.endswith("_2.txt"), second)
        self.assert_distinct_on_disk(["CAFÉ.txt", "café.txt", "Café.TXT"])

    def test_suffix_cannot_collide_with_a_later_case_variant(self):
        self.assert_distinct_on_disk(["a.txt", "A.txt", "A_2.txt", "a_2.TXT"])

    def test_case_variant_uploads_keep_both_payloads_through_the_app(self):
        at = AppTest.from_file(str(REPO / "app.py"), default_timeout=30)
        at.run()
        box = next(s for s in at.selectbox if s.label == "Corpus Dataset")
        box.select(next(o for o in box.options if "Upload" in o))
        at.run()
        next(s for s in at.selectbox if s.label == "Active YAML Codebook").select(UPLOAD_CODEBOOK)
        at.run()
        at.file_uploader[0].set_value([
            ("A.txt", UPLOAD_MATCHING, "text/plain"),
            ("a.txt", UPLOAD_NON_MATCHING, "text/plain"),
        ])
        at.run()
        # Control: the matching payload alone is coded, so a zero below can only mean it was lost.
        from atlas_engine import AtlasEngine

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "A.txt").write_bytes(UPLOAD_MATCHING)
            control = AtlasEngine(str(REPO / "config" / UPLOAD_CODEBOOK)).process_corpus(
                [str(Path(tmp) / "A.txt")], root_dir=tmp)
        self.assertEqual(int(control["frequencies_df"]["documents_reporting"].sum()), 1)
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(len(at.error), 0, [e.value for e in at.error])
        n_units = next(m for m in at.metric if m.label == "Analytical Units (N)")
        self.assertEqual(int(str(n_units.value)), 2)

        frames = [df.value for df in at.dataframe]
        freq = next(f for f in frames if {"domain_id", "prevalence_pct", "documents_reporting"} <= set(f.columns))
        self.assertEqual(int(freq["documents_reporting"].sum()), 1, freq.to_string())
        self.assertAlmostEqual(float(freq["prevalence_pct"].max()), 50.0, places=1)

        hashes = next(f for f in frames if list(f.columns) == ["source_id", "sha256"])
        self.assertEqual(len(hashes), 2, hashes.to_string())
        self.assertEqual(set(hashes["sha256"]), {hashlib.sha256(UPLOAD_MATCHING).hexdigest(),
                                                 hashlib.sha256(UPLOAD_NON_MATCHING).hexdigest()})


class StreamlitWidthCompatibilityTests(unittest.TestCase):
    """requirements.txt allows streamlit>=1.40.0, but width="stretch" only exists from 1.50."""

    @classmethod
    def setUpClass(cls):
        cls.stretch_kwargs = staticmethod(load_app_helpers("stretch_kwargs")["stretch_kwargs"])

    def test_streamlit_140_gets_use_container_width(self):
        for name in FULL_WIDTH_WIDGETS:
            for version in ("1.40.0", "1.49.9"):
                with self.subTest(widget=name, version=version):
                    self.assertEqual(self.stretch_kwargs(getattr(st, name), version), {"use_container_width": True})

    def test_kwargs_bind_to_a_streamlit_140_signature(self):
        def download_button_140(label, data, *, use_container_width=False):
            return use_container_width

        kwargs = self.stretch_kwargs(download_button_140, "1.40.0")
        inspect.signature(download_button_140).bind("label", b"data", **kwargs)
        self.assertTrue(download_button_140("label", b"data", **kwargs))
        # A newer version string must still not pass width= to a function without it.
        kwargs = self.stretch_kwargs(download_button_140, "1.67.0")
        inspect.signature(download_button_140).bind("label", b"data", **kwargs)

    def test_streamlit_150_plus_gets_width_stretch(self):
        for version in ("1.50.0", "1.67.0", None):
            for name in FULL_WIDTH_WIDGETS:
                with self.subTest(widget=name, version=version):
                    self.assertEqual(self.stretch_kwargs(getattr(st, name), version), {"width": "stretch"})

    def test_every_full_width_widget_call_uses_stretch_kwargs(self):
        tree = ast.parse((REPO / "app.py").read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in FULL_WIDTH_WIDGETS]
        self.assertGreaterEqual(len(calls), 12)
        for call in calls:
            where = f"app.py:{call.lineno} {ast.unparse(call.func)}"
            sizing = [kw.arg for kw in call.keywords if kw.arg in ("width", "use_container_width")]
            self.assertEqual(sizing, [], f"{where} passes a bare sizing keyword")
            spread = [ast.unparse(kw.value) for kw in call.keywords if kw.arg is None]
            self.assertIn(f"stretch_kwargs(st.{call.func.attr})", spread, where)


FIGURE_WIDTHS = {
    "atlas_pipeline_architecture.png": 1160,
    "atlas_codebook_context_fence.png": 1200,
    "atlas_labor_market_distribution.png": 1220,
    "atlas_audit_bridge.png": 1200,
    "atlas_dashboard_ui_walkthrough.png": 1220,
}
# Each alt text must name what its own diagram shows.
FIGURE_ALT_KEYWORDS = {
    "atlas_pipeline_architecture.png": ("pipeline", "UniversalTranscriptParser", "AtlasEngine"),
    "atlas_codebook_context_fence.png": ("context-fence", "PFL_GAP", "fence word"),
    "atlas_labor_market_distribution.png": ("bar chart", "prevalence", "standard error"),
    "atlas_audit_bridge.png": ("audit bridge", "SHA-256", "verify_workbook_integrity"),
    "atlas_dashboard_ui_walkthrough.png": ("workbench", "sidebar", "KPI"),
}
EMBED_COUNTS = {
    "README.md": 5,
    "docs/ATLAS_User_Guide.md": 4,
    "docs/ATLAS_Methodology_and_Reference_Manual.md": 5,
    "docs/ATLAS_Practitioner_Field_Guide_Program_Evaluation.md": 1,
}
PROMOTIONAL_WORDS = ("powerful", "seamless", "cutting-edge", "revolutionary", "effortless", "best-in-class",
                     "world-class", "game-chang", "unlock", "supercharge", "blazing", "stunning", "robust")
CSS_FONT_FLOORS = {".label": 22, ".kicker": 22, ".mono": 22, ".chip": 22, ".foot": 22, ".line": 22, ".sub": 22,
                   ".quote": 24, "h1": 36, ".big": 40}


def load_figures_module():
    spec = importlib.util.spec_from_file_location("atlas_docs_figures", REPO / "scripts" / "generate_docs_figures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def png_size(path: Path):
    raw = path.read_bytes()[:24]
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise AssertionError(f"{path.name} is not a PNG")
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


# A page that breaks every documentation-figure rule once. SOFTWARE_TEST markup.
QA_NEGATIVE_MARKUP = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<div id="figure" style="width:1400px;font-family:Helvetica,Arial,sans-serif;">
  <div class="card" style="border:2px solid #CBD5E1;padding:10px;">
    <div data-node style="font-size:18px;color:#0F172A;">Small text</div></div>
  <div data-node style="width:120px;white-space:nowrap;font-size:22px;color:#0F172A;">
    SOFTWARE_TEST_unbreakable_token_that_cannot_wrap</div>
  <svg width="300" height="60" xmlns="http://www.w3.org/2000/svg">
    <rect x="0" y="0" width="200" height="20" fill="#F1F5F9"/>
    <text data-node x="240" y="40" font-size="22" fill="#0F172A">Clipped label</text>
    <text data-node x="10" y="40" font-size="22" fill="#0F172A">First</text>
    <text data-node x="20" y="44" font-size="22" fill="#0F172A">Second</text>
  </svg>
</div></body></html>"""


class ADAAccessibilityTests(unittest.TestCase):
    """WCAG 2.1 AA: 1.1.1 alt text on the static figures, 1.4.11 non-text contrast and
    GitHub-column legibility for docs/figures/*.png, and a deterministic text summary
    (no AI, no network) for both live Altair charts. SOFTWARE_TEST fixtures only."""

    @classmethod
    def setUpClass(cls):
        cls.figs = load_figures_module()
        with tempfile.TemporaryDirectory() as tmp:
            cls.data = cls.figs.compute(Path(tmp))
        cls.markup = {name: build(cls.data) for name, build in cls.figs.FIGURES.items()}

    @staticmethod
    def helper():
        return load_app_helpers("describe_prevalence_chart")["describe_prevalence_chart"]

    def describe(self, *args, **kwargs):
        return self.helper()(*args, **kwargs)

    # ---- WCAG 1.1.1: alt text on every static figure embed -------------------------
    def test_all_fifteen_figure_embeds_have_descriptive_alt_text(self):
        pattern = re.compile(r"!\[([^\]]*)\]\(([^)]*figures/(atlas_[a-z_]+\.png))\)")
        total = 0
        for rel, expected in EMBED_COUNTS.items():
            embeds = pattern.findall((REPO / rel).read_text(encoding="utf-8"))
            self.assertEqual(len(embeds), expected, f"{rel}: figure embed count")
            total += len(embeds)
            for alt_text, _, name in embeds:
                with self.subTest(doc=rel, figure=name):
                    self.assertIn(name, FIGURE_WIDTHS)
                    self.assertGreaterEqual(len(alt_text.split()), 12, f"alt text too short: {alt_text!r}")
                    self.assertLessEqual(len(re.findall(r"[.!?](\s|$)", alt_text)), 1, f"multi-sentence: {alt_text!r}")
                    self.assertIsNone(re.search(r"2,?500", alt_text), alt_text)
                    for word in PROMOTIONAL_WORDS:
                        self.assertNotIn(word, alt_text.lower())
                    for keyword in FIGURE_ALT_KEYWORDS[name]:
                        self.assertIn(keyword.lower(), alt_text.lower(), f"{name} alt text must mention {keyword!r}")
        self.assertEqual(total, 15)

    # ---- Figure markup: width, font floors, contrast --------------------------------
    def test_figure_canvas_widths_fit_the_github_column(self):
        self.assertEqual(set(self.markup), set(FIGURE_WIDTHS))
        for name, html_text in self.markup.items():
            with self.subTest(figure=name):
                width = int(re.search(r"#figure \{ width: (\d+)px", html_text).group(1))
                self.assertEqual(width, FIGURE_WIDTHS[name])
                self.assertLessEqual(width, 1250)

    def test_every_font_size_is_at_least_22px(self):
        for name, html_text in self.markup.items():
            with self.subTest(figure=name):
                css_sizes = [int(s) for s in re.findall(r"font-size:\s*(\d+)px", html_text)]
                svg_sizes = [int(s) for s in re.findall(r'font-size="(\d+)"', html_text)]
                self.assertTrue(css_sizes)
                self.assertGreaterEqual(min(css_sizes + svg_sizes), 22)
        css = self.markup["atlas_pipeline_architecture.png"]
        for selector, size in CSS_FONT_FLOORS.items():
            with self.subTest(selector=selector):
                rule = re.search(rf"(?m)^{re.escape(selector)} \{{([^}}]*)\}}", css)
                self.assertIsNotNone(rule, selector)
                self.assertEqual(int(re.search(r"font-size:\s*(\d+)px", rule.group(1)).group(1)), size)

    def test_non_text_contrast_card_borders_and_bar_tracks(self):
        for name, html_text in self.markup.items():
            with self.subTest(figure=name):
                card = re.search(r"(?m)^\.card \{([^}]*)\}", html_text).group(1)
                self.assertIn("border: 2px solid #64748B", card)
                self.assertNotIn("#CBD5E1", html_text.upper())
                for rect in re.findall(r"<rect\b[^>]*>", html_text):
                    if 'fill="#F1F5F9"' in rect:
                        self.assertIn('stroke="#64748B"', rect)
                        self.assertIn('stroke-width="1.5"', rect)
        self.assertIn('fill="#F1F5F9"', self.markup["atlas_labor_market_distribution.png"])

    def test_audit_bridge_uses_numbered_steps(self):
        text = self.markup["atlas_audit_bridge.png"]
        steps = ["1. Verbatim quote", "2. Frequency row", "3. Excel cell comment", "4. Integrity check"]
        positions = [text.index(e) for e in (html.escape(s) for s in steps)]
        self.assertEqual(positions, sorted(positions))

    # ---- Rendered figures in Chromium: QA gate and 2x2 layout -----------------------
    def test_browser_qa_gate_and_layout(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = self.figs.launch_chromium(pw)
            try:
                page_ = browser.new_page(viewport={"width": 1800, "height": 1200})
                page_.set_content(QA_NEGATIVE_MARKUP)
                problems = "\n".join(page_.evaluate(self.figs.QA_SCRIPT, sorted(self.figs.ALLOWED_TEXT_COLORS)))
                for needle in ("< 22px", "> 1250px", "horizontal overflow", "card border", "bar track",
                               "past the SVG", "SVG text overlap"):
                    self.assertIn(needle, problems, f"QA gate missed {needle!r}:\n{problems}")

                for name, markup in self.markup.items():
                    with self.subTest(figure=name):
                        page_.set_content(markup)
                        self.assertEqual(page_.evaluate(self.figs.QA_SCRIPT, sorted(self.figs.ALLOWED_TEXT_COLORS)), [])
                        width = page_.evaluate("() => document.getElementById('figure').getBoundingClientRect().width")
                        self.assertEqual(round(width), FIGURE_WIDTHS[name])

                page_.set_content(self.markup["atlas_audit_bridge.png"])
                boxes = page_.evaluate(
                    "() => [...document.querySelectorAll('#figure .card')].map(c => c.getBoundingClientRect())"
                    ".map(r => ({x: Math.round(r.left), y: Math.round(r.top)}))")
                self.assertEqual(len(boxes), 4)
                self.assertEqual(boxes[0]["y"], boxes[1]["y"])
                self.assertEqual(boxes[2]["y"], boxes[3]["y"])
                self.assertLess(boxes[0]["y"], boxes[2]["y"])
                self.assertEqual(boxes[0]["x"], boxes[2]["x"])
                self.assertEqual(boxes[1]["x"], boxes[3]["x"])
                self.assertLess(boxes[0]["x"], boxes[1]["x"])
            finally:
                browser.close()

    def test_committed_pngs_match_canvas_widths(self):
        for name, width in FIGURE_WIDTHS.items():
            with self.subTest(figure=name):
                px_w, px_h = png_size(REPO / "docs" / "figures" / name)
                self.assertEqual(px_w, 2 * width, "device_scale_factor=2 screenshot of the #figure canvas")
                self.assertLessEqual(px_w, 2500)
                self.assertGreater(px_h, 0)

    # ---- describe_prevalence_chart: deterministic chart summary ---------------------
    def frame(self, rows, ci=False):
        import pandas as pd

        cols = ["domain_id", "domain_name", "documents_reporting", "prevalence_pct"]
        if ci:
            cols += ["ci95_low_pct", "ci95_high_pct"]
        return pd.DataFrame(rows, columns=cols)

    def test_describe_empty_and_zero_cases(self):
        self.assertEqual(self.describe(self.frame([]), 10), "No domains defined in the active codebook.")
        self.assertEqual(self.describe(self.frame([]), 0, include_ci=True), "No domains defined in the active codebook.")
        zero = self.frame([("A", "SOFTWARE_TEST Alpha", 0, 0.0), ("B", "SOFTWARE_TEST Beta", 0, 0.0)])
        self.assertEqual(self.describe(zero, 6),
                         "Horizontal bar chart across 6 analytical units showing 0% prevalence across all 2 coded domains.")
        no_units = self.describe(zero, 0)
        self.assertIn("0 analytical units", no_units)
        self.assertIn("2 coded domains", no_units)
        self.assertNotIn("%", no_units.replace("0%", ""))

    def test_describe_sorts_by_prevalence_then_name_and_counts_zero_domains(self):
        df = self.frame([
            ("A", "SOFTWARE_TEST Delta", 3, 30.0), ("B", "SOFTWARE_TEST Zero", 0, 0.0),
            ("C", "SOFTWARE_TEST Gamma", 5, 50.0), ("D", "SOFTWARE_TEST Alpha", 3, 30.0),
        ])
        before = df.copy()
        text = self.describe(df, 10)
        self.assertEqual(text, (
            "Horizontal bar chart across 10 analytical units. Highest prevalence: "
            "SOFTWARE_TEST Gamma 50.0% (5 of 10 units); SOFTWARE_TEST Alpha 30.0% (3 of 10 units); "
            "SOFTWARE_TEST Delta 30.0% (3 of 10 units). Domains with 0% prevalence: 1 of 4."))
        self.assertTrue(df.equals(before), "the helper must not modify its input")
        self.assertEqual(self.describe(df, 10), text, "same input, same text")

    def test_describe_lists_three_and_counts_the_rest(self):
        df = self.frame([(c, f"SOFTWARE_TEST {c}", n, n * 10.0) for c, n in zip("ABCDE", (1, 2, 3, 4, 5))])
        text = self.describe(df, 10)
        self.assertIn("SOFTWARE_TEST E 50.0% (5 of 10 units); SOFTWARE_TEST D 40.0% (4 of 10 units); "
                      "SOFTWARE_TEST C 30.0% (3 of 10 units).", text)
        self.assertIn("Other matched domains not listed: 2.", text)
        self.assertNotIn("Domains with 0% prevalence", text)

    def test_describe_with_confidence_interval(self):
        df = self.frame([("A", "SOFTWARE_TEST Alpha", 1, 16.7, 0.0, 46.5), ("B", "SOFTWARE_TEST Beta", 0, 0.0, 0.0, 0.0)],
                        ci=True)
        self.assertEqual(self.describe(df, 6, include_ci=True), (
            "Horizontal bar chart across 6 analytical units. Highest prevalence: "
            "SOFTWARE_TEST Alpha 16.7% (1 of 6 units, 95% CI 0.0%–46.5%). Domains with 0% prevalence: 1 of 2."))
        self.assertNotIn("95% CI", self.describe(df, 6))

    def test_describe_is_pure_python(self):
        source = ast.get_source_segment((REPO / "app.py").read_text(encoding="utf-8"), next(
            n for n in ast.parse((REPO / "app.py").read_text(encoding="utf-8")).body
            if isinstance(n, ast.FunctionDef) and n.name == "describe_prevalence_chart"))
        for banned in ("http", "requests", "urllib", "socket", "openai", "anthropic", "random", "time."):
            self.assertNotIn(banned, source)
        self.assertIsNone(re.search(r"\bst\.", source), "the helper must not call Streamlit")

    # ---- Both live charts carry the summary as Vega-Lite description and st.html ----
    def test_live_charts_carry_matching_summaries(self):
        import json

        at = AppTest.from_file(str(REPO / "app.py"), default_timeout=60)
        at.run()
        box = next(s for s in at.selectbox if s.label == "Corpus Dataset")
        box.select(next(o for o in box.options if "Survey" in o))
        at.run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        charts = at.get("vega_lite_chart")
        self.assertEqual(len(charts), 2)
        descriptions = [json.loads(c.proto.spec).get("description", "") for c in charts]
        captions = [c.value for c in at.caption]
        html_bodies = [h.value for h in at.html]
        frames = [df.value for df in at.dataframe]
        freq = next(f for f in frames if {"domain_name", "prevalence_pct", "documents_reporting"} <= set(f.columns)
                    and "ci95_low_pct" not in f.columns)
        matrix = next(f for f in frames if "ci95_low_pct" in f.columns)
        n_units = int(str(next(m for m in at.metric if m.label == "Analytical Units (N)").value))
        self.assertEqual(descriptions[0], self.describe(freq, n_units))
        self.assertEqual(descriptions[1], self.describe(matrix, n_units, include_ci=True))
        self.assertIn(f"(1 of {n_units} units)", descriptions[0])
        self.assertNotIn("95% CI", descriptions[0])
        self.assertIn("95% CI", descriptions[1])
        to_html = self.summary_html()
        for text in descriptions:
            self.assertTrue(text.startswith(f"Horizontal bar chart across {n_units} analytical units"), text)
            self.assertIn(to_html(text), html_bodies)
        self.assertFalse([c for c in captions if c.startswith("Chart summary:")],
                         "chart summaries render through st.html, never a Markdown caption")

    # ---- Visible summaries are literal HTML; uploaded domain names stay verbatim ----
    @staticmethod
    def summary_html():
        return load_app_helpers("chart_summary_html")["chart_summary_html"]

    @staticmethod
    def parse_paragraph(markup):
        """(tag names, attributes of the first tag, text) as an HTML parser reads markup."""
        from html.parser import HTMLParser

        class Reader(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.tags, self.attrs, self.text = [], [], []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)
                self.attrs.append(dict(attrs))

            def handle_startendtag(self, tag, attrs):
                self.handle_starttag(tag, attrs)

            def handle_data(self, data):
                self.text.append(data)

        reader = Reader()
        reader.feed(markup)
        reader.close()
        return reader.tags, (reader.attrs[0] if reader.attrs else {}), "".join(reader.text)

    def assert_literal_paragraph(self, markup, summary):
        tags, attrs, text = self.parse_paragraph(markup)
        self.assertEqual(tags, ["p"], f"exactly one <p> and no child elements in {markup!r}")
        self.assertEqual(attrs.get("class"), "atlas-chart-summary")
        self.assertEqual(text, f"Chart summary: {summary}")
        self.assertNotIn(WORD_JOINER, markup)
        self.assertTrue(markup.endswith("</p>"))

    def test_chart_summary_html_is_one_escaped_paragraph(self):
        to_html = self.summary_html()
        self.assertEqual(to_html("Plain words 50 units"), (
            '<p class="atlas-chart-summary" style="font-size:0.875rem;color:#475569;'
            'background-color:#FFFFFF;border:1px solid #64748B;border-radius:4px;'
            'padding:0.4rem 0.65rem;margin:0.25rem 0 0.5rem;line-height:1.45;">'
            'Chart summary: Plain words 50 units</p>'))
        out = to_html("a & b < c > d \" e ' f")
        self.assertIn("Chart summary: a &amp; b &lt; c &gt; d &quot; e &#x27; f</p>", out)
        payloads = [
            MARKDOWN_IMAGE_DOMAIN, SHORTCODE_DOMAIN,
            "[link](https://example.invalid)", "bare https://example.invalid/x and someone@example.invalid",
            ":streamlit: :material_home: :material/home: >= <= -> <-", "<img src=x onerror=alert(1)>",
            "<script>alert(1)</script>", "&amp; &#58; &lt;b&gt;", "C:\\path\\to [x] | # {d} e+f",
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                markup = to_html(payload)
                self.assert_literal_paragraph(markup, payload)
                inner = markup[markup.index(">") + 1:-len("</p>")]
                self.assertIsNone(re.search(r"[<>\"']", inner), f"unescaped HTML metacharacter in {inner!r}")
                self.assertEqual(html.unescape(inner), f"Chart summary: {payload}")
        for literal in (":streamlit:", ":material_home:", "&gt;=", "![marker](https://example.invalid/pixel.png)",
                        "&lt;b&gt;bold&lt;/b&gt;", "$x+y$", ":red[alert]"):
            with self.subTest(literal=literal):
                self.assertIn(literal, to_html(MARKDOWN_IMAGE_DOMAIN + " " + SHORTCODE_DOMAIN))
        self.assertNotIn("\\", to_html(SHORTCODE_DOMAIN), "no Markdown backslash escapes")

    def test_chart_summary_html_collapses_line_breaks(self):
        to_html = self.summary_html()
        markup = to_html("Transit\n# Heading\r\n- item\r> quote\n\n1. step")
        self.assert_literal_paragraph(markup, "Transit # Heading - item > quote 1. step")
        self.assert_literal_paragraph(to_html("a\u2028b\u2029c\x0bd\x0ce\x85f"), "a b c d e f")
        self.assertNotIn("\n", markup)
        self.assertNotIn("\r", markup)

    def test_chart_summary_text_contrast_meets_wcag_aa(self):
        def luminance(hex_color):
            channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(a, b):
            high, low = sorted((luminance(a), luminance(b)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        tags, attrs, _ = self.parse_paragraph(self.summary_html()("x"))
        self.assertEqual(tags, ["p"])
        self.assertEqual(attrs.get("class"), "atlas-chart-summary")
        style = {}
        for declaration in attrs.get("style", "").split(";"):
            name, sep, value = declaration.partition(":")
            if sep:
                style[name.strip().lower()] = value.strip()
        hex_color = re.compile(r"#[0-9A-Fa-f]{6}")
        self.assertRegex(style.get("color", ""), r"^#[0-9A-Fa-f]{6}$")
        color = style["color"]
        # Streamlit Light (#FFFFFF) and Dark (#171614 in 1.67, #0E1117 earlier) page backgrounds.
        pages = ("#FFFFFF", "#171614", "#0E1117")
        background = style.get("background-color")
        if background is None:
            for page in pages:
                with self.subTest(text=color, page=page):
                    ratio = contrast(color, page)
                    self.assertGreaterEqual(ratio, 4.5, f"{color} text on {page} page is {ratio:.2f}:1")
            return
        self.assertRegex(background, r"^#[0-9A-Fa-f]{6}$", "the summary background must be an opaque hex colour")
        ratio = contrast(color, background)
        self.assertGreaterEqual(ratio, 4.5, f"{color} text on {background} is {ratio:.2f}:1")
        border = hex_color.search(style.get("border", ""))
        self.assertIsNotNone(border, "an explicit background needs a visible border colour")
        for page in pages:
            with self.subTest(border=border.group(0), page=page):
                ratio = contrast(border.group(0), page)
                self.assertGreaterEqual(ratio, 3.0, f"{border.group(0)} border on {page} page is {ratio:.2f}:1")

    def test_summaries_use_single_positional_st_html_and_no_markdown_caption(self):
        source = (REPO / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertNotIn("escape_markdown_text", source)
        html_calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "st.html"),
                            key=lambda n: n.lineno)
        self.assertEqual(len(html_calls), 2, "Tab 1 and Tab 2 each render one chart summary")
        for call, arg in zip(html_calls, ("freq_summary", "ci_summary")):
            with self.subTest(line=call.lineno):
                # Streamlit 1.40's st.html(body) has no width=; pass the body positionally only.
                self.assertEqual(call.keywords, [])
                self.assertEqual([ast.unparse(a) for a in call.args], [f"chart_summary_html({arg})"])
        for call in ast.walk(tree):
            if isinstance(call, ast.Call) and ast.unparse(call.func) in ("st.caption", "st.markdown", "st.write"):
                self.assertNotIn("Chart summary", ast.unparse(call), f"app.py:{call.lineno}")
        first = next(iter(inspect.signature(st.html).parameters.values()))
        self.assertEqual(first.name, "body")
        self.assertIn(first.kind, (first.POSITIONAL_ONLY, first.POSITIONAL_OR_KEYWORD))

    def test_describe_tolerates_missing_numbers(self):
        import pandas as pd

        df = self.frame([("A", "SOFTWARE_TEST Alpha", 2, float("nan"), float("nan"), 50.0),
                         ("B", "SOFTWARE_TEST Beta", None, 10.0, 0.0, 30.0),
                         ("C", "SOFTWARE_TEST Gamma", 1, 10.0, None, float("inf"))], ci=True)
        df["documents_reporting"] = df["documents_reporting"].astype(object)
        text = self.describe(df, 10, include_ci=True)
        self.assertNotIn("nan", text.lower())
        self.assertNotIn("inf", text.lower())
        self.assertIn("SOFTWARE_TEST Gamma 10.0% (1 of 10 units, 95% CI n/a–n/a)", text)
        self.assertIn("SOFTWARE_TEST Alpha n/a (2 of 10 units, 95% CI n/a–50.0%)", text)
        self.assertIn("Domains with 0% prevalence: 1 of 3.", text, "a missing count is not a reporting unit")
        self.assertTrue(pd.isna(df.loc[0, "prevalence_pct"]), "the helper must not modify its input")

    def test_describe_tolerates_nullable_pd_na(self):
        import pandas as pd

        df = self.frame([("A", "SOFTWARE_TEST Alpha", 2, pd.NA, pd.NA, 50.0),
                         ("B", "SOFTWARE_TEST Beta", pd.NA, 10.0, 0.0, 30.0),
                         ("C", "SOFTWARE_TEST Gamma", 1, 10.0, pd.NA, 40.0)], ci=True)
        df["documents_reporting"] = df["documents_reporting"].astype("Int64")
        for col in ("prevalence_pct", "ci95_low_pct", "ci95_high_pct"):
            df[col] = df[col].astype("Float64")
        before = df.copy()
        text = self.describe(df, 10, include_ci=True)
        self.assertNotIn("nan", text.lower())
        self.assertNotIn("<na>", text.lower())
        self.assertIn("SOFTWARE_TEST Gamma 10.0% (1 of 10 units, 95% CI n/a–40.0%)", text)
        self.assertIn("SOFTWARE_TEST Alpha n/a (2 of 10 units, 95% CI n/a–50.0%)", text)
        self.assertIn("Domains with 0% prevalence: 1 of 3.", text, "pd.NA count is not a reporting unit")
        self.assertTrue(df.equals(before), "the helper must not modify its input")
        self.assertNotIn("95% CI", self.describe(df, 10))

    def test_markdown_domain_names_are_literal_in_both_summaries(self):
        import json

        at = AppTest.from_file(str(REPO / "app.py"), default_timeout=60)
        at.run()
        box = next(s for s in at.selectbox if s.label == "Corpus Dataset")
        box.select(next(o for o in box.options if "Upload" in o))
        at.run()
        next(s for s in at.selectbox if s.label == "Active YAML Codebook").select("Upload Custom Codebook (.yaml)")
        at.run()
        next(u for u in at.file_uploader if u.label.startswith("Upload Transcript")).set_value(
            [("software_test_markdown_domain.txt", UPLOAD_MATCHING, "text/plain")])
        next(u for u in at.file_uploader if u.label.startswith("Upload Custom Codebook")).set_value(
            ("software_test_markdown_domain.yaml", MARKDOWN_DOMAIN_CODEBOOK, "application/x-yaml"))
        at.run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(len(at.error), 0, [e.value for e in at.error])

        descriptions = [json.loads(c.proto.spec).get("description", "") for c in at.get("vega_lite_chart")]
        self.assertEqual(len(descriptions), 2)
        self.assertFalse([c.value for c in at.caption if c.value.startswith("Chart summary:")],
                         "no chart summary passes through a Markdown caption")
        summaries = [h.value for h in at.html if "atlas-chart-summary" in h.value]
        self.assertEqual(len(summaries), 2, "Tab 1 and Tab 2 each carry one st.html chart summary")
        to_html = self.summary_html()
        for description, markup in zip(descriptions, summaries):
            with self.subTest(markup=markup):
                # Vega-Lite description: plain text, both domain names verbatim.
                for name in (MARKDOWN_IMAGE_DOMAIN, SHORTCODE_DOMAIN):
                    self.assertIn(f"{name} 100.0% (1 of 1 unit", description)
                self.assertNotIn("&lt;", description)
                self.assertNotIn("\\", description)
                # Visible summary: the same text as one literal, HTML-escaped paragraph.
                self.assertEqual(markup, to_html(description))
                self.assert_literal_paragraph(markup, description)


class ReadmeCommandTests(unittest.TestCase):
    def test_readme_runs_final_slice_gate_and_all_smoke_stages(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("scripts/anti_shortcut_gate.py --repo . --slice 4", text)
        self.assertIn("scripts/smoke_test.py --max-stage 5", text)
        self.assertNotIn("--slice 3", text)
        self.assertNotIn("--max-stage 3", text)


if __name__ == "__main__":
    unittest.main()
