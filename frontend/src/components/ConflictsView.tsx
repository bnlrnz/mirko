import type { Conflict, ConflictResolution } from "../types";

interface Props {
  conflicts: Conflict[];
  onResolve: (id: number, resolution: ConflictResolution) => void;
  onSelect: (tdoc: string) => void;
}

export function ConflictsView({ conflicts, onResolve, onSelect }: Props) {
  if (conflicts.length === 0) {
    return (
      <div className="empty-state">
        <h3>No open conflicts</h3>
        <p>HTML, user, and hint assertions currently agree.</p>
      </div>
    );
  }
  return (
    <ul className="conflict-list" aria-label="Open conflicts">
      {conflicts.map((conflict) => (
        <li key={conflict.id}>
          <div className="conflict-heading">
            <span className={`badge predicate-${conflict.predicate}`}>
              {conflict.predicate}
            </span>
            <button
              type="button"
              className="link-button"
              onClick={() => onSelect(conflict.subject_ref)}
            >
              {conflict.subject_ref}
            </button>
            <span className="created-at">{conflict.created_at}</span>
          </div>
          <ul className="conflict-assertions">
            {conflict.assertions.map((assertion) => (
              <li
                key={assertion.id}
                className={assertion.muted ? "muted" : ""}
              >
                <code>{assertion.source}</code>
                <span>
                  {assertion.object_ref ?? assertion.value ?? "—"}
                </span>
                <small>
                  {Math.round(assertion.confidence * 100)}% ·{" "}
                  {assertion.verified ? "verified" : "unverified"}
                </small>
              </li>
            ))}
          </ul>
          <div className="conflict-actions">
            <button
              type="button"
              onClick={() => onResolve(conflict.id, "accept_html")}
            >
              Accept HTML
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
