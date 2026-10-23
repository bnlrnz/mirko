import {
  faEnvelope,
  faEnvelopesBulk,
} from "@fortawesome/free-solid-svg-icons";
import { useEffect, useMemo, useRef, useState } from "react";

import { agendaFilterOptions } from "../agendaFilter";
import type {
  Filters,
  Lineage,
  LineageEdge,
  LineageNode,
  MailSummary,
} from "../types";
import { EMPTY_FILTERS } from "../lineageTabs";
import {
  sourceMatches,
  uniqueSourceCompanies,
} from "../sourceFilter";
import { MailDialog } from "./MailViewer";
import {
  LANE_HEIGHT,
  LineageNodeGlyph,
  NODE_WIDTH,
} from "./NodeVisuals";

interface Props {
  lineage: Lineage;
  selected: string | null;
  selectedDraft?: number | null;
  filters?: Filters;
  onFilters?: (filters: Filters) => void;
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

const DEPTH_WIDTH = 230;
const MARGIN = 36;
const EMPTY_PATHS: ReadonlySet<string> = new Set();
const DRAFT_ORDER = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});
const WITHDRAWN_STATES = new Set(["withdrawn", "rejected"]);
const NOT_TREATED_STATES = new Set(["not treated", "not-treated", "reserved"]);

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
    emails: [],
  };
}

function nodeMoment(node: LineageNode | undefined): string {
  if (!node) {
    return "";
  }
  return node.node_kind === "draft"
    ? (node.remote_mtime ?? node.first_seen_at ?? "")
    : (node.first_seen_at ?? node.remote_mtime ?? "");
}

function mailMoment(mail: MailSummary): string {
  return mail.date_utc ?? mail.ingested_at;
}

function distributeMails(
  mails: MailSummary[],
  moments: string[],
): MailSummary[][] {
  const buckets = moments.slice(1).map(() => [] as MailSummary[]);
  if (mails.length === 0 || buckets.length === 0) {
    return buckets;
  }
  for (const mail of mails) {
    const moment = mailMoment(mail);
    let bucket = -1;
    for (let index = 1; index < moments.length; index += 1) {
      const start = moments[index - 1];
      const end = moments[index];
      if (!end) {
        continue;
      }
      if ((!start || moment >= start) && moment <= end) {
        bucket = index - 1;
        break;
      }
    }
    if (bucket < 0) {
      bucket = buckets.length - 1;
      for (let index = 1; index < moments.length; index += 1) {
        if (moments[index] && moment <= moments[index]) {
          bucket = index - 1;
          break;
        }
      }
    }
    buckets[bucket].push(mail);
  }
  return buckets;
}

export function chainDrafts(lineage: Lineage): Lineage {
  const byId = new Map(lineage.nodes.map((node) => [node.tdoc_number, node]));
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

  const edges: LineageEdge[] = lineage.edges
    .filter(
      (edge) => !draftIds.has(edge.source) && !draftIds.has(edge.target),
    )
    .map((edge) => ({ ...edge, emails: [...(edge.emails ?? [])] }));

  for (const [tdoc, group] of draftsByTdoc) {
    const tdocNode = byId.get(tdoc);
    const drafts = [...group].sort(compareDrafts);
    const incoming = edges.filter((edge) => edge.target === tdoc);
    const outgoing = edges.filter((edge) => edge.source === tdoc);
    const hasIncoming = incoming.length > 0;

    if (hasIncoming) {
      for (const edge of incoming) {
        const index = edges.indexOf(edge);
        if (index >= 0) {
          edges.splice(index, 1);
        }
      }
    } else if (outgoing.length > 0) {
      for (const edge of outgoing) {
        const index = edges.indexOf(edge);
        if (index >= 0) {
          edges.splice(index, 1);
        }
      }
    }

    const first = drafts[0];
    const last = drafts[drafts.length - 1];
    const firstSegments: LineageEdge[] = [];
    if (hasIncoming) {
      for (const edge of incoming) {
        const segment = {
          ...edge,
          target: first.tdoc_number,
          emails: [],
        };
        firstSegments.push(segment);
        edges.push(segment);
      }
    } else {
      const segment = draftLink(tdoc, first.tdoc_number);
      firstSegments.push(segment);
      edges.push(segment);
    }

    const draftSegments: LineageEdge[] = [];
    for (let index = 1; index < drafts.length; index += 1) {
      const segment = draftLink(
        drafts[index - 1].tdoc_number,
        drafts[index].tdoc_number,
      );
      draftSegments.push(segment);
      edges.push(segment);
    }

    const draftMoments = drafts.map((draft) => nodeMoment(draft));
    if (hasIncoming) {
      const lastSegment = {
        ...incoming[0],
        source: last.tdoc_number,
        target: tdoc,
        emails: [],
      };
      edges.push(lastSegment);
      for (let index = 0; index < incoming.length; index += 1) {
        const edge = incoming[index];
        const buckets = distributeMails(edge.emails ?? [], [
          nodeMoment(byId.get(edge.source)),
          ...draftMoments,
          nodeMoment(tdocNode),
        ]);
        for (let bucket = 0; bucket < buckets.length; bucket += 1) {
          const target =
            bucket === 0
              ? firstSegments[index]
              : bucket === buckets.length - 1
                ? lastSegment
                : draftSegments[bucket - 1];
          target.emails?.push(...buckets[bucket]);
        }
      }
    } else if (outgoing.length > 0) {
      for (const edge of outgoing) {
        const lastSegment = {
          ...edge,
          source: last.tdoc_number,
          emails: [],
        };
        edges.push(lastSegment);
        const buckets = distributeMails(edge.emails ?? [], [
          nodeMoment(tdocNode),
          ...draftMoments,
          nodeMoment(byId.get(edge.target)),
        ]);
        for (let bucket = 0; bucket < buckets.length; bucket += 1) {
          const target =
            bucket === 0
              ? firstSegments[0]
              : bucket === buckets.length - 1
                ? lastSegment
                : draftSegments[bucket - 1];
          target.emails?.push(...buckets[bucket]);
        }
      }
    }
  }

  for (const edge of edges) {
    edge.emails?.sort((left, right) => {
      const time = mailMoment(left).localeCompare(mailMoment(right));
      return time !== 0 ? time : left.id - right.id;
    });
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
    const depthDelta =
      (depth.get(a.tdoc_number) ?? 0) - (depth.get(b.tdoc_number) ?? 0);
    if (depthDelta !== 0) {
      return depthDelta;
    }
    const agenda = (a.agenda_item ?? "").localeCompare(b.agenda_item ?? "");
    return agenda !== 0 ? agenda : a.tdoc_number.localeCompare(b.tdoc_number);
  });

  const laneOf = new Map<string, number>();
  let laneCount = 0;
  for (const node of ordered) {
    const incomingEdges = incoming.get(node.tdoc_number) ?? [];
    const baselineEdges = incomingEdges.filter(
      (edge) => edge.kind === "revision_of",
    );
    const preferredEdges = baselineEdges.length > 0 ? baselineEdges : incomingEdges;
    const predecessors = preferredEdges
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

function edgeMailKey(edge: LineageEdge): string {
  return `${edge.source}->${edge.target}:${edge.kind}`;
}

function edgeMidpoint(
  edge: LineageEdge,
  positions: Map<string, PositionedNode>,
): { x: number; y: number } | null {
  const source = positions.get(edge.source);
  const target = positions.get(edge.target);
  if (!source || !target) {
    return null;
  }
  return {
    x: (source.x + NODE_WIDTH + target.x) / 2,
    y:
      (source.y + target.y) / 2 +
      LANE_HEIGHT / 2 -
      8,
  };
}

function mailButtonLabel(mail: MailSummary): string {
  return `Mail: ${mail.subject ?? "(no subject)"} from ${
    mail.from_addr ?? "unknown sender"
  }`;
}

function MailIconPaths({ bulk }: { bulk: boolean }) {
  const icon = bulk ? faEnvelopesBulk : faEnvelope;
  const [viewWidth, viewHeight, , , path] = icon.icon;
  const paths = Array.isArray(path) ? path : [path];
  return (
    <svg
      x={-9}
      y={-9}
      width={18}
      height={18}
      viewBox={`0 0 ${viewWidth} ${viewHeight}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((data, index) => (
        <path key={index} d={data} fill="currentColor" />
      ))}
    </svg>
  );
}

function EdgeMailGlyph({
  mails,
  x,
  y,
  bulk,
  label,
  onActivate,
  onPreview,
  onPreviewEnd,
}: {
  mails: MailSummary[];
  x: number;
  y: number;
  bulk: boolean;
  label: string;
  onActivate: () => void;
  onPreview: (element: Element, mails: MailSummary[]) => void;
  onPreviewEnd: () => void;
}) {
  return (
    <g
      className={`edge-mail${bulk ? " bulk" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={label}
      transform={`translate(${x}, ${y})`}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onActivate();
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          onActivate();
        }
      }}
      onMouseEnter={(event) => onPreview(event.currentTarget, mails)}
      onMouseLeave={onPreviewEnd}
      onFocus={(event) => onPreview(event.currentTarget, mails)}
      onBlur={onPreviewEnd}
    >
      <circle className="edge-mail-bg" r={12} />
      <MailIconPaths bulk={bulk} />
      {bulk ? (
        <g className="edge-mail-count" transform="translate(11, -11)">
          <circle r={7} />
          <text x={0} y={3} textAnchor="middle">
            {mails.length}
          </text>
        </g>
      ) : null}
    </g>
  );
}

function MailPreviewCard({
  mails,
  x,
  y,
}: {
  mails: MailSummary[];
  x: number;
  y: number;
}) {
  const left = Math.max(170, Math.min(x, window.innerWidth - 170));
  return (
    <div
      className="mail-preview"
      role="tooltip"
      style={{ left, top: Math.max(150, y - 10) }}
    >
      {mails.length > 1 ? (
        <div className="mail-preview-count">{mails.length} mails</div>
      ) : null}
      {mails.slice(0, 4).map((mail) => (
        <div className="mail-preview-item" key={mail.id}>
          <strong>{mail.subject ?? "(no subject)"}</strong>
          <span>{mail.from_addr ?? "unknown sender"}</span>
        </div>
      ))}
      {mails.length > 4 ? (
        <div className="mail-preview-more">
          +{mails.length - 4} more
        </div>
      ) : null}
    </div>
  );
}

const LEGEND = [
  ["state-approved", "approved / agreed / replied to"],
  ["state-merged", "merged / revised"],
  ["state-noted", "noted / postponed"],
  ["state-idle", "not treated / reserved"],
  ["state-negative", "withdrawn / rejected"],
] as const;

function uniqueOptions(values: (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => !!value))].sort();
}

interface FilterChoice {
  value: string;
  label: string;
}

function choiceOptions(
  values: (string | null | undefined)[],
): FilterChoice[] {
  return uniqueOptions(values).map((value) => ({ value, label: value }));
}

function CheckboxFilter({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: FilterChoice[];
  selected: readonly string[];
  onToggle: (value: string) => void;
}) {
  return (
    <fieldset
      className="lineage-filter-group"
      aria-label={`${label} filter`}
    >
      <legend>{label}</legend>
      <div className="lineage-filter-options">
        {options.length === 0 ? (
          <span className="lineage-filter-none">None</span>
        ) : (
          options.map((option) => (
            <label key={option.value}>
              <input
                type="checkbox"
                value={option.value}
                checked={selected.includes(option.value)}
                onChange={() => onToggle(option.value)}
              />
              <span title={option.label}>{option.label}</span>
            </label>
          ))
        )}
      </div>
    </fieldset>
  );
}

function filterMatches(node: LineageNode, filters: Filters): boolean {
  if (
    filters.agenda.length > 0 &&
    (!node.agenda_item || !filters.agenda.includes(node.agenda_item))
  ) {
    return false;
  }
  if (
    filters.type.length > 0 &&
    (!node.type || !filters.type.includes(node.type))
  ) {
    return false;
  }
  if (
    filters.state.length > 0 &&
    (!node.decision || !filters.state.includes(node.decision))
  ) {
    return false;
  }
  if (
    filters.source.length > 0 &&
    !filters.source.some((company) =>
      sourceMatches(company, node.source),
    )
  ) {
    return false;
  }
  return true;
}

function htmlConnectedIds(lineage: Lineage): Set<string> {
  const neighbours = new Map<string, Set<string>>();
  for (const node of lineage.nodes) {
    neighbours.set(node.tdoc_number, new Set());
  }
  for (const edge of lineage.edges) {
    neighbours.get(edge.source)?.add(edge.target);
    neighbours.get(edge.target)?.add(edge.source);
  }
  const connected = new Set(
    lineage.nodes
      .filter((node) => node.state_source === "html")
      .map((node) => node.tdoc_number),
  );
  const queue = [...connected];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    for (const neighbour of neighbours.get(current) ?? []) {
      if (!connected.has(neighbour)) {
        connected.add(neighbour);
        queue.push(neighbour);
      }
    }
  }
  return connected;
}

function trackedConnectedIds(lineage: Lineage): Set<string> {
  const tracked = new Set(
    lineage.nodes
      .filter(
        (node) => node.node_kind !== "draft" && node.is_tracked,
      )
      .map((node) => node.tdoc_number),
  );
  const connected = new Set(tracked);
  for (const edge of lineage.edges) {
    if (tracked.has(edge.source)) {
      connected.add(edge.target);
    }
    if (tracked.has(edge.target)) {
      connected.add(edge.source);
    }
  }
  return connected;
}

function hiddenByControls(
  node: LineageNode,
  filters: Filters,
  htmlConnected: ReadonlySet<string>,
): boolean {
  if (!filters.showHidden && node.is_hidden) {
    return true;
  }
  if (filters.hideUnknown && !htmlConnected.has(node.tdoc_number)) {
    return true;
  }
  const decision = (node.decision ?? "").trim().toLowerCase();
  if (filters.hideWithdrawn && WITHDRAWN_STATES.has(decision)) {
    return true;
  }
  if (filters.hideNotTreated && NOT_TREATED_STATES.has(decision)) {
    return true;
  }
  return false;
}

function filterLineage(lineage: Lineage, filters: Filters): Lineage {
  const active =
    Boolean(
      filters.agenda.length ||
        filters.type.length ||
        filters.state.length ||
        filters.source.length,
    ) ||
    filters.tracked ||
    filters.hideWithdrawn ||
    filters.hideNotTreated ||
    filters.hideUnknown ||
    !filters.showHidden;
  if (!active) {
    return lineage;
  }
  const htmlConnected = filters.hideUnknown
    ? htmlConnectedIds(lineage)
    : new Set<string>();
  const trackedConnected = filters.tracked
    ? trackedConnectedIds(lineage)
    : null;
  const keptTdocs = new Set(
    lineage.nodes
      .filter(
        (node) =>
          node.node_kind !== "draft" &&
          filterMatches(node, filters) &&
          (!trackedConnected ||
            trackedConnected.has(node.tdoc_number)) &&
          !hiddenByControls(node, filters, htmlConnected),
      )
      .map((node) => node.tdoc_number),
  );
  const nodes = lineage.nodes.filter((node) =>
    node.node_kind === "draft"
      ? !hiddenByControls(node, filters, htmlConnected) &&
        Boolean(node.attached_to && keptTdocs.has(node.attached_to))
      : keptTdocs.has(node.tdoc_number),
  );
  const ids = new Set(nodes.map((node) => node.tdoc_number));
  return {
    nodes,
    edges: lineage.edges.filter(
      (edge) => ids.has(edge.source) && ids.has(edge.target),
    ),
  };
}

export function LineageView({
  lineage,
  selected,
  selectedDraft = null,
  filters = EMPTY_FILTERS,
  onFilters,
  onSelect,
  onSelectDraft,
  focusRequest,
  newArtifactPaths = EMPTY_PATHS,
  newArtifactTdocs = EMPTY_PATHS,
  onTrack,
}: Props) {
  const includeDrafts = filters.includeEphemeral;
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
  const focusFrame = useRef<number | null>(null);
  const [expandedMailEdge, setExpandedMailEdge] = useState<string | null>(
    null,
  );
  const [openMail, setOpenMail] = useState<MailSummary | null>(null);
  const [mailPreview, setMailPreview] = useState<{
    mails: MailSummary[];
    x: number;
    y: number;
  } | null>(null);
  const filterOptions = useMemo(() => {
    const tdocs = lineage.nodes.filter((node) => node.node_kind !== "draft");
    return {
      agendas: agendaFilterOptions(tdocs),
      types: choiceOptions(tdocs.map((node) => node.type)),
      states: choiceOptions(tdocs.map((node) => node.decision)),
      sources: uniqueSourceCompanies(tdocs.map((node) => node.source)).map(
        (company) => ({ value: company, label: company }),
      ),
    };
  }, [lineage.nodes]);
  const filteredLineage = useMemo(
    () => filterLineage(lineage, filters),
    [filters, lineage],
  );
  const visibleLineage = useMemo(
    () =>
      includeDrafts
        ? chainDrafts(filteredLineage)
        : {
            nodes: filteredLineage.nodes.filter(
              (node) => node.node_kind !== "draft",
            ),
            edges: filteredLineage.edges.filter(
              (edge) => edge.kind !== "has_draft",
            ),
          },
    [filteredLineage, includeDrafts],
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
    if (focusFrame.current !== null) {
      window.cancelAnimationFrame(focusFrame.current);
    }
    const targetZoom = Math.max(1, zoom);
    if (targetZoom !== zoom) {
      setZoom(targetZoom);
    }
    focusFrame.current = window.requestAnimationFrame(() => {
      focusFrame.current = null;
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
  }, [focusRequest, positions]);

  useEffect(
    () => () => {
      if (focusFrame.current !== null) {
        window.cancelAnimationFrame(focusFrame.current);
      }
    },
    [],
  );

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

  const openMailView = (mail: MailSummary) => {
    setExpandedMailEdge(null);
    setMailPreview(null);
    setOpenMail(mail);
  };
  const previewMails = (element: Element, mails: MailSummary[]) => {
    const rect = element.getBoundingClientRect();
    setMailPreview({
      mails,
      x: rect.left + rect.width / 2,
      y: rect.top,
    });
  };
  const clearMailPreview = () => setMailPreview(null);

  useEffect(() => {
    if (expandedMailEdge === null) {
      return;
    }
    const collapse = (event: PointerEvent) => {
      const target = event.target as Element | null;
      if (target?.closest?.(".edge-mail")) {
        return;
      }
      setExpandedMailEdge(null);
      setMailPreview(null);
    };
    document.addEventListener("pointerdown", collapse, true);
    return () => document.removeEventListener("pointerdown", collapse, true);
  }, [expandedMailEdge]);

  const setFilter = (
    key:
      | "tracked"
      | "includeEphemeral"
      | "hideWithdrawn"
      | "hideNotTreated"
      | "hideUnknown"
      | "showHidden",
    value: boolean,
  ) => {
    onFilters?.({ ...filters, [key]: value });
  };
  const toggleFilter = (
    key: "agenda" | "type" | "state" | "source",
    value: string,
  ) => {
    const selected = filters[key];
    onFilters?.({
      ...filters,
      [key]: selected.includes(value)
        ? selected.filter((item) => item !== value)
        : [...selected, value],
    });
  };
  const hasFilters =
    Boolean(
      filters.agenda.length ||
        filters.type.length ||
        filters.state.length ||
        filters.source.length,
    ) ||
    filters.tracked ||
    !filters.includeEphemeral ||
    filters.hideWithdrawn ||
    filters.hideNotTreated ||
    filters.hideUnknown ||
    filters.showHidden;

  const startPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    const container = scrollRef.current;
    if (!container) {
      return;
    }
    stopMomentum();
    const target = event.target as Element;
    if (
      !target.closest?.(".lineage-canvas") ||
      target.closest?.(".node") ||
      target.closest?.(".edge-mail")
    ) {
      return;
    }
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
      if (!momentumActive.current || !container) {
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
        <span className="lineage-toolbar-actions">
          <button type="button" onClick={() => setZoom((value) => Math.max(0.5, value - 0.1))}>
            −
          </button>
          <button type="button" onClick={() => setZoom((value) => Math.min(1.8, value + 0.1))}>
            +
          </button>
          <button type="button" onClick={() => setZoom(1)}>
            Reset
          </button>
        </span>
      </div>
      <div className="lineage-filters" aria-label="Lineage filters">
        <CheckboxFilter
          label="Agenda"
          options={filterOptions.agendas}
          selected={filters.agenda}
          onToggle={(value) => toggleFilter("agenda", value)}
        />
        <CheckboxFilter
          label="Type"
          options={filterOptions.types}
          selected={filters.type}
          onToggle={(value) => toggleFilter("type", value)}
        />
        <CheckboxFilter
          label="State"
          options={filterOptions.states}
          selected={filters.state}
          onToggle={(value) => toggleFilter("state", value)}
        />
        <CheckboxFilter
          label="Source"
          options={filterOptions.sources}
          selected={filters.source}
          onToggle={(value) => toggleFilter("source", value)}
        />
        <fieldset
          className="lineage-filter-group lineage-display-group"
          aria-label="Display options"
        >
          <legend>Display</legend>
          <div className="lineage-display-options">
            <label className="check">
              <input
                type="checkbox"
                checked={filters.tracked}
                onChange={(event) =>
                  setFilter("tracked", event.target.checked)
                }
              />
              Tracked only
            </label>
            <label className="check">
              <input
                type="checkbox"
                aria-label="Include Drafts"
                checked={filters.includeEphemeral}
                onChange={(event) =>
                  setFilter("includeEphemeral", event.target.checked)
                }
              />
              Include Drafts
            </label>
            <label className="check">
              <input
                type="checkbox"
                aria-label="Hide withdrawn"
                checked={filters.hideWithdrawn}
                onChange={(event) =>
                  setFilter("hideWithdrawn", event.target.checked)
                }
              />
              Hide withdrawn
            </label>
            <label className="check">
              <input
                type="checkbox"
                aria-label="Hide not treated"
                checked={filters.hideNotTreated}
                onChange={(event) =>
                  setFilter("hideNotTreated", event.target.checked)
                }
              />
              Hide not treated
            </label>
            <label className="check">
              <input
                type="checkbox"
                aria-label="Hide unknown"
                checked={filters.hideUnknown}
                onChange={(event) =>
                  setFilter("hideUnknown", event.target.checked)
                }
              />
              Hide unknown
            </label>
            <label className="check">
              <input
                type="checkbox"
                aria-label="Show hidden"
                checked={filters.showHidden}
                onChange={(event) =>
                  setFilter("showHidden", event.target.checked)
                }
              />
              Show hidden
            </label>
            <button
              type="button"
              className="lineage-clear"
              disabled={!hasFilters}
              onClick={() =>
                onFilters?.({
                  ...EMPTY_FILTERS,
                  agenda: [],
                  type: [],
                  state: [],
                  source: [],
                })
              }
            >
              Clear
            </button>
          </div>
        </fieldset>
      </div>
      {layout.nodes.length === 0 ? (
        <div className="lineage-empty-filter">
          <h3>No nodes match</h3>
          <p>Adjust the filters or reveal hidden nodes.</p>
        </div>
      ) : (
      <div
        ref={scrollRef}
        className={`lineage-scroll${panning ? " panning" : ""}`}
        data-testid="lineage-scroll"
        onPointerDown={startPan}
        onPointerMove={movePan}
        onPointerUp={endPan}
        onPointerCancel={endPan}
        onWheel={stopMomentum}
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
            <g className="edge-mails">
              {visibleEdges.map((edge) => {
                const mails = edge.emails ?? [];
                if (mails.length === 0) {
                  return null;
                }
                const point = edgeMidpoint(edge, positions);
                if (!point) {
                  return null;
                }
                const key = edgeMailKey(edge);
                if (expandedMailEdge === key && mails.length > 1) {
                  return mails.map((mail, index) => (
                    <EdgeMailGlyph
                      key={`${key}:${mail.id}`}
                      mails={[mail]}
                      x={point.x}
                      y={
                        point.y +
                        (index - (mails.length - 1) / 2) * 24
                      }
                      bulk={false}
                      label={mailButtonLabel(mail)}
                      onActivate={() => openMailView(mail)}
                      onPreview={previewMails}
                      onPreviewEnd={clearMailPreview}
                    />
                  ));
                }
                return (
                  <EdgeMailGlyph
                    key={key}
                    mails={mails}
                    x={point.x}
                    y={point.y}
                    bulk={mails.length > 1}
                    label={
                      mails.length > 1
                        ? `Mail bundle: ${mails.length} mails`
                        : mailButtonLabel(mails[0])
                    }
                    onActivate={() => {
                      if (mails.length > 1) {
                        setMailPreview(null);
                        setExpandedMailEdge(key);
                      } else {
                        openMailView(mails[0]);
                      }
                    }}
                    onPreview={previewMails}
                    onPreviewEnd={clearMailPreview}
                  />
                );
              })}
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
                  <LineageNodeGlyph
                    key={node.tdoc_number}
                    node={node}
                    x={node.x}
                    y={node.y}
                    selected={
                      node.node_kind === "draft"
                        ? selectedDraft === node.artifact_id
                        : selected === node.tdoc_number
                    }
                    newFile={newFile}
                    onClick={() => selectNode(node)}
                    onDoubleClick={() => {
                      if (node.node_kind !== "draft" && onTrack) {
                        onTrack(node.tdoc_number, !node.is_tracked);
                      }
                    }}
                  />
                );
              })}
            </g>
          </svg>
        </div>
      </div>
      )}
      {mailPreview ? <MailPreviewCard {...mailPreview} /> : null}
      {openMail ? (
        <MailDialog mail={openMail} onClose={() => setOpenMail(null)} />
      ) : null}
    </div>
  );
}
