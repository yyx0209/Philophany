#!/usr/bin/env python3
"""
Generate review-only philosopher card candidates from source data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from graph_data_io import clamp_float, read_json, safe_id, safe_string_list, safe_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WIKIDATA_GRAPH = ROOT / "data" / "generated" / "wikidata_graph.json"
DEFAULT_WIKIPEDIA_CACHE = ROOT / "data" / "generated" / "wikipedia_philosophy_extracts.json"
DEFAULT_OUTPUT = ROOT / "data" / "generated" / "philosopher_card_candidates.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-5.5"
ALLOWED_COLORS = {"blue", "violet", "gold", "teal", "green", "purple", "red", "slate"}
STANCE_KEYS = {"reasonInstinct", "individualCollective", "desireDiscipline", "moralUniversalism", "languageWorld"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate philosopher card candidates from Wikidata and Wikipedia extracts.")
    parser.add_argument("--wikidata", type=Path, default=DEFAULT_WIKIDATA_GRAPH)
    parser.add_argument("--wikipedia-cache", type=Path, default=DEFAULT_WIKIPEDIA_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    model = args.model or DEFAULT_MODEL
    wikidata_graph = read_json(args.wikidata)
    wikipedia_cache = read_json(args.wikipedia_cache) if args.wikipedia_cache.exists() else {}
    source_cards = build_source_cards(wikidata_graph, wikipedia_cache)

    if args.dry_run:
        print(f"Source cards: {len(source_cards)}")
        print(f"Model: {model}")
        print(f"Output: {args.output}")
        return

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is missing. Add it to .env or the environment.")

    raw = call_openrouter(api_key=api_key, model=model, messages=build_prompt(source_cards))
    parsed = parse_model_json(raw)
    cards = sanitize_card_candidates(parsed.get("cards", []), source_ids={card["id"] for card in source_cards})
    output = {
        "metadata": {
            "source": "OpenRouter philosopher card generation",
            "model": model,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sourceCards": len(source_cards),
            "candidateCards": len(cards),
            "needsHumanConfirmation": True,
        },
        "cards": cards,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Candidate cards: {len(cards)}")


def build_source_cards(wikidata_graph: dict[str, Any], wikipedia_cache: dict[str, Any]) -> list[dict[str, Any]]:
    extracts = wikipedia_cache.get("extracts", {})
    cards = []
    for person in wikidata_graph.get("philosophers", []):
        person_id = person.get("id", "")
        cached = extracts.get(person_id, {})
        summary = cached if isinstance(cached, str) else cached.get("summary", "")
        extract = cached if isinstance(cached, str) else cached.get("extract", "")
        cards.append(
            {
                "id": person_id,
                "labelZh": person.get("labelZh", ""),
                "labelEn": person.get("labelEn", ""),
                "descriptionZh": person.get("descriptionZh", ""),
                "descriptionEn": person.get("descriptionEn", ""),
                "wikipedia": person.get("wikipedia", {}),
                "field": labels(person.get("field", [])),
                "movement": labels(person.get("movement", [])),
                "influencedBy": labels(person.get("influencedBy", [])),
                "notableWork": labels(person.get("notableWork", [])),
                "wikipediaSummary": summary[:900],
                "wikipediaExtract": extract[:2200],
            }
        )
    return cards


def build_prompt(source_cards: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "\n".join(
                [
                    "你是 Philophany 的哲学角色卡编辑。",
                    "你的任务是根据 Wikidata 和 Wikipedia 思想摘录生成候选角色卡，不是生成最终事实。",
                    "不要编造具体引文、页码、章节或名言。",
                    "必须只返回合法 JSON，不要 Markdown，不要代码块。",
                ]
            ),
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    "请为每位哲学家生成一张 Philophany 圆桌角色卡候选。",
                    "每张卡必须包含 id、name、era、tradition、color、coreConcepts、topics、stance、voice、summary、opening、questionHooks、evidenceBasis。",
                    "stance 的键必须是 reasonInstinct、individualCollective、desireDiscipline、moralUniversalism、languageWorld，数值在 -1 到 1。",
                    "summary、opening、questionHooks 必须是中文。opening 不要伪装成真实引文。",
                    "topics 从自由、幸福、道德、欲望、痛苦、死亡、意义、真理、行动、政治、语言、知识中选择或少量补充。",
                    "",
                    "sourceCards:",
                    json.dumps(source_cards, ensure_ascii=False, indent=2),
                    "",
                    "输出格式：",
                    json.dumps(
                        {
                            "cards": [
                                {
                                    "id": "socrates",
                                    "name": "苏格拉底",
                                    "era": "古希腊",
                                    "tradition": "古希腊哲学",
                                    "color": "blue",
                                    "coreConcepts": ["自知无知", "德性", "追问"],
                                    "topics": ["道德", "真理", "行动"],
                                    "stance": {
                                        "reasonInstinct": 0.7,
                                        "individualCollective": 0.1,
                                        "desireDiscipline": -0.5,
                                        "moralUniversalism": 0.6,
                                        "languageWorld": 0.1,
                                    },
                                    "voice": "不断追问定义，温和但不放过矛盾。",
                                    "summary": "苏格拉底把哲学变成一种审视生活的追问。",
                                    "opening": "你说的成功到底指什么？",
                                    "questionHooks": ["这个词的定义是什么？"],
                                    "evidenceBasis": ["wikidata", "wikipediaExtract", "philosophical common knowledge"],
                                }
                            ]
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                ]
            ),
        },
    ]


def sanitize_card_candidates(raw_cards: list[dict[str, Any]], source_ids: set[str]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for raw in raw_cards:
        person_id = safe_id(raw.get("id", ""))
        if person_id not in source_ids or person_id in seen:
            continue
        seen.add(person_id)
        color = safe_text(raw.get("color", ""), 40)
        if color not in ALLOWED_COLORS:
            color = "slate"
        output.append(
            {
                "id": person_id,
                "name": safe_text(raw.get("name", ""), 80),
                "era": safe_text(raw.get("era", ""), 80),
                "tradition": safe_text(raw.get("tradition", ""), 120),
                "color": color,
                "coreConcepts": safe_string_list(raw.get("coreConcepts", []), 8, 60),
                "topics": safe_string_list(raw.get("topics", []), 10, 40),
                "stance": sanitize_stance(raw.get("stance", {})),
                "voice": safe_text(raw.get("voice", ""), 220),
                "summary": safe_text(raw.get("summary", ""), 300),
                "opening": safe_text(raw.get("opening", ""), 420),
                "questionHooks": safe_string_list(raw.get("questionHooks", []), 6, 120),
                "evidenceBasis": safe_string_list(raw.get("evidenceBasis", []), 8, 80),
                "needsReview": True,
                "humanDecision": "pending",
            }
        )
    return output


def sanitize_stance(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {key: clamp_float(value.get(key, 0), -1, 1) for key in STANCE_KEYS if key in value}


def labels(items: list[dict[str, str]]) -> list[str]:
    return [(item.get("labelZh") or item.get("labelEn") or item.get("qid", "")).strip() for item in items if item]


def call_openrouter(api_key: str, model: str, messages: list[dict[str, str]]) -> str:
    body = json.dumps(
        {
            "model": model,
            "temperature": 0.18,
            "max_tokens": 9000,
            "messages": messages,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Title": "Philophany philosopher card generation",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=160) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {error.code}: {details}") from error

    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("OpenRouter returned an empty response.")
    return content


def parse_model_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise
        return json.loads(match.group(0))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    main()
