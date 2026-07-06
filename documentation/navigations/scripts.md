# Навигация: `scripts/`

Служебные одноразовые и отладочные скрипты. Запускать через `uv run python scripts/<name>.py`. Регламент: [`topics/automation/automation_brief.md`](../topics/automation/automation_brief.md).

| Скрипт | Назначение |
|--------|------------|
| [`analyze_stage4_relabel.py`](../../scripts/analyze_stage4_relabel.py) | Парсит `relabel-resume.log`, считает метрики validation/Neo4j, генерирует [`topics/ingestion/stage4_relabel_analysis.md`](../topics/ingestion/stage4_relabel_analysis.md) |
| [`download_yadisk_samples.py`](../../scripts/download_yadisk_samples.py) | Скачивает по одному файлу из каждой подпапки публичного Яндекс.Диска → `test_data/` |
| [`test_yandex_aistudio.py`](../../scripts/test_yandex_aistudio.py) | Smoke-тест Yandex AI Studio API (ручная проверка кредов) |
