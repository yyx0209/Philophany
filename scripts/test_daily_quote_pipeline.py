import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_daily_quote_candidates import parse_wikiquote_candidates
from merge_daily_quotes import approved_daily_quotes_from_reviews


class DailyQuotePipelineTest(unittest.TestCase):
    def test_parse_wikiquote_candidates_skips_unreliable_sections(self):
        wikitext = """
== Sourced ==
* Reason is, and ought only to be the slave of the passions.
** ''A Treatise of Human Nature'', Book 2, Part 3, Section 3

== Misattributed ==
* This should not be used.
** Popular quotation with no reliable source.

== Disputed ==
* This should not be used either.

== Unsourced ==
* Nor should this one.
"""

        candidates = parse_wikiquote_candidates(
            philosopher_id="hume",
            philosopher_name="大卫·休谟",
            page_title="David Hume",
            wikitext=wikitext,
            limit=5,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("hume", candidates[0]["philosopherId"])
        self.assertEqual("pending", candidates[0]["humanDecision"])
        self.assertIn("Reason is", candidates[0]["sourceText"])
        self.assertEqual("", candidates[0]["originalQuote"])
        self.assertEqual("en", candidates[0]["originalLanguage"])
        self.assertFalse(candidates[0]["showOriginal"])
        self.assertIn("Treatise", candidates[0]["source"])

    def test_parse_wikiquote_candidates_marks_original_language_not_source_language(self):
        candidates = parse_wikiquote_candidates(
            philosopher_id="socrates",
            philosopher_name="苏格拉底",
            page_title="Socrates",
            wikitext="""
== Sourced ==
* The unexamined life is not worth living.
** Plato, Apology 38a
""",
            limit=1,
        )

        self.assertEqual("grc", candidates[0]["originalLanguage"])
        self.assertEqual("The unexamined life is not worth living.", candidates[0]["sourceText"])
        self.assertEqual("", candidates[0]["originalQuote"])

    def test_parse_wikiquote_candidates_keeps_source_for_last_limited_item(self):
        wikitext = """
== Sourced ==
* First long enough quote for review.
** First source.
* Second long enough quote for review.
** Second source.
"""

        candidates = parse_wikiquote_candidates(
            philosopher_id="x",
            philosopher_name="某哲学家",
            page_title="Example",
            wikitext=wikitext,
            limit=2,
        )

        self.assertEqual(2, len(candidates))
        self.assertEqual("Second source.", candidates[1]["source"])

    def test_approved_daily_quotes_filters_pending_and_flagged(self):
        reviewed = {
            "candidates": [
                {
                    "philosopherId": "hume",
                    "sourceText": "Reason is, and ought only to be the slave of the passions.",
                    "displayQuote": "理性是激情的奴隶。",
                    "source": "A Treatise of Human Nature",
                    "sourceUrl": "https://en.wikiquote.org/wiki/David_Hume",
                    "originalLanguage": "en",
                    "flags": [],
                    "humanDecision": "approve",
                },
                {
                    "philosopherId": "kant",
                    "quote": "A fake quote.",
                    "source": "Unknown",
                    "sourceUrl": "https://en.wikiquote.org/wiki/Immanuel_Kant",
                    "flags": ["misattributed"],
                    "humanDecision": "approve",
                },
                {
                    "philosopherId": "socrates",
                    "quote": "The unexamined life is not worth living.",
                    "source": "Plato, Apology",
                    "sourceUrl": "https://en.wikiquote.org/wiki/Socrates",
                    "flags": [],
                    "humanDecision": "pending",
                },
            ]
        }

        approved, skipped = approved_daily_quotes_from_reviews(reviewed, philosopher_ids={"hume", "kant", "socrates"})

        self.assertEqual(["hume"], [item["philosopherId"] for item in approved])
        self.assertEqual(2, len(skipped))
        self.assertIn("sourceText", approved[0])
        self.assertNotIn("quote", approved[0])
        self.assertEqual("", approved[0]["originalQuote"])
        self.assertFalse(approved[0]["showOriginal"])

    def test_reviewed_daily_quotes_can_omit_human_decision(self):
        reviewed = {
            "dailyQuotes": [
                {
                    "philosopherId": "socrates",
                    "sourceText": "The unexamined life is not worth living.",
                    "displayQuote": "未经省察的人生不值得过。",
                    "source": "Plato, Apology 38a",
                    "sourceUrl": "https://en.wikiquote.org/wiki/Socrates",
                    "originalLanguage": "grc",
                    "flags": [],
                }
            ]
        }

        approved, skipped = approved_daily_quotes_from_reviews(reviewed, philosopher_ids={"socrates"})

        self.assertEqual(1, len(approved))
        self.assertEqual([], skipped)

    def test_approved_daily_quotes_limits_each_philosopher_to_five_quotes(self):
        reviewed = {
            "candidates": [
                {
                    "philosopherId": "hume",
                    "sourceText": f"Quote number {index} is long enough to review.",
                    "source": "A Treatise of Human Nature",
                    "sourceUrl": "https://en.wikiquote.org/wiki/David_Hume",
                    "originalLanguage": "en",
                    "flags": [],
                    "humanDecision": "approve",
                }
                for index in range(6)
            ]
        }

        approved, skipped = approved_daily_quotes_from_reviews(reviewed, philosopher_ids={"hume"})

        self.assertEqual(5, len(approved))
        self.assertEqual("too many quotes for philosopher", skipped[-1]["reason"])

    def test_frontend_has_daily_inspiration_hook(self):
        root = Path(__file__).resolve().parents[1]
        index = (root / "index.html").read_text(encoding="utf-8")
        app = (root / "app.js").read_text(encoding="utf-8")
        styles = (root / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="dailyInspiration"', index)
        self.assertIn("function renderDailyInspiration", app)
        self.assertIn("function dailyQuoteForDate", app)
        self.assertIn("function seededDailyQuoteIndex", app)
        self.assertIn("function shouldShowOriginalQuote", app)
        self.assertIn("item?.showOriginal !== true", app)
        self.assertIn("item?.originalQuote", app)
        self.assertIn('String(item?.originalLanguage || "").startsWith("zh")', app)
        self.assertIn("function refreshDailyQuote", app)
        self.assertIn("DAILY_QUOTE_STORAGE_KEY", app)
        self.assertIn("data-refresh-daily-quote", app)
        self.assertIn(".daily-inspiration", styles)
        self.assertIn(".daily-actions", styles)
        self.assertIn(".daily-note::before", styles)
        self.assertIn('content: "* "', styles)

    def test_reviewed_daily_quote_file_has_one_to_five_quotes_per_philosopher(self):
        root = Path(__file__).resolve().parents[1]
        reviewed = json.loads((root / "data/generated/reviewed_daily_quotes.json").read_text(encoding="utf-8"))
        counts = Counter(item["philosopherId"] for item in reviewed["dailyQuotes"])

        self.assertEqual(13, len(counts))
        self.assertGreaterEqual(min(counts.values()), 1)
        self.assertLessEqual(max(counts.values()), 5)

        for item in reviewed["dailyQuotes"]:
            self.assertIn("displayQuote", item)
            self.assertIn("sourceText", item)
            self.assertIn("originalQuote", item)
            self.assertIn("originalLanguage", item)
            self.assertIn("showOriginal", item)
            self.assertNotIn("quote", item)
            if item["sourceType"] == "wikiquote":
                self.assertFalse(item["showOriginal"])


if __name__ == "__main__":
    unittest.main()
