import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
SERVER_JS = ROOT / "server.js"
INDEX_HTML = ROOT / "index.html"
ROUNDTABLE_DOC = ROOT / "docs" / "roundtable-method.md"


class IncrementalOpeningRoundTest(unittest.TestCase):
    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_frontend_tracks_one_opening_speaker_at_a_time(self):
        app_js = self.read(APP_JS)

        self.assertIn("openingTurnIndex: 0", app_js)
        self.assertIn("function nextOpeningSpeaker", app_js)
        self.assertIn("function advanceOpeningTurn", app_js)
        self.assertIn("function generateLocalOpeningStep", app_js)
        self.assertIn('action: "opening_step"', app_js)
        self.assertRegex(app_js, r"currentSpeakerId:\s*nextSpeaker\.id")
        self.assertRegex(app_js, r"afterMessages:\s*\(\)\s*=>\s*advanceOpeningTurn\(nextSpeaker\.id\)")
        self.assertNotIn("generateLocalOpeningRound(participants)", app_js)

    def test_backend_opening_step_allows_only_current_speaker(self):
        server_js = self.read(SERVER_JS)

        self.assertIn('"opening_step"', server_js)
        self.assertRegex(
            server_js,
            r'if\s*\(context\.action\s*===\s*"opening_step"\s*&&\s*context\.currentSpeakerId\)\s*return\s*\[context\.currentSpeakerId\]',
        )
        self.assertIn("任务：生成第一轮中的下一位发言。", server_js)
        self.assertIn("只生成这位哲学家的 1 条发言", server_js)
        self.assertIn("如果这是第一位发言者", server_js)
        self.assertIn("必须回应已经可见的某个具体观点", server_js)

    def test_button_copy_reflects_incremental_opening(self):
        index_html = self.read(INDEX_HTML)
        app_js = self.read(APP_JS)
        doc = self.read(ROUNDTABLE_DOC)

        self.assertIn("下一位", index_html)
        self.assertIn("renderOpeningControl", app_js)
        self.assertIn("下一位发言", app_js)
        self.assertIn("用户点“下一位”", doc)
        self.assertIn("不是一次性生成五条发言", doc)


if __name__ == "__main__":
    unittest.main()
