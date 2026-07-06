# Архитектурный Аудит — HSME (HyperGraph Research Memory Engine)

> Дата аудита: 2026-07-04
> Дедлайн хакатона: 2026-07-04 23:59

---

## 1. Критические баги (🔴 нужно исправить до сдачи)

### 1.1. Walrus-оператор в декораторах — невалидный Python

**Файл:** [experiments.py](file:///home/himera/projects/HSME/backend/routers/experiments.py#L9-L24)

```python
@app_post := router.post("/ingest")       # ← СИНТАКСИЧЕСКАЯ ОШИБКА
async def ingest_experiment(...):

@app_get := router.get("/experiments")     # ← СИНТАКСИЧЕСКАЯ ОШИБКА
async def get_all_experiments(...):
```

> [!CAUTION]
> Walrus-оператор `:=` **нельзя** использовать в декораторе. Это SyntaxError в любой версии Python. Файл не импортируется — значит эндпоинты `/api/ingest` и `/api/experiments` **не работают**. Если это остался артефакт от генерации кода, нужно срочно вернуть стандартный синтаксис: `@router.post("/ingest")`.

**Приоритет: БЛОКЕР** — 2 эндпоинта полностью сломаны.

---

### 1.2. Pickle-персистентность — save_to_disk на каждый insert и каждый log_action

**Файл:** [database.py](file:///home/himera/projects/HSME/backend/repository/database.py#L169-L189)

```python
def insert_experiment(self, experiment):
    ...
    self.save_to_disk(self.db_filepath)     # ← СИНХРОННАЯ ЗАПИСЬ 7 МБ НА ДИСК

def log_action(self, ...):
    ...
    self.save_to_disk(self.db_filepath)     # ← КАЖДЫЙ HTTP-запрос = pickle.dump(7 MB)
```

> [!WARNING]
> **Каждый** HTTP-запрос (даже `GET /statistics`) логируется через `log_action`, который **сериализует весь in-memory state (~7.6 МБ) в pickle**. Это:
> - **O(n)** по числу экспериментов на каждый запрос
> - Блокирует event loop (синхронный I/O в async-контексте)
> - При параллельных запросах — **data race** (два потока пишут в один файл одновременно)

**Быстрый фикс:** Убрать `save_to_disk` из `log_action`. Аудит-логи сохранять отдельно (append в файл) или вообще в память до graceful shutdown. Сделать save_to_disk debounced или по явному триггеру.

---

### 1.3. Глобальный `np.random.seed(42)` в конструкторе VSA

**Файл:** [vsa.py](file:///home/himera/projects/HSME/backend/core/vsa.py#L4-L7)

```python
def __init__(self, dim: int = 10000, seed: int = None):
    self.dim = dim
    if seed is not None:
        np.random.seed(seed)   # ← ГЛОБАЛЬНЫЙ seed
```

> [!WARNING]
> `np.random.seed()` устанавливает **глобальное** состояние RNG для всего процесса. В многопоточном/многозадачном FastAPI-контексте это означает:
> - Два concurrent запроса, которые вызывают `generate_vector()`, получат **детерминированно одинаковые** вектора, что нарушает свойства VSA (ортогональность случайных гипервекторов)
> - `bundle()` с random tie-breaking также затронут

**Фикс:** Использовать `np.random.Generator` (экземпляр `np.random.default_rng(seed)`) вместо глобального seed.

---

## 2. Архитектурные проблемы (🟠 средний риск)

### 2.1. Отсутствие потокобезопасности в in-memory БД

[HSMEVectorDatabase](file:///home/himera/projects/HSME/backend/repository/database.py) — это один глобальный `db` объект на весь процесс. У него нет ни `threading.Lock`, ни `asyncio.Lock`. Параллельные запросы (Uvicorn с workers > 1 или asyncio concurrency при ingestion) могут привести к:

- Коррупции `self.codebook` и `self.vector_store` при одновременной записи
- Неконсистентному состоянию при одновременном `insert_experiment + search`
- Race condition в `audit_logs` (append + save_to_disk)

### 2.2. Сложность загрузки модуля database.py при import-time

```python
# Конец файла database.py (строки 404-414)
db = HSMEVectorDatabase(dim=10000)
if not db.load_from_disk(...) or not any(...) or not any(...):
    seed_database(db)
    db.save_to_disk(db.db_filepath)
```

> [!IMPORTANT]
> При **каждом импорте** модуля `backend.repository.database` (включая тесты, CLI-скрипты, type-checking) выполняется:
> 1. Создание объекта БД
> 2. Чтение pickle-файла (7.6 МБ)
> 3. Проверка условия на наличие отношений / чувствительных данных
> 4. Потенциально — полная пересидация
>
> Это делает юнит-тестирование крайне хрупким и может вызывать ошибки при first-import.

### 2.3. Ингест записывает на диск при каждом чанке

[ingestion.py:117](file:///home/himera/projects/HSME/backend/services/ingestion.py#L117): `self.db.insert_experiment(experiment)` вызывается **для каждого** чанка каждого документа. `insert_experiment` → `save_to_disk`. При ингесте 15 файлов с ~20 чанками каждый — **~300 полных pickle-дампов по 7+ МБ**. С concurrency_limit=6 — 6 одновременных записей в один файл.

### 2.4. NLPExtractor создаётся заново на каждый вызов

В [search.py](file:///home/himera/projects/HSME/backend/routers/search.py#L31) и [analytics.py](file:///home/himera/projects/HSME/backend/routers/analytics.py#L73):

```python
extractor = NLPExtractor()   # ← НОВЫЙ AsyncOpenAI клиент КАЖДЫЙ РАЗ
```

Это создаёт новый HTTP-клиент (connection pool) на каждый запрос — неэффективно и может исчерпать файловые дескрипторы при нагрузке.

### 2.5. Condition для re-seeding слишком хрупкий

```python
if not db.load_from_disk(...) or not any(exp.is_sensitive for ...) or not any(getattr(exp, "relations", None) for ...):
```

Если **все** импортированные из реальных документов эксперименты не имеют `is_sensitive=True`, то база пересидится с нуля, **уничтожив** все загруженные данные. Это тихая потеря данных.

---

## 3. Проблемы безопасности (🟡 для хакатона некритично, но жюри может заметить)

### 3.1. Аутентификация на доверии клиенту

[dependencies.py](file:///home/himera/projects/HSME/backend/routers/dependencies.py#L9-L20): Роль определяется из заголовков `X-User-Name` и `X-User-Role`, которые клиент может установить произвольно. Любой пользователь может стать администратором. Для хакатона это допустимо (демо), но стоит упомянуть в презентации как осознанное архитектурное решение.

### 3.2. CORS: allow_origins=["*"]

Все origins разрешены — стандартно для хакатона, но стоит зафиксировать в документации.

### 3.3. Pickle deserialization

[database.py:158-159](file:///home/himera/projects/HSME/backend/repository/database.py#L158-L159): `pickle.load(f)` — классический вектор атаки для Remote Code Execution. В продакшене недопустимо, для хакатона — ОК.

---

## 4. Математические замечания по VSA (🟡)

### 4.1. Bundling при неравном числе компонентов

При `bundle()` используется majority vote. Если один эксперимент имеет 4 entities, а другой 12 — их результирующие гипервекторы будут иметь **разную информационную ёмкость**. Это влияет на качество поиска: эксперименты с большим числом сущностей будут хуже матчиться, потому что каждый отдельный компонент «размывается» в majority vote.

### 4.2. Отсутствие весов при bundling

Все компоненты гиперребра (input, process, output, relations) имеют **равный вес** в bundling. На практике Material и Process важнее, чем Publication или Expert для семантического поиска. Рекомендуется взвешенный bundling (повторять критические компоненты 2-3 раза в списке перед bundle).

### 4.3. Cosine similarity на биполярных векторах

Формула `dot(v1, v2) / dim` работает корректно **только** когда оба вектора — чистые биполярные (+1/-1). Но после `bundle()` вектор приводится к знаку (`np.sign`), так что это OK. Однако в `get_entity_vector` для числовых properties создаётся **неявно не-биполярный** вектор (фрагментированная интерполяция v_min/v_max), что по-прежнему работает, поскольку v_min и v_max сами биполярные, но стоит задокументировать это допущение.

---

## 5. Рекомендация по графовой БД

### Нужна ли вообще?

**Для хакатона — нет.** Вот почему:

| Фактор | Аргумент |
|--------|----------|
| **Текущая архитектура** | VSA-гипервектора — это уже ваше математическое ядро поиска. Добавление Neo4j создаёт **дублирование данных** (два источника правды) |
| **Объём данных** | ~70-200 экспериментов, ~1000 сущностей. In-memory хранилище справляется за микросекунды |
| **Время до дедлайна** | Интеграция Neo4j — это 4-6 часов работы с учётом тестирования. Риск сломать работающую систему |
| **Ценность для жюри** | VSA-подход — ваше **конкурентное преимущество**. Добавление Neo4j размывает уникальность решения |
| **ТЗ "рекомендует"** | В ТЗ сказано «рекомендуется», а не «обязательно». Вы используете VSA, которое выполняет ту же функцию, но другим путём |

### Если бы нужно было — какую выбрать?

| БД | Подходит? | Причина |
|----|-----------|---------|
| **Neo4j Community** | ✅ Лучший выбор | Cypher = идеальный язык для запросов типа «покажи путь Material→Process→Property». Community Edition — бесплатна. Python-драйвер `neo4j` зрелый |
| **Amazon Neptune** | ❌ | Облачная, требует AWS аккаунт, настройку VPC. Overkill для хакатона |
| **JanusGraph** | ❌ | Требует Cassandra/HBase как бэкенд. Сложность развёртывания ~10x vs Neo4j |
| **Memgraph** | ⚠️ Альтернатива | Тот же Cypher, но in-memory (быстрее Neo4j). Проще развернуть через Docker |

### Если всё же интегрировать — архитектурный паттерн

Не заменять VSA на графовую БД, а **использовать обе параллельно**:

```text
Document → NLP Extraction
    ├── VSA Encoder → Qdrant/in-memory (semantic search, gap analysis)
    └── Graph Writer → Neo4j (traversal queries, visualization, Cypher)
```

- **VSA** для: семантического поиска, контрфактического анализа, gap discovery
- **Neo4j** для: визуализации графа (заменить Vis.js на Neo4j Browser / Bloom), Cypher-запросов, traversal

---

## 6. Быстрые фиксы для хакатона (приоритет по impact/effort)

| # | Проблема | Фикс | Время |
|---|----------|------|-------|
| 1 | 🔴 Walrus-оператор в experiments.py | Заменить `@app_post := router.post(...)` на `@router.post(...)` | 2 мин |
| 2 | 🔴 save_to_disk в log_action | Убрать `self.save_to_disk()` из `log_action()`, добавить periodic save или save-on-shutdown | 5 мин |
| 3 | 🟠 Глобальный np.random.seed | Заменить на `self.rng = np.random.default_rng(seed)` | 15 мин |
| 4 | 🟠 NLPExtractor recreated per request | Создать один глобальный экземпляр (как `pipeline`) | 5 мин |
| 5 | 🟠 Хрупкий re-seed condition | Упростить до `if not db.load_from_disk():` + ручной флаг | 5 мин |
| 6 | 🟡 Bundling без весов | Повторить Material/Process вектора 2x при encode_experiment | 10 мин |

---

## 7. Резюме

**Сильные стороны проекта:**
- Оригинальная идея VSA + Hypergraph — это реально выделяет вас среди участников
- Контрфактический анализ и gap discovery — мощные аналитические инструменты
- Ролевая модель и аудит реализованы
- NLP-пайплайн с YandexGPT работает

**Главные риски:**
1. **Файл experiments.py не импортируется** (walrus operator) — два ключевых эндпоинта мертвы
2. **Производительность I/O** — pickle dump на каждый запрос убьёт систему при демо
3. **Отсутствие thread safety** — при concurrency возможна порча данных

**По графовой БД:** Не ставить. Ваш VSA-подход — это и есть ваш главный аргумент. Упомяните в презентации, что Neo4j планируется как дополнительный слой для Cypher-запросов, но текущая архитектура решает задачу поиска по гиперграфу через VSA-алгебру, что эффективнее триплетного обхода для вашего use case.
