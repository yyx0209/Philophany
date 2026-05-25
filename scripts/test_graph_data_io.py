import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_data_io import approved_relations_from_reviews, load_card_bundle, load_existing_relations, normalize_card


class GraphDataIOTest(unittest.TestCase):
    def test_load_card_bundle_reads_json_cards_without_data_js(self):
        payload = {
            "cards": [
                {
                    "id": "socrates",
                    "name": "苏格拉底",
                    "coreConcepts": ["追问"],
                    "topics": ["真理"],
                    "humanDecision": "approve",
                },
                {
                    "id": "plato",
                    "name": "柏拉图",
                    "coreConcepts": ["理念"],
                    "topics": ["真理"],
                    "humanDecision": "pending",
                },
            ],
            "relations": [
                {
                    "source": "socrates",
                    "target": "plato",
                    "type": "influence",
                    "weight": 0.92,
                    "reason": "柏拉图的哲学写作以苏格拉底式追问为核心入口。",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reviewed_philosopher_cards.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            bundle = load_card_bundle(path)

            self.assertEqual(["socrates"], [person["id"] for person in bundle["philosophers"]])
            self.assertEqual(payload["relations"], bundle["relations"])

    def test_load_card_bundle_keeps_unmarked_seed_cards(self):
        payload = {
            "philosophers": [
                {"id": "socrates", "name": "苏格拉底"},
                {"id": "plato", "name": "柏拉图"},
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reviewed_philosopher_cards.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            bundle = load_card_bundle(path)

            self.assertEqual(["socrates", "plato"], [person["id"] for person in bundle["philosophers"]])

    def test_load_existing_relations_reads_only_human_approved_reviews(self):
        reviewed = {
            "reviews": [
                {
                    "source": "socrates",
                    "target": "plato",
                    "humanDecision": "approve",
                    "proposedRelation": {
                        "type": "influence",
                        "weight": 0.9,
                        "reason": "柏拉图的哲学写作以苏格拉底式追问为核心入口。",
                    },
                },
                {
                    "source": "kant",
                    "target": "sartre",
                    "humanDecision": "pending",
                    "proposedRelation": {
                        "type": "tension",
                        "weight": 0.8,
                        "reason": "pending should not load",
                    },
                },
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reviewed_graph_relations.json"
            path.write_text(json.dumps(reviewed, ensure_ascii=False), encoding="utf-8")

            relations = load_existing_relations(path)

            self.assertEqual(
                [
                    {
                        "source": "socrates",
                        "target": "plato",
                        "type": "influence",
                        "weight": 0.9,
                        "reason": "柏拉图的哲学写作以苏格拉底式追问为核心入口。",
                    }
                ],
                relations,
            )

    def test_approved_relations_from_reviews_rejects_invalid_types(self):
        relations, skipped = approved_relations_from_reviews(
            {
                "reviews": [
                    {
                        "source": "socrates",
                        "target": "kant",
                        "humanDecision": "approve",
                        "proposedRelation": {
                            "type": "critiques",
                            "weight": 0.8,
                            "reason": "unsupported",
                        },
                    }
                ]
            },
            philosopher_ids={"socrates", "kant"},
        )

        self.assertEqual([], relations)
        self.assertEqual("unsupported relation type", skipped[0]["reason"])

    def test_normalize_card_preserves_speech_persona(self):
        card = normalize_card(
            {
                "id": "nietzsche",
                "name": "尼采",
                "voice": "锋利。",
                "speechPersona": {
                    "temperament": "挑衅、骄傲、厌恶软弱的安慰。",
                    "favoriteMoves": ["挑衅", "反问", "翻译成人话", "无效动作"],
                    "responseToDisagreement": "遇到道德化反驳时会升级攻势。",
                    "sentenceRhythm": "短句、格言式、有冲击力。",
                    "overheatRisk": "容易把复杂问题压成强弱二分。",
                    "sampleLines": ["你先问问这是不是你的欲望。", "别急着把怯懦叫作美德。", "第三句会被裁掉。"],
                },
            }
        )

        self.assertEqual("挑衅、骄傲、厌恶软弱的安慰。", card["speechPersona"]["temperament"])
        self.assertEqual(["挑衅", "反问", "翻译成人话"], card["speechPersona"]["favoriteMoves"])
        self.assertEqual(["你先问问这是不是你的欲望。", "别急着把怯懦叫作美德。"], card["speechPersona"]["sampleLines"])

    def test_normalize_card_preserves_example_style(self):
        card = normalize_card(
            {
                "id": "kant",
                "name": "康德",
                "voice": "严谨。",
                "exampleStyle": {
                    "mode": "principle_test",
                    "frequency": "low",
                    "canDebateOnExample": True,
                    "preferredExampleForms": ["准则测试", "义务与利益冲突的小情境", "会被裁掉"],
                    "avoidExampleForms": ["把例子当作直觉裁判", "编造历史轶事", "会被裁掉"],
                    "signatureExample": "用承诺、撒谎、利用他人的小情境测试准则能否普遍化。",
                },
            }
        )

        self.assertEqual("principle_test", card["exampleStyle"]["mode"])
        self.assertEqual("low", card["exampleStyle"]["frequency"])
        self.assertTrue(card["exampleStyle"]["canDebateOnExample"])
        self.assertEqual(["准则测试", "义务与利益冲突的小情境"], card["exampleStyle"]["preferredExampleForms"])
        self.assertEqual(["把例子当作直觉裁判", "编造历史轶事"], card["exampleStyle"]["avoidExampleForms"])


if __name__ == "__main__":
    unittest.main()
