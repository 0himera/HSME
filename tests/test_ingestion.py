import asyncio
import os
from backend.repository.database import HSMEVectorDatabase
from backend.services.ingestion import IngestionPipeline

async def main():
    db = HSMEVectorDatabase(dim=10000)
    pipeline = IngestionPipeline(db, concurrency_limit=5)
    
    # Target files to index for the test
    test_files = [
        "data/Задача 2. Научный клубок/Источники информации/Обзоры/Электроэкстракция никеля. Влияние состава электролита.docx",
        "data/Задача 2. Научный клубок/Источники информации/Обзоры/ТИ-5-2017. Кучное выщелачивание в условиях холодного климата.pdf"
    ]
    
    print("Starting integration ingestion test on 2 files...")
    for f in test_files:
        assert os.path.exists(f), f"Test file {f} not found"
        source_type = "Обзор"
        print(f"Indexing: {f}")
        chunks_count = await pipeline.ingest_file(f, source_type)
        print(f"Parsed {chunks_count} chunks.")
        
    print("\n--- INGESTION REPORT ---")
    print(f"Total experiments loaded: {len(db.experiments)}")
    print(f"Codebook size: {len(db.codebook)} distinct entities/roles")
    
    assert len(db.experiments) > 0
    assert len(db.codebook) > 20
    
    # Check some experiments
    sample_exp = list(db.experiments.values())[0]
    print(f"\nSample Experiment ID: {sample_exp.id}")
    print(f"Name: {sample_exp.name}")
    print(f"Year: {sample_exp.year}")
    print(f"Geography: {sample_exp.geography}")
    print("Inputs:")
    for e in sample_exp.input_entities[:5]:
        print(f"  [{e.type}] -> {e.value}")
    print("Outputs:")
    for e in sample_exp.output_entities[:5]:
        print(f"  [{e.type}] -> {e.value}")
        
    # Test a search over the newly ingested database!
    print("\nRunning VSA query search for 'электроэкстракция никеля'...")
    from backend.core.models import Entity
    query = [
        Entity(type="Process", value="Электроэкстракция"),
        Entity(type="Material", value="никель")
    ]
    results = db.search(query, limit=3)
    print("\nSearch results:")
    for exp, score in results:
        print(f" - {exp.id} (Score: {score:.3f}): {exp.name}")
        
if __name__ == "__main__":
    asyncio.run(main())
