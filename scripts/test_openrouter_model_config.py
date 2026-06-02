import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODEL = "deepseek-v4-pro"
EXPECTED_ROUNDTABLE_MODEL = "deepseek-v4-pro"
EXPECTED_GRAPH_MODEL = "openai/gpt-5.5"
OLD_BROKEN_MODEL = "openai/gpt-5"


class ModelProviderConfigTest(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_runtime_analysis_uses_deepseek_official_api(self):
        app_js = self.read("app.js")
        server_js = self.read("server.js")
        env_example = self.read(".env.example")

        self.assertIn(f'DEFAULT_ANALYSIS_MODEL = "{EXPECTED_MODEL}"', app_js)
        self.assertIn(f'process.env.DEEPSEEK_MODEL || "{EXPECTED_MODEL}"', server_js)
        self.assertIn('DEEPSEEK_URL = process.env.DEEPSEEK_API_URL || "https://api.deepseek.com/chat/completions"', server_js)
        self.assertIn("function getDeepSeekKey", server_js)
        self.assertIn("process.env.DEEPSEEK_API_KEY", server_js)
        self.assertIn(f"DEEPSEEK_MODEL={EXPECTED_MODEL}", env_example)
        self.assertIn("DEEPSEEK_API_KEY=your-deepseek-api-key", env_example)
        self.assertNotIn("openrouter.ai/api/v1/chat/completions", server_js)
        self.assertNotIn("HTTP-Referer", server_js)
        self.assertNotIn("X-Title", server_js)

        for source in (app_js, server_js, env_example):
            self.assertNotRegex(source, rf'["=]{re.escape(OLD_BROKEN_MODEL)}["\\n]')

    def test_roundtable_generation_uses_deepseek(self):
        app_js = self.read("app.js")
        server_js = self.read("server.js")
        env_example = self.read(".env.example")

        self.assertIn(f'DEFAULT_ROUNDTABLE_MODEL = "{EXPECTED_ROUNDTABLE_MODEL}"', app_js)
        self.assertIn(f'process.env.DEEPSEEK_ROUNDTABLE_MODEL || "{EXPECTED_ROUNDTABLE_MODEL}"', server_js)
        self.assertIn(f"DEEPSEEK_ROUNDTABLE_MODEL={EXPECTED_ROUNDTABLE_MODEL}", env_example)
        self.assertIn("roundtableModel: state.provider.roundtableModel", app_js)
        self.assertIn("model: state.provider.model", app_js)
        self.assertIn("body.roundtableModel || DEFAULT_ROUNDTABLE_MODEL", server_js)
        self.assertIn("body.model || DEFAULT_ANALYSIS_MODEL", server_js)
        self.assertIn('response_format: { type: "json_object" }', server_js)

    def test_runtime_deepseek_requests_disable_thinking_mode(self):
        server_js = self.read("server.js")

        self.assertIn('thinking: { type: "disabled" }', server_js)
        self.assertGreaterEqual(server_js.count('thinking: { type: "disabled" }'), 5)

    def test_graph_generation_scripts_still_default_to_gpt55(self):
        for path in (
            "scripts/generate_philosopher_cards.py",
            "scripts/review_local_graph_candidates.py",
        ):
            with self.subTest(path=path):
                self.assertIn(f'DEFAULT_MODEL = "{EXPECTED_GRAPH_MODEL}"', self.read(path))

    def test_non_graph_enrichment_scripts_default_to_deepseek(self):
        for path in (
            "scripts/generate_speech_personas.py",
            "scripts/generate_example_styles.py",
        ):
            with self.subTest(path=path):
                source = self.read(path)
                self.assertIn(f'DEFAULT_MODEL = "{EXPECTED_MODEL}"', source)
                self.assertIn('DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"', source)
                self.assertIn("DEEPSEEK_API_KEY", source)
                self.assertIn('"response_format": {"type": "json_object"}', source)
                self.assertNotIn("OPENROUTER_API_KEY is missing", source)

    def test_local_env_model_matches_default_when_present(self):
        env_path = ROOT / ".env"
        if not env_path.exists():
            return

        env_text = env_path.read_text(encoding="utf-8")
        model_lines = [line for line in env_text.splitlines() if line.startswith("DEEPSEEK_MODEL=")]
        if model_lines:
            self.assertEqual(model_lines, [f"DEEPSEEK_MODEL={EXPECTED_MODEL}"])

    def test_question_analysis_has_enough_output_budget_for_full_roster(self):
        server_js = self.read("server.js")
        match = re.search(r"max_tokens:\s*(\d+),[\s\S]{0,220}messages:\s*buildQuestionAnalysisPrompt", server_js)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 3200)


if __name__ == "__main__":
    unittest.main()
