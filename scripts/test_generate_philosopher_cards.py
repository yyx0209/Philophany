import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_philosopher_cards import build_source_cards, sanitize_card_candidates


class GeneratePhilosopherCardsTest(unittest.TestCase):
    def test_build_source_cards_combines_wikidata_and_wikipedia_extracts(self):
        wikidata_graph = {
            "philosophers": [
                {
                    "id": "socrates",
                    "labelZh": "苏格拉底",
                    "labelEn": "Socrates",
                    "descriptionZh": "古希腊哲学家",
                    "movement": [],
                    "field": [{"labelZh": "伦理学"}],
                    "influencedBy": [{"labelZh": "前苏格拉底哲学"}],
                    "notableWork": [],
                }
            ]
        }
        wikipedia_cache = {
            "extracts": {
                "socrates": {
                    "summary": "苏格拉底是古希腊哲学家。",
                    "extract": "哲學信仰：苏格拉底强调追问、德性与灵魂照料。",
                }
            }
        }

        cards = build_source_cards(wikidata_graph, wikipedia_cache)

        self.assertEqual("socrates", cards[0]["id"])
        self.assertEqual("苏格拉底", cards[0]["labelZh"])
        self.assertIn("伦理学", cards[0]["field"])
        self.assertIn("追问", cards[0]["wikipediaExtract"])

    def test_sanitize_card_candidates_keeps_valid_cards_pending_human_review(self):
        raw_cards = [
            {
                "id": "socrates",
                "name": "苏格拉底",
                "era": "古希腊",
                "tradition": "古希腊哲学",
                "color": "blue",
                "coreConcepts": ["追问", "德性"],
                "topics": ["真理", "道德"],
                "stance": {"reasonInstinct": 2, "moralUniversalism": "0.6", "bad": "x"},
                "voice": "追问定义。",
                "summary": "苏格拉底把哲学变成生活中的追问。",
                "opening": "你说的成功是什么？",
                "questionHooks": ["定义是什么？"],
                "evidenceBasis": ["wikidata", "wikipediaExtract"],
            },
            {"id": "fake", "name": "Fake"},
        ]

        output = sanitize_card_candidates(raw_cards, source_ids={"socrates"})

        self.assertEqual(1, len(output))
        card = output[0]
        self.assertEqual("socrates", card["id"])
        self.assertEqual(1.0, card["stance"]["reasonInstinct"])
        self.assertEqual(0.6, card["stance"]["moralUniversalism"])
        self.assertNotIn("bad", card["stance"])
        self.assertTrue(card["needsReview"])
        self.assertEqual("pending", card["humanDecision"])


if __name__ == "__main__":
    unittest.main()
