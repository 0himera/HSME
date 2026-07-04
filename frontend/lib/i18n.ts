// ─── HSME i18n ────────────────────────────────────────────────────────────────
// Минимальный подход без внешних зависимостей.
// Использование: const { t, lang } = useLang();

import { useContext } from "react";
import { LangContext } from "./LangProvider";

export type Lang = "ru" | "en";

export const dict = {
  ru: {
    // Header
    header_subtitle: "гиперграфовая научная память R&D",
    header_edges: "экспериментов",
    header_role_label: "Активная роль",
    header_role_note: "роль передаётся ядру в заголовках запроса",
    header_lang_toggle: "EN",
    header_theme_toggle_dark: "Тёмная",
    header_theme_toggle_light: "Светлая",

    // Roles
    role_admin: "Администратор",
    role_analyst: "Аналитик",
    role_researcher: "Исследователь",
    role_partner: "Внешний партнёр",

    // CorpusPanel
    corpus_title: "База Экспериментов",
    corpus_loading: "Загрузка базы данных...",
    corpus_empty: "Нет доступных экспериментов.",
    corpus_search_placeholder: "Поиск по ID, названию, свойствам...",
    corpus_filter_all: "Все",
    corpus_filter_sensitive: "Только публичные",
    corpus_no_results: "Не найдено. Попробуйте изменить запрос.",
    corpus_page_of: "из",
    corpus_prev: "Пред",
    corpus_next: "След",
    corpus_private: "Приватный",
    corpus_full_access: "полный доступ к приватным данным",
    corpus_restricted: "внутренние отчёты скрыты",
    corpus_ingest_title: "Импорт:",
    corpus_ingest_running: "Импорт...",
    corpus_ingest_done: "Завершён успешно",
    corpus_ingest_failed: "Сбой:",
    corpus_ingest_ready: "Готов к импорту",
    corpus_ingest_btn: "Импортировать корпус",
    corpus_ingest_btn_running: "Импортируем...",
    corpus_filter_geo: "Регион",
    corpus_filter_year: "Год",
    corpus_filter_type: "Тип",

    // StudioPanel
    studio_title: "Студия",
    studio_graph_title: "Граф знаний",
    studio_graph_context: "(Контекст поиска)",
    studio_graph_edges: "рёбер",
    studio_graph_expand: "Кликните, чтобы развернуть",
    studio_gaps_title: "Карта пробелов",
    studio_gaps_partner_locked: "Доступно только внутренним ролям",
    studio_gaps_empty: "Не найдено белых пятен",
    studio_gaps_researched: "Исследованная область",
    studio_gaps_gen_hint: "Клик: сгенерировать гипотезу",
    studio_hyp_title: "Сгенерированные гипотезы",
    studio_hyp_loading: "Нейросеть строит гипотезу...",
    studio_hyp_failed: "Не удалось сгенерировать",
    studio_hyp_expand: "Читать полностью",
    studio_hyp_collapse: "Свернуть",
    studio_cf_label: "Сгенерировано контрфактов:",
    studio_report_label: "Статус синтеза отчёта:",
    studio_report_waiting: "ожидание...",
    studio_copy: "Копировать",
    studio_copied: "Скопировано",
    studio_partner_locked: "Доступно только внутренним ролям",

    // DialoguePanel
    dialogue_empty_title: "Спросите научную память",
    dialogue_empty_subtitle:
      "Каждый ответ собирается из гиперрёбер — целостных экспериментов с условиями, результатами и источниками. Не документы, а научные события.",
    dialogue_placeholder: "Спросите про материалы, режимы, свойства…",
    dialogue_send: "Отправить запрос",
    dialogue_synthesis: "синтез по",
    dialogue_synthesis_experiments: "экспериментам",
    dialogue_results_label: "Результаты семантического VSA-поиска:",
    dialogue_conditions: "Условия и процесс",
    dialogue_similarity: "Сходство:",
    dialogue_consensus: "Согласованность источников",
    dialogue_consensus_ok: "консенсус",
    dialogue_contradict: "противоречат",
    dialogue_cf_label: "контрфактная пара · отличие в одном параметре",

    // Thinking steps
    think_1: "разбор запроса на сущности",
    think_2: "связывание V_query = V_x ⊗ V_y",
    think_3: "поиск по гиперрёбрам корпуса",
    think_4: "оценка согласованности источников",
    think_5: "синтез научного ответа",

    // Passport
    passport_label: "ПАСПОРТ ЭКСПЕРИМЕНТА",
    passport_confidence: "достоверность",
    passport_in: "Вход",
    passport_process: "Процесс",
    passport_out: "Выход",
    passport_evidence: "Доказательства",
    passport_relations: "Семантические связи",
    passport_close: "Закрыть",
    passport_doc: "Документ",
    passport_internal: "внутренний",
    passport_open: "открытый",

    // App-level
    app_no_results:
      "### Вывод\nПо выбранному корпусу релевантных экспериментов не найдено. Попробуйте переформулировать запрос или снять фильтры.",
    app_found_title: "### Найденные научные события",
    app_confidence: "достоверность",
    app_restricted:
      "Авто-синтез ответа (LLM Reasoner) доступен ролям «Аналитик» и «Администратор».",

    // Mobile navigation
    mobile_tab_chat: "Чат",
    mobile_tab_corpus: "База",
    mobile_tab_studio: "Студия",
    mobile_back_to_chat: "Назад к чату",

    // Suggested queries
    suggested_queries: [
      "Какие технические решения организации циркуляции католита при электроэкстракции никеля описаны в мировой практике, и какая скорость потока считается оптимальной?",
      "Какие методы обессоливания воды подходят для обогатительной фабрики, если исходная вода содержит сульфаты, хлориды, Ca, Mg, Na по 200–300 мг/л, а требуемый сухой остаток — ≤1000 мг/дм³?",
      "Покажите все эксперименты и публикации по распределению Au, Ag и МПГ между медным/никелевым штейном и шлаком за последние 5 лет",
      "Какие способы закачки шахтных вод в глубокие горизонты применялись в России и за рубежом, и каковы их технико-экономические показатели?",
    ],

    // locale for numbers
    locale: "ru-RU",
  },

  en: {
    // Header
    header_subtitle: "hypergraph R&D research memory",
    header_edges: "experiments",
    header_role_label: "Active role",
    header_role_note: "role is passed to the core via request headers",
    header_lang_toggle: "RU",
    header_theme_toggle_dark: "Dark",
    header_theme_toggle_light: "Light",

    // Roles
    role_admin: "Administrator",
    role_analyst: "Analyst",
    role_researcher: "Researcher",
    role_partner: "External Partner",

    // CorpusPanel
    corpus_title: "Experiment Database",
    corpus_loading: "Loading database...",
    corpus_empty: "No experiments available.",
    corpus_search_placeholder: "Search by ID, name, properties...",
    corpus_filter_all: "All",
    corpus_filter_sensitive: "Public only",
    corpus_no_results: "No results. Try a different query.",
    corpus_page_of: "of",
    corpus_prev: "Prev",
    corpus_next: "Next",
    corpus_private: "Private",
    corpus_full_access: "full access to private data",
    corpus_restricted: "internal reports hidden",
    corpus_ingest_title: "Import:",
    corpus_ingest_running: "Importing...",
    corpus_ingest_done: "Completed successfully",
    corpus_ingest_failed: "Failed:",
    corpus_ingest_ready: "Ready to import",
    corpus_ingest_btn: "Import corpus",
    corpus_ingest_btn_running: "Importing...",
    corpus_filter_geo: "Region",
    corpus_filter_year: "Year",
    corpus_filter_type: "Type",

    // StudioPanel
    studio_title: "Studio",
    studio_graph_title: "Knowledge Graph",
    studio_graph_context: "(Search Context)",
    studio_graph_edges: "edges",
    studio_graph_expand: "Click to expand",
    studio_gaps_title: "Gap Map",
    studio_gaps_partner_locked: "Available to internal roles only",
    studio_gaps_empty: "No knowledge gaps found",
    studio_gaps_researched: "Researched area",
    studio_gaps_gen_hint: "Click: generate hypothesis",
    studio_hyp_title: "Generated Hypotheses",
    studio_hyp_loading: "Neural net is building a hypothesis...",
    studio_hyp_failed: "Failed to generate",
    studio_hyp_expand: "Read more",
    studio_hyp_collapse: "Collapse",
    studio_cf_label: "Counterfactuals generated:",
    studio_report_label: "Report synthesis status:",
    studio_report_waiting: "waiting...",
    studio_copy: "Copy",
    studio_copied: "Copied",
    studio_partner_locked: "Available to internal roles only",

    // DialoguePanel
    dialogue_empty_title: "Query the Research Memory",
    dialogue_empty_subtitle:
      "Every answer is assembled from hyperedges — complete experiments with conditions, results, and sources. Not documents — scientific events.",
    dialogue_placeholder: "Ask about materials, processes, properties…",
    dialogue_send: "Send query",
    dialogue_synthesis: "synthesis from",
    dialogue_synthesis_experiments: "experiments",
    dialogue_results_label: "Semantic VSA search results:",
    dialogue_conditions: "Conditions & process",
    dialogue_similarity: "Similarity:",
    dialogue_consensus: "Source consensus",
    dialogue_consensus_ok: "consensus",
    dialogue_contradict: "contradict",
    dialogue_cf_label: "counterfactual pair · single-parameter difference",

    // Thinking steps
    think_1: "parsing query into entities",
    think_2: "binding V_query = V_x ⊗ V_y",
    think_3: "searching hyperedge corpus",
    think_4: "evaluating source consistency",
    think_5: "synthesizing scientific answer",

    // Passport
    passport_label: "EXPERIMENT PASSPORT",
    passport_confidence: "confidence",
    passport_in: "Input",
    passport_process: "Process",
    passport_out: "Output",
    passport_evidence: "Evidence",
    passport_relations: "Semantic relations",
    passport_close: "Close",
    passport_doc: "Document",
    passport_internal: "internal",
    passport_open: "open",

    // App-level
    app_no_results:
      "### Conclusion\nNo relevant experiments found for the selected corpus. Try rephrasing your query or removing filters.",
    app_found_title: "### Found scientific events",
    app_confidence: "confidence",
    app_restricted:
      "Auto-synthesis (LLM Reasoner) is available for Analyst and Administrator roles.",

    // Mobile navigation
    mobile_tab_chat: "Chat",
    mobile_tab_corpus: "Database",
    mobile_tab_studio: "Studio",
    mobile_back_to_chat: "Back to chat",

    // Suggested queries
    suggested_queries: [
      "What technical solutions for catholyte circulation in nickel electroextraction are described in global practice, and what flow rate is considered optimal?",
      "What water desalination methods are suitable for a processing plant if source water contains sulfates, chlorides, Ca, Mg, Na at 200–300 mg/L and required TDS is ≤1000 mg/dm³?",
      "Show all experiments and publications on Au, Ag and PGM distribution between copper/nickel matte and slag over the last 5 years",
      "What methods of mine water injection into deep horizons have been used in Russia and abroad, and what are their technical and economic indicators?",
    ],

    // locale for numbers
    locale: "en-US",
  },
} as const;
 
export const pluralForms = {
  experiments: {
    ru: ["эксперимент", "эксперимента", "экспериментов"],
    en: ["experiment", "experiments"],
  },
  edges: {
    ru: ["ребро", "ребра", "рёбер"],
    en: ["edge", "edges"],
  },
} as const;

export type DictKey = keyof (typeof dict)["ru"];
 
export function useLang(): {
  t: (key: DictKey) => string;
  tPlural: (count: number, key: "experiments" | "edges") => string;
  tArr: (key: "suggested_queries") => readonly string[];
  lang: Lang;
  setLang: (l: Lang) => void;
  theme: "dark" | "light";
  setTheme: (t: "dark" | "light") => void;
} {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used inside LangProvider");
  const { lang, setLang, theme, setTheme } = ctx;
  const d = dict[lang];
 
  const t = (key: DictKey): string => {
    const v = d[key];
    if (Array.isArray(v)) return v.join(", ");
    return v as string;
  };
 
  const tPlural = (count: number, key: "experiments" | "edges"): string => {
    const forms = pluralForms[key][lang];
    if (lang === "en") {
      return count === 1 ? forms[0] : forms[1];
    }
    const ruForms = forms as readonly [string, string, string];
    const mod10 = count % 10;
    const mod100 = count % 100;
    if (mod100 >= 11 && mod100 <= 14) return ruForms[2];
    if (mod10 === 1) return ruForms[0];
    if (mod10 >= 2 && mod10 <= 4) return ruForms[1];
    return ruForms[2];
  };

  const tArr = (key: "suggested_queries"): readonly string[] =>
    d[key] as readonly string[];
 
  return { t, tPlural, tArr, lang, setLang, theme, setTheme };
}
