import { useEffect, useRef, useState } from "react";

import type {
  Conflict,
  ConflictResolution,
  DraftDetail,
  MailSummary,
  NodeStatus,
  Note,
  TdocDetail,
} from "../types";
import { MailDialog } from "./MailViewer";
import { NODE_ACTIONS, NodeStatusIcon } from "./NodeVisuals";

interface NoteTarget {
  kind: "tdoc" | "draft";
  ref: string;
}

interface Props {
  detail: TdocDetail | null;
  draft: DraftDetail | null;
  endpoint: string | null;
  conflicts: Conflict[];
  onTrack: (tdoc: string, tracked: boolean) => void;
  onAddNote: (body: string, target: NoteTarget) => void;
  onSetStatus: (status: NodeStatus | null, target: NoteTarget) => void;
  onSetHidden: (hidden: boolean, target: NoteTarget) => void;
  onDeleteNote: (id: number) => void;
  onAddAssertion: (subject: string, predicate: string, object: string) => void;
  onResolveConflict: (id: number, resolution: ConflictResolution) => void;
  onSelect: (tdoc: string) => void;
  onFetch: () => void;
  fetching: boolean;
  seriesPrefix: string;
  highlightArtifactId: number | null;
  onClearArtifactHighlight: () => void;
}

export function artifactUrl(
  endpoint: string | null,
  logicalPath: string,
): string | null {
  if (!endpoint) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(endpoint);
  } catch {
    return null;
  }
  const base = url.pathname.replace(/\/+$/, "");
  const prefix = base.startsWith("/ftp") ? "" : "/ftp";
  const path = logicalPath
    .split("/")
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/");
  const host =
    url.hostname.toLowerCase() === "ftp.3gpp.org"
      ? "www.3gpp.org"
      : url.hostname;
  return `https://${host}${prefix}${base}/${path}`;
}

export function tdocZipUrl(
  endpoint: string | null,
  tdocNumber: string,
): string | null {
  const tdoc = tdocNumber.trim().toUpperCase();
  if (!tdoc) {
    return null;
  }
  return artifactUrl(endpoint, `Docs/${tdoc}.zip`);
}

function value(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}

function ActionSection({
  action,
  target,
  onSetAction,
}: {
  action: NodeStatus | null;
  target: NoteTarget;
  onSetAction: (action: NodeStatus | null, target: NoteTarget) => void;
}) {
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const current =
    NODE_ACTIONS.find((option) => option.value === action) ?? NODE_ACTIONS[0];

  useEffect(() => {
    if (!open) {
      return;
    }
    const close = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <section>
      <div className="section-heading">
        <h3>Action</h3>
        <div className="action-menu" ref={menu}>
          <button
            type="button"
            className="action-trigger"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-label="Action"
            onClick={() => setOpen((value) => !value)}
          >
            {current.icon ? (
              <NodeStatusIcon
                status={current.value}
                className={current.className}
              />
            ) : null}
            <span>{current.label}</span>
            <span className="action-caret" aria-hidden="true">
              ▾
            </span>
          </button>
          {open ? (
            <ul className="action-options" role="listbox" aria-label="Actions">
              {NODE_ACTIONS.map((option) => (
                <li key={option.label}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={option.value === action}
                    onClick={() => {
                      onSetAction(option.value, target);
                      setOpen(false);
                    }}
                  >
                    {option.icon ? (
                      <NodeStatusIcon
                        status={option.value}
                        className={option.className}
                      />
                    ) : (
                      <span className="action-empty-icon" aria-hidden="true" />
                    )}
                    <span>{option.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function VisibilitySection({
  hidden,
  target,
  onSetHidden,
}: {
  hidden: boolean;
  target: NoteTarget;
  onSetHidden: (hidden: boolean, target: NoteTarget) => void;
}) {
  return (
    <section>
      <div className="section-heading">
        <h3>Visibility</h3>
        <button
          type="button"
          aria-pressed={hidden}
          onClick={() => onSetHidden(!hidden, target)}
        >
          {hidden ? "Show node" : "Hide node"}
        </button>
      </div>
    </section>
  );
}

function NoteSection({
  notes,
  target,
  onAddNote,
  onDeleteNote,
}: {
  notes: Note[];
  target: NoteTarget;
  onAddNote: (body: string, target: NoteTarget) => void;
  onDeleteNote: (id: number) => void;
}) {
  const [note, setNote] = useState("");

  return (
    <section>
      <h3>Notes <span className="count">{notes.length}</span></h3>
      {notes.length === 0 ? (
        <p className="empty">No notes yet.</p>
      ) : (
        <ul className="note-list">
          {notes.map((item) => (
            <li key={item.id}>
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
          onAddNote(note.trim(), target);
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
          <button type="submit" className="primary">Add note</button>
        </div>
      </form>
    </section>
  );
}

function MailSection({ emails }: { emails: MailSummary[] }) {
  const [open, setOpen] = useState<MailSummary | null>(null);

  return (
    <section>
      <h3>Mail <span className="count">{emails.length}</span></h3>
      {emails.length === 0 ? (
        <p className="empty">No linked mail.</p>
      ) : (
        <ul className="mail-list">
          {emails.map((mail) => (
            <li key={mail.id}>
              <button
                type="button"
                className="mail-open"
                aria-label={`Open mail: ${mail.subject ?? "(no subject)"}`}
                onClick={() => setOpen(mail)}
              >
                <strong>{mail.subject ?? "(no subject)"}</strong>
                <small>
                  {mail.from_addr ?? "unknown sender"} ·{" "}
                  {mail.date_utc ?? mail.ingested_at}
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open ? (
        <MailDialog mail={open} onClose={() => setOpen(null)} />
      ) : null}
    </section>
  );
}

function DraftDetailPanel({
  draft,
  endpoint,
  onAddNote,
  onSetStatus,
  onSetHidden,
  onDeleteNote,
  onSelect,
}: {
  draft: DraftDetail;
  endpoint: string | null;
  onAddNote: (body: string, target: NoteTarget) => void;
  onSetStatus: (status: NodeStatus | null, target: NoteTarget) => void;
  onSetHidden: (hidden: boolean, target: NoteTarget) => void;
  onDeleteNote: (id: number) => void;
  onSelect: (tdoc: string) => void;
}) {
  const href = artifactUrl(endpoint, draft.logical_path);
  return (
    <aside
      className="detail-panel"
      aria-label={`Detail for draft ${draft.title}`}
    >
      <header className="detail-header">
        <div>
          <h2>{draft.title}</h2>
          <p>Working draft for {draft.tdoc_number}</p>
        </div>
        <button type="button" onClick={() => onSelect(draft.tdoc_number)}>
          Open parent TDoc
        </button>
      </header>

      <div className="detail-badges">
        <span className="badge kind-working_draft">working draft</span>
        <span className="badge">{draft.status}</span>
        {draft.is_ephemeral ? <span className="badge">ephemeral</span> : null}
      </div>

      <dl className="metadata">
        <dt>Parent</dt>
        <dd>
          <button
            type="button"
            className="link-button"
            onClick={() => onSelect(draft.tdoc_number)}
          >
            {draft.tdoc_number}
          </button>
        </dd>
        <dt>Parent title</dt>
        <dd>{value(draft.parent_title)}</dd>
        <dt>Agenda</dt>
        <dd>{value(draft.agenda_item)}</dd>
        <dt>FTP status</dt>
        <dd>{value(draft.status)}</dd>
        <dt>FTP uploaded</dt>
        <dd>{value(draft.remote_mtime)}</dd>
        <dt>Size</dt>
        <dd>{draft.remote_size ? `${draft.remote_size} B` : "—"}</dd>
        <dt>Path</dt>
        <dd>{draft.logical_path}</dd>
      </dl>

      <section>
        <h3>File</h3>
        <ul className="artifact-list">
          <li>
            {href ? (
              <a href={href} target="_blank" rel="noreferrer">
                {draft.title}
              </a>
            ) : (
              <span>{draft.title}</span>
            )}
            <small>
              {draft.blob_hash === null ? "not fetched" : "cached"}
              {draft.remote_mtime
                ? ` · FTP uploaded ${draft.remote_mtime}`
                : ""}
            </small>
          </li>
        </ul>
      </section>

      <ActionSection
        key={`draft-action:${draft.id}`}
        action={draft.node_status}
        target={{ kind: "draft", ref: String(draft.id) }}
        onSetAction={onSetStatus}
      />

      <VisibilitySection
        key={`draft-visibility:${draft.id}`}
        hidden={draft.is_hidden}
        target={{ kind: "draft", ref: String(draft.id) }}
        onSetHidden={onSetHidden}
      />

      <NoteSection
        key={`draft:${draft.id}`}
        notes={draft.notes}
        target={{ kind: "draft", ref: String(draft.id) }}
        onAddNote={onAddNote}
        onDeleteNote={onDeleteNote}
      />
    </aside>
  );
}

export function DetailPanel({
  detail,
  draft,
  endpoint,
  conflicts,
  onTrack,
  onAddNote,
  onSetStatus,
  onSetHidden,
  onDeleteNote,
  onAddAssertion,
  onResolveConflict,
  onSelect,
  onFetch,
  fetching,
  seriesPrefix,
  highlightArtifactId,
  onClearArtifactHighlight,
}: Props) {
  const [predicate, setPredicate] = useState("revision_of");
  const [linkSuffix, setLinkSuffix] = useState("");
  const linkTarget = `${seriesPrefix}${linkSuffix}`;

  const highlightedArtifactVisible =
    highlightArtifactId !== null &&
    (detail?.artifacts.some(
      (artifact) => artifact.id === highlightArtifactId,
    ) ??
      false);

  useEffect(() => {
    if (!highlightedArtifactVisible) {
      return;
    }
    const timer = window.setTimeout(onClearArtifactHighlight, 2000);
    return () => window.clearTimeout(timer);
  }, [
    highlightArtifactId,
    highlightedArtifactVisible,
    onClearArtifactHighlight,
  ]);

  if (draft) {
    return (
      <DraftDetailPanel
        draft={draft}
        endpoint={endpoint}
        onAddNote={onAddNote}
        onSetStatus={onSetStatus}
        onSetHidden={onSetHidden}
        onDeleteNote={onDeleteNote}
        onSelect={onSelect}
      />
    );
  }

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

  const artifacts = detail.artifacts;
  const zipHref = tdocZipUrl(endpoint, detail.tdoc_number);
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
        <h3>TDoc ZIP</h3>
        <ul className="artifact-list">
          <li>
            <span className="badge">official file</span>
            {zipHref ? (
              <a href={zipHref} target="_blank" rel="noreferrer">
                {detail.tdoc_number}.zip
              </a>
            ) : (
              <span>{detail.tdoc_number}.zip</span>
            )}
            <small>Docs/{detail.tdoc_number}.zip</small>
          </li>
        </ul>
      </section>

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
            {artifacts.map((artifact) => {
              const href = artifactUrl(endpoint, artifact.logical_path);
              const name = artifact.filename ?? artifact.logical_path;
              return (
                <li key={artifact.id}>
                  <span className={`badge kind-${artifact.kind}`}>
                    {artifact.kind}
                  </span>
                  {href ? (
                    <a
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      className={
                        artifact.id === highlightArtifactId
                          ? "artifact-highlight"
                          : undefined
                      }
                    >
                      {name}
                    </a>
                  ) : (
                    <span>{name}</span>
                  )}
                  <small>
                    {artifact.status === "remote"
                      ? "not fetched"
                      : artifact.status}
                    {artifact.is_ephemeral ? " · ephemeral" : ""}
                    {artifact.remote_size
                      ? ` · ${artifact.remote_size} B`
                      : ""}
                    {artifact.remote_mtime
                      ? ` · FTP uploaded ${artifact.remote_mtime}`
                      : ""}
                  </small>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <MailSection
        key={`mail:${detail.tdoc_number}`}
        emails={detail.emails}
      />

      <ActionSection
        key={`tdoc-action:${detail.tdoc_number}`}
        action={detail.node_status}
        target={{ kind: "tdoc", ref: detail.tdoc_number }}
        onSetAction={onSetStatus}
      />

      <VisibilitySection
        key={`tdoc-visibility:${detail.tdoc_number}`}
        hidden={detail.is_hidden}
        target={{ kind: "tdoc", ref: detail.tdoc_number }}
        onSetHidden={onSetHidden}
      />

      <NoteSection
        key={`tdoc:${detail.tdoc_number}`}
        notes={detail.notes}
        target={{ kind: "tdoc", ref: detail.tdoc_number }}
        onAddNote={onAddNote}
        onDeleteNote={onDeleteNote}
      />

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
            if (linkSuffix.length !== 4) {
              return;
            }
            onAddAssertion(detail.tdoc_number, predicate, linkTarget);
            setLinkSuffix("");
          }}
        >
          <label>
            Link
            <select
              aria-label="Link predicate"
              value={predicate}
              onChange={(event) => setPredicate(event.target.value)}
            >
              <option value="revision_of">revised to</option>
              <option value="merged_into">merged into</option>
            </select>
          </label>
          <div className="tdoc-input">
            <span className="tdoc-input-prefix">{seriesPrefix}</span>
            <input
              aria-label="Link target"
              inputMode="numeric"
              maxLength={4}
              placeholder="4999"
              value={linkSuffix}
              onChange={(event) =>
                setLinkSuffix(
                  event.target.value.replace(/\D/g, "").slice(0, 4),
                )
              }
            />
          </div>
          <button type="submit" disabled={linkSuffix.length !== 4}>
            Add link
          </button>
        </form>
      </section>
    </aside>
  );
}
