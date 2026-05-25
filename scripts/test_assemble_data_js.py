import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from assemble_data_js import build_data_js, collect_topics


class AssembleDataJsTest(unittest.TestCase):
    def test_collect_topics_preserves_defaults_and_adds_card_topics(self):
        topics = collect_topics(
            [
                {"id": "a", "topics": ["自由", "语言"]},
                {"id": "b", "topics": ["政治", "自由"]},
            ]
        )

        self.assertIn("成功", topics)
        self.assertIn("语言", topics)
        self.assertIn("政治", topics)
        self.assertEqual(1, topics.count("自由"))

    def test_build_data_js_outputs_browser_bundle_without_reading_existing_data_js(self):
        cards = [
            {
                "id": "socrates",
                "name": "苏格拉底",
                "era": "古希腊",
                "tradition": "古希腊哲学",
                "color": "blue",
                "coreConcepts": ["追问"],
                "topics": ["真理"],
                "stance": {"reasonInstinct": 0.7},
                "voice": "追问定义。",
                "summary": "苏格拉底通过追问审视生活。",
                "opening": "你说的成功是什么？",
                "questionHooks": ["定义是什么？"],
            }
        ]
        relations = [
            {
                "source": "socrates",
                "target": "plato",
                "type": "influence",
                "weight": 0.92,
                "reason": "柏拉图的哲学写作以苏格拉底式追问为核心入口。",
            }
        ]

        output = build_data_js(cards, relations)

        self.assertIn("window.PHILOSOPHANY_DATA = ", output)
        self.assertIn('"socrates"', output)
        self.assertIn('"dimensions"', output)
        self.assertIn('"relations"', output)
        self.assertTrue(output.endswith(";\n"))

    def test_build_data_js_preserves_speech_persona(self):
        output = build_data_js(
            [
                {
                    "id": "nietzsche",
                    "name": "尼采",
                    "topics": ["道德"],
                    "speechPersona": {
                        "temperament": "挑衅。",
                        "favoriteMoves": ["挑衅", "反问"],
                        "responseToDisagreement": "升级攻势。",
                        "sentenceRhythm": "短句。",
                        "overheatRisk": "容易二分。",
                        "sampleLines": ["别急着把怯懦叫作美德。"],
                    },
                }
            ],
            [],
        )

        payload = json.loads(output.removeprefix("window.PHILOSOPHANY_DATA = ").removesuffix(";\n"))
        self.assertEqual("挑衅。", payload["philosophers"][0]["speechPersona"]["temperament"])


if __name__ == "__main__":
    unittest.main()
