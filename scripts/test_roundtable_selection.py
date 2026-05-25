import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
SERVER_JS = ROOT / "server.js"


class RoundtableSelectionTest(unittest.TestCase):
    def setUp(self):
        self.source = APP_JS.read_text(encoding="utf-8")
        self.server_source = SERVER_JS.read_text(encoding="utf-8")

    def test_selection_uses_relevance_gate_before_diversity_bonus(self):
        self.assertIn("RELEVANCE_GATE_THRESHOLD", self.source)
        self.assertRegex(
            self.source,
            r"const\s+relevanceScore\s*=\s*fitScore\s*\+\s*topicScore\s*\+\s*conceptScore\s*\+\s*discussionNeedScore\s*\+\s*tensionScore",
        )
        self.assertRegex(
            self.source,
            r"const\s+candidatePool\s*=\s*candidates\.filter\(\s*\(entry\)\s*=>\s*entry\.result\.passesRelevanceGate\s*\)",
        )
        self.assertRegex(
            self.source,
            r"finalScore:\s*relevanceScore\s*\+\s*selectedBonus\s*\+\s*specificity",
        )

    def test_discussion_needs_do_not_label_philosophers_as_slots(self):
        self.assertNotIn("适合槽位", self.source)
        self.assertIn("覆盖问题维度", self.source)
        self.assertIn("discussionNeeds", self.source)
        self.assertNotRegex(self.source, r"findMatches\(\s*\[\s*slot\.role")
        self.assertRegex(self.source, r"matched:\s*findMatches\(\s*need\.needs,\s*personTerms\s*\)")
        self.assertIn("discussionNeeds", self.server_source)
        self.assertIn("不是哲学家角色标签", self.server_source)


if __name__ == "__main__":
    unittest.main()
