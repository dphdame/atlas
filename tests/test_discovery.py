"""Slice 2a RED: deterministic offline Phase-1 topic discovery (atlas_discover).

Contract under test (.codex/contracts/slice_2b_green.md, item 2):
  discover_topics(turns, n_topics=5, n_top_words=8, random_state=42) -> dict
  topics_to_codebook_dict(discovery_result, project_name=...) -> dict

Every corpus built here is a SOFTWARE_TEST fixture that demonstrates software
mechanics only; none of its content is an empirical finding. The six-turn corpus
is a vocabulary-prototype fixture: the two clusters share no terms, and inside
each cluster one turn (turn 3 for housing, turn 4 for transit) carries the
cluster vocabulary in the proportions of the cluster mean, so its TF-IDF cosine
to the cluster centroid is the strict maximum (about 0.91 against about 0.69 and
0.66 for the other two). The prototype is neither the first nor the longest turn
of its cluster, so first-turn or longest-turn picking cannot pass.

Run: .venv/bin/python -m unittest tests/test_discovery.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from atlas_engine import AtlasEngine  # noqa: E402

try:
    import atlas_discover  # noqa: E402
except ImportError:
    atlas_discover = None

HOUSING_VOCAB = {"rent", "landlord", "eviction", "lease", "deposit", "mold", "repairs", "keys", "apartment", "hallway"}
TRANSIT_VOCAB = {"bus", "commute", "transit", "fare", "schedule", "driver", "bench", "shelter", "downtown", "transfer"}

HOUSING_TEXTS = {
    1: "rent landlord rent landlord",
    3: " ".join(["rent landlord eviction lease"] * 4),  # prototype
    5: " ".join(["eviction lease"] * 5 + ["deposit mold repairs keys apartment hallway"]),  # longest
}
TRANSIT_TEXTS = {
    2: "bus commute bus commute",
    4: " ".join(["bus commute transit fare"] * 4),  # prototype
    6: " ".join(["transit fare"] * 5 + ["schedule driver bench shelter downtown transfer"]),  # longest
}
HOUSING_PROTOTYPE_ID = 3
TRANSIT_PROTOTYPE_ID = 4


def _turn(turn_id, text, speaker=None, is_facilitator=False):
    return {
        "turn_id": turn_id,
        "unit_id": f"software_test/discovery_fixture.txt::unit_{turn_id}",
        "source_id": "software_test/discovery_fixture.txt",
        "speaker": speaker or f"Respondent {turn_id}",
        "is_facilitator": is_facilitator,
        "text": text,
    }


def six_turn_corpus():
    """Facilitator prompt first (must be filtered), then turns 1..6 alternating clusters."""
    turns = [_turn(0, "rent bus landlord fare eviction commute lease transit", speaker="Moderator", is_facilitator=True)]
    all_texts = {**HOUSING_TEXTS, **TRANSIT_TEXTS}
    for turn_id in sorted(all_texts):
        turns.append(_turn(turn_id, all_texts[turn_id]))
    return turns


def term_tokens(term):
    return set(term.split())


class DiscoveryBase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(atlas_discover, "atlas_discover module not implemented yet")
        self.assertTrue(callable(getattr(atlas_discover, "discover_topics", None)), "discover_topics missing")
        self.assertTrue(
            callable(getattr(atlas_discover, "topics_to_codebook_dict", None)), "topics_to_codebook_dict missing"
        )

    def topic_for(self, result, vocab):
        """Return the single topic whose medoid text is drawn from vocab."""
        matches = [t for t in result["topics"] if term_tokens(t["medoid_text"]) <= vocab]
        self.assertEqual(len(matches), 1, f"expected exactly one topic with a medoid from {sorted(vocab)[:4]}...")
        return matches[0]


class TestDiscoverTopicsPrototypeMedoids(DiscoveryBase):
    def setUp(self):
        super().setUp()
        self.result = atlas_discover.discover_topics(six_turn_corpus(), n_topics=2, random_state=42)

    def test_two_topics_and_facilitator_filtered(self):
        self.assertEqual(len(self.result["topics"]), 2)
        self.assertEqual(self.result["n_analyzed"], 6, "facilitator turn must be excluded from discovery")
        self.assertEqual(sum(t["turn_count"] for t in self.result["topics"]), 6)

    def test_top_terms_are_deduplicated_and_separate_clusters(self):
        housing = self.topic_for(self.result, HOUSING_VOCAB)
        transit = self.topic_for(self.result, TRANSIT_VOCAB)
        self.assertTrue(housing["top_terms"], "housing topic has no top_terms")
        self.assertTrue(transit["top_terms"], "transit topic has no top_terms")
        for term in housing["top_terms"]:
            self.assertTrue(term_tokens(term) <= HOUSING_VOCAB, f"housing topic carries non-housing term {term!r}")
        for term in transit["top_terms"]:
            self.assertTrue(term_tokens(term) <= TRANSIT_VOCAB, f"transit topic carries non-transit term {term!r}")
        self.assertEqual(set(housing["top_terms"]) & set(transit["top_terms"]), set(), "top_terms not deduplicated")
        self.assertLessEqual(len(housing["top_terms"]), 8)
        self.assertLessEqual(len(transit["top_terms"]), 8)

    def test_medoid_is_the_tfidf_centroid_prototype(self):
        housing = self.topic_for(self.result, HOUSING_VOCAB)
        transit = self.topic_for(self.result, TRANSIT_VOCAB)

        self.assertEqual(housing["medoid_text"], HOUSING_TEXTS[HOUSING_PROTOTYPE_ID])
        self.assertEqual(housing["medoid_turn_id"], HOUSING_PROTOTYPE_ID)
        self.assertEqual(housing["medoid_unit_id"], _turn(HOUSING_PROTOTYPE_ID, "")["unit_id"])
        self.assertEqual(housing["medoid_speaker"], f"Respondent {HOUSING_PROTOTYPE_ID}")

        self.assertEqual(transit["medoid_text"], TRANSIT_TEXTS[TRANSIT_PROTOTYPE_ID])
        self.assertEqual(transit["medoid_turn_id"], TRANSIT_PROTOTYPE_ID)
        self.assertEqual(transit["medoid_unit_id"], _turn(TRANSIT_PROTOTYPE_ID, "")["unit_id"])

        for topic in (housing, transit):
            self.assertEqual(topic["turn_count"], 3)
            self.assertAlmostEqual(float(topic["share_pct"]), 50.0, places=1)
            sim = float(topic["medoid_similarity"])
            self.assertGreater(sim, 0.85, "prototype cosine to its cluster centroid is about 0.91")
            self.assertLessEqual(sim, 1.0 + 1e-9)

    def test_result_carries_required_topic_fields(self):
        required = {
            "topic_id", "label", "top_terms", "turn_count", "share_pct", "medoid_text",
            "medoid_turn_id", "medoid_speaker", "medoid_unit_id", "medoid_similarity",
        }
        for topic in self.result["topics"]:
            self.assertTrue(required <= set(topic), f"missing keys: {sorted(required - set(topic))}")
        self.assertIn("assignments", self.result)

    def test_same_seed_is_reproducible(self):
        again = atlas_discover.discover_topics(six_turn_corpus(), n_topics=2, random_state=42)
        self.assertEqual(again["topics"], self.result["topics"])
        self.assertEqual(again["n_analyzed"], self.result["n_analyzed"])


class TestDiscoverTopicsEdgeCases(DiscoveryBase):
    def test_identical_turns_tie_break_to_lowest_turn_id(self):
        housing = "rent eviction landlord lease"
        transit = "bus commute transit fare"
        turns = [
            _turn(7, housing), _turn(6, transit), _turn(3, housing),
            _turn(2, transit), _turn(5, housing), _turn(4, transit),
        ]
        result = atlas_discover.discover_topics(turns, n_topics=2, random_state=42)
        self.assertEqual(len(result["topics"]), 2)
        self.assertEqual(self.topic_for(result, HOUSING_VOCAB)["medoid_turn_id"], 3)
        self.assertEqual(self.topic_for(result, TRANSIT_VOCAB)["medoid_turn_id"], 2)

    def test_tiny_corpus_clamps_topic_count(self):
        turns = [_turn(1, "rent eviction landlord lease"), _turn(2, "bus commute transit fare")]
        result = atlas_discover.discover_topics(turns, n_topics=5, random_state=42)
        self.assertEqual(len(result["topics"]), 2)
        self.assertEqual(result["n_analyzed"], 2)
        self.assertEqual(sum(t["turn_count"] for t in result["topics"]), 2)

    def test_empty_and_stopword_only_corpus_returns_no_topics(self):
        for label, turns in (
            ("no turns", []),
            ("blank and stopword-only", [_turn(1, ""), _turn(2, "   "), _turn(3, "the and of"), _turn(4, "y de la")]),
        ):
            with self.subTest(case=label):
                result = atlas_discover.discover_topics(turns, n_topics=2, random_state=42)
                self.assertEqual(result["topics"], [])
                self.assertEqual(result["n_analyzed"], 0)

    def test_plain_string_input_is_accepted(self):
        texts = [HOUSING_TEXTS[i] for i in sorted(HOUSING_TEXTS)] + [TRANSIT_TEXTS[i] for i in sorted(TRANSIT_TEXTS)]
        result = atlas_discover.discover_topics(texts, n_topics=2, random_state=42)
        self.assertEqual(result["n_analyzed"], 6)
        self.assertEqual(len(result["topics"]), 2)
        medoids = {t["medoid_text"] for t in result["topics"]}
        self.assertEqual(medoids, {HOUSING_TEXTS[HOUSING_PROTOTYPE_ID], TRANSIT_TEXTS[TRANSIT_PROTOTYPE_ID]})


class TestTopicsToCodebookRoundTrip(DiscoveryBase):
    def test_discovered_codebook_compiles_and_reidentifies_clusters(self):
        result = atlas_discover.discover_topics(six_turn_corpus(), n_topics=2, random_state=42)
        codebook = atlas_discover.topics_to_codebook_dict(result, project_name="SOFTWARE_TEST Discovered Codebook")

        self.assertEqual(codebook["project"], "SOFTWARE_TEST Discovered Codebook")
        self.assertEqual(len(codebook["domains"]), 2)
        for domain in codebook["domains"]:
            self.assertTrue(domain.get("id"))
            self.assertTrue(domain.get("name"))
            self.assertTrue(domain.get("roots_en"), f"domain {domain.get('id')} has no roots_en")

        with tempfile.TemporaryDirectory() as tmp:
            cb_path = os.path.join(tmp, "discovered_codebook.yaml")
            with open(cb_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(codebook, fh, allow_unicode=True, sort_keys=False)

            engine = AtlasEngine(cb_path)
            self.assertEqual(engine.project_name, "SOFTWARE_TEST Discovered Codebook")
            self.assertEqual(len(engine.compiled_rules), 2)
            for rule in engine.compiled_rules:
                self.assertIsNotNone(rule["root_regex"])

            transcript = os.path.join(tmp, "software_test_discovery_transcript.txt")
            all_texts = {**HOUSING_TEXTS, **TRANSIT_TEXTS}
            with open(transcript, "w", encoding="utf-8") as fh:
                for turn_id in sorted(all_texts):
                    fh.write(f"Respondent {turn_id}: {all_texts[turn_id]}\n")

            results = engine.process_corpus([transcript])
            quotes = results["quotes_df"]
            housing_set = set(HOUSING_TEXTS.values())
            transit_set = set(TRANSIT_TEXTS.values())
            by_domain = {d: set(quotes.loc[quotes["domain_id"] == d, "text"]) for d in quotes["domain_id"].unique()}
            self.assertEqual(
                set(map(frozenset, by_domain.values())),
                {frozenset(housing_set), frozenset(transit_set)},
                "each discovered domain should match exactly its own cluster's three turns",
            )


if __name__ == "__main__":
    unittest.main()
