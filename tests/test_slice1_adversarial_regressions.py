"""Slice 1 repair round 1: regressions for the twelve Codex review findings.

Every input built here is a SOFTWARE_TEST fixture that demonstrates software
mechanics only; none of its content is an empirical finding. Scratch inputs are
written under tempfile's directory (honours TMPDIR).

Run: .venv/bin/python -m unittest tests/test_slice1_adversarial_regressions.py -v
"""

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import docx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from universal_transcript_parser import UniversalTranscriptParser  # noqa: E402

SAMPLES = REPO_ROOT / "data" / "samples"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke_test.py"
BANNER_FRAGMENT = "SOFTWARE_TEST FIXTURE"
IS_WINDOWS = os.name == "nt"


class ScratchMixin:
    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory(prefix="atlas_r1_")
        self.scratch = Path(self._scratch.name)

    def tearDown(self):
        self._scratch.cleanup()

    def write(self, name: str, text: str) -> str:
        path = self.scratch / name
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return str(path)


def texts(turns):
    return [t["text"] for t in turns]


# ----------------------------------------------------------------------
# #1, #6 Word documents
# ----------------------------------------------------------------------
class WordTableTests(ScratchMixin, unittest.TestCase):
    def build_tables_docx(self) -> str:
        document = docx.Document()
        document.add_paragraph("Alice: Opening paragraph before any table.")
        small = document.add_table(rows=2, cols=3)
        for cell, value in zip(small.rows[0].cells, ("Speaker", "Dialogue", "Timestamp")):
            cell.text = value
        for cell, value in zip(small.rows[1].cells, ("Bob", "Answer from the two-row table.", "00:00:10")):
            cell.text = value
        document.add_paragraph("Alice: Middle paragraph between the tables.")
        large = document.add_table(rows=4, cols=3)
        rows = [
            ("Speaker", "Dialogue", "Timestamp"),
            ("Carol", "First row of the four-row table.", "00:01:00"),
            ("Dan", "Second row of the four-row table.", "00:01:20"),
            ("Carol", "Third row of the four-row table.", "00:01:40"),
        ]
        for row, values in zip(large.rows, rows):
            for cell, value in zip(row.cells, values):
                cell.text = value
        path = self.scratch / "software_test_tables.docx"
        document.save(str(path))
        return str(path)

    def test_paragraphs_and_tables_kept_in_document_order(self):
        turns = UniversalTranscriptParser().parse_file(self.build_tables_docx())
        self.assertEqual(
            [(t["speaker"], t["text"]) for t in turns],
            [
                ("Alice", "Opening paragraph before any table."),
                ("Bob", "Answer from the two-row table."),
                ("Alice", "Middle paragraph between the tables."),
                ("Carol", "First row of the four-row table."),
                ("Dan", "Second row of the four-row table."),
                ("Carol", "Third row of the four-row table."),
            ],
        )
        self.assertEqual(turns[1]["timestamp"], "00:00:10")
        self.assertNotIn("Speaker", {t["speaker"] for t in turns})

    def test_word_locations_are_one_based_and_ordered(self):
        turns = UniversalTranscriptParser().parse_file(self.build_tables_docx())
        lines = [t["line_number"] for t in turns]
        self.assertTrue(all(n >= 1 for n in lines), lines)
        self.assertEqual(lines, sorted(lines))
        self.assertEqual(len(set(lines)), len(lines))

    def test_paragraph_locations_are_one_based(self):
        document = docx.Document()
        document.add_paragraph("Alice: First paragraph.")
        document.add_paragraph("Bob: Second paragraph.")
        path = self.scratch / "software_test_paragraphs.docx"
        document.save(str(path))
        turns = UniversalTranscriptParser().parse_file(str(path))
        self.assertEqual([t["line_number"] for t in turns], [1, 2])

    def test_meeting_recording_phrase_in_dialogue_is_kept(self):
        document = docx.Document()
        document.add_paragraph("Alice: I watched the Meeting Recording yesterday.")
        path = self.scratch / "software_test_meeting_phrase.docx"
        document.save(str(path))
        turns = UniversalTranscriptParser().parse_file(str(path))
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["speaker"], "Alice")
        self.assertEqual(turns[0]["text"], "I watched the Meeting Recording yesterday.")

    def test_teams_export_header_is_still_dropped(self):
        document = docx.Document()
        document.add_paragraph("Program Check-in-20261119_100000-Meeting Recording")
        document.add_paragraph("Alice: Hello.")
        path = self.scratch / "software_test_teams_header.docx"
        document.save(str(path))
        turns = UniversalTranscriptParser().parse_file(str(path))
        self.assertEqual(texts(turns), ["Hello."])


# ----------------------------------------------------------------------
# #2, #4 Subtitles
# ----------------------------------------------------------------------
class SubtitleTests(ScratchMixin, unittest.TestCase):
    def test_voice_change_within_cue_flushes_separate_turns(self):
        layouts = {
            "separate_lines": "<v Alice>First.</v>\n<v Bob>Second.</v>\n",
            "same_line": "<v Alice>First.</v> <v Bob>Second.</v>\n",
        }
        for name, payload in layouts.items():
            with self.subTest(layout=name):
                path = self.write(
                    f"software_test_{name}.vtt",
                    "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n" + payload
                    + "\n00:00:04.000 --> 00:00:05.000\nAn unlabelled answer.\n",
                )
                turns = UniversalTranscriptParser(facilitator_names=["Alice"]).parse_file(path)
                self.assertEqual(
                    [(t["speaker"], t["text"]) for t in turns],
                    [("Alice", "First."), ("Bob", "Second."), ("Unknown", "An unlabelled answer.")],
                )
                self.assertEqual([t["is_facilitator"] for t in turns], [True, False, False])

    def test_numeric_srt_answer_is_kept(self):
        path = self.write(
            "software_test_numeric.srt",
            "1\n00:00:01,000 --> 00:00:02,000\nInterviewer: What year did you start?\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\n2026\n",
        )
        turns = UniversalTranscriptParser().parse_file(path)
        self.assertEqual(texts(turns), ["What year did you start?", "2026"])
        for turn in turns:
            self.assertNotIn(turn["text"], ("1", "2"))

    def test_non_numeric_vtt_cue_ids_are_not_dialogue(self):
        path = self.write(
            "software_test_cue_ids.vtt",
            "WEBVTT\n\ncue-a\n00:00:01.000 --> 00:00:02.000\n<v Alice>Hello there.</v>\n\n"
            "cue-b\n00:00:03.000 --> 00:00:04.000\n<v Bob>Hi.</v>\n",
        )
        turns = UniversalTranscriptParser().parse_file(path)
        self.assertEqual([(t["speaker"], t["text"]) for t in turns], [("Alice", "Hello there."), ("Bob", "Hi.")])


# ----------------------------------------------------------------------
# #3, #5 Speaker labels
# ----------------------------------------------------------------------
class SpeakerLabelTests(ScratchMixin, unittest.TestCase):
    def test_explicit_facilitator_matches_canonically_equivalent_name(self):
        path = self.write("software_test_nfd.txt", "María: How are you?\nBob: Fine.\n")
        turns = UniversalTranscriptParser(facilitator_names=["María"]).parse_file(path)
        self.assertEqual([t["is_facilitator"] for t in turns], [True, False])
        self.assertEqual(turns[0]["speaker"], "María", "display label must stay verbatim")

    def test_auto_detection_pools_nfc_and_nfd_spellings(self):
        path = self.write(
            "software_test_nfc_nfd_pool.txt",
            "María: First question?\n"
            "Bob: An answer. Is that enough?\n"
            "María: Second question?\n"
            "Bob: Another answer.\n"
            "María: Third question?\n"
            "María: Fourth question?\n",
        )
        turns = UniversalTranscriptParser().parse_file(path)
        for turn in turns:
            with self.subTest(speaker=turn["speaker"], turn_id=turn["turn_id"]):
                self.assertEqual(turn["is_facilitator"], turn["speaker"] != "Bob")

    def test_nfd_initial_uppercase_speaker_is_parsed(self):
        path = self.write("software_test_emilie.txt", "Émilie: Bonjour.\n")
        turns = UniversalTranscriptParser().parse_file(path)
        self.assertEqual(len(turns), 1)
        self.assertIn(turns[0]["speaker"], ("Émilie", "Émilie"))
        self.assertEqual(turns[0]["text"], "Bonjour.")

    def test_colon_prose_stays_with_current_speaker(self):
        path = self.write("software_test_colon_prose.txt", "Alice: I need help.\nMy main concern is: transport.\n")
        turns = UniversalTranscriptParser().parse_file(path)
        self.assertEqual(
            [(t["speaker"], t["text"]) for t in turns],
            [("Alice", "I need help. My main concern is: transport.")],
        )

    def test_multiword_names_with_particles_are_still_speakers(self):
        path = self.write(
            "software_test_particles.txt",
            "Juan de la Cruz: Hola.\nMaría José Pérez [00:01:12]: Bien.\nSpeaker 2: Okay.\n",
        )
        turns = UniversalTranscriptParser().parse_file(path)
        self.assertEqual([t["speaker"] for t in turns], ["Juan de la Cruz", "María José Pérez", "Speaker 2"])

    # Round 2: internal capitals, particles, lowercase surnames and '&' joiners.
    PARTICIPANT_LABELS = (
        "Jane duPont",
        "Jean-Luc d'Artagnan",
        "Damaris estrada",
        "Gabriel Manrique & Yurina Guzman",
        "The Moderator",
        "Will Smith",
        "May Chen",
        "Will",
    )

    def test_participant_labels_start_their_own_turn(self):
        for label in self.PARTICIPANT_LABELS:
            with self.subTest(label=label):
                path = self.write("software_test_participant_label.txt",
                                  f"Interviewer: A question?\n{label}: Participant answer.\n")
                turns = UniversalTranscriptParser(facilitator_names=["Interviewer"]).parse_file(path)
                self.assertEqual(
                    [(t["speaker"], t["text"], t["is_facilitator"]) for t in turns],
                    [("Interviewer", "A question?", True), (label, "Participant answer.", False)],
                )

    def test_participant_labels_in_word_paragraphs(self):
        for label in self.PARTICIPANT_LABELS:
            with self.subTest(label=label):
                document = docx.Document()
                document.add_paragraph("Interviewer: A question?")
                document.add_paragraph(f"{label}: Participant answer.")
                path = self.scratch / "software_test_participant_label.docx"
                document.save(str(path))
                turns = UniversalTranscriptParser(facilitator_names=["Interviewer"]).parse_file(str(path))
                self.assertEqual([t["speaker"] for t in turns], ["Interviewer", label])
                self.assertEqual([t["is_facilitator"] for t in turns], [True, False])

    def test_timestamp_disambiguates_lowercase_label(self):
        path = self.write("software_test_ts_lowercase.txt",
                          "Interviewer: A question?\njane doe [00:00:05]: Participant answer.\n")
        turns = UniversalTranscriptParser(facilitator_names=["Interviewer"]).parse_file(path)
        self.assertEqual([(t["speaker"], t["timestamp"]) for t in turns],
                         [("Interviewer", ""), ("jane doe", "00:00:05")])

    def test_verb_question_labels_stay_with_current_speaker(self):
        # A capitalized verb starts a name ("Will Smith", "May Chen") but not a question.
        for prose in ("May I: ask one more thing?", "Can I: add something?", "Will You: repeat that?",
                      "Can We: talk later?", "Do You: mean the clinic?"):
            with self.subTest(prose=prose):
                path = self.write("software_test_verb_question.txt",
                                  f"Interviewer: A question?\nParticipant: My answer.\n{prose}\n")
                turns = UniversalTranscriptParser(facilitator_names=["Interviewer"]).parse_file(path)
                self.assertEqual(
                    [(t["speaker"], t["text"], t["is_facilitator"]) for t in turns],
                    [("Interviewer", "A question?", True), ("Participant", f"My answer. {prose}", False)],
                )

    def test_prose_colon_lines_stay_with_current_speaker(self):
        for prose in ("My main concern is: transport.", "The main issue: cost.", "Step 1: apply online."):
            with self.subTest(prose=prose):
                path = self.write("software_test_prose_colon.txt", f"Alice: I need help.\n{prose}\n")
                turns = UniversalTranscriptParser().parse_file(path)
                self.assertEqual([(t["speaker"], t["text"]) for t in turns],
                                 [("Alice", f"I need help. {prose}")])


# ----------------------------------------------------------------------
# Round 3: hardened speaker attribution (txt and Word paragraphs)
# ----------------------------------------------------------------------
class HardenedSpeakerAttributionTests(ScratchMixin, unittest.TestCase):
    FORMATS = ("txt", "docx")

    def parse(self, fmt, lines, facilitators=("Interviewer",)):
        """Parse the same SOFTWARE_TEST lines as a .txt file or as Word paragraphs."""
        parser = UniversalTranscriptParser(facilitator_names=list(facilitators))
        if fmt == "txt":
            return parser.parse_file(self.write("software_test_r3.txt", "\n".join(lines) + "\n"))
        document = docx.Document()
        for line in lines:
            document.add_paragraph(line)
        path = self.scratch / "software_test_r3.docx"
        document.save(str(path))
        return parser.parse_file(str(path))

    def turns(self, fmt, lines, facilitators=("Interviewer",)):
        return [(t["speaker"], t["text"], t["is_facilitator"]) for t in self.parse(fmt, lines, facilitators)]

    # Capitalized homographs of verbs, determiners and metadata words are names.
    HOMOGRAPH_NAMES = (
        "Mary May", "Jane Do", "Min Son", "My Tran", "Thea May", "Can Yaman", "Do Kwon",
        "Son Heung-min", "Sin Kim", "Hay Tran", "An Nguyen", "Note Nguyen", "La Voz",
        "His Holiness", "Will", "May",
    )

    def test_homographic_names_are_not_absorbed_into_facilitator(self):
        for fmt in self.FORMATS:
            for label in self.HOMOGRAPH_NAMES:
                with self.subTest(fmt=fmt, label=label):
                    self.assertEqual(
                        self.turns(fmt, ["Interviewer: What happened?", f"{label}: Participant answer."]),
                        [("Interviewer", "What happened?", True), (label, "Participant answer.", False)],
                    )

    def assert_prose(self, fmt, prose):
        self.assertEqual(
            self.turns(fmt, ["Interviewer: A question?", "Participant 1: My answer.", prose]),
            [("Interviewer", "A question?", True), ("Participant 1", f"My answer. {prose}", False)],
        )

    def test_single_word_metadata_verb_and_scheme_labels_stay_prose(self):
        lines = ("Note: this is off the record.", "Summary: two barriers.", "Example: the bus.",
                 "Date: 2026-11-19.", "Location: the clinic.", "HTTPS: secure portal.", "Is: unclear.",
                 "Said: nothing more.", "First: transport.", "Question: who decides?",
                 "Sftp://files.example.org/upload", "Intake https://example.org/form")
        for fmt in self.FORMATS:
            for prose in lines:
                with self.subTest(fmt=fmt, prose=prose):
                    self.assert_prose(fmt, prose)

    def test_title_case_headings_and_outline_enumerators_stay_prose(self):
        lines = ("My Problem: the hours.", "My Boss: never flexible.", "Our Goal: stable housing.",
                 "The Problem: cost.", "Key Takeaways: two.", "Action Items: call back.",
                 "Next Steps: apply.", "Main Concern: rent.", "Option A: walk.", "Part II: follow-up.",
                 "Section 3: eligibility.", "Figure 1: wait times.", "Table 2: income.", "Note One: cost.",
                 "Step One: register.", "Is It: always this slow?", "Are They: open late?")
        for fmt in self.FORMATS:
            for prose in lines:
                with self.subTest(fmt=fmt, prose=prose):
                    self.assert_prose(fmt, prose)

    def test_speaker_ids_and_one_word_names_remain_speakers(self):
        labels = ("Participant 1", "Speaker 2", "CHW #2", "The Moderator", "Informant A", "Alice",
                  "Émilie", "Moderator", "Participant", "P1", "Speaker_01")
        for fmt in self.FORMATS:
            for label in labels:
                with self.subTest(fmt=fmt, label=label):
                    self.assertEqual(
                        self.turns(fmt, ["Interviewer: A question?", f"{label}: Participant answer."]),
                        [("Interviewer", "A question?", True), (label, "Participant answer.", False)],
                    )

    def test_explicit_facilitator_name_overrides_metadata_heuristic(self):
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                self.assertEqual(
                    self.turns(fmt, ["Note: Facilitator question?", "Alice: Answer."], facilitators=("Note",)),
                    [("Note", "Facilitator question?", True), ("Alice", "Answer.", False)],
                )

    def test_trailing_colon_does_not_swallow_next_speaker(self):
        cases = {
            "multi_word_name": (["Interviewer: Answer this:", "Mary May: My answer."], self.FORMATS),
            "timestamped_name": (["Interviewer: Consider this:", "Alice [00:00:05]: My answer."], ("txt",)),
            "blank_line_reset": (["Interviewer: Consider this:", "", "Alice: My answer."], self.FORMATS),
        }
        for name, (lines, formats) in cases.items():
            speaker = lines[-1].split(" [")[0].split(":")[0]
            for fmt in formats:
                with self.subTest(case=name, fmt=fmt):
                    turns = self.turns(fmt, lines)
                    self.assertEqual([(s, f) for s, _, f in turns], [("Interviewer", True), (speaker, False)])
                    self.assertEqual(turns[1][1], "My answer.")


class FormatTurnsMixin(ScratchMixin):
    """The same SOFTWARE_TEST lines parsed as .txt, Word paragraphs or WebVTT cues."""

    FORMATS = ("txt", "docx")

    def parser(self, facilitators=("Interviewer",)):
        return UniversalTranscriptParser(facilitator_names=list(facilitators))

    def turns(self, fmt, lines, facilitators=("Interviewer",)):
        """(speaker, text, is_facilitator) for SOFTWARE_TEST lines as .txt or Word paragraphs."""
        if fmt == "txt":
            path = self.write("software_test_r4.txt", "\n".join(lines) + "\n")
        else:
            document = docx.Document()
            for line in lines:
                document.add_paragraph(line)
            path = str(self.scratch / "software_test_r4.docx")
            document.save(path)
        return [(t["speaker"], t["text"], t["is_facilitator"]) for t in self.parser(facilitators).parse_file(path)]

    def vtt_turns(self, cues, facilitators=("Interviewer",)):
        """(speaker, text, is_facilitator) for a WebVTT file with one cue per list of payload lines."""
        body = "".join(
            f"00:00:{2 * i + 1:02d}.000 --> 00:00:{2 * i + 2:02d}.000\n" + "\n".join(cue) + "\n\n"
            for i, cue in enumerate(cues)
        )
        path = self.write("software_test_r4.vtt", "WEBVTT\n\n" + body)
        return [(t["speaker"], t["text"], t["is_facilitator"]) for t in self.parser(facilitators).parse_file(path)]


# ----------------------------------------------------------------------
# Round 4: facilitator colons, table speakers, name particles, voice spans
# and URI schemes (txt, Word paragraphs and WebVTT)
# ----------------------------------------------------------------------
class Round4AttributionTests(FormatTurnsMixin, unittest.TestCase):
    # Finding 1: one-word participants after a facilitator's trailing colon.
    def test_one_word_participant_after_facilitator_colon_starts_own_turn(self):
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                self.assertEqual(
                    self.turns(fmt, ["Interviewer: Please answer this:", "May: I lost my job."]),
                    [("Interviewer", "Please answer this:", True), ("May", "I lost my job.", False)],
                )

    def build_table_then_paragraphs_docx(self, header: bool) -> str:
        document = docx.Document()
        rows = [("Speaker", "Dialogue", "Timestamp")] if header else []
        rows.append(("Alice", "I attended the first session.", "00:00:05"))
        table = document.add_table(rows=len(rows), cols=3)
        for row, values in zip(table.rows, rows):
            for cell, value in zip(row.cells, values):
                cell.text = value
        document.add_paragraph("Bob: Two things matter:")
        document.add_paragraph("Alice: I agree with Bob.")
        path = self.scratch / f"software_test_r4_table_{header}.docx"
        document.save(str(path))
        return str(path)

    def test_word_table_speaker_is_confirmed_for_later_paragraphs(self):
        for header in (True, False):
            with self.subTest(header=header):
                turns = self.parser().parse_file(self.build_table_then_paragraphs_docx(header))
                self.assertEqual(
                    [(t["speaker"], t["text"], t["is_facilitator"]) for t in turns],
                    [
                        ("Alice", "I attended the first session.", False),
                        ("Bob", "Two things matter:", False),
                        ("Alice", "I agree with Bob.", False),
                    ],
                )

    # Finding 2: lowercase name particles inside multi-word names.
    PARTICLE_NAMES = ("Maria do Carmo", "José do Nascimento", "Will van der Meer", "May de la Cruz")

    def test_names_with_interior_particles_start_their_own_turn(self):
        expected = lambda name: [("Interviewer", "What happened?", True), (name, "Participant answer.", False)]
        for name in self.PARTICLE_NAMES:
            for fmt in self.FORMATS:
                with self.subTest(fmt=fmt, name=name):
                    self.assertEqual(
                        self.turns(fmt, ["Interviewer: What happened?", f"{name}: Participant answer."]),
                        expected(name),
                    )
            with self.subTest(fmt="vtt", name=name):
                self.assertEqual(
                    self.vtt_turns([["Interviewer: What happened?"], [f"{name}: Participant answer."]]),
                    expected(name),
                )
            with self.subTest(fmt="vtt_same_cue", name=name):
                self.assertEqual(
                    self.vtt_turns([["Interviewer: What happened?", f"{name}: Participant answer."]]),
                    expected(name),
                )

    def test_trailing_or_verb_lowercase_words_still_stay_prose(self):
        for prose in ("Jane do: the paperwork.", "Jane may: call later.", "My main concern is: rent.",
                      "Maria do: the forms."):
            for fmt in self.FORMATS:
                with self.subTest(fmt=fmt, prose=prose):
                    self.assertEqual(
                        self.turns(fmt, ["Interviewer: A question?", "Participant 1: My answer.", prose]),
                        [("Interviewer", "A question?", True), ("Participant 1", f"My answer. {prose}", False)],
                    )

    # A lone one-word label after any speaker's trailing colon is a speaker change.
    def test_lone_one_word_label_after_participant_colon_starts_own_turn(self):
        lines = ["Interviewer: Barriers?", "Bob: Two things:", "May: I lost my job."]
        expected = [("Interviewer", "Barriers?", True), ("Bob", "Two things:", False),
                    ("May", "I lost my job.", False)]
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                self.assertEqual(self.turns(fmt, lines), expected)
        with self.subTest(fmt="vtt"):
            self.assertEqual(self.vtt_turns([lines[:1], lines[1:]]), expected)

    # Finding 4: an open WebVTT voice span keeps its speaker over colon lines.
    def test_vtt_voice_span_keeps_attribution_over_colon_lines(self):
        cases = {
            "participant": (
                ["<v Mary May>Two barriers:", "Childcare: cost.", "Transport: bus schedule.</v>"],
                [("Mary May", "Two barriers: Childcare: cost. Transport: bus schedule.", False)],
            ),
            "facilitator": (
                ["<v Interviewer>Two items:", "Childcare: cost.</v>"],
                [("Interviewer", "Two items: Childcare: cost.", True)],
            ),
            "unclosed_span": (
                ["<v Mary May>Two barriers:", "Childcare: cost."],
                [("Mary May", "Two barriers: Childcare: cost.", False)],
            ),
        }
        for name, (cue, expected) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.vtt_turns([cue]), expected)

    def test_vtt_voice_span_closes_back_to_cue_speaker(self):
        self.assertEqual(
            self.vtt_turns([["<v Interviewer>Next?</v>", "Alice: My answer."]]),
            [("Interviewer", "Next?", True), ("Alice", "My answer.", False)],
        )

    # Finding 5: non-HTTP URI schemes are not speakers.
    URI_LINES = ("Mailto:alice@example.org", "Tel:+15555550100", "Urn:isbn:9780123456789",
                 "Data:text/plain", "File:/tmp/a", "Sms:+15555550100", "Sip:alice@example.org",
                 "Ssh:host.example.org", "Git:repo.example.org", "Mailto: alice@example.org")

    def test_non_http_uri_schemes_stay_prose(self):
        for prose in self.URI_LINES:
            expected = [("Interviewer", "A question?", True), ("Participant 1", f"My answer. {prose}", False)]
            for fmt in self.FORMATS:
                with self.subTest(fmt=fmt, prose=prose):
                    self.assertEqual(
                        self.turns(fmt, ["Interviewer: A question?", "Participant 1: My answer.", prose]),
                        expected,
                    )
            with self.subTest(fmt="vtt", prose=prose):
                self.assertEqual(
                    self.vtt_turns([["Interviewer: A question?"], ["Participant 1: My answer.", prose]]),
                    expected,
                )


# ----------------------------------------------------------------------
# Round 5: no flush-left colon-list guessing. A flush-left "Name: text" line
# always starts a turn; bulleted or numbered items stay in the current turn;
# an open WebVTT voice span keeps its speaker.
# ----------------------------------------------------------------------
class Round5ColonListTests(FormatTurnsMixin, unittest.TestCase):
    def assert_all_formats(self, lines, expected, facilitators=("Interviewer",)):
        """txt, Word paragraphs and a single WebVTT cue holding every line."""
        for fmt in self.FORMATS:
            with self.subTest(fmt=fmt):
                self.assertEqual(self.turns(fmt, lines, facilitators), expected)
        with self.subTest(fmt="vtt_same_cue"):
            self.assertEqual(self.vtt_turns([lines], facilitators), expected)

    # Codex R4 finding 1: one-word replies after a facilitator's trailing colon.
    def test_one_word_replies_after_facilitator_colon_are_separate_turns(self):
        self.assert_all_formats(
            ["Interviewer: Please answer this:", "May: I lost my job.", "Bob: I lost my housing."],
            [("Interviewer", "Please answer this:", True), ("May", "I lost my job.", False),
             ("Bob", "I lost my housing.", False)],
        )

    # Codex R4 finding 2: adjacent participant turns after colons never merge.
    BULLETS = {"dash": ("- ", "- "), "asterisk": ("* ", "* "), "numbered": ("1. ", "2. "), "bullet": ("• ", "• ")}

    def test_bulleted_list_items_stay_in_each_participant_turn(self):
        for name, (first, second) in self.BULLETS.items():
            with self.subTest(marker=name):
                self.assert_all_formats(
                    ["Alice: Two issues:", f"{first}Childcare: cost.", f"{second}Transport: bus.",
                     "Bob: Same two:", f"{first}Childcare: expensive.", f"{second}Transport: no car."],
                    [("Alice", f"Two issues: {first}Childcare: cost. {second}Transport: bus.", False),
                     ("Bob", f"Same two: {first}Childcare: expensive. {second}Transport: no car.", False)],
                )

    def test_adjacent_participant_turns_after_colons_never_merge(self):
        self.assert_all_formats(
            ["Alice: Two issues:", "Bob: Same two:"],
            [("Alice", "Two issues:", False), ("Bob", "Same two:", False)],
        )

    def test_flush_left_labels_after_colon_are_never_swallowed(self):
        # Flush-left "Word: text" is indistinguishable from a speaker label, so it is one.
        self.assert_all_formats(
            ["Alice: Two issues:", "Childcare: cost.", "Transport: bus.",
             "Bob: Same two:", "Childcare: expensive.", "Transport: no car."],
            [("Alice", "Two issues:", False), ("Childcare", "cost.", False), ("Transport", "bus.", False),
             ("Bob", "Same two:", False), ("Childcare", "expensive.", False), ("Transport", "no car.", False)],
        )

    def test_facilitator_bulleted_list_then_participant_reply(self):
        self.assert_all_formats(
            ["Interviewer: Please answer this:", "- Childcare: cost.", "May: I lost my job."],
            [("Interviewer", "Please answer this: - Childcare: cost.", True), ("May", "I lost my job.", False)],
        )

    # Codex R4 finding 3: a voice-tagged speaker in an earlier cue, then a
    # facilitator's list in a later cue.
    def test_vtt_voice_tagged_speaker_answers_after_facilitator_list(self):
        cases = {
            "bulleted": (
                ["Interviewer: Please answer this:", "- Childcare: cost.", "May: I lost my job."],
                [("Interviewer", "Please answer this: - Childcare: cost.", True)],
            ),
            "flush_left": (
                ["Interviewer: Two issues:", "Childcare: cost.", "Transport: bus.", "May: I lost my job."],
                [("Interviewer", "Two issues:", True), ("Childcare", "cost.", False),
                 ("Transport", "bus.", False)],
            ),
        }
        for name, (cue, middle) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(
                    self.vtt_turns([["<v May>Hello.</v>"], cue]),
                    [("May", "Hello.", False), *middle, ("May", "I lost my job.", False)],
                )

    def test_vtt_open_voice_span_still_keeps_colon_lines(self):
        self.assertEqual(
            self.vtt_turns([["<v May>Hello.</v>"],
                            ["<v Mary May>Two barriers:", "Childcare: cost.", "Transport: bus schedule.</v>"]]),
            [("May", "Hello.", False),
             ("Mary May", "Two barriers: Childcare: cost. Transport: bus schedule.", False)],
        )


# ----------------------------------------------------------------------
# #7, #8 Tabular ingestion
# ----------------------------------------------------------------------
class TabularRecordTests(ScratchMixin, unittest.TestCase):
    def test_whitespace_only_lines_keep_physical_line_numbers(self):
        cases = {
            "spaces_and_tab": "id,response\na,first\n   \n\t\nb,last\n",
            "quoted_multiline": 'id,response\na,"first\nstill first"\n   \nb,last\n',
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                path = self.write(f"software_test_{name}.csv", content)
                turns = UniversalTranscriptParser().parse_tabular(path, text_col="response")
                self.assertEqual([t["line_number"] for t in turns], [2, 5])
                self.assertEqual(texts(turns)[1], "last")
                if name == "quoted_multiline":
                    self.assertEqual(texts(turns)[0], "first\nstill first")

    def test_explicit_id_and_blank_id_use_distinct_namespaces(self):
        parser = UniversalTranscriptParser()
        for explicit in ("row_3", "__missing_id_row_3", "#row_3"):
            path = self.write("software_test_row_namespace.csv", f"id,response\n{explicit},first\n,second\n")
            sid = Path(path).resolve().as_posix()
            for allow in (False, True):
                with self.subTest(explicit=explicit, allow_duplicate_ids=allow):
                    turns = parser.parse_tabular(path, text_col="response", id_col="id", allow_duplicate_ids=allow)
                    self.assertEqual(
                        [t["unit_id"] for t in turns],
                        [f"{sid}::{explicit}", f"{sid}#row_3"],
                    )
            for id_col in (None, ""):
                with self.subTest(explicit=explicit, id_col=id_col):
                    turns = parser.parse_tabular(path, text_col="response", id_col=id_col)
                    self.assertEqual([t["unit_id"] for t in turns], [f"{sid}::row_2", f"{sid}::row_3"])

    def test_adversarial_explicit_ids_never_collide_with_blank_ids(self):
        path = self.write(
            "software_test_row_namespace_all.csv",
            "id,response\n,a\nrow_2,b\n__missing_id_row_2,c\n#row_2,d\n,e\n",
        )
        sid = Path(path).resolve().as_posix()
        turns = UniversalTranscriptParser().parse_tabular(path, text_col="response", id_col="id")
        units = [t["unit_id"] for t in turns]
        self.assertEqual(units, [f"{sid}#row_2", f"{sid}::row_2", f"{sid}::__missing_id_row_2",
                                 f"{sid}::#row_2", f"{sid}#row_6"])
        self.assertEqual(len(set(units)), len(units))


# ----------------------------------------------------------------------
# #9 Launcher repair after verified import failure
# ----------------------------------------------------------------------
class LauncherRepairTests(ScratchMixin, unittest.TestCase):
    """A real launcher run against a real (dependency-free) Python environment.

    requirements.txt contains only a comment, so pip "succeeds" offline while the
    core-import check genuinely fails - the corrupt-install situation. The
    launcher must rebuild .venv once, then fail with .venv removed instead of
    leaving the broken environment in place.
    """

    def launcher_copy(self):
        work = self.scratch / "launcher copy"
        work.mkdir()
        for name in ("run.command", "run.bat", "_pip_helper.py"):
            shutil.copy2(REPO_ROOT / name, work / name)
        (work / "requirements.txt").write_text("# SOFTWARE_TEST: no packages\n", encoding="utf-8")
        bindir = self.scratch / "bin"
        bindir.mkdir()
        if IS_WINDOWS:
            path_prefix = str(Path(sys.executable).parent)
            argv = ["cmd", "/c", "run.bat", "--check-only"]
        else:
            (bindir / "python3").symlink_to(sys.executable)
            path_prefix = str(bindir)
            argv = ["bash", "run.command", "--check-only"]
        env = dict(os.environ)
        env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")
        env.pop("ATLAS_NO_LAUNCH", None)
        env["BROWSER"] = "true"
        return work, argv, env

    def test_import_failure_rebuilds_once_then_removes_venv(self):
        work, argv, env = self.launcher_copy()
        proc = subprocess.run(
            argv, cwd=str(work), env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=600,
        )
        output = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, output)
        self.assertFalse((work / ".venv").exists(), "broken .venv must be removed, not just its marker\n" + output)
        self.assertEqual(output.count("Creating local isolated environment"), 2, output)
        self.assertNotIn("check-only: OK", output)

    def test_both_launchers_remove_venv_on_import_failure(self):
        # Static complement to the behavioural test, which can only execute the
        # current platform's launcher.
        command = (REPO_ROOT / "run.command").read_text(encoding="utf-8")
        after_import_check = command[command.index("import streamlit"):]
        self.assertIn("rm -rf .venv", after_import_check)
        self.assertNotIn('rm -f "$MARKER"', command)

        bat = (REPO_ROOT / "run.bat").read_text(encoding="utf-8")
        imports_failed = bat[bat.index(":imports_failed"):bat.index(":fail\n")]
        self.assertIn('rmdir /s /q ".venv"', imports_failed)
        self.assertRegex(imports_failed, r"goto (provision|repair)")


# ----------------------------------------------------------------------
# #11 Smoke-run dependency isolation
# ----------------------------------------------------------------------
def load_smoke():
    spec = importlib.util.spec_from_file_location("atlas_smoke_test", SMOKE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_probe_wheel(directory: Path) -> Path:
    """A minimal pure-Python wheel, installable by pip with no network or build step."""
    name, version = "atlas_smoke_probe", "0.0.0"
    dist_info = f"{name}-{version}.dist-info"
    files = {
        f"{name}.py": "PROBE = 'SOFTWARE_TEST'\n",
        f"{dist_info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        f"{dist_info}/WHEEL": "Wheel-Version: 1.0\nGenerator: atlas-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = [f"{path},,\n" for path in files] + [f"{dist_info}/RECORD,,\n"]
    files[f"{dist_info}/RECORD"] = "".join(record)
    wheel = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        for path, text in files.items():
            zf.writestr(path, text)
    return wheel


def under(path: str, root: Path) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(Path(os.path.realpath(root)))


class SmokeIsolationTests(ScratchMixin, unittest.TestCase):
    def test_copy_venv_is_independent_and_reads_shared_packages(self):
        smoke = load_smoke()
        shared = smoke.REPO / ".venv"
        before = smoke.repo_venv_fingerprint()
        work = smoke.prepare_copy(self.scratch)
        wrapper = work / ".venv"
        self.assertTrue(wrapper.is_dir())
        self.assertFalse(wrapper.is_symlink(), "the copy must not symlink the shared .venv itself")
        for entry in wrapper.iterdir():
            with self.subTest(entry=entry.name):
                self.assertFalse(under(str(entry), shared), f"{entry} resolves into the shared .venv")

        probe = (
            "import json, sys, sysconfig, docx; "
            "print(json.dumps([sys.prefix, sysconfig.get_paths()['purelib'], docx.__file__]))"
        )
        proc = subprocess.run(
            [str(smoke.venv_python(work)), "-c", probe], capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        prefix, purelib, docx_file = json.loads(proc.stdout)
        self.assertTrue(under(prefix, wrapper), prefix)
        self.assertTrue(under(purelib, wrapper), purelib)
        self.assertFalse(under(purelib, shared), purelib)
        # Read from the shared environment (or, inside a smoke copy, the chain it
        # reads from), never reinstalled into the copy's own site-packages.
        self.assertFalse(under(docx_file, wrapper), "shared packages must be read, not reinstalled")

        marker = wrapper / ".atlas_deps.sha256"
        shared_marker = shared / ".atlas_deps.sha256"
        if shared_marker.exists():
            self.assertEqual(marker.read_bytes(), shared_marker.read_bytes())
        shutil.rmtree(wrapper)
        smoke.check_repo_venv_unchanged(before)

    def test_pip_install_in_copy_never_writes_shared_venv(self):
        smoke = load_smoke()
        before = smoke.repo_venv_fingerprint()
        work = smoke.prepare_copy(self.scratch)
        wheel = build_probe_wheel(self.scratch)
        proc = subprocess.run(
            [str(smoke.venv_python(work)), "-m", "pip", "install", "--no-index",
             "--disable-pip-version-check", "--quiet", str(wheel)],
            capture_output=True, text=True, timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        where = subprocess.run(
            [str(smoke.venv_python(work)), "-c", "import atlas_smoke_probe as m; print(m.__file__)"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(where.returncode, 0, where.stderr)
        self.assertTrue(under(where.stdout.strip(), work / ".venv"), where.stdout)
        smoke.check_repo_venv_unchanged(before)
        shared_import = subprocess.run(
            [str(smoke.venv_python(smoke.REPO)), "-c", "import atlas_smoke_probe"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertNotEqual(shared_import.returncode, 0, "probe package leaked into the shared .venv")

    def tampered_fingerprint(self, smoke):
        """The real shared fingerprint with one recorded file digest altered."""
        fingerprint = smoke.repo_venv_fingerprint()
        files = dict(fingerprint["files"])
        files[".atlas_deps.sha256"] = hashlib.sha256(b"tampered").hexdigest()
        return dict(fingerprint, files=files)

    def test_shared_venv_change_is_refused(self):
        smoke = load_smoke()
        smoke.check_repo_venv_unchanged(smoke.repo_venv_fingerprint())
        with self.assertRaisesRegex(smoke.StageFailure, r"\.atlas_deps\.sha256"):
            smoke.check_repo_venv_unchanged(self.tampered_fingerprint(smoke))

    def test_same_size_rewrite_with_restored_mtime_is_detected(self):
        smoke = load_smoke()
        root = self.scratch / "env"
        (root / "lib").mkdir(parents=True)
        target = root / "lib" / "module.py"
        target.write_bytes(b"VALUE = 1\n")
        before = smoke.venv_fingerprint(root)
        stat = target.stat()
        target.write_bytes(b"VALUE = 2\n")
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(target.stat().st_size, stat.st_size)
        self.assertEqual(target.stat().st_mtime_ns, stat.st_mtime_ns)
        self.assertEqual(smoke.venv_changes(before, smoke.venv_fingerprint(root)), ["lib/module.py"])

    def test_fingerprint_works_without_hashlib_file_digest(self):
        # hashlib.file_digest is Python 3.11+; the supported floor is 3.10.
        smoke = load_smoke()
        root = self.scratch / "env"
        root.mkdir()
        (root / "module.py").write_bytes(b"VALUE = 1\n" * 100000)
        saved = getattr(hashlib, "file_digest", None)
        if saved is not None:
            del hashlib.file_digest
        try:
            fingerprint = smoke.venv_fingerprint(root)
        finally:
            if saved is not None:
                hashlib.file_digest = saved
        self.assertEqual(fingerprint["files"],
                         {"module.py": hashlib.sha256(b"VALUE = 1\n" * 100000).hexdigest()})

    def test_no_python311_only_file_digest_in_shipped_code(self):
        for rel in ("scripts/smoke_test.py", "universal_transcript_parser.py", "atlas_engine.py", "app.py",
                    "_pip_helper.py", "scripts/anti_shortcut_gate.py"):
            with self.subTest(file=rel):
                source = (REPO_ROOT / rel).read_text(encoding="utf-8")
                names = {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)}
                names |= {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
                self.assertNotIn("file_digest", names)
                self.assertNotIn("file_digest", source)

    def test_failed_stage_still_reports_shared_venv_change(self):
        smoke = load_smoke()

        def failing_stage(work, env, net_log, tmp):
            raise smoke.StageFailure("launcher --check-only: exited 1")

        with self.assertRaises(smoke.StageFailure) as caught:
            smoke.run_stages([(1, "failing", failing_stage)], self.scratch, {}, self.scratch / "net.jsonl",
                             self.scratch, self.tampered_fingerprint(smoke))
        message = str(caught.exception)
        self.assertIn("launcher --check-only: exited 1", message)
        self.assertIn("shared environment", message)
        self.assertIn(".atlas_deps.sha256", message)

    def test_unexpected_stage_error_still_checks_shared_venv(self):
        smoke = load_smoke()

        def crashing_stage(work, env, net_log, tmp):
            raise RuntimeError("unexpected crash")

        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(RuntimeError):
            smoke.run_stages([(1, "crashing", crashing_stage)], self.scratch, {}, self.scratch / "net.jsonl",
                             self.scratch, self.tampered_fingerprint(smoke))
        self.assertIn("shared environment", out.getvalue())
        self.assertIn(".atlas_deps.sha256", out.getvalue())


# ----------------------------------------------------------------------
# #12 Fixture banners
# ----------------------------------------------------------------------
class FixtureBannerTests(unittest.TestCase):
    def test_sample_transcripts_never_emit_banner_turns(self):
        transcripts = sorted(
            p for p in SAMPLES.iterdir()
            if p.suffix.lower() in (".txt", ".docx", ".vtt", ".srt", ".md")
        )
        self.assertGreaterEqual(len(transcripts), 6)
        for path in transcripts:
            with self.subTest(fixture=path.name):
                parser = UniversalTranscriptParser()
                turns = parser.parse_file(str(path))
                self.assertTrue(turns)
                self.assertEqual([t for t in turns if BANNER_FRAGMENT in t["text"]], [])

    def test_bilingual_fixture_has_no_unknown_banner_turn(self):
        parser = UniversalTranscriptParser()
        turns = parser.parse_file(str(SAMPLES / "software_test_bilingual_interview.txt"))
        self.assertEqual([t for t in turns if t["speaker"] == "Unknown"], [])
        self.assertEqual(parser.last_fixture_banner_lines, [1])


if __name__ == "__main__":
    unittest.main()
