import {
  faCheck,
  faNoteSticky,
  faQuestion,
  faXmark,
} from "@fortawesome/free-solid-svg-icons";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Lineage, LineageEdge, LineageNode } from "../types";

interface Props {
  lineage: Lineage;
  selected: string | null;
  selectedDraft?: number | null;
  includeDrafts?: boolean;
  onSelect: (tdoc: string, artifactId?: number) => void;
  onSelectDraft?: (artifactId: number) => void;
  focusRequest?: { tdoc: string; nonce: number } | null;
  newArtifactPaths?: ReadonlySet<string>;
  newArtifactTdocs?: ReadonlySet<string>;
  onTrack?: (tdoc: string, tracked: boolean) => void;
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
const EMPTY_PATHS: ReadonlySet<string> = new Set();
const DRAFT_ORDER = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

function draftSortKey(node: LineageNode): string {
  return node.remote_mtime ?? node.first_seen_at ?? "";
}

function compareDrafts(left: LineageNode, right: LineageNode): number {
  const time = draftSortKey(left).localeCompare(draftSortKey(right));
  if (time !== 0) {
    return time;
  }
  const name = DRAFT_ORDER.compare(left.title ?? "", right.title ?? "");
  if (name !== 0) {
    return name;
  }
  return (left.artifact_id ?? 0) - (right.artifact_id ?? 0);
}

function draftLink(source: string, target: string): LineageEdge {
  return {
    source,
    target,
    kind: "has_draft",
    confidence: 1,
    verified: true,
    source_ref: null,
    active: true,
    muted: false,
  };
}

export function chainDrafts(lineage: Lineage): Lineage {
  const draftsByTdoc = new Map<string, LineageNode[]>();
  const draftIds = new Set<string>();
  for (const node of lineage.nodes) {
    if (node.node_kind !== "draft" || !node.attached_to) {
      continue;
    }
    draftIds.add(node.tdoc_number);
    draftsByTdoc.set(node.attached_to, [
      ...(draftsByTdoc.get(node.attached_to) ?? []),
      node,
    ]);
  }
  if (draftsByTdoc.size === 0) {
    return lineage;
  }

  const edges = lineage.edges.filter(
    (edge) => !draftIds.has(edge.source) && !draftIds.has(edge.target),
  );

  for (const [tdoc, group] of draftsByTdoc) {
    const drafts = [...group].sort(compareDrafts);
    const incoming = edges.filter((edge) => edge.target === tdoc);
    const outgoing = edges.filter((edge) => edge.source === tdoc);

    if (incoming.length > 0) {
      for (const edge of incoming) {
        const index = edges.indexOf(edge);
        if (index >= 0) {
          edges.splice(index, 1);
        }
      }
    }
    if (incoming.length === 0 && outgoing.length > 0) {
      for (const edge of outgoing) {
        const index = edges.indexOf(edge);
        if (index >= 0) {
          edges.splice(index, 1);
        }
      }
    }

    const first = drafts[0];
    const last = drafts[drafts.length - 1];
    if (incoming.length > 0) {
      for (const edge of incoming) {
        edges.push({ ...edge, target: first.tdoc_number });
      }
    } else {
      edges.push(draftLink(tdoc, first.tdoc_number));
    }
    for (let index = 1; index < drafts.length; index += 1) {
      edges.push(
        draftLink(drafts[index - 1].tdoc_number, drafts[index].tdoc_number),
      );
    }
    if (incoming.length > 0) {
      const edge = incoming[0];
      edges.push({ ...edge, source: last.tdoc_number, target: tdoc });
    } else if (outgoing.length > 0) {
      for (const edge of outgoing) {
        edges.push({ ...edge, source: last.tdoc_number });
      }
    }
  }

  return { nodes: lineage.nodes, edges };
}

export function layoutLineage(lineage: Lineage): {
  nodes: PositionedNode[];
  width: number;
  height: number;
} {
  const byId = new Map(lineage.nodes.map((node) => [node.tdoc_number, node]));
  const edges = lineage.edges.filter(
    (edge) => byId.has(edge.source) && byId.has(edge.target),
  );
  const incoming = new Map<string, LineageEdge[]>();
  for (const edge of edges) {
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
    for (const edge of edges) {
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
  "replied to": "state-approved",
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
  ["state-approved", "approved / agreed / replied to"],
  ["state-merged", "merged / revised"],
  ["state-noted", "noted / postponed"],
  ["state-idle", "not treated / reserved"],
  ["state-negative", "withdrawn / rejected"],
] as const;

function decisionClass(node: LineageNode): string {
  const decision = (node.decision ?? "").trim().toLowerCase();
  return STATE_CLASSES[decision] ?? "state-idle";
}

function noteBadgeClass(tag: string | null | undefined): string {
  const normalized = (tag ?? "").trim().toLowerCase();
  if (normalized === "object") {
    return "note-badge-object";
  }
  if (normalized === "support") {
    return "note-badge-support";
  }
  if (normalized === "clarify") {
    return "note-badge-clarify";
  }
  return "";
}

function noteBadgeIcon(tag: string | null | undefined) {
  const normalized = (tag ?? "").trim().toLowerCase();
  if (normalized === "object") {
    return faXmark;
  }
  if (normalized === "support") {
    return faCheck;
  }
  if (normalized === "clarify") {
    return faQuestion;
  }
  return faNoteSticky;
}

function NoteBadgeIcon({
  tag,
  className,
}: {
  tag: string | null | undefined;
  className: string;
}) {
  const icon = noteBadgeIcon(tag);
  const [width, height, , , path] = icon.icon;
  const paths = Array.isArray(path) ? path : [path];
  return (
    <svg
      x={NODE_WIDTH - 26}
      y={9}
      width={17}
      height={17}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMid meet"
      className={`note-badge-icon ${className}`}
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((data, index) => (
        <path key={index} d={data} fill="currentColor" />
      ))}
    </svg>
  );
}

export function LineageView({
  lineage,
  selected,
  selectedDraft = null,
  includeDrafts = true,
  onSelect,
  onSelectDraft,
  focusRequest,
  newArtifactPaths = EMPTY_PATHS,
  newArtifactTdocs = EMPTY_PATHS,
  onTrack,
}: Props) {
  const [zoom, setZoom] = useState(1);
  const [panning, setPanning] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pan = useRef<{
    pointerId: number;
    x: number;
    y: number;
    left: number;
    top: number;
    moved: boolean;
  } | null>(null);
  const samples = useRef<{ time: number; x: number; y: number }[]>([]);
  const momentum = useRef({
    frame: null as number | null,
    x: 0,
    y: 0,
    last: 0,
  });
  const momentumActive = useRef(false);
  const focusedNonce = useRef<number | null>(null);
  const visibleLineage = useMemo(
    () =>
      includeDrafts
        ? chainDrafts(lineage)
        : {
            nodes: lineage.nodes.filter((node) => node.node_kind !== "draft"),
            edges: lineage.edges.filter((edge) => edge.kind !== "has_draft"),
          },
    [includeDrafts, lineage],
  );
  const layout = useMemo(
    () => layoutLineage(visibleLineage),
    [visibleLineage],
  );
  const positions = useMemo(
    () => new Map(layout.nodes.map((node) => [node.tdoc_number, node])),
    [layout.nodes],
  );
  const visibleEdges = useMemo(
    () =>
      visibleLineage.edges.filter(
        (edge) => positions.has(edge.source) && positions.has(edge.target),
      ),
    [visibleLineage.edges, positions],
  );

  const stopMomentum = () => {
    if (momentum.current.frame !== null) {
      window.cancelAnimationFrame(momentum.current.frame);
    }
    momentum.current.frame = null;
    momentum.current.x = 0;
    momentum.current.y = 0;
    momentumActive.current = false;
  };

  useEffect(() => stopMomentum, []);

  useEffect(() => {
    if (!focusRequest) {
      return;
    }
    stopMomentum();
    const node = positions.get(focusRequest.tdoc);
    if (!node || focusedNonce.current === focusRequest.nonce) {
      return;
    }
    focusedNonce.current = focusRequest.nonce;
    const targetZoom = Math.max(1, zoom);
    if (targetZoom !== zoom) {
      setZoom(targetZoom);
    }
    const frame = window.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (!container) {
        return;
      }
      container.scrollLeft =
        node.x * targetZoom +
        (NODE_WIDTH * targetZoom) / 2 -
        container.clientWidth / 2;
      container.scrollTop =
        node.y * targetZoom +
        ((LANE_HEIGHT - 12) * targetZoom) / 2 -
        container.clientHeight / 2;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [focusRequest, positions]);

  const selectNode = (node: LineageNode) => {
    if (node.node_kind === "draft") {
      if (onSelectDraft && node.artifact_id != null) {
        onSelectDraft(node.artifact_id);
        return;
      }
      onSelect(node.attached_to ?? node.tdoc_number, node.artifact_id ?? undefined);
    } else {
      onSelect(node.tdoc_number);
    }
  };

  const startPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    const container = scrollRef.current;
    if (!container) {
      return;
    }
    const target = event.target as Element;
    if (target.closest?.(".node")) {
      stopMomentum();
      return;
    }
    stopMomentum();
    pan.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      left: container.scrollLeft,
      top: container.scrollTop,
      moved: false,
    };
    samples.current = [
      { time: performance.now(), x: event.clientX, y: event.clientY },
    ];
    container.setPointerCapture?.(event.pointerId);
    setPanning(true);
  };

  const movePan = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = pan.current;
    const container = scrollRef.current;
    if (!state || !container || state.pointerId !== event.pointerId) {
      return;
    }
    const dx = event.clientX - state.x;
    const dy = event.clientY - state.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      state.moved = true;
    }
    if (!state.moved) {
      return;
    }
    container.scrollLeft = state.left - dx;
    container.scrollTop = state.top - dy;
    const now = performance.now();
    samples.current.push({ time: now, x: event.clientX, y: event.clientY });
    samples.current = samples.current.filter(
      (sample) => now - sample.time <= 120,
    );
  };

  const startMomentum = () => {
    if (!scrollRef.current) {
      return;
    }
    const now = performance.now();
    const recent = samples.current.filter(
      (sample) => now - sample.time <= 120,
    );
    if (recent.length < 2) {
      return;
    }
    const first = recent[0];
    const last = recent[recent.length - 1];
    const elapsed = last.time - first.time;
    if (elapsed <= 0) {
      return;
    }
    const x = (-(last.x - first.x) / elapsed) * 0.9;
    const y = (-(last.y - first.y) / elapsed) * 0.9;
    if (Math.hypot(x, y) < 0.15) {
      return;
    }
    momentum.current = { frame: null, x, y, last: now };
    momentumActive.current = true;
    const step = (time: number) => {
      const state = momentum.current;
      const container = scrollRef.current;
      if (!container) {
        stopMomentum();
        return;
      }
      const delta = Math.min(Math.max(time - state.last, 0), 50);
      state.last = time;
      container.scrollLeft += state.x * delta;
      container.scrollTop += state.y * delta;
      const decay = Math.pow(0.94, delta / 16.67);
      state.x *= decay;
      state.y *= decay;
      if (Math.hypot(state.x, state.y) < 0.02) {
        stopMomentum();
        return;
      }
      state.frame = window.requestAnimationFrame(step);
    };
    momentum.current.frame = window.requestAnimationFrame(step);
  };

  const endPan = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = pan.current;
    if (!state || state.pointerId !== event.pointerId) {
      return;
    }
    if (state.moved) {
      startMomentum();
    }
    pan.current = null;
    setPanning(false);
    scrollRef.current?.releasePointerCapture?.(event.pointerId);
  };

  if (visibleLineage.nodes.length === 0) {
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
        <span>{layout.nodes.length} nodes</span>
        <span>{visibleEdges.length} edges</span>
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
      <div
        ref={scrollRef}
        className={`lineage-scroll${panning ? " panning" : ""}`}
        data-testid="lineage-scroll"
        onPointerDown={startPan}
        onPointerMove={movePan}
        onPointerUp={endPan}
        onPointerCancel={endPan}
      >
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
              {visibleEdges.map((edge) => (
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
              {layout.nodes.map((node) => {
                const newFile =
                  node.node_kind === "draft"
                    ? node.logical_path
                      ? newArtifactPaths.has(node.logical_path)
                      : false
                    : newArtifactTdocs.has(node.tdoc_number);
                return (
                <g
                  key={node.tdoc_number}
                  role="button"
                  tabIndex={0}
                  aria-label={
                    node.node_kind === "draft"
                      ? `draft ${node.title ?? ""} for ${node.attached_to ?? ""} ${
                          node.status ?? "unknown"
                        }${node.is_tracked ? " tracked" : ""}${
                          newFile ? " new file" : ""
                        }`
                      : `${node.tdoc_number} ${node.title ?? ""} ${
                          node.decision ?? "unknown"
                        }${node.is_tracked ? " tracked" : ""}${
                          node.is_provisional ? " provisional" : ""
                        }${newFile ? " new file" : ""}`
                  }
                  aria-current={
                    node.node_kind === "draft"
                      ? selectedDraft === node.artifact_id
                        ? true
                        : undefined
                      : selected === node.tdoc_number
                        ? true
                        : undefined
                  }
                  className={`node ${decisionClass(node)} ${
                    node.is_tracked ? "tracked" : ""
                  } ${node.is_provisional ? "provisional" : ""} ${
                    node.node_kind === "draft" ? "draft" : ""
                  } ${newFile ? "new-file" : ""} ${
                    node.node_kind === "draft"
                      ? selectedDraft === node.artifact_id
                        ? "selected"
                        : ""
                      : selected === node.tdoc_number
                        ? "selected"
                        : ""
                  }`}
                  transform={`translate(${node.x}, ${node.y})`}
                  onClick={() => selectNode(node)}
                  onDoubleClick={() => {
                    if (node.node_kind !== "draft" && onTrack) {
                      onTrack(node.tdoc_number, !node.is_tracked);
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      selectNode(node);
                    }
                  }}
                >
                  <rect width={NODE_WIDTH} height={LANE_HEIGHT - 12} rx={9} />
                  <circle cx={18} cy={18} r={7} className="state-bubble">
                    <title>{node.decision ?? "unknown"}</title>
                  </circle>
                  <text x={32} y={22} className="node-id">
                    {node.node_kind === "draft" ? "DRAFT" : node.tdoc_number}
                  </text>
                  {node.is_tracked && node.node_kind !== "draft" ? (
                    <text
                      x={node.note_badge ? NODE_WIDTH - 40 : NODE_WIDTH - 16}
                      y={23}
                      className="node-star"
                    >
                      ★
                    </text>
                  ) : null}
                  {node.note_badge && node.node_kind !== "draft" ? (
                    <g
                      className="node-note-badge"
                      data-testid={`note-badge-${node.tdoc_number}`}
                    >
                      <title>{node.note_badge} note</title>
                      <NoteBadgeIcon
                        tag={node.note_badge}
                        className={noteBadgeClass(node.note_badge)}
                      />
                    </g>
                  ) : null}
                  <text x={14} y={45} className="node-title">
                    {(node.title ?? "Untitled").slice(0, 26)}
                  </text>
                  <text
                    x={NODE_WIDTH - 12}
                    y={58}
                    className="node-state"
                    textAnchor="end"
                  >
                    {node.status ?? node.decision ?? "unknown"}
                  </text>
                </g>
                );
              })}
            </g>
          </svg>
        </div>
      </div>
    </div>
  );
}
