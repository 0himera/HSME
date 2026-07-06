# Stage 4: Анализ corpus relabel (NLP ingestion)

> Сгенерировано: `scripts/analyze_stage4_relabel.py`  
> Источник лога: [relabel-resume.log](../../../logs/relabel/relabel-resume.log)  
> Регламент: [stages.md](../../stages.md) § Stage 4

## 1. Контекст и предпосылки

### Что делает Stage 4

Corpus relabel — повторный NLP-инжест корпуса через **YandexGPT 5.1** (`json_object` mode) с dual-write в **VSA** (`db_state.pkl`) и **Neo4j**. CLI: `corpus_relabel_loader.py`, resume через `--skip-files N`.

### Команда прогона (2026-07-05)

```
mode=test, max_files=5, skip_files=10, concurrency=3
model=gpt://{folder}/yandexgpt-5.1/latest
```

Пропущены первые 10 файлов (Обзоры/Статьи/Доклады), обработаны **5 журналов**, **550 чанков**. Итог: `Total DB size: 140`.

### Архитектурные предпосылки

| Компонент | Роль |
|-----------|------|
| `DocumentParser` | `code=N/A` если код не найден в имени/PDF |
| `IngestionPipeline.process_chunk` | `EXP-{code}-{index:02d}`, skip если id уже в VSA |
| `RelabelIngestionPipeline` | Перезаписывает существующий id; restore backup при пустом extraction |
| `NLPExtractor` | 3 retry, strict `validate_nlp_extraction`, пустой dict при провале |
| `neo4j_graph.insert_experiment_async` | MERGE без semaphore; deadlock retry на уровне драйвера |

---

## 2. Метрики из лога (автоанализ)

| Метрика | Значение |
|---------|----------|
| Validation warnings (все попытки) | 55 |
| Histogram ошибок Pydantic (N per attempt) | {1: 23, 2: 15, 3: 14, 4: 2, 7: 1} |
| Neo4j ingest ok (строк в логе) | 507 |
| Restored VSA (события) | 27 |
| Restored VSA (уникальные id) | 22 |
| DeadlockDetected | 3 |
| Moderation refusal | 3 |
| Relabeled ids (уникальные) | 113 |

### Уникальные restored IDs

- `EXP-RAW-00`
- `EXP-RAW-01`
- `EXP-RAW-02`
- `EXP-RAW-102`
- `EXP-RAW-125`
- `EXP-RAW-16`
- `EXP-RAW-17`
- `EXP-RAW-21`
- `EXP-RAW-22`
- `EXP-RAW-27`
- `EXP-RAW-32`
- `EXP-RAW-36`
- `EXP-RAW-42`
- `EXP-RAW-55`
- `EXP-RAW-57`
- `EXP-RAW-70`
- `EXP-RAW-76`
- `EXP-RAW-84`
- `EXP-RAW-89`
- `EXP-RAW-91`
- `EXP-RAW-92`
- `EXP-RAW-93`

### Предполагаемые invalid types (из preview)

**Relation types:** не удалось извлечь

**Entity types:** не удалось извлечь

---

## 3. Классы ошибок и фрагменты кода

### E1 — Коллизия `EXP-RAW-*` (P0)

**Симптом:** один `EXP-RAW-03` используется разными PDF; при resume restore подставляет данные **другого** файла.

**Корневая причина:** ID строится только из `doc_meta['code']` + chunk index. Для журналов без кода в имени → `code=N/A` → `EXP-RAW-{index}`.

```72:72:backend/services/ingestion.py
        exp_id = f"EXP-{doc_meta['code']}-{chunk['index']:02d}".replace("N/A", "RAW")
```

```80:82:backend/repository/corpus_relabel_loader.py
    async def process_chunk(self, chunk: dict[str, Any], doc_meta: dict[str, Any]) -> None:
        exp_id = f"EXP-{doc_meta['code']}-{chunk['index']:02d}".replace("N/A", "RAW")
        previous = self.db.experiments.get(exp_id)
```

```149:149:backend/services/document_parser.py
            "code": code or "N/A",
```

**Доказательство из лога:** `EXP-RAW-00` restored **3 раза** (строки 79, 692, 1029, 1396) — один id, разные журналы.

---

### E2 — Strict Pydantic validation (P0)

**Симптом:** `failed validation: N; preview='{"entities": [...'` — JSON выглядит осмысленным, но после 3 попыток → `{"entities": [], "relations": []}`.

**Корневая причина:** `validate_nlp_extraction` — all-or-nothing; одна invalid relation → весь payload rejected.

```117:119:backend/core/nlp_schemas.py
def validate_nlp_extraction(payload: Any) -> dict[str, Any]:
    return NLPExtractionResult.model_validate(payload).model_dump(mode="python")
```

```270:306:backend/services/nlp_extractor.py
                parsed_data = validate_nlp_extraction(parse_llm_json(clean_json))
                ...
            except ValidationError as exc:
                logger.warning(
                    "Extraction attempt %d failed validation: %s; preview=%.200r",
                    ...
                )
        return {"entities": [], "relations": []}
```

**Mismatch prompt ↔ schema:**

| Источник | Relation types |
|----------|----------------|
| `nlp_extractor.yaml` | 4: uses_material, operates_at_condition, produces_output, located_at |
| `nlp_schemas.py` | 7: + described_in, validated_by, contradicts |

LLM может возвращать синонимы (`has_property`, `contains`, `part_of`) или типы вне whitelist → ValidationError.

**Пример из лога** (validation: 1, entities выглядят OK):
```
preview='{"entities": [{"type": "Material", "value": "сера"}, ...], "relations": [...'
```

---

### E3 — Moderation refusal (P1)

**Симптом:** HTTP 200, но content = «Я не могу обсуждать эту тему...» → JSONDecodeError × 3 → restore.

```
WARNING Extraction attempt 1 failed: Expecting value: line 1 column 1 (char 0);
  preview='Я не могу обсуждать эту тему. Давайте поговорим о чём-нибудь ещё.'
...
WARNING Re-label produced no experiment for EXP-RAW-102; restored previous VSA record
```

Тематика: U, Pu, UF6, трихлорид плутония (строки 416–442 лога).

---

### E4 — Restore при пустом extraction (следствие E2/E3)

```91:98:backend/repository/corpus_relabel_loader.py
        if previous is not None and exp_id not in self.db.experiments:
            self.db.experiments[exp_id] = previous
            if previous_vector is not None:
                self.db.vector_store[exp_id] = previous_vector
            logger.warning(
                "Re-label produced no experiment for %s; restored previous VSA record",
                exp_id,
            )
```

При E1 restore может вернуть данные **чужого PDF** с тем же `EXP-RAW-{index}`.

---

### E5 — Neo4j deadlock (P1)

**Симптом:** `Transaction.DeadlockDetected` на shared NODE при `concurrency=3`; auto-retry OK (+0.8–1.0 s).

```76:79:backend/services/ingestion.py
        async with self.semaphore:  # LLM concurrency only
            ...
            if neo4j_graph.is_configured:
                await neo4j_graph.insert_experiment_async(experiment)  # no write semaphore
```

Neo4j writes идут параллельно внутри LLM semaphore → MERGE на общие Publication/Material nodes.

---

### E6 — Logging (P2)

```199:199:backend/services/ingestion.py
            print(f"Indexing [{source_type}] {os.path.basename(file)}...")
```

`print()` буферизуется → строки «Indexing [Журнал]…» только в конце лога.

---

## 4. Целевое решение (из stages.md)

| Проблема | Решение | Приоритет |
|----------|---------|-----------|
| E1 | `file_slug` в experiment.id | P0 |
| E2 | Tolerant validation: keep entities, drop bad relations | P0 |
| E3 | Detect refusal regex + neutral retry + `is_sensitive` | P1 |
| E4 | Restore только для того же file slug (после E1) | P0 |
| E5 | `asyncio.Semaphore(1)` на Neo4j write | P1 |
| E6 | `logger.info` вместо `print` | P2 |

**Цель:** success rate ≥ 97% (≤ 15 restored / 550 чанков). Текущий: ~92% Neo4j ok, ~5% restored.

---

## 5. LLM-консультация (LLM_* из .env)

1. **E2 root cause**: Типичные причины, по которым может произойти ошибка валидации при «валидно выглядящем» JSON:
   - **Несоответствие промпта и схемы**: Если типы отношений, указанные в JSON, не соответствуют тем, что определены в схеме (например, 4 типа в промпте против 7 в схеме).
   - **Обрезанный JSON**: Если JSON не полностью сформирован или содержит недостающие части, это может привести к ошибкам валидации.
   - **Выдуманные типы отношений**: Если в JSON указаны типы отношений, которые не предусмотрены в схеме, это также вызовет ошибку.

2. **Tolerant validation**: Паттерн для Pydantic v2, который фильтрует недопустимые отношения, сохраняя сущности. Пример сигнатуры функции:
   ```python
   from pydantic import BaseModel, ValidationError, validator
   from typing import List, Dict, Any

   class Entity(BaseModel):
       type: str
       value: str

   class Relation(BaseModel):
       type: str
       target: str

   class ExtractionResult(BaseModel):
       entities: List[Entity]
       relations: List[Relation]

       @validator('relations', pre=True, always=True)
       def filter_invalid_relations(cls, v, values):
           valid_relation_types = {'type1', 'type2', 'type3', 'type4'}  # допустимые типы отношений
           return [rel for rel in v if rel.type in valid_relation_types]

   def validate_extraction(data: Dict[str, Any]) -> ExtractionResult:
       return ExtractionResult(**data)
   ```

3. **E3 moderation**: Стратегия обнаружения и повторной попытки для академических текстов о уране/плутонии без отказа модели:
   - **Обнаружение**: Использовать регулярные выражения для выявления ключевых слов, связанных с ураном и плутонием, в тексте.
   - **Стратегия повторной попытки**:
     ```python
     def retry_moderation(text: str, max_attempts: int = 3) -> str:
         for attempt in range(max_attempts):
             response = send_to_moderation(text)
             if response.is_accepted():
                 return response
             elif response.is_refusal() and contains_sensitive_keywords(text):
                 # Изменить текст, чтобы избежать отказа
                 text = modify_text(text)
         raise Exception("Moderation failed after multiple attempts.")
     ```

4. **E1 experiment.id**: Формат slug из basename PDF. Пример для «Журнал Горный №1 2020.pdf» chunk 03:
   - Формат: `journal-gorny-1-2020-chunk-03`
   - Пример: `journal-gorny-1-2020-03`

5. **Приоритеты**: Для достижения максимального эффекта на success rate с 92% до 97% с минимальным диффом:
   - **Улучшение валидации**: Реализовать толерантную валидацию, чтобы фильтровать недопустимые отношения и сохранять валидные сущности.
   - **Оптимизация обработки**: Увеличить количество параллельных запросов к Neo4j, чтобы уменьшить количество deadlock-событий, возможно, путем уменьшения concurrency до 2.
   - **Обработка отказов**: Внедрить стратегию повторной попытки для текстов, связанных с ураном и плутонием, чтобы избежать отказов модели.

---

## 6. Открытые вопросы / следующие шаги

1. Реализовать `make_experiment_id(doc_meta, chunk_index)` с slug — **блокер для корректного resume**.
2. `validate_nlp_extraction(..., strict=False)` — оценить, сколько из 13 финальных провалов станут ok.
3. Синхронизировать `nlp_extractor.yaml` со схемой (или наоборот) — снизить invented types.
4. Прогон `--dry-run` после фиксов; сравнение с baseline `relabel-resume.log`.
5. `relabel.log` показывает `unrecognized arguments: --skip-files 10` — старая версия CLI до добавления флага.

---

## 7. Связанные файлы

| Файл | Статус |
|------|--------|
| `backend/repository/corpus_relabel_loader.py` | `--skip-files` есть; tolerant validation — нет |
| `backend/services/ingestion.py` | EXP-RAW collision; print() |
| `backend/services/nlp_extractor.py` | strict validation; no moderation detect |
| `backend/core/nlp_schemas.py` | strict only |
| `backend/repository/neo4j_graph.py` | no write semaphore |
| `tests/test_nlp_schemas.py` | только strict tests |
| `tests/test_corpus_relabel_loader.py` | restore test; no collision test |
