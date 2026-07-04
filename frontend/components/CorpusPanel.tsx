"use client";

import { useEffect, useMemo, useState } from "react";
import type { Experiment, Statistics, UserSession, IngestStatus } from "@/lib/types";
import { Icon, PanelLabel, TickNumber } from "./ui";
import { fetchIngestStatus, startIngestCorpus } from "@/lib/api";
import { useLang } from "@/lib/i18n";

const PAGE_SIZE = 15;

// ── Entity chip colours via CSS variables (design-system aligned) ─────────────
function EntityChip({ e, type }: { e: { value: string; type: string }; type: string }) {
  const colors =
    type === "inputs"
      ? "bg-nickeltint border-nickel/30 text-nickel"
      : type === "process"
      ? "bg-coppertint border-copper/30 text-copper"
      : "bg-malachitetint border-malachite/30 text-malachite";
  return (
    <span className={`px-1.5 py-[1px] text-[10px] rounded border ${colors}`}>
      <span className="font-semibold opacity-70 mr-1">{e.type}:</span>
      {e.value}
    </span>
  );
}

function EntityChips({
  entities,
  type,
}: {
  entities: { value: string; type: string }[];
  type: string;
}) {
  if (!entities.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-1.5">
      {entities.map((e, i) => (
        <EntityChip key={i} e={e} type={type} />
      ))}
    </div>
  );
}

// ── Filter chip ────────────────────────────────────────────────────────────────
function FilterChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`chip text-[10.5px] !py-0.5 !px-2 ${active ? "chip-on" : ""}`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

export default function CorpusPanel({
  experiments,
  user,
  stats,
  loading,
  onCite,
  collapsed,
  width,
  isResizing,
}: {
  experiments: Experiment[];
  user: UserSession;
  stats: Statistics | null;
  loading: boolean;
  onCite: (exp: Experiment) => void;
  collapsed: boolean;
  width?: number;
  isResizing?: boolean;
}) {
  const { t, tPlural } = useLang();
  const isPartner = user.role === "External Partner";
  const [ingestStatus, setIngestStatus] = useState<IngestStatus | null>(null);
  const [ingesting, setIngesting] = useState(false);

  // ── Search & Filter state ────────────────────────────────────────────────────
  const [query, setQuery] = useState("");
  const [filterGeo, setFilterGeo] = useState<string | null>(null);
  const [filterYear, setFilterYear] = useState<number | null>(null);
  const [filterPublic, setFilterPublic] = useState(false);
  const [page, setPage] = useState(1);

  // Reset page when filters change
  useEffect(() => { setPage(1); }, [query, filterGeo, filterYear, filterPublic]);

  // ── Derived option lists ──────────────────────────────────────────────────────
  const geoOptions = useMemo(() => {
    const s = new Set<string>();
    experiments.forEach((e) => e.geography && s.add(e.geography));
    return [...s].sort();
  }, [experiments]);

  const yearOptions = useMemo(() => {
    const s = new Set<number>();
    experiments.forEach((e) => e.year && s.add(e.year));
    return [...s].sort((a, b) => b - a);
  }, [experiments]);

  // ── Filtering ─────────────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    return experiments.filter((exp) => {
      if (filterPublic && exp.is_sensitive) return false;
      if (filterGeo && exp.geography !== filterGeo) return false;
      if (filterYear && exp.year !== filterYear) return false;
      if (!q) return true;
      if (exp.id.toLowerCase().includes(q)) return true;
      if (exp.name.toLowerCase().includes(q)) return true;
      const allEntities = [
        ...exp.input_entities,
        ...exp.process_entities,
        ...exp.output_entities,
      ];
      return allEntities.some((ent) => ent.value.toLowerCase().includes(q));
    });
  }, [experiments, query, filterGeo, filterYear, filterPublic]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  // ── Ingest status polling ─────────────────────────────────────────────────────
  useEffect(() => {
    let active = true;
    let timerId: ReturnType<typeof setTimeout> | null = null;

    async function checkStatus() {
      const res = await fetchIngestStatus(user);
      if (active && res.data) {
        setIngestStatus(res.data);
        if (res.data.status === "running") {
          timerId = setTimeout(checkStatus, 3000);
        }
      }
    }
    checkStatus();

    return () => {
      active = false;
      if (timerId) clearTimeout(timerId);
    };
  }, [user]);

  const handleIngest = async () => {
    if (user.role !== "Administrator") return;
    setIngesting(true);
    await startIngestCorpus(user);
    const res = await fetchIngestStatus(user);
    if (res.data) setIngestStatus(res.data);
    setIngesting(false);
  };

  const ingestLabel =
    ingestStatus?.status === "running"
      ? `${t("corpus_ingest_running")} (${ingestStatus.files_indexed} ф.)`
      : ingestStatus?.status === "completed"
      ? t("corpus_ingest_done")
      : ingestStatus?.status === "failed"
      ? `${t("corpus_ingest_failed")} ${ingestStatus.error || "?"}`
      : t("corpus_ingest_ready");

  return (
    <aside 
      className={`shrink-0 bg-panel border-r border-line flex flex-col overflow-hidden ${
        collapsed ? "w-0 opacity-0 border-r-0" : ""
      } ${!isResizing ? "transition-all duration-300" : ""}`}
      style={!collapsed ? { width: `${width || 23.75}rem` } : undefined}
    >
      {/* Header */}
      <div className="px-4 pt-4 pb-2 border-b border-line">
        <div className="flex items-center justify-between mb-2.5">
          <PanelLabel>{t("corpus_title")}</PanelLabel>
          {stats && (
            <span className="mono text-[10.5px] text-ink3">
              <TickNumber value={stats.total_experiments} />{" "}
              {tPlural(stats.total_experiments, "experiments")}
            </span>
          )}
        </div>

        {/* Search input */}
        <div className="flex items-center gap-1.5 bg-bg border border-line rounded-lg px-2.5 py-1.5 mb-2 focus-within:border-copperdim transition-colors">
          <Icon name="search" size={12} className="text-ink3 shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("corpus_search_placeholder")}
            className="flex-1 bg-transparent outline-none text-[12px] placeholder:text-ink3 text-ink"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="text-ink3 hover:text-ink transition-colors"
              aria-label="Clear search"
            >
              <Icon name="x" size={11} />
            </button>
          )}
        </div>

        {/* Filter chips row */}
        <div className="flex flex-wrap gap-1 mb-1">
          <FilterChip
            active={filterPublic}
            label={t("corpus_filter_sensitive")}
            onClick={() => setFilterPublic((v) => !v)}
          />
          {geoOptions.length > 0 && (
            <div className="relative">
              <select
                value={filterGeo ?? ""}
                onChange={(e) => setFilterGeo(e.target.value || null)}
                className={`chip text-[10.5px] !py-0.5 !px-2 appearance-none bg-card border-line cursor-pointer pr-5 ${filterGeo ? "chip-on" : ""}`}
                style={{ backgroundImage: "none" }}
              >
                <option value="">{t("corpus_filter_geo")}</option>
                {geoOptions.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </div>
          )}
          {yearOptions.length > 0 && (
            <div className="relative">
              <select
                value={filterYear ?? ""}
                onChange={(e) => setFilterYear(e.target.value ? Number(e.target.value) : null)}
                className={`chip text-[10.5px] !py-0.5 !px-2 appearance-none bg-card border-line cursor-pointer ${filterYear ? "chip-on" : ""}`}
                style={{ backgroundImage: "none" }}
              >
                <option value="">{t("corpus_filter_year")}</option>
                {yearOptions.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </div>
          )}
          {(filterGeo || filterYear || filterPublic) && (
            <button
              className="chip text-[10.5px] !py-0.5 !px-2 text-oxide border-oxide/30"
              onClick={() => { setFilterGeo(null); setFilterYear(null); setFilterPublic(false); }}
            >
              <Icon name="x" size={10} /> {t("corpus_filter_all")}
            </button>
          )}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-3 space-y-2">
        {loading && (
          <div className="px-3 text-[11.5px] text-ink3 mt-2 flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-copper a-pulse" />
            {t("corpus_loading")}
          </div>
        )}

        {!loading && pageItems.length === 0 && (
          <p className="text-[11.5px] text-ink3 px-3 py-4">
            {experiments.length === 0 ? t("corpus_empty") : t("corpus_no_results")}
          </p>
        )}

        {!loading &&
          pageItems.map((exp, i) => (
            <div
              key={exp.id}
              className="bg-bg border border-line rounded px-3 py-2.5 a-fade-up shadow-sm hover:border-copper/50 transition-colors cursor-pointer"
              style={{ animationDelay: `${i * 0.04}s` }}
              onClick={() => onCite(exp)}
            >
              <div className="flex items-start justify-between mb-2">
                <div className="min-w-0 flex-1">
                  <h4 className="mono text-[11px] font-bold text-ink mb-0.5 truncate">
                    {exp.id}
                  </h4>
                  <p className="text-[11px] text-ink2 leading-snug line-clamp-2">
                    {exp.name}
                  </p>
                </div>
                <div className="flex items-center gap-1.5 shrink-0 ml-2">
                  <span className="mono text-[9px] px-1.5 py-0.5 bg-panel border border-line rounded text-ink3 whitespace-nowrap">
                    {exp.geography} {exp.year}
                  </span>
                  {exp.is_sensitive && (
                    <span className="mono text-[9px] px-1.5 py-0.5 bg-oxidetint text-oxide border border-oxide/30 rounded">
                      {t("corpus_private")}
                    </span>
                  )}
                </div>
              </div>
              {exp.input_entities.length > 0 && (
                <EntityChips entities={exp.input_entities} type="inputs" />
              )}
              {exp.process_entities.length > 0 && (
                <EntityChips entities={exp.process_entities} type="process" />
              )}
              {exp.output_entities.length > 0 && (
                <EntityChips entities={exp.output_entities} type="outputs" />
              )}
            </div>
          ))}
      </div>

      {/* Pagination */}
      {!loading && filtered.length > PAGE_SIZE && (
        <div className="px-4 py-2 border-t border-line flex items-center justify-between text-[11px] text-ink3">
          <button
            className="btn-ghost !py-1 !px-2.5 text-[11px] disabled:opacity-30"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage === 1}
          >
            {t("corpus_prev")}
          </button>
          <span className="mono">
            {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)}{" "}
            {t("corpus_page_of")} {filtered.length}
          </span>
          <button
            className="btn-ghost !py-1 !px-2.5 text-[11px] disabled:opacity-30"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage === totalPages}
          >
            {t("corpus_next")}
          </button>
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-3 border-t border-line text-[11px] text-ink3 space-y-1.5">
        {isPartner ? (
          <p className="flex items-center gap-1.5 text-oxide">
            <Icon name="lock" size={11} />
            {t("corpus_restricted")}
          </p>
        ) : (
          <p className="flex items-center gap-1.5">
            <Icon name="lock" size={11} />
            {t("corpus_full_access")}
          </p>
        )}
      </div>

      {/* Admin ingest */}
      {user.role === "Administrator" && (
        <div className="px-4 py-3 border-t border-line text-[11px] space-y-2 bg-card2/35">
          <p className="mono text-ink2">
            {t("corpus_ingest_title")} {ingestLabel}
          </p>
          <button
            onClick={handleIngest}
            disabled={ingestStatus?.status === "running" || ingesting}
            className="btn-copper w-full py-1.5 text-[11px] font-medium transition-transform duration-150 active:scale-95"
          >
            {ingestStatus?.status === "running"
              ? t("corpus_ingest_btn_running")
              : t("corpus_ingest_btn")}
          </button>
        </div>
      )}
    </aside>
  );
}
