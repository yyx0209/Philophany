#!/usr/bin/env python3
"""
Generate exampleStyle proposals for philosopher cards with OpenRouter.

This script creates a review workspace only. Proposed example styles default to
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

from graph_data_io import load_card_bundle, normalize_example_style, safe_id, safe_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARDS = ROOT / "data" / "generated" / "reviewed_philosopher_cards.json"
DEFAULT_OUTPUT = ROOT / "data" / "generated" / "reviewed_example_styles.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
ALLOWED_MODES = [
    "dialogue_situation",
    "practical_scene",
    "parable",
    "ritual_relationship",
    "suffering_diagnosis",
    "daily_observation",
    "principle_test",
    "historical_mediation",
    "genealogical_scene",
    "existential_choice",
    "language_game",
    "inner_experience",
    "ascent_analogy",
]
ALLOWED_FREQUENCIES = ["high", "medium", "low"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reviewed exampleStyle proposals with OpenRouter.")
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
        model_styles=parsed.get("exampleStyles", []),
        input_file=str(args.cards),
        model=args.model,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Proposed example styles: {output['metadata']['proposedCount']}")
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
            "speechPersona": card.get("speechPersona", {}),
            "summary": card.get("summary", ""),
            "opening": card.get("opening", ""),
            "questionHooks": card.get("questionHooks", []),
        }
        for card in cards
    ]
    output_shape = {
        "exampleStyles": [
            {
                "id": "kant",
                "exampleStyle": {
                    "mode": "principle_test",
                    "frequency": "low",
                    "canDebateOnExample": True,
                    "preferredExampleForms": ["承诺、撒谎、利用他人的准则测试", "义务与利益冲突的小情境"],
                    "avoidExampleForms": ["把例子当作道德直觉裁判", "让情境例外替代普遍化检验"],
                    "signatureExample": "用承诺或撒谎的小情境测试准则能否普遍化、是否把人仅当工具。",
                },
                "llmReason": "说明为什么这种例子形态符合这位哲学家的方法，同时如何避免误导。",
            }
        ]
    }
    return [
        {
            "role": "system",
            "content": "\n".join(
                [
                    "你是 Philophany 的哲学对话设计师。",
                    "你的任务是为每位哲学家生成 exampleStyle，让他们在思想圆桌中用符合自身方法的例子、反例或小情境帮助普通用户理解抽象分歧。",
                    "不同哲学家使用例子的方式是不对称的：有人天然用例子，有人只适合少量准则测试，有人更适合分析别人例子的结构。",
                    "不要编造具体名言、页码、章节、真实人物轶事或历史场景。signatureExample 只能描述例子类型，不得伪装成原文引用。",
                    "必须只返回合法 JSON，不要 Markdown，不要代码块。",
                ]
            ),
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    "为下面每位哲学家生成 exampleStyle。",
                    "",
                    "每个 exampleStyle 必须包含：",
                    f"- mode：只能从这些值中选一个：{', '.join(ALLOWED_MODES)}。",
                    f"- frequency：只能从这些值中选一个：{', '.join(ALLOWED_FREQUENCIES)}。",
                    "- canDebateOnExample：是否适合直接围绕别人提出的例子争论。",
                    "- preferredExampleForms：1 到 2 个偏好的例子形态。",
                    "- avoidExampleForms：1 到 2 个应避免的例子形态。",
                    "- signatureExample：一句中文，描述这位哲学家最自然的例子入口。",
                    "",
                    "设计原则：",
                    "- 苏格拉底、亚里士多德、孔子、庄子、萨特通常可以高频使用例子。",
                    "- 休谟、尼采、佛陀、王阳明通常可以中频使用例子，但例子形态必须贴合他们的方法。",
                    "- 康德、黑格尔、维特根斯坦通常低频使用例子，更适合少量测试、结构分析或语言使用小场景。",
                    "- 如果上一条发言包含具体例子，下一位哲学家可以用同一个例子给出不同结论、提出反例、指出预设，或说明例子为什么误导。",
                    "- 例子不能替代论证；例子必须服务于用户原问题，不能劫持讨论。",
                    "- 不要把所有人都写成“日常生活例子”；每个人的例子风格要明显不同。",
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
    model_styles: list[dict[str, Any]],
    input_file: str,
    model: str,
) -> dict[str, Any]:
    cards_by_id = {safe_id(card.get("id", "")): card for card in cards}
    styles_by_id = {safe_id(item.get("id", "")): item for item in model_styles if safe_id(item.get("id", "")) in cards_by_id}
    reviews = []
    for philosopher_id, card in cards_by_id.items():
        proposal = styles_by_id.get(philosopher_id, {})
        style = normalize_example_style(proposal.get("exampleStyle", {}))
        if not style:
            continue
        reviews.append(
            {
                "id": philosopher_id,
                "name": card.get("name", ""),
                "currentVoice": card.get("voice", ""),
                "currentSpeechPersona": card.get("speechPersona", {}),
                "proposedExampleStyle": style,
                "llmReason": safe_text(proposal.get("llmReason", ""), 260),
                "evidenceBasis": {
                    "tradition": card.get("tradition", ""),
                    "coreConcepts": card.get("coreConcepts", []),
                    "summary": card.get("summary", ""),
                    "voice": card.get("voice", ""),
                    "speechPersona": card.get("speechPersona", {}),
                },
                "humanDecision": "pending",
            }
        )

    return {
        "metadata": {
            "source": "openrouter_example_style_generation",
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
            "temperature": 0.35,
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
