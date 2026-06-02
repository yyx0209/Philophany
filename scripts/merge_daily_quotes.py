#!/usr/bin/env python3
"""
Merge human-approved daily quotes into the reviewed daily quote artifact.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_data_io import load_card_bundle, safe_id, safe_string_list, safe_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "generated" / "wikiquote_quote_candidates.json"
DEFAULT_CARDS = ROOT / "data" / "generated" / "reviewed_philosopher_cards.json"
DEFAULT_OUTPUT = ROOT / "data" / "generated" / "reviewed_daily_quotes.json"
REJECT_FLAGS = {"misattributed", "disputed", "unsourced"}
DEFAULT_ORIGINAL_LANGUAGES = {
    "socrates": "grc",
    "plato": "grc",
    "aristotle": "grc",
    "confucius": "zh",
    "zhuangzi": "zh",
    "buddha": "pli",
    "hume": "en",
    "kant": "de",
    "hegel": "de",
    "nietzsche": "de",
    "wittgenstein": "de",
    "sartre": "fr",
    "wang-yangming": "zh",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge approved daily quote reviews.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    reviewed = json.loads(args.input.read_text(encoding="utf-8"))
    card_bundle = load_card_bundle(args.cards)
    philosopher_ids = {safe_id(card.get("id", "")) for card in card_bundle.get("philosophers", [])}
    approved, skipped = approved_daily_quotes_from_reviews(reviewed, philosopher_ids=philosopher_ids)

    output = {
        "metadata": {
            "source": "human-approved daily quote reviews",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "inputFile": str(args.input),
            "approvedCount": len(approved),
            "skippedCount": len(skipped),
            "needsHumanConfirmation": False,
        },
        "dailyQuotes": approved,
        "skipped": skipped,
    }

    print(f"Approved daily quotes: {len(approved)}")
    print(f"Skipped: {len(skipped)}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write reviewed_daily_quotes.json.")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")


def approved_daily_quotes_from_reviews(
    reviewed: dict[str, Any],
    philosopher_ids: set[str] | None = None,
    max_per_philosopher: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from_reviewed_daily_quotes = "dailyQuotes" in reviewed
    raw_items = reviewed.get("dailyQuotes") or reviewed.get("candidates") or reviewed.get("reviews") or []
    approved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    counts: dict[str, int] = {}

    for item in raw_items:
        philosopher_id = safe_id(item.get("philosopherId", ""))
        source_text = safe_text(item.get("sourceText") or item.get("quote", ""), 700)
        display_quote = safe_text(item.get("displayQuote", ""), 500) or source_text
        original_quote = safe_text(item.get("originalQuote", ""), 700)
        original_language = (
            safe_text(item.get("originalLanguage") or item.get("language", ""), 20)
            or DEFAULT_ORIGINAL_LANGUAGES.get(philosopher_id, "en")
        )
        show_original = bool(item.get("showOriginal")) and bool(original_quote)
        source = safe_text(item.get("source", ""), 240)
        source_url = safe_text(item.get("sourceUrl", ""), 300)
        flags = [flag.lower() for flag in safe_string_list(item.get("flags", []), 8, 40)]
        key = (philosopher_id, source_text.lower())

        decision = item.get("humanDecision")
        if decision != "approve" and not (from_reviewed_daily_quotes and decision is None):
            skipped.append({"philosopherId": philosopher_id, "reason": "not approved"})
            continue
        if philosopher_ids is not None and philosopher_id not in philosopher_ids:
            skipped.append({"philosopherId": philosopher_id, "reason": "invalid philosopher id"})
            continue
        if not source_text or not source or not source_url:
            skipped.append({"philosopherId": philosopher_id, "reason": "missing sourceText, source, or sourceUrl"})
            continue
        if any(flag in REJECT_FLAGS for flag in flags):
            skipped.append({"philosopherId": philosopher_id, "reason": "unreliable attribution flag"})
            continue
        if key in seen:
            skipped.append({"philosopherId": philosopher_id, "reason": "duplicate quote"})
            continue
        if counts.get(philosopher_id, 0) >= max_per_philosopher:
            skipped.append({"philosopherId": philosopher_id, "reason": "too many quotes for philosopher"})
            continue

        seen.add(key)
        counts[philosopher_id] = counts.get(philosopher_id, 0) + 1
        approved.append(
            {
                "philosopherId": philosopher_id,
                "displayQuote": display_quote,
                "sourceText": source_text,
                "originalQuote": original_quote,
                "originalLanguage": original_language,
                "showOriginal": show_original,
                "source": source,
                "sourceUrl": source_url,
                "sourceType": safe_text(item.get("sourceType", "wikiquote"), 40) or "wikiquote",
                "reliability": safe_text(item.get("reliability", "human_approved"), 40) or "human_approved",
                "translationNote": safe_text(item.get("translationNote", ""), 180),
                "note": safe_text(item.get("note", ""), 180),
            }
        )

    return approved, skipped


if __name__ == "__main__":
    main()
