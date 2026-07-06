# Навигация: `frontend/`

Next.js 16 App Router, static export (`output: "export"`). UX «Инженерный атлас» — три панели: Корпус / Диалог / Студия. Спека: [`DESIGN.md`](../../frontend/DESIGN.md).

## Точки входа

| Путь | Назначение |
|------|------------|
| [`app/page.tsx`](../../frontend/app/page.tsx) | Entry → `components/App.tsx` |
| [`app/layout.tsx`](../../frontend/app/layout.tsx) | Root layout, IBM Plex, `LangProvider` |
| [`components/App.tsx`](../../frontend/components/App.tsx) | Главный layout, state, API-оркестрация |

## Компоненты (`components/`)

| Путь | Назначение |
|------|------------|
| [`CorpusPanel.tsx`](../../frontend/components/CorpusPanel.tsx) | Документы, ingestion, фильтры, роли |
| [`DialoguePanel.tsx`](../../frontend/components/DialoguePanel.tsx) | NL-диалог, синтез ответа, цитаты |
| [`StudioPanel.tsx`](../../frontend/components/StudioPanel.tsx) | Граф, gaps, контрфакты, аналитика |
| [`GraphPanel.tsx`](../../frontend/components/GraphPanel.tsx) | vis-network визуализация |
| [`MiniGraph.tsx`](../../frontend/components/MiniGraph.tsx) | Компактный граф в ответе |
| [`Constellation.tsx`](../../frontend/components/Constellation.tsx) | Карта пробелов |
| [`Header.tsx`](../../frontend/components/Header.tsx) | Шапка, переключатель языка |
| [`Markdown.tsx`](../../frontend/components/Markdown.tsx) | Рендер markdown в ответах |
| [`Passport.tsx`](../../frontend/components/Passport.tsx) | Паспорт эксперимента |
| [`ui.tsx`](../../frontend/components/ui.tsx) | Общие UI-примитивы |

## Lib (`lib/`)

| Путь | Назначение |
|------|------------|
| [`api.ts`](../../frontend/lib/api.ts) | HTTP-клиент к `/api/*` |
| [`types.ts`](../../frontend/lib/types.ts) | TypeScript-типы API |
| [`i18n.ts`](../../frontend/lib/i18n.ts) | RU/EN строки |
| [`LangProvider.tsx`](../../frontend/lib/LangProvider.tsx) | React context локализации |
| [`mock.ts`](../../frontend/lib/mock.ts) | Mock-данные для dev без API |

> **Важно:** в `.gitignore` есть правило `lib/` — оно может игнорировать `frontend/lib/`. Проверяйте наличие файлов перед сборкой.

## Сборка и dev

```bash
cd frontend && bun install && bun run build   # → frontend/out/
cd frontend && bun run dev                    # http://localhost:3000
```

Prod: `frontend/out/` монтируется FastAPI в [`backend/app.py`](../../backend/app.py) → [http://localhost:8000](http://localhost:8000).

## Документация

| Файл | Содержание |
|------|------------|
| [`DESIGN.md`](../../frontend/DESIGN.md) | UX-концепция, три панели, API-привязки |
| [`README.md`](../../frontend/README.md) | Установка и команды |
| [`CLAUDE.md`](../../frontend/CLAUDE.md) | Ссылка на AGENTS.md для AI-агентов |
