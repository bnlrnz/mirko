import {
  faCheck,
  faNoteSticky,
  faQuestion,
  faXmark,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";
import type { KeyboardEvent } from "react";

import type { LineageNode, NodeStatus } from "../types";

export const NODE_WIDTH = 190;
export const LANE_HEIGHT = 76;
export const NODE_HEIGHT = LANE_HEIGHT - 12;

interface NodeAction {
  value: NodeStatus | null;
  label: string;
  icon: IconDefinition | null;
  className: string;
}

export const NODE_ACTIONS: NodeAction[] = [
  { value: null, label: "No action", icon: null, className: "" },
  {
    value: "Support",
    label: "Support",
    icon: faCheck,
    className: "status-badge-support",
  },
  {
    value: "Object",
    label: "Object",
    icon: faXmark,
    className: "status-badge-object",
  },
  {
    value: "Clarify",
    label: "Clarify",
    icon: faQuestion,
    className: "status-badge-clarify",
  },
];

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

export function nodeStatusIcon(
  status: string | null | undefined,
): IconDefinition {
  const normalized = (status ?? "").trim().toLowerCase();
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

export function statusBadgeClass(
  status: string | null | undefined,
): string {
  const normalized = (status ?? "").trim().toLowerCase();
  if (normalized === "object") {
    return "status-badge-object";
  }
  if (normalized === "support") {
    return "status-badge-support";
  }
  if (normalized === "clarify") {
    return "status-badge-clarify";
  }
  return "";
}

export function hasNodeBadge(node: LineageNode): boolean {
  return Boolean(node.node_status) || (node.notes_count ?? 0) > 0;
}

export function nodeTintClass(node: LineageNode): string {
  if (node.node_status) {
    return `status-tint-${node.node_status.toLowerCase()}`;
  }
  return (node.notes_count ?? 0) > 0 ? "note-tint-note" : "";
}

export function decisionClass(node: LineageNode): string {
  const decision = (node.decision ?? "").trim().toLowerCase();
  return STATE_CLASSES[decision] ?? "state-idle";
}

export function lineageNodeAriaLabel(
  node: LineageNode,
  newFile: boolean,
): string {
  if (node.node_kind === "draft") {
    return `draft ${node.title ?? ""} for ${node.attached_to ?? ""} ${
      node.status ?? "unknown"
    }${node.is_tracked ? " tracked" : ""}${
      newFile ? " new file" : ""
    }${node.is_hidden ? " hidden" : ""}`;
  }
  return `${node.tdoc_number} ${node.title ?? ""} ${
    node.decision ?? "unknown"
  }${node.is_tracked ? " tracked" : ""}${
    node.is_provisional ? " provisional" : ""
  }${newFile ? " new file" : ""}${node.is_hidden ? " hidden" : ""}`;
}

export function NodeStatusIcon({
  status,
  className,
  x,
  y,
  width = 17,
  height = 17,
}: {
  status: string | null | undefined;
  className: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
}) {
  const icon = nodeStatusIcon(status);
  const [viewWidth, viewHeight, , , path] = icon.icon;
  const paths = Array.isArray(path) ? path : [path];
  return (
    <svg
      x={x}
      y={y}
      width={width}
      height={height}
      viewBox={`0 0 ${viewWidth} ${viewHeight}`}
      preserveAspectRatio="xMidYMid meet"
      className={`node-badge-icon ${className}`}
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((data, index) => (
        <path key={index} d={data} fill="currentColor" />
      ))}
    </svg>
  );
}

export function LineageNodeGlyph({
  node,
  x = 0,
  y = 0,
  selected = false,
  newFile = false,
  ariaLabel,
  onClick,
  onDoubleClick,
  onKeyDown,
}: {
  node: LineageNode;
  x?: number;
  y?: number;
  selected?: boolean;
  newFile?: boolean;
  ariaLabel?: string;
  onClick?: () => void;
  onDoubleClick?: () => void;
  onKeyDown?: (event: KeyboardEvent<SVGGElement>) => void;
}) {
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={ariaLabel ?? lineageNodeAriaLabel(node, newFile)}
      aria-current={selected ? true : undefined}
      className={`node ${decisionClass(node)} ${
        node.is_tracked ? "tracked" : ""
      } ${node.is_provisional ? "provisional" : ""} ${
        node.node_kind === "draft" ? "draft" : ""
      } ${newFile ? "new-file" : ""} ${
        node.is_hidden ? "manually-hidden" : ""
      } ${nodeTintClass(node)} ${selected ? "selected" : ""}`}
      transform={`translate(${x}, ${y})`}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onKeyDown={(event) => {
        if (onKeyDown) {
          onKeyDown(event);
          return;
        }
        if (onClick && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onClick();
        }
      }}
    >
      <rect width={NODE_WIDTH} height={NODE_HEIGHT} rx={9} />
      <circle cx={18} cy={18} r={7} className="state-bubble">
        <title>{node.decision ?? "unknown"}</title>
      </circle>
      <text x={32} y={22} className="node-id">
        {node.node_kind === "draft" ? "DRAFT" : node.tdoc_number}
      </text>
      {node.is_tracked && node.node_kind !== "draft" ? (
        <text
          x={hasNodeBadge(node) ? NODE_WIDTH - 40 : NODE_WIDTH - 16}
          y={23}
          className="node-star"
        >
          ★
        </text>
      ) : null}
      {hasNodeBadge(node) ? (
        <g
          className="node-note-badge"
          data-testid={
            node.node_status
              ? `status-badge-${node.tdoc_number}`
              : `note-badge-${node.tdoc_number}`
          }
        >
          <title>
            {node.node_status
              ? `${node.node_status} status`
              : `${node.notes_count ?? 0} ${
                  (node.notes_count ?? 0) === 1 ? "note" : "notes"
                }`}
          </title>
          <NodeStatusIcon
            x={NODE_WIDTH - 26}
            y={9}
            status={node.node_status}
            className={
              node.node_status ? statusBadgeClass(node.node_status) : "note-badge"
            }
          />
        </g>
      ) : null}
      <text x={14} y={45} className="node-title">
        {(node.title ?? "Untitled").slice(0, 26)}
      </text>
      <text x={NODE_WIDTH - 12} y={58} className="node-state" textAnchor="end">
        {node.status ?? node.decision ?? "unknown"}
      </text>
    </g>
  );
}
