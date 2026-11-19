import type { CSSProperties } from "react";

import { formatTime } from "../format";
import type { ExportOptions, Meeting, SyncStatus } from "../types";
import { ExportMenu } from "./ExportMenu";

interface Props {
  meeting: Meeting | null;
  sync: SyncStatus | null;
  busy: boolean;
  agendaItems: string[];
  onSync: () => void;
  onExport: (options: ExportOptions) => void;
  onSettings: () => void;
  notificationPermission: NotificationPermission | "unsupported";
  onEnableNotifications: () => void;
}

function freshness(value: string | null | undefined): string {
  if (!value) {
    return "never";
  }
  return formatTime(value);
}

function barColors(color: string): CSSProperties {
  const match = /^#([0-9a-f]{6})$/i.exec(color);
  if (!match) {
    return {};
  }
  const value = Number.parseInt(match[1], 16);
  const red = (value >> 16) & 0xff;
  const green = (value >> 8) & 0xff;
  const blue = value & 0xff;
  const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;
  const light = luminance > 0.6;
  return {
    background: `linear-gradient(90deg, ${color} 0%, #ffffff 100%)`,
    "--topbar-text": light ? "#1b2430" : "#f8fafc",
    "--topbar-muted": light ? "#475467" : "rgba(248, 250, 252, 0.78)",
    "--topbar-accent": light ? "#2457c5" : "#f8fafc",
  } as CSSProperties;
}

export function TopBar({
  meeting,
  sync,
  busy,
  agendaItems,
  onSync,
  onExport,
  onSettings,
  notificationPermission,
  onEnableNotifications,
}: Props) {
  return (
    <header className="top-bar" style={meeting ? barColors(meeting.bar_color) : undefined}>
      <div className="meeting-title">
        <strong>Mirko</strong>
        <span>{meeting?.title ?? "Loading meeting…"}</span>
        {meeting ? <code>{meeting.id}</code> : null}
      </div>
      <div className="top-actions">
        <ExportMenu agendaItems={agendaItems} busy={busy} onExport={onExport} />
        <button type="button" onClick={onSettings}>
          Settings
        </button>
        {notificationPermission === "default" ? (
          <button type="button" onClick={onEnableNotifications}>
            Enable alerts
          </button>
        ) : null}
        {notificationPermission === "granted" ? (
          <span
            className="alert-chip"
            title="Desktop notifications are enabled"
          >
            alerts on
          </span>
        ) : null}
        {notificationPermission === "denied" ? (
          <span
            className="alert-chip blocked"
            title="Desktop notifications are blocked in the browser"
          >
            alerts blocked
          </span>
        ) : null}
        <div className={`sync-chip health-${sync?.health ?? "unknown"}`}>
          <span className="sync-dot" aria-hidden="true" />
          <span title={sync?.endpoint ?? ""}>
            {sync?.endpoint ?? "No endpoint"}
          </span>
          <span
            title={
              sync?.mode === "idle"
                ? "Idle outside configured meeting days/hours"
                : "Meeting-day polling interval"
            }
          >
            every {sync?.interval_s ?? "–"}s
            {sync?.mode === "idle" ? " (idle)" : ""}
          </span>
          <span title={sync?.last_error ?? ""}>
            checked{" "}
            {freshness(sync?.last_attempt_at ?? sync?.last_success_at)}
          </span>
          {sync?.next_due_at ? (
            <span>next {freshness(sync.next_due_at)}</span>
          ) : null}
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
