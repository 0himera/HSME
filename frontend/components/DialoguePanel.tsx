"use client";

import { useEffect, useRef, useState } from "react";
import type {
  AssistantPayload,
  ChatMessage,
  Experiment,
  UserSession,
} from "@/lib/types";
import { SUGGESTED_QUERIES } from "@/lib/mock";
import Markdown from "./Markdown";
import { Icon } from "./ui";

const THINKING_STEPS = [
  "разбор запроса на сущности",
  "связывание V_query = V_x ⊗ V_y",
  "поиск по гиперрёбрам корпуса",
  "оценка согласованности источников",
  "синтез научного ответа",
];

function ThinkingSteps() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const t = setInterval(
      () => setStep((s) => Math.min(s + 1, THINKING_STEPS.length - 1)),
      950,
    );
    return () => clearInterval(t);
  }, []);

  return (
    <div className="a-fade-up card px-4 py-3.5 max-w-[420px]">
      <div className="mono text-[11.5px] space-y-2">
        {THINKING_STEPS.map((s, i) => (
          <div
            key={s}
            className={`flex items-center gap-2 transition-opacity duration-300 ${
              i > step ? "opacity-25" : ""
            }`}
          >
            {i < step ? (
              <span className="text-malachite">
                <Icon name="check" size={11} />
              </span>
            ) : i === step ? (
              <span className="w-[11px] text-copperbright a-blink">▪</span>
            ) : (
              <span className="w-[11px] text-ink3">·</span>
            )}
            <span className={i === step ? "text-ink" : "text-ink3"}>{s}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ConsensusBar({ payload }: { payload: AssistantPayload }) {
  const { consensus } = payload;
  const pct = Math.round(consensus.ratio * 100);
  return (
    <div className="a-fade-up" style={{ animationDelay: "0.25s" }}>
      <div className="flex items-baseline justify-between text-[11px] mb-1.5">
        <span className="text-ink3">Согласованность источников</span>
        {consensus.contradict > 0 ? (
          <span className="text-oxide">
            {consensus.contradict} противоречат
          </span>
        ) : (
          <span className="text-malachite">консенсус</span>
        )}
      </div>
      <div className="h-[5px] rounded-full bg-card2 overflow-hidden flex">
        <span
          className="bg-malachite origin-left"
          style={{
            width: `${pct}%`,
            animation: "grow-x .8s cubic-bezier(.22,.61,.36,1) .3s both",
          }}
        />
        {consensus.contradict > 0 && (
          <span
            className="bg-oxide/70 origin-left"
            style={{
              width: `${100 - pct}%`,
              animation: "grow-x .8s cubic-bezier(.22,.61,.36,1) .5s both",
            }}
          />
        )}
      </div>
    </div>
  );
}

function CounterfactualCard({
  payload,
  onCite,
}: {
  payload: AssistantPayload;
  onCite: (exp: Experiment) => void;
}) {
  const cf = payload.counterfactual;
  if (!cf || cf.cf.effects.length === 0) return null;
  const eff = cf.cf.effects[0];
  return (
    <div
      className="card px-4 py-3 a-fade-up"
      style={{ animationDelay: "0.4s" }}
    >
      <p className="lbl mb-2 flex items-center gap-1.5">
        <Icon name="diff" size={12} />
        контрфактная пара · отличие в одном параметре
      </p>
      <div className="mono text-[11.5px] flex items-center gap-2.5 flex-wrap">
        <button className="cite !m-0" onClick={() => onCite(cf.base)}>
          {cf.base.id}
        </button>
        <span className="text-ink2">
          {cf.cf.difference.parameter}: {cf.cf.difference.from}
        </span>
        <span className="text-ink3">→</span>
        <button className="cite !m-0" onClick={() => onCite(cf.cf.experiment)}>
          {cf.cf.experiment.id}
        </button>
        <span className="text-ink2">{cf.cf.difference.to}</span>
        <span className="text-malachite bg-malachitetint border border-malachite/25 rounded px-1.5 py-0.5">
          Δ {eff.property}: {eff.from} → {eff.to}
        </span>
      </div>
    </div>
  );
}

function AssistantMessage({
  payload,
  onCite,
  onAsk,
}: {
  payload: AssistantPayload;
  onCite: (exp: Experiment) => void;
  onAsk: (q: string) => void;
}) {
  const experiments = payload.results.map((r) => r.experiment);
  return (
    <div className="space-y-4 max-w-[640px]">
      <div className="flex items-center gap-2 text-[11px] text-ink3 a-fade-in">
        <span className="w-1.5 h-1.5 rounded-full bg-copper a-pulse" />
        синтез по {payload.results.length} экспериментам
        {!payload.live && (
          <span className="chip !text-[10px] !py-0.5 !px-2 text-sulfur border-sulfur/30">
            демо-данные
          </span>
        )}
      </div>

      <Markdown
        text={payload.markdown}
        experiments={experiments}
        onCite={onCite}
      />

      <ConsensusBar payload={payload} />
      <CounterfactualCard payload={payload} onCite={onCite} />

      {payload.results.length > 0 && (
        <div
          className="a-fade-up flex items-center gap-1.5 flex-wrap"
          style={{ animationDelay: "0.55s" }}
        >
          <span className="text-[11px] text-ink3 mr-1">Источники:</span>
          {payload.results.map((r) => (
            <button
              key={r.experiment.id}
              className="cite !m-0"
              onClick={() => onCite(r.experiment)}
              title={`${r.experiment.name} · сходство ${(r.similarity * 100).toFixed(0)}%`}
            >
              {r.experiment.id}
              <span className="text-copperdim ml-1">
                {(r.similarity * 100).toFixed(0)}%
              </span>
            </button>
          ))}
        </div>
      )}

      <div
        className="a-fade-up flex gap-1.5 flex-wrap"
        style={{ animationDelay: "0.7s" }}
      >
        {["А что при 80 °C?", "Покажи противоречия", "Где пробелы рядом?"].map(
          (q) => (
            <button key={q} className="chip" onClick={() => onAsk(q)}>
              {q}
            </button>
          ),
        )}
      </div>
    </div>
  );
}

function EmptyState({ onAsk }: { onAsk: (q: string) => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 text-center select-none">
      <div className="stagger max-w-[520px]">
        <p className="mono text-[11px] text-copperdim tracking-[0.2em] mb-4">
          HYPERGRAPH RESEARCH MEMORY ENGINE
        </p>
        <h1 className="serif text-[26px] leading-snug font-medium mb-3">
          Спросите научную память
        </h1>
        <p className="text-[13px] text-ink2 mb-8 leading-relaxed">
          Каждый ответ собирается из гиперрёбер — целостных экспериментов
          с условиями, результатами и источниками. Не документы, а научные
          события.
        </p>
        <div className="flex flex-col gap-2 items-stretch">
          {SUGGESTED_QUERIES.map((q) => (
            <button
              key={q}
              className="btn-ghost text-left px-4 py-2.5 text-[12.5px] leading-snug"
              onClick={() => onAsk(q)}
            >
              <span className="text-copperdim mr-2">→</span>
              {q}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function DialoguePanel({
  messages,
  thinking,
  onAsk,
  onCite,
  user,
}: {
  messages: ChatMessage[];
  thinking: boolean;
  onAsk: (q: string) => void;
  onCite: (exp: Experiment) => void;
  user: UserSession;
}) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length, thinking]);

  const submit = () => {
    const q = draft.trim();
    if (!q || thinking) return;
    setDraft("");
    onAsk(q);
  };

  return (
    <main className="flex-1 min-w-0 flex flex-col bg-bg relative z-[1]">
      {messages.length === 0 && !thinking ? (
        <EmptyState onAsk={onAsk} />
      ) : (
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-6 py-6 space-y-6"
        >
          {messages.map((m) =>
            m.kind === "user" ? (
              <div key={m.id} className="flex justify-end a-fade-up">
                <div className="card !bg-card2 px-4 py-2.5 max-w-[70%] text-[13px]">
                  {m.text}
                </div>
              </div>
            ) : (
              m.payload && (
                <AssistantMessage
                  key={m.id}
                  payload={m.payload}
                  onCite={onCite}
                  onAsk={onAsk}
                />
              )
            ),
          )}
          {thinking && <ThinkingSteps />}
        </div>
      )}

      <div className="px-6 pb-5 pt-2 shrink-0">
        <div
          className="flex items-center gap-2 card !bg-panel2 px-2 py-2 focus-within:border-copperdim transition-colors duration-200"
          onClick={() => inputRef.current?.focus()}
        >
          <span className="pl-2 text-ink3">
            <Icon name="search" size={15} />
          </span>
          <input
            ref={inputRef}
            value={draft}
            onChange={(ev) => setDraft(ev.target.value)}
            onKeyDown={(ev) => ev.key === "Enter" && submit()}
            placeholder="Спросите про материалы, режимы, свойства…"
            className="flex-1 bg-transparent outline-none text-[13px] placeholder:text-ink3 py-1"
          />
          <button
            className="btn-copper w-9 h-9 flex items-center justify-center shrink-0"
            onClick={submit}
            aria-label="Отправить запрос"
            disabled={thinking}
          >
            <Icon name="arrow-up" size={16} />
          </button>
        </div>
        <p className="mono text-[10.5px] text-ink3 mt-2 px-1 flex items-center gap-2">
          <span
            className="w-1 h-1 rounded-full bg-malachite a-pulse"
            aria-hidden="true"
          />
          VSA · D=10 000 · биполярные гипервектора · роль: {user.role}
        </p>
      </div>
    </main>
  );
}
