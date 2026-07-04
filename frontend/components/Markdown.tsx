"use client";

import React from "react";
import type { Experiment } from "@/lib/types";

/**
 * Мини-рендерер markdown под ответы LLM-синтеза:
 * ### заголовки, **жирный**, `код`, маркированные и нумерованные списки.
 * Идентификаторы найденных экспериментов превращаются в кликабельные цитаты.
 */
export default function Markdown({
  text,
  experiments = [],
  onCite,
  animate = true,
}: {
  text: string;
  experiments?: Experiment[];
  onCite?: (exp: Experiment) => void;
  animate?: boolean;
}) {
  const byId = new Map(experiments.map((x) => [x.id, x]));
  const idPattern =
    experiments.length > 0
      ? new RegExp(
          `(${experiments
            .map((x) => x.id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
            .join("|")})`,
          "g",
        )
      : null;

  const inline = (chunk: string, keyBase: string): React.ReactNode[] => {
    const out: React.ReactNode[] = [];
    const boldSplit = chunk.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    boldSplit.forEach((part, i) => {
      const key = `${keyBase}-${i}`;
      if (part.startsWith("**") && part.endsWith("**")) {
        out.push(
          <strong key={key} className="font-medium text-ink">
            {citeSplit(part.slice(2, -2), key)}
          </strong>,
        );
      } else if (part.startsWith("`") && part.endsWith("`")) {
        out.push(
          <code
            key={key}
            className="mono text-[12px] text-nickel bg-nickeltint px-1 py-px rounded"
          >
            {part.slice(1, -1)}
          </code>,
        );
      } else if (part) {
        out.push(...citeSplit(part, key));
      }
    });
    return out;
  };

  const citeSplit = (s: string, keyBase: string): React.ReactNode[] => {
    if (!idPattern) return [s];
    const parts = s.split(idPattern);
    return parts.map((p, i) => {
      const exp = byId.get(p);
      if (exp) {
        return (
          <button
            key={`${keyBase}-c${i}`}
            className="cite"
            onClick={() => onCite?.(exp)}
            title={exp.name}
          >
            {exp.id}
          </button>
        );
      }
      return <React.Fragment key={`${keyBase}-t${i}`}>{p}</React.Fragment>;
    });
  };

  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let list: React.ReactNode[] = [];
  let listType: "ul" | "ol" | null = null;
  let bi = 0;

  const flushList = () => {
    if (list.length === 0) return;
    const cls = "space-y-1.5 my-2 pl-1";
    blocks.push(
      listType === "ol" ? (
        <ol key={`b${bi++}`} className={cls}>
          {list}
        </ol>
      ) : (
        <ul key={`b${bi++}`} className={cls}>
          {list}
        </ul>
      ),
    );
    list = [];
    listType = null;
  };

  lines.forEach((raw, li) => {
    const line = raw.trimEnd();
    const h = line.match(/^(#{2,4})\s+(.*)/);
    const bullet = line.match(/^[-*•]\s+(.*)/);
    const num = line.match(/^(\d+)[.)]\s+(.*)/);

    if (h) {
      flushList();
      blocks.push(
        <h3
          key={`b${bi++}`}
          className="serif text-[14px] font-medium text-copperbright mt-4 mb-1.5 first:mt-0"
        >
          {inline(h[2], `h${li}`)}
        </h3>,
      );
    } else if (bullet) {
      if (listType !== "ul") flushList();
      listType = "ul";
      list.push(
        <li key={`l${li}`} className="flex gap-2">
          <span className="text-copperdim mt-px select-none">—</span>
          <span>{inline(bullet[1], `b${li}`)}</span>
        </li>,
      );
    } else if (num) {
      if (listType !== "ol") flushList();
      listType = "ol";
      list.push(
        <li key={`l${li}`} className="flex gap-2">
          <span className="mono text-[11px] text-copperdim mt-0.5 select-none">
            {num[1]}.
          </span>
          <span>{inline(num[2], `n${li}`)}</span>
        </li>,
      );
    } else if (line.trim() === "") {
      flushList();
    } else {
      flushList();
      blocks.push(
        <p key={`b${bi++}`} className="my-1.5">
          {inline(line, `p${li}`)}
        </p>,
      );
    }
  });
  flushList();

  return (
    <div
      className={`serif text-[13.5px] leading-[1.7] text-ink/90 break-words ${
        animate ? "stagger" : ""
      }`}
    >
      {blocks}
    </div>
  );
}
