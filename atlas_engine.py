"""
ATLAS Engine
Core deterministic natural language processing engine for qualitative policy
and mixed-methods analysis. Implements reproducible, auditable bilingual
rule execution, context and exclusion fencing, combining-mark-insensitive
matching with exact verbatim spans, cryptographic provenance tracking, and
actuarial spreadsheet export.
"""

import bisect
import hashlib
import json
import math
import os
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import openpyxl
import pandas as pd
import yaml
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.exceptions import InvalidFileException

from universal_transcript_parser import TABULAR_EXTENSIONS, UniversalTranscriptParser

FREQUENCY_SHEET = "Empirical Frequencies"
FREQUENCY_HEADERS = [
    "Domain ID", "Policy Domain Name", "Reporting Documents", "Total Documents", "Prevalence Rate (%)",
    "Matching Dialogue Turns", "Plain Language Empirical Statement",
]
QUOTE_COLUMNS = [
    "domain_id", "domain_name", "document_name", "source_id", "unit_id", "turn_id", "line_number",
    "timestamp", "speaker", "text", "char_start", "char_end", "match_char_start", "match_char_end",
    "match_text", "source_sha256",
    # v1.2 notes provenance, appended after the v1.1 columns ("" when a turn lacks them).
    "evidence_type", "question_id", "group_id", "participant_id",
]
NOTES_PROVENANCE_COLUMNS = ("evidence_type", "question_id", "group_id", "participant_id")
NOTES_THEMES_EVIDENCE_TYPE = "themes_summary"
# Evidence holding the speaker's own words: notes "Notable Quotes" cells, transcript or
# survey turns, and legacy turns without an evidence type. Paraphrased key points and
# note-taker observations are coded evidence but never verbatim quotations.
VERBATIM_EVIDENCE_TYPES = ("notable_quote_verbatim", "verbatim_turn", "")
NOTES_EVIDENCE_LABELS = {
    "notable_quote_verbatim": "Verbatim Quote (notes)",
    "key_point_paraphrase": "Paraphrase (Key Point, not verbatim)",
    "observation": "Note-Taker Observation (not verbatim)",
    "verbatim_turn": "Verbatim Turn (transcript / survey)",
    "": "Verbatim Turn (transcript / survey)",
}
CODED_EVIDENCE_EXPORT = "coded_evidence_inventory"


def has_non_verbatim_evidence(quotes_df: pd.DataFrame) -> bool:
    """Whether any coded row is a paraphrase or observation rather than verbatim words."""
    if quotes_df is None or len(quotes_df) == 0 or "evidence_type" not in quotes_df.columns:
        return False
    return bool((~quotes_df["evidence_type"].astype(str).isin(VERBATIM_EVIDENCE_TYPES)).any())


def verbatim_only(quotes_df: pd.DataFrame) -> pd.DataFrame:
    """The rows of quotes_df that are verbatim words (see VERBATIM_EVIDENCE_TYPES)."""
    if "evidence_type" not in quotes_df.columns:
        return quotes_df
    return quotes_df[quotes_df["evidence_type"].astype(str).isin(VERBATIM_EVIDENCE_TYPES)].reset_index(drop=True)
_TOKEN = re.compile(r"\w+")


# ----------------------------------------------------------------------
# Combining-mark folding with an exact index map
# ----------------------------------------------------------------------
def fold_accents_with_map(text: str) -> Tuple[str, List[int]]:
    """
    Strip combining marks (Unicode category Mn) after per-character NFD
    decomposition, so NFC "é" and NFD "e\\u0301" both fold to "e". Characters
    without a canonical decomposition ("ﬁ", "ß") are kept 1-to-1.

    Returns (folded, index_map) where folded[j] came from text[index_map[j]];
    index_map carries a trailing sentinel len(text).
    """
    folded_chars: List[str] = []
    index_map: List[int] = []
    for orig_i, ch in enumerate(text):
        for c in unicodedata.normalize("NFD", ch):
            if unicodedata.category(c) != "Mn":
                folded_chars.append(c)
                index_map.append(orig_i)
    index_map.append(len(text))
    return "".join(folded_chars), index_map


def fold_accents(text: str) -> str:
    return fold_accents_with_map(text)[0]


def folded_span_to_original(text: str, index_map: Sequence[int], folded_start: int, folded_end: int) -> Tuple[int, int]:
    """Map a non-empty folded [start, end) span back to [start, end) in the original text."""
    orig_start = index_map[folded_start]
    orig_end = index_map[folded_end - 1] + 1
    while orig_end < len(text) and unicodedata.category(text[orig_end]) == "Mn":
        orig_end += 1
    return orig_start, orig_end


# ----------------------------------------------------------------------
# Codebook normalization
# ----------------------------------------------------------------------
def _first_present(item: Dict[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return default


def _term_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        value = [value]
    terms = []
    for term in value:
        if term is None:
            continue
        term = str(term).strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def _parse_window(value: Any, label: str, rule_id: str) -> Optional[int]:
    """
    A token window is None (turn-level) or a nonnegative whole number: an int, an
    integral float such as 8.0, or a string of digits such as "8". Anything else
    (negative, fractional, boolean, "8 tokens") is rejected so a malformed window
    can never silently change what a rule matches.
    """
    if value is None:
        return None
    window: Optional[int] = None
    if isinstance(value, bool):
        window = None
    elif isinstance(value, int):
        window = value
    elif isinstance(value, float) and value.is_integer():
        window = int(value)
    elif isinstance(value, str) and value.strip().isdigit() and value.strip().isascii():
        window = int(value.strip())
    if window is None or window < 0:
        raise ValueError(f"{label} for rule {rule_id!r} must be a nonnegative whole token count, not {value!r}")
    return window


def _normalize_rule(item: Dict[str, Any], default_id: str) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"Codebook rule {default_id!r} must be a mapping, got {type(item).__name__}")
    rule_id = str(_first_present(item, ("id",), default_id))
    roots_en = _term_list(item.get("roots_en")) + _term_list(item.get("keywords"))
    return {
        "id": rule_id,
        "name": str(_first_present(item, ("name", "label"), rule_id)),
        "description": str(_first_present(item, ("description", "definition"), "")),
        "roots_en": _term_list(roots_en),
        "roots_es": _term_list(item.get("roots_es")),
        "context_fences": _term_list(_first_present(item, ("context_fences", "required_context"), [])),
        "context_window": _first_present(item, ("context_window", "co_occurrence_window")),
        "exclude_fences": _term_list(_first_present(item, ("exclude_fences", "negative_fences", "exclude_terms"), [])),
        "exclude_window": item.get("exclude_window"),
    }


def normalize_codebook_rules(codebook: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flatten the supported codebook schemas into one ordered list of rules:
    'domains' (researcher), 'topics' as a dict or list (practitioner), or
    'themes' followed by 'frictions' (benchmarking).
    """
    items: List[Tuple[Any, str]] = []
    if codebook.get("domains") is not None:
        items = [(d, f"domain_{i}") for i, d in enumerate(codebook["domains"] or [], 1)]
    elif codebook.get("topics") is not None:
        topics = codebook["topics"]
        if isinstance(topics, dict):
            for t_id, t_info in topics.items():
                info = dict(t_info or {})
                info.setdefault("id", t_id)
                items.append((info, str(t_id)))
        else:
            for i, t_info in enumerate(topics or [], 1):
                info = dict(t_info or {})
                if "id" not in info and info.get("label") is not None:
                    info["id"] = info["label"]
                items.append((info, f"topic_{i}"))
    else:
        for section in ("themes", "frictions"):
            section_items = codebook.get(section) or []
            if not isinstance(section_items, list):
                raise ValueError(f"Codebook section {section!r} must be a list")
            items.extend((d, f"{section}_{i}") for i, d in enumerate(section_items, 1))

    rules = [_normalize_rule(item, default_id) for item, default_id in items]
    seen = set()
    for rule in rules:
        if rule["id"] in seen:
            raise ValueError(f"Duplicate codebook rule id {rule['id']!r}")
        seen.add(rule["id"])
    return rules


def _compile_terms(terms: Sequence[str]) -> Optional["re.Pattern[str]"]:
    """Word-boundary-anchored stem alternation over folded terms, longest first."""
    folded = sorted({fold_accents(t) for t in terms if fold_accents(t)}, key=lambda t: (-len(t), t))
    if not folded:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in folded) + r")", re.IGNORECASE)


def _compile_term_patterns(terms: Sequence[str]) -> List["re.Pattern[str]"]:
    """One word-boundary-anchored stem pattern per distinct folded term, longest first."""
    folded = sorted({fold_accents(t) for t in terms if fold_accents(t)}, key=lambda t: (-len(t), t))
    return [re.compile(r"\b" + re.escape(t), re.IGNORECASE) for t in folded]


def _find_overlapping_spans(patterns: Sequence["re.Pattern[str]"], text: str) -> List[Tuple[int, int]]:
    """
    Every occurrence of every pattern, including occurrences that overlap one
    another, sorted by earliest start and then longest span.
    """
    spans = set()
    for pat in patterns:
        pos = 0
        while pos < len(text):
            m = pat.search(text, pos)
            if m is None:
                break
            spans.add(m.span())
            pos = m.start() + 1
    return sorted(spans, key=lambda s: (s[0], -s[1]))


def _to_finite_float(value: Any) -> Optional[float]:
    """float(value) when it is a finite non-boolean number or numeric string, else None."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _expected_prevalence(documents_reporting: int, total_documents: int) -> Optional[float]:
    """Rounded prevalence percentage, or None when the division cannot yield a finite float."""
    if total_documents <= 0:
        return 0.0
    try:
        return _to_finite_float(round(documents_reporting / total_documents * 100.0, 1))
    except (OverflowError, ZeroDivisionError):
        return None


def audit_digest(domain_id: Any, documents_reporting: int, total_documents: int, matching_turns: int,
                 prevalence_pct: float, file_hashes: Dict[str, str]) -> str:
    """Consistency-bound SHA-256 that ties a frequency row to the exact source files."""
    shas = "+".join(sorted(file_hashes.values()))
    payload = (
        f"{domain_id}|{int(documents_reporting)}|{int(total_documents)}|{int(matching_turns)}|"
        f"{float(prevalence_pct):.1f}|{shas}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _audit_comment_text(domain_name: Any, documents_reporting: int, total_documents: int,
                        matching_turns: int, digest: str) -> str:
    return (
        f"ATLAS VERIFICATION AUDIT STAMP\n"
        f"Domain: {domain_name}\n"
        f"Documents: {int(documents_reporting)} / {int(total_documents)}\n"
        f"Matching Turns: {int(matching_turns)}\n"
        f"Verification SHA-256: {digest}\n"
        f"Status: PASS (Deterministic Match)"
    )


def _reporting_statement(prevalence_pct: float, documents_reporting: int, total_documents: int,
                         matching_turns: int, domain_name: Any) -> str:
    return (
        f"{prevalence_pct}% of documents ({documents_reporting} of {total_documents}) across "
        f"{matching_turns} matching turns reported {str(domain_name).lower()}."
    )


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_COUNTS = ("total_documents", "total_turns_parsed", "participant_turns_analyzed")
_DOMAIN_COUNTS = ("documents_reporting", "total_documents", "matching_turns")
# Largest integer an IEEE-754 double (and so an Excel numeric cell) holds exactly.
_MAX_EXACT_COUNT = (1 << 53) - 1
_COUNT_RULE = f"an integer from 0 to {_MAX_EXACT_COUNT}"


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_EXACT_COUNT


def _short_repr(value: Any, limit: int = 60) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > 200:
        # Avoid repr: Python refuses int-to-str conversion past 4300 digits.
        return f"an integer of {value.bit_length()} bits"
    text = repr(value)
    return text if len(text) <= limit else f"{text[:limit]}... ({len(text)} chars)"


def validate_manifest(manifest: Any) -> Tuple[List[str], List[Optional[Dict[str, Any]]]]:
    """
    Structural and arithmetic validation of a provenance manifest, without raising.

    Returns (reasons, domains) where domains[i] is the i-th domain entry when it
    is well formed and None otherwise. Counts must be integers in
    [0, _MAX_EXACT_COUNT] (exactly representable in a double / Excel cell) and
    obey the relationships any real export satisfies:
      participant_turns_analyzed <= total_turns_parsed;
      per domain: total_documents equals the manifest total,
      documents_reporting <= total_documents,
      documents_reporting <= matching_turns <= participant_turns_analyzed,
      and matching_turns > 0 implies documents_reporting >= 1.
    """
    if not isinstance(manifest, dict):
        return [f"manifest must be a JSON object, got {type(manifest).__name__}"], []
    reasons: List[str] = []
    for key in _MANIFEST_COUNTS:
        if not _is_count(manifest.get(key)):
            reasons.append(f"manifest {key} must be {_COUNT_RULE}, got {_short_repr(manifest.get(key))}")
    counts_ok = not reasons
    if counts_ok and manifest["participant_turns_analyzed"] > manifest["total_turns_parsed"]:
        reasons.append("manifest participant_turns_analyzed exceeds total_turns_parsed")

    file_hashes = manifest.get("file_hashes")
    if not isinstance(file_hashes, dict):
        reasons.append("manifest file_hashes must be a mapping of source_id to SHA-256")
    else:
        for source_id, sha in file_hashes.items():
            if not isinstance(sha, str) or not _HEX64.match(sha):
                reasons.append(f"manifest file_hashes[{_short_repr(source_id)}] is not a lowercase SHA-256 hex digest")

    raw_domains = manifest.get("domains")
    if not isinstance(raw_domains, list):
        reasons.append("manifest domains must be a list")
        return reasons, []

    domains: List[Optional[Dict[str, Any]]] = []
    seen_ids = set()
    for pos, dom in enumerate(raw_domains, 1):
        label = f"manifest domain entry {pos}"
        if not isinstance(dom, dict):
            reasons.append(f"{label} must be an object")
            domains.append(None)
            continue
        problems = []
        domain_id = dom.get("domain_id")
        if not isinstance(domain_id, str) or not domain_id:
            problems.append(f"domain_id must be a non-empty string, got {_short_repr(domain_id)}")
        elif domain_id in seen_ids:
            problems.append(f"duplicate domain_id {domain_id!r}")
        else:
            seen_ids.add(domain_id)
            label = f"{label} ({domain_id})"
        if not isinstance(dom.get("domain_name"), str):
            problems.append(f"domain_name must be a string, got {_short_repr(dom.get('domain_name'))}")
        for key in _DOMAIN_COUNTS:
            if not _is_count(dom.get(key)):
                problems.append(f"{key} must be {_COUNT_RULE}, got {_short_repr(dom.get(key))}")
        prev = dom.get("prevalence_pct")
        if not isinstance(prev, (int, float)) or _to_finite_float(prev) is None:
            problems.append(f"prevalence_pct must be a finite number, got {_short_repr(prev)}")
        if not isinstance(dom.get("audit_sha256"), str):
            problems.append("audit_sha256 must be a string")
        if not problems:
            docs, total, turns = dom["documents_reporting"], dom["total_documents"], dom["matching_turns"]
            if counts_ok and total != manifest["total_documents"]:
                problems.append(f"total_documents {total} != manifest total_documents {manifest['total_documents']}")
            if docs > total:
                problems.append(f"documents_reporting {docs} exceeds total_documents {total}")
            if docs > turns:
                problems.append(f"documents_reporting {docs} exceeds matching_turns {turns}")
            if turns > 0 and docs == 0:
                problems.append(f"{turns} matching turns but no reporting documents")
            if counts_ok and turns > manifest["participant_turns_analyzed"]:
                problems.append(
                    f"matching_turns {turns} exceeds participant_turns_analyzed {manifest['participant_turns_analyzed']}"
                )
        reasons.extend(f"{label}: {p}" for p in problems)
        domains.append(None if problems else dom)
    return reasons, domains


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AtlasEngine:
    """
    Deterministic text analysis and qualitative synthesis engine.
    """

    def __init__(self, codebook_path: str):
        """
        Initialize the engine with a structured YAML codebook.
        """
        if not os.path.exists(codebook_path):
            raise FileNotFoundError(f"Codebook file not found: {codebook_path}")

        with open(codebook_path, "r", encoding="utf-8") as f:
            self.codebook = yaml.safe_load(f) or {}
        if not isinstance(self.codebook, dict):
            raise ValueError(f"Codebook {codebook_path} must be a YAML mapping")

        meta = self.codebook.get("meta") if isinstance(self.codebook.get("meta"), dict) else {}
        self.project_name = (
            self.codebook.get("project")
            or self.codebook.get("program_name")
            or meta.get("project")
            or "Qualitative Policy Study"
        )
        self.domains = normalize_codebook_rules(self.codebook)
        self._compile_patterns()

    def _compile_patterns(self):
        """
        Pre-compile combining-mark-folded root, context-fence and exclusion-fence
        patterns for high-throughput execution.
        """
        self.compiled_rules = []
        for domain in self.domains:
            rule_id = domain["id"]
            roots = domain.get("roots_en", []) + domain.get("roots_es", [])
            self.compiled_rules.append({
                "id": rule_id,
                "name": domain["name"],
                "description": domain.get("description", ""),
                "root_regex": _compile_terms(roots),
                "root_patterns": _compile_term_patterns(roots),
                "fence_regex": _compile_terms(domain.get("context_fences", [])),
                "fence_patterns": _compile_term_patterns(domain.get("context_fences", [])),
                "context_window": _parse_window(domain.get("context_window"), "context_window", rule_id),
                "exclude_regex": _compile_terms(domain.get("exclude_fences", [])),
                "exclude_patterns": _compile_term_patterns(domain.get("exclude_fences", [])),
                "exclude_window": _parse_window(domain.get("exclude_window"), "exclude_window", rule_id),
            })

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------
    @staticmethod
    def _token_interval(token_starts: List[int], start: int, end: int) -> Tuple[int, int]:
        if not token_starts:
            return 0, 0
        first = max(bisect.bisect_right(token_starts, start) - 1, 0)
        last = max(bisect.bisect_right(token_starts, max(end - 1, start)) - 1, first)
        return first, last

    @staticmethod
    def _count_mentions(spans: List[Tuple[int, int]]) -> int:
        """
        Mentions are non-overlapping qualifying spans, chosen greedily in span
        order (earliest start, longest first), so nested or overlapping roots
        such as "alpha" inside "alpha beta" count once.
        """
        count, covered_to = 0, -1
        for start, end in spans:
            if start >= covered_to:
                count += 1
                covered_to = end
        return count

    @staticmethod
    def _interval_gap(a: Tuple[int, int], b: Tuple[int, int]) -> int:
        return max(0, b[0] - a[1], a[0] - b[1])

    def _match_rule(self, rule: Dict[str, Any], folded: str, token_starts: List[int]) -> List[Tuple[int, int]]:
        """
        Return the folded (start, end) spans of every root occurrence that
        satisfies the rule's context fences without violating its exclusion fences.

        Root and fence occurrences are enumerated individually per term, so
        overlapping occurrences (e.g. "alpha beta" and "beta gamma" in
        "alpha beta gamma") are each evaluated against the windows. Spans are
        ordered by earliest start, then longest.
        """
        if not rule["root_patterns"]:
            return []
        roots = _find_overlapping_spans(rule["root_patterns"], folded)
        if not roots:
            return []

        has_fences, fence_window = bool(rule["fence_patterns"]), rule["context_window"]
        fences = _find_overlapping_spans(rule["fence_patterns"], folded)
        if has_fences and not fences:
            return []

        excl_window = rule["exclude_window"]
        excludes = _find_overlapping_spans(rule["exclude_patterns"], folded)
        if excludes and excl_window is None:
            return []

        fence_toks = [self._token_interval(token_starts, s, e) for s, e in fences]
        excl_toks = [self._token_interval(token_starts, s, e) for s, e in excludes]

        qualifying = []
        for r_start, r_end in roots:
            r_tok = self._token_interval(token_starts, r_start, r_end)
            if has_fences and fence_window is not None:
                if not any(self._interval_gap(r_tok, f_tok) <= fence_window for f_tok in fence_toks):
                    continue
            if excl_window is not None and any(self._interval_gap(r_tok, x_tok) <= excl_window for x_tok in excl_toks):
                continue
            qualifying.append((r_start, r_end))
        return qualifying

    # ------------------------------------------------------------------
    # Corpus processing
    # ------------------------------------------------------------------
    def process_corpus(
        self,
        transcript_files: List[str],
        facilitator_names: Optional[List[str]] = None,
        interviewer_prompt_patterns: Optional[List[str]] = None,
        root_dir: Optional[str] = None,
        tabular_options: Optional[Dict[str, Any]] = None,
        include_evidence_types: Optional[Sequence[str]] = None,
        notes_unit_level: str = "group",
    ) -> Dict[str, Any]:
        """
        Parse transcript and tabular files and generate verified frequency matrices.

        file_hashes is keyed by source_id: the POSIX path relative to root_dir when
        given, otherwise the canonical absolute path, so files sharing a basename in
        different folders never collide. tabular_options (text_col, id_col,
        speaker_col, allow_duplicate_ids) apply to .csv/.xlsx inputs.
        include_evidence_types and notes_unit_level are passed to the parser and only
        affect structured focus-group notes (.docx).

        Besides the process_turns keys, the result holds document_structures
        ({source_id: "transcript" | "tabular" | "focus_group_notes"}), notes_metadata
        (the parser's per-file notes metadata) and note_taker_themes_df: every
        note-taker "Themes" row of the notes files, read by a separate parse so it is
        reference only and never enters the coded turns, frequencies or quotes.
        """
        parser = UniversalTranscriptParser(
            facilitator_names=facilitator_names,
            interviewer_prompt_patterns=interviewer_prompt_patterns,
            root_dir=root_dir,
            include_evidence_types=include_evidence_types,
            notes_unit_level=notes_unit_level,
        )
        themes_parser = UniversalTranscriptParser(
            root_dir=root_dir, include_evidence_types=(NOTES_THEMES_EVIDENCE_TYPE,),
        )
        all_turns: List[Dict[str, Any]] = []
        theme_turns: List[Dict[str, Any]] = []
        file_hashes: Dict[str, str] = {}
        document_structures: Dict[str, str] = {}
        seen_paths = set()

        for file_path in transcript_files:
            resolved = Path(file_path).resolve().as_posix()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            ext = os.path.splitext(file_path)[1].lower()
            if ext in TABULAR_EXTENSIONS and tabular_options:
                turns = parser.parse_tabular(file_path, root_dir=root_dir, **tabular_options)
            else:
                turns = parser.parse_file(file_path, root_dir=root_dir)

            source_id = parser._source_id(file_path, root_dir)
            if source_id in file_hashes:
                raise ValueError(f"Two inputs resolve to the same source_id {source_id!r}")
            file_hashes[source_id] = _sha256_file(file_path)
            document_structures[source_id] = parser.last_document_structure
            all_turns.extend(turns)
            if parser.last_document_structure == "focus_group_notes":
                theme_turns.extend(themes_parser.parse_file(file_path, root_dir=root_dir))

        results = self.process_turns(all_turns, file_hashes)
        results["document_structures"] = document_structures
        results["notes_metadata"] = dict(parser.last_document_metadata)
        results["note_taker_themes_df"] = pd.DataFrame(theme_turns)
        return results

    process_transcripts = process_corpus

    def process_turns(self, turns: List[Dict[str, Any]], file_hashes: Dict[str, str]) -> Dict[str, Any]:
        """
        Tag pre-parsed turns (e.g. from Streamlit uploads) against the compiled rules.

        file_hashes maps each turn's source_id to the SHA-256 of its source file.
        Prevalence denominators count distinct participant unit_ids (one per
        transcript, one per tabular respondent row).
        """
        file_hashes = dict(file_hashes)
        participant_turns = [t for t in turns if not t.get("is_facilitator", False)]

        tagged_records = []
        quote_inventory = []
        mention_counts = {rule["id"]: 0 for rule in self.compiled_rules}

        for turn in participant_turns:
            text = turn["text"]
            source_id = turn.get("source_id") or turn.get("document_name")
            unit_id = turn.get("unit_id") or source_id
            if source_id not in file_hashes:
                raise ValueError(f"No source file hash supplied for source_id {source_id!r}")

            folded, index_map = fold_accents_with_map(text)
            token_starts = [m.start() for m in _TOKEN.finditer(folded)]
            matched_domains = []

            for rule in self.compiled_rules:
                spans = self._match_rule(rule, folded, token_starts)
                if not spans:
                    continue
                mention_counts[rule["id"]] += self._count_mentions(spans)
                f_start, f_end = spans[0]
                match_start, match_end = folded_span_to_original(text, index_map, f_start, f_end)
                if fold_accents(text[match_start:match_end]) != folded[f_start:f_end]:
                    raise RuntimeError(
                        f"Span mapping inconsistency for rule {rule['id']!r} in {unit_id!r}: "
                        f"{text[match_start:match_end]!r} does not fold to {folded[f_start:f_end]!r}"
                    )

                matched_domains.append(rule["id"])
                quote_inventory.append({
                    "domain_id": rule["id"],
                    "domain_name": rule["name"],
                    "document_name": turn.get("document_name", os.path.basename(str(source_id))),
                    "source_id": source_id,
                    "unit_id": unit_id,
                    "turn_id": turn.get("turn_id"),
                    "line_number": turn.get("line_number"),
                    "timestamp": turn.get("timestamp", ""),
                    "speaker": turn.get("speaker", "Unknown"),
                    "text": text,
                    "char_start": turn.get("char_start"),
                    "char_end": turn.get("char_end"),
                    "match_char_start": match_start,
                    "match_char_end": match_end,
                    "match_text": text[match_start:match_end],
                    "source_sha256": file_hashes[source_id],
                    **{col: str(turn.get(col) or "") for col in NOTES_PROVENANCE_COLUMNS},
                })

            record = dict(turn)
            record["matched_domains"] = matched_domains
            tagged_records.append(record)

        all_unit_ids = self._analytical_units(turns, file_hashes)
        total_docs = len(all_unit_ids)

        frequency_rows = []
        for rule in self.compiled_rules:
            dom_quotes = [q for q in quote_inventory if q["domain_id"] == rule["id"]]
            doc_count = len({q["unit_id"] for q in dom_quotes})
            prevalence_pct = round((doc_count / total_docs * 100.0) if total_docs > 0 else 0.0, 1)
            frequency_rows.append({
                "domain_id": rule["id"],
                "domain_name": rule["name"],
                "documents_reporting": doc_count,
                "total_documents": total_docs,
                "prevalence_pct": prevalence_pct,
                "matching_turns": len(dom_quotes),
                "total_mentions": mention_counts[rule["id"]],
                "reporting_statement": _reporting_statement(
                    prevalence_pct, doc_count, total_docs, len(dom_quotes), rule["name"]
                ),
            })

        return {
            "project_name": self.project_name,
            "total_documents": total_docs,
            "total_turns_parsed": len(turns),
            "participant_turns_analyzed": len(participant_turns),
            "file_hashes": file_hashes,
            "frequencies_df": pd.DataFrame(frequency_rows),
            "quotes_df": pd.DataFrame(quote_inventory, columns=QUOTE_COLUMNS),
            "tagged_turns_df": pd.DataFrame(tagged_records),
        }

    @staticmethod
    def _analytical_units(turns: List[Dict[str, Any]], file_hashes: Dict[str, str]) -> set:
        """
        Prevalence denominator: every analytical unit among all parsed inputs,
        before facilitator filtering.

        - A transcript (unit_id == source_id) is one unit even when every turn in
          it is a facilitator turn, and a transcript that parsed to no turns at
          all still counts as one document.
        - A tabular respondent row (unit_id "<source_id>::<id>" or "...#row_N") is
          a unit when it holds a participant response. A row flagged as a
          facilitator (a configured facilitator speaker or a matched interviewer
          prompt pattern) is a prompt, not a respondent, and is not counted.
        """
        units = set()
        sources_with_turns = set()
        for t in turns:
            source_id = t.get("source_id") or t.get("document_name")
            unit_id = t.get("unit_id") or source_id
            sources_with_turns.add(source_id)
            if not t.get("is_facilitator", False) or unit_id == source_id:
                units.add(unit_id)
        for source_id in file_hashes:
            if source_id not in sources_with_turns and os.path.splitext(source_id)[1].lower() not in TABULAR_EXTENSIONS:
                units.add(source_id)
        return units

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    @staticmethod
    def build_manifest(results: Dict[str, Any]) -> Dict[str, Any]:
        file_hashes = dict(results["file_hashes"])
        domains = []
        for _, r in results["frequencies_df"].iterrows():
            dom = {
                "domain_id": str(r["domain_id"]),
                "domain_name": str(r["domain_name"]),
                "documents_reporting": int(r["documents_reporting"]),
                "total_documents": int(r["total_documents"]),
                "prevalence_pct": float(r["prevalence_pct"]),
                "matching_turns": int(r["matching_turns"]),
            }
            dom["audit_sha256"] = audit_digest(
                dom["domain_id"], dom["documents_reporting"], dom["total_documents"],
                dom["matching_turns"], dom["prevalence_pct"], file_hashes,
            )
            domains.append(dom)
        return {
            "project_name": results["project_name"],
            "total_documents": int(results["total_documents"]),
            "total_turns_parsed": int(results["total_turns_parsed"]),
            "participant_turns_analyzed": int(results["participant_turns_analyzed"]),
            "file_hashes": file_hashes,
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "domains": domains,
        }

    def export_results(self, results: Dict[str, Any], output_dir: str):
        """
        Export verified matrices to open standard formats (CSV, Parquet, Excel)
        plus provenance_manifest.json.

        verbatim_quotes_inventory.csv / .parquet hold verbatim words only. When the
        coded evidence also holds paraphrased key points or note-taker observations
        (structured focus-group notes), every coded row, labelled by evidence_type,
        is also written to coded_evidence_inventory.csv / .parquet; otherwise the
        outputs are exactly the v1.1 set, and any coded_evidence_inventory files an
        earlier export left in output_dir are removed.
        """
        os.makedirs(output_dir, exist_ok=True)

        quotes = results["quotes_df"]
        results["frequencies_df"].to_csv(os.path.join(output_dir, "thematic_frequencies.csv"), index=False)
        verbatim = verbatim_only(quotes)
        verbatim.to_csv(os.path.join(output_dir, "verbatim_quotes_inventory.csv"), index=False)
        verbatim.to_parquet(os.path.join(output_dir, "verbatim_quotes_inventory.parquet"), index=False)
        coded_paths = [os.path.join(output_dir, f"{CODED_EVIDENCE_EXPORT}{ext}") for ext in (".csv", ".parquet")]
        if has_non_verbatim_evidence(quotes):
            quotes.to_csv(coded_paths[0], index=False)
            quotes.to_parquet(coded_paths[1], index=False)
        else:
            # A reused output directory must not keep a coded-evidence inventory from an
            # earlier corpus; only these ATLAS-named files are removed.
            for path in coded_paths:
                if os.path.isfile(path):
                    os.remove(path)

        manifest = self.build_manifest(results)
        self._export_excel(results, manifest, os.path.join(output_dir, "actuarial_parameter_matrix.xlsx"))

        with open(os.path.join(output_dir, "provenance_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        print(f"Exported clean results to: {output_dir}")

    def _export_excel(self, results: Dict[str, Any], manifest: Dict[str, Any], excel_path: str):
        """
        Generate publication-ready Excel workbook formatted with cell comments and audit hashes.
        """
        wb = openpyxl.Workbook()
        ws_summary = wb.active
        ws_summary.title = FREQUENCY_SHEET

        NAVY_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        BORDER_GRAY = Side(style="thin", color="CBD5E1")
        BORDER_BOX = Border(top=BORDER_GRAY, left=BORDER_GRAY, right=BORDER_GRAY, bottom=BORDER_GRAY)
        FONT_HEADER = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        FONT_BODY = Font(name="Calibri", size=10, color="1E293B")
        FONT_BOLD = Font(name="Calibri", size=10, bold=True, color="1E293B")

        for col_idx, h in enumerate(FREQUENCY_HEADERS, 1):
            cell = ws_summary.cell(row=1, column=col_idx, value=h)
            cell.fill = NAVY_FILL
            cell.font = FONT_HEADER
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        statements = list(results["frequencies_df"]["reporting_statement"]) if len(results["frequencies_df"]) else []
        for row_idx, dom in enumerate(manifest["domains"]):
            r_num = row_idx + 2
            ws_summary.cell(row=r_num, column=1, value=dom["domain_id"]).font = FONT_BOLD
            ws_summary.cell(row=r_num, column=2, value=dom["domain_name"]).font = FONT_BODY
            ws_summary.cell(row=r_num, column=3, value=dom["documents_reporting"]).font = FONT_BODY
            ws_summary.cell(row=r_num, column=4, value=dom["total_documents"]).font = FONT_BODY

            prev_cell = ws_summary.cell(row=r_num, column=5, value=dom["prevalence_pct"])
            prev_cell.font = FONT_BOLD
            prev_cell.comment = Comment(
                _audit_comment_text(dom["domain_name"], dom["documents_reporting"], dom["total_documents"],
                                    dom["matching_turns"], dom["audit_sha256"]),
                "ATLAS Engine",
            )

            ws_summary.cell(row=r_num, column=6, value=dom["matching_turns"]).font = FONT_BODY
            ws_summary.cell(row=r_num, column=7, value=statements[row_idx]).font = FONT_BODY

            if row_idx % 2 == 1:
                for c in range(1, 8):
                    ws_summary.cell(row=r_num, column=c).fill = ZEBRA_FILL
            for c in range(1, 8):
                ws_summary.cell(row=r_num, column=c).border = BORDER_BOX

        col_widths = [14, 34, 18, 14, 18, 22, 60]
        for idx, width in enumerate(col_widths, 1):
            ws_summary.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width

        # Mixed evidence (paraphrases / observations) gets an evidence-labelled sheet so no
        # summary is presented as a participant's verbatim statement.
        mixed = has_non_verbatim_evidence(results["quotes_df"])
        ws_quotes = wb.create_sheet(title="Coded Evidence & Provenance" if mixed else "Verbatim Quotes & Provenance")
        q_headers = ["Domain ID", "Source ID", "Unit ID", "Line", "Timestamp", "Speaker", "Match Start",
                     "Match End", "Coded Entry Text (see Evidence Type)" if mixed else "Verbatim Statement",
                     "Source File SHA-256"]
        if mixed:
            q_headers += ["Evidence Type", "Question"]
        for col_idx, h in enumerate(q_headers, 1):
            cell = ws_quotes.cell(row=1, column=col_idx, value=h)
            cell.fill = NAVY_FILL
            cell.font = FONT_HEADER
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for row_idx, r in enumerate(results["quotes_df"].to_dict("records")):
            r_num = row_idx + 2
            values = [
                r["domain_id"], r["source_id"], r["unit_id"],
                int(r["line_number"]) if r["line_number"] is not None else None,
                str(r["timestamp"]), r["speaker"], int(r["match_char_start"]), int(r["match_char_end"]),
                r["text"], r["source_sha256"],
            ]
            if mixed:
                evidence = str(r.get("evidence_type") or "")
                values += [NOTES_EVIDENCE_LABELS.get(evidence, evidence), str(r.get("question_id") or "")]
            for col_idx, value in enumerate(values, 1):
                cell = ws_quotes.cell(row=r_num, column=col_idx, value=value)
                cell.font = FONT_BOLD if col_idx == 1 else FONT_BODY
                cell.border = BORDER_BOX

        wb.save(excel_path)

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------
    @staticmethod
    def verify_workbook_integrity(excel_path: str, manifest_path: str) -> Tuple[bool, List[str]]:
        """
        Recompute every domain's prevalence, audit digest and plain-language
        statement from the manifest, and check them against the manifest itself
        and against every cell of each row of the 'Empirical Frequencies' sheet
        (domain id and name, counts, prevalence, matching turns, statement, and
        the prevalence-cell audit comment). Scope: this binds the frequency sheet
        to the manifest; it does not re-verify the quote sheet or re-hash the
        source files. The manifest is first checked by validate_manifest, so
        malformed fields and impossible counts are reported, never raised.
        Returns (True, []) when consistent, else (False, reasons).
        """
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError) as exc:
            # ValueError covers JSONDecodeError, UnicodeDecodeError and integer
            # literals beyond Python's int-string conversion limit.
            return False, [f"cannot read manifest {manifest_path}: {exc}"]
        try:
            wb = openpyxl.load_workbook(excel_path)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile, InvalidFileException) as exc:
            return False, [f"cannot read workbook {excel_path}: {exc}"]
        if FREQUENCY_SHEET not in wb.sheetnames:
            return False, [f"workbook has no {FREQUENCY_SHEET!r} sheet"]
        ws = wb[FREQUENCY_SHEET]

        reasons, domains = validate_manifest(manifest)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("file_hashes"), dict) \
                or not isinstance(manifest.get("domains"), list) \
                or not all(isinstance(v, str) for v in manifest["file_hashes"].values()):
            return False, reasons
        file_hashes = manifest["file_hashes"]

        header = [ws.cell(row=1, column=c).value for c in range(1, len(FREQUENCY_HEADERS) + 1)]
        if header != FREQUENCY_HEADERS:
            reasons.append(f"header row {header} does not match {FREQUENCY_HEADERS}")
        if ws.max_column != len(FREQUENCY_HEADERS):
            reasons.append(f"sheet has {ws.max_column} columns; expected {len(FREQUENCY_HEADERS)}")
        if ws.max_row - 1 != len(domains):
            reasons.append(f"sheet has {ws.max_row - 1} data rows; manifest lists {len(domains)} domains")

        for row_idx, dom in enumerate(domains, 2):
            if dom is None:
                reasons.append(f"row {row_idx}: not checked because its manifest entry is malformed")
                continue
            domain_id = dom["domain_id"]
            docs, total, turns = dom["documents_reporting"], dom["total_documents"], dom["matching_turns"]
            manifest_prev = _to_finite_float(dom["prevalence_pct"])
            label = f"row {row_idx} ({domain_id})"

            expected_prev = _expected_prevalence(docs, total)
            if manifest_prev is None or expected_prev is None:
                reasons.append(
                    f"{label}: prevalence is not a finite number "
                    f"(manifest {dom['prevalence_pct']!r}, {docs} of {total} documents)"
                )
                continue
            if abs(manifest_prev - expected_prev) > 1e-9:
                reasons.append(f"{label}: manifest prevalence {manifest_prev} != recomputed {expected_prev}")
            expected_digest = audit_digest(domain_id, docs, total, turns, expected_prev, file_hashes)
            if dom["audit_sha256"] != expected_digest:
                reasons.append(f"{label}: manifest audit_sha256 does not match recomputed digest")

            domain_name = dom["domain_name"]
            expected_cells = {
                1: domain_id, 2: domain_name, 3: docs, 4: total, 6: turns,
                7: _reporting_statement(expected_prev, docs, total, turns, domain_name),
            }
            for col, expected in expected_cells.items():
                actual = ws.cell(row=row_idx, column=col).value
                # Exact type match: an Excel boolean (True == 1) or float (1.0 == 1)
                # must not pass an integer count, nor a number pass a text cell.
                if type(actual) is not type(expected) or actual != expected:
                    reasons.append(f"{label}: column {col} ({FREQUENCY_HEADERS[col - 1]}) is {actual!r}, expected {expected!r}")

            prev_cell = ws.cell(row=row_idx, column=5)
            cell_prev = _to_finite_float(prev_cell.value)
            if cell_prev is None or abs(cell_prev - expected_prev) > 1e-9:
                reasons.append(f"{label}: prevalence cell is {prev_cell.value!r}, expected {expected_prev}")

            expected_comment = _audit_comment_text(domain_name, docs, total, turns, expected_digest)
            if prev_cell.comment is None:
                reasons.append(f"{label}: prevalence cell has no audit comment")
            elif (prev_cell.comment.text or "").strip() != expected_comment:
                reasons.append(f"{label}: prevalence audit comment does not match the recomputed audit stamp")

        return (not reasons), reasons
