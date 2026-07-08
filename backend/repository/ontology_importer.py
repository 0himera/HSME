"""Import mining/metallurgy ontology landmarks into VSA codebook and Neo4j."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from typing import Any

import httpx

from backend.core.models import Entity
from backend.repository.database import HSMEVectorDatabase, db
from backend.repository.neo4j_graph import neo4j_graph

logger = logging.getLogger(__name__)

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_USER_AGENT = "HSME-Bot/1.0 (contact: support@hsme-research.org)"

STATIC_METALLURGY_ONTOLOGY: dict[str, list[str]] = {
    "Material": [
        "Никель",
        "Nickel",
        "Медь",
        "Copper",
        "Кобальт",
        "Cobalt",
        "Железо",
        "Iron",
        "Халькопирит",
        "Chalcopyrite",
        "Пентландит",
        "Pentlandite",
        "Борнит",
        "Bornite",
        "Хлоридный электролит никеля",
        "Chloride nickel electrolyte",
        "Серная кислота",
        "Sulfuric acid",
    ],
    "Process": [
        "Электроэкстракция",
        "Electrowinning",
        "Кучное выщелачивание",
        "Heap leaching",
        "Автоклавное окисление",
        "Autoclave oxidation",
        "Флотация",
        "Flotation",
        "Автогенная плавка",
        "Smelting",
        "Обезмеживание",
        "Copper removal",
    ],
    "Equipment": [
        "Ванна электроэкстракции",
        "Electrowinning bath",
        "Автоклав",
        "Autoclave",
        "Печь Ванюкова",
        "Vanyukov furnace",
        "Флотационная машина",
        "Flotation cell",
        "Шаровая мельница",
        "Ball mill",
    ],
    "Facility": [
        "Кольская ГМК",
        "Kola MMC",
        "Завод Long Harbour",
        "Long Harbour Plant",
        "рудник Кайерканский",
        "Kayerkansky mine",
        "Надеждинский металлургический завод",
    ],
}

PROCESS_KEYWORDS = (
    "процесс",
    "выщелачивание",
    "плавка",
    "extraction",
    "leaching",
    "smelting",
    "flotation",
    "electrowinning",
)
EQUIPMENT_KEYWORDS = (
    "печь",
    "мельница",
    "ванна",
    "furnace",
    "mill",
    "bath",
    "cell",
    "autoclave",
)
FACILITY_KEYWORDS = (
    "рудник",
    "завод",
    "гмк",
    "mine",
    "plant",
    "harbour",
    "facility",
)


def _label_has_keyword(label: str, keywords: tuple[str, ...]) -> bool:
    tokens = re.findall(r"[a-zа-яё0-9]+", label.lower())
    token_set = set(tokens)
    for keyword in keywords:
        if " " in keyword:
            if keyword in label.lower():
                return True
            continue
        if keyword in token_set:
            return True
    return False


def classify_wikidata_label(label: str) -> str:
    if _label_has_keyword(label, PROCESS_KEYWORDS):
        return "Process"
    if _label_has_keyword(label, EQUIPMENT_KEYWORDS):
        return "Equipment"
    if _label_has_keyword(label, FACILITY_KEYWORDS):
        return "Facility"
    return "Material"


def build_entities_from_ontology(data: dict[str, list[str]]) -> list[Entity]:
    entities: list[Entity] = []
    for ent_type, values in data.items():
        for value in values:
            cleaned = value.strip()
            if cleaned:
                entities.append(Entity(type=ent_type, value=cleaned))
    return entities


async def fetch_wikidata_ontology(limit: int = 100) -> dict[str, list[str]]:
    """Fetch mining and metallurgical concepts using the Wikidata SPARQL API."""
    query = f"""
    SELECT ?item ?itemLabel WHERE {{
      ?item wdt:P279 ?class .
      VALUES ?class {{ wd:Q191943 wd:Q11425 wd:Q7944 }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ru,en". }}
    }}
    LIMIT {limit}
    """
    headers = {
        "User-Agent": WIKIDATA_USER_AGENT,
        "Accept": "application/sparql-results+json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            WIKIDATA_SPARQL_URL,
            params={"query": query},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()

    fetched: dict[str, list[str]] = {
        "Material": [],
        "Process": [],
        "Equipment": [],
        "Facility": [],
    }
    seen: set[str] = set()
    for row in payload.get("results", {}).get("bindings", []):
        label = row.get("itemLabel", {}).get("value", "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        ent_type = classify_wikidata_label(label)
        fetched[ent_type].append(label)
    return fetched


async def import_ontology(
    *,
    source: str = "static",
    database: HSMEVectorDatabase | None = None,
    write_neo4j: bool | None = None,
) -> dict[str, Any]:
    """Seed ontology landmarks into VSA codebook and optionally Neo4j."""
    target_db = database or db
    logger.info("Starting ontology import using source: %s", source)

    if source == "wikidata":
        try:
            data = await fetch_wikidata_ontology()
            logger.info("Fetched Wikidata ontology terms.")
        except Exception as exc:
            logger.warning("Wikidata SPARQL failed, falling back to static ontology: %s", exc)
            data = STATIC_METALLURGY_ONTOLOGY
    else:
        data = STATIC_METALLURGY_ONTOLOGY

    entities = build_entities_from_ontology(data)
    for entity in entities:
        target_db.get_or_create_vector(entity.to_key())

    logger.info("Registered %d entities in VSA codebook.", len(entities))
    target_db.save_to_disk(target_db.db_filepath)

    neo4j_enabled = neo4j_graph.is_configured if write_neo4j is None else write_neo4j
    neo4j_count = 0
    if neo4j_enabled:
        try:
            neo4j_count = await neo4j_graph.insert_ontology_entities_async(entities)
            logger.info("Pre-populated %d ontology nodes in Neo4j.", neo4j_count)
        except Exception as exc:
            logger.warning("Failed to populate Neo4j ontology: %s", exc)

    return {
        "source": source,
        "entity_count": len(entities),
        "codebook_size": len(target_db.codebook),
        "neo4j_nodes_written": neo4j_count,
        "types": {ent_type: len(values) for ent_type, values in data.items()},
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import mining ontology into VSA and Neo4j.")
    parser.add_argument("--source", choices=["static", "wikidata"], default="static")
    parser.add_argument("--no-neo4j", action="store_true", help="Skip Neo4j landmark writes")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    result = asyncio.run(
        import_ontology(
            source=args.source,
            write_neo4j=not args.no_neo4j,
        )
    )
    print(
        "Ontology import complete: "
        f"source={result['source']} entities={result['entity_count']} "
        f"codebook={result['codebook_size']} neo4j={result['neo4j_nodes_written']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
