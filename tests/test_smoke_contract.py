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

import importlib.util
import os
import re
import socket
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl
import yaml

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

    def test_codebook_audit_compiles_all_six(self):
        compiled = self.smoke.codebook_audit(REPO / "config")
        expected = sorted(p.name for p in (REPO / "config").glob("*.yaml"))
        self.assertEqual(len(expected), 6)
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
        self.assertEqual(sorted(scenarios), ["empty .venv without marker", "stale marker and damaged interpreter"])
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / ".venv"
            scenarios["stale marker and damaged interpreter"](venv)
            exe = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            self.assertTrue(exe.is_file())
            self.assertTrue((venv / ".atlas_deps.sha256").is_file())
        source = (REPO / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
        check = source[source.index("def broken_venv_check"):source.index("def stage2")]
        self.assertIn('if "Creating local isolated environment" not in output:', check,
                      "every damaged .venv must be recreated in the same run, on every platform")

    def test_workflow_sets_no_elapsed_time_ceiling(self):
        self.assertNotIn("timeout-minutes", WORKFLOW.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
