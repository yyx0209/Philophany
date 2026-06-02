#!/usr/bin/env python3
"""
Generate daily philosophy quote candidates from Wikiquote.

This script only builds a review queue. Product data should use quotes after
human approval, because even Wikiquote can contain rough translations,
disputed attributions, and weakly sourced entries.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_data_io import load_card_bundle, safe_id, safe_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARDS = ROOT / "data" / "generated" / "reviewed_philosopher_cards.json"
DEFAULT_OUTPUT = ROOT / "data" / "generated" / "wikiquote_quote_candidates.json"
WIKIQUOTE_API = "https://en.wikiquote.org/w/api.php"
UNRELIABLE_SECTION_RE = re.compile(r"(misattributed|disputed|unsourced|quotes about)", re.I)
WIKIQUOTE_TITLES = {
    "socrates": "Socrates",
    "plato": "Plato",
    "aristotle": "Aristotle",
    "confucius": "Confucius",
    "zhuangzi": "Zhuangzi",
    "buddha": "Gautama Buddha",
    "hume": "David Hume",
    "kant": "Immanuel Kant",
    "hegel": "Georg Wilhelm Friedrich Hegel",
    "nietzsche": "Friedrich Nietzsche",
    "wittgenstein": "Ludwig Wittgenstein",
    "sartre": "Jean-Paul Sartre",
    "wang-yangming": "Wang Yangming",
}
ORIGINAL_LANGUAGES = {
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
    parser = argparse.ArgumentParser(description="Generate Wikiquote candidates for daily philosophy inspiration.")
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit-per-philosopher", type=int, default=4)
    parser.add_argument("--delay-seconds", type=float, default=0.7)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    card_bundle = load_card_bundle(args.cards)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for card in card_bundle.get("philosophers", []):
        philosopher_id = safe_id(card.get("id", ""))
        page_title = WIKIQUOTE_TITLES.get(philosopher_id)
        if not page_title:
            skipped.append({"philosopherId": philosopher_id, "reason": "missing Wikiquote title mapping"})
            continue
        try:
            wikitext = fetch_wikiquote_wikitext(page_title, retries=args.retries)
        except Exception as exc:  # pragma: no cover - CLI network path
            skipped.append({"philosopherId": philosopher_id, "reason": f"fetch failed: {exc}"})
            continue
        candidates.extend(
            parse_wikiquote_candidates(
                philosopher_id=philosopher_id,
                philosopher_name=safe_text(card.get("name", ""), 80),
                page_title=page_title,
                wikitext=wikitext,
                limit=args.limit_per_philosopher,
            )
        )
        if args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    output = {
        "metadata": {
            "source": "Wikiquote candidate extraction",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "candidateCount": len(candidates),
            "skippedCount": len(skipped),
            "needsHumanConfirmation": True,
            "note": "Candidates exclude obvious Misattributed, Disputed, Unsourced, and Quotes about sections, but still require human review.",
        },
        "candidates": candidates,
        "skipped": skipped,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(candidates)} quote candidates to {args.output}")
    if skipped:
        print(f"Skipped {len(skipped)} philosophers; inspect metadata for details.")


def fetch_wikiquote_wikitext(page_title: str, retries: int = 2) -> str:
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": page_title,
        "format": "json",
        "formatversion": "2",
    }
    url = f"{WIKIQUOTE_API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "Philophany quote candidate generator"})
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code != 429 or attempt >= retries:
                raise
            time.sleep(3 + attempt * 3)
    else:  # pragma: no cover - loop always breaks or raises
        raise last_error or RuntimeError(f"failed to fetch Wikiquote page: {page_title}")
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        raise ValueError(f"Wikiquote page not found: {page_title}")
    revision = pages[0].get("revisions", [{}])[0]
    slots = revision.get("slots", {})
    if isinstance(slots, dict) and "main" in slots:
        return slots["main"].get("content", "")
    return revision.get("content", "")


def parse_wikiquote_candidates(
    philosopher_id: str,
    philosopher_name: str,
    page_title: str,
    wikitext: str,
    limit: int = 4,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    section_stack: list[str] = []
    current: dict[str, Any] | None = None

    for raw_line in wikitext.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^(=+)\s*(.*?)\s*\1$", line)
        if heading:
            level = max(0, len(heading.group(1)) - 2)
            title = clean_wiki_markup(heading.group(2))
            section_stack = section_stack[:level] + [title]
            current = None
            continue

        if not line or is_unreliable_section(section_stack):
            continue

        if line.startswith("* ") and not line.startswith("**"):
            if len(candidates) >= limit:
                current = None
                continue
            quote = clean_quote_text(line[2:])
            if not is_usable_quote(quote):
                current = None
                continue
            current = {
                "philosopherId": safe_id(philosopher_id),
                "philosopherName": safe_text(philosopher_name, 80),
                "sourceText": quote,
                "displayQuote": "",
                "originalQuote": "",
                "originalLanguage": ORIGINAL_LANGUAGES.get(safe_id(philosopher_id), "en"),
                "showOriginal": False,
                "source": "",
                "sourceUrl": f"https://en.wikiquote.org/wiki/{urllib.parse.quote(page_title.replace(' ', '_'))}",
                "sourceType": "wikiquote",
                "reliability": "needs_review",
                "flags": [],
                "note": "",
                "humanDecision": "pending",
            }
            candidates.append(current)
            continue

        if current and line.startswith("** "):
            source = clean_wiki_markup(line[3:])
            if source and not current["source"]:
                current["source"] = safe_text(source, 240)
                current["reliability"] = "sourced"

    return candidates


def is_unreliable_section(section_stack: list[str]) -> bool:
    return any(UNRELIABLE_SECTION_RE.search(section) for section in section_stack)


def is_usable_quote(quote: str) -> bool:
    if len(quote) < 20:
        return False
    if quote.startswith(("File:", "Image:", "Category:")):
        return False
    return True


def clean_quote_text(value: str) -> str:
    text = clean_wiki_markup(value)
    text = re.sub(r"\s+[-–—]\s*$", "", text)
    return safe_text(text, 500)


def clean_wiki_markup(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.I | re.S)
    text = re.sub(r"<ref[^/]*/>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


if __name__ == "__main__":
    main()
