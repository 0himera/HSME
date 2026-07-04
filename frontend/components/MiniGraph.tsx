"use client";

import { useEffect, useRef } from "react";
import type { GraphData, Experiment } from "@/lib/types";

export default function MiniGraph({
  lastResults,
  graphData,
}: {
  lastResults: Experiment[];
  graphData: GraphData | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let network: any = null;

    async function init() {
      if (!graphData || !containerRef.current) return;
      const { Network } = await import("vis-network");

      const colors = {
        Experiment: { background: "#c98a52", border: "#e2a76e", highlight: "#df9a57" },
        default: { background: "#746a58", border: "#a89d87", highlight: "#e9e1d0" },
      };

      const nodeMapper = (n: any) => {
        const isExp = n.group === "Experiment";
        const groupColor = isExp ? colors.Experiment : colors.default;

        return {
          id: n.id,
          shape: "dot",
          size: isExp ? 20 : 12,
          color: {
            background: groupColor.background,
            border: groupColor.border,
          },
          borderWidth: 1.5,
        };
      };

      const edgeMapper = (e: any) => ({
        from: e.from,
        to: e.to,
        color: { color: "#544a3d" },
        width: 1,
      });

      let styledNodes: any[] = [];
      let styledEdges: any[] = [];

      if (lastResults.length > 0) {
        const expIds = new Set(lastResults.map((r) => `exp_${r.id}`));
        const entityKeys = new Set<string>();

        for (const exp of lastResults) {
          for (const ent of exp.input_entities) entityKeys.add(ent.type + ":" + ent.value);
          for (const ent of exp.process_entities) entityKeys.add(ent.type + ":" + ent.value);
          for (const ent of exp.output_entities) entityKeys.add(ent.type + ":" + ent.value);
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
        styledNodes = graphData.nodes.map(nodeMapper);
        styledEdges = graphData.edges.map(edgeMapper);
      }

      const options = {
        nodes: { scaling: { min: 10, max: 30 } },
        edges: { smooth: { enabled: true, type: "continuous", roundness: 0.5 } },
        physics: {
          forceAtlas2Based: {
            gravitationalConstant: -100,
            centralGravity: 0.01,
            springLength: 80,
            springConstant: 0.08,
          },
          maxVelocity: 50,
          solver: "forceAtlas2Based",
          timestep: 0.35,
          stabilization: { iterations: 100 },
        },
        interaction: {
          dragNodes: false,
          dragView: false,
          zoomView: false,
        },
      };

      network = new Network(containerRef.current, { nodes: styledNodes, edges: styledEdges }, options);
      // Fit slightly zoomed out
      network.once("stabilizationIterationsDone", () => {
        network.fit({ animation: { duration: 500 } });
      });
    }

    init();

    return () => {
      if (network) network.destroy();
    };
  }, [graphData, lastResults]);

  if (!graphData) {
    return (
      <div className="w-full h-full flex items-center justify-center text-[10px] text-ink3 mono">
        Загрузка данных...
      </div>
    );
  }

  if (lastResults.length === 0) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center text-[10.5px] text-ink3 bg-bg/50 px-4 text-center">
        <span className="text-[16px] mb-2 opacity-60">🔎</span>
        Сделайте запрос в чат, чтобы построить граф связей
      </div>
    );
  }

  return <div ref={containerRef} className="w-full h-full" />;
}
