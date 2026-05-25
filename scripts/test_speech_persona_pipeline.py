import json
import tempfile
import unittest
from pathlib import Path

from generate_speech_personas import build_prompt, build_review_output
from merge_speech_personas import approved_personas_from_reviews, merge_approved_personas


class SpeechPersonaPipelineTest(unittest.TestCase):
    def test_prompt_requests_dialogue_persona_schema_and_human_review_output(self):
        cards = [
            {
                "id": "nietzsche",
                "name": "尼采",
                "tradition": "谱系学与价值重估",
                "coreConcepts": ["权力意志", "价值重估"],
                "topics": ["道德", "欲望"],
                "voice": "锋利、挑衅、格言式。",
                "summary": "尼采追问道德背后的生命力量。",
            }
        ]

        messages = build_prompt(cards)
        prompt_text = "\n".join(message["content"] for message in messages)

        self.assertIn("speechPersona", prompt_text)
        self.assertIn("temperament", prompt_text)
        self.assertIn("favoriteMoves", prompt_text)
        self.assertIn("打断", prompt_text)
        self.assertIn("反问", prompt_text)
        self.assertIn("拒答", prompt_text)
        self.assertIn("可以锋利，但不能人身攻击用户", prompt_text)
        self.assertIn("不能歪曲别人", prompt_text)

    def test_review_output_defaults_to_pending_and_sanitizes_persona(self):
        cards = [{"id": "nietzsche", "name": "尼采", "voice": "锋利。"}]
        output = build_review_output(
            cards=cards,
            model_personas=[
                {
                    "id": "nietzsche",
                    "speechPersona": {
                        "temperament": "挑衅。",
                        "favoriteMoves": ["挑衅", "反问", "无效"],
                        "responseToDisagreement": "更强硬。",
                        "sentenceRhythm": "短句。",
                        "overheatRisk": "容易过火。",
                        "sampleLines": ["第一句。", "第二句。", "第三句。"],
                    },
                    "llmReason": "尼采需要锋利的价值翻转。",
                }
            ],
            input_file="cards.json",
            model="openai/gpt-5.5",
        )

        self.assertTrue(output["metadata"]["needsHumanConfirmation"])
        self.assertEqual("pending", output["reviews"][0]["humanDecision"])
        persona = output["reviews"][0]["proposedSpeechPersona"]
        self.assertEqual(["挑衅", "反问"], persona["favoriteMoves"])
        self.assertEqual(["第一句。", "第二句。"], persona["sampleLines"])

    def test_only_approved_personas_merge_into_cards(self):
        cards = [
            {"id": "nietzsche", "name": "尼采", "voice": "锋利。"},
            {"id": "kant", "name": "康德", "voice": "严谨。"},
        ]
        reviewed = {
            "reviews": [
                {
                    "id": "nietzsche",
                    "humanDecision": "approve",
                    "proposedSpeechPersona": {
                        "temperament": "挑衅。",
                        "favoriteMoves": ["挑衅"],
                        "responseToDisagreement": "升级攻势。",
                        "sentenceRhythm": "短句。",
                        "overheatRisk": "容易二分。",
                        "sampleLines": ["你先问问这是不是你的欲望。"],
                    },
                },
                {
                    "id": "kant",
                    "humanDecision": "pending",
                    "proposedSpeechPersona": {
                        "temperament": "严谨。",
                        "favoriteMoves": ["重框"],
                        "responseToDisagreement": "划清概念。",
                        "sentenceRhythm": "长句。",
                        "overheatRisk": "过于枯燥。",
                        "sampleLines": ["先问准则。"],
                    },
                },
            ]
        }

        personas, skipped = approved_personas_from_reviews(reviewed, philosopher_ids={"nietzsche", "kant"})
        merged = merge_approved_personas(cards, personas)

        self.assertIn("speechPersona", merged[0])
        self.assertNotIn("speechPersona", merged[1])
        self.assertEqual("not approved", skipped[0]["reason"])

    def test_merge_script_round_trip_writes_json_cards(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cards_path = Path(temp_dir) / "cards.json"
            review_path = Path(temp_dir) / "reviewed_speech_personas.json"
            output_path = Path(temp_dir) / "out.json"
            cards_path.write_text(
                json.dumps({"reviews": [{"humanDecision": "approve", "card": {"id": "zhuangzi", "name": "庄子", "voice": "飘逸。"}}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            review_path.write_text(
                json.dumps(
                    {
                        "reviews": [
                            {
                                "id": "zhuangzi",
                                "humanDecision": "approve",
                                "proposedSpeechPersona": {
                                    "temperament": "飘逸、反讽。",
                                    "favoriteMoves": ["重框", "拒答"],
                                    "responseToDisagreement": "换掉问题尺度。",
                                    "sentenceRhythm": "轻快、寓言式。",
                                    "overheatRisk": "容易说得太玄。",
                                    "sampleLines": ["你先别急着把自己钉在这个问题上。"],
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            personas, _ = approved_personas_from_reviews(json.loads(review_path.read_text(encoding="utf-8")), {"zhuangzi"})
            merged = merge_approved_personas(json.loads(cards_path.read_text(encoding="utf-8"))["reviews"][0]["card"], personas)

            output_path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("飘逸、反讽。", payload["speechPersona"]["temperament"])


if __name__ == "__main__":
    unittest.main()
