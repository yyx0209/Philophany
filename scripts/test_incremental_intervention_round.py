import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
SERVER_JS = ROOT / "server.js"
ROUNDTABLE_DOC = ROOT / "docs" / "roundtable-method.md"


class IncrementalInterventionRoundTest(unittest.TestCase):
    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_frontend_tracks_followup_responses_one_speaker_at_a_time(self):
        app_js = self.read(APP_JS)

        self.assertIn("interventionRound: null", app_js)
        self.assertIn("function createInterventionRound", app_js)
        self.assertIn("function speakerNameCandidates", app_js)
        self.assertIn("function nextInterventionSpeaker", app_js)
        self.assertIn("async function generateInterventionRoundStep", app_js)
        self.assertIn("function advanceInterventionTurn", app_js)
        self.assertIn('action: "intervention_step"', app_js)
        self.assertRegex(app_js, r"currentSpeakerId:\s*nextSpeaker\.id")
        self.assertRegex(app_js, r"afterMessages:\s*\(\)\s*=>\s*advanceInterventionTurn\(nextSpeaker\.id\)")
        self.assertRegex(app_js, r"state\.interventionRound\s*=\s*createInterventionRound\(text,\s*participants\)")
        self.assertRegex(app_js, r"speakerNameCandidates\(person\)\.some\(\(alias\)\s*=>")
        self.assertIn("name.split", app_js)

    def test_backend_intervention_step_allows_only_current_speaker(self):
        server_js = self.read(SERVER_JS)

        self.assertIn('"intervention_step"', server_js)
        self.assertIn("function speakerNameCandidates", server_js)
        self.assertRegex(
            server_js,
            r'if\s*\(context\.action\s*===\s*"intervention_step"\s*&&\s*context\.currentSpeakerId\)\s*return\s*\[context\.currentSpeakerId\]',
        )
        self.assertIn("任务：逐位回应用户追问。", server_js)
        self.assertIn("只生成这位哲学家的 1 条回应", server_js)
        self.assertNotIn("输出 1 到 5 条真正必要的回应", server_js)

    def test_short_names_like_kant_are_supported_for_targeting(self):
        app_js = self.read(APP_JS)
        server_js = self.read(SERVER_JS)

        for source in (app_js, server_js):
            self.assertRegex(source, r"split\(/\[·・\.\\s\]\+/\)")
            self.assertIn("normalizedName", source)
            self.assertIn("康德", self.read(ROOT / "data.js"))

    def test_targeted_intervention_answers_user_directly_without_forced_cross_response(self):
        server_js = self.read(SERVER_JS)

        self.assertIn("context.targetedSpeakerIds.includes(context.currentSpeakerId)", server_js)
        self.assertIn("用户点名当前发言者时，直接回应用户追问", server_js)
        self.assertIn("不要强行回应前文", server_js)
        self.assertNotIn("必须回应用户追问，并尽量连接已经可见的某个具体观点", server_js)

    def test_honorific_address_targets_named_philosopher_even_when_other_philosopher_is_mentioned(self):
        app_js = self.read(APP_JS)
        server_js = self.read(SERVER_JS)

        for source in (app_js, server_js):
            self.assertIn("directAddressPatterns", source)
            self.assertIn("先生|老师|教授", source)
            self.assertIn("有什么要说", source)
            self.assertIn("[，,：:！!？?\\\\s]+你", source)

    def test_at_mentions_target_first_mentioned_philosopher(self):
        app_js = self.read(APP_JS)
        server_js = self.read(SERVER_JS)

        for source in (app_js, server_js):
            self.assertIn("function extractAtMentionedSpeakers", source)
            self.assertIn("function findPersonByMention", source)
            self.assertIn("const atMentioned = extractAtMentionedSpeakers(text, participants)", source)
            self.assertIn("atMentioned[0]", source)
            self.assertIn("佛陀", source)

        index_html = self.read(ROOT / "index.html")
        self.assertIn("@庄子", index_html)
        self.assertIn("@康德", index_html)

    def test_multiple_at_mentions_can_create_a_speaker_queue(self):
        app_js = self.read(APP_JS)
        server_js = self.read(SERVER_JS)

        self.assertIn("function findTargetedSpeakersForText", app_js)
        self.assertIn("function shouldTreatAtMentionsAsSpeakerQueue", app_js)
        self.assertIn("const targetedSpeakers = findTargetedSpeakersForText(text, participants)", app_js)
        self.assertIn("targetedSpeakers.length > 0 ? targetedSpeakers", app_js)
        self.assertIn("你们", app_js)

        self.assertIn("context.targetedSpeakerIds", server_js)
        self.assertIn("context.targetedSpeakerIds.includes(context.currentSpeakerId)", server_js)
        self.assertIn("function findTargetedSpeakerIds", server_js)

        index_html = self.read(ROOT / "index.html")
        self.assertIn("@庄子@康德", index_html)

    def test_docs_state_followups_are_incremental(self):
        doc = self.read(ROUNDTABLE_DOC)

        self.assertIn("追问后也按逐位回应推进", doc)
        self.assertIn("不是一次性让所有哲学家同时回应", doc)
        self.assertIn("点名追问直接回答用户问题", doc)
        self.assertIn("@庄子", doc)
        self.assertIn("@庄子@孔子", doc)


if __name__ == "__main__":
    unittest.main()
