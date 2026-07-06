# Навигация: `test_data/`

Урезанный корпус для dev/test ingestion (`--mode test`). В `.gitignore` — не коммитится в репозиторий.

## Структура

```
test_data/
  Обзоры/          ← обзорные документы (PDF/DOCX)
  Статьи/          ← научные статьи
  Доклады/         ← доклады конференций
  Источники информации/   ← доп. источники кейса
```

## Как получить

```bash
uv run python scripts/download_yadisk_samples.py
# или corpus loader с --mode test
```

Источник prod-архива: [Яндекс.Диск](https://disk.yandex.ru/d/npigiuw4Rbe9Pg) (полный multi-GB корпус → `data/`).

## Связанный код

| Путь | Назначение |
|------|------------|
| [`backend/repository/corpus_loader.py`](../../backend/repository/corpus_loader.py) | CLI: `--mode test` читает `test_data/` |
| [`scripts/download_yadisk_samples.py`](../../scripts/download_yadisk_samples.py) | Скачивание сэмплов с Яндекс.Диска |
| [`INGESTION_LOADER.md`](../../INGESTION_LOADER.md) | Регламент loader: test/prod, dry-run |
