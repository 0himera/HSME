# Загрузка данных — рекомендации (summary)

Сжатая выжимка по проблемам из [data_ingestion_overview.md §4–§7](./data_ingestion_overview.md).  
Подробные обоснования — в [data_ingestion_overview_answer.md](./data_ingestion_overview_answer.md); реализованные и планируемые фиксы — в [stages.md §Stage 4/5](../.../../stages.md).

**Baseline (relabel-resume.log, 550 чанков):** Neo4j ok 92,2% · restored 4,9% · validation_failed 2,4% · moderation 0,2%.

---

## §4.1 Долгая загрузка — 7 факторов

### Фактор 1: LLM на каждый чанк

**Проблема:** один HTTP-запрос на чанк; при 550 чанках — сотни вызовов; retry ×3 при validation fail.  
**Статус:** 📋 рекомендация  
**Суть:** кэшировать LLM-ответы по ключу `(file_slug, chunk_hash, model_id)` в `ingestion_cache/` (JSON или SQLite). При relabel/resume повторно не вызывать LLM, если чанк не менялся. Pre-filter коротких чанков (Stage 5) — дополнение, не замена кэша.  
**Не делать:** batch-промпт с несколькими чанками в одном запросе — усложняет парсинг ответа.  
**Effort / эффект:** S · −30–50% LLM-вызовов при повторных прогонах.  
**Источник:** *в answer отсутствует* (восстановлено из ранней версии answer); дополнение — [stages.md Stage 5 V3](../.../../stages.md).

---

### Фактор 2: Линейный рост объёма корпуса

**Проблема:** число чанков растёт линейно; test ~1411, prod — multi-GB архив.  
**Статус:** ✅ частично закрыто ([Stage 4.1](../../stages.md#stage-41-chunknorris-style-semantic-chunking)) · 📋 process pool ещё в backlog  
**Суть:** ChunkNorris-style section-aware chunking (`cn_v1`) вместо fixed-size/page splits; oversized tables с повтором headers; code skip. Дополнительно (не сделано): `ProcessPoolExecutor` для параллельного парсинга файлов (`--file-workers`).  
**Не делать:** увеличивать размер чанка до 3000 без перетеста качества extraction; agentic TopoChunker на ingest (см. [topochunker.md](../architecture/topochunker.md)).  
**Effort / эффект:** M · цель −15–25% LLM-calls; process pool — отдельно.  
**Источник:** [answer §Фактор 2](./data_ingestion_overview_answer.md), [Stage 4.1](../../stages.md#stage-41-chunknorris-style-semantic-chunking).

---

### Фактор 3: Concurrency vs rate limit

**Проблема:** default concurrency 6 → автоснижение до 2 (OpenRouter); relabel использует 3.  
**Статус:** 📋 рекомендация  
**Суть:** динамический планировщик — измерять throughput и адаптировать `asyncio.Semaphore` под текущий rate limit (цель утилизации 90–95% вместо 60–70%).  
**Не делать:** полноценный брокер с очередями — overkill для текущего объёма.  
**Effort / эффект:** S (1 день).  
**Источник:** [answer §Фактор 3](./data_ingestion_overview_answer.md).

---

### Фактор 4: Синхронный Neo4j dual-write

**Проблема:** `Semaphore(1)` сериализует graph writes; +0,8–1,0 s на эксперимент с учётом deadlock-retry.  
**Статус:** 🔄 частично закрыто (E5) · 📋 оптимизация  
**Суть:** **Краткосрочно:** batch-commit Neo4j каждые 10–20 экспериментов (`UNWIND` вместо N отдельных `MERGE`) — Effort M, −30–40% wait (0,8–1,0 s → 0,2–0,3 s). **Долгосрочно:** SQLite outbox + фоновый воркер — основной поток только ставит в очередь; batch-запись асинхронно — Effort 5–7 дней, −70–80% Neo4j-time, eventual consistency 1–2 с, concurrency LLM до 10–15.  
**Не делать:** отключать Neo4j в prod (`USE_NEO4J=false`) ради скорости — теряется граф.  
**Effort / эффект:** см. выше.  
**Источник:** [answer §Фактор 4](./data_ingestion_overview_answer.md), [answer §2.1](./data_ingestion_overview_answer.md).

---

### Фактор 5: Скачивание архива

**Проблема:** multi-GB zip с Яндекс.Диска; timeout read до 3600 s — разовая, но тяжёлая операция.  
**Статус:** 📋 рекомендация  
**Суть:** перед скачиванием проверять, что `data/` уже существует и не пуста — пропускать download. Флаг `--force-download` для принудительного обновления.  
**Effort / эффект:** S (0,5 дня) · при повторных запусках −5–15 мин.  
**Источник:** *в answer отсутствует* (восстановлено из ранней версии answer).

---

### Фактор 6: Validation failures (~2,4%)

**Проблема:** ~13/550 чанков — финальный провал после 3 одинаковых retry; ×3 LLM-попытки впустую.  
**Статус:** 🔄 частично закрыто (tolerant validation) · 📋 оптимизация  

**Слой A — JSON validation (синтаксис + Pydantic):** adaptive retry (temperature 0,1 → 0,4 → 0,7 + hint с whitelist типов), pre-filter коротких чанков, опционально `json_schema` вместо `json_object`, relation alias map, repair truncated JSON. Цель: validation_failed **<1%**.  
**Источник:** [stages.md Stage 5](../../stages.md).

**Слой B — quality gate (содержательность extraction):** после NLP — `quality_score` (число entities/relations, наличие Material/Process). При низком скоре — повтор LLM с уточняющим промптом; затем rule-based enrich (keyword-словари, шаблонные связи). Цель: restored **<1%**, validation_failed **<0,5%**.  
**Не делать:** смешивать JSON-retry и quality-retry в одну политику без раздельной телеметрии.  
**Effort / эффект:** JSON — S ([Stage 5](../../stages.md)); quality gate — ~4 дня.  
**Источник:** [answer §2.5](./data_ingestion_overview_answer.md).

---

### Фактор 7: Отсутствие async broker

**Проблема:** синхронный dual-write — архитектурный потолок; Stage 3 (Redis/Outbox) в backlog.  
**Статус:** ⏸ отложить · 📋 промежуточное решение  
**Суть:** полный Redis Streams + Outbox — отложить до 10× роста корпуса. Промежуточно — SQLite outbox-lite (см. фактор 4, §2.1 answer) без новой инфраструктуры.  
**Источник:** [answer §Фактор 4 «отложить»](./data_ingestion_overview_answer.md), [answer §2.1](./data_ingestion_overview_answer.md).

---

## §4.2 Нормализация — A / B / C / D

### A. DocumentParser

**Проблема:** частый `code=N/A` → нестабильные метаданные и ID до Stage 4 fix.  
**Статус:** 📋 рекомендация  
**Суть:** унифицировать извлечение `normalize_code`, year, title, authors для PDF и DOCX; единая fallback-цепочка → `file_slug`, если code не найден.  
**Effort / эффект:** S (1 день) · −30–50% случаев `code=N/A`.  
**Источник:** *в answer отсутствует* (восстановлено из ранней версии answer §2A).

---

### B. NLPExtractor

**Проблема:** LLM вызывается на пустые/мусорные чанки.  
**Статус:** 📋 рекомендация (Stage 5 V3)  
**Суть:** pre-filter — чанк <50 символов → skip без LLM, status `empty`.  
**Не делать:** менять онтологию или промпт без перетеста всего корпуса.  
**Effort / эффект:** S (0,5 дня) · −0,5–1% LLM-вызовов.  
**Источник:** [answer §2B](./data_ingestion_overview_answer.md).

---

### C. IngestionPipeline (`classify_entities`)

**Проблема:** эвристики input/process/output покрывают не все термины корпуса.  
**Статус:** 📋 рекомендация  
**Суть:** расширить keyword-словари (сплав, реактор, центрифуга и др.) на основе анализа корпуса.  
**Не делать:** переписывать tolerant validation — она уже работает.  
**Follow-up:** проверить HACKATHON_TASK на словарь аббревиатур — отдельная задача, не блокер.  
**Effort / эффект:** S (1 день) · +5–10% правильной классификации.  
**Источник:** [answer §2C](./data_ingestion_overview_answer.md).

---

### D. Corpus relabel

**Проблема:** restored 4,9% (22 ID); цель success rate ≥97%.  
**Статус:** 🔄 Stage 4 `in_progress` · 📋 рекомендация  
**Суть:** verify-before-overwrite — перед перезаписью сравнить новый extraction со старым (число entities/relations); если хуже — оставить backup. Связать с quality gate (§2.5) и scoped restore (E4).  
**Effort / эффект:** M (2 дня) · restored с 4,9% до <2%; вместе с quality gate — <1%.  
**Источник:** *в answer отсутствует §2D*; частично [answer §2.5](./data_ingestion_overview_answer.md).

---

## §5 Классы ошибок E1–E6

### E1: Коллизия `EXP-RAW-*`

**Статус:** ✅ закрыто  
**Суть:** `make_experiment_id` + `file_slug` — уникальный ID per (file, chunk). Действий нет.  
**Источник:** [overview §5](./data_ingestion_overview.md), [stages.md Stage 4](../../stages.md).

---

### E2: Strict Pydantic validation

**Статус:** ✅ закрыто · 📋 дальнейшая оптимизация — Stage 5  
**Суть:** tolerant validation (`strict=False`) — invalid relations отбрасываются, valid entities сохраняются. Stage 5: adaptive retry, json_schema, observability.  
**Источник:** [overview §5](./data_ingestion_overview.md), [stages.md Stage 5](../../stages.md).

---

### E3: Moderation refusal (0,2%)

**Статус:** ✅ закрыто  
**Суть:** detect refusal regex → retry с neutral system prompt → `is_sensitive`, status `moderation`. Доля мала — дополнительных усилий не требует.  
**Источник:** [overview §5](./data_ingestion_overview.md).

---

### E4: Пустой extraction → restore

**Статус:** ✅ scoped restore · 📋 verify-before-overwrite  
**Суть:** backup VSA восстанавливается только для того же experiment id. Снижение restored: verify-before-overwrite + quality gate (§2.5, §4.2 D).  
**Источник:** [overview §5](./data_ingestion_overview.md), [answer §2.5](./data_ingestion_overview_answer.md).

---

### E5: Neo4j deadlock

**Статус:** ✅ закрыто (`Semaphore(1)`) · 📋 batch/outbox для высокого concurrency  
**Суть:** module-level write semaphore устраняет deadlock при concurrency=3. Долгосрочно — batch Neo4j или outbox (фактор 4).  
**Источник:** [overview §5](./data_ingestion_overview.md), [answer §Фактор 4](./data_ingestion_overview_answer.md).

---

### E6: Буферизация логов (`print` vs logger)

**Статус:** 🔄 в работе  
**Суть:** заменить `print()` на `logging.getLogger(__name__)`, уровень через `--verbose` — структурированные логи, фильтрация, запись в файл.  
**Effort / эффект:** S (1–2 ч).  
**Источник:** [answer §E6](./data_ingestion_overview_answer.md).

---

## §7 Backlog и неподдерживаемые форматы

### Async ingestion (Stage 3)

**Статус:** ⏸ backlog · 📋 промежуточно outbox-lite  
**Суть:** Redis Streams + Transactional Outbox — после стабилизации success rate. Сейчас достаточно SQLite outbox / batch Neo4j (answer §2.1).  
**Источник:** [overview §7](./data_ingestion_overview.md), [answer §2.1](./data_ingestion_overview_answer.md).

---

### Cascade inference (cheap→strong LLM)

**Статус:** ⏸ отложить  
**Суть:** не внедрять до стабильных eval-метрик (Success Rate, TTFT, TTFA) — иначе риск ухудшения качества ради latency.  
**Источник:** *в answer отсутствует* · [overview §7](./data_ingestion_overview.md), [stages.md backlog](../../stages.md).

---

### Неподдерживаемые форматы корпуса

**Проблема:** сейчас только PDF/DOCX; в архиве — PPTX, legacy DOC, XLS, RAR/multi-part.  
**Статус:** 📋 рекомендация  

| Формат | Подход | Effort | Покрытие | Приоритет |
|--------|--------|--------|----------|-----------|
| **PPTX** | `python-pptx`, текст из `text_frame` слайдов | M (2 дня) | ~15–20% | **Топ-1** |
| **Legacy DOC** | `antiword` fallback (или `olefile`) | S (1 день) | ~5–10% | **Топ-2** |
| **XLS** | `xlrd` / `openpyxl`, текст из ячеек | S (1 день) | <5% | отложить |
| **RAR/multi-part** | one-off pre-process (`unrar`, `7z`, `zip -F`) | L | низкое | отложить |

**Источник:** [answer §Блок 5](./data_ingestion_overview_answer.md).

---

## Приоритетный план (top actions)

| Приоритет | Действие | Effort | Ожидаемый эффект |
|-----------|----------|--------|------------------|
| **P0** | Pre-filter чанков + adaptive JSON retry ([Stage 5](../../stages.md)) | S | validation_failed <1% |
| **P0** | E6: `print` → `logging` | S | observability, разбор прогонов |
| **P1** | LLM cache `(file_slug, chunk_hash)` при relabel | S | −30–50% повторных LLM-вызовов |
| **P1** | Neo4j batch-queue (UNWIND каждые 10–20 exp) | M | −30–40% Neo4j wait |
| **P2** | ~~Семантический чанкинг по заголовкам~~ → **Stage 4.1 done (`cn_v1`)** | — | re-ingest wave |
| **P2** | PPTX + legacy DOC в DocumentParser | M+S | +20–30% покрытия корпуса |
| **P3** | Quality gate + verify-before-overwrite (§2.5, §2D) | M | restored <1–2% |
| **P3** | SQLite outbox + фоновый воркер Neo4j | 5–7 дней | −70–80% Neo4j-time |

---

*Источники: [data_ingestion_overview.md](./data_ingestion_overview.md) · [data_ingestion_overview_answer.md](./data_ingestion_overview_answer.md) · [stages.md](../../stages.md)*
