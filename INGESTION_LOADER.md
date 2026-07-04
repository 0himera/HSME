# Corpus Ingestion Loader

Standalone-скрипт для скачивания, распаковки и запуска ingestion pipeline корпуса документов с публичных ссылок Яндекс.Диска.

## Что делает

1. Скачивает архив по публичному URL Яндекс.Диска (Public API) — опционально, флаг `--archive-url`.
2. Распаковывает содержимое в локальный кэш `.cache/hsme_corpus_loader/`.
3. Парсит DOCX/PDF и режет на чанки.
4. Вызывает LLM через `NLPExtractor` (OpenRouter или Yandex Cloud — см. `.env`) для извлечения сущностей и связей.
5. Создаёт `Experiment` и пишет в локальную VSA-базу (pickle).
6. Опционально дублирует данные в Neo4j (`USE_NEO4J`, по умолчанию включён; отключить — `--no-neo4j`).

Повторный запуск идемпотентен: чанки с уже существующим ID (`EXP-{code}-{index:02d}`) пропускаются до вызова LLM.

## Связанные файлы

| Файл | Роль |
|------|------|
| `backend/repository/corpus_loader.py` | CLI entrypoint |
| `backend/core/config.py` | `resolve_llm_settings()` — CLI → env → `.env` |
| `backend/services/nlp_extractor.py` | OpenAI-compatible клиент, промпт из YAML |
| `backend/prompts/nlp_extractor.yaml` | Промпт entity/relation extraction |
| `backend/services/ingestion.py` | Пайплайн, идемпотентность, инъекция экстрактора |
| `backend/services/document_parser.py` | Сканирование каталогов, парсинг файлов |
| `.env.example` | Шаблон LLM-кредов |
| `tests/test_corpus_loader.py` | Юнит-тесты |

## Быстрый старт

```bash
# 1. Креды LLM (обязательны для реального прогона, не dry-run)
cp .env.example .env
# отредактируйте .env — см. раздел «Креды LLM» ниже

# 2. Dry-run: только сканирование test_data/, без LLM и записи в БД
PYTHONPATH=. uv run python -m backend.repository.corpus_loader --mode test --dry-run

# 3. Test mode: до 15 файлов из test_data/ (папки Обзоры / Статьи / Доклады)
PYTHONPATH=. uv run python -m backend.repository.corpus_loader --mode test

# 4. Prod: полный корпус — локально из data/ или с Яндекс.Диска
PYTHONPATH=. uv run python -m backend.repository.corpus_loader \
  --archive-url "https://disk.yandex.ru/d/npigiuw4Rbe9Pg" \
  --mode prod \
  --no-neo4j
```

## Режим test vs prod

| | test | prod |
|---|------|------|
| Папка по умолчанию | `test_data/` | `data/` |
| Каталоги | только `Обзоры`, `Статьи`, `Доклады` | те же + всё под `Источники информации` |
| Лимит файлов | 15 | без лимита (`999999`) |

Переопределить лимит: `--max-files N`. Переопределить корень: `--data-dir /path/to/corpus`.

### Откуда взять test_data/

**Вариант A** — скачать сэмпл с Яндекс.Диска (локальный helper, каталог `scripts/` в `.gitignore`):

```bash
PYTHONPATH=. python3 scripts/download_yadisk_samples.py
```

Скрипт кладёт по одному файлу из каждой подпапки в `test_data/`.

**Вариант B** — сразу через loader с `--archive-url` (скачивает zip-архив в кэш).

## Креды LLM

Создайте `.env` в корне проекта из шаблона:

```bash
cp .env.example .env
```

**OpenRouter** (рекомендуется для локальной разработки):

```env
LLM_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
```

**Yandex Cloud**:

```env
LLM_API_KEY=AQVN...
LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1
LLM_FOLDER_ID=b1g...
LLM_MODEL=gpt://b1g.../gpt-oss-120b/latest
```

Приоритет конфигурации: **CLI-флаги** → **переменные окружения процесса** → **`.env` файл** (путь — `--llm-env-file`, по умолчанию `.env`).

Жёстко зашитых API-ключей в коде нет. Для не-dry-run прогона нужны как минимум `LLM_API_KEY` и `LLM_BASE_URL`; для Yandex дополнительно `LLM_FOLDER_ID` или полный URI модели в `LLM_MODEL`.

```bash
# Достаточно .env:
PYTHONPATH=. uv run python -m backend.repository.corpus_loader --mode test

# Другой файл с секретами:
PYTHONPATH=. uv run python -m backend.repository.corpus_loader \
  --mode test \
  --llm-env-file secrets/llm.env

# Переопределение через CLI:
PYTHONPATH=. uv run python -m backend.repository.corpus_loader \
  --mode test \
  --llm-api-key "YOUR_API_KEY" \
  --llm-base-url "https://openrouter.ai/api/v1" \
  --llm-model-id "openai/gpt-4o-mini"
```

`--llm-folder-id` — ID каталога Yandex Cloud (не папка на Яндекс.Диске). Нужен только для YandexGPT; для OpenRouter не требуется.

## CLI-аргументы

| Аргумент | По умолчанию | Описание |
|----------|--------------|----------|
| `--archive-url` | — | Публичная ссылка Яндекс.Диска; скачивает архив в `.cache/hsme_corpus_loader/` |
| `--mode` | `test` | `test` — `test_data/`, 3 папки, до 15 файлов; `prod` — `data/`, полный корпус |
| `--max-files` | из mode | Явный лимит файлов |
| `--data-dir` | из mode | Корень корпуса (`test_data/` или `data/`) |
| `--db-file` | `db_state.pkl` | Pickle-файл VSA-базы (читается и дописывается) |
| `--llm-env-file` | `.env` | Dotenv с `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` и др. |
| `--llm-base-url` | из конфига | Base URL LLM API |
| `--llm-api-key` | из конфига | API key |
| `--llm-folder-id` | из конфига | Yandex Cloud folder ID |
| `--llm-model-id` | из конфига | ID модели (`LLM_MODEL` / `LLM_MODEL_ID`) |
| `--no-neo4j` | Neo4j включён | Отключить dual-write в Neo4j |
| `--dry-run` | `false` | Только парсинг и подсчёт чанков, без LLM и записи в БД |
| `--concurrency` | `6` | Параллельных чанков в LLM |

При `--llm-base-url` с `openrouter.ai` и дефолтном `--concurrency 6` loader автоматически снижает concurrency до `2`, чтобы реже упираться в rate limit.

## Детали реализации

1. **Идемпотентность.** ID чанка: `EXP-{code}-{index:02d}`. Если эксперимент уже в БД — LLM не вызывается.
2. **Отдельный экземпляр БД.** Loader создаёт свой `HSMEVectorDatabase` и пишет в `--db-file`, не трогая in-memory singleton FastAPI-приложения.
3. **Общая конфигурация LLM.** Loader и API (`/api/search`, ingestion) читают одни и те же переменные через `resolve_llm_settings()`; CLI-флаги loader'а переопределяют их только на время этого запуска.
4. **Кэш.** Скачанные архивы — в `.cache/hsme_corpus_loader/` (в `.gitignore`).

## Тесты

```bash
USE_NEO4J=false PYTHONPATH=. uv run pytest tests/test_corpus_loader.py -v
```
