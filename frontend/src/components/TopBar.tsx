import type { Meeting, SyncStatus } from "../types";

interface Props {
  meeting: Meeting | null;
  sync: SyncStatus | null;
  busy: boolean;
  exportPath: string | null;
  onSync: () => void;
  onExport: () => void;
  onFinalize: () => void;
  onSettings: () => void;
}

function freshness(value: string | null | undefined): string {
  if (!value) {
    return "never";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString();
}

export function TopBar({
  meeting,
  sync,
  busy,
  exportPath,
  onSync,
  onExport,
  onFinalize,
  onSettings,
}: Props) {
  return (
    <header className="top-bar">
      <div className="meeting-title">
        <strong>Mirko</strong>
        <span>{meeting?.title ?? "Loading meeting…"}</span>
        {meeting ? <code>{meeting.id}</code> : null}
      </div>
      <div className="top-actions">
        <button type="button" onClick={onExport}>
          Export
        </button>
        <button type="button" onClick={onFinalize} disabled={busy}>
          Finalize
        </button>
        <button type="button" onClick={onSettings}>
          Settings
        </button>
        {exportPath ? (
          <a className="export-link" href={`/${exportPath}`}>
            latest export
          </a>
        ) : null}
        <div className={`sync-chip health-${sync?.health ?? "unknown"}`}>
          <span className="sync-dot" aria-hidden="true" />
          <span title={sync?.endpoint ?? ""}>
            {sync?.endpoint ?? "No endpoint"}
          </span>
          <span>every {sync?.interval_s ?? "–"}s</span>
          <span>last {freshness(sync?.last_success_at)}</span>
          {sync?.stale ? <strong>stale</strong> : null}
        </div>
        <button
          type="button"
          className="primary"
          onClick={onSync}
          disabled={busy}
        >
          {busy ? "Syncing…" : "Sync Now"}
        </button>
      </div>
    </header>
  );
}
