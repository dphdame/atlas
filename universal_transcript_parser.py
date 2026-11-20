"""
Universal Transcript Parser
Module for parsing, normalizing, and attributing speaker dialogue turns
across diverse meeting and interview recording formats (Microsoft Teams,
Zoom WebVTT, Otter.ai, Descript, and standard plain-text transcripts), plus
row-per-response tabular exports (.csv / .xlsx survey or interview sheets).

Every turn carries two identities:
  * source_id - the file it came from (POSIX path relative to root_dir when
    given, otherwise the canonical absolute POSIX path).
  * unit_id   - the counting unit. For transcripts the whole file is one unit
    (unit_id == source_id); for tabular files each row is one unit
    ("<source_id>::<id value>", "<source_id>#row_<line_number>" for a blank
    id cell, or "<source_id>::row_<line_number>" without id_col).

Every line_number is 1-based: the physical line for text, subtitle and CSV
files, the sheet row for XLSX, and the block position (paragraph or table row,
in document order) for Word files.
"""

import csv
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import docx
import pandas as pd
from docx.table import Table


TRANSCRIPT_EXTENSIONS = {".docx", ".vtt", ".srt", ".txt", ".md"}
TABULAR_EXTENSIONS = {".csv", ".xlsx"}

# Speaker names: an uppercase Unicode letter followed by Unicode letters,
# combining marks, digits, spaces, '.', '-', '_', straight/curly apostrophes, '&' and
# '#' ("CHW #2"). The leading class matches any Unicode letter; _is_speaker_name()
# then requires that letter to be uppercase (Python's re has no \p{Lu}).
_SPEAKER = r"[^\W\d_][\ẁ-ͯ .\-'’&#]*?"
_TIMESTAMP = r"\d{1,2}:\d{2}(?::\d{2})?"

# Format A: "Speaker Name 00:14:22"
_DOCX_SPEAKER_TS = re.compile(rf"^({_SPEAKER}) +({_TIMESTAMP})$")
# Format B: "Speaker Name: Dialogue text..."
_DOCX_SPEAKER_COLON = re.compile(rf"^({_SPEAKER}):\s*(.*)$", re.DOTALL)
# Format C: "00:14:22 Speaker Name: Dialogue"
_DOCX_TS_SPEAKER_COLON = re.compile(rf"^({_TIMESTAMP}) +({_SPEAKER}):\s*(.*)$", re.DOTALL)
_DOCX_LEADING_TS = re.compile(r"^\d{1,2}:\d{2}")

_VTT_TIMECODE = re.compile(r"^(\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{3})?)\s+-->\s+")
# Voice span start "<v Name>" or "<v.class Name>", and voice span end "</v>".
_VTT_VOICE_TAG = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>|</v>")
_VTT_SPEAKER_COLON = re.compile(rf"^({_SPEAKER}):\s*(.*)$")

# Microsoft Teams export title line, e.g. "Weekly Sync-20240105_100000-Meeting Recording".
_TEAMS_HEADER = re.compile(r"^(?:.*-)?Meeting Recording$")

# Fixture label carried by every SOFTWARE_TEST sample; it is metadata, never dialogue.
SOFTWARE_TEST_BANNER = "[SOFTWARE_TEST FIXTURE — DEMONSTRATES SOFTWARE MECHANICS ONLY, NOT EMPIRICAL FINDINGS]"

# Word-table header cells that name the speaker / dialogue / timestamp columns.
_TABLE_HEADER_ROLES = {
    "speaker": "speaker", "speaker name": "speaker", "name": "speaker",
    "dialogue": "text", "text": "text", "transcript": "text", "utterance": "text", "content": "text",
    "timestamp": "timestamp", "time": "timestamp", "start time": "timestamp",
}

# Lowercase name particles and joiners allowed inside a multi-word speaker label
# ("Juan de la Cruz", "Gabriel Manrique & Yurina Guzman").
_NAME_PARTICLES = {
    "&", "al", "and", "bin", "da", "das", "de", "del", "della", "der", "des", "di", "do",
    "dos", "du", "el", "et", "ibn", "la", "las", "le", "los", "of", "ter", "van", "von", "y",
}
_MAX_SPEAKER_WORDS = 6
_MAX_SPEAKER_CHARS = 60

# Verbs that mark an untimestamped "Label: text" line as prose when written in
# lowercase ("My main concern is:", "Jane may:"). Capitalized, they can be names
# ("Mary May", "Jane Do", "Min Son", "Will Smith").
_PROSE_VERBS = {
    "is", "are", "was", "were", "am", "be", "been", "being", "has", "have", "had",
    "do", "does", "did", "will", "would", "can", "could", "should", "may", "might",
    "must", "need", "needs", "said", "says", "asked",
    "es", "son", "fue", "era", "está", "están", "tiene", "hay",
}
# One-word labels that are never speakers: verbs (except the given names "Will"
# and "May") and document metadata, callout, ordinal and URI-scheme headers
# ("Mailto:alice@example.org", "Tel:+1555...", "Urn:isbn:...").
_SINGLE_WORD_NON_SPEAKERS = (_PROSE_VERBS - {"will", "may"}) | {
    "note", "notes", "summary", "example", "examples", "warning", "caution", "important",
    "tip", "question", "answer", "date", "time", "location", "topic", "subject", "title",
    "background", "conclusion", "context", "agenda", "action", "status", "source",
    "reference", "result", "results", "problem", "issue", "concern", "reason", "goal",
    "first", "second", "third", "http", "https", "url", "uri", "ftp", "todo", "fixme",
    "mailto", "tel", "urn", "data", "file", "sms", "geo", "cid", "mid", "sip", "sips", "ssh", "git",
}
# "<noun> <enumerator>" outline and artifact labels ("Step 1:", "Option A:", "Part II:").
_OUTLINE_NOUNS = {
    "step", "part", "section", "chapter", "item", "option", "point", "rule", "case", "figure",
    "fig", "table", "page", "phase", "stage", "track", "module", "slide", "exhibit", "appendix",
    "reason", "example", "problem", "issue", "question", "answer", "task", "round", "version",
}
_ROMAN_NUMERAL = re.compile(r"^(?:I{1,3}|IV|VI{0,3}|IX|XI{0,3}|XIV|XV|XVI{0,3}|XIX|XX)$")
# First words that never start a multi-word speaker label ("Our Goal:", "Next Steps:").
# The outline nouns kept from the round-2 starter list ("Step One:", "Problem Areas:")
# are not given names, so they stay here as well.
_STRICT_PROSE_STARTERS = {
    "our", "your", "its", "their", "this", "that", "these", "those", "here", "there",
    "what", "when", "where", "why", "how", "because", "if", "while", "although",
    "key", "next", "action", "main", "final", "open", "total", "overall", "general",
    "example", "reason", "problem", "issue", "point", "step", "part", "item", "option",
    "case", "rule",
}
# First words that start a name only when every later word is capitalized and none
# is a heading noun ("My Tran", "The Moderator", "Note Nguyen"; not "My Problem:").
_AMBIGUOUS_STARTERS = {"my", "his", "her", "the", "a", "an", "note", "summary"}
_PROSE_HEAD_NOUNS = {
    "problem", "problems", "issue", "issues", "concern", "concerns", "goal", "goals",
    "point", "points", "question", "questions", "answer", "answers", "reason", "reasons",
    "idea", "ideas", "thought", "thoughts", "takeaway", "takeaways", "step", "steps",
    "item", "items", "note", "notes", "summary", "example", "examples", "boss", "doctor",
    "case", "rule", "option", "part", "section", "one", "two", "three", "cost", "time",
    "plan", "result", "results",
}
# Pronouns after a leading verb mark a question ("May I:", "Will You:"), not a name.
_PRONOUNS = {
    "i", "you", "we", "he", "she", "it", "they", "me", "us", "him", "them", "there", "this", "that",
    "yo", "tú", "usted", "ustedes", "él", "ella", "nosotros", "nosotras", "ellos", "ellas",
}

# "Speaker [00:01:12]: text", "Speaker 00:01:12: text" or "Speaker: text"
_TEXT_SPEAKER = re.compile(rf"^({_SPEAKER})(?: +\[?({_TIMESTAMP})\]?)?:\s*(.*)$")

def _has_upper(word: str) -> bool:
    return any(ch.isupper() for ch in word)


def _is_enumerator(word: str) -> bool:
    """"1", "#2", "A" or a Roman numeral up to XX."""
    return (
        word.isdigit()
        or (word.startswith("#") and word[1:].isdigit())
        or (len(word) == 1 and word.isupper())
        or bool(_ROMAN_NUMERAL.match(word))
    )


def _is_speaker_name(name: str, has_timestamp: bool = False, rest: str = "") -> bool:
    """
    Whether the text before a colon (or timestamp) is a speaker label; rest is the
    text after the colon. This is the syntactic check; explicitly configured
    facilitator names bypass it (UniversalTranscriptParser._is_speaker_label).

    A label whose colon starts "//" is a URL ("https://...", "Intake https://...").
    Every label has 1.._MAX_SPEAKER_WORDS words and at most _MAX_SPEAKER_CHARS
    characters. A label followed by an explicit timestamp only needs a letter.
    An untimestamped label needs an uppercase letter in its first word and:
      * one word: not a verb or metadata header ("Is:", "Note:", "Date:"); the given
        names "Will" and "May" are speakers.
      * two or more words: no lowercase prose verb ("Jane may:") other than a name
        particle between the first word and a capitalized surname ("Maria do Carmo",
        "Will van der Meer"); a leading verb only
        before capitalized non-pronoun words ("Will Smith", not "May I" / "Can we");
        no "<outline noun> <enumerator>" pair ("Step 1:", "Part II:"); no strict prose
        starter ("Our Goal:", "Next Steps:"); an ambiguous starter ("My", "The", "Note")
        only before capitalized words that are not heading nouns ("My Tran", not
        "My Problem:"); and every later word contains an uppercase letter ("duPont",
        "d'Artagnan"), is numeric or '#'-numbered, is a name particle, or is the
        lowercase surname of a two-word label ("Damaris estrada").
    """
    if rest.lstrip().startswith("//"):
        return False
    name = name.strip()
    words = name.split()
    if not words or len(name) > _MAX_SPEAKER_CHARS or len(words) > _MAX_SPEAKER_WORDS:
        return False
    if has_timestamp:
        return any(ch.isalpha() for ch in name)
    if not _has_upper(words[0]):
        return False

    cleaned = [w.strip(".,;:!?'’\"()") for w in words]
    keys = [w.lower() for w in cleaned]
    if len(words) == 1:
        return keys[0] not in _SINGLE_WORD_NON_SPEAKERS

    def interior_particle(idx: int) -> bool:
        return 0 < idx < len(words) - 1 and keys[idx] in _NAME_PARTICLES

    # Every later word is capitalized or an interior particle; the last word never is one.
    later_cap = all(_has_upper(w) or interior_particle(i) for i, w in enumerate(words[1:], start=1))
    if any(
        key in _PROSE_VERBS and not _has_upper(w) and not (interior_particle(i) and _has_upper(words[-1]))
        for i, (w, key) in enumerate(zip(cleaned, keys))
    ):
        return False
    if keys[0] in _PROSE_VERBS and (not later_cap or any(k in _PRONOUNS for k in keys[1:])):
        return False
    if len(words) == 2 and keys[0] in _OUTLINE_NOUNS and _is_enumerator(cleaned[1]):
        return False
    if keys[0] in _STRICT_PROSE_STARTERS:
        return False
    if keys[0] in _AMBIGUOUS_STARTERS and (
        not later_cap or any(k in _PROSE_HEAD_NOUNS for k in keys[1:])
    ):
        return False

    return all(
        any(ch.isupper() for ch in w)
        or w[0].isdigit()
        or w.startswith("#")
        or w.lower() in _NAME_PARTICLES
        or (len(words) == 2 and w.isalpha())
        for w in words[1:]
    )


def _normalize_name(name: str) -> str:
    """Comparison key: Unicode NFC, lowercase, collapsed whitespace."""
    folded = unicodedata.normalize("NFC", str(name)).lower()
    return unicodedata.normalize("NFC", " ".join(folded.split()))


def _is_banner(line: str) -> bool:
    return line.strip() == SOFTWARE_TEST_BANNER


def _join_lines(text: str) -> str:
    return " ".join(ln.strip() for ln in text.split("\n") if ln.strip())


def _table_header_roles(cells: List[str]) -> Optional[Dict[str, int]]:
    """Column roles when every non-empty cell is a known header label and one names the text."""
    roles: Dict[str, int] = {}
    for col, cell in enumerate(cells):
        if not cell.strip():
            continue
        role = _TABLE_HEADER_ROLES.get(_normalize_name(cell))
        if role is None:
            return None
        roles.setdefault(role, col)
    return roles if "text" in roles else None


def _dedupe_columns(header: List[str]) -> List[str]:
    """Rename repeated header labels "a", "a" to "a", "a.1" (pandas' convention)."""
    columns: List[str] = []
    for label in header:
        candidate, n = label, 0
        while candidate in columns:
            n += 1
            candidate = f"{label}.{n}"
        columns.append(candidate)
    return columns


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


class UniversalTranscriptParser:
    """
    Parses qualitative interview transcripts and tabular response exports into
    structured, speaker-attributed turns with source/unit identity,
    character-level offsets and timestamp tracking.
    """

    def __init__(
        self,
        facilitator_names: Optional[List[str]] = None,
        interviewer_prompt_patterns: Optional[List[str]] = None,
        root_dir: Optional[str] = None,
    ):
        """
        Initialize parser.
        :param facilitator_names: Optional list of known interviewer/facilitator names,
            matched exactly (case-, whitespace- and Unicode-normalization-insensitive)
            against speaker labels.
            If omitted, a named speaker is auto-detected as facilitator only when the
            transcript contains at least 3 questions ('?') from named speakers and that
            speaker asked strictly more than 50% of them.
        :param interviewer_prompt_patterns: Optional list of regular expressions, applied
            case-insensitively to speakerless ("Unknown") turns. A matching turn is marked
            is_facilitator=True, tagged with exclusion_reason and logged in
            last_excluded_turns. Speakerless turns are never flagged otherwise.
        :param root_dir: Optional default root used to build relative source_id values.
        """
        self.facilitator_names = (
            {_normalize_name(f) for f in facilitator_names if _normalize_name(f)}
            if facilitator_names else set()
        )
        self.interviewer_prompt_patterns = [
            (pat, re.compile(pat, re.IGNORECASE)) for pat in (interviewer_prompt_patterns or [])
        ]
        self.root_dir = root_dir
        self.last_excluded_turns: List[Dict[str, Any]] = []
        self.last_skipped_empty_rows = 0
        self.last_fixture_banner_lines: List[int] = []

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    def _source_id(self, file_path: str, root_dir: Optional[str]) -> str:
        resolved = Path(file_path).resolve()
        eff_root = root_dir or self.root_dir
        if eff_root:
            try:
                return resolved.relative_to(Path(eff_root).resolve()).as_posix()
            except ValueError:
                pass
        return resolved.as_posix()

    def _reset_call_state(self) -> None:
        self.last_excluded_turns = []
        self.last_skipped_empty_rows = 0
        self.last_fixture_banner_lines = []

    # ------------------------------------------------------------------
    # Speaker labels
    # ------------------------------------------------------------------
    def _is_speaker_label(self, name: str, has_timestamp: bool = False, rest: str = "") -> bool:
        """A configured facilitator name is always a speaker, even "Note" or "Question"."""
        return _normalize_name(name) in self.facilitator_names or _is_speaker_name(name, has_timestamp, rest)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def parse_file(self, file_path: str, root_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Detect file format and parse into standardized turns.
        Tabular files (.csv/.xlsx) use parse_tabular defaults (text column "response").
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Transcript file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext in TABULAR_EXTENSIONS:
            return self.parse_tabular(file_path, root_dir=root_dir)
        if ext not in TRANSCRIPT_EXTENSIONS:
            raise ValueError(f"Unsupported transcript extension: {ext}")

        self._reset_call_state()
        if ext == ".docx":
            raw_entries = self._parse_docx(file_path)
        elif ext in (".vtt", ".srt"):
            raw_entries = self._parse_vtt(file_path)
        else:
            raw_entries = self._parse_text(file_path)

        source_id = self._source_id(file_path, root_dir)
        unit_ids = [source_id] * len(raw_entries)
        return self._normalize_turns(raw_entries, file_path, source_id, unit_ids, auto_detect=True)

    # ------------------------------------------------------------------
    # Transcript formats
    # ------------------------------------------------------------------
    def _parse_docx(self, file_path: str) -> List[Tuple[int, str, str, str]]:
        """
        Parse Word document transcripts. Paragraphs and tables are read in document
        order, and each paragraph or table row is one 1-based block location.
        A table with two or more columns holds one turn per row: speaker, text and
        optional timestamp columns, or the columns named by a recognized header row
        (e.g. "Speaker | Dialogue | Timestamp"), which is itself skipped.
        Every paragraph with an accepted "Name: text" label starts a turn; bulleted or
        numbered items ("- Childcare: cost.") stay in the current turn.
        """
        doc = docx.Document(file_path)
        # (paragraph text, None) or (None, table rows), in document order.
        items: List[Tuple[Optional[str], Optional[List[List[str]]]]] = [
            (item.text, None) if not isinstance(item, Table)
            else (None, [[cell.text.strip() for cell in row.cells] for row in item.rows])
            for item in doc.iter_inner_content()
        ]
        raw_entries: List[Tuple[int, str, str, str]] = []
        current_speaker = "Unknown"
        current_timestamp = ""
        line_idx = 0
        buffer: List[str] = []

        def speaker_label(text: str) -> Optional[Tuple[str, str, str]]:
            """(speaker, timestamp, content) when the paragraph opens a speaker turn."""
            match_a = _DOCX_SPEAKER_TS.match(text)
            match_b = _DOCX_SPEAKER_COLON.match(text)
            match_c = _DOCX_TS_SPEAKER_COLON.match(text)
            if match_a and self._is_speaker_label(match_a.group(1), has_timestamp=True):
                return match_a.group(1).strip(), match_a.group(2).strip(), ""
            if match_b and self._is_speaker_label(match_b.group(1), rest=match_b.group(2)):
                return match_b.group(1).strip(), "", match_b.group(2)
            if match_c and self._is_speaker_label(match_c.group(2), has_timestamp=True, rest=match_c.group(3)):
                return match_c.group(2).strip(), match_c.group(1).strip(), match_c.group(3)
            return None

        def is_turn_table(rows: Optional[List[List[str]]]) -> bool:
            return rows is not None and max((len(cells) for cells in rows), default=0) >= 2

        def table_turns(rows: List[List[str]]):
            """(row index, speaker, timestamp, text) for every non-header row of a turn table."""
            header_roles = _table_header_roles(rows[0])
            roles = header_roles or {"speaker": 0, "text": 1, "timestamp": 2}
            for row_idx, cells in enumerate(rows):
                if row_idx == 0 and header_roles:
                    continue

                def cell(role: str) -> str:
                    col = roles.get(role)
                    return cells[col] if col is not None and col < len(cells) else ""

                yield row_idx, cell("speaker"), cell("timestamp"), _join_lines(cell("text"))

        # Blocks in document order: (location, text, None) for a paragraph or a
        # single-column table cell, (first row location, None, rows) for a turn table.
        units: List[Tuple[int, Optional[str], Optional[List[List[str]]]]] = []
        location = 0
        for para, rows in items:
            if rows is None:
                location += 1
                units.append((location, para, None))
            elif not is_turn_table(rows):
                for cells in rows:
                    location += 1
                    units.append((location, cells[0] if cells else "", None))
            else:
                units.append((location + 1, None, rows))
                location += len(rows)

        def flush() -> None:
            if buffer:
                raw_entries.append((line_idx, current_speaker, current_timestamp, " ".join(buffer)))
                buffer.clear()

        def start_turn(block: int, speaker: str, timestamp: str, content: str) -> None:
            nonlocal current_speaker, current_timestamp, line_idx
            flush()
            current_speaker, current_timestamp, line_idx = speaker, timestamp, block
            content = _join_lines(content)
            if content:
                buffer.append(content)

        def handle_paragraph(block: int, raw: str) -> None:
            nonlocal current_timestamp, line_idx
            text = raw.strip()
            if not text:
                return
            if _is_banner(text):
                self.last_fixture_banner_lines.append(block)
                return

            found = speaker_label(text)
            if found:
                start_turn(block, *found)
            elif _TEAMS_HEADER.match(text):
                return  # export title line, not dialogue
            else:
                # Newline-delimited timestamps (Teams default export): keep every line after it.
                lines = text.split("\n")
                if len(lines) >= 2 and _DOCX_LEADING_TS.match(lines[0]):
                    flush()
                    current_timestamp = lines[0].strip()
                    line_idx = block
                    content = _join_lines("\n".join(lines[1:]))
                    if content:
                        buffer.append(content)
                else:
                    if not buffer:
                        line_idx = block
                    buffer.append(_join_lines(text))

        for block, para, rows in units:
            if rows is None:
                handle_paragraph(block, para)
                continue

            flush()
            for row_idx, speaker, timestamp, text in table_turns(rows):
                row_block = block + row_idx
                if not text:
                    continue
                if _is_banner(text):
                    self.last_fixture_banner_lines.append(row_block)
                    continue
                raw_entries.append((row_block, speaker or "Unknown", timestamp, text))
            # Table rows carry their own attribution; later prose does not inherit it.
            current_speaker, current_timestamp = "Unknown", ""

        flush()
        return raw_entries

    def _parse_vtt(self, file_path: str) -> List[Tuple[int, str, str, str]]:
        """
        Parse WebVTT (.vtt) and SubRip (.srt) subtitle transcripts.
        - The WEBVTT header block and NOTE comment blocks (up to the next blank line)
          are discarded.
        - A cue identifier is the non-blank line immediately before a timing line; it
          is never dialogue, while payload lines (even purely numeric ones) are kept.
        - Attribution is scoped to its cue. A voice span "<v Name>...</v>" or a leading
          "Name:" label sets the speaker for that span (or the rest of the cue), a
          change of speaker starts a new turn, and every cue starts as "Unknown".
        - Inside an open voice span (closed by "</v>" or the end of the cue) a
          "Name:" line is dialogue of the span's speaker. Outside one, every accepted
          "Name:" label starts a turn, as in text and Word transcripts; bulleted or
          numbered items ("- Childcare: cost.") stay in the current turn.
        """
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = [line.strip() for line in f.readlines()]
        is_timing = [bool(_VTT_TIMECODE.match(line)) for line in lines]

        def colon_label(line_str: str) -> Optional[Tuple[str, str]]:
            """(speaker, rest) for a leading "Name:" label."""
            match = _VTT_SPEAKER_COLON.match(line_str)
            if match and self._is_speaker_label(match.group(1), rest=match.group(2)):
                return match.group(1).strip(), match.group(2).strip()
            return None

        raw_entries: List[Tuple[int, str, str, str]] = []
        speaker = "Unknown"
        current_ts = ""
        current_text: List[str] = []
        line_num = 0
        cue_speaker = "Unknown"  # speaker outside any voice span in the current cue
        active = "Unknown"  # speaker of the text at the current position
        in_header = bool(lines) and lines[0].startswith("WEBVTT")
        in_note = False
        in_voice_span = False

        def flush() -> None:
            if current_text:
                raw_entries.append((line_num, speaker, current_ts, " ".join(current_text)))
                current_text.clear()

        def add(text_speaker: str, text: str) -> None:
            nonlocal speaker
            text = text.strip()
            if not text:
                return
            if text_speaker != speaker:
                flush()
                speaker = text_speaker
            current_text.append(text)

        for idx, line_str in enumerate(lines):
            if in_header:
                in_header = bool(line_str)
                continue
            if in_note:
                in_note = bool(line_str)
                continue
            if line_str == "NOTE" or line_str.startswith(("NOTE ", "NOTE\t")):
                in_note = True
                continue
            if not line_str:
                continue
            if is_timing[idx]:
                flush()
                current_ts = _VTT_TIMECODE.match(line_str).group(1)
                line_num = idx + 1
                speaker = cue_speaker = active = "Unknown"
                in_voice_span = False
                continue
            if idx + 1 < len(lines) and is_timing[idx + 1]:
                continue  # cue identifier
            if _is_banner(line_str):
                self.last_fixture_banner_lines.append(idx + 1)
                continue

            label = None if in_voice_span or line_str.startswith("<") else colon_label(line_str)
            if label:
                flush()  # an accepted label starts a new turn, as in text and Word transcripts
                cue_speaker = active = label[0]
                line_str = label[1]

            pos = 0
            for tag in _VTT_VOICE_TAG.finditer(line_str):
                add(active, line_str[pos:tag.start()])
                active = tag.group(1).strip() if tag.group(1) else cue_speaker
                in_voice_span = bool(tag.group(1))
                pos = tag.end()
            add(active, line_str[pos:])

        flush()
        return raw_entries

    def _parse_text(self, file_path: str) -> List[Tuple[int, str, str, str]]:
        """
        Parse plain text (.txt) and Markdown transcripts.
        Every line with an accepted "Name: text" label starts a turn; bulleted or
        numbered items ("- Childcare: cost.") stay in the current turn.
        """
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = [line.strip() for line in f.readlines()]

        def speaker_match(line_str: str) -> Optional["re.Match[str]"]:
            match = _TEXT_SPEAKER.match(line_str)
            if match and self._is_speaker_label(match.group(1), has_timestamp=bool(match.group(2)),
                                                rest=match.group(3)):
                return match
            return None

        raw_entries = []
        current_speaker = "Unknown"
        current_ts = ""
        current_text: List[str] = []
        start_line = 1

        for idx, line_str in enumerate(lines):
            if not line_str:
                continue
            if _is_banner(line_str):
                self.last_fixture_banner_lines.append(idx + 1)
                continue

            match = speaker_match(line_str)
            if match:
                if current_text:
                    raw_entries.append((start_line, current_speaker, current_ts, " ".join(current_text)))
                    current_text = []
                current_speaker = match.group(1).strip()
                current_ts = match.group(2) if match.group(2) else ""
                start_line = idx + 1
                content = match.group(3).strip()
                if content:
                    current_text.append(content)
            else:
                if not current_text:
                    start_line = idx + 1
                current_text.append(line_str)

        if current_text:
            raw_entries.append((start_line, current_speaker, current_ts, " ".join(current_text)))

        return raw_entries

    # ------------------------------------------------------------------
    # Tabular formats
    # ------------------------------------------------------------------
    def parse_tabular(
        self,
        file_path: str,
        text_col: str = "response",
        id_col: Optional[str] = None,
        speaker_col: Optional[str] = None,
        root_dir: Optional[str] = None,
        allow_duplicate_ids: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Parse a headered .csv or .xlsx file with one response per row.

        - Rows whose text_col cell is empty or whitespace-only are skipped and counted
          in last_skipped_empty_rows.
        - line_number is the 1-based physical line (CSV, after any leading '#' comment
          lines) or sheet row (XLSX) where the record starts; the header is row 1.
        - unit_id is "<source_id>::<id>" when id_col names a non-blank cell,
          "<source_id>#row_<line_number>" when that cell is blank, and
          "<source_id>::row_<line_number>" when no id_col is given. Explicit ids always
          have ':' right after source_id and blank-id fallbacks have '#', so the two
          can never collide whatever the id text ("row_3", "#row_3", ...). Duplicate unit_ids
          raise ValueError unless allow_duplicate_ids=True.
        - Cells are read as text without NA coercion, so answers such as "None" or
          "N/A" are kept verbatim.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Tabular file not found: {file_path}")

        self._reset_call_state()
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".csv":
            frame, line_numbers = self._read_csv(file_path)
        elif ext == ".xlsx":
            frame = pd.read_excel(file_path, dtype=str, keep_default_na=False, na_filter=False)
            line_numbers = [row_idx + 2 for row_idx in range(len(frame))]
        else:
            raise ValueError(f"Unsupported tabular extension: {ext}")

        columns = [str(c) for c in frame.columns]
        frame.columns = columns
        for label, col in (("text_col", text_col), ("id_col", id_col), ("speaker_col", speaker_col)):
            if col and col not in columns:
                raise ValueError(f"{label} {col!r} not found in {os.path.basename(file_path)}; columns: {columns}")

        source_id = self._source_id(file_path, root_dir)
        raw_entries: List[Tuple[int, str, str, str]] = []
        unit_ids: List[str] = []
        seen_units = set()

        for row_pos, row in enumerate(frame.itertuples(index=False, name=None)):
            record = dict(zip(columns, row))
            line_number = line_numbers[row_pos]
            text_value = record[text_col]
            if _is_blank(text_value):
                self.last_skipped_empty_rows += 1
                continue

            id_value = record.get(id_col) if id_col else None
            if not id_col:
                unit_id = f"{source_id}::row_{line_number}"
            elif _is_blank(id_value):
                unit_id = f"{source_id}#row_{line_number}"
            else:
                unit_id = f"{source_id}::{str(id_value).strip()}"
            if unit_id in seen_units and not allow_duplicate_ids:
                raise ValueError(
                    f"Duplicate unit id {unit_id!r} at line {line_number} of {os.path.basename(file_path)}; "
                    "pass allow_duplicate_ids=True to keep repeated ids as one unit"
                )
            seen_units.add(unit_id)

            speaker_value = record.get(speaker_col) if speaker_col else None
            speaker = "Unknown" if _is_blank(speaker_value) else str(speaker_value).strip()

            raw_entries.append((line_number, speaker, "", str(text_value)))
            unit_ids.append(unit_id)

        return self._normalize_turns(raw_entries, file_path, source_id, unit_ids, auto_detect=False)

    def _read_csv(self, file_path: str) -> Tuple[pd.DataFrame, List[int]]:
        """
        Read a CSV whose header may be preceded by '#' comment lines (e.g. a
        SOFTWARE_TEST banner) or blank lines. Only leading comment lines are skipped,
        so '#' inside a response is never truncated. A single csv.reader pass yields
        both the values and the 1-based physical start line of each data record
        (quoted multi-line cells span several physical lines). Blank or
        whitespace-only physical lines are not records; short records are padded
        with empty cells, and a record with extra non-empty cells raises ValueError.
        """
        name = os.path.basename(file_path)
        with open(file_path, "r", encoding="utf-8-sig", newline="") as fh:
            leading = 0
            for line in fh:
                if line.strip() == "" or line.lstrip().startswith("#"):
                    leading += 1
                    continue
                break

        header: Optional[List[str]] = None
        rows: List[List[str]] = []
        data_starts: List[int] = []
        with open(file_path, "r", encoding="utf-8-sig", newline="") as fh:
            for _ in range(leading):
                next(fh)
            reader = csv.reader(fh)
            while True:
                start = leading + reader.line_num + 1
                try:
                    rec = next(reader)
                except StopIteration:
                    break
                if not rec or (len(rec) == 1 and not rec[0].strip()):
                    continue
                if header is None:
                    header = rec
                    continue
                if len(rec) > len(header):
                    if any(cell.strip() for cell in rec[len(header):]):
                        raise ValueError(
                            f"CSV record at line {start} of {name} has {len(rec)} cells; header has {len(header)}"
                        )
                    rec = rec[: len(header)]
                rows.append(rec + [""] * (len(header) - len(rec)))
                data_starts.append(start)

        if header is None:
            raise ValueError(f"No header row found in {name}")
        return pd.DataFrame(rows, columns=_dedupe_columns(header), dtype=str), data_starts

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    def _detect_facilitators(self, raw_entries: List[Tuple[int, str, str, str]]) -> set:
        """Named speaker asking >50% of at least 3 questions from named speakers."""
        speaker_question_counts: Dict[str, int] = {}
        for _, speaker, _, text in raw_entries:
            spk_norm = _normalize_name(speaker)
            if spk_norm not in ("unknown", ""):
                speaker_question_counts[spk_norm] = speaker_question_counts.get(spk_norm, 0) + text.count("?")

        total_questions = sum(speaker_question_counts.values())
        if total_questions < 3:
            return set()
        return {spk for spk, count in speaker_question_counts.items() if (count / total_questions) > 0.50}

    def _normalize_turns(
        self,
        raw_entries: List[Tuple[int, str, str, str]],
        file_path: str,
        source_id: str,
        unit_ids: List[str],
        auto_detect: bool,
    ) -> List[Dict[str, Any]]:
        """
        Normalize speaker turns, calculate character spans, and evaluate facilitator roles.
        """
        detected_facilitators = set(self.facilitator_names)
        if not detected_facilitators and auto_detect and raw_entries:
            detected_facilitators = self._detect_facilitators(raw_entries)

        doc_name = os.path.basename(file_path)
        normalized_turns = []
        char_cursor = 0

        for turn_idx, ((line_num, speaker, timestamp, text), unit_id) in enumerate(zip(raw_entries, unit_ids)):
            clean_text = text.strip()
            text_len = len(clean_text)
            speaker_clean = speaker.strip() or "Unknown"
            spk_norm = _normalize_name(speaker_clean)
            speakerless = spk_norm == "unknown"

            record = {
                "turn_id": turn_idx + 1,
                "document_name": doc_name,
                "source_id": source_id,
                "unit_id": unit_id,
                "line_number": line_num,
                "timestamp": timestamp,
                "speaker": speaker_clean,
                "is_facilitator": (not speakerless) and spk_norm in detected_facilitators,
                "text": clean_text,
                "word_count": len(clean_text.split()),
                "char_start": char_cursor,
                "char_end": char_cursor + text_len,
            }

            if speakerless:
                for pat, compiled in self.interviewer_prompt_patterns:
                    if compiled.search(clean_text):
                        record["is_facilitator"] = True
                        record["exclusion_reason"] = f"matched_prompt_pattern:{pat}"
                        self.last_excluded_turns.append(dict(record))
                        break

            normalized_turns.append(record)
            char_cursor += text_len + 1

        return normalized_turns
