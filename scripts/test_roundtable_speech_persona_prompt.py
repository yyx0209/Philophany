import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
SERVER_JS = ROOT / "server.js"
ROUNDTABLE_DOC = ROOT / "docs" / "roundtable-method.md"


class RoundtableSpeechPersonaPromptTest(unittest.TestCase):
    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_frontend_sends_speech_persona_to_backend(self):
        app_js = self.read(APP_JS)

        self.assertIn("speechPersona: person.speechPersona", app_js)
        self.assertIn("exampleStyle: person.exampleStyle", app_js)

    def test_backend_sanitizes_and_prompts_speech_persona(self):
        server_js = self.read(SERVER_JS)

        self.assertIn("function sanitizeSpeechPersona", server_js)
        self.assertIn("speechPersona: sanitizeSpeechPersona", server_js)
        self.assertIn("发言人格", server_js)
        self.assertIn("打断、反问、拒答、重框、挑衅、缓和、翻译成人话", server_js)
        self.assertIn("可以锋利，但不能人身攻击用户", server_js)
        self.assertIn("可以拒绝问题，但必须给出更好的问法", server_js)
        self.assertIn("可以打断别人，但不能歪曲别人", server_js)
        self.assertIn("function sanitizeExampleStyle", server_js)
        self.assertIn("exampleStyle: sanitizeExampleStyle", server_js)
        self.assertIn("例子协议", server_js)
        self.assertIn("如果上一条发言包含具体例子", server_js)
        self.assertIn("同一个例子给出不同结论", server_js)
        self.assertIn("例子不能替代论证", server_js)

    def test_docs_describe_speech_persona_review_step(self):
        doc = self.read(ROUNDTABLE_DOC)

        self.assertIn("speechPersona", doc)
        self.assertIn("人工审核", doc)
        self.assertIn("打断、反问、拒答、重框、挑衅、缓和、翻译成人话", doc)
        self.assertIn("exampleStyle", doc)
        self.assertIn("例子协议", doc)
        self.assertIn("同一个例子给出不同结论", doc)


if __name__ == "__main__":
    unittest.main()
