import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_example_styles import build_prompt, build_review_output
from merge_example_styles import approved_example_styles_from_reviews, merge_approved_example_styles


class ExampleStylePipelineTest(unittest.TestCase):
    def test_prompt_requests_example_style_schema_and_review_output(self):
        cards = [
            {
                "id": "socrates",
                "name": "苏格拉底",
                "tradition": "苏格拉底式追问",
                "coreConcepts": ["自知无知", "苏格拉底式诘问"],
                "topics": ["道德", "知识"],
                "voice": "温和、讽刺、执着追问。",
                "summary": "苏格拉底从日常判断追问定义。",
            }
        ]

        messages = build_prompt(cards)
        prompt_text = "\n".join(message["content"] for message in messages)

        self.assertIn("exampleStyle", prompt_text)
        self.assertIn("preferredExampleForms", prompt_text)
        self.assertIn("signatureExample", prompt_text)
        self.assertIn("如果上一条发言包含具体例子", prompt_text)
        self.assertIn("同一个例子给出不同结论", prompt_text)
        self.assertIn("例子不能替代论证", prompt_text)

    def test_review_output_defaults_to_pending_and_sanitizes_example_style(self):
        cards = [{"id": "kant", "name": "康德", "voice": "严谨。"}]
        output = build_review_output(
            cards=cards,
            model_styles=[
                {
                    "id": "kant",
                    "exampleStyle": {
                        "mode": "principle_test",
                        "frequency": "low",
                        "canDebateOnExample": True,
                        "preferredExampleForms": ["准则测试", "义务与利益冲突的小情境", "会被裁掉"],
                        "avoidExampleForms": ["把例子当作直觉裁判", "编造历史轶事", "会被裁掉"],
                        "signatureExample": "用承诺或撒谎的小情境测试准则能否普遍化。",
                    },
                    "llmReason": "康德适合少量准则测试。",
                }
            ],
            input_file="cards.json",
            model="openai/gpt-5.5",
        )

        self.assertTrue(output["metadata"]["needsHumanConfirmation"])
        self.assertEqual("pending", output["reviews"][0]["humanDecision"])
        style = output["reviews"][0]["proposedExampleStyle"]
        self.assertEqual("principle_test", style["mode"])
        self.assertEqual("low", style["frequency"])
        self.assertEqual(["准则测试", "义务与利益冲突的小情境"], style["preferredExampleForms"])
        self.assertEqual(["把例子当作直觉裁判", "编造历史轶事"], style["avoidExampleForms"])

    def test_only_approved_example_styles_merge_into_cards(self):
        cards = [
            {"id": "socrates", "name": "苏格拉底", "voice": "追问。"},
            {"id": "kant", "name": "康德", "voice": "严谨。"},
        ]
        reviewed = {
            "reviews": [
                {
                    "id": "socrates",
                    "humanDecision": "approve",
                    "proposedExampleStyle": {
                        "mode": "dialogue_situation",
                        "frequency": "high",
                        "canDebateOnExample": True,
                        "preferredExampleForms": ["两个人争论正义的小对话"],
                        "avoidExampleForms": ["长篇寓言"],
                        "signatureExample": "用小对话追问定义。",
                    },
                },
                {
                    "id": "kant",
                    "humanDecision": "pending",
                    "proposedExampleStyle": {
                        "mode": "principle_test",
                        "frequency": "low",
                        "canDebateOnExample": True,
                        "preferredExampleForms": ["准则测试"],
                        "avoidExampleForms": ["直觉裁判"],
                        "signatureExample": "测试准则。",
                    },
                },
            ]
        }

        styles, skipped = approved_example_styles_from_reviews(reviewed, philosopher_ids={"socrates", "kant"})
        merged = merge_approved_example_styles(cards, styles)

        self.assertIn("exampleStyle", merged[0])
        self.assertNotIn("exampleStyle", merged[1])
        self.assertEqual("not approved", skipped[0]["reason"])

    def test_merge_script_round_trip_writes_json_cards(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "out.json"
            card = {"id": "zhuangzi", "name": "庄子", "voice": "飘逸。"}
            reviewed = {
                "reviews": [
                    {
                        "id": "zhuangzi",
                        "humanDecision": "approve",
                        "proposedExampleStyle": {
                            "mode": "parable",
                            "frequency": "high",
                            "canDebateOnExample": True,
                            "preferredExampleForms": ["动物、工匠或梦境的短寓言"],
                            "avoidExampleForms": ["故作玄虚"],
                            "signatureExample": "用轻巧故事松动成败尺度。",
                        },
                    }
                ]
            }

            styles, _ = approved_example_styles_from_reviews(reviewed, {"zhuangzi"})
            merged = merge_approved_example_styles(card, styles)

            output_path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("parable", payload["exampleStyle"]["mode"])


if __name__ == "__main__":
    unittest.main()
