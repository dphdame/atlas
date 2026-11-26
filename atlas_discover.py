"""
ATLAS Discover
Deterministic, fully offline Phase-1 topic discovery for qualitative corpora.

Fits a TF-IDF + Non-Negative Matrix Factorization (NMF, default) or classic
bag-of-words Latent Dirichlet Allocation (LDA) model (scikit-learn) over
participant turns, assigns each turn to its dominant topic, picks a TF-IDF
cosine medoid turn per topic, and converts the discovered topics into an ATLAS
YAML codebook draft that compiles directly in AtlasEngine. Stopwords are
embedded static English and Spanish sets; nothing is downloaded.

Discovered topics are exploratory suggestions for a human coder to review,
rename and fence; they are not findings.
"""

import unicodedata
import warnings
from typing import Any, Dict, List, Sequence, Union

import numpy as np
from sklearn.decomposition import LatentDirichletAllocation, NMF
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DISCOVERY_METHODS = ("nmf", "lda")
_DENSE_NMF_CELL_LIMIT = 4_000_000

EN_STOPWORDS = frozenset("""
a about above after again against all also am an and any are aren as at be because been before being below
between both but by can cannot could couldn did didn do does doesn doing don down during each even ever every
few for from further get gets got had hadn has hasn have haven having he her here hers herself him himself his
how however i if in into is isn it its itself just like ll me might more most much must mustn my myself no nor
not now of off on once one only or other our ours ourselves out over own really re said same say says she
should shouldn so some still such than that the their theirs them themselves then there these they thing
things this those though through to too under until up upon us ve very was wasn we well were weren what when
where which while who whom whose why will with won would wouldn yeah yes yet you your yours yourself
yourselves um uh okay ok oh
""".split())

ES_STOPWORDS = frozenset("""
a al algo algunas algunos ante antes aquel aquella aquellas aquellos aqui aquí asi así aun aún bien cada como
cómo con contra cual cuál cuales cuando cuándo de del desde donde dónde dos el él ella ellas ello ellos en entre
era eran eres es esa esas ese eso esos esta está estaba estaban estamos estan están estar este esto estos estoy
fue fueron fui ha había habían han has hasta hay la las le les lo los mas más me mi mí mis mucho muchos muy
nada ni no nos nosotras nosotros nuestra nuestras nuestro nuestros o os otra otras otro otros para pero poco
por porque pues que qué quien quién quienes se sea ser si sí siempre sin sobre solo sólo son su sus también
tambien tan tanto te tenemos tener tengo ti tiene tienen todo todos tu tú tus un una unas uno unos usted
ustedes va vamos van y ya yo
""".split())

SPEAKER_ID_STOPWORDS = frozenset(
    [f"p{i}" for i in range(100)] + ["participant", "participants"]
)
EN_ES_STOPWORDS = EN_STOPWORDS | ES_STOPWORDS
_STOP_LIST = sorted(EN_ES_STOPWORDS | SPEAKER_ID_STOPWORDS)


def _empty_result(method: str = "nmf") -> Dict[str, Any]:
    return {"method": method, "topics": [], "n_analyzed": 0, "doc_topics": [], "assignments": []}


def _turn_records(turns: Sequence[Union[Dict[str, Any], str]]) -> List[Dict[str, Any]]:
    """Normalize dict or string input into participant records with stable identity."""
    records = []
    for index, item in enumerate(turns or []):
        if isinstance(item, dict):
            if item.get("is_facilitator", False):
                continue
            text = item.get("text")
            records.append({
                "index": index,
                "turn_id": item.get("turn_id", index + 1),
                "speaker": item.get("speaker"),
                "unit_id": item.get("unit_id"),
                "source_id": item.get("source_id"),
                "text": "" if text is None else str(text),
            })
        else:
            records.append({
                "index": index, "turn_id": index + 1, "speaker": None, "unit_id": None, "source_id": None,
                "text": "" if item is None else str(item),
            })
    return records


def _tie_key(record: Dict[str, Any]):
    turn_id = record["turn_id"]
    if isinstance(turn_id, (int, np.integer)) and not isinstance(turn_id, bool):
        return (0, int(turn_id), "", record["index"])
    return (1, 0, str(turn_id), record["index"])


def _fit_nmf_stable(matrix, k: int, random_state: int):
    """Fit NMF without sparse Frobenius-norm cancellation warnings.

    In scikit-learn's sparse `_beta_divergence(beta=2)`, `(||X||^2 + ||WH||^2 - 2<X,WH>)/2`
    can round to `-1e-16` on exact-rank fits and trigger `np.sqrt(res * 2)` RuntimeWarning.
    Dense inputs compute `squared_norm(X - W @ H) / 2` (strictly non-negative).
    """
    use_dense = (matrix.shape[0] * matrix.shape[1]) <= _DENSE_NMF_CELL_LIMIT
    nmf_input = matrix.toarray() if use_dense else matrix
    nmf_init = "nndsvda" if k <= min(nmf_input.shape[0], nmf_input.shape[1]) else "random"

    def _run(init_mode: str):
        model = NMF(n_components=k, init=init_mode, max_iter=400, random_state=random_state)
        if use_dense:
            doc_topic = model.fit_transform(nmf_input)
        else:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"invalid value encountered in sqrt",
                    category=RuntimeWarning,
                    module=r"sklearn\.decomposition\._nmf",
                )
                doc_topic = model.fit_transform(nmf_input)
        return doc_topic, model.components_

    doc_topic, components = _run(nmf_init)
    if not (np.all(np.isfinite(doc_topic)) and np.all(np.isfinite(components))):
        doc_topic, components = _run("random")
    return doc_topic, components


def discover_topics(
    turns: Sequence[Union[Dict[str, Any], str]],
    n_topics: int = 5,
    n_top_words: int = 8,
    random_state: int = 42,
    method: str = "nmf",
) -> Dict[str, Any]:
    """
    Discover latent topics over participant turns.

    turns: list of turn dicts (facilitator turns, is_facilitator=True, are dropped)
    or list of plain strings. Empty texts and texts with no tokens after stopword
    filtering are not analyzed. Effective topic count is clamped to the supported
    unique-pattern and vocabulary ceiling in [1, n_valid_docs], and empty or
    ownerless components are dropped so topics stay supported with exclusive top terms.
    method: "nmf" (default: TF-IDF 1-2 grams with sublinear TF + NMF) or "lda"
    (classic CountVectorizer + LatentDirichletAllocation).

    Returns {"method": str, "topics": [...], "n_analyzed": int, "doc_topics": [[...], ...],
    "assignments": [...]}; each topic carries topic_id, label, top_terms,
    turn_count, share_pct and its TF-IDF cosine medoid turn (medoid_text,
    medoid_turn_id, medoid_speaker, medoid_unit_id, medoid_similarity).
    """
    method_key = str(method).strip().lower()
    if method_key not in DISCOVERY_METHODS:
        raise ValueError(f"Unsupported discovery method {method!r}; expected one of {DISCOVERY_METHODS}")

    records = _turn_records(turns)
    analyzer = CountVectorizer(ngram_range=(1, 2), stop_words=_STOP_LIST).build_analyzer()

    valid: List[Dict[str, Any]] = []
    for rec in records:
        if not rec["text"].strip():
            continue
        normalized = unicodedata.normalize("NFC", rec["text"])
        if not analyzer(normalized):
            continue
        valid.append(dict(rec, normalized=normalized))
    if not valid:
        return _empty_result(method_key)

    docs = [rec["normalized"] for rec in valid]
    requested_k = max(1, int(n_topics))
    n_top_words = max(1, int(n_top_words))

    if method_key == "nmf":
        vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words=_STOP_LIST, min_df=1, max_features=2000)
        matrix = vec.fit_transform(docs)
        vocab = vec.get_feature_names_out()
        if len(vocab) == 0:
            return _empty_result(method_key)
        unique_patterns = len({
            (tuple(matrix[i].indices), tuple(np.round(matrix[i].data, 12)))
            for i in range(matrix.shape[0])
        })
        k = min(requested_k, len(docs), len(vocab), max(1, unique_patterns))
        corpus_weights = np.asarray(matrix.sum(axis=0)).ravel()
        if k == 1:
            doc_topic = np.ones((len(docs), 1), dtype=float)
            components = corpus_weights.reshape(1, -1)
        else:
            doc_topic, components = _fit_nmf_stable(matrix, k, random_state)
    else:
        counter = CountVectorizer(ngram_range=(1, 2), stop_words=_STOP_LIST, min_df=1, max_features=2000)
        counts = counter.fit_transform(docs)
        vocab = counter.get_feature_names_out()
        if len(vocab) == 0:
            return _empty_result(method_key)
        unique_patterns = len({
            (tuple(counts[i].indices), tuple(counts[i].data))
            for i in range(counts.shape[0])
        })
        k = min(requested_k, len(docs), len(vocab), max(1, unique_patterns))
        corpus_weights = np.asarray(counts.sum(axis=0)).ravel()
        if k == 1:
            doc_topic = np.ones((len(docs), 1), dtype=float)
            components = corpus_weights.reshape(1, -1)
        else:
            lda = LatentDirichletAllocation(n_components=k, max_iter=25, random_state=random_state)
            doc_topic = lda.fit_transform(counts)
            components = lda.components_

    # Cross-topic deduplication: each term belongs to the single component with
    # the highest positive weight. Drop ownerless or zero-member components so
    # degenerate corpora never emit empty or duplicate domains.
    raw_owner = np.argmax(components, axis=0)
    term_supported = [
        t for t in range(k)
        if any(raw_owner[j] == t and components[t, j] > 0 for j in range(len(vocab)))
    ]

    if not term_supported:
        doc_topic = np.ones((len(docs), 1), dtype=float)
        best_topic = [0] * len(docs)
        ranked_vocab = sorted(range(len(vocab)), key=lambda j: (-float(corpus_weights[j]), str(vocab[j])))
        top_terms: List[List[str]] = [[str(vocab[j]) for j in ranked_vocab[:n_top_words]]]
        n_kept = 1
    else:
        sub_doc_topic = doc_topic[:, term_supported]
        raw_best = [int(np.argmax(sub_doc_topic[i])) for i in range(len(docs))]
        kept_local = sorted(set(raw_best))
        kept = [term_supported[idx] for idx in kept_local]
        doc_topic = doc_topic[:, kept]
        kept_components = components[kept, :]
        remap = {old_idx: new_idx for new_idx, old_idx in enumerate(kept_local)}
        best_topic = [remap[idx] for idx in raw_best]

        owner = np.argmax(kept_components, axis=0)
        top_terms = []
        for t in range(len(kept)):
            owned = [j for j in range(len(vocab)) if owner[j] == t and kept_components[t, j] > 0]
            owned.sort(key=lambda j: (-float(kept_components[t, j]), str(vocab[j])))
            top_terms.append([str(vocab[j]) for j in owned[:n_top_words]])
        n_kept = len(kept)

    tfidf = TfidfVectorizer(ngram_range=(1, 2), stop_words=_STOP_LIST, min_df=1).fit_transform(docs)

    topics = []
    for t in range(n_kept):
        members = [i for i, bt in enumerate(best_topic) if bt == t]
        topic = {
            "topic_id": t + 1,
            "label": " / ".join(top_terms[t][:3]),
            "top_terms": top_terms[t],
            "turn_count": len(members),
            "share_pct": round(len(members) / len(docs) * 100.0, 1),
            "medoid_text": None,
            "medoid_turn_id": None,
            "medoid_speaker": None,
            "medoid_unit_id": None,
            "medoid_similarity": None,
        }
        if members:
            block = tfidf[members]
            centroid = np.asarray(block.mean(axis=0))
            sims = cosine_similarity(block, centroid).ravel()
            ranked = sorted(
                range(len(members)),
                key=lambda m: (-round(float(sims[m]), 12), _tie_key(valid[members[m]])),
            )
            best = ranked[0]
            rec = valid[members[best]]
            topic.update({
                "medoid_text": rec["text"],
                "medoid_turn_id": rec["turn_id"],
                "medoid_speaker": rec["speaker"],
                "medoid_unit_id": rec["unit_id"],
                "medoid_similarity": float(sims[best]),
            })
        topics.append(topic)

    assignments = [
        {
            "index": rec["index"],
            "source_id": rec["source_id"],
            "turn_id": rec["turn_id"],
            "unit_id": rec["unit_id"],
            "speaker": rec["speaker"],
            "topic_id": best_topic[i] + 1,
            "topic_weight": float(doc_topic[i, best_topic[i]]),
        }
        for i, rec in enumerate(valid)
    ]

    return {
        "method": method_key,
        "topics": topics,
        "n_analyzed": len(docs),
        "doc_topics": [[float(x) for x in row] for row in doc_topic],
        "assignments": assignments,
    }


def compute_topic_codebook_overlap(
    discovery_result: Dict[str, Any],
    turn_records: Sequence[Dict[str, Any]],
    domain_names: Dict[str, str] = None,
) -> Dict[int, Dict[str, Any]]:
    """
    Compute deterministic codebook-coverage statistics per discovered topic.

    Joins strictly one-to-one using each assignment's original input `index`
    against `turn_records` (never `turn_id`, which restarts at 1 per file).
    """
    topics = list((discovery_result or {}).get("topics") or [])
    assignments = list((discovery_result or {}).get("assignments") or [])
    names_map = dict(domain_names or {})
    n_turns = len(turn_records)

    by_topic: Dict[int, List[int]] = {int(t["topic_id"]): [] for t in topics}
    for assign in assignments:
        idx = int(assign["index"])
        if not (0 <= idx < n_turns):
            raise ValueError(f"Discovery assignment index {idx} out of bounds for {n_turns} turn records")
        tid = int(assign["topic_id"])
        by_topic.setdefault(tid, []).append(idx)

    total_assigned = sum(len(v) for v in by_topic.values())
    expected_analyzed = int((discovery_result or {}).get("n_analyzed", 0))
    if total_assigned != expected_analyzed:
        raise ValueError(
            f"Discovery assignment conservation failed: {total_assigned} assigned vs {expected_analyzed} analyzed"
        )

    out: Dict[int, Dict[str, Any]] = {}
    for t in topics:
        tid = int(t["topic_id"])
        member_indices = by_topic.get(tid, [])
        total = len(member_indices)
        uncoded = 0
        domain_counts: Dict[str, int] = {}
        for idx in member_indices:
            matched = list(turn_records[idx].get("matched_domains") or [])
            if not matched:
                uncoded += 1
            else:
                for did in matched:
                    label = str(names_map.get(str(did), str(did)))
                    domain_counts[label] = domain_counts.get(label, 0) + 1
        covered = total - uncoded
        uncoded_share = (uncoded / total) if total > 0 else 0.0
        top_overlap = ""
        if domain_counts:
            top_overlap = sorted(domain_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        if total == 0:
            status = "empty"
            label = "No entries assigned"
        elif uncoded_share >= 0.70:
            status = "mostly_uncoded"
            label = f"Mostly Uncoded by Active Themes ({uncoded} of {total} uncoded)"
        elif uncoded_share > 0.30:
            status = "partially_uncoded"
            suffix = f"; overlaps {top_overlap}" if top_overlap else ""
            label = f"Partially Uncoded ({uncoded} of {total} uncoded{suffix})"
        else:
            status = "mostly_covered"
            suffix = f"; mostly {top_overlap}" if top_overlap else ""
            label = f"Mostly Covered by Active Themes ({covered} of {total} matched{suffix})"

        out[tid] = {
            "topic_id": tid,
            "member_indices": member_indices,
            "total_count": total,
            "uncoded_count": uncoded,
            "covered_count": covered,
            "uncoded_share": round(uncoded_share, 4),
            "top_overlap_domain": top_overlap,
            "coverage_status": status,
            "coverage_label": label,
        }
    return out


def topics_to_codebook_dict(discovery_result: Dict[str, Any], project_name: str = "Discovered Codebook") -> Dict[str, Any]:
    """
    Convert discover_topics output into an ATLAS 'domains' codebook dict whose
    roots are each topic's top terms. The draft has no context fences; a coder
    should review, rename and fence it before deductive use.
    """
    domains = []
    for topic in discovery_result.get("topics", []):
        terms = [str(t) for t in topic.get("top_terms", []) if str(t).strip()]
        if not terms:
            continue
        domain_id = f"DISCOVERED_TOPIC_{topic['topic_id']}"
        domains.append({
            "id": domain_id,
            "name": topic.get("label") or domain_id,
            "description": (
                f"Discovered topic {topic['topic_id']} ({topic.get('turn_count', 0)} assigned turns); "
                "exploratory draft for coder review."
            ),
            "roots_en": terms,
            "roots_es": [],
            "context_fences": [],
        })
    return {"project": project_name, "version": "1.0", "domains": domains}
