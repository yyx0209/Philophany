import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
SERVER_JS = ROOT / "server.js"
ROUNDTABLE_DOC = ROOT / "docs" / "roundtable-method.md"


class DynamicRoundtableSchedulerTest(unittest.TestCase):
    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_frontend_uses_llm_scheduler_with_sequential_rollback(self):
        app_js = self.read(APP_JS)

        self.assertIn('const DEFAULT_ROUND_SCHEDULER_MODE = "llm"', app_js)
        self.assertIn('const ROUND_SCHEDULER_STORAGE_KEY = "philophany.roundScheduler"', app_js)
        self.assertIn("function getRoundSchedulerMode", app_js)
        self.assertIn('saved === "sequential"', app_js)
        self.assertIn("async function callNextSpeakerScheduler", app_js)
        self.assertIn('fetch("/api/next-speaker"', app_js)
        self.assertIn("async function generateDynamicRoundStep", app_js)
        self.assertIn("function createDynamicInterventionRound", app_js)
        self.assertIn("function createInterventionRound", app_js)
        self.assertIn("LLM 调度失败，已切回原顺序", app_js)

    def test_backend_exposes_next_speaker_scheduler_prompt(self):
        server_js = self.read(SERVER_JS)

        self.assertIn('url.pathname === "/api/next-speaker"', server_js)
        self.assertIn("async function handleNextSpeaker", server_js)
        self.assertIn("function buildNextSpeakerPrompt", server_js)
        self.assertIn("function sanitizeNextSpeakerDecision", server_js)
        self.assertIn("发言紧迫度", server_js)
        self.assertIn("沉默补偿", server_js)
        self.assertIn("最近发言惩罚", server_js)
        self.assertIn("只决定下一位发言者，不生成圆桌发言", server_js)

    def test_docs_describe_dynamic_scheduler_and_rollback(self):
        doc = self.read(ROUNDTABLE_DOC)

        self.assertIn("LLM 动态调度", doc)
        self.assertIn("philophany.roundScheduler", doc)
        self.assertIn("sequential", doc)
        self.assertIn("回退", doc)

    def test_dynamic_round_shows_immediate_scheduler_feedback(self):
        app_js = self.read(APP_JS)

        self.assertIn("function updateSystemMessage", app_js)
        self.assertIn("下一位...", app_js)
        self.assertIn("${nextSpeaker.name}正在发言", app_js)
        self.assertIn("loadingMessageId: schedulerLoading.id", app_js)
        self.assertNotIn("动态圆桌开始：LLM 会根据上一条发言", app_js)
        self.assertNotIn("function addDynamicStartMessageIfNeeded", app_js)

    def test_dynamic_round_reveals_speaker_text_incrementally(self):
        app_js = self.read(APP_JS)

        self.assertIn("function wait", app_js)
        self.assertIn("async function revealMessageText", app_js)
        self.assertIn("streamLike = false", app_js)
        self.assertIn("await revealMessageText", app_js)

    def test_user_can_return_from_followup_to_main_question(self):
        app_js = self.read(APP_JS)
        index_html = self.read(ROOT / "index.html")
        doc = self.read(ROUNDTABLE_DOC)

        self.assertIn('id="returnToMainButton"', index_html)
        self.assertIn("回到原问题", index_html)
        self.assertIn("function returnToMainQuestion", app_js)
        self.assertIn("state.interventionRound = null", app_js)
        self.assertIn("function renderReturnToMainControl", app_js)
        self.assertIn("button.hidden = !state.interventionRound", app_js)
        self.assertIn("returnToMainQuestion", app_js)
        self.assertIn("回到原问题", doc)
        self.assertIn("非点名追问", doc)
        self.assertIn("shouldContinue: false", doc)

    def test_discussion_state_refresh_does_not_block_next_button(self):
        app_js = self.read(APP_JS)

        self.assertIn("function scheduleDiscussionStateRefresh", app_js)
        self.assertIn("scheduleDiscussionStateRefresh();", app_js)
        self.assertNotIn("await refreshDiscussionState();", app_js)

    def test_frontend_user_copy_does_not_name_provider(self):
        app_js = self.read(APP_JS)

        forbidden_visible_copy = [
            "正在通过 OpenRouter",
            "后端代理已连接 OpenRouter",
            "OpenRouter 解析失败",
            "OpenRouter ·",
        ]
        for copy in forbidden_visible_copy:
            self.assertNotIn(copy, app_js)


if __name__ == "__main__":
    unittest.main()
