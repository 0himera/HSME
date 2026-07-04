"use client";

import { useEffect } from "react";
import type { Entity, Experiment } from "@/lib/types";
import { Icon } from "./ui";
import { useLang } from "@/lib/i18n";

function EntityLine({ ent }: { ent: Entity }) {
  const isNumeric = ent.type === "Property";
  return (
    <p className="text-[12px] leading-relaxed">
      {isNumeric ? (
        <span className="mono text-nickel">{ent.value}</span>
      ) : (
        <span className="text-ink/90">{ent.value}</span>
      )}
      <span className="text-ink3 text-[10.5px] ml-1.5">{ent.type}</span>
    </p>
  );
}

function ChainColumn({
  title,
  delay,
  children,
}: {
  title: string;
  delay: number;
  children: React.ReactNode;
}) {
  return (
    <div
      className="a-fade-up min-w-0"
      style={{ animationDelay: `${delay}s` }}
    >
      <p className="lbl mb-2">{title}</p>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

export default function Passport({
  exp,
  onClose,
}: {
  exp: Experiment;
  onClose: () => void;
}) {
  const { t } = useLang();

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const confPct = Math.round(exp.confidence * 100);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-6 bg-black/65 a-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[720px] max-h-[85vh] overflow-y-auto bg-card border border-linestrong rounded-xl a-slide-up shadow-[0_24px_80px_rgba(0,0,0,.6)]"
        onClick={(ev) => ev.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`${t("passport_label")} ${exp.id}`}
      >
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-line">
          <div>
            <p className="mono text-[11px] text-copperdim tracking-[0.18em] mb-1">
              {t("passport_label")}
            </p>
            <h2 className="serif text-[18px] font-medium leading-snug pr-6">
              {exp.name}
            </h2>
          </div>
          <div className="flex items-center gap-2.5 shrink-0">
            <div className="text-right">
              <span
                className={`chip !text-[11px] ${
                  exp.confidence >= 0.8
                    ? "text-malachite border-malachite/35 !bg-malachitetint"
                    : "text-sulfur border-sulfur/35 !bg-sulfurtint"
                }`}
              >
                {t("passport_confidence")} {exp.confidence.toFixed(2)}
              </span>
              <div className="h-[3px] w-full rounded-full bg-card2 mt-1.5 overflow-hidden">
                <div
                  className={`h-full origin-left ${
                    exp.confidence >= 0.8 ? "bg-malachite" : "bg-sulfur"
                  }`}
                  style={{
                    width: `${confPct}%`,
                    animation: "grow-x .7s cubic-bezier(.22,.61,.36,1) .2s both",
                  }}
                />
              </div>
            </div>
            <button
              className="btn-ghost w-8 h-8 flex items-center justify-center"
              onClick={onClose}
              aria-label={t("passport_close")}
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-[1fr_20px_1fr_20px_1fr_20px_1fr] gap-x-4 px-6 py-5">
          <ChainColumn title={t("passport_in")} delay={0.05}>
            {exp.input_entities.map((ent, i) => (
              <EntityLine key={i} ent={ent} />
            ))}
            {exp.input_entities.length === 0 && (
              <p className="text-[11.5px] text-ink3">—</p>
            )}
          </ChainColumn>
          <div
            className="flex items-center justify-center text-copperdim a-fade-in"
            style={{ animationDelay: "0.18s" }}
          >
            →
          </div>
          <ChainColumn title={t("passport_process")} delay={0.22}>
            {exp.process_entities.map((ent, i) => (
              <EntityLine key={i} ent={ent} />
            ))}
            {exp.process_entities.length === 0 && (
              <p className="text-[11.5px] text-ink3">—</p>
            )}
          </ChainColumn>
          <div
            className="flex items-center justify-center text-copperdim a-fade-in"
            style={{ animationDelay: "0.35s" }}
          >
            →
          </div>
          <ChainColumn title={t("passport_out")} delay={0.4}>
            {exp.output_entities.map((ent, i) => (
              <EntityLine key={i} ent={ent} />
            ))}
            {exp.output_entities.length === 0 && (
              <p className="text-[11.5px] text-ink3">—</p>
            )}
          </ChainColumn>
          <div
            className="flex items-center justify-center text-copperdim a-fade-in"
            style={{ animationDelay: "0.52s" }}
          >
            →
          </div>
          <ChainColumn title={t("passport_evidence")} delay={0.58}>
            {exp.evidence.map((ev) => (
              <p key={ev} className="mono text-[11.5px] text-copperbright">
                <Icon name="file" size={11} className="inline mr-1 -mt-px" />
                {ev}
              </p>
            ))}
            {exp.evidence.length === 0 && (
              <p className="text-[11.5px] text-ink3">—</p>
            )}
          </ChainColumn>
        </div>

        {exp.relations.length > 0 && (
          <div className="px-6 pb-4 a-fade-up" style={{ animationDelay: "0.6s" }}>
            <p className="lbl mb-2">{t("passport_relations")}</p>
            <div className="flex flex-wrap gap-1.5">
              {exp.relations.slice(0, 6).map((r, i) => (
                <span key={i} className="chip mono !text-[10.5px]">
                  {r.source} <span className="text-copperdim">—{r.type}→</span>{" "}
                  {r.target}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="mono text-[11px] text-ink2 grid grid-cols-[auto_auto_1fr_auto_auto_auto] border-t border-linestrong select-none">
          {[
            "HSME",
            exp.id,
            exp.evidence[0] ?? "—",
            exp.source_type ?? t("passport_doc"),
            exp.year?.toString() ?? "—",
          ].map((cell, i) => (
            <span
              key={i}
              className="px-3.5 py-2 border-r border-line truncate"
            >
              {cell}
            </span>
          ))}
          <span
            className={`px-3.5 py-2 flex items-center gap-1.5 justify-end ${
              exp.is_sensitive ? "text-oxide" : "text-malachite"
            }`}
          >
            <Icon name="lock" size={11} />
            {exp.is_sensitive ? t("passport_internal") : t("passport_open")}
          </span>
        </div>
      </div>
    </div>
  );
}
