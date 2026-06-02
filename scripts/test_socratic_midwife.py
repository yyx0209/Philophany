import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SocraticMidwifeTest(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_frontend_has_socratic_page_and_controls(self):
        index_html = self.read("index.html")
        app_js = self.read("app.js")
        styles_css = self.read("styles.css")

        self.assertIn('data-view="socratic"', index_html)
        self.assertIn('id="socraticView"', index_html)
        self.assertIn('id="socraticQuestionInput"', index_html)
        self.assertIn('id="socraticStateBoard"', index_html)
        self.assertIn("function startSocraticDialogue", app_js)
        self.assertIn("function respondToSocratic", app_js)
        self.assertIn("function renderSocraticStateBoard", app_js)
        self.assertIn(".socratic-layout", styles_css)
        self.assertIn(".socratic-state-panel", styles_css)

    def test_backend_route_and_prompt_exist(self):
        server_js = self.read("server.js")

        self.assertIn('url.pathname === "/api/socratic-chat"', server_js)
        self.assertIn("async function handleSocraticChat", server_js)
        self.assertIn("function buildSocraticPrompt", server_js)
        self.assertIn("function sanitizeSocraticState", server_js)
        self.assertIn("每次只推进一个清楚问题", server_js)
        self.assertIn("不要伪造苏格拉底、柏拉图", server_js)
        self.assertIn("用户问“你觉得呢”", server_js)
        self.assertIn("临时判断", server_js)

    def test_socratic_state_contract_is_structured(self):
        server_js = self.read("server.js")
        app_js = self.read("app.js")

        for key in (
            "originalQuestion",
            "currentUnderstanding",
            "keyTerms",
            "clarifiedTerms",
            "userClaims",
            "assumptions",
            "tensions",
            "openQuestions",
            "focus",
            "wholeQuestionReminder",
            "driftCheck",
            "stage",
        ):
            with self.subTest(key=key):
                self.assertIn(key, server_js)
                self.assertIn(key, app_js)

        for drift_check in ("none", "narrow", "off_track"):
            with self.subTest(drift_check=drift_check):
                self.assertIn(drift_check, server_js)
                self.assertIn(drift_check, app_js)

        self.assertIn("如果 driftCheck 是 narrow", server_js)
        self.assertIn("如果 driftCheck 是 off_track", server_js)
        self.assertIn("不能只继续定义当前 focus", server_js)
        self.assertIn("function enforceSocraticDriftText", server_js)

        for stage in (
            "starting",
            "clarifying_terms",
            "testing_assumptions",
            "finding_tension",
            "summarizing",
        ):
            with self.subTest(stage=stage):
                self.assertIn(stage, server_js)
                self.assertIn(stage, app_js)

    def test_socratic_requests_have_timeout_fallback_boundary(self):
        server_js = self.read("server.js")
        app_js = self.read("app.js")

        self.assertIn("DEEPSEEK_TIMEOUT_MS", server_js)
        self.assertIn("fetchWithTimeout", server_js)
        self.assertIn("Model provider timed out", server_js)
        self.assertIn("sendJson(response, 504", server_js)

        self.assertIn("SOCRATIC_REQUEST_TIMEOUT_MS", app_js)
        self.assertIn("fetchWithTimeout", app_js)
        self.assertIn('"/api/socratic-chat"', app_js)
        self.assertIn("generateLocalSocraticReply", app_js)

    def test_socratic_user_can_ask_for_socrates_view(self):
        server_js = self.read("server.js")
        app_js = self.read("app.js")

        self.assertIn("inferSocraticUserIntent", server_js)
        self.assertIn("inferSocraticUserIntent", app_js)
        self.assertIn("ask_socrates_view", server_js)
        self.assertIn("ask_socrates_view", app_js)
        self.assertIn("userIntent", server_js)
        self.assertIn("userIntent", app_js)
        self.assertIn("你觉得呢|你怎么看", server_js)
        self.assertIn("你觉得呢|你怎么看", app_js)

    def test_socratic_can_synthesize_self_understanding(self):
        index_html = self.read("index.html")
        server_js = self.read("server.js")
        app_js = self.read("app.js")

        self.assertIn('id="socraticSynthesisButton"', index_html)
        self.assertIn("生成自我理解", index_html)
        self.assertIn("function synthesizeSocraticUnderstanding", app_js)
        self.assertIn("generateLocalSocraticSelfUnderstanding", app_js)
        self.assertIn("synthesize_self_understanding", app_js)
        self.assertIn("synthesize_self_understanding", server_js)
        self.assertIn("自我理解", server_js)
        self.assertIn("用第二人称", server_js)
        self.assertIn("你真正困惑", server_js)
        self.assertIn("function enforceSocraticSecondPersonText", server_js)
        self.assertIn("你可能", app_js)
        self.assertNotIn("用第一人称表达用户", server_js)
        self.assertNotIn("我真正困惑", server_js)
        self.assertNotIn("我真正困惑", app_js)

    def test_socratic_redirects_to_original_question_without_pause_copy(self):
        server_js = self.read("server.js")
        app_js = self.read("app.js")

        self.assertIn("function shouldRedirectSocraticThread", server_js)
        self.assertIn("function shouldRedirectSocraticThread", app_js)
        self.assertIn("function userAnswerCountSinceSocraticRedirect", server_js)
        self.assertIn("function userAnswerCountSinceSocraticRedirect", app_js)
        self.assertIn("function isDerivativeSocraticFocus", server_js)
        self.assertIn("function enforceSocraticRedirectText", server_js)
        self.assertIn("回到原问题直接提问", server_js)
        self.assertIn("socraticControl", server_js)
        self.assertIn("socraticControl", app_js)
        self.assertIn("shouldRedirect", server_js)
        self.assertIn("shouldRedirect", app_js)
        self.assertNotIn("小结后仍给出一个新的追问", server_js)
        self.assertNotIn("先停一下", server_js)
        self.assertNotIn("先停一下", app_js)
        self.assertNotIn("不继续追问", server_js)
        self.assertNotIn("不继续追问", app_js)

    def test_socratic_view_request_direct_concepts_and_definition_depth(self):
        server_js = self.read("server.js")
        app_js = self.read("app.js")

        self.assertIn('context.userIntent !== "ask_socrates_view"', server_js)
        self.assertIn('context.userIntent === "ask_socrates_view" ? baseSocraticText : enforceSocraticDriftText', server_js)
        self.assertIn("不要套用回题句式", server_js)
        self.assertIn("if (hasDirectSocraticConceptFocus(context?.socraticState)) return text;", server_js)
        self.assertIn('userIntent === "ask_socrates_view" ? false : shouldRedirectSocraticThread()', app_js)

        for function_name in (
            "function hasDirectSocraticConceptFocus",
            "function isDefinitionChainStale",
            "function recentSocraticDefinitionQuestionCount",
            "function buildSocraticTempoShiftQuestion",
        ):
            with self.subTest(function_name=function_name):
                self.assertIn(function_name, server_js)
                self.assertIn(function_name, app_js)

        self.assertIn("不把原问题的直接概念链误判为偏题", server_js)
        self.assertIn("连续定义追问已经够多", server_js)
        self.assertNotIn("你判断这条分界线时", server_js)
        self.assertNotIn("你判断这条分界线时", app_js)

    def test_socratic_redirect_prefers_definition_revision_over_binary_template(self):
        server_js = self.read("server.js")
        app_js = self.read("app.js")

        for function_name in (
            "function shouldAskForSocraticDefinitionRevision",
            "function buildSocraticDefinitionRevisionQuestion",
            "function normalizeSocraticDefinitionStandard",
        ):
            with self.subTest(function_name=function_name):
                self.assertIn(function_name, server_js)
                self.assertIn(function_name, app_js)

        self.assertIn("用户已经提出新的区分标准时，优先追问是否要改写定义", server_js)
        self.assertIn("重新理解", server_js)
        self.assertIn("重新理解", app_js)
        self.assertNotIn("更像把你推向", server_js)
        self.assertNotIn("更像把你推向", app_js)


if __name__ == "__main__":
    unittest.main()
