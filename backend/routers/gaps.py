from fastapi import APIRouter, HTTPException, Depends
from typing import List
from backend.core.models import GapQuery, Entity
from backend.repository.database import db
from backend.services.nlp_extractor import NLPExtractor
from backend.core.prompts import load_prompt
from backend.routers.dependencies import UserSession, require_roles

router = APIRouter(prefix="/api", tags=["Gap Analysis"])

@router.post("/gaps")
async def find_gaps(
    query: GapQuery,
    session: UserSession = Depends(require_roles(["Administrator", "Analyst", "Researcher"]))
):
    """Analyzes missing combinations (gaps) in research dimensions."""
    try:
        db.log_action(
            username=session.username,
            role=session.role,
            action="GAP_ANALYSIS",
            details=f"Поиск пробелов по измерениям: {query.dimensions}"
        )
        gaps = db.analyze_gaps(query.dimensions)
        return gaps
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/enrich-gap")
async def enrich_gap(
    gap_config: List[Entity],
    session: UserSession = Depends(require_roles(["Administrator", "Analyst"]))
):
    """Extrapolates property values and generates a hypothesis for a missing configuration using Qwen 3.6 35B."""
    db.log_action(
        username=session.username,
        role=session.role,
        action="GAP_ENRICHMENT",
        details=f"Синтез гипотезы для пробела: {', '.join([f'{e.type}:{e.value}' for e in gap_config])}"
    )
    config_desc = ", ".join([f"{e.type}: {e.value}" for e in gap_config])
    
    dimensions = [e.type for e in gap_config]
    all_gaps = db.analyze_gaps(dimensions)
    
    matching_gap = None
    for gap in all_gaps:
        gap_map = {e.type: e.value for e in gap["configuration"]}
        if all(gap_map.get(e.type) == e.value for e in gap_config):
            matching_gap = gap
            break
            
    if not matching_gap:
        return {
            "configuration": gap_config,
            "hypothesis": f"Конфигурация [{config_desc}] не является пробелом (уже исследована)."
        }
        
    predicted_props = matching_gap["predicted_properties"]
    prop_desc = ", ".join([f"{p.type} ~ {p.value}" for p in predicted_props]) if predicted_props else "Неизвестно"
    
    similar_ids = matching_gap["similar_experiments"]
    sim_details = []
    for sid in similar_ids:
        sexp = db.experiments[sid]
        inputs = ", ".join([f"{e.value}" for e in sexp.input_entities if e.type in dimensions])
        outputs = ", ".join([f"{e.type}={e.value}" for e in sexp.output_entities])
        sim_details.append(f"  * {sexp.id} ({inputs}) -> {outputs}")
        
    sim_context = "\n".join(sim_details) if sim_details else "  * Нет близких базовых экспериментов."
    
    prompt_config = load_prompt("gaps_enrich")
    prompt = prompt_config["user"].format(
        config_desc=config_desc,
        prop_desc=prop_desc,
        sim_context=sim_context,
    )
    
    try:
        extractor = NLPExtractor()
        response = await extractor.client.chat.completions.create(
            model=extractor.model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000
        )
        hypothesis = response.choices[0].message.content
        return {
            "configuration": gap_config,
            "predicted_properties": predicted_props,
            "hypothesis": hypothesis
        }
    except Exception as e:
        print(f"Gap enrichment LLM call failed: {e}")
        fallback_hyp = (
            f"### Научная гипотеза для: [{config_desc}]\n\n"
            f"**Прогнозируемые свойства**:\n- {prop_desc}\n\n"
            f"**Обоснование**:\n"
            f"На основе VSA топологического анализа выявлены близкие к пробелу опыты:\n{sim_context}\n\n"
            f"Рекомендуется провести физический эксперимент при данных условиях для подтверждения стабильности manifold-структуры."
        )
        return {
            "configuration": gap_config,
            "predicted_properties": predicted_props,
            "hypothesis": fallback_hyp
        }
