"use client";

import { useState } from "react";
import type {
  EnrichedGap,
  Gap,
  Statistics,
  UserSession,
} from "@/lib/types";
import { enrichGap } from "@/lib/api";
import Constellation from "./Constellation";
import Markdown from "./Markdown";
import { Icon, PanelLabel, TickNumber } from "./ui";

function gapLabel(g: Gap): string {
  return g.configuration.map((c) => c.value).join(" × ");
}

export default function StudioPanel({
  user,
  stats,
  gaps,
  gapsLoading,
  cfCount,
  lastAnswer,
}: {
  user: UserSession;
  stats: Statistics | null;
  gaps: Gap[];
  gapsLoading: boolean;
  cfCount: number;
  lastAnswer: string | null;
}) {
  const [hypotheses, setHypotheses] = useState<
    { key: string; label: string; state: "loading" | "done"; data?: EnrichedGap }[]
  >([]);
  const [copied, setCopied] = useState(false);
  const [expandedHyp, setExpandedHyp] = useState<string | null>(null);

  const canEnrich = user.role === "Administrator" || user.role === "Analyst";
  const isPartner = user.role === "External Partner";

  const onGapClick = async (g: Gap) => {
    const key = gapLabel(g);
    if (!canEnrich || hypotheses.some((h) => h.key === key)) return;
    setHypotheses((hs) => [{ key, label: key, state: "loading" }, ...hs]);
    const { data } = await enrichGap(user, g.configuration);
    setHypotheses((hs) =>
      hs.map((h) => (h.key === key ? { ...h, state: "done", data } : h)),
    );
  };

  const onCopy = async () => {
    if (!lastAnswer) return;
    try {
      await navigator.clipboard.writeText(lastAnswer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard недоступен — молча пропускаем */
    }
  };

  const filledCells = 8;

  return (
    <aside className="w-[292px] shrink-0 bg-panel border-l border-line flex flex-col overflow-hidden">
      <div className="px-4 pt-4 pb-2">
        <PanelLabel>Студия</PanelLabel>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-2.5 stagger">
        <div className="card overflow-hidden group" data-cursor="pointer">
          <div className="px-3.5 pt-3 pb-1 flex items-center justify-between">
            <p className="text-[12px] text-ink2 flex items-center gap-1.5">
              <Icon name="graph" size={13} className="text-nickel" />
              Граф знаний
            </p>
            {stats && (
              <span className="mono text-[10.5px] text-ink3">
                <TickNumber value={stats.total_experiments} /> рёбер
              </span>
            )}
          </div>
          <div className="h-[104px] transition-opacity duration-300 group-hover:opacity-100 opacity-80">
            <Constellation density={22} speed={0.22} lineDistance={64} />
          </div>
        </div>

        <div className="card px-3.5 py-3">
          <p className="text-[12px] text-ink2 flex items-center gap-1.5 mb-2.5">
            <Icon name="grid" size={13} className="text-sulfur" />
            Карта пробелов
            {isPartner && (
              <span className="text-[10px] text-oxide ml-auto flex items-center gap-1">
                <Icon name="lock" size={10} />
                нет доступа
              </span>
            )}
          </p>
          {gapsLoading && <div className="skeleton h-[64px]" />}
          {!gapsLoading && !isPartner && (
            <>
              <div className="grid grid-cols-6 gap-1.5">
                {Array.from({ length: filledCells }).map((_, i) => (
                  <span
                    key={`f${i}`}
                    className="h-[22px] rounded-[5px] bg-malachitetint border border-malachite/20"
                  />
                ))}
                {gaps.slice(0, 4).map((g, i) => (
                  <button
                    key={`g${i}`}
                    className="h-[22px] rounded-[5px] bg-sulfurtint border border-sulfur/40 text-sulfur text-[11px] mono leading-none transition-transform duration-150 hover:scale-110 hover:border-sulfur a-pulse"
                    style={{ animationDelay: `${i * 0.4}s` }}
                    title={gapLabel(g)}
                    onClick={() => onGapClick(g)}
                  >
                    ?
                  </button>
                ))}
              </div>
              <p className="text-[10.5px] text-ink3 mt-2">
                {gaps.length} пробелов ·{" "}
                {canEnrich
                  ? "клик по «?» — синтез гипотезы"
                  : "гипотезы доступны аналитикам"}
              </p>
            </>
          )}
        </div>

        <div className="card px-3.5 py-3 flex items-center justify-between">
          <p className="text-[12px] text-ink2 flex items-center gap-1.5">
            <Icon name="diff" size={13} className="text-nickel" />
            Контрфакты
          </p>
          <span className="mono text-[11px] text-ink3">
            {isPartner ? "—" : `${cfCount} пар`}
          </span>
        </div>

        <button
          className="card w-full px-3.5 py-3 flex items-center justify-between text-left transition-colors duration-200 hover:border-copperdim disabled:opacity-40"
          onClick={onCopy}
          disabled={!lastAnswer}
        >
          <p className="text-[12px] text-ink2 flex items-center gap-1.5">
            <Icon name="copy" size={13} className="text-nickel" />
            Экспорт литобзора
          </p>
          <span
            className={`mono text-[11px] transition-colors ${
              copied ? "text-malachite" : "text-ink3"
            }`}
          >
            {copied ? "скопировано ✓" : "Markdown"}
          </span>
        </button>

        {hypotheses.map((h) => (
          <div
            key={h.key}
            className="card !border-sulfur/35 !bg-sulfurtint px-3.5 py-3 a-slide-up"
          >
            <p className="text-[11px] text-sulfur flex items-center gap-1.5 mb-1.5">
              <Icon name="pin" size={11} />
              гипотеза · {h.label}
            </p>
            {h.state === "loading" ? (
              <div className="space-y-1.5">
                <div className="skeleton h-3 !bg-none !bg-card2" />
                <div className="skeleton h-3 w-4/5 !bg-none !bg-card2" />
              </div>
            ) : (
              <div
                className={
                  expandedHyp === h.key ? "" : "max-h-[110px] overflow-hidden relative"
                }
              >
                <Markdown
                  text={h.data?.hypothesis ?? ""}
                  animate={false}
                />
                {expandedHyp !== h.key && (
                  <button
                    className="absolute bottom-0 inset-x-0 h-9 text-[10.5px] text-sulfur text-center pt-4"
                    style={{
                      background:
                        "linear-gradient(transparent, var(--sulfur-tint) 70%)",
                    }}
                    onClick={() => setExpandedHyp(h.key)}
                  >
                    развернуть
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="px-4 py-2.5 border-t border-line mono text-[10px] text-ink3 flex items-center gap-2 select-none">
        <span className="w-1 h-1 rounded-full bg-copper a-pulse" />
        tensor completion · counterfactual retrieval
      </div>
    </aside>
  );
}
