import os
import asyncio
from typing import List, Dict, Any
from backend.services.document_parser import DocumentParser
from backend.services.nlp_extractor import NLPExtractor
from backend.core.models import Entity, Experiment, Relation
from backend.repository.database import HSMEVectorDatabase, db

class IngestionPipeline:
    def __init__(self, db: HSMEVectorDatabase, concurrency_limit: int = 8):
        self.db = db
        self.parser = DocumentParser()
        self.extractor = NLPExtractor()
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    def guess_geography(self, text: str, filename: str) -> str:
        """Guesses the geographical context of the document (RU or Global)."""
        combined = (text + " " + filename).lower()
        ru_keywords = ["россия", "кольский", "гмк", "комсомольский", "кайерканский", "норильск", "сибирь", "урал", "черняевск"]
        global_keywords = ["australia", "caledonia", "chile", "harbour", "glencore", "eramet", "outotec", "valegoro"]
        
        ru_score = sum(1 for kw in ru_keywords if kw in combined)
        global_score = sum(1 for kw in global_keywords if kw in combined)
        
        if ru_score > global_score:
            return "RU"
        elif global_score > ru_score:
            return "Global"
        return "RU" if any(c in combined for c in "абвгдежзийклмнопрстуфхцчшщъыьэюя") else "Global"

    def classify_entities(self, entities: List[Dict[str, str]]) -> tuple[List[Entity], List[Entity], List[Entity]]:
        """Classifies extracted flat entities into inputs, processes, and outputs for the Experiment model."""
        inputs = []
        processes = []
        outputs = []
        
        for ent in entities:
            e_type = ent.get("type", "Property")
            e_val = ent.get("value", "").strip()
            if not e_val:
                continue
                
            entity_obj = Entity(type=e_type, value=e_val)
            
            # Classification logic based on semantics
            if e_type in ["Material", "Facility"]:
                # If it's a product, put in outputs
                if any(kw in e_val.lower() for kw in ["катод", "осадок", "раствор ni-cu", "шлам", "хвосты", "продукт", "выход"]):
                    outputs.append(entity_obj)
                else:
                    inputs.append(entity_obj)
            elif e_type in ["Process", "Equipment"]:
                processes.append(entity_obj)
            elif e_type == "Property":
                # If it contains performance metric words, it is an output
                if any(kw in e_val.lower() for kw in ["выход по току", "светлость", "извлечение", "чистота", "содержание", "дефект", "производительность"]):
                    outputs.append(entity_obj)
                else:
                    inputs.append(entity_obj)
            else:
                inputs.append(entity_obj)
                
        return inputs, processes, outputs

    async def process_chunk(self, chunk: Dict[str, Any], doc_meta: Dict[str, Any]) -> None:
        """Processes a single text chunk, extracts data from LLM, and stores as an experiment."""
        async with self.semaphore:
            text = chunk["text"]
            res = await self.extractor.extract_entities_and_relations(text)
            
            if not res.get("entities"):
                return
                
            inputs, processes, outputs = self.classify_entities(res["entities"])
            
            # Skip if we got zero relevant entities
            if not inputs and not processes and not outputs:
                return
                
            # Add Publication and Expert if available in metadata
            publication_title = doc_meta["title"]
            inputs.append(Entity(type="Publication", value=publication_title))
            for auth in doc_meta["authors"]:
                if auth != "Не указан":
                    processes.append(Entity(type="Expert", value=auth))

            # Guess geography
            geography = self.guess_geography(text, doc_meta["filename"])
            
            # Extract relations
            relations = []
            for rel in res.get("relations", []):
                source = rel.get("source", "").strip()
                rel_type = rel.get("type", "").strip()
                target = rel.get("target", "").strip()
                if source and rel_type and target:
                    relations.append(Relation(source=source, type=rel_type, target=target))
            
            # Format experiment
            exp_id = f"EXP-{doc_meta['code']}-{chunk['index']:02d}".replace("N/A", "RAW")
            exp_name = f"{doc_meta['title']} (Раздел {chunk['section'] or 'Введение'}, Чанк {chunk['index']})"
            
            experiment = Experiment(
                id=exp_id,
                name=exp_name,
                input_entities=inputs,
                process_entities=processes,
                output_entities=outputs,
                relations=relations,
                evidence=[doc_meta["filename"]],
                confidence=0.95,
                year=doc_meta["year"],
                geography=geography,
                source_type=doc_meta["source_type"]
            )
            
            self.db.insert_experiment(experiment)

    async def ingest_file(self, file_path: str, source_type: str) -> int:
        """Parses a single file, processes all its chunks concurrently, and indexes them."""
        doc = self.parser.parse_file(file_path)
        if not doc or not doc["chunks"]:
            return 0
            
        doc["source_type"] = source_type
        
        # Process all chunks concurrently
        tasks = [self.process_chunk(chunk, doc) for chunk in doc["chunks"]]
        await asyncio.gather(*tasks)
        return len(doc["chunks"])

    async def ingest_directory(self, base_dir: str, max_files: int = 15, progress_callback = None) -> Dict[str, Any]:
        """Scans directory and indexes up to max_files of high-priority research documents."""
        files = self.parser.scan_directory(base_dir)
        
        # Sort files to put 'Обзоры' and 'Статьи' first
        files.sort(key=lambda x: 0 if "Обзоры" in x else (1 if "Статьи" in x else 2))
        
        indexed_count = 0
        total_chunks = 0
        indexed_files = []
        
        for file in files:
            if indexed_count >= max_files:
                break
                
            # Determine source category
            source_type = "Статья"
            if "Обзоры" in file:
                source_type = "Обзор"
            elif "Доклады" in file:
                source_type = "Доклад"
            elif "Журналы" in file:
                source_type = "Журнал"
                
            print(f"Indexing [{source_type}] {os.path.basename(file)}...")
            chunks_count = await self.ingest_file(file, source_type)
            if chunks_count > 0:
                indexed_count += 1
                total_chunks += chunks_count
                indexed_files.append(file)
                if progress_callback:
                    progress_callback(file, chunks_count)
                
        return {
            "files_indexed_count": indexed_count,
            "total_chunks_indexed": total_chunks,
            "indexed_files": indexed_files,
            "total_experiments_in_db": len(self.db.experiments)
        }

# Instantiate global ingestion pipeline
pipeline = IngestionPipeline(db, concurrency_limit=6)
