# Corpus Ingestion Loader

Отдельный скрипт для скачивания, распаковки и запуска `ingestion pipeline` корпуса документов с публичных ссылок Яндекс Диска.

## Основное назначение
Загрузчик реализует пайплайн:
- скачивание архива с документами по публичному URL Яндекс Диска (Yandex Disk Public API);
- распаковка содержимого в локальный кэш;
- парсинг файлов (DOCX, PDF) и разделение на чанки;
- использование YandexGPT (через `NLPExtractor`) для извлечения сущностей и отношений;
- создание структуры `Experiment` и запись её в локальную VSA-базу (pickle);
- опциональный dual-write в Neo4j (через `USE_NEO4J`).

Загрузчик умеет дедуплицировать чанки до вызова LLM. Если запустить его повторно (в режиме prod после test), он пропустит уже обработанные чанки, экономя время и запросы к API.

## Затронутые файлы
- `backend/repository/corpus_loader.py` — новый standalone-модуль.
- `backend/core/config.py` — чтение LLM-кредов из `.env`.
- `backend/services/ingestion.py` — добавлена идемпотентность (пропуск уже загруженных чанков) и инъекция экстрактора.
- `.gitignore` — добавлена директория для кэша (`.cache/hsme_corpus_loader/`).
- `tests/test_corpus_loader.py` — юнит-тесты загрузчика.

## Быстрый старт
```bash
# Test mode: локальный test_data/, только папки Обзоры / Статьи / Доклады (до 15 файлов)
PYTHONPATH=. uv run python -m backend.repository.corpus_loader --mode test --dry-run

# Test mode с вашим API-ключом (folder_id можно не указывать — возьмётся дефолт из кода)
PYTHONPATH=. uv run python -m backend.repository.corpus_loader \
  --mode test \
  --llm-api-key "YOUR_API_KEY"

# Prod: полный корпус из data/ или с Яндекс Диска
PYTHONPATH=. uv run python -m backend.repository.corpus_loader \
  --archive-url "https://disk.yandex.ru/d/npigiuw4Rbe9Pg" \
  --mode prod \
  --no-neo4j
```

## Режим test vs prod

| | test | prod |
|---|------|------|
| Папка по умолчанию | `test_data/` | `data/` |
| Какие каталоги сканируются | только `Обзоры`, `Статьи`, `Доклады` | `Обзоры`, `Статьи`, `Доклады` + всё под `Источники информации` |
| Лимит файлов | 15 | без лимита |

Перед test-прогоном скачайте сэмпл корпуса:
```bash
PYTHONPATH=. python3 scripts/download_yadisk_samples.py
```

## Креды нейросети

Создайте файл `.env` в корне проекта (он уже в `.gitignore`):

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
# или для YandexGPT:
# LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1
# LLM_MODEL=gpt://b1g.../gpt-oss-120b/latest
# LLM_FOLDER_ID=b1g...
```

Приоритет: **CLI-флаги** → **переменные окружения** → **`.env` файл** → дефолты из `nlp_extractor.py`.

```bash
# Достаточно положить ключ и url в .env и запустить:
PYTHONPATH=. python3 -m backend.repository.corpus_loader --mode test

# Другой файл с секретами:
PYTHONPATH=. python3 -m backend.repository.corpus_loader --mode test --llm-env-file secrets/llm.env
```

`--llm-folder-id` — это **ID каталога Yandex Cloud** для YandexGPT, не папка на Яндекс.Диске. Его можно не указывать, если подходит дефолт из кода.

## Доступные аргументы (CLI)

| Аргумент | По умолчанию | Описание |
|----------|--------------|----------|
| `--archive-url` | `None` | Публичная ссылка на папку Яндекс Диска для скачивания |
| `--mode` | `test` | `test`: `test_data/`, папки Обзоры/Статьи/Доклады, до 15 файлов. `prod`: `data/`, полный корпус |
| `--max-files` | `None` | Явное переопределение количества файлов (заменяет лимит `mode`) |
| `--data-dir` | см. mode | `test_data/` или `data/`; можно переопределить вручную |
| `--db-file` | `db_state.pkl` | Путь к выходному/входному файлу БД (VSA pickle) |
| `--llm-env-file` | `.env` | Файл с `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` и др. |
| `--llm-base-url` | из `.env` | Custom LLM API base URL |
| `--llm-api-key` | из `.env` | Custom LLM API key |
| `--llm-folder-id`| `None` | Кастомный Folder ID (Project ID) для LLM (заменяет вшитый) |
| `--llm-model-id` | из `.env` | ID модели (`LLM_MODEL` или `LLM_MODEL_ID` в `.env`) |
| `--no-neo4j` | `False` | Отключить двойную запись в Neo4j (даже если он сконфигурирован) |
| `--dry-run` | `False` | Выполнить только парсинг документов (план), без вызова LLM и БД |
| `--concurrency` | `6` | Количество одновременных чанков, отправляемых в LLM |

## Особенности реализации
1. **Идемпотентность**. Перед тем как отправить чанк в LLM, скрипт вычисляет его уникальный ID по шаблону `EXP-{code}-{index:02d}`. Если он уже есть в БД, запрос пропускается.
2. **Изолированность**. Для работы загрузчика создается отдельная структура `HSMEVectorDatabase`, не влияющая на глобальный объект, работающий в основном FastAPI приложении.
3. **Безопасность конфигурации LLM**. Переданные ключи `--llm-api-key` и остальные параметры влияют только на выполнение данного скрипта, не меняя код FastAPI-приложения и встроенный дефолтный `nlp_extractor`.
4. **Кэширование**. При скачивании с Яндекс Диска, файлы временно сохраняются в `.cache/hsme_corpus_loader`, которая добавлена в `.gitignore`.

## Запуск тестов
```bash
USE_NEO4J=false PYTHONPATH=. uv run pytest tests/test_corpus_loader.py -v
```