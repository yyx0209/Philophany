import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_JS = ROOT / "server.js"
APP_JS = ROOT / "app.js"
ROUNDTABLE_DOC = ROOT / "docs" / "roundtable-method.md"


class DiscussionStateTrackerTest(unittest.TestCase):
    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_backend_route_and_prompt_exist(self):
        server_js = self.read(SERVER_JS)

        self.assertIn('url.pathname === "/api/discussion-state"', server_js)
        self.assertIn("async function handleDiscussionState", server_js)
        self.assertIn("function buildDiscussionStatePrompt", server_js)
        self.assertIn("function sanitizeDiscussionState", server_js)

        self.assertIn("claimsOnTable", server_js)
        self.assertIn("unresolvedTensions", server_js)
        self.assertIn("unquestionedAssumptions", server_js)
        self.assertIn("drift", server_js)

        self.assertIn('"unanswered"', server_js)
        self.assertIn('"challenged"', server_js)
        self.assertIn('"clarified"', server_js)
        self.assertIn('"repeated"', server_js)
        self.assertIn('"none"', server_js)
        self.assertIn('"mild"', server_js)
        self.assertIn('"serious"', server_js)

    def test_discussion_state_has_no_next_best_move_contract(self):
        server_js = self.read(SERVER_JS)
        app_js = self.read(APP_JS)
        doc = self.read(ROUNDTABLE_DOC)

        self.assertNotIn('"nextBestMove"', server_js)
        self.assertNotIn('"nextBestMove"', app_js)
        self.assertIn("不生成 nextBestMove", server_js)
        self.assertIn("不使用 nextBestMove", doc)

    def test_frontend_keeps_state_internal_and_sends_it_to_backend(self):
        app_js = self.read(APP_JS)

        self.assertIn("discussionState: createEmptyDiscussionState()", app_js)
        self.assertIn("function createEmptyDiscussionState", app_js)
        self.assertIn("function normalizeDiscussionState", app_js)
        self.assertIn("async function refreshDiscussionState", app_js)
        self.assertIn('fetch("/api/discussion-state"', app_js)
        self.assertRegex(app_js, r"discussionState:\s*state\.discussionState")

        visible_labels = [
            "讨论状态",
            "未解决张力",
            "未被追问的前提",
            "跑题程度",
        ]
        for label in visible_labels:
            self.assertNotIn(label, app_js)

    def test_chat_prompt_receives_discussion_state_as_background_notes(self):
        server_js = self.read(SERVER_JS)

        self.assertRegex(server_js, r"discussionState:\s*sanitizeDiscussionState")
        self.assertIn("后台讨论状态", server_js)
        self.assertIn("只作为背景笔记", server_js)
        self.assertIn("不得把它当成下一步发言指令", server_js)


if __name__ == "__main__":
    unittest.main()
