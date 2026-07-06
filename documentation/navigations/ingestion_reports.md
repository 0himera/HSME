# Навигация: `ingestion_reports/`

Артефакты прогонов corpus loader / relabel. Каждый прогон — подпапка `{run_id}/` (UTC timestamp, напр. `20260706T213453Z/`).

## Структура прогона

```
ingestion_reports/{run_id}/
  summary.json    ← агрегированная статистика
```

## Поля `summary.json`

| Поле | Описание |
|------|----------|
| `run_id` | Идентификатор прогона (совпадает с именем папки) |
| `counts` | Сводка по статусам: `ok`, `restored`, `skipped`, `validation_failed`, `moderation`, `empty` |
| `files_indexed_count` | Число обработанных файлов |
| `total_chunks_indexed` | Число проиндексированных чанков |
| `files_skipped_count` | Пропущенные файлы (resume/skip) |
| `total_experiments_in_db` | Размер VSA БД после прогона |
| `chunk_outcomes` | Детализация по чанкам (если включена) |

## Связанный код

- Запись отчётов: [`backend/services/ingestion.py`](../../backend/services/ingestion.py), [`backend/repository/corpus_loader.py`](../../backend/repository/corpus_loader.py)
- Анализ Stage 4: [`scripts/analyze_stage4_relabel.py`](../../scripts/analyze_stage4_relabel.py) → читает `logs/relabel/relabel-resume.log`
- Документация: [`topics/ingestion/`](../topics/ingestion/), [`INGESTION_LOADER.md`](../../INGESTION_LOADER.md)
