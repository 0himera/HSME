# LLM call sites

> Все места в HSME, где вызывается LLM и обрабатывается ответ.

**Актуальность:** 2026-07-07 · Клиент: `AsyncOpenAI` (OpenAI-compatible) или Gemini fallback.

---

## Общая архитектура

HSME **не использует** Anthropic SDK, LiteLLM или прямые httpx-вызовы к OpenRouter (кроме Gemini fallback). Весь production-трафик идёт через:

| Компонент | Файл | Назначение |
|-----------|------|------------|
| `NLPExtractor` | `backend/services/nlp_extractor.py` | Основной async клиент |
| `GeminiCompletions` | `backend/services/nlp_extractor.py` | httpx → Google Generative Language API |
| `YandexAIStudioClient` | `backend/services/yandex_aistudio_client.py` | Sync smoke-test only |
| `load_prompt()` | `backend/core/prompts.py` | YAML → dict |
| `resolve_llm_settings()` | `backend/core/config.py` | CLI → env → `.env` |

**Приоритет провайдеров:** OpenRouter / Yandex Cloud / Gemini fallback (если нет API key, но есть `GEMINI_API_KEY`).

**Промпты:** `backend/prompts/{domain}.yaml` — 6 YAML-файлов для production.

---

## Сводная таблица

| # | Функция | Файл | Промпт | Формат ответа | Pipeline |
|---|---------|------|--------|---------------|----------|
| 1 | `extract_entities_and_relations` | `nlp_extractor.py` | `nlp_extractor.yaml` | JSON `{entities, relations}` | Ingestion |
| 2 | `parse_query_to_entities` | `query_parse.py` | `search_parse_query.yaml` | JSON array `[{type, value}]` | Search L0 |
| 3 | `synthesize_vsa_answer` | `search.py` | `search_synthesize.yaml` | Markdown (stream) | Search L4 |
| 4 | `reason_causality` | `analytics.py` | `analytics_reason.yaml` | Markdown | Studio |
| 5 | `enrich_gap` | `gaps.py` | `gaps_enrich.yaml` | Markdown | Studio |
| 6 | `evaluate_answer_with_llm` | `llm_judge.py` | `llm_judge.yaml` | JSON `{score, reasoning}` | Eval |
| 7 | `GeminiCompletions.create` | `nlp_extractor.py` | — (прокси) | OpenAI-compatible shim | Fallback |
| 8 | `YandexAIStudioClient.ask` | `yandex_aistudio_client.py` | inline | plain text | Smoke-test |

---

## 1. `extract_entities_and_relations` — Ingestion NLP

### Назначение

Извлечение structured entities + relations из text chunk (~1800 chars) при ingestion. Основной LLM-вызов по объёму (один call на chunk).

### Стек вызовов

```
corpus_loader.main / POST /api/ingest-corpus
└── IngestionPipeline.ingest_file
    └── IngestionPipeline.process_chunk
        └── NLPExtractor.extract_entities_and_relations(text)
            └── self.client.chat.completions.create(...)
                └── validate_nlp_extraction(parse_llm_json(...))
                    └── _enrich_numeric_properties(...)
```

### Код

```260:310:backend/services/nlp_extractor.py
        for attempt in range(3):
            try:
                current_system = moderation_retry_prompt if use_moderation_prompt else system_prompt
                request_kwargs: Dict[str, Any] = {
                    "model": self.model_id,
                    "messages": [
                        {"role": "system", "content": current_system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 3000,
                }
                if uses_yandex_json_mode(self.model_id, use_gemini=self._use_gemini):
                    request_kwargs["response_format"] = {"type": "json_object"}
                // ...
                response = await self.client.chat.completions.create(**request_kwargs)

                content = normalize_message_content(response.choices[0].message.content)
                // ...
                clean_json = extract_json_payload(content)
                parsed_data = validate_nlp_extraction(parse_llm_json(clean_json), strict=False)
                self._enrich_numeric_properties(chunk_text, parsed_data)
                return parsed_data
```

### Промпт

**Файл:** [backend/prompts/nlp_extractor.yaml](../../backend/prompts/nlp_extractor.yaml)

| Ключ | Placeholder |
|------|-------------|
| `system` | — (онтология entity/relation types) |
| `system_moderation_retry` | — (нейтральный retry при refusal) |
| `user` | `{chunk_text}` |

Entity types: Material, Process, Equipment, Property, Expert, Facility, Publication.  
Relation types: uses_material, operates_at_condition, produces_output, located_at, described_in, validated_by, contradicts.

### Обработка ответа

1. `normalize_message_content` — flatten list/dict content parts
2. `is_moderation_refusal` → retry с `system_moderation_retry` (до 3 попыток)
3. `extract_json_payload` — strip markdown fences, find `{...}`
4. `parse_llm_json` — repair smart quotes, trailing commas
5. `validate_nlp_extraction(..., strict=False)` — tolerant Pydantic; drop invalid relations
6. `_enrich_numeric_properties` — regex pH, °C, А/м²

**Failure outcomes:**

```python
{"entities": [], "relations": [], "_skip_reason": "moderation"}
{"entities": [], "relations": [], "_skip_reason": "validation_failed"}
```

### Пример ответа

Из [tests/test_nlp_extractor.py](../../tests/test_nlp_extractor.py):

```json
{
  "entities": [{"type": "Material", "value": "никель"}],
  "relations": []
}
```

Расширенный пример из промпта:

```json
{
  "entities": [{"type": "Material", "value": "Normalized Value"}],
  "relations": [{"source": "Value1", "type": "uses_material", "target": "Value2"}]
}
```

---

## 2. `parse_query_to_entities` — L0 парсинг запроса

### Назначение

Преобразование NL search query в `List[Entity]` для VSA retrieval.

### Стек вызовов

```
App.ask → searchQuery → POST /api/search
└── search_experiments
    └── parse_query_to_entities(query.query)
        └── extractor.client.chat.completions.create(...)
            └── json.loads → List[Entity]
                └── parse_query_local_sync (fallback)
```

Eval note: `run_retrieval_eval.py` и `parse_query_with_timeout(..., prefer_local=True)` **не вызывают LLM**.

### Код

```94:142:backend/services/query_parse.py
async def parse_query_to_entities(query_text: str) -> List[Entity]:
    """Parse NL query via LLM; fall back to regex heuristics on failure."""
    try:
        prompt_config = load_prompt("search_parse_query")
        // ...
        response = await extractor.client.chat.completions.create(
            model=extractor.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2500,
        )
        // ... regex extract JSON array ...
        parsed = json.loads(content)
        entities: List[Entity] = []
        for item in parsed:
            t = item.get("type")
            v = item.get("value")
            if t and v:
                entities.append(Entity(type=t, value=v))
        if entities:
            return entities
    except Exception as exc:
        logger.warning("LLM query parse failed, using regex fallback: %s", exc)

    return parse_query_local_sync(query_text)
```

### Промпт

**Файл:** [backend/prompts/search_parse_query.yaml](../../backend/prompts/search_parse_query.yaml)

| Ключ | Placeholder |
|------|-------------|
| `system` | — (entity types + JSON format) |
| `user` | `{query_text}` |

### Обработка ответа

- Regex `\[\s*\{.*\}\s*\]` или markdown fences
- `json.loads` → filter items with both `type` and `value`
- Fallback: `parse_query_local_sync()` — keyword matching (никель, медь, pH, °C, …)

### Пример ответа

**LLM (из промпта):**

```json
[
  {"type": "Material", "value": "никель"},
  {"type": "Process", "value": "электроэкстракция"},
  {"type": "Property", "value": "pH < 2.0"}
]
```

**Fallback (query `"электроэкстракция никеля при pH 2.0"`, из [tests/test_query_parse.py](../../tests/test_query_parse.py)):**

```python
[Entity(type="Material", value="никель"), Entity(type="Process", value="электроэкстракция"), Entity(type="Property", value="PH: 2.0")]
```

---

## 3. `synthesize_vsa_answer` — L4 синтез ответа

### Назначение

Генерация Markdown scientific report из VSA results, counterfactuals, graph context, gap analysis.

### Стек вызовов

```
POST /api/search (Admin/Analyst, paged=True, query set)
└── search_experiments
    └── synthesize_vsa_answer(query, sliced, graph_context, entities)
        ├── db.get_counterfactuals(top_exp.id)
        ├── db.analyze_gaps(...)  [if relevant_count < 3]
        ├── load_prompt("search_synthesize")
        └── extractor.client.chat.completions.create(..., stream=True)
            └── concatenate deltas → append gap_summary
```

### Код

```169:213:backend/routers/search.py
    prompt_config = load_prompt("search_synthesize")
    // ... format user_prompt with query, exp_context, entropy, counterfactuals, graph ...
    try:
        extractor = NLPExtractor()
        llm_start = time.perf_counter()
        stream = await extractor.client.chat.completions.create(
            model=extractor.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
            stream=True,
        )
        // ... collect deltas, track ttft_s, ttfa_s ...
        ans = "".join(content_parts)
        if gap_summary:
            ans += "\n" + gap_summary
        return ans, ttft_s, ttfa_s
    except Exception as e:
        fallback = (
            f"**Синтез ответа недоступен (LLM Error).**\n\n"
            f"*Сырые причинные связи:*\n{counterfactuals_summary}"
        )
        return fallback, None, None
```

### Промпт

**Файл:** [backend/prompts/search_synthesize.yaml](../../backend/prompts/search_synthesize.yaml)

| Ключ | Placeholders |
|------|--------------|
| `system` | — (структура отчёта: Вывод, Консенсус, Counterfactuals) |
| `user` | `{query_text}`, `{exp_context}`, `{entropy_summary}`, `{counterfactuals_summary}`, `{graph_summary}` |

### Обработка ответа

- **Streaming** — delta chunks concatenated
- **No JSON parsing** — free-form Markdown
- Gap summary appended after stream (non-LLM, from `db.analyze_gaps`)
- Metrics: `llm_ttft_s`, `llm_ttfa_s` in API response

### Пример ответа

**Mock из eval** ([tests/test_eval.py](../../tests/test_eval.py)):

```markdown
Ответ с электроэкстракцией никеля.
```

**Ожидаемая структура (из промпта):**

```markdown
### 1. Вывод
...

### 2. Консенсус и результаты
...

### 3. Причинно-следственные связи
...
```

**Fallback при LLM error:**

```markdown
**Синтез ответа недоступен (LLM Error).**

*Сырые причинные связи:*
- Если изменить 'pH' с '2.0' на '3.0', то наблюдается: ...
```

---

## 4. `reason_causality` — Studio causal report

### Назначение

Причинно-следственный отчёт для одного experiment на основе counterfactual data. UI: Studio panel.

### Стек вызовов

```
GET /api/reason/{experiment_id}
└── reason_causality
    ├── db.get_counterfactuals(experiment_id)
    ├── load_prompt("analytics_reason")
    └── extractor.client.chat.completions.create(...)
        └── return explanation (Markdown)
            └── rule-based fallback on error
```

### Код

```64:86:backend/routers/analytics.py
    prompt_config = load_prompt("analytics_reason")
    prompt = prompt_config["user"].format(
        experiment_id=exp.id,
        experiment_name=exp.name,
        cf_details="\n".join(cf_details),
    )
    
    try:
        extractor = NLPExtractor()
        response = await extractor.client.chat.completions.create(
            model=extractor.model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000
        )
        report = response.choices[0].message.content
        if not report:
            report = getattr(response.choices[0].message, "reasoning_content", None) or ""
        return {
            "experiment_id": experiment_id,
            "has_explanation": True,
            "explanation": report
        }
```

### Промпт

**Файл:** [backend/prompts/analytics_reason.yaml](../../backend/prompts/analytics_reason.yaml)

| Ключ | Placeholders |
|------|--------------|
| `user` | `{experiment_id}`, `{experiment_name}`, `{cf_details}` |

No system message.

### Обработка ответа

- Read `message.content` or `reasoning_content`
- Return as `explanation` string
- Fallback: rule-based Markdown from counterfactual data

### Пример ответа

**Ожидаемый формат:** 2–3 абзаца Markdown на русском с физико-химическим объяснением.

**Fallback (из кода):**

```markdown
### Научный отчет причинно-следственного анализа (Локальная копия)

Сравнение EXP-... с EXP-...:
  - Параметр 'pH' изменен с 2.0 на 3.0.
  - Эффекты:
• свойство 'чистота' изменилось с 99.5% на 98.1%

**Вывод**: Изменение 'pH' оказывает влияние на 'чистота'.
```

---

## 5. `enrich_gap` — Studio gap hypothesis

### Назначение

Генерация scientific hypothesis для unstudied parameter combination.

### Стек вызовов

```
POST /api/enrich-gap
└── enrich_gap(gap_config)
    ├── db.analyze_gaps(dimensions, specific_combinations=[gap_config])
    ├── load_prompt("gaps_enrich")
    └── extractor.client.chat.completions.create(...)
        └── return hypothesis (Markdown)
```

### Код

```67:88:backend/routers/gaps.py
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
            max_tokens=3000
        )
        hypothesis = response.choices[0].message.content
        // ...
        return {
            "configuration": gap_config,
            "predicted_properties": predicted_props,
            "hypothesis": hypothesis
        }
```

### Промпт

**Файл:** [backend/prompts/gaps_enrich.yaml](../../backend/prompts/gaps_enrich.yaml)

| Ключ | Placeholders |
|------|--------------|
| `user` | `{config_desc}`, `{prop_desc}`, `{sim_context}` |

### Обработка ответа

- Free-text Markdown hypothesis
- Fallback: template with predicted properties + similar experiments

### Пример ответа

**Fallback (из кода):**

```markdown
### Научная гипотеза для: [Material: никель, Process: электроэкстракция]

**Прогнозируемые свойства:**
- Property ~ чистота 99.5%

**Обоснование:**
На основе VSA топологического анализа выявлены близкие к пробелу опыты:
  * EXP-... (никель, электроэкстракция) -> Property=99.2%

Рекомендуется провести физический эксперимент...
```

---

## 6. `evaluate_answer_with_llm` — Eval LLM-as-judge

### Назначение

Score RAG answer relevance 0..1 for E2E evaluation (Stage 2b).

### Стек вызовов

```
run_e2e_eval (use_llm=True)
└── evaluate_answer_with_llm(query, answer, expected_keywords)
    ├── load_prompt("llm_judge")
    └── asyncio.wait_for(extractor.client.chat.completions.create(...), timeout)
        └── _parse_judge_json(content)
```

### Код

```32:82:backend/evaluation/judges/llm_judge.py
async def evaluate_answer_with_llm(
    query: str,
    answer: Optional[str],
    expected_keywords: Optional[List[str]] = None,
    *,
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    // ...
    response = await asyncio.wait_for(coro, timeout=timeout_s)
    content = response.choices[0].message.content
    // ...
    return _parse_judge_json(content)
```

```13:29:backend/evaluation/judges/llm_judge.py
def _parse_judge_json(content: str) -> Dict[str, Any]:
    // ... regex extract {...} ...
    parsed = json.loads(text)
    score = float(parsed.get("score", 0))
    score = max(0.0, min(1.0, score))
    return {
        "score": round(score, 4),
        "reasoning": str(parsed.get("reasoning", "")),
        "pass": score >= 0.5,
    }
```

### Промпт

**Файл:** [backend/prompts/llm_judge.yaml](../../backend/prompts/llm_judge.yaml)

| Ключ | Placeholders |
|------|--------------|
| `system` | — (score 0..1, JSON only) |
| `user` | `{query}`, `{answer_preview}`, `{keywords_hint}` |

### Обработка ответа

- Regex extract JSON object
- Clamp `score` to [0, 1]
- `pass = score >= 0.5`
- Error → `{score: 0, pass: False, reasoning: "judge error: ..."}`

### Пример ответа

Из [tests/test_eval.py](../../tests/test_eval.py):

```json
{"score": 0.75, "reasoning": "Partially relevant"}
```

Parsed result:

```python
{"score": 0.75, "pass": True, "reasoning": "Partially relevant"}
```

---

## 7. `GeminiCompletions.create` — Fallback proxy

### Назначение

OpenAI-compatible shim когда нет Yandex/LLM API key, но задан `GEMINI_API_KEY`.

### Стек вызовов

```
NLPExtractor.__init__ (no api_key, GEMINI_API_KEY set)
└── GeminiChat.completions = GeminiCompletions(api_key)
    └── любой caller → client.chat.completions.create(...)
        └── httpx.post → generativelanguage.googleapis.com
            └── MockResponse(text) — OpenAI interface
```

### Код

```108:167:backend/services/nlp_extractor.py
    async def create(self, model=None, messages=None, temperature=0.1, max_tokens=1000, **kwargs):
        // ... convert messages to Gemini format ...
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=body, headers=headers, timeout=60.0)
            data = res.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        return MockResponse(text)
```

### Промпт

Наследует messages от caller — нет отдельного YAML.

### Обработка ответа

`candidates[0].content.parts[0].text` → wrapped in `MockResponse` with `.choices[0].message.content`.

### Пример ответа

Зависит от caller. Для ingestion — тот же JSON `{entities, relations}`.

---

## 8. `YandexAIStudioClient.ask` — Smoke-test only

### Назначение

Credential/model smoke tests. **Не production path.**

### Стек вызовов

```
tests/test_yandex_aistudio.py (optional live integration)
└── YandexAIStudioClient.ask(prompt)
    └── sync OpenAI(...).chat.completions.create(...)
```

### Код

Default prompt: `"Ответь одним словом: какой химический символ у водорода?"`

### Пример ответа

Из live test expectation: `"H"` или `"Водород"`.

---

## Shared response-processing utilities

Все в [backend/services/nlp_extractor.py](../../backend/services/nlp_extractor.py):

| Function | Role |
|----------|------|
| `normalize_message_content` | Flatten list/dict content to string |
| `extract_json_payload` | Strip fences, extract outermost `{...}` |
| `repair_json_text` | Fix smart quotes, trailing commas |
| `parse_llm_json` | `json.loads(..., strict=False)` with repair |
| `is_moderation_refusal` | Detect safety refusals |
| `uses_yandex_json_mode` | Enable JSON mode for `gpt://` models |

Validation schema: [backend/core/nlp_schemas.py](../../backend/core/nlp_schemas.py)

---

## Indirect callers (no new LLM logic)

| Caller | File | Triggers |
|--------|------|----------|
| `IngestionPipeline.process_chunk` | `ingestion.py` | #1 extraction |
| `corpus_loader` / `corpus_relabel_loader` | `repository/` | #1 via pipeline |
| `search_experiments` | `search.py` | #2 L0, #3 L4 |
| `run_e2e_eval` | `run_e2e_eval.py` | #3, #6; L0 via API or local |
| `_run_question_via_api` | `run_e2e_eval.py` | #2+#3 server-side |

---

## Что НЕ является LLM-вызовом

| Component | Почему |
|-----------|--------|
| `parse_query_local_sync` | Regex/heuristics fallback |
| `rule_judge.evaluate_answer` | Keyword/recall rules |
| `httpx` in `corpus_loader.py` | Yandex Disk archive download |
| `httpx` in `run_e2e_eval.py` | HTTP to `/api/search` |
| Frontend | Displays Markdown only |
| `db.analyze_gaps` | Rule-based gap detection |
| `db.get_counterfactuals` | VSA math, no LLM |

---

## Config / env vars

From [backend/core/config.py](../../backend/core/config.py):

```
LLM_API_KEY, LLM_BASE_URL, LLM_FOLDER_ID, LLM_MODEL_ID / LLM_MODEL
YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_BASE_URL
GEMINI_API_KEY  (fallback only)
```

Dependency: `openai>=2.44.0` — no litellm, no anthropic SDK.

---

## Навигация

### Промпты

| Файл | Call site |
|------|-----------|
| [nlp_extractor.yaml](../../backend/prompts/nlp_extractor.yaml) | #1 |
| [search_parse_query.yaml](../../backend/prompts/search_parse_query.yaml) | #2 |
| [search_synthesize.yaml](../../backend/prompts/search_synthesize.yaml) | #3 |
| [analytics_reason.yaml](../../backend/prompts/analytics_reason.yaml) | #4 |
| [gaps_enrich.yaml](../../backend/prompts/gaps_enrich.yaml) | #5 |
| [llm_judge.yaml](../../backend/prompts/llm_judge.yaml) | #6 |

### Пайплайны

| Файл | Связь |
|------|-------|
| [retrieval-to-answer.md](./retrieval-to-answer.md) | L0 + L4 в search flow |
| [ingestion-pipeline.md](./ingestion-pipeline.md) | #1 в ingestion flow |
| [navigations/backend.md](../navigations/backend.md) | Полная карта backend |

### Tests

| Файл | Покрытие |
|------|----------|
| [tests/test_nlp_extractor.py](../../tests/test_nlp_extractor.py) | #1 parsing, utilities |
| [tests/test_query_parse.py](../../tests/test_query_parse.py) | #2 fallback |
| [tests/test_eval.py](../../tests/test_eval.py) | #6 judge |
| [tests/test_yandex_aistudio.py](../../tests/test_yandex_aistudio.py) | #8 smoke |
