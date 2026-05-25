import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_local_graph_candidates import (
    DEFAULT_CARDS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MAX_PER_PHILOSOPHER,
    DEFAULT_MIN_SCORE,
    DEFAULT_WIKIDATA_GRAPH,
    SCORING_WEIGHTS,
    build_heterogeneous_graph,
    generate_candidates,
    load_wikipedia_cache,
    philosopher_text,
    read_json,
)
from graph_data_io import load_card_bundle


class LocalGraphCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.wikidata_graph = {
            "philosophers": [
                {
                    "id": "a",
                    "labelZh": "甲",
                    "descriptionZh": "重视德性与实践的哲学家",
                    "wikipediaSummary": "甲的维基百科摘要强调德性伦理、实践智慧和人的成全。",
                    "wikipediaExtract": "甲的思想段落讨论目的论、德性伦理和实践智慧。",
                    "field": [{"qid": "Q1", "labelZh": "伦理学", "labelEn": "ethics"}],
                    "movement": [{"qid": "Q2", "labelZh": "德性伦理", "labelEn": "virtue ethics"}],
                    "influencedBy": [{"qid": "Q5", "labelZh": "共同老师", "labelEn": "shared teacher"}],
                    "notableWork": [{"qid": "Q6", "labelZh": "共同著作", "labelEn": "shared work"}],
                },
                {
                    "id": "b",
                    "labelZh": "乙",
                    "descriptionZh": "讨论修养、实践和德性的思想家",
                    "field": [{"qid": "Q1", "labelZh": "伦理学", "labelEn": "ethics"}],
                    "movement": [{"qid": "Q2", "labelZh": "德性伦理", "labelEn": "virtue ethics"}],
                    "influencedBy": [{"qid": "Q5", "labelZh": "共同老师", "labelEn": "shared teacher"}],
                    "notableWork": [{"qid": "Q6", "labelZh": "共同著作", "labelEn": "shared work"}],
                },
                {
                    "id": "c",
                    "labelZh": "丙",
                    "descriptionZh": "关注语言和命题意义的哲学家",
                    "field": [{"qid": "Q4", "labelZh": "语言哲学", "labelEn": "philosophy of language"}],
                    "movement": [],
                    "influencedBy": [],
                    "notableWork": [],
                },
            ]
        }
        self.curated = {
            "philosophers": [
                {
                    "id": "a",
                    "name": "甲",
                    "summary": "甲认为幸福来自德性与实践智慧。",
                    "coreConcepts": ["德性", "实践智慧"],
                    "topics": ["幸福", "道德"],
                    "stance": {"reasonInstinct": 0.8, "moralUniversalism": 0.7},
                },
                {
                    "id": "b",
                    "name": "乙",
                    "summary": "乙强调修养、行动与德性。",
                    "coreConcepts": ["德性", "修养"],
                    "topics": ["幸福", "道德"],
                    "stance": {"reasonInstinct": 0.75, "moralUniversalism": 0.66},
                },
                {
                    "id": "c",
                    "name": "丙",
                    "summary": "丙分析语言、命题和意义。",
                    "coreConcepts": ["语言", "意义"],
                    "topics": ["真理"],
                },
            ],
            "relations": [],
        }

    def test_builds_heterogeneous_graph_with_shared_evidence_nodes(self):
        graph, people = build_heterogeneous_graph(self.wikidata_graph, self.curated)

        self.assertEqual({"a", "b", "c"}, set(people))
        self.assertTrue(graph.has_edge("philosopher:a", "field:Q1"))
        self.assertTrue(graph.has_edge("philosopher:b", "field:Q1"))
        self.assertTrue(graph.has_edge("philosopher:a", "concept:德性"))
        self.assertTrue(graph.has_edge("philosopher:b", "topic:幸福"))

    def test_philosopher_text_includes_curated_and_wikidata_fields(self):
        _, people = build_heterogeneous_graph(self.wikidata_graph, self.curated)
        text = philosopher_text(people["a"])

        self.assertIn("甲", text)
        self.assertIn("德性", text)
        self.assertIn("伦理学", text)
        self.assertIn("实践智慧", text)
        self.assertIn("维基百科摘要", text)
        self.assertIn("思想段落", text)

    def test_load_wikipedia_cache_preserves_new_extracts_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "wikipedia_philosophy_extracts.json"
            path.write_text(
                json.dumps(
                    {
                        "metadata": {"source": "test"},
                        "extracts": {
                            "a": {
                                "summary": "summary",
                                "extract": "思想段落",
                                "sections": [{"title": "思想", "text": "思想段落"}],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cache = load_wikipedia_cache(path)

            self.assertIn("extracts", cache)
            self.assertEqual("思想段落", cache["extracts"]["a"]["extract"])

    def test_generates_ranked_review_only_candidates_without_duplicates(self):
        graph, people = build_heterogeneous_graph(self.wikidata_graph, self.curated)
        candidates = generate_candidates(
            graph,
            people,
            existing_relations=[],
            max_per_philosopher=2,
            min_score=0.1,
            embedding_backend="tfidf",
        )

        pairs = {tuple(sorted([item["source"], item["target"]])) for item in candidates}
        self.assertEqual(len(pairs), len(candidates))
        self.assertTrue(
            all(item["qualityTier"] in {"strong_candidate", "medium_candidate", "weak_candidate"} for item in candidates)
        )
        self.assertTrue(all(item["source"] != item["target"] for item in candidates))
        self.assertEqual(("a", "b"), tuple(sorted([candidates[0]["source"], candidates[0]["target"]])))
        self.assertEqual("affinity", candidates[0]["suggestedType"])
        self.assertIn("shared_evidence", candidates[0]["candidateSources"])
        self.assertEqual(
            {
                "source",
                "target",
                "suggestedType",
                "candidateSources",
                "candidateNotes",
                "qualityTier",
                "retrievalScore",
                "relationEvidenceScore",
                "semanticSimilarityScore",
                "graphProximityScore",
                "structuredEvidenceScore",
                "problemAxisScore",
                "problemAxes",
                "stanceRelationHint",
                "sharedEvidence",
            },
            set(candidates[0]),
        )
        self.assertGreater(candidates[0]["retrievalScore"], 0.1)
        self.assertGreaterEqual(len(candidates[0]["sharedEvidence"]), 2)
        self.assertFalse(any(":" in evidence for evidence in candidates[0]["sharedEvidence"]))
        self.assertIn("relationEvidenceScore", candidates[0])
        self.assertIn("problemAxisScore", candidates[0])
        self.assertIn("problemAxes", candidates[0])
        self.assertIn("stanceRelationHint", candidates[0])
        self.assertIn("伦理学", candidates[0]["problemAxes"])
        self.assertIn("共同老师", candidates[0]["sharedEvidence"])
        self.assertIn("共同著作", candidates[0]["sharedEvidence"])
        self.assertNotIn("德性伦理", candidates[0]["problemAxes"])
        self.assertNotIn("共同老师", candidates[0]["problemAxes"])
        self.assertNotIn("共同著作", candidates[0]["problemAxes"])
        self.assertLess(
            candidates[0]["sharedEvidence"].index("伦理学"),
            candidates[0]["sharedEvidence"].index("幸福"),
        )

    def test_stance_opposition_is_an_independent_tension_candidate_source(self):
        curated = {
            "philosophers": [
                {
                    "id": "a",
                    "name": "甲",
                    "summary": "甲强调礼法秩序与共同体修养。",
                    "coreConcepts": ["礼"],
                    "topics": ["政治"],
                    "stance": {"individualCollective": -0.75, "moralUniversalism": 0.72},
                },
                {
                    "id": "c",
                    "name": "丙",
                    "summary": "丙强调逍遥、自然与反固定规范。",
                    "coreConcepts": ["逍遥"],
                    "topics": ["政治"],
                    "stance": {"individualCollective": 0.72, "moralUniversalism": -0.75},
                },
            ],
            "relations": [],
        }
        graph, people = build_heterogeneous_graph(self.wikidata_graph, curated)

        candidates = generate_candidates(
            graph,
            people,
            existing_relations=[],
            max_per_philosopher=10,
            min_score=0.9,
            embedding_backend="tfidf",
        )
        candidate = next(item for item in candidates if tuple(sorted([item["source"], item["target"]])) == ("a", "c"))

        self.assertEqual("tension", candidate["suggestedType"])
        self.assertIn("stance_opposition", candidate["candidateSources"])
        self.assertEqual("same_problem_opposed_positions", candidate["stanceRelationHint"])
        self.assertIn("政治", candidate["problemAxes"])

    def test_relation_priors_force_canonical_pairs_into_review_pool(self):
        graph, people = build_heterogeneous_graph(self.wikidata_graph, self.curated)

        candidates = generate_candidates(
            graph,
            people,
            existing_relations=[],
            max_per_philosopher=10,
            min_score=0.99,
            embedding_backend="tfidf",
            relation_priors=[
                {
                    "source": "a",
                    "target": "c",
                    "suggestedType": "tension",
                    "reason": "甲的德性实践与丙的语言分析在哲学方法上形成张力。",
                }
            ],
        )
        candidate = next(item for item in candidates if tuple(sorted([item["source"], item["target"]])) == ("a", "c"))

        self.assertEqual("tension", candidate["suggestedType"])
        self.assertIn("relation_prior", candidate["candidateSources"])
        self.assertGreaterEqual(candidate["retrievalScore"], 0.72)

    def test_wikidata_influenced_by_preserves_directed_influence_candidate(self):
        wikidata_graph = {
            "philosophers": [
                {
                    "id": "socrates",
                    "qid": "Q913",
                    "labelZh": "苏格拉底",
                    "descriptionZh": "古希腊哲学家",
                    "field": [],
                    "movement": [],
                    "influencedBy": [],
                    "notableWork": [],
                },
                {
                    "id": "plato",
                    "qid": "Q859",
                    "labelZh": "柏拉图",
                    "descriptionZh": "古希腊哲学家",
                    "field": [],
                    "movement": [],
                    "influencedBy": [{"qid": "Q913", "labelZh": "苏格拉底", "labelEn": "Socrates"}],
                    "notableWork": [],
                },
            ]
        }
        curated = {
            "philosophers": [
                {"id": "socrates", "name": "苏格拉底", "summary": "苏格拉底使用诘问法讨论德性。"},
                {"id": "plato", "name": "柏拉图", "summary": "柏拉图以对话形式展开理念论。"},
            ],
            "relations": [],
        }
        graph, people = build_heterogeneous_graph(wikidata_graph, curated)

        candidates = generate_candidates(
            graph,
            people,
            existing_relations=[],
            max_per_philosopher=10,
            min_score=0.99,
            embedding_backend="tfidf",
        )

        matches = [item for item in candidates if {item["source"], item["target"]} == {"socrates", "plato"}]
        self.assertEqual(1, len(matches))
        candidate = matches[0]
        self.assertEqual("socrates", candidate["source"])
        self.assertEqual("plato", candidate["target"])
        self.assertEqual("influence", candidate["suggestedType"])
        self.assertIn("wikidata_influenced_by", candidate["candidateSources"])

    def test_scoring_weights_demote_semantic_similarity_to_recall_signal(self):
        self.assertAlmostEqual(1.0, sum(SCORING_WEIGHTS.values()))
        self.assertLessEqual(SCORING_WEIGHTS["semantic_recall"], 0.15)
        self.assertGreater(SCORING_WEIGHTS["structured_evidence"], SCORING_WEIGHTS["semantic_recall"])
        self.assertGreater(SCORING_WEIGHTS["graph_proximity"], SCORING_WEIGHTS["semantic_recall"])

    def test_default_recall_threshold_and_real_negative_pair_guardrail(self):
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            self.skipTest("sentence-transformers is not installed")

        self.assertEqual(0.34, DEFAULT_MIN_SCORE)
        self.assertEqual(6, DEFAULT_MAX_PER_PHILOSOPHER)
        self.assertEqual("BAAI/bge-m3", DEFAULT_EMBEDDING_MODEL)

        graph, people = build_heterogeneous_graph(read_json(DEFAULT_WIKIDATA_GRAPH), load_card_bundle(DEFAULT_CARDS))
        all_pairs = generate_candidates(
            graph,
            people,
            existing_relations=[],
            max_per_philosopher=100,
            min_score=0.0,
            embedding_backend="sentence-transformers",
        )
        negative_pairs = [
            ("confucius", "wittgenstein"),
            ("buddha", "wittgenstein"),
            ("zhuangzi", "wittgenstein"),
            ("aristotle", "wittgenstein"),
            ("buddha", "kant"),
            ("confucius", "hume"),
            ("zhuangzi", "hume"),
        ]
        score_by_pair = {tuple(sorted([item["source"], item["target"]])): item["retrievalScore"] for item in all_pairs}
        for source, target in negative_pairs:
            with self.subTest(source=source, target=target):
                self.assertLess(score_by_pair[tuple(sorted([source, target]))], DEFAULT_MIN_SCORE)

        recall_pool = generate_candidates(
            graph,
            people,
            existing_relations=[],
            max_per_philosopher=DEFAULT_MAX_PER_PHILOSOPHER,
            min_score=DEFAULT_MIN_SCORE,
            embedding_backend="sentence-transformers",
        )
        stricter_pool = generate_candidates(
            graph,
            people,
            existing_relations=[],
            max_per_philosopher=DEFAULT_MAX_PER_PHILOSOPHER,
            min_score=0.4,
            embedding_backend="sentence-transformers",
        )
        recall_pairs = {tuple(sorted([item["source"], item["target"]])) for item in recall_pool}
        counts = {}
        for item in recall_pool:
            counts[item["source"]] = counts.get(item["source"], 0) + 1
            counts[item["target"]] = counts.get(item["target"], 0) + 1

        for source, target in negative_pairs:
            with self.subTest(source=source, target=target):
                self.assertNotIn(tuple(sorted([source, target])), recall_pairs)
        self.assertGreater(len(recall_pool), len(stricter_pool))
        self.assertTrue(all(count <= DEFAULT_MAX_PER_PHILOSOPHER for count in counts.values()))


if __name__ == "__main__":
    unittest.main()
