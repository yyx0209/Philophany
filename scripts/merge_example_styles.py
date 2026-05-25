#!/usr/bin/env python3
"""
Merge human-approved exampleStyle proposals into reviewed philosopher cards.

Default mode is dry-run. Only reviews with humanDecision=approve are merged.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from graph_data_io import load_card_bundle, normalize_example_style, safe_id


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARDS = ROOT / "data" / "generated" / "reviewed_philosopher_cards.json"
DEFAULT_STYLES = ROOT / "data" / "generated" / "reviewed_example_styles.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge approved exampleStyle reviews into philosopher cards.")
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--styles", type=Path, default=DEFAULT_STYLES)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be merged without writing files.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    card_bundle = load_card_bundle(args.cards, approved_only=False)
    cards = card_bundle.get("philosophers", [])
    reviewed = json.loads(args.styles.read_text(encoding="utf-8"))
    approved_styles, skipped = approved_example_styles_from_reviews(reviewed, {card["id"] for card in cards})
    merged_cards = merge_approved_example_styles(cards, approved_styles)
    output_path = args.output or args.cards

    print(f"Cards: {len(cards)}")
    print(f"Approved example styles: {len(approved_styles)}")
    print(f"Skipped reviews: {len(skipped)}")
    print(f"Output: {output_path}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write cards.")
        return

    payload = preserve_card_bundle_shape(args.cards, merged_cards)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")


def approved_example_styles_from_reviews(
    reviewed: dict[str, Any],
    philosopher_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    approved = {}
    skipped = []
    for review in reviewed.get("reviews", []):
        philosopher_id = safe_id(review.get("id", ""))
        if review.get("humanDecision") != "approve":
            skipped.append({"id": philosopher_id, "reason": "not approved"})
            continue
        if philosopher_id not in philosopher_ids:
            skipped.append({"id": philosopher_id, "reason": "invalid philosopher id"})
            continue
        style = normalize_example_style(review.get("proposedExampleStyle", {}))
        if not style:
            skipped.append({"id": philosopher_id, "reason": "invalid exampleStyle"})
            continue
        approved[philosopher_id] = style
    return approved, skipped


def merge_approved_example_styles(
    cards: list[dict[str, Any]] | dict[str, Any],
    approved_styles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]] | dict[str, Any]:
    if isinstance(cards, dict):
        merged_card = deepcopy(cards)
        style = approved_styles.get(safe_id(merged_card.get("id", "")))
        if style:
            merged_card["exampleStyle"] = style
        return merged_card

    merged_cards = []
    for card in cards:
        merged_card = deepcopy(card)
        style = approved_styles.get(safe_id(merged_card.get("id", "")))
        if style:
            merged_card["exampleStyle"] = style
        merged_cards.append(merged_card)
    return merged_cards


def preserve_card_bundle_shape(cards_path: Path, merged_cards: list[dict[str, Any]]) -> dict[str, Any]:
    original = json.loads(cards_path.read_text(encoding="utf-8"))
    if "reviews" in original:
        by_id = {card["id"]: card for card in merged_cards}
        payload = deepcopy(original)
        for review in payload.get("reviews", []):
            card = review.get("card", review)
            philosopher_id = safe_id(card.get("id", ""))
            if philosopher_id in by_id:
                if "card" in review:
                    review["card"] = by_id[philosopher_id]
                else:
                    review.update(by_id[philosopher_id])
        return payload
    if "philosophers" in original:
        payload = deepcopy(original)
        payload["philosophers"] = merged_cards
        return payload
    if "cards" in original:
        payload = deepcopy(original)
        payload["cards"] = merged_cards
        return payload
    return {"philosophers": merged_cards}


if __name__ == "__main__":
    main()
