import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DuelDebatePageTest(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_frontend_has_duel_page_and_controls(self):
        index_html = self.read("index.html")
        app_js = self.read("app.js")
        styles_css = self.read("styles.css")

        self.assertIn('data-view="duel"', index_html)
        self.assertIn('id="duelView"', index_html)
        self.assertIn('id="duelMiniGraph"', index_html)
        self.assertIn('id="duelFirstSelect"', index_html)
        self.assertIn('id="duelSecondSelect"', index_html)
        self.assertIn('id="generateDebateAnglesButton"', index_html)
        self.assertIn('id="debateAngleList"', index_html)
        self.assertIn('id="startDuelButton"', index_html)
        self.assertIn('id="duelConversation"', index_html)
        self.assertIn('id="duelForm"', index_html)

        self.assertIn("function renderDuel", app_js)
        self.assertIn("function renderDuelMiniGraph", app_js)
        self.assertIn("function selectDuelPhilosopher", app_js)
        self.assertIn("function generateDebateAngles", app_js)
        self.assertIn("function startDuelDebate", app_js)
        self.assertIn("function generateNextDuelTurn", app_js)
        self.assertIn("function callDebateAnglesProxy", app_js)
        self.assertIn("function callDebateTurnProxy", app_js)
        self.assertIn("function generateLocalDebateAngles", app_js)
        self.assertIn("function generateLocalDebateTurn", app_js)

        self.assertIn(".duel-layout", styles_css)
        self.assertIn(".duel-mini-graph", styles_css)
        self.assertIn(".debate-angle-card", styles_css)
        self.assertIn(".duelist-card", styles_css)

    def test_backend_has_duel_routes_and_prompt_contract(self):
        server_js = self.read("server.js")

        self.assertIn('url.pathname === "/api/debate-angles"', server_js)
        self.assertIn('url.pathname === "/api/debate-turn"', server_js)
        self.assertIn("async function handleDebateAngles", server_js)
        self.assertIn("async function handleDebateTurn", server_js)
        self.assertIn("function buildDebateAnglesPrompt", server_js)
        self.assertIn("function buildDebateTurnPrompt", server_js)
        self.assertIn("function sanitizeDebateContext", server_js)
        self.assertIn("只推荐 3 个张力角度", server_js)
        self.assertIn("辩论不是圆桌缩小版", server_js)
        self.assertIn("每次只生成一位哲学家的发言", server_js)
        self.assertIn("不要伪造具体名言", server_js)
        self.assertIn("response_format: { type: \"json_object\" }", server_js)
        self.assertIn("thinking: { type: \"disabled\" }", server_js)

    def test_duel_uses_existing_graph_relation_and_stance_inputs(self):
        app_js = self.read("app.js")
        server_js = self.read("server.js")

        self.assertIn("duelRelationsForPair", app_js)
        self.assertIn("duelStanceDifferences", app_js)
        self.assertIn("strongestDuelOpponents", app_js)
        self.assertIn("relation.type === \"tension\"", app_js)
        self.assertIn("stanceDifferences", server_js)
        self.assertIn("pairRelations", server_js)

    def test_duel_uses_distinct_debate_voice_guardrails(self):
        data_js = self.read("data.js")
        reviewed_cards = self.read("data/generated/reviewed_philosopher_cards.json")
        app_js = self.read("app.js")
        server_js = self.read("server.js")

        self.assertEqual(data_js.count('"debateVoiceGuardrails"'), 13)
        self.assertEqual(reviewed_cards.count('"debateVoiceGuardrails"'), 13)
        self.assertIn("庄子：少线性论证", data_js)
        self.assertIn("孔子：短、端正、具体关系场景", data_js)
        self.assertIn("debateVoiceGuardrails: person.debateVoiceGuardrails", app_js)
        self.assertIn("debateVoiceGuardrails: sanitizeDebateVoiceGuardrails", server_js)
        self.assertIn("sanitizeDebateVoiceGuardrails", server_js)
        self.assertIn("风格分离协议", server_js)
        self.assertIn("sampleLines 只用于模仿语气", server_js)
        self.assertIn("不要让所有哲学家共享", server_js)


if __name__ == "__main__":
    unittest.main()
