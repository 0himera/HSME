"use client";

import { useState, useEffect } from "react";
import type {
  EnrichedGap,
  Gap,
  Statistics,
  UserSession,
  GraphData,
  Experiment,
} from "@/lib/types";
import { enrichGap, fetchGraph } from "@/lib/api";
import Markdown from "./Markdown";
import MiniGraph from "./MiniGraph";
import { Icon, PanelLabel, TickNumber } from "./ui";
import { useLang } from "@/lib/i18n";

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
  lastResults,
  onViewGraph,
}: {
  user: UserSession;
  stats: Statistics | null;
  gaps: Gap[];
  gapsLoading: boolean;
  cfCount: number;
  lastAnswer: string | null;
  lastResults: Experiment[];
  onViewGraph: () => void;
}) {
  const { t, tPlural } = useLang();
  const [hypotheses, setHypotheses] = useState<
    { key: string; label: string; state: "loading" | "done"; data?: EnrichedGap }[]
  >([]);
  const [copied, setCopied] = useState(false);
  const [expandedHyp, setExpandedHyp] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);

  const canEnrich = user.role === "Administrator" || user.role === "Analyst";
  const isPartner = user.role === "External Partner";

  useEffect(() => {
    fetchGraph(user).then((res) => {
      if (res.data) setGraphData(res.data);
    }).catch(console.error);
  }, [user]);

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
      /* clipboard недоступен */
    }
  };

  const filledCells = 8;

  return (
    <aside className="w-[380px] shrink-0 bg-panel border-l border-line flex flex-col overflow-hidden">
      <div className="px-4 pt-4 pb-2">
        <PanelLabel>{t("studio_title")}</PanelLabel>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 pb-4 space-y-2.5 stagger">
        {/* Interactive Graph Preview */}
        <div
          className="card overflow-hidden group relative"
          data-cursor="pointer"
          onClick={lastResults.length > 0 ? onViewGraph : undefined}
        >
          <div className="px-3.5 pt-3 pb-1 flex items-center justify-between relative z-10">
            <p className="text-[12px] text-ink2 flex items-center gap-1.5">
              <Icon name="graph" size={13} className="text-nickel" />
              {t("studio_graph_title")} {lastResults.length > 0 ? t("studio_graph_context") : ""}
            </p>
            {stats && (
              <span className="mono text-[10.5px] text-ink3">
                <TickNumber value={stats.total_experiments} />{" "}
                {tPlural(stats.total_experiments, "experiments")}
              </span>
            )}
          </div>
          <div className="h-[140px] bg-bg relative">
            <MiniGraph lastResults={lastResults} graphData={graphData} />
            {lastResults.length > 0 && (
              <div className="absolute inset-0 bg-black/5 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none z-20">
                <span className="bg-copper text-bg text-[10px] mono px-2 py-1 rounded shadow-lg">
                  {t("studio_graph_expand")}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Gap map */}
        <div className="card px-3.5 py-3">
          <p className="text-[12px] text-ink2 flex items-center gap-1.5 mb-2.5">
            <Icon name="grid" size={13} className="text-sulfur" />
            {t("studio_gaps_title")}
            {isPartner && (
              <Icon name="lock" size={11} className="text-oxide ml-auto" />
            )}
          </p>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(28px,1fr))] gap-1">
            {gapsLoading ? (
              Array.from({ length: 48 }).map((_, i) => (
                <div
                  key={i}
                  className="aspect-square rounded-[2px] bg-line/30 a-pulse"
                  style={{ animationDelay: `${i * 0.02}s` }}
                />
              ))
            ) : gaps.length === 0 ? (
              <div className="col-span-full py-4 text-center text-[11px] text-ink3">
                {isPartner
                  ? t("studio_gaps_partner_locked")
                  : t("studio_gaps_empty")}
              </div>
            ) : (
              Array.from({ length: 48 }).map((_, i) => {
                const isFilled = i < filledCells;
                const gapIndex = i - filledCells;
                const g = gapIndex >= 0 ? gaps[gapIndex] : null;

                if (isFilled) {
                  return (
                    <div
                      key={`f-${i}`}
                      className="aspect-square rounded-[2px] bg-copper/20 border border-copper/30"
                      title={t("studio_gaps_researched")}
                    />
                  );
                }

                if (!g) {
                  return (
                    <div
                      key={`e-${i}`}
                      className="aspect-square rounded-[2px] bg-line/10"
                    />
                  );
                }

                return (
                  <button
                    key={`g-${gapIndex}`}
                    className="aspect-square rounded-[2px] bg-sulfur border border-sulfurbright hover:bg-sulfurbright transition-colors a-fade-in group relative"
                    style={{ animationDelay: `${gapIndex * 0.05}s` }}
                    onClick={() => onGapClick(g)}
                    aria-label={gapLabel(g)}
                  >
                    <div className="absolute opacity-0 group-hover:opacity-100 bottom-full left-1/2 -translate-x-1/2 mb-1 pointer-events-none whitespace-nowrap bg-card border border-line text-ink text-[10px] px-2 py-1 rounded shadow-lg z-10 transition-opacity">
                      {gapLabel(g)}
                      {canEnrich && (
                        <span className="block text-copper mt-0.5">
                          {t("studio_gaps_gen_hint")}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Hypotheses */}
        {hypotheses.length > 0 && (
          <div className="space-y-2">
            <PanelLabel>{t("studio_hyp_title")}</PanelLabel>
            {hypotheses.map((h) => (
              <div key={h.key} className="card p-3 a-fade-up">
                <p className="text-[11px] font-mono text-ink2 mb-1 break-words">{h.label}</p>
                {h.state === "loading" ? (
                  <div className="flex items-center gap-2 text-[11px] text-ink3 mt-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-copper a-pulse" />
                    {t("studio_hyp_loading")}
                  </div>
                ) : (
                  <div>
                    {h.data ? (
                      <div className="mt-2 text-[11.5px] leading-relaxed text-ink2">
                        <div
                          className={`relative overflow-hidden transition-all duration-300 ${
                            expandedHyp === h.key ? "max-h-[3000px]" : "max-h-24"
                          }`}
                        >
                          <Markdown text={h.data.hypothesis} />
                          {expandedHyp !== h.key && (
                            <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-card to-transparent" />
                          )}
                        </div>
                        <button
                          onClick={() =>
                            setExpandedHyp((prev) =>
                              prev === h.key ? null : h.key,
                            )
                          }
                          className="mt-1 text-copper hover:text-copperbright text-[10px] uppercase tracking-wider"
                        >
                          {expandedHyp === h.key ? t("studio_hyp_collapse") : t("studio_hyp_expand")}
                        </button>
                      </div>
                    ) : (
                      <p className="text-[11px] text-oxide mt-1">
                        {t("studio_hyp_failed")}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="px-4 py-3 border-t border-line text-[11px] text-ink3 space-y-1.5">
        <p className="flex justify-between">
          <span>{t("studio_cf_label")}</span>
          <span className="mono text-ink">{cfCount}</span>
        </p>
        <p className="flex justify-between items-center">
          <span>{t("studio_report_label")}</span>
          {lastAnswer ? (
            <button
              onClick={onCopy}
              className="btn-ghost !py-0.5 !px-2 flex items-center gap-1"
            >
              <Icon name={copied ? "check" : "copy"} size={11} />
              {copied ? t("studio_copied") : t("studio_copy")}
            </button>
          ) : (
            <span className="text-ink3">{t("studio_report_waiting")}</span>
          )}
        </p>
      </div>
    </aside>
  );
}
