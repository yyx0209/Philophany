import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QuestionAnalysisStyleTest(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_summary_prompt_uses_natural_question_understanding_wording(self):
        server_js = self.read("server.js")
        docs = self.read("docs/roundtable-method.md")

        for source in (server_js, docs):
            self.assertNotIn("卡在哪里", source)
            self.assertNotIn("真正卡", source)

        self.assertIn("summary：一句话表达你对这个问题的理解", server_js)
        self.assertIn("避免使用“不是……而是……”", server_js)
        self.assertIn("`summary`：一句话说明系统对问题的理解", docs)

    def test_ui_labels_question_analysis_as_understanding(self):
        app_js = self.read("app.js")

        self.assertNotIn("问题解析", app_js)
        self.assertIn("问题理解", app_js)


if __name__ == "__main__":
    unittest.main()
