#!/usr/bin/env python3
"""
Generate speechPersona proposals for philosopher cards with OpenRouter.

This script creates a review workspace only. Proposed personae default to
humanDecision=pending and must be approved before they can be merged into cards.
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

from graph_data_io import load_card_bundle, normalize_speech_persona, safe_id, safe_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARDS = ROOT / "data" / "generated" / "reviewed_philosopher_cards.json"
DEFAULT_OUTPUT = ROOT / "data" / "generated" / "reviewed_speech_personas.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
ALLOWED_MOVES = ["打断", "反问", "拒答", "重框", "挑衅", "缓和", "翻译成人话"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reviewed speechPersona proposals with OpenRouter.")
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    card_bundle = load_card_bundle(args.cards)
    cards = card_bundle.get("philosophers", [])

    if args.dry_run:
        print(f"Cards: {len(cards)}")
        print(f"Model: {args.model}")
        print(f"Output: {args.output}")
        print("Human confirmation required before merge.")
        return

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is missing. Add it to .env or the environment.")

    raw = call_openrouter(api_key=api_key, model=args.model, messages=build_prompt(cards))
    parsed = parse_model_json(raw)
    output = build_review_output(
        cards=cards,
        model_personas=parsed.get("personas", []),
        input_file=str(args.cards),
        model=args.model,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Proposed personae: {output['metadata']['proposedCount']}")
    print("All proposals are pending human approval.")


def build_prompt(cards: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact_cards = [
        {
            "id": card.get("id", ""),
            "name": card.get("name", ""),
            "tradition": card.get("tradition", ""),
            "coreConcepts": card.get("coreConcepts", []),
            "topics": card.get("topics", []),
            "voice": card.get("voice", ""),
            "summary": card.get("summary", ""),
            "opening": card.get("opening", ""),
            "questionHooks": card.get("questionHooks", []),
        }
        for card in cards
    ]
    output_shape = {
        "personas": [
            {
                "id": "nietzsche",
                "speechPersona": {
                    "temperament": "挑衅、骄傲、厌恶廉价安慰。",
                    "favoriteMoves": ["挑衅", "反问", "重框"],
                    "responseToDisagreement": "遇到道德化反驳时会升级攻势，逼对方承认价值来源。",
                    "sentenceRhythm": "短句、格言式、有冲击力。",
                    "overheatRisk": "容易把复杂问题压成强弱二分，或把用户的脆弱误读成软弱。",
                    "sampleLines": [
                        "你先问问这是不是你的欲望，还是别人塞进你胸口的口号。",
                        "别急着把怯懦叫作美德。",
                    ],
                },
                "llmReason": "说明为什么这个 speechPersona 符合角色卡，同时如何避免漫画化。",
            }
        ]
    }
    return [
        {
            "role": "system",
            "content": "\n".join(
                [
                    "你是 Philophany 的哲学角色写作者。",
                    "你的任务是为每位哲学家生成 speechPersona，让圆桌对普通用户更有个性、更好看，但不牺牲思想准确性。",
                    "不要编造具体名言、页码、章节或历史场景。样例句只能是风格示例，不得伪装成原文引用。",
                    "必须只返回合法 JSON，不要 Markdown，不要代码块。",
                ]
            ),
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    "为下面每位哲学家生成 speechPersona。",
                    "",
                    "每个 speechPersona 必须包含：",
                    "- temperament：脾气。不是学术标签，而是这位哲学家在圆桌里的心理气质。",
                    "- favoriteMoves：惯用发言动作，只能从这些值中选 2 到 4 个：打断、反问、拒答、重框、挑衅、缓和、翻译成人话。",
                    "- responseToDisagreement：遇到反对时如何回应。",
                    "- sentenceRhythm：句子节奏。",
                    "- overheatRisk：容易过火的风险，用来提醒 prompt 不要漫画化。",
                    "- sampleLines：1 到 2 条中文样例句，风格鲜活，但不能像引文。",
                    "",
                    "安全边界：",
                    "- 可以锋利，但不能人身攻击用户。",
                    "- 可以不礼貌，但不能辱骂。",
                    "- 可以拒绝问题，但必须给出更好的问法。",
                    "- 可以打断别人，但不能歪曲别人。",
                    "",
                    "写作方向：",
                    "- 有趣来自脾气、画面、节奏和思想摩擦，不来自卖萌或段子化。",
                    "- 每个人都要有差异，不要都写成“温和解释”。",
                    "- 既要保留角色卡里的 voice，也要补出更具体的发言人格。",
                    "- 不要把尼采写成中二挑衅者，不要把庄子写成玄学谜语人，不要把康德写成道德教导主任。",
                    "",
                    "哲学家角色卡 JSON：",
                    json.dumps(compact_cards, ensure_ascii=False, indent=2),
                    "",
                    "输出格式：",
                    json.dumps(output_shape, ensure_ascii=False, indent=2),
                ]
            ),
        },
    ]


def build_review_output(
    cards: list[dict[str, Any]],
    model_personas: list[dict[str, Any]],
    input_file: str,
    model: str,
) -> dict[str, Any]:
    cards_by_id = {safe_id(card.get("id", "")): card for card in cards}
    proposals_by_id = {
        safe_id(item.get("id", "")): item for item in model_personas if safe_id(item.get("id", "")) in cards_by_id
    }
    reviews = []
    for philosopher_id, card in cards_by_id.items():
        proposal = proposals_by_id.get(philosopher_id, {})
        persona = normalize_speech_persona(proposal.get("speechPersona", {}))
        if not persona:
            continue
        reviews.append(
            {
                "id": philosopher_id,
                "name": card.get("name", ""),
                "currentVoice": card.get("voice", ""),
                "proposedSpeechPersona": persona,
                "llmReason": safe_text(proposal.get("llmReason", ""), 260),
                "evidenceBasis": {
                    "tradition": card.get("tradition", ""),
                    "coreConcepts": card.get("coreConcepts", []),
                    "summary": card.get("summary", ""),
                    "voice": card.get("voice", ""),
                },
                "humanDecision": "pending",
            }
        )

    return {
        "metadata": {
            "source": "openrouter_speech_persona_generation",
            "model": model,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "inputFile": input_file,
            "philosopherCount": len(cards_by_id),
            "proposedCount": len(reviews),
            "needsHumanConfirmation": True,
        },
        "reviews": reviews,
    }


def call_openrouter(api_key: str, model: str, messages: list[dict[str, str]]) -> str:
    body = json.dumps(
        {
            "model": model,
            "temperature": 0.45,
            "max_tokens": 6000,
            "messages": messages,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://127.0.0.1:5173",
            "X-Title": "Philophany",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {error.code}: {details}") from error
    content = payload.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError(f"OpenRouter returned empty content for model {model}.")
    return content


def parse_model_json(content: str) -> dict[str, Any]:
    trimmed = content.strip()
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", trimmed)
        if not match:
            raise
        return json.loads(match.group(0))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    main()
