"use client";

import { useEffect, useRef, useState } from "react";
import { fetchGraph, fetchExperiments } from "@/lib/api";
import type { GraphData, Experiment, UserSession } from "@/lib/types";
import { Icon } from "./ui";

export default function GraphPanel({
  user,
  onClose,
  onCite,
  lastResults = [],
}: {
  user: UserSession;
  onClose: () => void;
  onCite: (exp: Experiment) => void;
  lastResults?: Experiment[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let network: any = null;
    let resizeObserver: any = null;

    async function init() {
      try {
        setLoading(true);
        const [graphRes, expRes] = await Promise.all([
          fetchGraph(user),
          fetchExperiments(user),
        ]);

        if (!graphRes.data) {
          throw new Error("Failed to load graph data");
        }

        const graphData = graphRes.data;
        const experiments = expRes.data || [];

        const { Network } = await import("vis-network");

        const colors = {
          Experiment: { background: "#c98a52", border: "#e2a76e", highlight: "#df9a57" },
          Material: { background: "#5fa98c", border: "#7fc9ac", highlight: "#6fcbb4" },
          Process: { background: "#8fa9b8", border: "#abc5d4", highlight: "#9ec2d9" },
          Property: { background: "#d8a848", border: "#f6c666", highlight: "#ffd175" },
          Equipment: { background: "#9c8eb9", border: "#bcafdb", highlight: "#c4b5e7" },
          Facility: { background: "#b3a092", border: "#d3c0b2", highlight: "#dfcfc1" },
          default: { background: "#746a58", border: "#a89d87", highlight: "#e9e1d0" },
        };

        const nodeMapper = (n: any) => {
          const groupColor = colors[n.group as keyof typeof colors] || colors.default;
          const isExp = n.group === "Experiment";

          return {
            id: n.id,
            label: n.label,
            title: n.title,
            shape: isExp ? "dot" : n.group === "Property" ? "box" : "dot",
            size: isExp ? 24 : 14,
            color: {
              background: groupColor.background,
              border: groupColor.border,
              highlight: {
                background: groupColor.highlight,
                border: "#e9e1d0",
              },
            },
            font: {
              color: n.group === "Property" ? "#14110E" : "#e9e1d0",
              size: isExp ? 12 : 10,
              face: "IBM Plex Mono, monospace",
            },
            borderWidth: 1.5,
          };
        };

        const edgeMapper = (e: any) => ({
          from: e.from,
          to: e.to,
          label: e.label,
          arrows: e.arrows || undefined,
          color: {
            color: "#544a3d",
            highlight: "#c98a52",
            hover: "#df9a57",
          },
          font: {
            color: "#e9e1d0",
            size: 9,
            face: "IBM Plex Mono, monospace",
            align: "horizontal",
            strokeWidth: 4,
            strokeColor: "#14110E",
          },
          width: 1.2,
        });

        let styledNodes: any[] = [];
        let styledEdges: any[] = [];

        if (lastResults && lastResults.length > 0) {
          const expIds = new Set(lastResults.map((r) => `exp_${r.id}`));
          const entityKeys = new Set<string>();

          for (const exp of lastResults) {
            for (const ent of exp.input_entities) {
              entityKeys.add(ent.type + ":" + ent.value);
            }
            for (const ent of exp.process_entities) {
              entityKeys.add(ent.type + ":" + ent.value);
            }
            for (const ent of exp.output_entities) {
              entityKeys.add(ent.type + ":" + ent.value);
            }
          }

          const filteredNodes = graphData.nodes.filter(
            (n) => expIds.has(n.id) || entityKeys.has(n.id)
          );
          const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));

          const filteredEdges = graphData.edges.filter(
            (e) => filteredNodeIds.has(e.from) && filteredNodeIds.has(e.to)
          );

          styledNodes = filteredNodes.map(nodeMapper);
          styledEdges = filteredEdges.map(edgeMapper);
        } else {
          // Do not render anything if no search context
        }

        if (!containerRef.current) return;

        const options = {
          autoResize: false,
          nodes: {
            scaling: {
              min: 10,
              max: 30,
            },
          },
          edges: {
            smooth: {
              enabled: true,
              type: "continuous",
              forceDirection: "none",
              roundness: 0.5,
            },
          },
          physics: {
            forceAtlas2Based: {
              gravitationalConstant: -180,
              centralGravity: 0.005,
              springLength: 200,
              springConstant: 0.04,
            },
            maxVelocity: 50,
            solver: "forceAtlas2Based",
            timestep: 0.35,
            stabilization: {
              enabled: true,
              iterations: 250,
              updateInterval: 25,
            },
          },
          interaction: {
            hover: true,
            tooltipDelay: 200,
          },
        };

        const data = {
          nodes: styledNodes,
          edges: styledEdges,
        };

        network = new Network(containerRef.current, data, options);

        let resizeTimeout: any;
        resizeObserver = new ResizeObserver((entries) => {
          if (!network) return;
          const entry = entries[0];
          if (entry) {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
              network.setSize(`${entry.contentRect.width}px`, `${entry.contentRect.height}px`);
            }, 100);
          }
        });
        resizeObserver.observe(containerRef.current);

        network.on("click", (params: any) => {
          if (params.nodes && params.nodes.length > 0) {
            const nodeId = params.nodes[0] as string;
            if (nodeId.startsWith("exp_")) {
              const expId = nodeId.substring(4);
              const found = experiments.find((x) => x.id === expId);
              if (found) {
                onCite(found);
              }
            }
          }
        });

        setLoading(false);
      } catch (err: any) {
        console.error("Graph initialization error:", err);
        setError(err.message || "Failed to initialize graph view");
        setLoading(false);
      }
    }

    init();

    return () => {
      if (network) {
        network.destroy();
      }
      if (typeof resizeObserver !== 'undefined') resizeObserver.disconnect();
    };
  }, [user, onCite, lastResults]);

  return (
    <div className="flex-1 flex flex-col bg-bg relative z-[1] select-none h-full min-h-0">
      {/* Header */}
      <div className="px-4 md:px-6 py-2 md:py-4 border-b border-line flex items-center justify-between shrink-0">
        <div>
          <h2 className="serif text-[14px] md:text-[18px] leading-snug font-medium flex items-center gap-1.5 md:gap-2">
            <Icon name="graph" size={14} className="text-nickel hidden md:block" />
            Интерактивный граф знаний R&D
          </h2>
          <p className="mono text-[10.5px] text-ink3 mt-0.5 hidden md:block">
            Двудольный гиперграф: оранжевые вершины — эксперименты, цветные — параметры/процессы/материалы
          </p>
        </div>

        {/* Close */}
        <div className="flex items-center gap-2 md:gap-3">
          {lastResults && lastResults.length > 0 && (
            <div className="hidden md:block px-3 py-1.5 mono text-[11px] font-medium bg-copper text-bg rounded">
              По запросу ({lastResults.length} эксп.)
            </div>
          )}

          <button
            onClick={onClose}
            className="btn-ghost !px-2 md:!px-3 !py-1 md:!py-1.5 flex items-center gap-1 md:gap-1.5 text-[10px] md:text-[11px]"
          >
            <Icon name="arrow-left" size={12} />
            <span className="hidden md:inline">Назад к диалогу</span>
            <span className="md:hidden">Назад</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 relative bg-panel min-h-0">
        {loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-bg/50 z-10 backdrop-blur-[2px]">
            <span className="w-6 h-6 text-copperbright a-blink mb-2">▪</span>
            <p className="mono text-[11px] text-copperdim tracking-widest uppercase">
              Стабилизация топологии графа...
            </p>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-bg/50 z-10">
            <p className="text-[13px] text-oxide mb-4">{error}</p>
            <button
              onClick={onClose}
              className="btn-copper text-[12px] px-4 py-2"
            >
              Вернуться
            </button>
          </div>
        )}

        {lastResults.length === 0 && !loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-bg/50 z-10">
            <p className="text-[13px] text-oxide mb-4">
              Сделайте поисковой запрос, чтобы построить граф по релевантным экспериментам.
            </p>
          </div>
        )}

        <div ref={containerRef} className="w-full h-full min-h-[500px]" />

        {/* Legend Overlay */}
        <div className="absolute bottom-4 left-4 bg-card/90 border border-line rounded px-4 py-3 space-y-2 max-w-[260px] pointer-events-none backdrop-blur">
          <p className="mono text-[9.5px] text-ink3 uppercase tracking-wider mb-2">Легенда вершин</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[10.5px] text-ink2">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#c98a52] shrink-0" />
              <span>Эксперимент</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#5fa98c] shrink-0" />
              <span>Материал</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#8fa9b8] shrink-0" />
              <span>Процесс</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded bg-[#d8a848] shrink-0" />
              <span>Параметр</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#9c8eb9] shrink-0" />
              <span>Оборудование</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-[#b3a092] shrink-0" />
              <span>Объект</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
