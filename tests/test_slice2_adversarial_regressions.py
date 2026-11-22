"""Slice 2 repair round 1: regressions for the two Codex [P2] review findings.

1. Overlapping root, context-fence and exclusion-fence occurrences must all be
   enumerated before window evaluation (non-overlapping finditer hid them).
2. verify_workbook_integrity must reject non-finite or unconvertible prevalence
   values in the manifest and in the workbook, returning (False, reasons) and
   never raising OverflowError.

Slice 2 repair round 2 (Codex r1 recheck, two further [P2] findings):

3. Counts above the exact-integer ceiling of an IEEE-754 double / Excel cell
   ((1 << 53) - 1) must be rejected by validate_manifest and
   verify_workbook_integrity even when manifest and workbook agree.
4. A workbook count cell holding an Excel boolean (True == 1, False == 0) or a
   float (1.0 == 1) must not pass the integer comparison.

Every input built here is a SOFTWARE_TEST fixture that demonstrates software
mechanics only; none of its content is an empirical finding. Scratch inputs are
written under tempfile's directory (honours TMPDIR).

Run: .venv/bin/python -m unittest tests/test_slice2_adversarial_regressions.py -v
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import openpyxl
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from atlas_engine import (  # noqa: E402
    AtlasEngine,
    _audit_comment_text,
    _expected_prevalence,
    _reporting_statement,
    audit_digest,
    validate_manifest,
)

FAKE_SHA = "0" * 64
SOURCE_ID = "software_test_overlap.txt"
SENTINEL = 987654.321


class ScratchMixin:
    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory(prefix="atlas_s2r1_")
        self.scratch = Path(self._scratch.name)

    def tearDown(self):
        self._scratch.cleanup()

    def write_codebook(self, rule):
        path = self.scratch / "software_test_codebook.yaml"
        payload = {"project": "SOFTWARE_TEST Overlap", "domains": [dict({"id": "OVL", "name": "Overlap"}, **rule)]}
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
        return str(path)


# ----------------------------------------------------------------------
# Finding 1: overlapping occurrences before fence evaluation
# ----------------------------------------------------------------------
class OverlappingMatchTests(ScratchMixin, unittest.TestCase):
    def run_rule(self, rule, text):
        engine = AtlasEngine(self.write_codebook(rule))
        turns = [{"text": text, "source_id": SOURCE_ID, "unit_id": SOURCE_ID, "speaker": "Respondent 1",
                  "is_facilitator": False}]
        results = engine.process_turns(turns, {SOURCE_ID: FAKE_SHA})
        quotes = results["quotes_df"]
        freq = results["frequencies_df"].set_index("domain_id").loc["OVL"]
        return quotes, freq

    def assert_match(self, rule, text, expected_text):
        quotes, freq = self.run_rule(rule, text)
        self.assertEqual(len(quotes), 1, f"expected one matching turn for {text!r}")
        q = quotes.iloc[0]
        start, end = int(q["match_char_start"]), int(q["match_char_end"])
        self.assertEqual(text[start:end], expected_text)
        self.assertEqual(q["match_text"], expected_text)
        self.assertEqual(int(freq["matching_turns"]), 1)
        return start, end

    def assert_no_match(self, rule, text):
        quotes, freq = self.run_rule(rule, text)
        self.assertEqual(len(quotes), 0, f"expected no match for {text!r}, got {list(quotes.get('match_text', []))}")
        self.assertEqual(int(freq["matching_turns"]), 0)

    def test_overlapping_root_survives_exclusion_of_its_neighbour(self):
        rule = {"roots_en": ["alpha beta", "beta gamma"], "exclude_fences": ["not"], "exclude_window": 1}
        span = self.assert_match(rule, "not alpha beta gamma", "beta gamma")
        self.assertEqual(span, (10, 20))

    def test_overlapping_root_satisfies_context_fence(self):
        rule = {"roots_en": ["alpha beta", "beta gamma"], "context_fences": ["delta"], "context_window": 1}
        span = self.assert_match(rule, "alpha beta gamma delta", "beta gamma")
        self.assertEqual(span, (6, 16))

    def test_root_order_in_codebook_does_not_matter(self):
        rule = {"roots_en": ["beta gamma", "alpha beta"], "exclude_fences": ["not"], "exclude_window": 1}
        self.assertEqual(self.assert_match(rule, "not alpha beta gamma", "beta gamma"), (10, 20))

    def test_overlapping_context_fence_is_found_false_negative(self):
        rule = {"roots_en": ["zeta"], "context_fences": ["red blue", "blue green"], "context_window": 1}
        self.assertEqual(self.assert_match(rule, "red blue green zeta", "zeta"), (15, 19))

    def test_overlapping_context_fence_outside_window_still_rejects(self):
        rule = {"roots_en": ["zeta"], "context_fences": ["red blue", "blue green"], "context_window": 1}
        self.assert_no_match(rule, "red blue green omega zeta")

    def test_overlapping_exclusion_fence_is_found_false_positive(self):
        rule = {"roots_en": ["zeta"], "exclude_fences": ["red blue", "blue green"], "exclude_window": 1}
        self.assert_no_match(rule, "red blue green zeta")

    def test_overlapping_exclusion_fence_outside_window_still_matches(self):
        rule = {"roots_en": ["zeta"], "exclude_fences": ["red blue", "blue green"], "exclude_window": 1}
        self.assert_match(rule, "red blue green omega zeta", "zeta")

    def test_same_start_prefers_longest_root(self):
        rule = {"roots_en": ["alpha", "alpha beta"]}
        self.assertEqual(self.assert_match(rule, "the alpha beta case", "alpha beta"), (4, 14))

    def test_nested_and_overlapping_roots_do_not_inflate_mentions(self):
        rule = {"roots_en": ["alpha", "alpha beta", "beta gamma"]}
        _, freq = self.run_rule(rule, "alpha beta gamma")
        self.assertEqual(int(freq["total_mentions"]), 1)
        _, freq = self.run_rule(rule, "alpha beta and later alpha")
        self.assertEqual(int(freq["total_mentions"]), 2)

    def test_excluded_overlap_counts_the_surviving_root_once(self):
        rule = {"roots_en": ["alpha beta", "beta gamma"], "exclude_fences": ["not"], "exclude_window": 1}
        _, freq = self.run_rule(rule, "not alpha beta gamma")
        self.assertEqual(int(freq["total_mentions"]), 1)

    def test_whole_turn_exclusion_with_overlapping_fences(self):
        rule = {"roots_en": ["zeta"], "exclude_fences": ["red blue", "blue green"]}
        self.assert_no_match(rule, "zeta then far away blue green")


# ----------------------------------------------------------------------
# Finding 2: non-finite / overflowing prevalence in integrity verification
# ----------------------------------------------------------------------
class IntegrityFixtureMixin(ScratchMixin):
    def setUp(self):
        super().setUp()
        codebook = self.write_codebook({"roots_en": ["childcare"]})
        corpus = self.scratch / "corpus"
        corpus.mkdir()
        inputs = []
        for name, text in (("a.txt", "Respondent A: Childcare costs too much.\n"),
                           ("b.txt", "Respondent B: The bus was late.\n"),
                           ("c.txt", "Respondent C: No childcare slots nearby.\n")):
            path = corpus / name
            path.write_text(text, encoding="utf-8")
            inputs.append(str(path))
        engine = AtlasEngine(codebook)
        out = self.scratch / "export"
        engine.export_results(engine.process_corpus(inputs, root_dir=str(corpus)), str(out))
        self.xlsx = str(out / "actuarial_parameter_matrix.xlsx")
        self.manifest_path = str(out / "provenance_manifest.json")
        with open(self.manifest_path, encoding="utf-8") as fh:
            self.manifest = json.load(fh)

    def assert_rejected(self, ok_reasons):
        ok, reasons = ok_reasons
        self.assertIs(ok, False)
        self.assertIsInstance(reasons, list)
        self.assertGreaterEqual(len(reasons), 1)
        self.assertTrue(all(isinstance(r, str) and r for r in reasons))
        return reasons

    def verify(self, xlsx=None, manifest_path=None):
        return AtlasEngine.verify_workbook_integrity(xlsx or self.xlsx, manifest_path or self.manifest_path)

    def tampered_workbook(self, value):
        path = str(self.scratch / "tampered.xlsx")
        wb = openpyxl.load_workbook(self.xlsx)
        huge = isinstance(value, int) and not isinstance(value, bool) and abs(value) > 10**300
        wb["Empirical Frequencies"].cell(row=2, column=5).value = SENTINEL if huge else value
        wb.save(path)
        if huge:
            # openpyxl cannot serialise an int beyond float range, but a workbook
            # edited elsewhere can hold one; rewrite the sheet XML directly.
            self.rewrite_cell_xml(path, f"<v>{SENTINEL}</v>", f"<v>{value}</v>")
            cell_value = openpyxl.load_workbook(path)["Empirical Frequencies"].cell(row=2, column=5).value
            self.assertEqual(cell_value, value, "fixture did not store the huge integer")
        return path

    @staticmethod
    def rewrite_cell_xml(path, old, new):
        with zipfile.ZipFile(path) as zin:
            entries = [(info, zin.read(info.filename)) for info in zin.infolist()]
        replaced = 0
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
            for info, data in entries:
                if info.filename.startswith("xl/worksheets/") and old.encode() in data:
                    replaced += data.count(old.encode())
                    data = data.replace(old.encode(), new.encode())
                zout.writestr(info, data)
        if replaced != 1:
            raise AssertionError(f"expected one sentinel cell, replaced {replaced}")

    def tampered_manifest(self, mutate):
        manifest = json.loads(json.dumps(self.manifest))
        mutate(manifest)
        path = str(self.scratch / "tampered_manifest.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        return path


class IntegrityFiniteValueTests(IntegrityFixtureMixin, unittest.TestCase):
    def test_untouched_export_still_verifies(self):
        self.assertEqual(self.verify(), (True, []))

    def test_rejects_non_finite_or_unconvertible_prevalence_cells(self):
        for value in ("NaN", "nan", "Infinity", "inf", "-inf", "-Infinity", True, 10**400, float("nan")):
            with self.subTest(cell=repr(value)[:20]):
                reasons = self.assert_rejected(self.verify(xlsx=self.tampered_workbook(value)))
                self.assertTrue(any("prevalence cell" in r for r in reasons), reasons)

    def test_rejects_non_finite_or_overflowing_manifest_prevalence(self):
        for value in (float("nan"), float("inf"), float("-inf"), 10**400, -10**400, True, "NaN"):
            with self.subTest(prevalence=repr(value)[:20]):
                def mutate(m, value=value):
                    m["domains"][0]["prevalence_pct"] = value
                reasons = self.assert_rejected(self.verify(manifest_path=self.tampered_manifest(mutate)))
                self.assertTrue(any("prevalence" in r for r in reasons), reasons)

    def test_json_nan_and_infinity_literals_in_manifest(self):
        text = Path(self.manifest_path).read_text(encoding="utf-8")
        prev = self.manifest["domains"][0]["prevalence_pct"]
        needle = f'"prevalence_pct": {json.dumps(prev)}'
        self.assertIn(needle, text)
        for literal in ("NaN", "Infinity", "-Infinity", "1" + "0" * 400):
            with self.subTest(literal=literal[:12]):
                path = self.scratch / "literal_manifest.json"
                path.write_text(text.replace(needle, f'"prevalence_pct": {literal}', 1), encoding="utf-8")
                self.assert_rejected(self.verify(manifest_path=str(path)))

    def test_validate_manifest_flags_non_finite_prevalence(self):
        for value in (float("nan"), float("inf"), 10**400):
            with self.subTest(prevalence=repr(value)[:20]):
                manifest = json.loads(json.dumps(self.manifest))
                manifest["domains"][0]["prevalence_pct"] = value
                reasons, domains = validate_manifest(manifest)
                self.assertTrue(any("prevalence_pct" in r for r in reasons), reasons)
                self.assertIsNone(domains[0])

    def test_rejects_huge_document_counts_without_overflow(self):
        huge = 10**400
        mutations = {
            "documents_reporting": lambda m: m["domains"][0].__setitem__("documents_reporting", huge),
            "total_documents": lambda m: m["domains"][0].__setitem__("total_documents", huge),
            "both_domain_counts": lambda m: m["domains"][0].update(documents_reporting=huge, total_documents=huge),
            "consistent_huge_manifest": lambda m: (
                m.update(total_documents=huge, total_turns_parsed=huge, participant_turns_analyzed=huge),
                [d.update(documents_reporting=huge, total_documents=huge, matching_turns=huge, prevalence_pct=100.0)
                 for d in m["domains"]],
            ),
            "one_of_huge_total": lambda m: (
                m.update(total_documents=huge, total_turns_parsed=huge, participant_turns_analyzed=huge),
                [d.update(documents_reporting=1, total_documents=huge, matching_turns=1, prevalence_pct=0.0)
                 for d in m["domains"]],
            ),
            "negative_counts": lambda m: m["domains"][0].update(documents_reporting=-1, total_documents=-3),
            "boolean_counts": lambda m: m["domains"][0].update(documents_reporting=True, total_documents=True),
        }
        for label, mutate in mutations.items():
            with self.subTest(mutation=label):
                self.assert_rejected(self.verify(manifest_path=self.tampered_manifest(mutate)))

    def test_fixture_manifest_hashes_are_real(self):
        for source_id, sha in self.manifest["file_hashes"].items():
            with self.subTest(source=source_id):
                data = (self.scratch / "corpus" / source_id).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), sha)


# ----------------------------------------------------------------------
# Round 2, finding 3: counts beyond the exact-integer ceiling
# ----------------------------------------------------------------------
MAX_EXACT = (1 << 53) - 1
HUGE = 10**400


class HugeCoherentCountTests(IntegrityFixtureMixin, unittest.TestCase):
    """Manifest and workbook agree on out-of-range counts; both must still be rejected."""

    # Distinct integer sentinels, swapped for the real values in the sheet XML
    # because openpyxl cannot serialise integers beyond float range.
    SENTINELS = {3: 987601, 4: 987602, 6: 987603}

    def coherent_export(self, docs, total, turns):
        manifest = json.loads(json.dumps(self.manifest))
        manifest.update(total_documents=total, total_turns_parsed=max(total, turns),
                        participant_turns_analyzed=max(total, turns))
        wb = openpyxl.load_workbook(self.xlsx)
        ws = wb["Empirical Frequencies"]
        swaps = []
        for row_idx, dom in enumerate(manifest["domains"], 2):
            prev = _expected_prevalence(docs, total)
            self.assertIsNotNone(prev)
            digest = audit_digest(dom["domain_id"], docs, total, turns, prev, manifest["file_hashes"])
            dom.update(documents_reporting=docs, total_documents=total, matching_turns=turns,
                       prevalence_pct=prev, audit_sha256=digest)
            for col, value in ((3, docs), (4, total), (6, turns)):
                if value > 10**300:
                    sentinel = self.SENTINELS[col] + 10 * row_idx
                    ws.cell(row=row_idx, column=col).value = sentinel
                    swaps.append((sentinel, value))
                else:
                    ws.cell(row=row_idx, column=col).value = value
            ws.cell(row=row_idx, column=5).value = prev
            ws.cell(row=row_idx, column=5).comment.text = _audit_comment_text(
                dom["domain_name"], docs, total, turns, digest)
            ws.cell(row=row_idx, column=7).value = _reporting_statement(
                prev, docs, total, turns, dom["domain_name"])
        xlsx = str(self.scratch / "coherent_huge.xlsx")
        wb.save(xlsx)
        for sentinel, value in swaps:
            self.rewrite_cell_xml(xlsx, f"<v>{sentinel}</v>", f"<v>{value}</v>")
        manifest_path = str(self.scratch / "coherent_huge_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        stored = openpyxl.load_workbook(xlsx)["Empirical Frequencies"]
        self.assertEqual([stored.cell(row=2, column=c).value for c in (3, 4, 6)], [docs, total, turns],
                         "fixture did not store the counts")
        return xlsx, manifest_path, manifest

    def test_fixture_builder_is_coherent_for_in_range_counts(self):
        # Guards the builder itself: without out-of-range values it must verify.
        xlsx, manifest_path, _ = self.coherent_export(1, 3, 1)
        self.assertEqual(self.verify(xlsx=xlsx, manifest_path=manifest_path), (True, []))

    def test_coherent_huge_counts_rejected_by_both_validators(self):
        cases = {
            "all_huge_prevalence_100": (HUGE, HUGE, HUGE),
            "one_of_huge_total_prevalence_0": (1, HUGE, 1),
            "just_above_ceiling": (MAX_EXACT + 1, MAX_EXACT + 1, MAX_EXACT + 1),
        }
        for label, (docs, total, turns) in cases.items():
            with self.subTest(case=label):
                xlsx, manifest_path, manifest = self.coherent_export(docs, total, turns)
                reasons, domains = validate_manifest(manifest)
                self.assertTrue(reasons, f"validate_manifest accepted {label}")
                self.assertTrue(any(str(MAX_EXACT) in r for r in reasons), reasons)
                self.assertTrue(all(d is None for d in domains), domains)
                self.assert_rejected(self.verify(xlsx=xlsx, manifest_path=manifest_path))

    def test_counts_beyond_python_int_string_limit_are_rejected_cleanly(self):
        # Python refuses int<->str conversion past 4300 digits by default; neither
        # json.load nor a reason message may let that ValueError escape.
        giant = "1" + "0" * 5000
        text = Path(self.manifest_path).read_text(encoding="utf-8")
        docs = self.manifest["domains"][0]["documents_reporting"]
        needle = f'"documents_reporting": {docs}'
        self.assertIn(needle, text)
        path = self.scratch / "giant_literal_manifest.json"
        path.write_text(text.replace(needle, f'"documents_reporting": {giant}', 1), encoding="utf-8")
        self.assert_rejected(self.verify(manifest_path=str(path)))

        manifest = json.loads(json.dumps(self.manifest))
        manifest["total_documents"] = 10**5000
        manifest["domains"][0]["matching_turns"] = 10**5000
        reasons, domains = validate_manifest(manifest)
        self.assertTrue(any(str(MAX_EXACT) in r for r in reasons), reasons)
        self.assertTrue(all(len(r) < 500 for r in reasons), "reason text embeds the giant value")
        self.assertIsNone(domains[0])

    def test_giant_integers_in_any_manifest_field_are_reported_not_raised(self):
        giant = 10**5000
        fields = {
            "prevalence_pct": lambda m, v: m["domains"][0].__setitem__("prevalence_pct", v),
            "domain_id": lambda m, v: m["domains"][0].__setitem__("domain_id", v),
            "domain_name": lambda m, v: m["domains"][0].__setitem__("domain_name", v),
            "file_hashes_key": lambda m, v: m.__setitem__("file_hashes", {v: "not-a-sha"}),
        }
        for label, mutate in fields.items():
            for value in (giant, -giant):
                with self.subTest(field=label, sign="+" if value > 0 else "-"):
                    manifest = json.loads(json.dumps(self.manifest))
                    mutate(manifest, value)
                    reasons, _ = validate_manifest(manifest)
                    self.assertTrue(reasons, f"giant {label} accepted")
                    self.assertTrue(all(len(r) < 500 for r in reasons), "reason text embeds the giant value")

    def test_counts_at_the_ceiling_are_still_accepted(self):
        xlsx, manifest_path, manifest = self.coherent_export(MAX_EXACT, MAX_EXACT, MAX_EXACT)
        self.assertEqual(validate_manifest(manifest)[0], [])
        self.assertEqual(self.verify(xlsx=xlsx, manifest_path=manifest_path), (True, []))


# ----------------------------------------------------------------------
# Round 2, finding 4: boolean / float workbook count cells
# ----------------------------------------------------------------------
class BooleanCountCellTests(IntegrityFixtureMixin, unittest.TestCase):
    """One-document corpus: row 2 counts are 1/1/1, row 3 (no match) is 0/1/0."""

    def setUp(self):
        ScratchMixin.setUp(self)
        codebook = self.scratch / "software_test_codebook.yaml"
        payload = {"project": "SOFTWARE_TEST Boolean Cells", "domains": [
            {"id": "CHC", "name": "Childcare", "roots_en": ["childcare"]},
            {"id": "ZER", "name": "Zero", "roots_en": ["helicopter"]},
        ]}
        codebook.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        corpus = self.scratch / "corpus"
        corpus.mkdir()
        doc = corpus / "a.txt"
        doc.write_text("Respondent A: Childcare costs too much.\n", encoding="utf-8")
        engine = AtlasEngine(str(codebook))
        out = self.scratch / "export"
        engine.export_results(engine.process_corpus([str(doc)], root_dir=str(corpus)), str(out))
        self.xlsx = str(out / "actuarial_parameter_matrix.xlsx")
        self.manifest_path = str(out / "provenance_manifest.json")
        with open(self.manifest_path, encoding="utf-8") as fh:
            self.manifest = json.load(fh)
        ws = openpyxl.load_workbook(self.xlsx)["Empirical Frequencies"]
        self.assertEqual([[ws.cell(row=r, column=c).value for c in (3, 4, 6)] for r in (2, 3)],
                         [[1, 1, 1], [0, 1, 0]], "fixture counts changed")

    def tampered_cell(self, ref, value):
        path = str(self.scratch / f"tampered_{ref}.xlsx")
        wb = openpyxl.load_workbook(self.xlsx)
        is_float = isinstance(value, float)
        # openpyxl writes 1.0 as <v>1</v>, which reads back as int; store a
        # sentinel and rewrite the sheet XML so the cell really holds a float.
        wb["Empirical Frequencies"][ref].value = SENTINEL if is_float else value
        wb.save(path)
        if is_float:
            self.rewrite_cell_xml(path, f"<v>{SENTINEL}</v>", f"<v>{value!r}</v>")
        stored = openpyxl.load_workbook(path)["Empirical Frequencies"][ref].value
        self.assertIs(type(stored), type(value), "fixture did not store the tampered type")
        return path

    def test_boolean_and_float_count_cells_are_rejected(self):
        cases = [("C2", True), ("D2", True), ("F2", True), ("C3", False), ("F3", False),
                 ("C2", 1.0), ("D2", 1.0), ("F2", 1.0), ("F3", 0.0)]
        for ref, value in cases:
            with self.subTest(cell=ref, value=value):
                reasons = self.assert_rejected(self.verify(xlsx=self.tampered_cell(ref, value)))
                self.assertTrue(any(f"is {value!r}" in r for r in reasons), reasons)

    def test_untouched_export_still_verifies(self):
        self.assertEqual(self.verify(), (True, []))

    def test_non_string_text_cells_are_rejected(self):
        for ref, value in (("A2", 1), ("B2", True), ("G2", 0)):
            with self.subTest(cell=ref):
                self.assert_rejected(self.verify(xlsx=self.tampered_cell(ref, value)))


if __name__ == "__main__":
    unittest.main()
