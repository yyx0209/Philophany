import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_local_graph_candidates import build_prompt, build_review_output, chunked, parse_model_json


class ReviewLocalGraphCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {
                "source": "socrates",
                "target": "kant",
                "retrievalScore": 0.51,
                "qualityTier": "medium_candidate",
                "sharedEvidence": ["伦理学", "知识论"],
            },
            {
                "source": "confucius",
                "target": "wittgenstein",
                "retrievalScore": 0.27,
                "qualityTier": "weak_candidate",
                "sharedEvidence": ["道德"],
            },
            {
                "source": "plato",
                "target": "sartre",
                "retrievalScore": 0.4,
                "qualityTier": "weak_candidate",
                "sharedEvidence": ["意义"],
            },
        ]
        self.philosopher_ids = {"socrates", "kant", "confucius", "wittgenstein", "plato", "sartre"}
        self.existing_relations = [{"source": "plato", "target": "sartre", "type": "tension"}]

    def test_parse_model_json_accepts_markdown_wrapped_json(self):
        parsed = parse_model_json('```json\n{"reviews": []}\n```')

        self.assertEqual({"reviews": []}, parsed)

    def test_chunked_splits_candidates_for_reliable_llm_review(self):
        self.assertEqual([[1, 2], [3, 4], [5]], list(chunked([1, 2, 3, 4, 5], 2)))

    def test_build_prompt_marks_embedding_as_retrieval_only(self):
        candidates = [
            {
                "source": "socrates",
                "target": "kant",
                "suggestedType": "tension",
                "candidateSources": ["stance_opposition", "relation_prior"],
                "retrievalScore": 0.51,
                "relationEvidenceScore": 0.58,
                "qualityTier": "medium_candidate",
                "semanticSimilarityScore": 0.82,
                "graphProximityScore": 0.44,
                "structuredEvidenceScore": 0.61,
                "problemAxisScore": 0.7,
                "problemAxes": ["伦理学", "知识论"],
                "stanceRelationHint": "same_problem_aligned_positions",
                "sharedEvidence": ["伦理学", "知识论"],
            }
        ]
        cards = [
            {"id": "socrates", "name": "苏格拉底", "coreConcepts": ["德性"], "summary": "追问德性。"},
            {"id": "kant", "name": "康德", "coreConcepts": ["义务"], "summary": "讨论道德法则。"},
        ]

        messages = build_prompt(candidates=candidates, cards=cards, existing_relations=[])
        prompt_text = "\n".join(message["content"] for message in messages)

        self.assertIn("semanticSimilarityScore 只能作为召回信号", prompt_text)
        self.assertIn("retrieval_signal_only", prompt_text)
        self.assertIn("relationEvidenceScore", prompt_text)
        self.assertIn("problemAxes", prompt_text)
        self.assertIn("suggestedType", prompt_text)
        self.assertIn("candidateSources", prompt_text)
        self.assertIn("stance_opposition", prompt_text)
        self.assertIn("同属传统", prompt_text)

    def test_build_review_output_sanitizes_decisions_and_keeps_rejections(self):
        model_reviews = [
            {
                "source": "socrates",
                "target": "kant",
                "decision": "accept",
                "proposedRelation": {
                    "type": "affinity",
                    "weight": 0.57,
                    "reason": "二者都把伦理学问题推向主体能否为自己的理由负责。",
                },
                "confidence": 0.72,
                "llmReason": "共享伦理学和知识论问题，但不是直接影响关系。",
                "evidenceBasis": ["coreConcepts", "field", "wikipediaExtract"],
            },
            {
                "source": "confucius",
                "target": "wittgenstein",
                "decision": "reject",
                "confidence": 0.81,
                "llmReason": "只有宽泛的道德词重合，缺少可解释的共同问题结构。",
                "evidenceBasis": ["localEvidence"],
            },
            {
                "source": "plato",
                "target": "sartre",
                "decision": "revise",
                "proposedRelation": {
                    "type": "tension",
                    "weight": 0.62,
                    "reason": "柏拉图的理念论与萨特的存在先于本质形成清晰张力。",
                },
                "confidence": 0.78,
                "llmReason": "模型提出了合理关系，但该 pair 已经存在于正式图谱，应被拒绝合并。",
                "evidenceBasis": ["summary"],
            },
            {
                "source": "fake",
                "target": "kant",
                "decision": "accept",
                "proposedRelation": {"type": "affinity", "weight": 0.5, "reason": "bad"},
            },
            {
                "source": "socrates",
                "target": "kant",
                "decision": "accept",
                "proposedRelation": {"type": "critiques", "weight": 0.5, "reason": "bad"},
            },
        ]

        output = build_review_output(
            candidates=self.candidates,
            model_reviews=model_reviews,
            philosopher_ids=self.philosopher_ids,
            existing_relations=self.existing_relations,
            input_file="data/generated/local_graph_candidates.json",
            model="test-model",
        )

        self.assertEqual("OpenRouter local candidate review", output["metadata"]["source"])
        self.assertEqual(3, output["metadata"]["candidateCount"])
        self.assertEqual(1, output["metadata"]["acceptedCount"])
        self.assertTrue(output["metadata"]["needsHumanConfirmation"])
        self.assertEqual(3, len(output["reviews"]))

        accepted = output["reviews"][0]
        self.assertEqual("accept", accepted["decision"])
        self.assertEqual("affinity", accepted["proposedRelation"]["type"])
        self.assertEqual("pending", accepted["humanDecision"])

        rejected = output["reviews"][1]
        self.assertEqual("reject", rejected["decision"])
        self.assertIsNone(rejected["proposedRelation"])
        self.assertIn("宽泛", rejected["llmReason"])

        duplicate_pair = output["reviews"][2]
        self.assertEqual("reject", duplicate_pair["decision"])
        self.assertIsNone(duplicate_pair["proposedRelation"])
        self.assertIn("正式图谱", duplicate_pair["llmReason"])


if __name__ == "__main__":
    unittest.main()
