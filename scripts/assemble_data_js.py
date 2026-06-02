#!/usr/bin/env python3
"""
Assemble the final browser data bundle from reviewed JSON artifacts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from graph_data_io import load_card_bundle, load_existing_relations
from merge_daily_quotes import approved_daily_quotes_from_reviews


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARDS = ROOT / "data" / "generated" / "reviewed_philosopher_cards.json"
DEFAULT_RELATIONS = ROOT / "data" / "generated" / "product_graph_relations.json"
DEFAULT_DAILY_QUOTES = ROOT / "data" / "generated" / "reviewed_daily_quotes.json"
DEFAULT_OUTPUT = ROOT / "data.js"
DEFAULT_DIMENSIONS = [
    {"id": "reasonInstinct", "left": "直觉/生命", "right": "理性/论证"},
    {"id": "individualCollective", "left": "共同秩序", "right": "个体自我"},
    {"id": "desireDiscipline", "left": "节制欲望", "right": "肯定欲望"},
    {"id": "moralUniversalism", "left": "情境/谱系", "right": "普遍原则"},
    {"id": "languageWorld", "left": "世界先于语言", "right": "语言塑造世界"},
]
DEFAULT_TOPICS = ["成功", "自由", "幸福", "道德", "欲望", "痛苦", "死亡", "意义", "真理", "行动"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble reviewed cards and relations into data.js.")
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--relations", type=Path, default=DEFAULT_RELATIONS)
    parser.add_argument("--daily-quotes", type=Path, default=DEFAULT_DAILY_QUOTES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    card_bundle = load_card_bundle(args.cards)
    cards = card_bundle.get("philosophers", [])
    philosopher_ids = {card["id"] for card in cards}
    relations = load_existing_relations(args.relations, philosopher_ids=philosopher_ids)
    daily_quotes = load_daily_quotes(args.daily_quotes, philosopher_ids=philosopher_ids)
    output = build_data_js(
        cards,
        relations,
        dimensions=card_bundle.get("dimensions") or DEFAULT_DIMENSIONS,
        daily_quotes=daily_quotes,
    )

    print(f"Cards: {len(cards)}")
    print(f"Approved relations: {len(relations)}")
    print(f"Daily quotes: {len(daily_quotes)}")
    print(f"Output: {args.output}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write data.js.")
        return
    args.output.write_text(output, encoding="utf-8")
    print(f"Wrote {args.output}")


def build_data_js(
    cards: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    dimensions: list[dict[str, str]] | None = None,
    daily_quotes: list[dict[str, Any]] | None = None,
) -> str:
    payload = {
        "dimensions": dimensions or DEFAULT_DIMENSIONS,
        "topics": collect_topics(cards),
        "philosophers": cards,
        "relations": relations,
        "dailyQuotes": daily_quotes or [],
    }
    return f"window.PHILOSOPHANY_DATA = {json.dumps(payload, ensure_ascii=False, indent=2)};\n"


def collect_topics(cards: list[dict[str, Any]]) -> list[str]:
    topics = list(DEFAULT_TOPICS)
    seen = set(topics)
    for card in cards:
        for topic in card.get("topics", []):
            if topic in seen:
                continue
            seen.add(topic)
            topics.append(topic)
    return topics


def load_daily_quotes(path: Path | None, philosopher_ids: set[str]) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    reviewed = json.loads(path.read_text(encoding="utf-8"))
    approved, _ = approved_daily_quotes_from_reviews(reviewed, philosopher_ids=philosopher_ids)
    return approved


if __name__ == "__main__":
    main()
