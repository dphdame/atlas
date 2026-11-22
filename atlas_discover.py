"""
ATLAS Discover
Deterministic, fully offline Phase-1 topic discovery for qualitative corpora.

Fits a bag-of-words Latent Dirichlet Allocation model (scikit-learn) over
participant turns, assigns each turn to its dominant topic, picks a TF-IDF
cosine medoid turn per topic, and converts the discovered topics into an ATLAS
YAML codebook draft that compiles directly in AtlasEngine. Stopwords are
embedded static English and Spanish sets; nothing is downloaded.

Discovered topics are exploratory suggestions for a human coder to review,
rename and fence; they are not findings.
"""

import unicodedata
from typing import Any, Dict, List, Sequence, Union

import numpy as np
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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

EN_ES_STOPWORDS = EN_STOPWORDS | ES_STOPWORDS
_STOP_LIST = sorted(EN_ES_STOPWORDS)


def _empty_result() -> Dict[str, Any]:
    return {"topics": [], "n_analyzed": 0, "doc_topics": [], "assignments": []}


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


def discover_topics(
    turns: Sequence[Union[Dict[str, Any], str]],
    n_topics: int = 5,
    n_top_words: int = 8,
    random_state: int = 42,
) -> Dict[str, Any]:
    """
    Discover latent topics over participant turns.

    turns: list of turn dicts (facilitator turns, is_facilitator=True, are dropped)
    or list of plain strings. Empty texts and texts with no tokens after stopword
    filtering are not analyzed. The topic count is clamped to [1, n_valid_docs].

    Returns {"topics": [...], "n_analyzed": int, "doc_topics": [[...], ...],
    "assignments": [...]}; each topic carries topic_id, label, top_terms,
    turn_count, share_pct and its TF-IDF cosine medoid turn (medoid_text,
    medoid_turn_id, medoid_speaker, medoid_unit_id, medoid_similarity).
    """
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
        return _empty_result()

    docs = [rec["normalized"] for rec in valid]
    k = min(max(1, int(n_topics)), len(docs))
    n_top_words = max(1, int(n_top_words))

    counter = CountVectorizer(ngram_range=(1, 2), stop_words=_STOP_LIST, min_df=1, max_features=2000)
    counts = counter.fit_transform(docs)
    vocab = counter.get_feature_names_out()
    if len(vocab) == 0:
        return _empty_result()

    lda = LatentDirichletAllocation(n_components=k, max_iter=25, random_state=random_state)
    doc_topic = lda.fit_transform(counts)
    components = lda.components_

    # Cross-topic deduplication: each term belongs to the topic where its weight is highest.
    owner = np.argmax(components, axis=0)
    top_terms: List[List[str]] = []
    for t in range(k):
        owned = [j for j in range(len(vocab)) if owner[j] == t]
        owned.sort(key=lambda j: (-components[t, j], vocab[j]))
        if not owned:
            owned = sorted(range(len(vocab)), key=lambda j: (-components[t, j], vocab[j]))
        top_terms.append([str(vocab[j]) for j in owned[:n_top_words]])

    best_topic = [int(np.argmax(doc_topic[i])) for i in range(len(docs))]

    tfidf = TfidfVectorizer(ngram_range=(1, 2), stop_words=_STOP_LIST, min_df=1).fit_transform(docs)

    topics = []
    for t in range(k):
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
            "turn_id": rec["turn_id"],
            "unit_id": rec["unit_id"],
            "speaker": rec["speaker"],
            "topic_id": best_topic[i] + 1,
            "topic_weight": float(doc_topic[i, best_topic[i]]),
        }
        for i, rec in enumerate(valid)
    ]

    return {
        "topics": topics,
        "n_analyzed": len(docs),
        "doc_topics": [[float(x) for x in row] for row in doc_topic],
        "assignments": assignments,
    }


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
