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
FREQUENCY_COLUMNS = [
    "domain_id", "domain_name", "documents_reporting", "total_documents",
    "prevalence_pct", "matching_turns", "total_mentions", "reporting_statement",
]
FREQUENCY_HEADERS = [
    "Domain ID", "Policy Domain Name", "Reporting Documents", "Total Documents", "Prevalence Rate (%)",
    "Matching Dialogue Turns", "Plain Language Empirical Statement",
]
TYPO_MATCH_COLUMNS = [
    "source_id", "unit_id", "turn_id", "line_number", "domain_id", "domain_name",
    "matched_span", "matched_root", "match_char_start", "match_char_end", "text",
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


MATCH_MODES = ("prefix", "exact")


def _parse_match_mode(raw: Any, default: str, context: str) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    mode = str(raw).strip().lower()
    if mode not in MATCH_MODES:
        raise ValueError(f"Invalid match_mode {raw!r} in {context}; expected one of {MATCH_MODES}")
    return mode


def _normalize_rule(item: Dict[str, Any], default_id: str, default_match_mode: str = "prefix") -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"Codebook rule {default_id!r} must be a mapping, got {type(item).__name__}")
    rule_id = str(_first_present(item, ("id",), default_id))
    roots_en = _term_list(item.get("roots_en")) + _term_list(item.get("roots")) + _term_list(item.get("keywords"))
    match_mode = _parse_match_mode(item.get("match_mode"), default_match_mode, f"rule {rule_id!r}")
    return {
        "id": rule_id,
        "name": str(_first_present(item, ("name", "label"), rule_id)),
        "description": str(_first_present(item, ("description", "definition"), "")),
        "roots_en": _term_list(roots_en),
        "roots_es": _term_list(item.get("roots_es")),
        "match_mode": match_mode,
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
    meta = codebook.get("meta") if isinstance(codebook.get("meta"), dict) else {}
    default_match_mode = _parse_match_mode(
        _first_present(codebook, ("match_mode",), meta.get("match_mode")),
        "prefix",
        "codebook",
    )
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

    rules = [_normalize_rule(item, default_id, default_match_mode) for item, default_id in items]
    seen = set()
    for rule in rules:
        if rule["id"] in seen:
            raise ValueError(f"Duplicate codebook rule id {rule['id']!r}")
        seen.add(rule["id"])
    return rules


def _term_pattern_str(term: str, match_mode: str = "prefix") -> str:
    prefix = r"\b" if re.match(r"\w", term[0]) else r"(?<!\w)"
    if match_mode == "exact":
        suffix = r"\b" if re.match(r"\w", term[-1]) else r"(?!\w)"
    else:
        suffix = ""
    return prefix + re.escape(term) + suffix


def _compile_terms(terms: Sequence[str], match_mode: str = "prefix") -> Optional["re.Pattern[str]"]:
    """Word-boundary-anchored stem (or exact-word) alternation over folded terms, longest first."""
    folded = sorted({fold_accents(t) for t in terms if fold_accents(t)}, key=lambda t: (-len(t), t))
    if not folded:
        return None
    if match_mode == "prefix":
        return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in folded) + r")", re.IGNORECASE)
    return re.compile("(?:" + "|".join(_term_pattern_str(t, "exact") for t in folded) + ")", re.IGNORECASE)


def _compile_term_patterns(terms: Sequence[str], match_mode: str = "prefix") -> List["re.Pattern[str]"]:
    """One word-boundary-anchored stem (or exact-word) pattern per distinct folded term, longest first."""
    folded = sorted({fold_accents(t) for t in terms if fold_accents(t)}, key=lambda t: (-len(t), t))
    if match_mode == "prefix":
        return [re.compile(r"\b" + re.escape(t), re.IGNORECASE) for t in folded]
    return [re.compile(_term_pattern_str(t, "exact"), re.IGNORECASE) for t in folded]


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


def _damerau_levenshtein_1(a: str, b: str) -> bool:
    """
    True iff the optimal string alignment (Damerau-Levenshtein) distance between
    lowercase strings a and b is strictly 1: one substitution, one adjacent
    transposition, one insertion, or one deletion. Returns False when a == b.
    """
    if a == b:
        return False
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = [i for i in range(la) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        if len(diffs) == 2:
            i, j = diffs
            return j == i + 1 and a[i] == b[j] and a[j] == b[i]
        return False
    # Ensure `short` is 1 character shorter than `long`.
    short, long_ = (a, b) if la < lb else (b, a)
    i = j = 0
    skipped = False
    while i < len(short) and j < len(long_):
        if short[i] == long_[j]:
            i += 1
            j += 1
        elif not skipped:
            skipped = True
            j += 1
        else:
            return False
    return True


def _compile_fuzzy_roots(terms: Sequence[str], min_len: int = 5) -> List[str]:
    """Single-word folded lowercase roots of length >= min_len eligible for DL=1 matching."""
    seen = set()
    out: List[str] = []
    for raw in terms:
        folded = fold_accents(str(raw or "")).strip().lower()
        if len(folded) < min_len or " " in folded or not _TOKEN.fullmatch(folded):
            continue
        if folded not in seen:
            seen.add(folded)
            out.append(folded)
    return sorted(out)


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
            match_mode = domain.get("match_mode", "prefix")
            self.compiled_rules.append({
                "id": rule_id,
                "name": domain["name"],
                "description": domain.get("description", ""),
                "match_mode": match_mode,
                "root_regex": _compile_terms(roots, match_mode),
                "root_patterns": _compile_term_patterns(roots, match_mode),
                "fuzzy_roots": _compile_fuzzy_roots(roots, min_len=5),
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

    def _match_rule_fuzzy(
        self, rule: Dict[str, Any], folded: str, token_starts: List[int]
    ) -> List[Tuple[int, int, str]]:
        """
        Bounded opt-in spelling-tolerance fallback: returns (folded_start, folded_end,
        matched_root) for whole tokens (len >= 4) at exact Damerau-Levenshtein distance 1
        from any single-word root of len >= 5, enforcing the exact same context_fences
        and exclude_fences windows as _match_rule.
        """
        fuzzy_roots = rule.get("fuzzy_roots") or []
        if not fuzzy_roots:
            return []

        candidates: List[Tuple[int, int, str]] = []
        for tok_m in _TOKEN.finditer(folded):
            tok_lower = tok_m.group(0).lower()
            if len(tok_lower) < 4:
                continue
            for root in fuzzy_roots:
                if _damerau_levenshtein_1(tok_lower, root):
                    candidates.append((tok_m.start(), tok_m.end(), root))
                    break
        if not candidates:
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

        qualifying: List[Tuple[int, int, str]] = []
        for r_start, r_end, root in candidates:
            r_tok = self._token_interval(token_starts, r_start, r_end)
            if has_fences and fence_window is not None:
                if not any(self._interval_gap(r_tok, f_tok) <= fence_window for f_tok in fence_toks):
                    continue
            if excl_window is not None and any(self._interval_gap(r_tok, x_tok) <= excl_window for x_tok in excl_toks):
                continue
            qualifying.append((r_start, r_end, root))
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
        group_by_source: bool = False,
        spelling_tolerance: bool = False,
    ) -> Dict[str, Any]:
        """
        Parse transcript and tabular files and generate verified frequency matrices.

        file_hashes is keyed by source_id: the POSIX path relative to root_dir when
        given, otherwise the canonical absolute path, so files sharing a basename in
        different folders never collide. tabular_options (text_col, id_col,
        speaker_col, allow_duplicate_ids, sheet_name, duplicate_id_policy) apply to
        .csv/.xlsx inputs. include_evidence_types and notes_unit_level are passed to
        the parser and only affect structured focus-group notes (.docx).
        group_by_source is passed to process_turns: every input file is one analytical
        unit (Group mode). spelling_tolerance enables opt-in DL=1 fallback on 5+ char
        single-word roots (default False).
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
        tabular_stats: List[Dict[str, Any]] = []
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
            if parser.last_tabular_stats is not None:
                tabular_stats.append(dict(parser.last_tabular_stats))
            all_turns.extend(turns)
            if parser.last_document_structure == "focus_group_notes":
                theme_turns.extend(themes_parser.parse_file(file_path, root_dir=root_dir))

        results = self.process_turns(
            all_turns, file_hashes, group_by_source=group_by_source,
            spelling_tolerance=spelling_tolerance,
        )
        results["document_structures"] = document_structures
        results["notes_metadata"] = dict(parser.last_document_metadata)
        results["note_taker_themes_df"] = pd.DataFrame(theme_turns)
        results["tabular_stats"] = tabular_stats
        return results

    process_transcripts = process_corpus

    def process_turns(
        self,
        turns: List[Dict[str, Any]],
        file_hashes: Dict[str, str],
        group_by_source: bool = False,
        spelling_tolerance: bool = False,
    ) -> Dict[str, Any]:
        """
        Tag pre-parsed turns (e.g. from Streamlit uploads) against the compiled rules.

        file_hashes maps each turn's source_id to the SHA-256 of its source file.
        Prevalence denominators count distinct participant unit_ids (one per
        transcript, one per tabular respondent row). With group_by_source every
        input file is one unit instead (unit_id = source_id, total_documents = number
        of files); speakers are kept, so voices can still be counted per file.
        When spelling_tolerance=True, DL=1 fallback runs only for (turn, domain) pairs
        with zero qualifying normal spans, preserving strict normal-match precedence.
        """
        file_hashes = dict(file_hashes)
        if group_by_source:
            turns = [
                {**t, "unit_id": t.get("source_id") or t.get("document_name")} for t in turns
            ]
        participant_turns = [t for t in turns if not t.get("is_facilitator", False)]
        has_respondent_id = any("respondent_id" in t for t in participant_turns)

        tagged_records = []
        quote_inventory = []
        typo_inventory: List[Dict[str, Any]] = []
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
                fuzzy_hits: List[Tuple[int, int, str]] = []
                if not spans and spelling_tolerance:
                    fuzzy_hits = self._match_rule_fuzzy(rule, folded, token_starts)
                    spans = [(s, e) for s, e, _ in fuzzy_hits]
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

                for fs, fe, froot in fuzzy_hits:
                    os_i, oe_i = folded_span_to_original(text, index_map, fs, fe)
                    typo_inventory.append({
                        "source_id": source_id,
                        "unit_id": unit_id,
                        "turn_id": turn.get("turn_id"),
                        "line_number": turn.get("line_number"),
                        "domain_id": rule["id"],
                        "domain_name": rule["name"],
                        "matched_span": text[os_i:oe_i],
                        "matched_root": froot,
                        "match_char_start": os_i,
                        "match_char_end": oe_i,
                        "text": text,
                    })

                matched_domains.append(rule["id"])
                q_row = {
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
                }
                if has_respondent_id:
                    q_row["respondent_id"] = str(turn.get("respondent_id") or "")
                quote_inventory.append(q_row)

            record = dict(turn)
            record["matched_domains"] = matched_domains
            tagged_records.append(record)

        all_unit_ids = set(file_hashes) if group_by_source else self._analytical_units(turns, file_hashes)
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

        quote_cols = [*QUOTE_COLUMNS, "respondent_id"] if has_respondent_id else QUOTE_COLUMNS
        return {
            "project_name": self.project_name,
            "total_documents": total_docs,
            "total_turns_parsed": len(turns),
            "participant_turns_analyzed": len(participant_turns),
            "file_hashes": file_hashes,
            "frequencies_df": pd.DataFrame(frequency_rows, columns=FREQUENCY_COLUMNS),
            "quotes_df": pd.DataFrame(quote_inventory, columns=quote_cols),
            "tagged_turns_df": pd.DataFrame(tagged_records),
            "spelling_tolerance": bool(spelling_tolerance),
            "typo_matches_df": pd.DataFrame(typo_inventory, columns=TYPO_MATCH_COLUMNS),
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
        manifest = {
            "project_name": results["project_name"],
            "total_documents": int(results["total_documents"]),
            "total_turns_parsed": int(results["total_turns_parsed"]),
            "participant_turns_analyzed": int(results["participant_turns_analyzed"]),
            "file_hashes": file_hashes,
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "domains": domains,
        }
        if results.get("spelling_tolerance"):
            typo_df = results.get("typo_matches_df")
            n_occ = int(len(typo_df)) if typo_df is not None else 0
            if typo_df is not None and len(typo_df):
                n_matches = len({
                    (str(r["source_id"]), str(r["unit_id"]), str(r["turn_id"]), str(r["line_number"]), str(r["domain_id"]))
                    for _, r in typo_df.iterrows()
                })
            else:
                n_matches = 0
            manifest["spelling_tolerance"] = True
            manifest["typo_rescued_matches"] = int(n_matches)
            manifest["typo_rescued_occurrences"] = int(n_occ)
        tab_stats = results.get("tabular_stats")
        if tab_stats:
            manifest["tabular_stats"] = tab_stats
        return manifest

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
        quotes_df = results["quotes_df"]
        mixed = has_non_verbatim_evidence(quotes_df)
        has_respondent_id = (
            "respondent_id" in quotes_df.columns
            and quotes_df["respondent_id"].astype(str).str.strip().ne("").any()
        )
        ws_quotes = wb.create_sheet(title="Coded Evidence & Provenance" if mixed else "Verbatim Quotes & Provenance")
        q_headers = ["Domain ID", "Source ID", "Unit ID"]
        if has_respondent_id:
            q_headers.append("Respondent ID")
        q_headers += ["Line", "Timestamp", "Speaker", "Match Start",
                      "Match End", "Coded Entry Text (see Evidence Type)" if mixed else "Verbatim Statement",
                      "Source File SHA-256"]
        if mixed:
            q_headers += ["Evidence Type", "Question"]
        for col_idx, h in enumerate(q_headers, 1):
            cell = ws_quotes.cell(row=1, column=col_idx, value=h)
            cell.fill = NAVY_FILL
            cell.font = FONT_HEADER
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for row_idx, r in enumerate(quotes_df.to_dict("records")):
            r_num = row_idx + 2
            values = [r["domain_id"], r["source_id"], r["unit_id"]]
            if has_respondent_id:
                values.append(str(r.get("respondent_id") or ""))
            values += [
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


# ----------------------------------------------------------------------
# Analyst codebook helpers (stacking, appending discovered topics,
# false-alarm spot-check audit, and safe rule tightening)
# ----------------------------------------------------------------------
FALSE_ALARM_COLUMNS = [
    "risk_level", "domain_id", "domain_name", "matched_span", "full_word",
    "extension_words", "spelling_words", "flag_codes", "flag_reason", "suggested_fix",
    "speaker", "source_id", "line_number", "evidence_type",
    "match_char_start", "match_char_end", "text",
]
FALSE_ALARM_SUMMARY_COLUMNS = [
    "Risk", "Domain", "Matched Span", "Full Word", "Flagged Matches", "Why Flagged", "Suggested Fix",
]
_AUDIT_TOKEN = re.compile(r"[A-Za-z0-9_]+(?:['\u2019][A-Za-z0-9_]+)?")
_SIMPLE_LONG_INFLECTIONS = frozenset({"s", "es", "ed", "d", "ing", "er", "ers", "ly", "ies", "y"})
_NEGATION_CUES = frozenset({
    "no", "not", "never", "neither", "nor", "none", "nothing", "nowhere", "without",
    "hardly", "barely", "cannot", "cant", "can't", "dont", "don't", "didnt", "didn't",
    "doesnt", "doesn't", "isnt", "isn't", "arent", "aren't", "wasnt", "wasn't",
    "werent", "weren't", "wont", "won't", "wouldnt", "wouldn't", "couldnt", "couldn't",
    "havent", "haven't", "hasnt", "hasn't", "hadnt", "hadn't",
    "ningun", "ninguna", "nunca", "tampoco", "sin",
})


def _slugify_id(text: str) -> str:
    folded = fold_accents(str(text or "")).lower()
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")


def _codebook_project_name(codebook: Dict[str, Any], default: str = "Qualitative Policy Study") -> str:
    meta = codebook.get("meta") if isinstance(codebook.get("meta"), dict) else {}
    return str(
        codebook.get("project")
        or codebook.get("program_name")
        or meta.get("project")
        or default
    )


def _serialize_normalized_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    rule_id = str(rule["id"])
    ctx_window = _parse_window(rule.get("context_window"), "context_window", rule_id)
    excl_window = _parse_window(rule.get("exclude_window"), "exclude_window", rule_id)
    out: Dict[str, Any] = {
        "id": rule_id,
        "name": str(rule["name"]),
        "description": str(rule.get("description", "")),
        "match_mode": _parse_match_mode(rule.get("match_mode"), "prefix", f"rule {rule_id!r}"),
        "roots_en": list(rule.get("roots_en", [])),
        "roots_es": list(rule.get("roots_es", [])),
        "context_fences": list(rule.get("context_fences", [])),
        "exclude_fences": list(rule.get("exclude_fences", [])),
    }
    if ctx_window is not None:
        out["context_window"] = ctx_window
    if excl_window is not None:
        out["exclude_window"] = excl_window
    return out


def merge_codebook_dicts(
    codebooks: Sequence[Tuple[str, Dict[str, Any]]],
    project_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Combine one or more ATLAS codebooks (in any supported YAML schema) into a
    single unified 'domains' codebook dict that compiles in AtlasEngine.

    Preserves each rule's own match_mode, roots, fences, and windows, and
    deterministically disambiguates colliding domain IDs or display names.
    """
    entries = list(codebooks or [])
    if not entries:
        raise ValueError("At least one codebook is required to merge.")

    merged_domains: List[Dict[str, Any]] = []
    seen_ids: set = set()
    seen_names: set = set()
    labels: List[str] = []

    for idx, entry in enumerate(entries, 1):
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError(f"Codebook entry {idx} must be a (label, dict) pair.")
        label, cb_dict = str(entry[0]), entry[1]
        if not isinstance(cb_dict, dict):
            raise ValueError(f"Codebook {label!r} must be a YAML mapping, got {type(cb_dict).__name__}")
        labels.append(label)
        slug = _slugify_id(Path(label).stem) or f"cb_{idx}"

        for rule in normalize_codebook_rules(cb_dict):
            ser = _serialize_normalized_rule(rule)
            raw_id = ser["id"]
            if raw_id in seen_ids:
                candidate = f"{slug}__{raw_id}"
                suffix = 2
                while candidate in seen_ids:
                    candidate = f"{slug}__{raw_id}_{suffix}"
                    suffix += 1
                ser["id"] = candidate
            seen_ids.add(ser["id"])

            raw_name = ser["name"]
            if raw_name.strip().lower() in seen_names:
                candidate_name = f"{raw_name} ({label})"
                suffix = 2
                while candidate_name.strip().lower() in seen_names:
                    candidate_name = f"{raw_name} ({label} #{suffix})"
                    suffix += 1
                ser["name"] = candidate_name
            seen_names.add(ser["name"].strip().lower())
            merged_domains.append(ser)

    if project_name and str(project_name).strip():
        resolved_project = str(project_name).strip()
    elif len(entries) == 1:
        resolved_project = _codebook_project_name(entries[0][1])
    else:
        resolved_project = f"Combined Codebook ({len(entries)} packs, {len(merged_domains)} domains)"

    return {
        "project": resolved_project,
        "version": "1.0",
        "domains": merged_domains,
    }


def append_topic_to_codebook(
    codebook_dict: Dict[str, Any],
    topic: Dict[str, Any],
    *,
    domain_name: Optional[str] = None,
    domain_id: Optional[str] = None,
    match_mode: str = "exact",
    terms: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Append one discovered topic as a new domain on top of an existing codebook,
    preserving all existing domains and defaulting the added domain to exact
    whole-word matching so short discovered terms do not trigger prefix collisions.
    """
    if not isinstance(codebook_dict, dict):
        raise ValueError(f"codebook_dict must be a mapping, got {type(codebook_dict).__name__}")
    if not isinstance(topic, dict):
        raise ValueError(f"topic must be a mapping, got {type(topic).__name__}")
    resolved_mode = _parse_match_mode(match_mode, "exact", "append_topic_to_codebook")

    raw_terms = terms if terms is not None else topic.get("top_terms", [])
    cleaned_terms: List[str] = []
    seen_terms: set = set()
    for term in _term_list(raw_terms):
        key = fold_accents(term).lower()
        if key and key not in seen_terms:
            seen_terms.add(key)
            cleaned_terms.append(term)
    if not cleaned_terms:
        raise ValueError("Cannot add a discovered theme with no non-empty terms.")

    existing = [_serialize_normalized_rule(r) for r in normalize_codebook_rules(codebook_dict)]
    seen_ids = {r["id"] for r in existing}
    seen_names = {r["name"].strip().lower() for r in existing}

    topic_label = str(topic.get("label") or "").strip()
    topic_num = topic.get("topic_id", len(existing) + 1)
    base_name = str(domain_name or "").strip() or f"Discovered: {topic_label or f'Topic {topic_num}'}"
    resolved_name = base_name
    name_idx = 2
    while resolved_name.strip().lower() in seen_names:
        resolved_name = f"{base_name} ({name_idx})"
        name_idx += 1

    if domain_id is not None and str(domain_id).strip():
        base_id = _slugify_id(domain_id)
        if not base_id:
            raise ValueError(f"domain_id {domain_id!r} must contain at least one ASCII letter or digit.")
    else:
        slug = _slugify_id(resolved_name)
        base_id = f"discovered_{slug}" if slug else f"discovered_topic_{topic_num}"
    resolved_id = base_id
    id_idx = 2
    while resolved_id in seen_ids:
        resolved_id = f"{base_id}_{id_idx}"
        id_idx += 1

    existing.append({
        "id": resolved_id,
        "name": resolved_name,
        "description": (
            f"Added from offline topic discovery ({resolved_mode} matching); "
            "review and refine fences as needed."
        ),
        "match_mode": resolved_mode,
        "roots_en": cleaned_terms,
        "roots_es": [],
        "context_fences": [],
        "exclude_fences": [],
    })

    return {
        "project": _codebook_project_name(codebook_dict),
        "version": str(codebook_dict.get("version") or "1.0"),
        "domains": existing,
    }


def tighten_codebook_domain(
    codebook_dict: Dict[str, Any],
    domain_id: str,
    *,
    add_exclude_terms: Sequence[str] = (),
    set_exact_mode: bool = False,
) -> Dict[str, Any]:
    """
    Tighten a single domain in a codebook by adding exclusion terms and/or
    switching it to exact whole-word matching. Preserves existing nonzero
    exclude_window settings; defaults to exclude_window=0 only when adding the
    domain's first exclusion terms so word-level exclusions do not suppress real
    mentions elsewhere in the same turn.
    """
    if not isinstance(codebook_dict, dict):
        raise ValueError(f"codebook_dict must be a mapping, got {type(codebook_dict).__name__}")
    extra_excludes = _term_list(add_exclude_terms)
    if not extra_excludes and not set_exact_mode:
        raise ValueError("Provide at least one exclusion term or set_exact_mode=True.")

    rules = [_serialize_normalized_rule(r) for r in normalize_codebook_rules(codebook_dict)]
    target = next((r for r in rules if r["id"] == str(domain_id)), None)
    if target is None:
        raise ValueError(f"Domain id {domain_id!r} not found in codebook.")

    if set_exact_mode:
        target["match_mode"] = "exact"
    if extra_excludes:
        had_excludes = bool(target["exclude_fences"])
        existing_lower = {fold_accents(t).lower() for t in target["exclude_fences"]}
        for term in extra_excludes:
            key = fold_accents(term).lower()
            if key and key not in existing_lower:
                existing_lower.add(key)
                target["exclude_fences"].append(term)
        if not had_excludes and "exclude_window" not in target:
            target["exclude_window"] = 0

    return {
        "project": _codebook_project_name(codebook_dict),
        "version": str(codebook_dict.get("version") or "1.0"),
        "domains": rules,
    }


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or unicodedata.category(ch) == "Mn"


def _is_benign_inflection(folded_span: str, tail: str, short_root_max_len: int) -> bool:
    if not tail:
        return True
    if len(folded_span) <= 3:
        if tail == "s":
            return True
        if tail == "es" and folded_span.endswith(("s", "x", "z", "ch", "sh")):
            return True
        return False
    if len(folded_span) <= short_root_max_len:
        if tail in {"s", "ed", "ing"}:
            return True
        if tail == "es" and folded_span.endswith(("s", "x", "z", "ch", "sh")):
            return True
        return False
    return tail in _SIMPLE_LONG_INFLECTIONS


def _compile_audit_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    rule_id = str(rule.get("id", ""))
    match_mode = _parse_match_mode(rule.get("match_mode"), "prefix", f"rule {rule_id!r}")
    if "root_patterns" in rule:
        root_patterns = list(rule.get("root_patterns") or [])
        fence_patterns = list(rule.get("fence_patterns") or [])
        exclude_patterns = list(rule.get("exclude_patterns") or [])
    else:
        roots = list(rule.get("roots_en") or []) + list(rule.get("roots_es") or [])
        root_patterns = _compile_term_patterns(roots, match_mode)
        fence_patterns = _compile_term_patterns(rule.get("context_fences") or [])
        exclude_patterns = _compile_term_patterns(rule.get("exclude_fences") or [])
    return {
        "id": rule_id,
        "match_mode": match_mode,
        "root_patterns": root_patterns,
        "fence_patterns": fence_patterns,
        "context_window": _parse_window(rule.get("context_window"), "context_window", rule_id),
        "exclude_patterns": exclude_patterns,
        "exclude_window": _parse_window(rule.get("exclude_window"), "exclude_window", rule_id),
        "has_context": bool(fence_patterns or rule.get("context_fences") or rule.get("fence_regex")),
        "has_exclude": bool(exclude_patterns or rule.get("exclude_fences") or rule.get("exclude_regex")),
    }


def _qualifying_non_overlapping_spans(
    compiled_rule: Dict[str, Any],
    text: str,
    folded_text: str,
    idx_map: Sequence[int],
) -> List[Tuple[int, int]]:
    if not compiled_rule["root_patterns"]:
        return []
    roots = _find_overlapping_spans(compiled_rule["root_patterns"], folded_text)
    if not roots:
        return []
    has_fences, fence_window = bool(compiled_rule["fence_patterns"]), compiled_rule["context_window"]
    fences = _find_overlapping_spans(compiled_rule["fence_patterns"], folded_text)
    if has_fences and not fences:
        return []
    excl_window = compiled_rule["exclude_window"]
    excludes = _find_overlapping_spans(compiled_rule["exclude_patterns"], folded_text)
    if excludes and excl_window is None:
        return []

    token_starts = [m.start() for m in _TOKEN.finditer(folded_text)]
    fence_toks = [AtlasEngine._token_interval(token_starts, s, e) for s, e in fences]
    excl_toks = [AtlasEngine._token_interval(token_starts, s, e) for s, e in excludes]

    qualifying: List[Tuple[int, int]] = []
    for r_start, r_end in roots:
        r_tok = AtlasEngine._token_interval(token_starts, r_start, r_end)
        if has_fences and fence_window is not None:
            if not any(AtlasEngine._interval_gap(r_tok, f_tok) <= fence_window for f_tok in fence_toks):
                continue
        if excl_window is not None and any(AtlasEngine._interval_gap(r_tok, x_tok) <= excl_window for x_tok in excl_toks):
            continue
        qualifying.append((r_start, r_end))

    non_overlapping: List[Tuple[int, int]] = []
    covered_to = -1
    for f_s, f_e in qualifying:
        if f_s >= covered_to:
            non_overlapping.append(folded_span_to_original(text, idx_map, f_s, f_e))
            covered_to = f_e
    return non_overlapping


def audit_false_alarm_risks(
    quotes_df: pd.DataFrame,
    rules: Sequence[Dict[str, Any]],
    *,
    short_root_max_len: int = 4,
    negation_window: int = 5,
    typo_matches_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Inspect matched quotes against active codebook rules (1 audit row per flagged
    match row, strictly preserving len(audit_df) <= len(quotes_df)) and flag
    common false-alarm patterns:
      1. prefix_extension (High): any qualifying span in the turn is only the prefix
         of a different longer word (e.g. 'car' inside 'card' or 'career'), excluding
         simple plurals and routine inflections.
      2. spelling_tolerance (High): the (entry, domain) match was rescued only via
         bounded Damerau-Levenshtein=1 spelling tolerance (surfaces all unique typo
         words for that entry/domain in `spelling_words` for one-click review/exclusion).
      3. negation_nearby (Medium): a negation cue ('not', 'never', 'didn't', 'no',
         'without', ...) appears within +/- negation_window tokens of a qualifying span.
      4. short_unfenced_root (Medium): a single-word <=4-character stem matched
         under prefix mode in a rule with neither context_fences nor exclude_fences.
    """
    if quotes_df is None or len(quotes_df) == 0:
        return pd.DataFrame(columns=FALSE_ALARM_COLUMNS)

    compiled_by_id = {
        str(r["id"]): _compile_audit_rule(r)
        for r in (rules or [])
        if isinstance(r, dict) and "id" in r
    }
    typo_by_match: Dict[Tuple[str, str, str, str, str], List[Tuple[int, int, str, str]]] = {}
    if typo_matches_df is not None and len(typo_matches_df) > 0:
        for _, tr in typo_matches_df.iterrows():
            key = (
                str(tr.get("source_id", "")),
                str(tr.get("unit_id", "")),
                str(tr.get("turn_id", "")),
                str(tr.get("line_number", "")),
                str(tr.get("domain_id", "")),
            )
            try:
                ts = int(tr.get("match_char_start", 0))
                te = int(tr.get("match_char_end", ts))
            except (TypeError, ValueError):
                ts, te = 0, 0
            typo_by_match.setdefault(key, []).append(
                (ts, te, str(tr.get("matched_span", "")), str(tr.get("matched_root", "")))
            )

    flagged_rows: List[Dict[str, Any]] = []

    for _, row in quotes_df.iterrows():
        text = str(row.get("text", ""))
        domain_id = str(row.get("domain_id", ""))
        domain_name = str(row.get("domain_name", domain_id))
        try:
            row_start = max(0, min(len(text), int(row.get("match_char_start", 0))))
            row_end = max(row_start, min(len(text), int(row.get("match_char_end", row_start))))
        except (TypeError, ValueError):
            row_start, row_end = 0, 0

        match_key = (
            str(row.get("source_id", "")),
            str(row.get("unit_id", "")),
            str(row.get("turn_id", "")),
            str(row.get("line_number", "")),
            domain_id,
        )
        typo_entries = typo_by_match.get(match_key, [])

        folded_text, idx_map = fold_accents_with_map(text)
        compiled_rule = compiled_by_id.get(domain_id)
        spans = (
            _qualifying_non_overlapping_spans(compiled_rule, text, folded_text, idx_map)
            if compiled_rule is not None and not typo_entries
            else []
        )
        if not spans:
            spans = [(s, e) for s, e, _, _ in typo_entries] if typo_entries else [(row_start, row_end)]

        ext_entries: List[Tuple[int, int, str, str]] = []
        ext_words_ordered: List[str] = []
        ext_words_seen: set = set()
        spelling_words_ordered: List[str] = []
        spelling_words_seen: set = set()
        spelling_pairs: List[str] = []
        short_span_entry: Optional[Tuple[int, int, str, str]] = None
        nearest_neg: Optional[Tuple[int, str, int, int, str, str]] = None

        for _, _, t_span, t_root in typo_entries:
            w_key = t_span.strip().lower()
            if w_key and w_key not in spelling_words_seen:
                spelling_words_seen.add(w_key)
                spelling_words_ordered.append(t_span.strip())
                spelling_pairs.append(f"'{t_span.strip()}' -> '{t_root}'")

        toks = list(_AUDIT_TOKEN.finditer(folded_text))
        rule_mode = compiled_rule["match_mode"] if compiled_rule else "prefix"
        has_context = compiled_rule["has_context"] if compiled_rule else False
        has_exclude = compiled_rule["has_exclude"] if compiled_rule else False

        for s, e in spans:
            matched_span = text[s:e] if e > s else str(row.get("match_text", ""))
            w_start, w_end = s, e
            while w_start > 0 and _is_word_char(text[w_start - 1]):
                w_start -= 1
            while w_end < len(text) and _is_word_char(text[w_end]):
                w_end += 1
            full_word = text[w_start:w_end] if w_end > w_start else matched_span
            folded_span = fold_accents(matched_span).lower()
            tail = fold_accents(text[e:w_end]).lower() if w_end > e else ""
            head_ext = w_start < s

            if not typo_entries:
                if (w_end > e and not _is_benign_inflection(folded_span, tail, short_root_max_len)) or head_ext:
                    ext_entries.append((s, e, matched_span, full_word))
                    w_key = full_word.strip().lower()
                    if w_key and w_key not in ext_words_seen:
                        ext_words_seen.add(w_key)
                        ext_words_ordered.append(full_word.strip())

                if (
                    short_span_entry is None
                    and rule_mode == "prefix"
                    and not has_context
                    and not has_exclude
                    and 0 < len(folded_span) <= short_root_max_len
                    and " " not in folded_span
                ):
                    short_span_entry = (s, e, matched_span, full_word)

            if toks:
                f_start = bisect.bisect_left(idx_map, s)
                f_end = bisect.bisect_left(idx_map, e)
                overlap = [
                    i for i, m in enumerate(toks)
                    if m.end() > f_start and m.start() < max(f_end, f_start + 1)
                ]
                if overlap:
                    first_t, last_t = overlap[0], overlap[-1]
                    lo = max(0, first_t - negation_window)
                    hi = min(len(toks), last_t + 1 + negation_window)
                    for i in range(lo, hi):
                        if first_t <= i <= last_t:
                            continue
                        if toks[i].group(0).replace("\u2019", "'").lower() in _NEGATION_CUES:
                            dist = min(abs(i - first_t), abs(i - last_t))
                            if nearest_neg is None or dist < nearest_neg[0]:
                                nearest_neg = (dist, toks[i].group(0), s, e, matched_span, full_word)

        codes: List[str] = []
        reasons: List[str] = []
        fixes: List[str] = []

        if typo_entries:
            codes.append("spelling_tolerance")
            reasons.append(f"Matched via spelling tolerance ({', '.join(spelling_pairs)})")
            excl_hint = ", ".join(f"'{w.lower()}'" for w in spelling_words_ordered)
            fixes.append(f"Confirm typo in context; exclude {excl_hint} below if this is not a real match")
        if ext_entries:
            codes.append("prefix_extension")
            quoted_words = ", ".join(f"'{w}'" for w in ext_words_ordered)
            reasons.append(f"Keyword '{ext_entries[0][2]}' matched inside longer word {quoted_words}")
            excl_hint = ", ".join(f"'{w.lower()}'" for w in ext_words_ordered)
            excl_win = compiled_rule["exclude_window"] if compiled_rule else None
            if (not has_exclude and excl_win is None) or excl_win == 0:
                fixes.append(
                    f"Exclude {excl_hint} below, or switch this theme to exact whole-word matching"
                )
            elif excl_win is not None:
                fixes.append(
                    f"Switch to exact whole-word matching, or exclude {excl_hint} below "
                    f"(keeps existing {excl_win}-word exclusion window)"
                )
            else:
                fixes.append(
                    f"Switch to exact whole-word matching, or exclude {excl_hint} below "
                    "(keeps existing entry-level exclusion window)"
                )
        if nearest_neg is not None:
            codes.append("negation_nearby")
            reasons.append(f"Negation word '{nearest_neg[1]}' appeared nearby")
            fixes.append("Read in context to confirm this still belongs in the theme")
        if short_span_entry is not None:
            codes.append("short_unfenced_root")
            reasons.append(f"Short keyword ('{short_span_entry[2]}') matched in a theme without exclusion words")
            if "prefix_extension" not in codes:
                fixes.append("Review in context or switch this theme to exact whole-word matching")

        if not codes:
            continue

        if typo_entries:
            focus_s, focus_e, focus_span, _ = typo_entries[0]
            focus_word = focus_span
        elif ext_entries:
            focus_s, focus_e, focus_span, focus_word = ext_entries[0]
        elif nearest_neg is not None:
            _, _, focus_s, focus_e, focus_span, focus_word = nearest_neg
        else:
            focus_s, focus_e, focus_span, focus_word = short_span_entry

        risk_level = "High" if ("prefix_extension" in codes or "spelling_tolerance" in codes) else "Medium"
        flagged_rows.append({
            "risk_level": risk_level,
            "domain_id": domain_id,
            "domain_name": domain_name,
            "matched_span": focus_span,
            "full_word": focus_word,
            "extension_words": ", ".join(w.lower() for w in ext_words_ordered),
            "spelling_words": ", ".join(w.lower() for w in spelling_words_ordered),
            "flag_codes": ",".join(codes),
            "flag_reason": "; ".join(reasons),
            "suggested_fix": "; ".join(fixes),
            "speaker": str(row.get("speaker", "")),
            "source_id": str(row.get("source_id", "")),
            "line_number": row.get("line_number", ""),
            "evidence_type": str(row.get("evidence_type", "")),
            "match_char_start": focus_s,
            "match_char_end": focus_e,
            "text": text,
        })

    if not flagged_rows:
        return pd.DataFrame(columns=FALSE_ALARM_COLUMNS)

    df = pd.DataFrame(flagged_rows, columns=FALSE_ALARM_COLUMNS)
    df["_risk_ord"] = df["risk_level"].map({"High": 0, "Medium": 1}).fillna(2)
    df = df.sort_values(
        ["_risk_ord", "domain_name", "source_id", "line_number", "match_char_start"],
        kind="mergesort",
    ).drop(columns=["_risk_ord"]).reset_index(drop=True)
    return df


def summarize_false_alarm_risks(audit_df: pd.DataFrame) -> pd.DataFrame:
    """Group individual false-alarm flags by pattern for fast analyst review."""
    if audit_df is None or len(audit_df) == 0:
        return pd.DataFrame(columns=FALSE_ALARM_SUMMARY_COLUMNS)

    grouped = (
        audit_df.groupby(
            ["risk_level", "domain_name", "matched_span", "full_word", "flag_reason", "suggested_fix"],
            dropna=False,
            as_index=False,
        )
        .size()
        .rename(columns={
            "risk_level": "Risk",
            "domain_name": "Domain",
            "matched_span": "Matched Span",
            "full_word": "Full Word",
            "size": "Flagged Matches",
            "flag_reason": "Why Flagged",
            "suggested_fix": "Suggested Fix",
        })
    )
    grouped["_risk_ord"] = grouped["Risk"].map({"High": 0, "Medium": 1}).fillna(2)
    grouped = grouped.sort_values(
        ["_risk_ord", "Flagged Matches", "Domain", "Full Word"],
        ascending=[True, False, True, True],
        kind="mergesort",
    ).drop(columns=["_risk_ord"]).reset_index(drop=True)
    return grouped[FALSE_ALARM_SUMMARY_COLUMNS]
