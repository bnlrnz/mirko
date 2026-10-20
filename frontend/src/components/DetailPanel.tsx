import { useState } from "react";

import type { Conflict, ConflictResolution, TdocDetail } from "../types";

interface Props {
  detail: TdocDetail | null;
  includeEphemeral: boolean;
  conflicts: Conflict[];
  onTrack: (tdoc: string, tracked: boolean) => void;
  onAddNote: (body: string, position: string) => void;
  onDeleteNote: (id: number) => void;
  onAddAssertion: (subject: string, predicate: string, object: string) => void;
  onResolveConflict: (id: number, resolution: ConflictResolution) => void;
  onSelect: (tdoc: string) => void;
  onFetch: () => void;
  fetching: boolean;
}

function value(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}

export function DetailPanel({
  detail,
  includeEphemeral,
  conflicts,
  onTrack,
  onAddNote,
  onDeleteNote,
  onAddAssertion,
  onResolveConflict,
  onSelect,
  onFetch,
  fetching,
}: Props) {
  const [note, setNote] = useState("");
  const [position, setPosition] = useState("");
  const [predicate, setPredicate] = useState("revision_of");
  const [linkTarget, setLinkTarget] = useState("");

  if (!detail) {
    return (
      <aside className="detail-panel" aria-label="TDoc detail">
        <div className="empty-state">
          <h3>Select a TDoc</h3>
          <p>Metadata, provenance, artifacts, mail, and notes appear here.</p>
        </div>
      </aside>
    );
  }

  const artifacts = detail.artifacts.filter(
    (artifact) => includeEphemeral || !artifact.is_ephemeral,
  );
  const missing = artifacts.filter(
    (artifact) =>
      artifact.blob_hash === null &&
      (artifact.status === "remote" || artifact.status === "failed"),
  ).length;

  return (
    <aside className="detail-panel" aria-label={`Detail for ${detail.tdoc_number}`}>
      <header className="detail-header">
        <div>
          <h2>{detail.tdoc_number}</h2>
          <p>{detail.title ?? detail.topic ?? "Untitled"}</p>
        </div>
        <button
          type="button"
          className={detail.is_tracked ? "tracked" : ""}
          onClick={() => onTrack(detail.tdoc_number, !detail.is_tracked)}
        >
          {detail.is_tracked ? "★ Tracked" : "☆ Track"}
        </button>
      </header>

      <div className="detail-badges">
        <span className={`badge state-${(detail.decision ?? "unknown").replace(/\s+/g, "-")}`}>
          {detail.decision ?? "unknown"}
        </span>
        {detail.is_provisional ? <span className="badge provisional">provisional</span> : null}
        {detail.state_source ? <span className="badge">via {detail.state_source}</span> : null}
        {detail.has_conflict ? <span className="badge conflict">conflict</span> : null}
      </div>

      <dl className="metadata">
        <dt>Agenda</dt>
        <dd>{value(detail.agenda_item)}</dd>
        <dt>Type</dt>
        <dd>{value(detail.type)}</dd>
        <dt>For</dt>
        <dd>{value(detail.for_action)}</dd>
        <dt>Source</dt>
        <dd>{value(detail.source)}</dd>
        <dt>Avail</dt>
        <dd>{detail.avail === null ? "—" : detail.avail ? "Yes" : "No"}</dd>
        <dt>Treated</dt>
        <dd>{detail.treated === null ? "—" : detail.treated ? "Yes" : "No"}</dd>
        <dt>Release / WI</dt>
        <dd>{[detail.release, detail.wi_code].filter(Boolean).join(" / ") || "—"}</dd>
      </dl>

      {detail.treated_note ? (
        <section>
          <h3>Meeting note</h3>
          <p className="note-body">{detail.treated_note}</p>
        </section>
      ) : null}

      <section>
        <h3>
          Artifacts <span className="count">{artifacts.length}</span>
          {missing > 0 ? (
            <button
              type="button"
              className="fetch-button"
              onClick={onFetch}
              disabled={fetching}
            >
              {fetching ? "Fetching…" : `Fetch missing (${missing})`}
            </button>
          ) : null}
        </h3>
        {artifacts.length === 0 ? (
          <p className="empty">No cached artifacts.</p>
        ) : (
          <ul className="artifact-list">
            {artifacts.map((artifact) => (
              <li key={artifact.id}>
                <span className={`badge kind-${artifact.kind}`}>{artifact.kind}</span>
                <span>{artifact.filename ?? artifact.logical_path}</span>
                <small>
                  {artifact.status === "remote"
                    ? "not fetched"
                    : artifact.status}
                  {artifact.is_ephemeral ? " · ephemeral" : ""}
                  {artifact.remote_size ? ` · ${artifact.remote_size} B` : ""}
                  {artifact.remote_mtime
                    ? ` · FTP uploaded ${artifact.remote_mtime}`
                    : ""}
                </small>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3>Mail <span className="count">{detail.emails.length}</span></h3>
        {detail.emails.length === 0 ? (
          <p className="empty">No linked mail.</p>
        ) : (
          <ul className="mail-list">
            {detail.emails.map((mail) => (
              <li key={mail.id}>
                <strong>{mail.subject ?? "(no subject)"}</strong>
                <small>
                  {mail.from_addr ?? "unknown sender"} ·{" "}
                  {mail.date_utc ?? mail.ingested_at}
                </small>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3>Notes <span className="count">{detail.notes.length}</span></h3>
        {detail.notes.length === 0 ? (
          <p className="empty">No notes yet.</p>
        ) : (
          <ul className="note-list">
            {detail.notes.map((item) => (
              <li key={item.id}>
                {item.position_tag ? (
                  <span className={`badge position-${item.position_tag.toLowerCase()}`}>
                    {item.position_tag}
                  </span>
                ) : null}
                <p className="note-body">{item.body}</p>
                <small>{item.author ?? item.source} · {item.created_at}</small>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => onDeleteNote(item.id)}
                >
                  delete
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="note-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!note.trim()) {
              return;
            }
            onAddNote(note.trim(), position);
            setNote("");
          }}
        >
          <textarea
            aria-label="New note"
            placeholder="Add a note…"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <div className="note-actions">
            <select
              aria-label="Position tag"
              value={position}
              onChange={(event) => setPosition(event.target.value)}
            >
              <option value="">No tag</option>
              <option>Support</option>
              <option>Object</option>
              <option>Clarify</option>
            </select>
            <button type="submit" className="primary">Add note</button>
          </div>
        </form>
      </section>

      {conflicts.length > 0 ? (
        <section>
          <h3>Conflicts <span className="count">{conflicts.length}</span></h3>
          <ul className="conflict-list" aria-label="TDoc conflicts">
            {conflicts.map((conflict) => (
              <li key={conflict.id}>
                <div className="conflict-heading">
                  <span className={`badge predicate-${conflict.predicate}`}>
                    {conflict.predicate}
                  </span>
                </div>
                <div className="conflict-actions">
                  <button
                    type="button"
                    onClick={() =>
                      onResolveConflict(conflict.id, "accept_html")
                    }
                  >
                    Accept HTML
                  </button>
                  <button
                    type="button"
                    onClick={() => onResolveConflict(conflict.id, "keep_mine")}
                  >
                    Keep mine
                  </button>
                  <button
                    type="button"
                    onClick={() => onResolveConflict(conflict.id, "repair")}
                  >
                    Repair
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <h3>Assertions <span className="count">{detail.assertions.length}</span></h3>
        <ul className="assertion-list">
          {detail.assertions.map((assertion) => (
            <li key={assertion.id} className={assertion.active ? "" : "muted"}>
              <code>{assertion.predicate}</code>
              <span>
                {assertion.object_ref ?? assertion.value ?? "—"}
              </span>
              <small>
                {assertion.source} · {Math.round(assertion.confidence * 100)}%
                {assertion.verified ? " · verified" : " · unverified"}
                {assertion.muted ? " · muted" : ""}
              </small>
              {assertion.object_ref ? (
                <button
                  type="button"
                  className="link-button"
                  onClick={() => onSelect(assertion.object_ref as string)}
                >
                  open
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        <form
          className="link-form"
          onSubmit={(event) => {
            event.preventDefault();
            const target = linkTarget.trim().toUpperCase();
            if (!target) {
              return;
            }
            onAddAssertion(detail.tdoc_number, predicate, target);
            setLinkTarget("");
          }}
        >
          <label>
            Link
            <select
              aria-label="Link predicate"
              value={predicate}
              onChange={(event) => setPredicate(event.target.value)}
            >
              <option value="revision_of">revision of</option>
              <option value="merged_into">merged into</option>
              <option value="based_on">based on</option>
            </select>
          </label>
          <input
            aria-label="Link target"
            placeholder="S3-264999"
            value={linkTarget}
            onChange={(event) => setLinkTarget(event.target.value)}
          />
          <button type="submit">Add link</button>
        </form>
      </section>
    </aside>
  );
}
