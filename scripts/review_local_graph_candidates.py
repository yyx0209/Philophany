#!/usr/bin/env python3
"""
Review local philosopher relation candidates with an LLM.

The output is an audit workspace, not curated product data. A human must mark
items as approved before any merge script will write them into data.js.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from graph_data_io import load_card_bundle, load_existing_relations


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "generated" / "local_graph_candidates.json"
DEFAULT_OUTPUT = ROOT / "data" / "generated" / "reviewed_graph_relations.json"
DEFAULT_WIKIDATA_GRAPH = ROOT / "data" / "generated" / "wikidata_graph.json"
DEFAULT_WIKIPEDIA_CACHE = ROOT / "data" / "generated" / "wikipedia_philosophy_extracts.json"
DEFAULT_CARDS = ROOT / "data" / "generated" / "reviewed_philosopher_cards.json"
LEGACY_DATA_JS = ROOT / "data.js"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-5.5"
ALLOWED_DECISIONS = {"accept", "revise", "reject"}
ALLOWED_RELATION_TYPES = {"affinity", "tension", "influence"}
MIN_CONFIDENCE_BY_TIER = {
    "strong_candidate": 0.55,
    "medium_candidate": 0.62,
    "weak_candidate": 0.72,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Review local graph candidates with OpenRouter.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--wikidata", type=Path, default=DEFAULT_WIKIDATA_GRAPH)
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--existing-relations", type=Path, default=None)
    parser.add_argument("--data-js", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--wikipedia-cache", type=Path, default=DEFAULT_WIKIPEDIA_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    model = args.model or DEFAULT_MODEL
    local_candidates = read_json(args.input).get("candidateRelations", [])
    cards_path = args.data_js or args.cards
    card_bundle = load_card_bundle(cards_path)
    wikidata_graph = read_json(args.wikidata)
    wikipedia_cache = read_json(args.wikipedia_cache) if args.wikipedia_cache.exists() else {}
    cards = build_philosopher_cards(wikidata_graph, card_bundle, wikipedia_cache)
    philosopher_ids = {card["id"] for card in cards}
    existing_relations = (
        load_existing_relations(args.existing_relations, philosopher_ids=philosopher_ids)
        if args.existing_relations
        else card_bundle.get("relations", [])
    )

    if args.dry_run:
        print(f"Candidates: {len(local_candidates)}")
        print(f"Philosophers: {len(cards)}")
        print(f"Cards: {cards_path}")
        print(f"Existing curated relations: {len(existing_relations)}")
        print(f"Model: {model}")
        print(f"Batch size: {args.batch_size}")
        print(f"Output: {args.output}")
        print("Human confirmation required before merge.")
        return

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is missing. Add it to .env or the environment.")

    model_reviews = []
    for batch in chunked(local_candidates, max(1, args.batch_size)):
        messages = build_prompt(
            candidates=batch,
            cards=cards,
            existing_relations=existing_relations,
        )
        raw = call_openrouter(api_key=api_key, model=model, messages=messages)
        parsed = parse_model_json(raw)
        model_reviews.extend(parsed.get("reviews", []))
    output = build_review_output(
        candidates=local_candidates,
        model_reviews=model_reviews,
        philosopher_ids=philosopher_ids,
        existing_relations=existing_relations,
        input_file=str(args.input),
        model=model,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Reviewed candidates: {output['metadata']['candidateCount']}")
    print(f"Merge-ready suggestions pending human approval: {output['metadata']['acceptedCount']}")


def build_prompt(
    candidates: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    existing_relations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    cards_by_id = {card["id"]: card for card in cards}
    compact_candidates = []
    for candidate in candidates:
        source = safe_id(candidate.get("source", ""))
        target = safe_id(candidate.get("target", ""))
        compact_candidates.append(
            {
                "source": source,
                "target": target,
                "suggestedType": candidate.get("suggestedType", ""),
                "candidateSources": candidate.get("candidateSources", []),
                "candidateNotes": candidate.get("candidateNotes", []),
                "sourceCard": cards_by_id.get(source, {}),
                "targetCard": cards_by_id.get(target, {}),
                "localScore": candidate.get("retrievalScore", candidate.get("finalScore")),
                "retrievalScore": candidate.get("retrievalScore", candidate.get("finalScore")),
                "retrievalOnly": True,
                "relationEvidenceScore": candidate.get("relationEvidenceScore"),
                "qualityTier": candidate.get("qualityTier"),
                "semanticSimilarityScore": candidate.get("semanticSimilarityScore"),
                "semanticSimilarityRole": "retrieval_signal_only",
                "semanticSimilarityIsEvidence": False,
                "graphProximityScore": candidate.get("graphProximityScore"),
                "structuredEvidenceScore": candidate.get("structuredEvidenceScore"),
                "problemAxisScore": candidate.get("problemAxisScore"),
                "problemAxes": candidate.get("problemAxes", []),
                "stanceRelationHint": candidate.get("stanceRelationHint", ""),
                "sharedEvidence": candidate.get("sharedEvidence", []),
            }
        )
    compact_existing = [
        {
            "source": relation.get("source"),
            "target": relation.get("target"),
            "type": relation.get("type"),
            "reason": relation.get("reason", ""),
        }
        for relation in existing_relations
    ]

    return [
        {
            "role": "system",
            "content": "\n".join(
                [
                    "你是 Philophany 的哲学知识图谱审稿人。",
                    "本地算法只负责高召回初筛；你负责判断候选关系是否值得进入人工审核工作台。",
                    "semanticSimilarityScore 只能作为召回信号，不能作为 affinity、tension 或 influence 成立的证据。",
                    "affinity 和 tension 不要求历史上直接互相影响；只要同一核心问题上的互补或冲突足够清楚，就可以 accept/revise。",
                    "不要把词面重合当成思想关系。不要编造具体引文、页码、章节或历史事件。",
                    "必须只返回合法 JSON，不要 Markdown，不要代码块。",
                ]
            ),
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    "请逐条审核 localCandidates。每个候选必须返回一条 review。",
                    "",
                    "decision 只能是：",
                    "- accept：本地候选成立，proposedRelation 可直接作为人工审核候选。",
                    "- revise：本地候选有价值，但关系类型、方向或 reason 需要你改写。",
                    "- reject：关系太弱、太泛、重复、或没有足够哲学依据。",
                    "",
                    "proposedRelation.type 只能是 affinity、tension、influence：",
                    "- affinity：共享具体问题结构、方法或可互补。",
                    "- tension：在同一个核心问题上有清晰冲突；批判性关系先归入 tension。",
                    "- influence：必须有明确历史影响或谱系依据，不能只靠思想相似。",
                    "",
                    "额外要求：",
                    "1. 如果 candidate qualityTier 是 weak_candidate，只有把握很高时才 accept/revise。",
                    "2. 如果只共享“道德、自由、成功、行动”等大词，通常 reject。",
                    "3. 如果 pair 已在 existingRelations 中出现，必须 reject。",
                    "4. reason 必须中文一句话，说明这条边为什么有助于圆桌辩论。",
                    "5. 不要输出 critiques 类型；批判性张力用 tension。",
                    "6. 不要因为缺少直接历史影响而拒绝 affinity 或 tension；直接历史依据只对 influence 必需。",
                    "7. 优先看 relationEvidenceScore、problemAxes、sharedEvidence、stanceRelationHint 和角色卡内容；不要因为 semanticSimilarityScore 高就 accept。",
                    "8. 如果 embedding 高但 problemAxes、立场结构或历史/概念证据弱，通常 reject。",
                    "9. suggestedType 只是本地候选类型提示，不是最终结论；candidateSources 说明候选来自共享证据、立场对立或人工 prior。",
                    "10. candidateSources 包含 relation_prior 时，仍要审查 reason 是否哲学上成立，但不要因为本地分数低而直接 reject。",
                    "11. candidateSources 包含 stance_opposition 时，优先判断它是否构成同一问题上的 tension。",
                    "12. 不要把同属传统、学派谱系或后世发展自动改成 influence；如果 suggestedType 是 affinity 且 prior reason 表示同一传统亲缘，优先保持 affinity。",
                    "13. influence 只用于明确的直接影响、师承、文本刺激或非常清楚的历史影响关系；一般传统亲缘用 affinity。",
                    "",
                    "existingRelations:",
                    json.dumps(compact_existing, ensure_ascii=False, indent=2),
                    "",
                    "localCandidates:",
                    json.dumps(compact_candidates, ensure_ascii=False, indent=2),
                    "",
                    "输出格式：",
                    json.dumps(
                        {
                            "reviews": [
                                {
                                    "source": "kant",
                                    "target": "nietzsche",
                                    "decision": "accept",
                                    "proposedRelation": {
                                        "type": "tension",
                                        "weight": 0.86,
                                        "reason": "康德的普遍道德法则与尼采对普遍道德的谱系式怀疑形成清晰张力。",
                                    },
                                    "confidence": 0.82,
                                    "llmReason": "二者围绕道德普遍性有明确冲突，且能推动圆桌分歧。",
                                    "evidenceBasis": ["coreConcepts", "summary", "philosophical common knowledge"],
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


def build_review_output(
    candidates: list[dict[str, Any]],
    model_reviews: list[dict[str, Any]],
    philosopher_ids: set[str],
    existing_relations: list[dict[str, Any]],
    input_file: str,
    model: str,
) -> dict[str, Any]:
    existing_pairs = {pair_key(relation.get("source", ""), relation.get("target", "")) for relation in existing_relations}
    candidate_pairs = {pair_key(candidate.get("source", ""), candidate.get("target", "")) for candidate in candidates}
    raw_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for review in model_reviews:
        source = safe_id(review.get("source", ""))
        target = safe_id(review.get("target", ""))
        pair = pair_key(source, target)
        if source not in philosopher_ids or target not in philosopher_ids or source == target or pair not in candidate_pairs:
            continue
        raw_by_pair.setdefault(pair, review)

    reviews = []
    for candidate in candidates:
        source = safe_id(candidate.get("source", ""))
        target = safe_id(candidate.get("target", ""))
        pair = pair_key(source, target)
        local_score = clamp_float(candidate.get("retrievalScore", candidate.get("finalScore", 0)), 0, 1)
        quality_tier = safe_text(candidate.get("qualityTier", ""), 40)
        local_evidence = [safe_text(item, 80) for item in candidate.get("sharedEvidence", [])[:8]]
        raw = raw_by_pair.get(pair)

        base = {
            "source": source,
            "target": target,
            "localScore": local_score,
            "qualityTier": quality_tier,
            "localEvidence": local_evidence,
            "decision": "reject",
            "proposedRelation": None,
            "confidence": 0.0,
            "llmReason": "模型未返回此候选的有效审核结果。",
            "evidenceBasis": [],
            "humanDecision": "pending",
        }

        if source not in philosopher_ids or target not in philosopher_ids or source == target:
            base["llmReason"] = "候选包含非法哲学家 id。"
            reviews.append(base)
            continue
        if pair in existing_pairs:
            base["confidence"] = clamp_float((raw or {}).get("confidence", 1), 0, 1)
            base["llmReason"] = "该 pair 已经存在于正式图谱，不能重复合并。"
            reviews.append(base)
            continue
        if not raw:
            reviews.append(base)
            continue

        decision = safe_decision(raw.get("decision", ""))
        confidence = clamp_float(raw.get("confidence", 0), 0, 1)
        llm_reason = safe_text(raw.get("llmReason", ""), 360) or "模型未提供审核理由。"
        evidence_basis = [safe_text(item, 80) for item in raw.get("evidenceBasis", [])[:8]]
        base.update(
            {
                "decision": decision,
                "confidence": confidence,
                "llmReason": llm_reason,
                "evidenceBasis": evidence_basis,
            }
        )

        if decision == "reject":
            reviews.append(base)
            continue

        proposed = sanitize_proposed_relation(raw.get("proposedRelation", {}))
        if not proposed:
            base.update(
                {
                    "decision": "reject",
                    "proposedRelation": None,
                    "llmReason": append_reason(llm_reason, "模型给出的 proposedRelation 不合法。"),
                }
            )
            reviews.append(base)
            continue

        minimum_confidence = MIN_CONFIDENCE_BY_TIER.get(quality_tier, 0.72)
        if confidence < minimum_confidence:
            base.update(
                {
                    "decision": "reject",
                    "proposedRelation": None,
                    "llmReason": append_reason(
                        llm_reason,
                        f"{quality_tier or 'unknown'} 需要至少 {minimum_confidence:.2f} 的 LLM confidence。",
                    ),
                }
            )
            reviews.append(base)
            continue

        base["proposedRelation"] = proposed
        reviews.append(base)

    return {
        "metadata": {
            "source": "OpenRouter local candidate review",
            "model": model,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "inputFile": input_file,
            "candidateCount": len(candidates),
            "acceptedCount": sum(1 for review in reviews if review["decision"] in {"accept", "revise"} and review["proposedRelation"]),
            "needsHumanConfirmation": True,
        },
        "reviews": reviews,
    }


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), max(1, size))]


def sanitize_proposed_relation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    relation_type = safe_relation_type(value.get("type", ""))
    reason = safe_text(value.get("reason", ""), 260)
    if not relation_type or not reason:
        return None
    return {
        "type": relation_type,
        "weight": clamp_float(value.get("weight", 0.5), 0, 1),
        "reason": reason,
    }


def build_philosopher_cards(
    wikidata_graph: dict[str, Any],
    curated: dict[str, Any],
    wikipedia_cache: dict[str, Any],
) -> list[dict[str, Any]]:
    curated_by_id = {person["id"]: person for person in curated.get("philosophers", [])}
    extracts = wikipedia_cache.get("extracts", {})
    cards = []
    for wd_person in wikidata_graph.get("philosophers", []):
        person_id = wd_person["id"]
        curated_person = curated_by_id.get(person_id, {})
        cached = extracts.get(person_id, {})
        extract = cached if isinstance(cached, str) else cached.get("extract", "")
        summary = cached if isinstance(cached, str) else cached.get("summary", "")
        cards.append(
            {
                "id": person_id,
                "name": curated_person.get("name") or wd_person.get("labelZh") or wd_person.get("labelEn"),
                "tradition": curated_person.get("tradition", ""),
                "coreConcepts": curated_person.get("coreConcepts", []),
                "topics": curated_person.get("topics", []),
                "stance": curated_person.get("stance", {}),
                "summary": curated_person.get("summary", ""),
                "wikidataDescription": wd_person.get("descriptionZh") or wd_person.get("descriptionEn", ""),
                "movement": labels(wd_person.get("movement", [])),
                "field": labels(wd_person.get("field", [])),
                "influencedBy": labels(wd_person.get("influencedBy", [])),
                "wikipediaSummary": summary[:800],
                "wikipediaExtract": extract[:1600],
            }
        )
    return cards


def call_openrouter(api_key: str, model: str, messages: list[dict[str, str]]) -> str:
    body = json.dumps(
        {
            "model": model,
            "temperature": 0.16,
            "max_tokens": 7200,
            "messages": messages,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Title": "Philophany local graph review",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
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


def load_curated_data(data_js_path: Path) -> dict[str, Any]:
    node = find_node()
    if not node:
        raise RuntimeError("node was not found. Set NODE or use the bundled Codex Node path.")

    code = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({json.dumps(str(data_js_path))}, 'utf8');
const sandbox = {{ window: {{}} }};
vm.createContext(sandbox);
vm.runInContext(code, sandbox, {{ filename: 'data.js' }});
console.log(JSON.stringify(sandbox.window.PHILOSOPHANY_DATA));
"""
    result = subprocess.run([node, "-e", code], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def find_node() -> str:
    candidates = [
        os.environ.get("NODE"),
        "node",
        "/Applications/Codex.app/Contents/Resources/node",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            subprocess.run([candidate, "--version"], capture_output=True, text=True, check=True)
            return candidate
        except (OSError, subprocess.CalledProcessError):
            continue
    return ""


def labels(items: list[dict[str, str]]) -> list[str]:
    return [(item.get("labelZh") or item.get("labelEn") or item.get("qid", "")).strip() for item in items if item]


def safe_decision(value: Any) -> str:
    decision = str(value or "").strip()
    return decision if decision in ALLOWED_DECISIONS else "reject"


def safe_relation_type(value: Any) -> str:
    relation_type = str(value or "").strip()
    return relation_type if relation_type in ALLOWED_RELATION_TYPES else ""


def safe_id(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", str(value or "").strip())


def safe_text(value: Any, max_length: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:max_length]


def append_reason(original: str, addition: str) -> str:
    if not original:
        return addition
    return f"{original} {addition}"


def clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, round(number, 3)))


def pair_key(source: Any, target: Any) -> tuple[str, str]:
    return tuple(sorted([safe_id(source), safe_id(target)]))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
