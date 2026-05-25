import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODEL = "deepseek/deepseek-v4-pro"
EXPECTED_ROUNDTABLE_MODEL = "deepseek/deepseek-v4-pro"
EXPECTED_GRAPH_MODEL = "openai/gpt-5.5"
OLD_BROKEN_MODEL = "openai/gpt-5"


class OpenRouterModelConfigTest(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_default_openrouter_model_uses_deepseek_for_runtime_analysis(self):
        app_js = self.read("app.js")
        server_js = self.read("server.js")
        env_example = self.read(".env.example")

        self.assertIn(f'DEFAULT_ANALYSIS_MODEL = "{EXPECTED_MODEL}"', app_js)
        self.assertIn(f'DEFAULT_ANALYSIS_MODEL = process.env.OPENROUTER_MODEL || "{EXPECTED_MODEL}"', server_js)
        self.assertIn(f"OPENROUTER_MODEL={EXPECTED_MODEL}", env_example)

        for source in (app_js, server_js, env_example):
            self.assertNotRegex(source, rf'["=]{re.escape(OLD_BROKEN_MODEL)}["\\n]')

    def test_roundtable_generation_uses_deepseek(self):
        app_js = self.read("app.js")
        server_js = self.read("server.js")
        env_example = self.read(".env.example")

        self.assertIn(f'DEFAULT_ROUNDTABLE_MODEL = "{EXPECTED_ROUNDTABLE_MODEL}"', app_js)
        self.assertIn(
            f'DEFAULT_ROUNDTABLE_MODEL = process.env.OPENROUTER_ROUNDTABLE_MODEL || "{EXPECTED_ROUNDTABLE_MODEL}"',
            server_js,
        )
        self.assertIn(f"OPENROUTER_ROUNDTABLE_MODEL={EXPECTED_ROUNDTABLE_MODEL}", env_example)
        self.assertIn("roundtableModel: state.provider.roundtableModel", app_js)
        self.assertIn("model: state.provider.model", app_js)
        self.assertIn("body.roundtableModel || DEFAULT_ROUNDTABLE_MODEL", server_js)
        self.assertIn("body.model || DEFAULT_ANALYSIS_MODEL", server_js)

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
                self.assertIn(f'DEFAULT_MODEL = "{EXPECTED_MODEL}"', self.read(path))

    def test_local_env_model_matches_default_when_present(self):
        env_path = ROOT / ".env"
        if not env_path.exists():
            return

        env_text = env_path.read_text(encoding="utf-8")
        model_lines = [line for line in env_text.splitlines() if line.startswith("OPENROUTER_MODEL=")]
        self.assertEqual(model_lines, [f"OPENROUTER_MODEL={EXPECTED_MODEL}"])

    def test_question_analysis_has_enough_output_budget_for_full_roster(self):
        server_js = self.read("server.js")
        match = re.search(r"max_tokens:\s*(\d+),\s*messages:\s*buildQuestionAnalysisPrompt", server_js)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 3200)


if __name__ == "__main__":
    unittest.main()
