from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


ALLOWED_RELATION_TYPES = {"affinity", "tension", "influence"}
ALLOWED_PERSONA_MOVES = {"打断", "反问", "拒答", "重框", "挑衅", "缓和", "翻译成人话"}
ALLOWED_EXAMPLE_MODES = {
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
}
ALLOWED_EXAMPLE_FREQUENCIES = {"high", "medium", "low"}


def load_card_bundle(path: Path, approved_only: bool = True) -> dict[str, Any]:
    if str(path).endswith(".js"):
        return load_data_js(path)
    data = read_json(path)
    if "philosophers" in data:
        raw_cards = data.get("philosophers", [])
    elif "cards" in data:
        raw_cards = data.get("cards", [])
    elif "reviews" in data:
        raw_cards = [item.get("card", item) for item in data.get("reviews", [])]
    else:
        raw_cards = []

    cards = [normalize_card(card) for card in raw_cards if include_review_item(card, approved_only)]
    cards = [card for card in cards if card.get("id")]
    return {
        "dimensions": data.get("dimensions", []),
        "topics": data.get("topics", []),
        "philosophers": cards,
        "relations": normalize_relations(data.get("relations", [])),
    }


def load_existing_relations(path: Path | None, philosopher_ids: set[str] | None = None) -> list[dict[str, Any]]:
    if not path:
        return []
    if str(path).endswith(".js"):
        return normalize_relations(load_data_js(path).get("relations", []), philosopher_ids)
    data = read_json(path)
    if "reviews" in data:
        relations, _ = approved_relations_from_reviews(data, philosopher_ids=philosopher_ids)
        return relations
    return normalize_relations(data.get("relations", []), philosopher_ids)


def approved_relations_from_reviews(
    reviewed: dict[str, Any],
    philosopher_ids: set[str] | None = None,
    existing_pairs: set[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen_pairs = set(existing_pairs or set())
    output = []
    skipped = []
    for review in reviewed.get("reviews", []):
        source = safe_id(review.get("source", ""))
        target = safe_id(review.get("target", ""))
        proposed = review.get("proposedRelation")
        if review.get("humanDecision") != "approve":
            skipped.append({"source": source, "target": target, "reason": "not approved"})
            continue
        if philosopher_ids is not None and (source not in philosopher_ids or target not in philosopher_ids):
            skipped.append({"source": source, "target": target, "reason": "invalid philosopher id"})
            continue
        if source == target:
            skipped.append({"source": source, "target": target, "reason": "self relation"})
            continue
        if not isinstance(proposed, dict):
            skipped.append({"source": source, "target": target, "reason": "missing proposedRelation"})
            continue
        relation_type = safe_relation_type(proposed.get("type", ""))
        if not relation_type:
            skipped.append({"source": source, "target": target, "reason": "unsupported relation type"})
            continue
        pair = pair_key(source, target)
        if pair in seen_pairs:
            skipped.append({"source": source, "target": target, "reason": "duplicate pair"})
            continue
        reason = safe_text(proposed.get("reason", ""), 260)
        if not reason:
            skipped.append({"source": source, "target": target, "reason": "missing reason"})
            continue
        seen_pairs.add(pair)
        output.append(
            {
                "source": source,
                "target": target,
                "type": relation_type,
                "weight": clamp_float(proposed.get("weight", 0.5), 0, 1),
                "reason": reason,
            }
        )
    return output, skipped


def normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "id": safe_id(card.get("id", "")),
        "name": safe_text(card.get("name", ""), 80),
        "era": safe_text(card.get("era", ""), 80),
        "tradition": safe_text(card.get("tradition", ""), 120),
        "color": safe_text(card.get("color", ""), 40),
        "coreConcepts": safe_string_list(card.get("coreConcepts", []), 10, 60),
        "topics": safe_string_list(card.get("topics", []), 12, 40),
        "stance": normalize_stance(card.get("stance", {})),
        "voice": safe_text(card.get("voice", ""), 220),
        "summary": safe_text(card.get("summary", ""), 300),
        "opening": safe_text(card.get("opening", ""), 420),
        "questionHooks": safe_string_list(card.get("questionHooks", []), 6, 120),
    }
    speech_persona = normalize_speech_persona(card.get("speechPersona", {}))
    if speech_persona:
        normalized["speechPersona"] = speech_persona
    example_style = normalize_example_style(card.get("exampleStyle", {}))
    if example_style:
        normalized["exampleStyle"] = example_style
    return normalized


def normalize_speech_persona(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    favorite_moves = [
        move for move in safe_string_list(value.get("favoriteMoves", []), 7, 20) if move in ALLOWED_PERSONA_MOVES
    ]
    sample_lines = safe_string_list(value.get("sampleLines", []), 2, 160)
    persona = {
        "temperament": safe_text(value.get("temperament", ""), 120),
        "favoriteMoves": favorite_moves,
        "responseToDisagreement": safe_text(value.get("responseToDisagreement", ""), 180),
        "sentenceRhythm": safe_text(value.get("sentenceRhythm", ""), 120),
        "overheatRisk": safe_text(value.get("overheatRisk", ""), 200),
        "sampleLines": sample_lines,
    }
    if not persona["temperament"] and not favorite_moves and not sample_lines:
        return {}
    return persona


def normalize_example_style(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    mode = safe_text(value.get("mode", ""), 60)
    frequency = safe_text(value.get("frequency", ""), 20)
    preferred_forms = safe_string_list(value.get("preferredExampleForms", []), 2, 80)
    avoid_forms = safe_string_list(value.get("avoidExampleForms", []), 2, 80)
    signature_example = safe_text(value.get("signatureExample", ""), 180)
    example_style = {
        "mode": mode if mode in ALLOWED_EXAMPLE_MODES else "practical_scene",
        "frequency": frequency if frequency in ALLOWED_EXAMPLE_FREQUENCIES else "medium",
        "canDebateOnExample": bool(value.get("canDebateOnExample", True)),
        "preferredExampleForms": preferred_forms,
        "avoidExampleForms": avoid_forms,
        "signatureExample": signature_example,
    }
    if not preferred_forms and not avoid_forms and not signature_example:
        return {}
    return example_style


def normalize_relations(
    relations: list[dict[str, Any]],
    philosopher_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for relation in relations:
        source = safe_id(relation.get("source", ""))
        target = safe_id(relation.get("target", ""))
        relation_type = safe_relation_type(relation.get("type", ""))
        if not source or not target or source == target or not relation_type:
            continue
        if philosopher_ids is not None and (source not in philosopher_ids or target not in philosopher_ids):
            continue
        pair = pair_key(source, target)
        if pair in seen:
            continue
        reason = safe_text(relation.get("reason", ""), 260)
        if not reason:
            continue
        seen.add(pair)
        output.append(
            {
                "source": source,
                "target": target,
                "type": relation_type,
                "weight": clamp_float(relation.get("weight", 0.5), 0, 1),
                "reason": reason,
            }
        )
    return output


def include_review_item(item: dict[str, Any], approved_only: bool) -> bool:
    decision = item.get("humanDecision")
    if not approved_only:
        return decision != "reject"
    if decision is None:
        return True
    return decision == "approve"


def normalize_stance(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    allowed = {"reasonInstinct", "individualCollective", "desireDiscipline", "moralUniversalism", "languageWorld"}
    output = {}
    for key, raw in value.items():
        if key not in allowed:
            continue
        output[key] = clamp_float(raw, -1, 1)
    return output


def safe_string_list(value: Any, limit: int, max_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output = []
    seen = set()
    for item in value:
        text = safe_text(item, max_length)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def load_data_js(data_js_path: Path) -> dict[str, Any]:
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


def safe_relation_type(value: Any) -> str:
    relation_type = str(value or "").strip()
    return relation_type if relation_type in ALLOWED_RELATION_TYPES else ""


def safe_id(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", str(value or "").strip())


def safe_text(value: Any, max_length: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:max_length]


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
