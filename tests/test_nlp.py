import asyncio
import pytest
from backend.services.nlp_extractor import NLPExtractor

def test_nlp_extractor_enrichment():
    extractor = NLPExtractor()
    text = "В процессе электроэкстракции никеля при температуре 60°C и pH = 2.5 достигается высокая чистота катодов."
    
    # Check regex enrichment directly
    data = {"entities": [], "relations": []}
    extractor._enrich_numeric_properties(text, data)
    
    values = [e["value"] for e in data["entities"]]
    assert "60°C" in values
    assert "pH = 2.5" in values
    print("\n[Test NLP Regex] Enrichment successful. Found:", values)

async def run_async_test():
    extractor = NLPExtractor()
    sample_text = (
        "ООО «Институт Гипроникель» провел исследование электроэкстракции никеля из сульфатных растворов. "
        "Эксперимент проводился в ваннах электроэкстракции при плотности тока 300 А/м2 и концентрации сульфатов 200 мг/л. "
        "Главный специалист Евграфова А.К. зафиксировала увеличение выхода металла."
    )
    
    print("\nCalling Yandex Cloud GPT 5.1 for NLP Extraction...")
    res = await extractor.extract_entities_and_relations(sample_text)
    
    assert res is not None
    assert "entities" in res
    assert "relations" in res
    
    print("--- EXTRACTED ENTITIES ---")
    for ent in res["entities"]:
        print(f"[{ent['type']}] -> {ent['value']}")
        
    print("--- EXTRACTED RELATIONS ---")
    for rel in res["relations"]:
        print(f"{rel['source']} --({rel['type']})--> {rel['target']}")
        
    # Check that some expected entities are present
    entity_values = [e["value"].lower() for e in res["entities"]]
    assert any("никель" in v for v in entity_values)
    assert any("электроэкстракция" in v for v in entity_values)
    assert any("300 а/м2" in v for v in entity_values)

if __name__ == "__main__":
    test_nlp_extractor_enrichment()
    asyncio.run(run_async_test())
