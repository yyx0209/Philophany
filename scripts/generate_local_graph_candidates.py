#!/usr/bin/env python3
"""
Generate local relation candidates with NetworkX and local text embeddings.

This script does not call an LLM and does not overwrite curated app data.
It outputs review-only relation candidates for later human selection.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from itertools import combinations
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from graph_data_io import load_card_bundle, load_existing_relations


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WIKIDATA_GRAPH = ROOT / "data" / "generated" / "wikidata_graph.json"
DEFAULT_CARDS = ROOT / "data" / "generated" / "reviewed_philosopher_cards.json"
LEGACY_DATA_JS = ROOT / "data.js"
DEFAULT_OUTPUT = ROOT / "data" / "generated" / "local_graph_candidates.json"
DEFAULT_WIKIPEDIA_CACHE = ROOT / "data" / "generated" / "wikipedia_philosophy_extracts.json"
DEFAULT_RELATION_PRIORS = ROOT / "data" / "seeds" / "relation_priors.json"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_MIN_SCORE = 0.34
DEFAULT_MAX_PER_PHILOSOPHER = 6
RELATION_PRIOR_RETRIEVAL_FLOOR = 0.72
WIKIDATA_INFLUENCE_RETRIEVAL_FLOOR = 0.78
WIKIDATA_INFLUENCE_CONFIDENCE = 0.86
STANCE_TENSION_RETRIEVAL_FLOOR = 0.36
STANCE_OPPOSITION_MIN_SCORE = 0.66
GENERIC_EVIDENCE_IDS = {"Q5891"}
GENERIC_EVIDENCE_LABELS = {"哲學", "哲学", "philosophy"}
BROAD_TOPIC_LABELS = {"成功", "道德", "行动", "自由"}
EVIDENCE_KIND_WEIGHTS = {
    "concept": 1.3,
    "movement": 1.2,
    "field": 1.0,
    "influence": 0.95,
    "work": 0.75,
    "topic": 0.22,
    "stance": 0.16,
}
SCORING_WEIGHTS = {
    "semantic_recall": 0.12,
    "graph_proximity": 0.28,
    "structured_evidence": 0.30,
    "problem_axis": 0.20,
    "stance_relation": 0.10,
}
PROBLEM_AXIS_KINDS = {"concept", "field", "topic"}
ALLOWED_SUGGESTED_TYPES = {"affinity", "tension", "influence"}
USER_AGENT = "PhilophanyMVP/0.1 (local graph candidate generation)"
SECTION_TITLE_KEYWORDS = {
    "zh": [
        "思想",
        "哲学",
        "哲學",
        "学说",
        "學說",
        "理论",
        "理論",
        "教义",
        "教義",
        "心学",
        "心學",
        "伦理",
        "倫理",
        "认识论",
        "認識論",
        "知识论",
        "知識論",
        "形而上",
        "政治哲学",
        "政治哲學",
    ],
    "en": [
        "philosophy",
        "thought",
        "ideas",
        "doctrine",
        "teachings",
        "ethics",
        "epistemology",
        "metaphysics",
        "political philosophy",
        "political philosophy",
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local philosopher graph candidates.")
    parser.add_argument("--wikidata", type=Path, default=DEFAULT_WIKIDATA_GRAPH)
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--existing-relations", type=Path, default=None)
    parser.add_argument("--data-js", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--wikipedia-cache", type=Path, default=DEFAULT_WIKIPEDIA_CACHE)
    parser.add_argument("--relation-priors", type=Path, default=DEFAULT_RELATION_PRIORS)
    parser.add_argument("--embedding-backend", choices=["auto", "tfidf", "sentence-transformers"], default="auto")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--max-per-philosopher", type=int, default=DEFAULT_MAX_PER_PHILOSOPHER)
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--skip-wikipedia-extracts", action="store_true")
    parser.add_argument("--refresh-wikipedia-extracts", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wikidata_graph = read_json(args.wikidata)
    cards_path = args.data_js or args.cards
    card_bundle = load_card_bundle(cards_path)
    graph, people = build_heterogeneous_graph(wikidata_graph, card_bundle)
    philosopher_ids = set(people)
    existing_relations = (
        load_existing_relations(args.existing_relations, philosopher_ids=philosopher_ids)
        if args.existing_relations
        else card_bundle.get("relations", [])
    )
    relation_priors = load_relation_priors(args.relation_priors, philosopher_ids=philosopher_ids)
    wikipedia_cache_count = cached_wikipedia_extract_count(args.wikipedia_cache)

    if args.dry_run:
        print(f"Philosophers: {len(people)}")
        print(f"Graph nodes: {graph.number_of_nodes()}")
        print(f"Graph edges: {graph.number_of_edges()}")
        print(f"Cards: {cards_path}")
        print(f"Existing curated relations: {len(existing_relations)}")
        print(f"Relation priors: {len(relation_priors)}")
        print(f"Cached Wikipedia extracts: {wikipedia_cache_count}")
        print(f"Embedding backend: {choose_embedding_backend(args.embedding_backend)}")
        print(f"Output: {args.output}")
        return

    backend = choose_embedding_backend(args.embedding_backend)
    wikipedia_stats = enrich_wikipedia_extracts(
        people=people,
        cache_path=args.wikipedia_cache,
        refresh=args.refresh_wikipedia_extracts,
        skip_fetch=args.skip_wikipedia_extracts,
    )
    candidates = generate_candidates(
        graph=graph,
        people=people,
        existing_relations=existing_relations,
        max_per_philosopher=args.max_per_philosopher,
        min_score=args.min_score,
        embedding_backend=backend,
        embedding_model=args.embedding_model,
        relation_priors=relation_priors,
    )

    output = {
        "metadata": {
            "source": "local-networkx-embeddings",
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "needsReview": True,
            "embeddingBackend": backend,
            "embeddingModel": args.embedding_model if backend == "sentence-transformers" else "sklearn-tfidf-char-ngrams",
            "philosophers": len(people),
            "graphNodes": graph.number_of_nodes(),
            "graphEdges": graph.number_of_edges(),
            "wikipediaCache": str(args.wikipedia_cache),
            "cards": str(cards_path),
            "existingRelations": str(args.existing_relations) if args.existing_relations else "",
            "relationPriors": str(args.relation_priors),
            "relationPriorCount": len(relation_priors),
            "wikipediaExtracts": wikipedia_stats["available"],
            "wikipediaSections": wikipedia_stats["sections"],
            "minScore": args.min_score,
            "maxPerPhilosopher": args.max_per_philosopher,
            "scoringWeights": SCORING_WEIGHTS,
            "candidateCount": len(candidates),
            "candidateSourceKinds": sorted({source for candidate in candidates for source in candidate.get("candidateSources", [])}),
            "note": "Local relation candidates. retrievalScore is ranking only; semantic similarity is not relation evidence.",
        },
        "candidateRelations": candidates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Candidates: {len(candidates)}")
    print(f"Wikipedia extracts: {wikipedia_stats['available']}")
    print(f"Wikipedia sections: {wikipedia_stats['sections']}")
    print(f"Embedding backend: {backend}")


def build_heterogeneous_graph(
    wikidata_graph: dict[str, Any],
    curated: dict[str, Any],
) -> tuple[nx.Graph, dict[str, dict[str, Any]]]:
    graph = nx.Graph()
    curated_by_id = {person["id"]: person for person in curated.get("philosophers", [])}
    people: dict[str, dict[str, Any]] = {}

    for wd_person in wikidata_graph.get("philosophers", []):
        person_id = wd_person["id"]
        curated_person = curated_by_id.get(person_id, {})
        person_node = philosopher_node(person_id)
        person = merge_person(wd_person, curated_person)
        people[person_id] = person

        graph.add_node(person_node, kind="philosopher", label=person["name"], personId=person_id)

        for item in person["field"]:
            add_evidence_edge(graph, person_node, "field", item)
        for item in person["movement"]:
            add_evidence_edge(graph, person_node, "movement", item)
        for item in person["influencedBy"]:
            add_evidence_edge(graph, person_node, "influence", item)
        for item in person["notableWork"]:
            add_evidence_edge(graph, person_node, "work", item)
        for concept in person["coreConcepts"]:
            add_evidence_edge(graph, person_node, "concept", concept)
        for topic in person["topics"]:
            add_evidence_edge(graph, person_node, "topic", topic)
        for stance in stance_buckets(person.get("stance", {})):
            add_evidence_edge(graph, person_node, "stance", stance)

    return graph, people


def merge_person(wd_person: dict[str, Any], curated_person: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": wd_person["id"],
        "qid": wd_person.get("qid", ""),
        "name": curated_person.get("name") or wd_person.get("labelZh") or wd_person.get("labelEn") or wd_person["id"],
        "tradition": curated_person.get("tradition", ""),
        "summary": curated_person.get("summary", ""),
        "voice": curated_person.get("voice", ""),
        "coreConcepts": curated_person.get("coreConcepts", []),
        "topics": curated_person.get("topics", []),
        "stance": curated_person.get("stance", {}),
        "wikipedia": wd_person.get("wikipedia", {}),
        "wikipediaSummary": wd_person.get("wikipediaSummary", ""),
        "wikipediaExtract": wd_person.get("wikipediaExtract", ""),
        "wikidataDescription": wd_person.get("descriptionZh") or wd_person.get("descriptionEn", ""),
        "field": wd_person.get("field", []),
        "movement": wd_person.get("movement", []),
        "influencedBy": wd_person.get("influencedBy", []),
        "notableWork": wd_person.get("notableWork", []),
    }


def add_evidence_edge(graph: nx.Graph, person_node: str, kind: str, value: Any) -> None:
    label, stable_id = evidence_label_and_id(value)
    if not label or is_generic_evidence(kind, label, stable_id):
        return
    node = f"{kind}:{stable_id}"
    graph.add_node(node, kind=kind, label=label)
    graph.add_edge(person_node, node, kind=kind)


def evidence_label_and_id(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        label = value.get("labelZh") or value.get("labelEn") or value.get("qid", "")
        stable_id = value.get("qid") or slug(label)
        return str(label).strip(), str(stable_id).strip()
    label = str(value or "").strip()
    return label, slug(label)


def is_generic_evidence(kind: str, label: str, stable_id: str) -> bool:
    if kind != "field":
        return False
    return stable_id in GENERIC_EVIDENCE_IDS or label.strip().lower() in GENERIC_EVIDENCE_LABELS


def stance_buckets(stance: dict[str, Any]) -> list[str]:
    buckets = []
    for dimension, raw_value in stance.items():
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if value >= 0.42:
            buckets.append(f"{dimension}:right")
        elif value <= -0.42:
            buckets.append(f"{dimension}:left")
    return buckets


def enrich_wikipedia_extracts(
    people: dict[str, dict[str, Any]],
    cache_path: Path,
    refresh: bool = False,
    skip_fetch: bool = False,
) -> dict[str, int]:
    cache = load_wikipedia_cache(cache_path)
    extracts = cache.setdefault("extracts", cache.pop("summaries", {}))
    updated = False

    for person_id, person in people.items():
        cached = extracts.get(person_id, {})
        cached_extract = cached if isinstance(cached, str) else cached.get("extract", "")
        if cached_extract and not refresh:
            person["wikipediaSummary"] = cached_extract if isinstance(cached, str) else cached.get("summary", cached_extract)
            person["wikipediaExtract"] = cached_extract
            continue
        if person.get("wikipediaExtract") and not refresh:
            extracts[person_id] = {
                "summary": person.get("wikipediaSummary", ""),
                "extract": person["wikipediaExtract"],
                "sections": [],
                "source": "wikidata_graph",
                "sourceLangs": [],
                "fetchedAt": "",
            }
            updated = True
            continue
        if skip_fetch:
            continue

        fetched = fetch_wikipedia_extract(person.get("wikipedia", {}))
        if not fetched:
            continue
        person["wikipediaSummary"] = fetched.get("summary", "")
        person["wikipediaExtract"] = fetched["extract"]
        extracts[person_id] = fetched
        updated = True

    if updated:
        cache["metadata"] = {
            "source": "Wikipedia REST summary + MediaWiki parse sections",
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sectionTitleKeywords": SECTION_TITLE_KEYWORDS,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "available": sum(1 for person in people.values() if person.get("wikipediaExtract")),
        "sections": sum(len(extracts.get(person_id, {}).get("sections", [])) for person_id in people),
    }


def fetch_wikipedia_extract(wikipedia: dict[str, str]) -> dict[str, Any] | None:
    summaries = []
    sections = []
    source_langs = []

    for lang in ("zh", "en"):
        title = wikipedia_title(wikipedia.get(lang, ""))
        if not title:
            continue
        summary = fetch_wikipedia_page_summary(lang, title)
        if summary:
            summaries.append(summary)
            source_langs.append(lang)
        section_extracts = fetch_wikipedia_section_extracts(lang, title)
        if section_extracts:
            sections.extend(section_extracts)
            if lang not in source_langs:
                source_langs.append(lang)

        if lang == "zh" and sum(len(section["text"]) for section in sections) >= 1200:
            break

    combined = "\n\n".join(
        [item["extract"] for item in summaries[:1]]
        + [f"{section['title']}：{section['text']}" for section in sections]
    ).strip()
    if not combined:
        return None
    return {
        "summary": summaries[0]["extract"] if summaries else "",
        "extract": combined[:3200],
        "sections": sections[:8],
        "sourceLangs": source_langs,
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def fetch_wikipedia_page_summary(lang: str, title: str) -> dict[str, str] | None:
    endpoint = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title, safe='')}"
    payload = fetch_json(endpoint)
    if not payload:
        return None
    extract = str(payload.get("extract", "")).strip()
    if not extract:
        return None
    return {"title": title, "lang": lang, "extract": extract[:900], "source": endpoint}


def fetch_wikipedia_section_extracts(lang: str, title: str) -> list[dict[str, str]]:
    endpoint = (
        f"https://{lang}.wikipedia.org/w/api.php?"
        f"{urllib.parse.urlencode({'action': 'parse', 'page': title, 'prop': 'sections|text', 'format': 'json', 'formatversion': '2'})}"
    )
    payload = fetch_json(endpoint)
    if not payload:
        return []
    parse = payload.get("parse", {})
    sections = parse.get("sections", [])
    text_by_anchor = section_text_by_anchor(parse.get("text", ""))
    results = []
    for section in sections:
        title_text = str(section.get("line", "")).strip()
        anchor = str(section.get("anchor", "")).strip()
        if not is_philosophy_section_title(title_text, lang):
            continue
        text = clean_wikipedia_html(text_by_anchor.get(anchor, ""))
        if len(text) < 80:
            continue
        results.append(
            {
                "title": title_text,
                "lang": lang,
                "text": text[:1200],
                "source": endpoint,
            }
        )
    return results


def fetch_json(url: str) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            http.client.IncompleteRead,
            json.JSONDecodeError,
        ):
            time.sleep(0.6 * (attempt + 1))
    return None


def section_text_by_anchor(html: str) -> dict[str, str]:
    output = {}
    matches = list(re.finditer(r'<h[2-4][^>]*id="([^"]+)"[^>]*>', html))
    for index, match in enumerate(matches):
        anchor = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        output[anchor] = html[start:end]
    return output


def is_philosophy_section_title(title: str, lang: str) -> bool:
    lowered = title.lower()
    return any(keyword.lower() in lowered for keyword in SECTION_TITLE_KEYWORDS.get(lang, []))


def clean_wikipedia_html(html: str) -> str:
    text = re.sub(r"(?is)<style.*?</style>|<script.*?</script>|<table.*?</table>", " ", html)
    text = re.sub(r"(?is)<sup.*?</sup>", " ", text)
    text = re.sub(r"(?is)<span class=\"mw-editsection\".*?</span>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", text).strip()


def wikipedia_title(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    marker = "/wiki/"
    if marker not in parsed.path:
        return ""
    return urllib.parse.unquote(parsed.path.split(marker, 1)[1]).replace("_", " ")


def generate_candidates(
    graph: nx.Graph,
    people: dict[str, dict[str, Any]],
    existing_relations: list[dict[str, Any]],
    max_per_philosopher: int = DEFAULT_MAX_PER_PHILOSOPHER,
    min_score: float = DEFAULT_MIN_SCORE,
    embedding_backend: str = "auto",
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    relation_priors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    person_ids = sorted(people)
    similarities = text_similarities(
        [philosopher_text(people[person_id]) for person_id in person_ids],
        backend=choose_embedding_backend(embedding_backend),
        model_name=embedding_model,
    )
    index_by_id = {person_id: index for index, person_id in enumerate(person_ids)}
    existing_pairs = {pair_key(relation["source"], relation["target"]) for relation in existing_relations}
    prior_by_pair = relation_priors_by_pair(relation_priors or [], people)
    wikidata_influence_by_pair = wikidata_influences_by_pair(people)

    scored = []
    for source, target in combinations(person_ids, 2):
        pair = pair_key(source, target)
        if pair in existing_pairs:
            continue
        source_node = philosopher_node(source)
        target_node = philosopher_node(target)
        shared_nodes = shared_evidence_nodes(graph, source_node, target_node)
        graph_score = graph_proximity_score(graph, source_node, target_node, shared_nodes)
        semantic_score = float(similarities[index_by_id[source], index_by_id[target]])
        structured_evidence_score = shared_evidence_score(graph, shared_nodes)
        axis_score = problem_axis_score(graph, shared_nodes)
        axes = problem_axes(graph, shared_nodes)
        stance_hint, stance_score, stance_dimensions = stance_relation(
            people[source].get("stance", {}),
            people[target].get("stance", {}),
        )
        prior = prior_by_pair.get(pair)
        wikidata_influence = wikidata_influence_by_pair.get(pair)
        relation_evidence = relation_evidence_score(
            graph_score=graph_score,
            structured_evidence_score=structured_evidence_score,
            problem_axis_score=axis_score,
            stance_relation_score=stance_score,
        )
        retrieval_score = round(
            SCORING_WEIGHTS["semantic_recall"] * semantic_score
            + SCORING_WEIGHTS["graph_proximity"] * graph_score
            + SCORING_WEIGHTS["structured_evidence"] * structured_evidence_score
            + SCORING_WEIGHTS["problem_axis"] * axis_score
            + SCORING_WEIGHTS["stance_relation"] * stance_score,
            3,
        )
        candidate_sources, suggested_type, candidate_notes = candidate_source_hints(
            retrieval_score=retrieval_score,
            min_score=min_score,
            problem_axes=axes,
            stance_hint=stance_hint,
            stance_score=stance_score,
            stance_dimensions=stance_dimensions,
            prior=prior,
            wikidata_influence=wikidata_influence,
        )
        if not candidate_sources:
            continue
        retrieval_score = adjusted_retrieval_score(
            retrieval_score=retrieval_score,
            semantic_score=semantic_score,
            problem_axis_score=axis_score,
            stance_score=stance_score,
            prior=prior,
            wikidata_influence=wikidata_influence,
            has_stance_opposition="stance_opposition" in candidate_sources,
        )
        relation_evidence = adjusted_relation_evidence_score(relation_evidence, prior, wikidata_influence)
        output_source, output_target = candidate_output_direction(
            default_source=source,
            default_target=target,
            suggested_type=suggested_type,
            prior=prior,
            wikidata_influence=wikidata_influence,
        )

        evidence = shared_evidence(graph, shared_nodes)
        visible_type_count = evidence_type_count(graph, shared_nodes)
        quality_tier = quality_tier_for(retrieval_score, relation_evidence, visible_type_count)
        quality_tier = adjusted_quality_tier(quality_tier, relation_evidence, candidate_sources, prior)
        scored.append(
            {
                "source": output_source,
                "target": output_target,
                "suggestedType": suggested_type,
                "candidateSources": candidate_sources,
                "candidateNotes": candidate_notes,
                "qualityTier": quality_tier,
                "retrievalScore": retrieval_score,
                "relationEvidenceScore": relation_evidence,
                "semanticSimilarityScore": round(semantic_score, 3),
                "graphProximityScore": round(graph_score, 3),
                "structuredEvidenceScore": round(structured_evidence_score, 3),
                "problemAxisScore": axis_score,
                "problemAxes": axes,
                "stanceRelationHint": stance_hint,
                "sharedEvidence": evidence,
            }
        )

    scored.sort(key=lambda item: item["retrievalScore"], reverse=True)
    return cap_candidates_per_philosopher(scored, max_per_philosopher)


def candidate_source_hints(
    retrieval_score: float,
    min_score: float,
    problem_axes: list[str],
    stance_hint: str,
    stance_score: float,
    stance_dimensions: list[str],
    prior: dict[str, Any] | None,
    wikidata_influence: dict[str, Any] | None,
) -> tuple[list[str], str, list[str]]:
    sources = []
    notes = []
    suggested_type = "affinity"

    if retrieval_score >= min_score:
        sources.append("shared_evidence")
        notes.append("shared_evidence: local graph and embedding retrieval score passed threshold")

    if is_stance_opposition_candidate(problem_axes, stance_hint, stance_score):
        sources.append("stance_opposition")
        suggested_type = "tension"
        dimensions = ", ".join(stance_dimensions[:4])
        notes.append(f"stance_opposition: opposed stance dimensions {dimensions}")

    if prior:
        sources.append("relation_prior")
        suggested_type = prior["suggestedType"]
        notes.append(f"relation_prior: {prior['reason']}")

    if wikidata_influence:
        sources.append("wikidata_influenced_by")
        if suggested_type != "influence":
            notes.append(f"wikidata_influenced_by_type_note: suggested type changed from {suggested_type} to influence")
        suggested_type = "influence"
        notes.append(f"wikidata_influenced_by: {wikidata_influence['reason']}")

    return dedupe_list(sources), suggested_type, dedupe_list(notes)


def is_stance_opposition_candidate(problem_axes: list[str], stance_hint: str, stance_score: float) -> bool:
    return bool(problem_axes) and stance_hint == "same_problem_opposed_positions" and stance_score >= STANCE_OPPOSITION_MIN_SCORE


def adjusted_retrieval_score(
    retrieval_score: float,
    semantic_score: float,
    problem_axis_score: float,
    stance_score: float,
    prior: dict[str, Any] | None,
    wikidata_influence: dict[str, Any] | None,
    has_stance_opposition: bool,
) -> float:
    score = retrieval_score
    if has_stance_opposition:
        stance_retrieval = round(
            max(
                STANCE_TENSION_RETRIEVAL_FLOOR,
                0.56 * stance_score + 0.28 * problem_axis_score + 0.16 * semantic_score,
            ),
            3,
        )
        score = max(score, stance_retrieval)
    if prior:
        score = max(score, clamp_float(prior.get("retrievalFloor", RELATION_PRIOR_RETRIEVAL_FLOOR), 0, 1))
    if wikidata_influence:
        score = max(
            score,
            clamp_float(wikidata_influence.get("retrievalFloor", WIKIDATA_INFLUENCE_RETRIEVAL_FLOOR), 0, 1),
        )
    return round(score, 3)


def adjusted_relation_evidence_score(
    score: float,
    prior: dict[str, Any] | None,
    wikidata_influence: dict[str, Any] | None,
) -> float:
    if prior:
        score = max(score, clamp_float(prior.get("confidence", 0.78), 0, 1))
    if wikidata_influence:
        score = max(score, clamp_float(wikidata_influence.get("confidence", WIKIDATA_INFLUENCE_CONFIDENCE), 0, 1))
    return round(score, 3)


def adjusted_quality_tier(
    quality_tier: str,
    relation_evidence_score: float,
    candidate_sources: list[str],
    prior: dict[str, Any] | None,
) -> str:
    if prior and clamp_float(prior.get("confidence", 0.78), 0, 1) >= 0.82:
        return "strong_candidate"
    if "relation_prior" in candidate_sources or "stance_opposition" in candidate_sources:
        if quality_tier == "weak_candidate" and relation_evidence_score >= 0.38:
            return "medium_candidate"
    if "wikidata_influenced_by" in candidate_sources and relation_evidence_score >= 0.70:
        return "strong_candidate"
    return quality_tier


def candidate_output_direction(
    default_source: str,
    default_target: str,
    suggested_type: str,
    prior: dict[str, Any] | None,
    wikidata_influence: dict[str, Any] | None,
) -> tuple[str, str]:
    if suggested_type == "influence" and wikidata_influence:
        return wikidata_influence["source"], wikidata_influence["target"]
    if suggested_type == "influence" and prior and prior.get("suggestedType") == "influence":
        return prior["source"], prior["target"]
    return default_source, default_target


def text_similarities(texts: list[str], backend: str, model_name: str) -> np.ndarray:
    if backend == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError("sentence-transformers is not installed. Use --embedding-backend tfidf.") from error
        model = SentenceTransformer(model_name)
        vectors = model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors) @ np.asarray(vectors).T

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=False)
    vectors = vectorizer.fit_transform(texts)
    return cosine_similarity(vectors)


def choose_embedding_backend(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return "tfidf"
    return "sentence-transformers"


def philosopher_text(person: dict[str, Any]) -> str:
    pieces = [
        person.get("name", ""),
        person.get("tradition", ""),
        person.get("wikidataDescription", ""),
        person.get("summary", ""),
        person.get("wikipediaSummary", ""),
        person.get("wikipediaExtract", ""),
        person.get("voice", ""),
        repeat_text(" ".join(person.get("coreConcepts", [])), 4),
        repeat_text(labels_text(person.get("movement", []), "movement"), 3),
        repeat_text(labels_text(person.get("field", []), "field"), 3),
        repeat_text(labels_text(person.get("influencedBy", []), "influence"), 2),
        labels_text(person.get("notableWork", []), "work"),
        " ".join(person.get("topics", [])),
    ]
    return " ".join(piece for piece in pieces if piece).strip()


def labels_text(items: list[Any], kind: str = "") -> str:
    labels = []
    for item in items:
        label, stable_id = evidence_label_and_id(item)
        if label and not is_generic_evidence(kind, label, stable_id):
            labels.append(label)
    return " ".join(labels)


def repeat_text(text: str, times: int) -> str:
    return " ".join([text] * times) if text else ""


def graph_proximity_score(graph: nx.Graph, source_node: str, target_node: str, shared_nodes: set[str]) -> float:
    source_neighbors = evidence_neighbors(graph, source_node)
    target_neighbors = evidence_neighbors(graph, target_node)
    union = source_neighbors | target_neighbors
    if not union:
        return 0.0

    shared_weight = sum(evidence_weight(graph, node) for node in shared_nodes)
    union_weight = sum(evidence_weight(graph, node) for node in union)
    jaccard = shared_weight / union_weight if union_weight else 0
    adamic_adar = sum(evidence_weight(graph, node) / math.log(graph.degree(node) + 1) for node in shared_nodes)
    resource_allocation = sum(evidence_weight(graph, node) / graph.degree(node) for node in shared_nodes)
    return round(
        0.5 * jaccard
        + 0.25 * bounded(adamic_adar)
        + 0.25 * bounded(resource_allocation),
        3,
    )


def shared_evidence_score(graph: nx.Graph, shared_nodes: set[str]) -> float:
    if not shared_nodes:
        return 0.0
    visible_nodes = displayable_evidence_nodes(graph, shared_nodes)
    if not visible_nodes:
        return 0.0
    kinds = {graph.nodes[node].get("kind", "") for node in visible_nodes}
    weight_sum = sum(evidence_weight(graph, node) for node in visible_nodes)
    return round(min(1.0, 0.68 * bounded(weight_sum / 3) + 0.32 * (len(kinds) / 5)), 3)


def problem_axis_score(graph: nx.Graph, shared_nodes: set[str]) -> float:
    nodes = problem_axis_nodes(graph, shared_nodes)
    if not nodes:
        return 0.0
    kinds = {graph.nodes[node].get("kind", "") for node in nodes}
    weight_sum = sum(evidence_weight(graph, node) for node in nodes)
    return round(min(1.0, 0.72 * bounded(weight_sum / 2.4) + 0.28 * (len(kinds) / 5)), 3)


def problem_axes(graph: nx.Graph, shared_nodes: set[str], limit: int = 6) -> list[str]:
    return [graph.nodes[node].get("label", node) for node in problem_axis_nodes(graph, shared_nodes)[:limit]]


def problem_axis_nodes(graph: nx.Graph, shared_nodes: set[str]) -> list[str]:
    nodes = []
    for node in displayable_evidence_nodes(graph, shared_nodes):
        kind = graph.nodes[node].get("kind", "")
        label = str(graph.nodes[node].get("label", "")).strip()
        if kind not in PROBLEM_AXIS_KINDS:
            continue
        if kind == "topic" and label in BROAD_TOPIC_LABELS:
            continue
        nodes.append(node)

    def sort_key(node: str) -> tuple[int, float, str]:
        priority = {"concept": 0, "movement": 1, "field": 2, "influence": 3, "work": 4, "topic": 5}
        kind = graph.nodes[node].get("kind", "")
        label = graph.nodes[node].get("label", node)
        return priority.get(kind, 99), -evidence_weight(graph, node), label

    return sorted(nodes, key=sort_key)


def stance_relation(
    source_stance: dict[str, Any],
    target_stance: dict[str, Any],
) -> tuple[str, float, list[str]]:
    aligned = []
    opposed = []
    for dimension in sorted(set(source_stance) & set(target_stance)):
        try:
            source_value = float(source_stance[dimension])
            target_value = float(target_stance[dimension])
        except (TypeError, ValueError):
            continue
        if abs(source_value) < 0.42 or abs(target_value) < 0.42:
            continue
        if source_value * target_value < 0:
            opposed.append(f"{dimension}:opposed")
        else:
            aligned.append(f"{dimension}:aligned")

    if opposed:
        return "same_problem_opposed_positions", round(min(1.0, 0.5 + 0.16 * len(opposed)), 3), opposed
    if aligned:
        return "same_problem_aligned_positions", round(min(1.0, 0.38 + 0.14 * len(aligned)), 3), aligned
    return "no_clear_stance_signal", 0.0, []


def relation_evidence_score(
    graph_score: float,
    structured_evidence_score: float,
    problem_axis_score: float,
    stance_relation_score: float,
) -> float:
    non_semantic_total = 1 - SCORING_WEIGHTS["semantic_recall"]
    score = (
        SCORING_WEIGHTS["graph_proximity"] * graph_score
        + SCORING_WEIGHTS["structured_evidence"] * structured_evidence_score
        + SCORING_WEIGHTS["problem_axis"] * problem_axis_score
        + SCORING_WEIGHTS["stance_relation"] * stance_relation_score
    ) / non_semantic_total
    return round(score, 3)


def evidence_type_count(graph: nx.Graph, shared_nodes: set[str]) -> int:
    return len({graph.nodes[node].get("kind", "") for node in displayable_evidence_nodes(graph, shared_nodes)})


def shared_evidence(graph: nx.Graph, shared_nodes: set[str], limit: int = 8) -> list[str]:
    def sort_key(node: str) -> tuple[int, str]:
        priority = {"concept": 0, "movement": 1, "field": 2, "influence": 3, "work": 4, "topic": 5}
        kind = graph.nodes[node].get("kind", "")
        label = graph.nodes[node].get("label", node)
        return priority.get(kind, 99), -evidence_weight(graph, node), label

    nodes = displayable_evidence_nodes(graph, shared_nodes)
    return [graph.nodes[node].get("label", node) for node in sorted(nodes, key=sort_key)[:limit]]


def displayable_evidence_nodes(graph: nx.Graph, nodes: set[str]) -> list[str]:
    return [node for node in nodes if graph.nodes[node].get("kind") != "stance"]


def evidence_weight(graph: nx.Graph, node: str) -> float:
    kind = graph.nodes[node].get("kind", "")
    label = str(graph.nodes[node].get("label", "")).strip()
    base = EVIDENCE_KIND_WEIGHTS.get(kind, 0.4)
    if kind == "topic" and label in BROAD_TOPIC_LABELS:
        return 0.06
    return base


def quality_tier_for(retrieval_score: float, relation_evidence_score: float, visible_type_count: int) -> str:
    if relation_evidence_score >= 0.58 and visible_type_count >= 2:
        return "strong_candidate"
    if relation_evidence_score >= 0.46 or (retrieval_score >= 0.52 and relation_evidence_score >= 0.40):
        return "medium_candidate"
    return "weak_candidate"


def relation_reason(
    relation_type: str,
    evidence: list[str],
    relation_evidence_score: float,
    semantic_score: float,
    graph_score: float,
) -> str:
    evidence_text = "、".join(evidence[:4]) if evidence else "非语义证据较弱"
    label = "亲缘关系" if relation_type == "affinity_candidate" else "相关关系"
    return (
        f"本地召回信号：二者共享 {evidence_text} 等证据，"
        f"关系证据分 {relation_evidence_score:.2f}、图接近度 {graph_score:.2f}；"
        f"embedding 只作召回，文本相似度 {semantic_score:.2f} 不能作为{label}成立证据。"
    )


def cap_candidates_per_philosopher(candidates: list[dict[str, Any]], max_per_philosopher: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    output = []
    for candidate in candidates:
        source = candidate["source"]
        target = candidate["target"]
        candidate_sources = candidate.get("candidateSources", [])
        is_forced_candidate = "relation_prior" in candidate_sources or "wikidata_influenced_by" in candidate_sources
        if (
            not is_forced_candidate
            and (counts.get(source, 0) >= max_per_philosopher or counts.get(target, 0) >= max_per_philosopher)
        ):
            continue
        counts[source] = counts.get(source, 0) + 1
        counts[target] = counts.get(target, 0) + 1
        output.append(candidate)
    return output


def shared_evidence_nodes(graph: nx.Graph, source_node: str, target_node: str) -> set[str]:
    return evidence_neighbors(graph, source_node) & evidence_neighbors(graph, target_node)


def evidence_neighbors(graph: nx.Graph, node: str) -> set[str]:
    return {neighbor for neighbor in graph.neighbors(node) if graph.nodes[neighbor].get("kind") != "philosopher"}


def philosopher_node(person_id: str) -> str:
    return f"philosopher:{person_id}"


def pair_key(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted([source, target]))


def wikidata_influences_by_pair(people: dict[str, dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    qid_to_person_id = {
        str(person.get("qid", "")).strip(): person_id
        for person_id, person in people.items()
        if person.get("qid")
    }
    output = {}
    for target_id, target_person in people.items():
        for item in target_person.get("influencedBy", []):
            source_id = local_person_id_for_wikidata_item(item, qid_to_person_id)
            if not source_id or source_id == target_id:
                continue
            pair = pair_key(source_id, target_id)
            source_name = people[source_id].get("name", source_id)
            target_name = target_person.get("name", target_id)
            signal = {
                "source": source_id,
                "target": target_id,
                "suggestedType": "influence",
                "reason": f"Wikidata P737: {target_name} influenced by {source_name}; mapped as {source_name} -> {target_name}.",
                "confidence": WIKIDATA_INFLUENCE_CONFIDENCE,
                "retrievalFloor": WIKIDATA_INFLUENCE_RETRIEVAL_FLOOR,
            }
            existing = output.get(pair)
            if existing and (existing["source"], existing["target"]) != (source_id, target_id):
                existing["reason"] = f"{existing['reason']} Direction conflict also found: {signal['reason']}"
                existing["directionConflict"] = True
                continue
            output[pair] = signal
    return output


def local_person_id_for_wikidata_item(item: Any, qid_to_person_id: dict[str, str]) -> str:
    if not isinstance(item, dict):
        return ""
    qid = str(item.get("qid", "")).strip()
    return qid_to_person_id.get(qid, "")


def relation_priors_by_pair(
    relation_priors: list[dict[str, Any]],
    people: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    people_ids = set(people)
    output = {}
    for prior in relation_priors:
        source = safe_id(prior.get("source", ""))
        target = safe_id(prior.get("target", ""))
        if source not in people_ids or target not in people_ids or source == target:
            continue
        output[pair_key(source, target)] = {
            "source": source,
            "target": target,
            "suggestedType": safe_suggested_type(prior.get("suggestedType", "")),
            "reason": safe_note(prior.get("reason", "")),
            "confidence": clamp_float(prior.get("confidence", 0.82), 0, 1),
            "retrievalFloor": clamp_float(prior.get("retrievalFloor", RELATION_PRIOR_RETRIEVAL_FLOOR), 0, 1),
        }
    return output


def load_relation_priors(path: Path, philosopher_ids: set[str] | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = read_json(path)
    raw_priors = data.get("relations", data if isinstance(data, list) else [])
    output = []
    for prior in raw_priors:
        if not isinstance(prior, dict):
            continue
        source = safe_id(prior.get("source", ""))
        target = safe_id(prior.get("target", ""))
        if not source or not target or source == target:
            continue
        if philosopher_ids and (source not in philosopher_ids or target not in philosopher_ids):
            continue
        reason = safe_note(prior.get("reason", ""))
        if not reason:
            continue
        output.append(
            {
                "source": source,
                "target": target,
                "suggestedType": safe_suggested_type(prior.get("suggestedType", "")),
                "reason": reason,
                "confidence": clamp_float(prior.get("confidence", 0.82), 0, 1),
                "retrievalFloor": clamp_float(prior.get("retrievalFloor", RELATION_PRIOR_RETRIEVAL_FLOOR), 0, 1),
            }
        )
    return output


def safe_suggested_type(value: Any) -> str:
    suggested_type = str(value or "").strip()
    return suggested_type if suggested_type in ALLOWED_SUGGESTED_TYPES else "affinity"


def safe_id(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", str(value or "").strip())


def safe_note(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:280]


def dedupe_list(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", text)
    return text or "unknown"


def load_curated_data(data_js_path: Path) -> dict[str, Any]:
    node = find_node()
    if not node:
        print("Warning: node not found; using Wikidata-only cards.", flush=True)
        return {"philosophers": [], "relations": []}

    code = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({json.dumps(str(data_js_path))}, 'utf8');
const sandbox = {{ window: {{}} }};
vm.createContext(sandbox);
vm.runInContext(code, sandbox, {{ filename: 'data.js' }});
console.log(JSON.stringify(sandbox.window.PHILOSOPHANY_DATA));
"""
    result = subprocess.run([node, "-e", code], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def find_node() -> str:
    candidates = [
        os.environ.get("NODE"),
        "node",
        "/Applications/Codex.app/Contents/Resources/node",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            subprocess.run([candidate, "--version"], capture_output=True, text=True, check=True)
            return candidate
        except (OSError, subprocess.CalledProcessError):
            continue
    return ""


def bounded(value: float) -> float:
    return 1 - math.exp(-value)


def clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, round(number, 3)))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_wikipedia_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"metadata": {}, "extracts": {}}
    data = read_json(path)
    if "extracts" in data or "summaries" in data:
        return data
    return {"metadata": {}, "extracts": data}


def cached_wikipedia_extract_count(path: Path) -> int:
    if not path.exists():
        return 0
    cache = load_wikipedia_cache(path)
    values = cache.get("extracts", cache.get("summaries", {}))
    return sum(1 for value in values.values() if value)


if __name__ == "__main__":
    main()
