"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ChatMessage,
  Consensus,
  Counterfactual,
  DocInfo,
  Experiment,
  Gap,
  SearchResult,
  Statistics,
  UserSession,
} from "@/lib/types";
import {
  fetchCounterfactuals,
  fetchDocuments,
  fetchGaps,
  fetchStatistics,
  searchQuery,
} from "@/lib/api";
import Header from "./Header";
import CorpusPanel from "./CorpusPanel";
import DialoguePanel from "./DialoguePanel";
import StudioPanel from "./StudioPanel";
import Passport from "./Passport";
import Constellation from "./Constellation";

function calcConsensus(results: SearchResult[]): Consensus {
  const top = results.slice(0, 6);
  const byProp = new Map<string, Set<string>>();
  for (const r of top) {
    for (const out of r.experiment.output_entities) {
      const [name, ...rest] = out.value.split(":");
      if (rest.length === 0) continue;
      const key = name.trim().toLowerCase();
      if (!byProp.has(key)) byProp.set(key, new Set());
      byProp.get(key)!.add(rest.join(":").trim());
    }
  }
  let contradict = 0;
  for (const values of byProp.values()) {
    if (values.size > 1) contradict += values.size - 1;
  }
  contradict = Math.min(contradict, Math.max(0, top.length - 1));
  const avgConf =
    top.length > 0
      ? top.reduce((s, r) => s + r.experiment.confidence, 0) / top.length
      : 0;
  const ratio = Math.max(
    0.15,
    Math.min(1, avgConf * (1 - contradict / Math.max(top.length, 1)) + 0.08),
  );
  return {
    ratio,
    agree: Math.max(top.length - contradict, 0),
    contradict,
    total: top.length,
  };
}

function localSummary(results: SearchResult[], restricted: boolean): string {
  if (results.length === 0) {
    return "### Вывод\nПо выбранному корпусу релевантных экспериментов не найдено. Попробуйте переформулировать запрос или снять фильтры.";
  }
  const lines = [
    "### Найденные научные события",
    ...results
      .slice(0, 5)
      .map(
        (r) =>
          `- ${r.experiment.id}: ${r.experiment.name} — ${r.experiment.output_entities
            .map((o) => o.value)
            .join(", ")} (достоверность ${r.experiment.confidence.toFixed(2)})`,
      ),
  ];
  if (restricted) {
    lines.push(
      "",
      "Авто-синтез ответа (LLM Reasoner) доступен ролям «Аналитик» и «Администратор».",
    );
  }
  return lines.join("\n");
}

function Workspace({
  user,
  onUserChange,
}: {
  user: UserSession;
  onUserChange: (u: UserSession) => void;
}) {
  const [docs, setDocs] = useState<DocInfo[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [geography, setGeography] = useState<string | null>(null);
  const [stats, setStats] = useState<Statistics | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [gapsLoading, setGapsLoading] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [thinking, setThinking] = useState(false);
  const [passport, setPassport] = useState<Experiment | null>(null);
  const [live, setLive] = useState(false);
  const [cfCount, setCfCount] = useState(0);
  const msgId = useRef(1);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [d, s, g] = await Promise.all([
        fetchDocuments(user),
        fetchStatistics(user),
        fetchGaps(user, ["Material", "Process"]),
      ]);
      if (cancelled) return;
      setDocs(d.data);
      setSelectedDocs(new Set(d.data.map((x) => x.filename)));
      setStats(s.data);
      setGaps(g.data);
      setLive(d.live || s.live);
      setDocsLoading(false);
      setGapsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ask = useCallback(
    async (q: string) => {
      setMessages((ms) => [
        ...ms,
        { id: msgId.current++, kind: "user", text: q },
      ]);
      setThinking(true);

      const { data, live: searchLive } = await searchQuery(user, q, {
        geography,
      });
      const allResults = data.results ?? [];
      const results = allResults.filter(
        (r) =>
          r.experiment.evidence.length === 0 ||
          r.experiment.evidence.some((ev) => selectedDocs.has(ev)),
      );
      const shown = results.length > 0 ? results : allResults;

      const restricted =
        user.role === "Researcher" || user.role === "External Partner";
      const rag = data.rag_explanation;
      const markdown =
        rag && !rag.startsWith("Ваша роль")
          ? rag
          : localSummary(shown, restricted);

      let counterfactual:
        | { base: Experiment; cf: Counterfactual }
        | undefined;
      if (shown.length > 0 && !restricted) {
        const cf = await fetchCounterfactuals(user, shown[0].experiment.id);
        if (cf.data.length > 0) {
          counterfactual = { base: shown[0].experiment, cf: cf.data[0] };
          setCfCount((c) => Math.max(c, cf.data.length * 7));
        }
      }

      setMessages((ms) => [
        ...ms,
        {
          id: msgId.current++,
          kind: "assistant",
          payload: {
            markdown,
            results: shown,
            consensus: calcConsensus(shown),
            counterfactual,
            live: searchLive,
          },
        },
      ]);
      setThinking(false);
    },
    [user, geography, selectedDocs],
  );

  const toggleDoc = useCallback((filename: string) => {
    setSelectedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(filename)) next.delete(filename);
      else next.add(filename);
      return next;
    });
  }, []);

  const lastAnswer =
    [...messages].reverse().find((m) => m.kind === "assistant")?.payload
      ?.markdown ?? null;

  return (
    <div className="h-dvh flex flex-col relative">
      <div className="fixed inset-0 opacity-[0.05] pointer-events-none z-0">
        <Constellation density={34} speed={0.08} lineDistance={110} />
      </div>

      <Header user={user} onUserChange={onUserChange} stats={stats} live={live} />

      <div className="flex-1 flex min-h-0 relative z-[1]">
        <CorpusPanel
          docs={docs}
          selected={selectedDocs}
          onToggle={toggleDoc}
          geography={geography}
          onGeography={setGeography}
          user={user}
          stats={stats}
          loading={docsLoading}
        />
        <DialoguePanel
          messages={messages}
          thinking={thinking}
          onAsk={ask}
          onCite={setPassport}
          user={user}
        />
        <StudioPanel
          user={user}
          stats={stats}
          gaps={gaps}
          gapsLoading={gapsLoading}
          cfCount={cfCount}
          lastAnswer={lastAnswer}
        />
      </div>

      {passport && (
        <Passport exp={passport} onClose={() => setPassport(null)} />
      )}
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<UserSession>({
    name: "А. Петрова",
    role: "Analyst",
  });

  /* key-перемонтирование: при смене роли рабочая область полностью
     сбрасывается — диалог и артефакты не «протекают» между ролями */
  return (
    <Workspace
      key={`${user.role}:${user.name}`}
      user={user}
      onUserChange={setUser}
    />
  );
}
