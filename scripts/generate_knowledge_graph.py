#!/usr/bin/env python3
"""
Generate candidate Philophany knowledge graph data from Wikidata.

This script intentionally writes generated data to data/generated/ instead of
overwriting the curated app graph in data.js.
"""

from __future__ import annotations

import argparse
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = ROOT / "data" / "seeds" / "philosophers.json"
DEFAULT_OUTPUT = ROOT / "data" / "generated" / "wikidata_graph.json"

WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
WIKIDATA_SEARCH_URL = "https://www.wikidata.org/w/api.php"
USER_AGENT = "PhilophanyMVP/0.1 (local knowledge graph generation)"

PROPERTIES = {
    "P31": "instanceOf",
    "P106": "occupation",
    "P101": "field",
    "P135": "movement",
    "P737": "influencedBy",
    "P800": "notableWork",
    "P569": "birthDate",
    "P570": "deathDate",
    "P27": "country",
    "P1412": "languages",
}

NODE_RELATION_TYPES = {
    "movement": "belongs_to_movement",
    "field": "works_in_field",
    "influencedBy": "influenced_by",
    "notableWork": "created_work",
}


class WikidataClient:
    def __init__(self, delay: float = 0.12) -> None:
        self.delay = delay
        self.entity_cache: dict[str, dict[str, Any]] = {}

    def get_json(self, url: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead) as error:
                last_error = error
                time.sleep(0.8 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {url}: {last_error}")

    def resolve_qid(self, label: str) -> str:
        params = {
            "action": "wbsearchentities",
            "search": label,
            "language": "en",
            "format": "json",
            "limit": "1",
        }
        url = f"{WIKIDATA_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        data = self.get_json(url)
        time.sleep(self.delay)
        search = data.get("search") or []
        if not search:
            raise RuntimeError(f"No Wikidata entity found for {label!r}")
        return search[0]["id"]

    def entity(self, qid: str) -> dict[str, Any]:
        if qid in self.entity_cache:
            return self.entity_cache[qid]

        url = WIKIDATA_ENTITY_URL.format(qid=qid)
        data = self.get_json(url)
        time.sleep(self.delay)
        entity = data["entities"][qid]
        self.entity_cache[qid] = entity
        return entity

    def label(self, qid: str) -> dict[str, str]:
        entity = self.entity(qid)
        return entity_label(entity)


def entity_label(entity: dict[str, Any]) -> dict[str, str]:
    labels = entity.get("labels", {})
    return {
        "zh": labels.get("zh", labels.get("zh-hans", {})).get("value", ""),
        "en": labels.get("en", {}).get("value", ""),
    }


def entity_description(entity: dict[str, Any]) -> dict[str, str]:
    descriptions = entity.get("descriptions", {})
    return {
        "zh": descriptions.get("zh", descriptions.get("zh-hans", {})).get("value", ""),
        "en": descriptions.get("en", {}).get("value", ""),
    }


def sitelink(entity: dict[str, Any], key: str) -> str:
    site = entity.get("sitelinks", {}).get(key)
    if not site:
        return ""
    title = site.get("title", "")
    return f"https://{key.replace('wiki', '')}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"


def claim_values(entity: dict[str, Any], prop: str) -> list[dict[str, Any]]:
    values = []
    for claim in entity.get("claims", {}).get(prop, []):
        mainsnak = claim.get("mainsnak", {})
        datavalue = mainsnak.get("datavalue", {})
        value = datavalue.get("value")
        if value is None:
            continue

        if isinstance(value, dict) and value.get("entity-type") == "item":
            values.append({"type": "item", "qid": f"Q{value['numeric-id']}"})
        elif isinstance(value, dict) and "time" in value:
            values.append({"type": "time", "value": value["time"]})
        else:
            values.append({"type": "literal", "value": value})
    return values


def item_list(client: WikidataClient, entity: dict[str, Any], prop: str, max_items: int) -> list[dict[str, str]]:
    items = []
    for value in claim_values(entity, prop)[:max_items]:
        if value["type"] != "item":
            continue
        qid = value["qid"]
        labels = client.label(qid)
        items.append({"qid": qid, "labelZh": labels["zh"], "labelEn": labels["en"]})
    return dedupe_items(items)


def first_time(entity: dict[str, Any], prop: str) -> str:
    for value in claim_values(entity, prop):
        if value["type"] == "time":
            return value["value"]
    return ""


def dedupe_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    result = []
    for item in items:
        if item["qid"] in seen:
            continue
        seen.add(item["qid"])
        result.append(item)
    return result


def make_external_node(item: dict[str, str], kind: str) -> dict[str, str]:
    return {
        "id": f"wd:{item['qid']}",
        "qid": item["qid"],
        "type": kind,
        "labelZh": item["labelZh"],
        "labelEn": item["labelEn"],
    }


def build_graph(seeds: list[dict[str, Any]], client: WikidataClient, max_values_per_property: int) -> dict[str, Any]:
    philosophers = []
    nodes_by_id: dict[str, dict[str, str]] = {}
    relations = []
    qid_to_seed_id = {}

    for seed in seeds:
        qid = seed.get("wikidataId") or client.resolve_qid(seed["searchLabel"])
        print(f"Fetching {seed['id']} ({qid})...", flush=True)
        qid_to_seed_id[qid] = seed["id"]
        entity = client.entity(qid)
        labels = entity_label(entity)
        descriptions = entity_description(entity)

        movement = item_list(client, entity, "P135", max_values_per_property)
        field = item_list(client, entity, "P101", max_values_per_property)
        influenced_by = item_list(client, entity, "P737", max_values_per_property)
        notable_work = item_list(client, entity, "P800", max_values_per_property)

        philosopher = {
            "id": seed["id"],
            "seedName": seed["name"],
            "qid": qid,
            "labelZh": labels["zh"],
            "labelEn": labels["en"],
            "descriptionZh": descriptions["zh"],
            "descriptionEn": descriptions["en"],
            "wikipedia": {
                "zh": sitelink(entity, "zhwiki"),
                "en": sitelink(entity, "enwiki"),
            },
            "birthDate": first_time(entity, "P569"),
            "deathDate": first_time(entity, "P570"),
            "occupation": item_list(client, entity, "P106", max_values_per_property),
            "field": field,
            "movement": movement,
            "influencedBy": influenced_by,
            "notableWork": notable_work,
            "country": item_list(client, entity, "P27", max_values_per_property),
            "languages": item_list(client, entity, "P1412", max_values_per_property),
        }
        philosophers.append(philosopher)

        for key, kind in [("movement", "movement"), ("field", "field"), ("notableWork", "work")]:
            for item in philosopher[key]:
                nodes_by_id[f"wd:{item['qid']}"] = make_external_node(item, kind)
                relations.append(
                    {
                        "source": philosopher["id"],
                        "target": f"wd:{item['qid']}",
                        "type": NODE_RELATION_TYPES[key],
                        "sourceWikidata": qid,
                        "targetWikidata": item["qid"],
                        "evidence": "Wikidata claim",
                    }
                )

        for item in influenced_by:
            target = qid_to_seed_id.get(item["qid"], f"wd:{item['qid']}")
            if target.startswith("wd:"):
                nodes_by_id[target] = make_external_node(item, "philosopher")
            relations.append(
                {
                    "source": philosopher["id"],
                    "target": target,
                    "type": "influenced_by",
                    "sourceWikidata": qid,
                    "targetWikidata": item["qid"],
                    "evidence": "Wikidata P737",
                }
            )

    return {
        "metadata": {
            "source": "Wikidata",
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": "Generated candidate graph. Review before merging into curated app data.",
        },
        "philosophers": philosophers,
        "externalNodes": sorted(nodes_by_id.values(), key=lambda node: (node["type"], node["labelEn"])),
        "relations": relations,
    }


def load_seeds(path: Path, limit: int | None) -> list[dict[str, Any]]:
    seeds = json.loads(path.read_text(encoding="utf-8"))
    return seeds[:limit] if limit else seeds


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate candidate knowledge graph data from Wikidata.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-values-per-property", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true", help="Validate seeds and print planned work without network calls.")
    args = parser.parse_args()

    seeds = load_seeds(args.seed, args.limit or None)
    if args.dry_run:
        print(f"Seed file: {args.seed}")
        print(f"Output file: {args.output}")
        print(f"Philosophers: {len(seeds)}")
        for seed in seeds:
            qid = seed.get("wikidataId", "<resolve by label>")
            print(f"- {seed['id']}: {seed['name']} ({qid})")
        return

    client = WikidataClient()
    graph = build_graph(seeds, client, args.max_values_per_property)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Philosophers: {len(graph['philosophers'])}")
    print(f"External nodes: {len(graph['externalNodes'])}")
    print(f"Relations: {len(graph['relations'])}")


if __name__ == "__main__":
    main()
