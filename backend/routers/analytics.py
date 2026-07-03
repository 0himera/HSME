from fastapi import APIRouter, HTTPException, Depends
from backend.repository.database import db
from backend.services.nlp_extractor import NLPExtractor
from backend.routers.dependencies import UserSession, require_roles

router = APIRouter(prefix="/api", tags=["Analytics & Reasoning"])

@router.get("/counterfactuals/{experiment_id}")
async def get_counterfactuals(
    experiment_id: str, 
    session: UserSession = Depends(require_roles(["Administrator", "Analyst", "Researcher"]))
):
    """Retrieves counterfactual experiments differing by exactly one parameter."""
    if experiment_id not in db.experiments:
        raise HTTPException(status_code=404, detail="Experiment not found")
        
    db.log_action(
        username=session.username,
        role=session.role,
        action="COUNTERFACTUALS",
        details=f"Запрос контрфактов для {experiment_id}"
    )
    return db.get_counterfactuals(experiment_id)

@router.get("/reason/{experiment_id}")
async def reason_causality(
    experiment_id: str,
    session: UserSession = Depends(require_roles(["Administrator", "Analyst"]))
):
    """Generates a causal explanation based on counterfactual analysis using Qwen 3.6 35B."""
    if experiment_id not in db.experiments:
        raise HTTPException(status_code=404, detail="Experiment not found")
        
    db.log_action(
        username=session.username,
        role=session.role,
        action="AI_REASON",
        details=f"Запуск причинно-следственного ИИ-анализа для {experiment_id}"
    )
    exp = db.experiments[experiment_id]
    cfs = db.get_counterfactuals(experiment_id)
    
    if not cfs:
        return {
            "experiment_id": experiment_id,
            "has_explanation": False,
            "explanation": f"В текущей базе данных не найдены контрфактические эксперименты для {experiment_id}. Попробуйте проиндексировать больше документов для нахождения связей."
        }
        
    cf_details = []
    for cf in cfs:
        cf_exp = cf["experiment"]
        diff = cf["difference"]
        effects = cf["effects"]
        
        eff_str = ", ".join([f"свойство '{e['property']}' изменилось с '{e['from']}' на '{e['to']}'" for e in effects])
        cf_details.append(
            f"- Сравнение с опытом {cf_exp.id} ('{cf_exp.name}'):\n"
            f"  Изменен параметр '{diff['parameter']}' с '{diff['from']}' на '{diff['to']}'.\n"
            f"  Наблюдаемые эффекты: {eff_str or 'без значительных изменений'}."
        )
        
    prompt = (
        f"Вы — ведущий научный аналитик в области горной металлургии. Проанализируйте следующие экспериментальные данные и составьте краткий научный отчет (2-3 абзаца) на русском языке о причинно-следственной связи между измененным параметром и свойствами продукта.\n\n"
        f"Исходный эксперимент: {exp.id} ('{exp.name}')\n"
        f"Контрфактические данные:\n"
        + "\n".join(cf_details) +
        f"\n\nОтчет должен объяснить физико-химический смысл наблюдаемого эффекта (почему изменение параметра приводит к такому изменению свойств) и сделать однозначный научный вывод."
    )
    
    try:
        extractor = NLPExtractor()
        response = await extractor.client.chat.completions.create(
            model="gpt://your_yandex_folder_id_here/yandexgpt-5.1/latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1000
        )
        report = response.choices[0].message.content
        return {
            "experiment_id": experiment_id,
            "has_explanation": True,
            "explanation": report
        }
    except Exception as e:
        print(f"Causal reasoning LLM call failed: {e}")
        # Fallback to local rule-based summary
        explanations = []
        for cf in cfs[:2]:
            cf_exp = cf["experiment"]
            diff = cf["difference"]
            effects = cf["effects"]
            
            eff_summary = "\n".join([f"• свойство '{e['property']}' изменилось с {e['from']} на {e['to']}" for e in effects])
            explanation = (
                f"Сравнение {exp.id} с {cf_exp.id}:\n"
                f"  - Параметр '{diff['parameter']}' изменен с {diff['from']} на {diff['to']}.\n"
                f"  - Эффекты:\n{eff_summary or '• без изменений'}\n"
            )
            explanations.append(explanation)
            
        fallback_text = (
            f"### Научный отчет причинно-следственного анализа (Локальная копия)\n\n" +
            "\n".join(explanations) +
            f"\n**Вывод**: Изменение '{cfs[0]['difference']['parameter']}' оказывает влияние на "
            f"'{cfs[0]['effects'][0]['property'] if cfs[0]['effects'] else 'выходные параметры'}' со степенью достоверности {exp.confidence:.2f}."
        )
        return {
            "experiment_id": experiment_id,
            "has_explanation": True,
            "explanation": fallback_text
        }
