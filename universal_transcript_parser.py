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

A Word file holding a 3+-column "Key Points | Notable Quotes | Observations"
table is parsed as structured focus-group notes (one file per group); every other
file keeps its transcript or tabular parse. Every turn also carries:
  * document_structure - "focus_group_notes", "transcript" or "tabular".
  * evidence_type      - for notes: "key_point_paraphrase", "notable_quote_verbatim",
    "observation" or "themes_summary"; "verbatim_turn" otherwise.
  * question_id        - "Question N" for notes; "" otherwise.
  * group_id           - source_id.
  * participant_id     - "<source_id>::<P#>" for notes, so P1 in two groups never
    collide; unit_id otherwise.
"""

import csv
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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

# Structured focus-group notes (.docx): the evidence a notes-table row can yield.
NOTES_EVIDENCE_TYPES = ("key_point_paraphrase", "notable_quote_verbatim", "observation", "themes_summary")
DEFAULT_NOTES_EVIDENCE_TYPES = ("key_point_paraphrase", "notable_quote_verbatim")
NOTES_UNIT_LEVELS = ("group", "participant")
NOTES_THEMES_SPEAKER = "NoteTaker_Themes"
_NOTES_COLUMN_ROLES = {
    "key point": "key_points", "key points": "key_points",
    "notable quote": "notable_quotes", "notable quotes": "notable_quotes",
    "observation": "observations", "observations": "observations",
}
# Rows checked for the notes header (a title or "Question N" row may sit above it).
_NOTES_HEADER_SCAN_ROWS = 3
_NOTES_PARTICIPANT = re.compile(r"^(P\d+)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
_NOTES_THEMES = re.compile(
    r"^\s*themes(?:\s*/\s*topics)?(?:\s*/\s*patterns)?\s*(?::[ \t]*|(?=\n|$))",
    re.IGNORECASE,
)
_NOTES_QUESTION = re.compile(r"^question\s*(\d+)\b\s*[:.)\-]?\s*(.*)$", re.IGNORECASE | re.DOTALL)
# Structural rows embedded in a notes table: a "Question N:" heading (separator or
# nothing after the number, so "Question 2 was confusing" stays evidence), a
# follow-up / probe prompt, and a consent header/statement ("Consent:", "Consent
# statement/script ...", or "Consent form:" / "Consent form reviewed/signed/...";
# ordinary prose like "Consent form paperwork was confusing" stays evidence).
_NOTES_EMBEDDED_QUESTION = re.compile(r"^question\s*\d+\s*(?:[:.)\-]|$)", re.IGNORECASE)
_NOTES_PROMPT = re.compile(r"^(?:follow[\s-]*ups?|probes?)\s*:", re.IGNORECASE)
_NOTES_CONSENT = re.compile(
    r"^consent(?:\s+(?:statement|script|forms?))?(?:\s*\([^)]*\))?\s*(?:$|:)|"
    r"^consent\s+(?:statement|script)\s+(?:(?:was|were)\s+)?(?:read|reviewed|given|delivered|presented|shared|recited|"
    r"completed|confirmed|signed|received)(?:\s+(?:again|aloud|to\s+all|by\s+all(?:\s+participants)?))*"
    r"(?:\s+(?:before|after)\s+the\s+(?:paperwork|intake|enrollment|session|interview|discussion|questions?)"
    r"(?:\s+(?:break|questions?|discussion|session|portion|section))?)?\s*\.?$|"
    r"^consent\s+forms?\s+(?:(?:was|were)\s+)?(?:reviewed|read|signed|received|collected|obtained|completed|confirmed)"
    r"(?:\s+(?:and\s+(?:reviewed|read|signed|received|collected|obtained|completed|confirmed)|by\s+all(?:\s+participants)?))?"
    r"(?:\s+(?:before|after)\s+the\s+(?:paperwork|intake|enrollment|session|interview|discussion|questions?)"
    r"(?:\s+(?:break|questions?|discussion|session|portion|section))?)?\s*\.?$",
    re.IGNORECASE,
)
# Metadata keys that collapse every label variant ("Main Observations (4-5) Ideas:").
_NOTES_CANONICAL_KEYS = ("summary_of_session", "main_observations")
# Strict grammar for the summary boxes: group 1 is the label, group 2 any text after the colon.
_NOTES_SUMMARY_LABEL = re.compile(
    r"^(summary\s+of\s+session(?:\s*\([^)]*\))?|main\s+observations(?:\s*\([^)]*\))?(?:\s+ideas)?)\s*(?::\s*(.*)|$)",
    re.IGNORECASE,
)

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


def _docx_table_rows(table: Table) -> Tuple[List[List[str]], List[Set[int]]]:
    """
    Stripped cell texts of each Word table row (a horizontally merged cell repeats as ""
    after its first column) and, for each row, the columns holding a vertically merged
    continuation: a physical cell (<w:tc>) that already appeared in an earlier row.
    """
    rows: List[List[str]] = []
    continued: List[Set[int]] = []
    seen: set = set()  # holding the elements keeps their lxml identity stable
    for row in table.rows:
        texts: List[str] = []
        cont: Set[int] = set()
        previous = None
        for col, cell in enumerate(row.cells):
            tc = cell._tc
            texts.append("" if tc is previous else cell.text.strip())
            if tc in seen:
                cont.add(col)
            previous = tc
        seen.update(cell._tc for cell in row.cells)
        rows.append(texts)
        continued.append(cont)
    return rows, continued


def _docx_blocks(file_path: str) -> List[Tuple[Optional[str], Optional[List[List[str]]], Optional[List[Set[int]]]]]:
    """
    (paragraph text, None, None) or (None, table row texts, vertically merged
    continuation columns per row) for each body block, in document order.
    """
    return [
        (item.text, None, None) if not isinstance(item, Table) else (None, *_docx_table_rows(item))
        for item in docx.Document(file_path).iter_inner_content()
    ]


def _notes_columns(rows: List[List[str]]) -> Optional[Tuple[int, Dict[str, List[int]]]]:
    """
    (header row index, columns of each role, left to right) when one of the first rows
    of a 3+-column table names both "Key Points" and "Notable Quotes" (case-,
    whitespace- and trailing colon-insensitive; "Observations" optional). A repeated
    header ("Notable Quotes | Notable Quotes") keeps every column.
    """
    for r_idx, cells in enumerate(rows[:_NOTES_HEADER_SCAN_ROWS]):
        if len(cells) < 3:
            continue
        cols: Dict[str, List[int]] = {}
        for col, cell in enumerate(cells):
            role = _NOTES_COLUMN_ROLES.get(" ".join(cell.lower().split()).rstrip(":").strip())
            if role:
                cols.setdefault(role, []).append(col)
        if "key_points" in cols and "notable_quotes" in cols:
            return r_idx, cols
    return None


def _participant_segments(text: str) -> List[Tuple[Optional[str], str]]:
    """
    (upper-case "P#" label or None, joined text) for each contribution in a notes cell.
    Every line opening with a "P#:" label starts a new contribution, so
    "P1: a\\nP2: b" is two; lines before the first label form one unlabelled contribution.
    """
    segments: List[Tuple[Optional[str], List[str]]] = []
    for line in text.split("\n"):
        label = _NOTES_PARTICIPANT.match(line.strip())
        if label:
            segments.append((label.group(1).upper(), [label.group(2)]))
        elif segments:
            segments[-1][1].append(line)
        else:
            segments.append((None, [line]))
    return [(pid, _join_lines("\n".join(lines))) for pid, lines in segments]


def _metadata_key(label: str) -> str:
    """ "Project Name (s):" -> "project_name"; summary-box labels map to their canonical key."""
    base = re.sub(r"\([^)]*\)", " ", label).strip().rstrip(":")
    key = re.sub(r"[\W_]+", "_", unicodedata.normalize("NFC", base).lower()).strip("_")
    for canonical in _NOTES_CANONICAL_KEYS:
        if key.startswith(canonical):
            return canonical
    return key


def _box_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def _validate_csv_quoting(text: str, name: str, start_line: int = 1) -> None:
    """
    RFC 4180 quote balance for a CSV body whose first character is on physical
    line start_line. A '"' may appear only at the start of a cell, where it opens a
    quoted cell (a quote inside an unquoted cell is malformed); inside it '""' is an
    escaped quote, and a closing '"' must be followed by ',', a line break or the
    end of the file.
    Raises ValueError naming the physical line on malformed quoting.
    """
    in_quotes = False
    at_field_start = True
    line_no = open_line = start_line
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    i += 2
                    continue
                if i + 1 < n and text[i + 1] not in ",\r\n":
                    raise ValueError(f"Malformed CSV quoting at line {line_no} of {name}")
                in_quotes = False
        elif ch == '"':
            if not at_field_start:
                raise ValueError(
                    f"Malformed CSV quoting at line {line_no} of {name}: unexpected quote inside unquoted field"
                )
            in_quotes, open_line = True, line_no
        at_field_start = not in_quotes and ch in ",\r\n"
        if ch == "\r" or (ch == "\n" and (i == 0 or text[i - 1] != "\r")):
            line_no += 1
        i += 1
    if in_quotes:
        raise ValueError(f"Malformed CSV: unterminated quoted field opened at line {open_line} of {name}")


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
        include_evidence_types: Optional[Sequence[str]] = None,
        notes_unit_level: str = "group",
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
        :param include_evidence_types: Evidence types kept from structured focus-group
            notes, a non-empty sequence drawn from NOTES_EVIDENCE_TYPES (default
            DEFAULT_NOTES_EVIDENCE_TYPES: key points and notable quotes). Transcript
            and tabular files are unaffected. Unknown names raise ValueError.
        :param notes_unit_level: Counting unit for focus-group notes: "group" (default,
            unit_id = source_id, one unit per focus-group file) or "participant"
            (unit_id = participant_id). Any other value raises ValueError.
        """
        if include_evidence_types is None:
            evidence_types: Tuple[str, ...] = DEFAULT_NOTES_EVIDENCE_TYPES
        else:
            if isinstance(include_evidence_types, str):
                raise ValueError("include_evidence_types must be a sequence of evidence type names, not a string")
            evidence_types = tuple(include_evidence_types)
            unknown = [t for t in evidence_types if t not in NOTES_EVIDENCE_TYPES]
            if not evidence_types or unknown:
                raise ValueError(
                    f"include_evidence_types must be a non-empty subset of {NOTES_EVIDENCE_TYPES}; got {evidence_types!r}"
                )
        if notes_unit_level not in NOTES_UNIT_LEVELS:
            raise ValueError(f"notes_unit_level must be one of {NOTES_UNIT_LEVELS}; got {notes_unit_level!r}")
        self.include_evidence_types = evidence_types
        self.notes_unit_level = notes_unit_level
        # Focus-group notes metadata per source_id, kept across calls on one parser.
        self.last_document_metadata: Dict[str, Dict[str, Any]] = {}
        # document_structure of the most recent parse_file / parse_tabular call.
        self.last_document_structure: Optional[str] = None
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
    @staticmethod
    def detect_docx_structure(file_path: str) -> str:
        """
        "structured_notes" when a Word file holds a "Key Points | Notable Quotes"
        notes table (parse_file would read it as focus-group notes), else
        "transcript". A malformed package raises the same errors as parse_file.
        """
        blocks = _docx_blocks(file_path)
        if any(rows is not None and _notes_columns(rows) for _, rows, _ in blocks):
            return "structured_notes"
        return "transcript"

    def parse_file(self, file_path: str, root_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Detect file format and parse into standardized turns.
        Tabular files (.csv/.xlsx) use parse_tabular defaults (text column "response").
        A .docx with a "Key Points | Notable Quotes" notes table is parsed as
        structured focus-group notes; any other .docx keeps the transcript parse.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Transcript file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext in TABULAR_EXTENSIONS:
            return self.parse_tabular(file_path, root_dir=root_dir)
        if ext not in TRANSCRIPT_EXTENSIONS:
            raise ValueError(f"Unsupported transcript extension: {ext}")

        self._reset_call_state()
        source_id = self._source_id(file_path, root_dir)
        self.last_document_metadata.pop(source_id, None)
        self.last_document_structure = "transcript"
        if ext == ".docx":
            blocks = _docx_blocks(file_path)
            if any(rows is not None and _notes_columns(rows) for _, rows, _ in blocks):
                self.last_document_structure = "focus_group_notes"
                return self._parse_focus_group_notes(blocks, file_path, source_id)
            raw_entries = self._parse_docx(file_path)
        elif ext in (".vtt", ".srt"):
            raw_entries = self._parse_vtt(file_path)
        else:
            raw_entries = self._parse_text(file_path)

        unit_ids = [source_id] * len(raw_entries)
        turns = self._normalize_turns(raw_entries, file_path, source_id, unit_ids, auto_detect=True)
        return self._add_structure_keys(turns, "transcript")

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
    # Structured focus-group notes
    # ------------------------------------------------------------------
    def _parse_focus_group_notes(
        self,
        blocks: List[Tuple[Optional[str], Optional[List[List[str]]], Optional[List[Set[int]]]]],
        file_path: str,
        source_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Parse a structured focus-group notes document (one file per group).

        Only notes-table rows become turns. Paragraphs (title, consent, "Question N:"
        prompts, follow-ups and probes) and every other table (label/value metadata
        layouts and 1-column "Summary of Session" / "Main Observations" boxes) are
        recorded in last_document_metadata[source_id] and never emitted.

        Each notes table takes the question_id of the "Question N" paragraph (or
        pre-header row) since the previous notes table, or "Question <k>" for the
        k-th notes table when that heading is missing. Within it, every row after the
        header yields, in order, a key_point_paraphrase (the Key Points cell after its
        "P#:" label), a notable_quote_verbatim and an observation for that participant
        when the cell is non-empty; a role with several columns yields one turn per
        column, left to right. A row whose Key Points cell (or first cell) starts
        "Themes / Topics / Patterns:" yields one themes_summary turn by
        NOTES_THEMES_SPEAKER, marked is_facilitator.

        Attribution: every line opening "P#:" starts a contribution of that participant,
        so one cell can hold several. An unlabelled contribution goes to the row's label
        when the row names exactly one participant and to "Unknown" otherwise. Rows
        naming different participants are listed in metadata["mixed_label_rows"]; those
        where one cell names several participants and an unlabelled contribution became
        "Unknown" are also listed in metadata["ambiguous_multilabel_rows"].

        A row with a structural label cell in any column (the other new cells are its
        payload), and no explicit "P#:" label, is not evidence: a "Question N:" heading
        starts that question for the following rows;
        a "Follow-up:" / "Probe:" prompt extends the current question's prompt; a
        "Consent:" statement is dropped; and a "Summary of Session" / "Main
        Observations" box is stored in the metadata. None of them is evidence.

        A vertically merged cell is emitted once, on its first row; on later rows it
        only supplies participant labels.
        Only include_evidence_types are kept, and turn_ids and character offsets are
        assigned after that filter.
        """
        metadata: Dict[str, Any] = {}
        questions: Dict[str, str] = {}
        # (block location, speaker, text, evidence_type, question_id)
        entries: List[Tuple[int, str, str, str, str]] = []
        mixed_label_rows: List[int] = []  # rows whose cells name different participants
        ambiguous_multilabel_rows: List[int] = []  # one cell names several; unlabelled text is "Unknown"
        pending: Dict[str, Any] = {"question_id": None, "prompt": []}
        notes_tables = 0
        location = 0

        def note_question(text: str) -> bool:
            match = _NOTES_QUESTION.match(text.strip())
            if not match:
                return False
            pending["question_id"] = f"Question {int(match.group(1))}"
            pending["prompt"] = _box_lines(match.group(2))
            return True

        def set_metadata(label: str, value: str) -> None:
            key = _metadata_key(label)
            if key and not metadata.get(key):
                metadata[key] = value.strip()

        def read_box(lines: List[str], keys: Optional[Sequence[str]] = None) -> bool:
            """Store a "Label: value" box (only a label in keys, when given); whether it was stored."""
            label, colon, rest = lines[0].partition(":")
            key = _metadata_key(label) if colon else ""
            if not key or (keys is not None and key not in keys):
                return False
            set_metadata(label, "\n".join(([rest.strip()] if rest.strip() else []) + lines[1:]))
            return True

        def read_metadata_table(rows: List[List[str]]) -> None:
            if max((len(cells) for cells in rows), default=0) == 1:
                lines = [ln for cells in rows if cells for ln in _box_lines(cells[0])]
                if lines and not note_question(lines[0]):
                    read_box(lines)
                return
            for cells in rows:
                col = 0
                while col < len(cells):
                    text = cells[col]
                    if text.endswith(":"):
                        value = cells[col + 1] if col + 1 < len(cells) and not cells[col + 1].endswith(":") else ""
                        set_metadata(text, "\n".join(_box_lines(value)))
                        col += 2 if value else 1
                        continue
                    label, colon, rest = text.partition(":")
                    if colon and rest.strip() and len(label.split()) <= _MAX_SPEAKER_WORDS:
                        set_metadata(label, rest)
                    col += 1

        def row_entries(row_block: int, cells: List[str], cols: Dict[str, List[int]], question_id: str,
                        continued: Set[int]) -> None:
            def text_at(col: int) -> str:
                return cells[col] if col < len(cells) else ""

            # A themes row carries a genuine "Themes / Topics / Patterns:" header and no
            # explicit "P#:" label in any new cell. Check Key Points columns first, then
            # left to right. A vertically merged themes cell was emitted on its first row,
            # so a continuation row is read as participant evidence.
            has_new_participant = any(
                pid for col, c in enumerate(cells) if c and col not in continued
                for pid, _ in _participant_segments(c)
            )
            if not has_new_participant:
                for col in dict.fromkeys(cols["key_points"] + list(range(len(cells)))):
                    themes = None if col in continued else _NOTES_THEMES.match(text_at(col))
                    if themes:
                        parts = [cells[col][themes.end():]] + [
                            c for i, c in enumerate(cells) if i != col and i not in continued]
                        text = " ".join(p for p in (_join_lines(part) for part in parts) if p)
                        if text:
                            entries.append((row_block, NOTES_THEMES_SPEAKER, text, "themes_summary", question_id))
                        return

            # Each contribution keeps its own "P#:" label. An unlabelled one takes the
            # row's label when the row names one participant, and is "Unknown" when the
            # row names several (no reliable owner). A continuation only supplies labels.
            contributions: List[Tuple[str, Optional[str], str, bool]] = []
            multilabel_cell = False
            for role, evidence_type in (("key_points", "key_point_paraphrase"),
                                        ("notable_quotes", "notable_quote_verbatim"),
                                        ("observations", "observation")):
                for col in cols.get(role, []):
                    segments = _participant_segments(text_at(col))
                    multilabel_cell |= len({pid for pid, _ in segments if pid}) > 1
                    contributions.extend((evidence_type, pid, text, col not in continued) for pid, text in segments)
            labels = set(pid for _, pid, _, _ in contributions if pid)
            row_pid = next(iter(labels)) if len(labels) == 1 else "Unknown"
            if len(labels) > 1:
                mixed_label_rows.append(row_block)
            if multilabel_cell and any(not pid and text and emit for _, pid, text, emit in contributions):
                ambiguous_multilabel_rows.append(row_block)
            for evidence_type, pid, text, emit in contributions:
                if text and emit:
                    entries.append((row_block, pid or row_pid, text, evidence_type, question_id))

        def structural_row(cells: List[str], cont: Set[int], cols: Dict[str, List[int]],
                           question_id: str) -> Optional[str]:
            """
            The question_id after an embedded structural row, or None when the row is
            evidence. A row with an explicit "P#:" label in any new cell is evidence. Otherwise
            the structural label cell is found in any column (Key Points columns first, then
            left to right) and the other new cells are its payload, so the result does not
            depend on column order. Inherited labels from vertically merged cells never
            exempt a genuine structural header; ordinary prose stays evidence.
            """
            new_cells = [(col, c) for col, c in enumerate(cells) if c and col not in cont]
            if not new_cells:
                return None
            if any(pid for _, c in new_cells for pid, _ in _participant_segments(c)):
                return None
            order = sorted(new_cells, key=lambda item: (item[0] not in cols["key_points"], item[0]))
            for label_col, label_text in order:
                first_lines = _box_lines(label_text)
                if not first_lines:
                    continue
                head = first_lines[0]
                summary_label = _NOTES_SUMMARY_LABEL.match(head)
                if not (_NOTES_EMBEDDED_QUESTION.match(head) or _NOTES_PROMPT.match(head)
                        or _NOTES_CONSENT.match(head) or summary_label):
                    continue
                extra_lines = [ln for col, c in new_cells if col != label_col for ln in _box_lines(c)]
                if _NOTES_EMBEDDED_QUESTION.match(head):
                    match = _NOTES_QUESTION.match(label_text.strip())
                    question_id = f"Question {int(match.group(1))}"
                    questions[question_id] = "\n".join(_box_lines(match.group(2)) + extra_lines)
                    return question_id
                if _NOTES_PROMPT.match(head):
                    if len(first_lines) == 1 and head.endswith(":") and extra_lines:
                        prompt_lines = [f"{head} {extra_lines[0]}"] + extra_lines[1:]
                    else:
                        prompt_lines = first_lines + extra_lines
                    if question_id in questions:
                        questions[question_id] = "\n".join(_box_lines(questions[question_id]) + prompt_lines)
                    return question_id
                if summary_label:
                    rest = (summary_label.group(2) or "").strip()
                    set_metadata(summary_label.group(1),
                                 "\n".join(([rest] if rest else []) + first_lines[1:] + extra_lines))
                return question_id
            return None

        for para, rows, continued in blocks:
            if rows is None:
                location += 1
                text = para.strip()
                if _is_banner(text):
                    self.last_fixture_banner_lines.append(location)
                elif text and not note_question(text) and pending["question_id"]:
                    pending["prompt"].extend(_box_lines(text))
                continue

            first_block = location + 1
            location += len(rows)
            banner_rows = [r_idx for r_idx, cells in enumerate(rows) if any(_is_banner(c) for c in cells)]
            self.last_fixture_banner_lines.extend(first_block + r_idx for r_idx in banner_rows)
            rows = [["" if _is_banner(c) else c for c in cells] for cells in rows]

            found = _notes_columns(rows)
            if found is None:
                read_metadata_table(rows)
                continue

            header_idx, cols = found
            notes_tables += 1
            for cells in rows[:header_idx]:
                note_question(" ".join(c for c in cells if c))
            question_id = pending["question_id"] or f"Question {notes_tables}"
            if pending["question_id"]:
                questions[question_id] = "\n".join(pending["prompt"])
            pending.update(question_id=None, prompt=[])
            for r_idx in range(header_idx + 1, len(rows)):
                cells, cont = rows[r_idx], continued[r_idx]
                if _notes_columns([cells]):
                    continue  # header repeated on a new page
                next_question = structural_row(cells, cont, cols, question_id)
                if next_question is not None:
                    question_id = next_question
                    continue
                row_entries(first_block + r_idx, cells, cols, question_id, cont)

        metadata["questions"] = questions
        metadata["mixed_label_rows"] = mixed_label_rows
        metadata["ambiguous_multilabel_rows"] = ambiguous_multilabel_rows
        self.last_document_metadata[source_id] = metadata

        kept = [e for e in entries if e[3] in self.include_evidence_types]
        raw_entries = [(block, speaker, "", text) for block, speaker, text, _, _ in kept]
        participant_ids = [f"{source_id}::{speaker}" for _, speaker, _, _, _ in kept]
        unit_ids = participant_ids if self.notes_unit_level == "participant" else [source_id] * len(kept)
        turns = self._normalize_turns(raw_entries, file_path, source_id, unit_ids, auto_detect=False)
        for turn, (_, _, _, evidence_type, question_id), participant_id in zip(turns, kept, participant_ids):
            if evidence_type == "themes_summary":
                turn["is_facilitator"] = True
            turn.update(
                document_structure="focus_group_notes",
                evidence_type=evidence_type,
                question_id=question_id,
                group_id=source_id,
                participant_id=participant_id,
            )
        return turns

    def _add_structure_keys(self, turns: List[Dict[str, Any]], structure: str) -> List[Dict[str, Any]]:
        """Additive keys for a transcript or tabular parse (also on last_excluded_turns)."""
        for record in turns + self.last_excluded_turns:
            record.update(
                document_structure=structure,
                evidence_type="verbatim_turn",
                question_id="",
                group_id=record["source_id"],
                participant_id=record["unit_id"],
            )
        return turns

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

        self.last_document_metadata.pop(source_id, None)
        self.last_document_structure = "tabular"
        turns = self._normalize_turns(raw_entries, file_path, source_id, unit_ids, auto_detect=False)
        return self._add_structure_keys(turns, "tabular")

    def _read_csv(self, file_path: str) -> Tuple[pd.DataFrame, List[int]]:
        """
        Read a CSV whose header may be preceded by '#' comment lines (e.g. a
        SOFTWARE_TEST banner) or blank lines. Only leading comment lines are skipped,
        so '#' inside a response is never truncated. A single csv.reader pass yields
        both the values and the 1-based physical start line of each data record
        (quoted multi-line cells span several physical lines). Blank or
        whitespace-only physical lines are not records; short records are padded
        with empty cells, and a record with extra non-empty cells raises ValueError.
        Malformed quoting (an unterminated quoted cell, or a character other than
        ',' or a line break after a closing quote) raises ValueError, so a stray
        quote can never merge the following records into one cell.
        """
        name = os.path.basename(file_path)
        with open(file_path, "r", encoding="utf-8-sig", newline="") as fh:
            leading = 0
            for line in fh:
                if line.strip() == "" or line.lstrip().startswith("#"):
                    leading += 1
                    continue
                break
            fh.seek(0)
            lines = fh.readlines()
        _validate_csv_quoting("".join(lines[leading:]), name, leading + 1)

        header: Optional[List[str]] = None
        rows: List[List[str]] = []
        data_starts: List[int] = []
        with open(file_path, "r", encoding="utf-8-sig", newline="") as fh:
            for _ in range(leading):
                next(fh)
            reader = csv.reader(fh, strict=True)
            while True:
                start = leading + reader.line_num + 1
                try:
                    rec = next(reader)
                except StopIteration:
                    break
                except csv.Error as exc:
                    raise ValueError(f"Malformed CSV at line {start} of {name}: {exc}") from exc
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
