import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"


class RoundtableLineupStateTest(unittest.TestCase):
    def read_app(self):
        return APP_JS.read_text(encoding="utf-8")

    def test_initial_lineup_is_empty_until_user_summons(self):
        app_js = self.read_app()

        self.assertIn("lineup: []", app_js)
        self.assertNotIn('state.lineup = ["nietzsche", "zhuangzi", "kant", "buddha", "wang-yangming"]', app_js)
        self.assertNotIn("默认圆桌已就绪", app_js)

    def test_lineup_shows_loading_while_summoning(self):
        app_js = self.read_app()

        self.assertIn("isSummoningLineup: false", app_js)
        self.assertIn("state.isSummoningLineup = true", app_js)
        self.assertIn("state.isSummoningLineup = false", app_js)
        self.assertIn("正在召集哲学家阵容", app_js)
        self.assertIn("if (state.isSummoningLineup)", app_js)

    def test_lineup_is_capped_at_five(self):
        app_js = self.read_app()

        self.assertIn("const MAX_LINEUP_SIZE = 5", app_js)
        self.assertIn("const targetSize = MAX_LINEUP_SIZE", app_js)
        self.assertIn("if (state.lineup.length >= MAX_LINEUP_SIZE) return", app_js)
        self.assertNotIn("state.lineup = [...state.lineup, id].slice(0, 6)", app_js)
        self.assertIn("当前阵容最多五位", app_js)


if __name__ == "__main__":
    unittest.main()
