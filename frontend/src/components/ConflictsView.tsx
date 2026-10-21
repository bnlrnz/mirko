import type {
  Assertion,
  Conflict,
  ConflictResolution,
  Lineage,
  LineageNode,
} from "../types";
import {
  LineageNodeGlyph,
  NODE_HEIGHT,
  NODE_WIDTH,
} from "./NodeVisuals";

interface Props {
  conflicts: Conflict[];
  lineage: Lineage;
  onResolve: (id: number, resolution: ConflictResolution) => void;
  onSelect: (tdoc: string) => void;
}

function competingNode(assertion: Assertion): string {
  if (assertion.predicate === "decision") {
    return assertion.subject_ref;
  }
  return assertion.object_ref ?? assertion.subject_ref;
}

function sourceDetail(assertion: Assertion): string {
  const parts = [assertion.source];
  if (assertion.source_ref) {
    parts.push(`via ${assertion.source_ref}`);
  }
  parts.push(`${Math.round(assertion.confidence * 100)}% confidence`);
  return parts.join(" · ");
}

function displayNode(
  assertion: Assertion,
  nodeRef: string,
  node: LineageNode | undefined,
): LineageNode {
  const base =
    node ??
    ({
      tdoc_number: nodeRef,
      title: "Unknown node",
      decision: assertion.value,
      state_source: assertion.source,
      agenda_item: null,
      type: null,
      is_tracked: false,
      is_provisional: false,
      first_seen_at: null,
      notes_count: 0,
      node_status: null,
      is_hidden: false,
    } satisfies LineageNode);
  if (assertion.predicate !== "decision") {
    return base;
  }
  return { ...base, decision: assertion.value ?? "No decision" };
}

function ConflictNode({
  assertion,
  node,
  onSelect,
}: {
  assertion: Assertion;
  node: LineageNode | undefined;
  onSelect: (tdoc: string) => void;
}) {
  const nodeRef = competingNode(assertion);
  const shown = displayNode(assertion, nodeRef, node);
  return (
    <li className={`conflict-node${assertion.muted ? " muted" : ""}`}>
      <span className="source-pill">{assertion.source}</span>
      <svg
        className="conflict-node-svg"
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        viewBox={`0 0 ${NODE_WIDTH} ${NODE_HEIGHT}`}
      >
        <LineageNodeGlyph
          node={shown}
          ariaLabel={`Open ${nodeRef} from ${assertion.source}`}
          onClick={() => onSelect(nodeRef)}
        />
      </svg>
      <small>{sourceDetail(assertion)}</small>
      {assertion.object_ref &&
      assertion.object_ref !== assertion.subject_ref ? (
        <small>asserted by {assertion.subject_ref}</small>
      ) : null}
    </li>
  );
}

export function ConflictsView({
  conflicts,
  lineage,
  onResolve,
  onSelect,
}: Props) {
  if (conflicts.length === 0) {
    return (
      <div className="empty-state">
        <h3>No open conflicts</h3>
        <p>HTML, user, and hint assertions currently agree.</p>
      </div>
    );
  }
  const nodes = new Map(
    lineage.nodes
      .filter((node) => node.node_kind !== "draft")
      .map((node) => [node.tdoc_number, node]),
  );
  return (
    <ul className="conflict-list" aria-label="Open conflicts">
      {conflicts.map((conflict) => (
        <li key={conflict.id}>
          <div className="conflict-heading">
            <span className={`badge predicate-${conflict.predicate}`}>
              {conflict.predicate}
            </span>
            <strong>{conflict.subject_ref}</strong>
            <span className="created-at">{conflict.created_at}</span>
          </div>
          {conflict.assertions.length > 0 ? (
            <>
              <p className="conflict-instructions">
                The competing nodes are shown side by side. Click either node
                to inspect it, then choose a resolution.
              </p>
              <ul
                className="conflict-choices"
                aria-label={`Competing nodes for ${conflict.subject_ref}`}
              >
                {conflict.assertions.map((assertion) => (
                  <ConflictNode
                    key={assertion.id}
                    assertion={assertion}
                    node={nodes.get(competingNode(assertion))}
                    onSelect={onSelect}
                  />
                ))}
              </ul>
            </>
          ) : (
            <p className="conflict-instructions">
              {conflict.subject_ref} has an unresolved lineage issue. Open the
              node to repair it.
            </p>
          )}
          <div className="conflict-actions">
            <button
              type="button"
              onClick={() => onResolve(conflict.id, "accept_html")}
            >
              Accept HTML
            </button>
            <button
              type="button"
              onClick={() => onSelect(conflict.subject_ref)}
            >
              Inspect {conflict.subject_ref}
            </button>
            <button
              type="button"
              onClick={() => onResolve(conflict.id, "keep_mine")}
            >
              Keep mine
            </button>
            <button
              type="button"
              onClick={() => onResolve(conflict.id, "repair")}
            >
              Repair
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
