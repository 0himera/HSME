"use client";

import type { DocInfo, Statistics, UserSession } from "@/lib/types";
import { Icon, PanelLabel, TickNumber } from "./ui";

function DocCheckbox({ checked }: { checked: boolean }) {
  return (
    <span
      className={`mt-0.5 w-[15px] h-[15px] shrink-0 rounded-[4px] border flex items-center justify-center transition-colors duration-200 ${
        checked
          ? "border-copper bg-coppertint"
          : "border-linestrong bg-transparent"
      }`}
    >
      {checked && (
        <svg
          width="9"
          height="9"
          viewBox="0 0 10 10"
          fill="none"
          stroke="var(--copper-bright)"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ animation: "check-pop .22s cubic-bezier(.34,1.56,.64,1) both" }}
        >
          <path d="M1.5 5.5L4 8L8.5 2" />
        </svg>
      )}
    </span>
  );
}

export default function CorpusPanel({
  docs,
  selected,
  onToggle,
  geography,
  onGeography,
  user,
  stats,
  loading,
}: {
  docs: DocInfo[];
  selected: Set<string>;
  onToggle: (filename: string) => void;
  geography: string | null;
  onGeography: (g: string | null) => void;
  user: UserSession;
  stats: Statistics | null;
  loading: boolean;
}) {
  const isPartner = user.role === "External Partner";

  return (
    <aside className="w-[248px] shrink-0 bg-panel border-r border-line flex flex-col overflow-hidden">
      <div className="px-4 pt-4 pb-3 border-b border-line">
        <PanelLabel>Корпус</PanelLabel>
        <div className="flex gap-1.5 flex-wrap">
          {[
            { key: "RU", label: "РФ" },
            { key: "Global", label: "Мир" },
          ].map((g) => (
            <button
              key={g.key}
              className={`chip ${geography === g.key ? "chip-on" : ""}`}
              onClick={() => onGeography(geography === g.key ? null : g.key)}
            >
              {g.label}
            </button>
          ))}
          <span className="chip mono !text-[11px] opacity-70">2019–2026</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2 stagger">
        {loading &&
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-[52px] mx-2 my-2" />
          ))}
        {!loading &&
          docs.map((d) => {
            const checked = selected.has(d.filename);
            return (
              <button
                key={d.filename}
                onClick={() => onToggle(d.filename)}
                className={`w-full text-left flex gap-2.5 px-2.5 py-2.5 rounded-lg transition-colors duration-200 group ${
                  checked ? "hover:bg-panel2" : "opacity-45 hover:opacity-80"
                }`}
              >
                <DocCheckbox checked={checked} />
                <span className="min-w-0">
                  <span className="mono block text-[11.5px] text-nickel truncate group-hover:text-copperbright transition-colors duration-200">
                    {d.filename}
                  </span>
                  <span className="block text-[11px] text-ink3 mt-0.5">
                    {d.source_type ?? "Документ"}
                    {d.year ? ` · ${d.year}` : ""}
                    {d.geography ? ` · ${d.geography === "RU" ? "РФ" : "Мир"}` : ""}
                    {` · ${d.experiments_count} эксп.`}
                  </span>
                </span>
              </button>
            );
          })}
        {!loading && docs.length === 0 && (
          <p className="text-[11.5px] text-ink3 px-3 py-4">
            Нет доступных документов для текущей роли.
          </p>
        )}
      </div>

      <div className="px-4 py-3 border-t border-line text-[11px] text-ink3 space-y-1.5">
        {isPartner ? (
          <p className="flex items-center gap-1.5 text-oxide">
            <Icon name="lock" size={11} />
            внутренние отчёты скрыты
          </p>
        ) : (
          <p className="flex items-center gap-1.5">
            <Icon name="lock" size={11} />3 документа под грифом «внутренний»
          </p>
        )}
        {stats && (
          <p className="mono">
            <TickNumber value={docs.length} /> документов ·{" "}
            <TickNumber value={stats.total_experiments} /> экспериментов
          </p>
        )}
      </div>
    </aside>
  );
}
