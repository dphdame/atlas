"""Slice 1 (A1 + A2) contract tests for ATLAS packaging and transcript ingestion.

Every fixture used here is a labelled SOFTWARE_TEST fixture that demonstrates
software mechanics only; none of its content is an empirical finding.

Run: .venv/bin/python -m unittest tests/test_parser_and_ingestion.py -v
"""

import hashlib
import importlib.util
import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path

import docx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from universal_transcript_parser import UniversalTranscriptParser  # noqa: E402

SAMPLES = REPO_ROOT / "data" / "samples"
BANNER = "[SOFTWARE_TEST FIXTURE — DEMONSTRATES SOFTWARE MECHANICS ONLY, NOT EMPIRICAL FINDINGS]"

BILINGUAL_TXT = SAMPLES / "software_test_bilingual_interview.txt"
TEAMS_DOCX = SAMPLES / "software_test_teams_multiline.docx"
ZOOM_VTT = SAMPLES / "software_test_zoom_session.vtt"
SURVEY_CSV = SAMPLES / "software_test_survey.csv"
SURVEY_XLSX = SAMPLES / "software_test_survey.xlsx"
DUPLICATE_IDS_CSV = SAMPLES / "software_test_duplicate_ids.csv"
ANN_JOANNA_TXT = SAMPLES / "software_test_ann_joanna.txt"
TWO_QUESTIONS_TXT = SAMPLES / "software_test_two_questions.txt"
MAJORITY_TXT = SAMPLES / "software_test_majority.txt"
BINARY_BUILDER = SAMPLES / "software_test_build_binary_fixtures.py"

# SHA-256 of the committed binary fixtures as produced by BINARY_BUILDER.
BINARY_FIXTURE_SHA256 = {
    "software_test_teams_multiline.docx": "5bee36078575a35e03b12cab1fb9985762040689b88dfbbd3e58afcb391b35eb",
    "software_test_survey.xlsx": "716d429a4917a2b9fd9ad5ca65f78fffa87e4c3c0fdc5f84ba1d31fe9e02f104",
}

PROMPT_PATTERN = r"^let me start with our first question"

STRAY_DOCS = [
    "docs/elevenlabs_video_script.md",
    "docs/linkedin_announcement_sequence.md",
    "docs/ATLAS_Visual_Asset_and_Card_Design_System.md",
    "docs/tooearlytosay_methods_article.md",
    "docs/tooearlytosay_methods_article.html",
    "docs/atlas_v1.0.0.zip",
]


def load_binary_builder():
    spec = importlib.util.spec_from_file_location("software_test_build_binary_fixtures", BINARY_BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def turns_by_speaker(turns, speaker):
    return [t for t in turns if t["speaker"] == speaker]


def turn_containing(turns, fragment):
    matches = [t for t in turns if fragment in t["text"]]
    return matches[0] if matches else None


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


class FixtureIntegrityTests(unittest.TestCase):
    """The fixtures themselves must be labelled and intact, so parser failures are real."""

    def test_text_fixtures_carry_banner(self):
        for path in (
            BILINGUAL_TXT, ZOOM_VTT, SURVEY_CSV, DUPLICATE_IDS_CSV,
            ANN_JOANNA_TXT, TWO_QUESTIONS_TXT, MAJORITY_TXT, BINARY_BUILDER,
        ):
            with self.subTest(fixture=path.name):
                self.assertIn(BANNER, path.read_text(encoding="utf-8"))

    def test_binary_fixture_name_and_raw_multiline_paragraph(self):
        self.assertTrue(TEAMS_DOCX.name.startswith("software_test_"))
        raw = [p.text for p in docx.Document(str(TEAMS_DOCX)).paragraphs]
        self.assertIn("\n0:02\nFirst line of response.\nSecond line that used to be dropped.", raw)
        self.assertTrue(SURVEY_XLSX.name.startswith("software_test_"))

    def test_binary_fixtures_match_pinned_hashes(self):
        for name, expected in BINARY_FIXTURE_SHA256.items():
            with self.subTest(fixture=name):
                self.assertEqual(hashlib.sha256((SAMPLES / name).read_bytes()).hexdigest(), expected)

    def test_binary_fixtures_rebuild_byte_for_byte(self):
        builder = load_binary_builder()
        versions = f"python-docx {docx.__version__}"
        self.assertEqual(builder.build_docx_bytes(), TEAMS_DOCX.read_bytes(), versions)
        self.assertEqual(builder.build_xlsx_bytes(), SURVEY_XLSX.read_bytes())


class MultilineDocxTests(unittest.TestCase):
    def test_multiline_timestamp_paragraph_keeps_every_line(self):
        turns = UniversalTranscriptParser().parse_file(str(TEAMS_DOCX))
        turn = turn_containing(turns, "First line of response.")
        self.assertIsNotNone(turn, "first line after the timestamp is missing")
        self.assertIn("Second line that used to be dropped.", turn["text"])
        self.assertEqual(turn["timestamp"], "0:02")

    def test_every_multiline_paragraph_is_lossless(self):
        turns = UniversalTranscriptParser().parse_file(str(TEAMS_DOCX))
        joined = "\n".join(t["text"] for t in turns)
        for fragment in (
            "Let me start with our first question.",
            "First line of response.",
            "Second line that used to be dropped.",
            "Can I ask whether the benefit covers travel time to appointments?",
            "That covers what I wanted to know.",
            "The paperwork took two visits.",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, joined)


class UnicodeSpeakerTests(unittest.TestCase):
    def setUp(self):
        self.turns = UniversalTranscriptParser().parse_file(str(BILINGUAL_TXT))

    def test_accented_and_apostrophe_speakers_are_distinct(self):
        named = {t["speaker"] for t in self.turns if t["speaker"] != "Unknown"}
        self.assertEqual(named, {"Interviewer", "María José Pérez", "O'Connor"})

    def test_accented_speaker_owns_its_text_and_timestamp(self):
        maria = turns_by_speaker(self.turns, "María José Pérez")
        self.assertEqual(len(maria), 2)
        self.assertEqual(maria[0]["timestamp"], "00:01:12")
        self.assertIn("se agotó el beneficio", maria[0]["text"])

    def test_apostrophe_speaker_owns_its_text(self):
        oconnor = turns_by_speaker(self.turns, "O'Connor")
        self.assertEqual(len(oconnor), 2)
        self.assertEqual(oconnor[0]["timestamp"], "00:01:45")
        self.assertIn("protección laboral", oconnor[0]["text"])

    def test_participant_text_is_not_absorbed_into_interviewer_turn(self):
        for turn in turns_by_speaker(self.turns, "Interviewer"):
            self.assertNotIn("se agotó", turn["text"])
            self.assertNotIn("protección laboral", turn["text"])

    def test_accented_text_survives_verbatim(self):
        joined = "\n".join(t["text"] for t in self.turns)
        self.assertIn("se agotó el beneficio", joined)
        self.assertIn("protección laboral", joined)
        self.assertIn("not about protección laboral at all", joined)

    def test_heuristic_marks_only_the_interviewer(self):
        # Interviewer asks 3 of 4 questions; O'Connor asks 1.
        for turn in self.turns:
            if turn["speaker"] == "Unknown":
                continue
            with self.subTest(speaker=turn["speaker"], turn_id=turn["turn_id"]):
                self.assertEqual(turn["is_facilitator"], turn["speaker"] == "Interviewer")


class FacilitatorMatchingTests(unittest.TestCase):
    def test_explicit_name_is_exact_not_substring(self):
        turns = UniversalTranscriptParser(facilitator_names=["Ann"]).parse_file(str(ANN_JOANNA_TXT))
        ann = turns_by_speaker(turns, "Ann")
        joanna = turns_by_speaker(turns, "Joanna")
        self.assertEqual(len(ann), 2)
        self.assertEqual(len(joanna), 2)
        self.assertTrue(all(t["is_facilitator"] for t in ann))
        self.assertFalse(any(t["is_facilitator"] for t in joanna))

    def test_fifty_fifty_question_share_marks_neither_speaker(self):
        turns = UniversalTranscriptParser().parse_file(str(ZOOM_VTT))
        self.assertEqual(len(turns_by_speaker(turns, "Facilitator")), 2)
        self.assertEqual(len(turns_by_speaker(turns, "Participant")), 2)
        flagged = sorted({t["speaker"] for t in turns if t["is_facilitator"]})
        self.assertEqual(flagged, [], "a 50/50 question share must not mark any facilitator")

    def test_vtt_note_block_never_becomes_dialogue(self):
        # WebVTT NOTE blocks are comments; the fixture banner lives in one.
        turns = UniversalTranscriptParser().parse_file(str(ZOOM_VTT))
        for turn in turns:
            with self.subTest(turn_id=turn["turn_id"]):
                self.assertNotIn("NOTE", turn["text"])
                self.assertNotIn("SOFTWARE_TEST", turn["text"])
        self.assertEqual(len(turns), 4)

    def test_fewer_than_three_questions_marks_neither_speaker(self):
        turns = UniversalTranscriptParser().parse_file(str(TWO_QUESTIONS_TXT))
        self.assertEqual(sorted({t["speaker"] for t in turns if t["is_facilitator"]}), [])

    def test_majority_question_share_still_marks_facilitator(self):
        # Control: 3 of 4 questions (> 0.50 share, >= 3 total) must still be detected.
        turns = UniversalTranscriptParser().parse_file(str(MAJORITY_TXT))
        self.assertTrue(all(t["is_facilitator"] for t in turns_by_speaker(turns, "Rosa")))
        self.assertFalse(any(t["is_facilitator"] for t in turns_by_speaker(turns, "Lee")))


class SpeakerlessPromptTests(unittest.TestCase):
    def test_default_retains_speakerless_participant_questions(self):
        parser = UniversalTranscriptParser()
        turns = parser.parse_file(str(TEAMS_DOCX))
        speakerless = [t for t in turns if t["speaker"] == "Unknown"]
        self.assertGreaterEqual(len(speakerless), 4)
        question = turn_containing(turns, "Can I ask whether the benefit covers travel time")
        self.assertIsNotNone(question)
        self.assertEqual(question["speaker"], "Unknown")
        self.assertFalse(question["is_facilitator"])
        self.assertFalse(any(t["is_facilitator"] for t in speakerless))

    def test_explicit_prompt_pattern_flags_or_excludes_matching_turn_with_log(self):
        # Patterns are applied case-insensitively to speakerless turn text.
        parser = UniversalTranscriptParser(interviewer_prompt_patterns=[PROMPT_PATTERN])
        turns = parser.parse_file(str(TEAMS_DOCX))
        excluded = list(getattr(parser, "last_excluded_turns", []) or [])

        prompt = turn_containing(turns, "Let me start with our first question.")
        if prompt is not None:
            self.assertTrue(prompt["is_facilitator"])
            logged = PROMPT_PATTERN in str(prompt.get("exclusion_reason", "")) or any(
                PROMPT_PATTERN in str(entry) for entry in excluded
            )
        else:
            logged = any(
                "Let me start with our first question." in str(entry) and PROMPT_PATTERN in str(entry)
                for entry in excluded
            )
        self.assertTrue(logged, "matched interviewer prompt pattern must be recorded")

        question = turn_containing(turns, "Can I ask whether the benefit covers travel time")
        self.assertIsNotNone(question, "non-matching speakerless participant question was dropped")
        self.assertFalse(question["is_facilitator"])
        response = turn_containing(turns, "First line of response.")
        self.assertIsNotNone(response)
        self.assertFalse(response["is_facilitator"])


class SourceIdentityTests(unittest.TestCase):
    def test_transcript_turns_carry_relative_source_and_unit_ids(self):
        parser = UniversalTranscriptParser()
        for path in (BILINGUAL_TXT, TEAMS_DOCX, ZOOM_VTT):
            with self.subTest(fixture=path.name):
                turns = parser.parse_file(str(path), root_dir=str(REPO_ROOT))
                self.assertTrue(turns)
                for turn in turns:
                    self.assertEqual(turn["source_id"], rel(path))
                    self.assertEqual(turn["unit_id"], rel(path))

    def test_transcript_source_id_defaults_to_canonical_path(self):
        turns = UniversalTranscriptParser().parse_file(str(BILINGUAL_TXT))
        self.assertTrue(turns)
        for turn in turns:
            self.assertEqual(turn["source_id"], BILINGUAL_TXT.resolve().as_posix())
            self.assertEqual(turn["unit_id"], turn["source_id"])


class TabularIngestionTests(unittest.TestCase):
    def parse_survey(self, parser, path=SURVEY_CSV, **kwargs):
        return parser.parse_tabular(
            str(path), text_col="response", speaker_col="role", root_dir=str(REPO_ROOT), **kwargs
        )

    def test_csv_with_id_col_builds_unit_ids_and_skips_blank_rows(self):
        parser = UniversalTranscriptParser()
        turns = self.parse_survey(parser, id_col="respondent_id")
        sid = rel(SURVEY_CSV)
        self.assertEqual(len(turns), 6)
        self.assertEqual(
            [t["unit_id"] for t in turns],
            [f"{sid}::R00{i}" for i in (1, 2, 3, 5, 6, 7)],
        )
        self.assertEqual(len({t["unit_id"] for t in turns}), 6)
        self.assertTrue(all(t["source_id"] == sid for t in turns))
        self.assertEqual(parser.last_skipped_empty_rows, 1)

    def test_csv_turns_keep_text_and_speaker(self):
        turns = self.parse_survey(UniversalTranscriptParser(), id_col="respondent_id")
        by_unit = {t["unit_id"].split("::")[-1]: t for t in turns}
        self.assertEqual(by_unit["R001"]["text"], "Cuando se agotó el beneficio, busqué otro trabajo.")
        self.assertEqual(by_unit["R001"]["speaker"], "participant")
        self.assertEqual(by_unit["R003"]["speaker"], "staff")
        self.assertNotIn("R004", by_unit)

    def test_csv_without_id_col_uses_original_line_numbers(self):
        sid = rel(SURVEY_CSV)
        for blank_id in (None, ""):
            with self.subTest(id_col=blank_id):
                parser = UniversalTranscriptParser()
                turns = self.parse_survey(parser, id_col=blank_id)
                # Header is line 1; the whitespace-only response sits on line 5.
                self.assertEqual(
                    [t["unit_id"] for t in turns],
                    [f"{sid}::row_{n}" for n in (2, 3, 4, 6, 7, 8)],
                )
                self.assertEqual(parser.last_skipped_empty_rows, 1)

    def test_duplicate_ids_raise_unless_allowed(self):
        parser = UniversalTranscriptParser()
        with self.assertRaises(ValueError):
            parser.parse_tabular(
                str(DUPLICATE_IDS_CSV), text_col="response", id_col="respondent_id", speaker_col="role"
            )
        turns = parser.parse_tabular(
            str(DUPLICATE_IDS_CSV),
            text_col="response",
            id_col="respondent_id",
            speaker_col="role",
            root_dir=str(REPO_ROOT),
            allow_duplicate_ids=True,
        )
        self.assertEqual(len(turns), 2)
        self.assertEqual({t["unit_id"] for t in turns}, {f"{rel(DUPLICATE_IDS_CSV)}::R001"})

    def test_xlsx_ingestion_matches_csv_contract(self):
        sid = rel(SURVEY_XLSX)
        parser = UniversalTranscriptParser()
        turns = self.parse_survey(parser, path=SURVEY_XLSX, id_col="respondent_id")
        self.assertEqual([t["unit_id"] for t in turns], [f"{sid}::R001", f"{sid}::R003"])
        self.assertTrue(all(t["source_id"] == sid for t in turns))
        self.assertEqual(turns[0]["text"], "Cuando se agotó el beneficio, busqué otro trabajo.")
        self.assertEqual(turns[0]["speaker"], "participant")
        self.assertEqual(parser.last_skipped_empty_rows, 1)
        unkeyed = self.parse_survey(UniversalTranscriptParser(), path=SURVEY_XLSX, id_col=None)
        # Spreadsheet row numbers: header is row 1, whitespace-only response is row 3.
        self.assertEqual([t["unit_id"] for t in unkeyed], [f"{sid}::row_2", f"{sid}::row_4"])


class RepoHygieneAndLauncherTests(unittest.TestCase):
    def test_mit_license_present(self):
        lic = REPO_ROOT / "LICENSE"
        self.assertTrue(lic.is_file(), "LICENSE file is missing")
        text = lic.read_text(encoding="utf-8")
        self.assertIn("MIT License", text)
        self.assertIn("Permission is hereby granted, free of charge", text)
        self.assertIn("Victoria E. Cholette", text)

    def test_gitignore_ignores_dot_venv(self):
        lines = [ln.strip() for ln in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(".venv/" in lines or ".venv" in lines, ".gitignore must ignore .venv/")

    def test_requirements_declare_runtime_dependencies(self):
        lines = [
            ln.split("#")[0].strip().lower()
            for ln in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("streamlit>=1.40.0", lines)
        names = {ln.split(">")[0].split("=")[0].split("<")[0].strip() for ln in lines if ln}
        for pkg in ("python-docx", "pyarrow", "scikit-learn", "pyyaml", "openpyxl", "pandas"):
            with self.subTest(package=pkg):
                self.assertIn(pkg, names)

    def test_stray_docs_removed(self):
        present = [p for p in STRAY_DOCS if (REPO_ROOT / p).exists()]
        self.assertEqual(present, [])

    def test_run_bat_supports_check_only(self):
        self.assertIn("--check-only", (REPO_ROOT / "run.bat").read_text(encoding="utf-8"))

    def test_run_command_check_only_exits_without_launching_streamlit(self):
        env = dict(os.environ)
        env["BROWSER"] = "true"  # never open a real browser if a legacy launcher starts Streamlit
        if os.name == "nt":
            argv = ["cmd", "/c", "run.bat", "--check-only"]
        else:
            argv = ["bash", "run.command", "--check-only"]
        proc = subprocess.Popen(
            argv,
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        timed_out = False
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if hasattr(os, "killpg"):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
        if timed_out:
            proc.communicate()
            self.fail("run.command --check-only did not exit within 5 seconds (Streamlit likely launched)")
        output = out.decode("utf-8", "replace") + err.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, output)
        self.assertNotIn("You can now view your Streamlit app", output)
        self.assertNotIn("Launching ATLAS Desktop Interface", output)


if __name__ == "__main__":
    unittest.main()
