import type { Filters, Meeting, SyncStatus } from "../types";

interface Props {
  meeting: Meeting | null;
  filters: Filters;
  sync: SyncStatus | null;
  busy: boolean;
  exportPath: string | null;
  onFilters: (filters: Filters) => void;
  onSync: () => void;
  onExport: () => void;
  onFinalize: () => void;
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
  filters,
  sync,
  busy,
  exportPath,
  onFilters,
  onSync,
  onExport,
  onFinalize,
}: Props) {
  return (
    <header className="top-bar">
      <div className="meeting-title">
        <strong>Mirko</strong>
        <span>{meeting?.title ?? "Loading meeting…"}</span>
        {meeting ? <code>{meeting.id}</code> : null}
      </div>
      <input
        className="search"
        type="search"
        aria-label="Search TDocs"
        placeholder="Search TDocs…"
        value={filters.search}
        onChange={(event) =>
          onFilters({ ...filters, search: event.target.value })
        }
      />
      <button
        type="button"
        className="primary"
        onClick={onSync}
        disabled={busy}
      >
        {busy ? "Syncing…" : "Sync Now"}
      </button>
      <button type="button" onClick={onExport}>
        Export
      </button>
      <button type="button" onClick={onFinalize} disabled={busy}>
        Finalize
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
    </header>
  );
}
