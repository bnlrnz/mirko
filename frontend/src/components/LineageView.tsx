import { useMemo, useState } from "react";

import type { Lineage, LineageEdge, LineageNode } from "../types";

interface Props {
  lineage: Lineage;
  selected: string | null;
  onSelect: (tdoc: string) => void;
}

interface PositionedNode extends LineageNode {
  x: number;
  y: number;
  lane: number;
  depth: number;
}

const NODE_WIDTH = 190;
const LANE_HEIGHT = 76;
const DEPTH_WIDTH = 230;
const MARGIN = 36;

export function layoutLineage(lineage: Lineage): {
  nodes: PositionedNode[];
  width: number;
  height: number;
} {
  const byId = new Map(lineage.nodes.map((node) => [node.tdoc_number, node]));
  const incoming = new Map<string, LineageEdge[]>();
  for (const edge of lineage.edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) {
      continue;
    }
    incoming.set(edge.target, [
      ...(incoming.get(edge.target) ?? []),
      edge,
    ]);
  }

  const depth = new Map<string, number>();
  for (const node of lineage.nodes) {
    depth.set(node.tdoc_number, 0);
  }
  for (let pass = 0; pass < lineage.nodes.length; pass += 1) {
    let changed = false;
    for (const edge of lineage.edges) {
      if (!depth.has(edge.source) || !depth.has(edge.target)) {
        continue;
      }
      const candidate = (depth.get(edge.source) ?? 0) + 1;
      if (candidate > (depth.get(edge.target) ?? 0)) {
        depth.set(edge.target, candidate);
        changed = true;
      }
    }
    if (!changed) {
      break;
    }
  }

  const ordered = [...lineage.nodes].sort((a, b) => {
    const depthDelta = (depth.get(a.tdoc_number) ?? 0) - (depth.get(b.tdoc_number) ?? 0);
    if (depthDelta !== 0) {
      return depthDelta;
    }
    const agenda = (a.agenda_item ?? "").localeCompare(b.agenda_item ?? "");
    return agenda !== 0 ? agenda : a.tdoc_number.localeCompare(b.tdoc_number);
  });

  const laneOf = new Map<string, number>();
  let laneCount = 0;
  for (const node of ordered) {
    const predecessors = (incoming.get(node.tdoc_number) ?? [])
      .map((edge) => laneOf.get(edge.source))
      .filter((lane): lane is number => lane !== undefined);
    const lane = predecessors.length
      ? Math.min(...predecessors)
      : laneCount++;
    laneOf.set(node.tdoc_number, lane);
  }

  const nodes = ordered.map((node) => {
    const nodeDepth = depth.get(node.tdoc_number) ?? 0;
    const lane = laneOf.get(node.tdoc_number) ?? 0;
    return {
      ...node,
      depth: nodeDepth,
      lane,
      x: MARGIN + nodeDepth * DEPTH_WIDTH,
      y: MARGIN + lane * LANE_HEIGHT,
    };
  });
  const width =
    Math.max(320, ...nodes.map((node) => node.x + NODE_WIDTH + MARGIN));
  const height = Math.max(180, ...nodes.map((node) => node.y + LANE_HEIGHT));
  return { nodes, width, height };
}

function edgePath(edge: LineageEdge, positions: Map<string, PositionedNode>) {
  const source = positions.get(edge.source);
  const target = positions.get(edge.target);
  if (!source || !target) {
    return "";
  }
  const x1 = source.x + NODE_WIDTH;
  const y1 = source.y + LANE_HEIGHT / 2 - 8;
  const x2 = target.x;
  const y2 = target.y + LANE_HEIGHT / 2 - 8;
  if (source.lane === target.lane) {
    return `M ${x1} ${y1} L ${x2} ${y2}`;
  }
  const mid = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
}

const STATE_CLASSES: Record<string, string> = {
  approved: "state-approved",
  agreed: "state-approved",
  merged: "state-merged",
  revised: "state-merged",
  noted: "state-noted",
  postponed: "state-noted",
  "not treated": "state-idle",
  "not pursued": "state-idle",
  reserved: "state-idle",
  withdrawn: "state-negative",
  rejected: "state-negative",
};

const LEGEND = [
  ["state-approved", "approved / agreed"],
  ["state-merged", "merged / revised"],
  ["state-noted", "noted / postponed"],
  ["state-idle", "not treated / reserved"],
  ["state-negative", "withdrawn / rejected"],
] as const;

function decisionClass(node: LineageNode): string {
  const decision = (node.decision ?? "").trim().toLowerCase();
  return STATE_CLASSES[decision] ?? "state-idle";
}

export function LineageView({ lineage, selected, onSelect }: Props) {
  const [zoom, setZoom] = useState(1);
  const layout = useMemo(() => layoutLineage(lineage), [lineage]);
  const positions = useMemo(
    () => new Map(layout.nodes.map((node) => [node.tdoc_number, node])),
    [layout.nodes],
  );

  if (lineage.nodes.length === 0) {
    return (
      <div className="empty-state">
        <h3>No lineage yet</h3>
        <p>Sync a meeting or track a TDoc to see its revision and merge lanes.</p>
      </div>
    );
  }

  return (
    <div className="lineage-view">
      <div className="lineage-toolbar">
        <span>{lineage.nodes.length} nodes</span>
        <span>{lineage.edges.length} edges</span>
        <span className="lineage-legend" aria-label="Node state colors">
          {LEGEND.map(([className, label]) => (
            <span key={className} className="legend-item">
              <i className={`legend-swatch ${className}`} />
              {label}
            </span>
          ))}
        </span>
        <button type="button" onClick={() => setZoom((value) => Math.max(0.5, value - 0.1))}>
          −
        </button>
        <button type="button" onClick={() => setZoom((value) => Math.min(1.8, value + 0.1))}>
          +
        </button>
        <button type="button" onClick={() => setZoom(1)}>
          Reset
        </button>
      </div>
      <div className="lineage-scroll">
        <div
          className="lineage-canvas"
          style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
        >
          <svg
            role="img"
            aria-label="TDoc lineage graph"
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
          >
            <g className="edges">
              {lineage.edges.map((edge) => (
                <path
                  key={`${edge.source}-${edge.target}-${edge.kind}`}
                  className={`edge ${edge.kind} ${
                    edge.verified ? "verified" : "unverified"
                  } ${edge.active === false || edge.muted ? "muted" : ""}`}
                  d={edgePath(edge, positions)}
                  data-testid={`edge-${edge.source}-${edge.target}`}
                />
              ))}
            </g>
            <g className="nodes">
              {layout.nodes.map((node) => (
                <g
                  key={node.tdoc_number}
                  role="button"
                  tabIndex={0}
                  aria-label={`${node.tdoc_number} ${node.title ?? ""} ${
                    node.decision ?? "unknown"
                  }${node.is_tracked ? " tracked" : ""}`}
                  aria-current={selected === node.tdoc_number || undefined}
                  className={`node ${decisionClass(node)} ${
                    node.is_tracked ? "tracked" : ""
                  } ${node.is_provisional ? "provisional" : ""} ${
                    selected === node.tdoc_number ? "selected" : ""
                  }`}
                  transform={`translate(${node.x}, ${node.y})`}
                  onClick={() => onSelect(node.tdoc_number)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(node.tdoc_number);
                    }
                  }}
                >
                  <rect width={NODE_WIDTH} height={LANE_HEIGHT - 12} rx={9} />
                  <circle cx={18} cy={22} r={7} className="state-bubble">
                    <title>{node.decision ?? "unknown"}</title>
                  </circle>
                  <text x={32} y={26} className="node-id">
                    {node.tdoc_number}
                  </text>
                  {node.is_tracked ? (
                    <text x={NODE_WIDTH - 16} y={27} className="node-star">
                      ★
                    </text>
                  ) : null}
                  <text x={14} y={48} className="node-title">
                    {(node.title ?? "Untitled").slice(0, 26)}
                  </text>
                  <text x={14} y={62} className="node-meta">
                    {node.decision ?? "unknown"}
                    {node.is_provisional ? " · provisional" : ""}
                  </text>
                </g>
              ))}
            </g>
          </svg>
        </div>
      </div>
    </div>
  );
}
