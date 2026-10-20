import type {
  Conflict,
  ConflictResolution,
  Lineage,
  NotificationItem,
  TimelineEvent,
  UserAction,
} from "../types";
import { ConflictsView } from "./ConflictsView";
import { LineageView } from "./LineageView";
import { LogView } from "./LogView";
import { NotificationsView } from "./NotificationsView";
import { TimelineView } from "./TimelineView";

export type CenterTab =
  | "lineage"
  | "timeline"
  | "conflicts"
  | "notifications"
  | "log";

interface Props {
  tab: CenterTab;
  onTab: (tab: CenterTab) => void;
  lineage: Lineage;
  timeline: TimelineEvent[];
  notifications: NotificationItem[];
  log: UserAction[];
  conflicts: Conflict[];
  selected: string | null;
  includeDrafts: boolean;
  onSelect: (tdoc: string, artifactId?: number) => void;
  focusRequest: { tdoc: string; nonce: number } | null;
  onResolve: (id: number, resolution: ConflictResolution) => void;
  onTrack: (tdoc: string, tracked: boolean) => void;
}

const TABS: { id: CenterTab; label: string }[] = [
  { id: "lineage", label: "Lineage" },
  { id: "timeline", label: "Timeline" },
  { id: "conflicts", label: "Conflicts" },
  { id: "notifications", label: "Notifications" },
  { id: "log", label: "Log" },
];

export function CenterPane({
  tab,
  onTab,
  lineage,
  timeline,
  notifications,
  log,
  conflicts,
  selected,
  includeDrafts,
  onSelect,
  focusRequest,
  onResolve,
  onTrack,
}: Props) {
  return (
    <section className="center-pane">
      <nav className="tabs" role="tablist" aria-label="Center views">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => onTab(item.id)}
          >
            {item.label}
            {item.id === "conflicts" && conflicts.length > 0 ? (
              <span className="count">{conflicts.length}</span>
            ) : null}
            {item.id === "notifications" && notifications.length > 0 ? (
              <span className="count">{notifications.length}</span>
            ) : null}
            {item.id === "log" && log.length > 0 ? (
              <span className="count">{log.length}</span>
            ) : null}
          </button>
        ))}
      </nav>
      <div className="tab-panel" role="tabpanel">
        {tab === "lineage" ? (
          <LineageView
            lineage={lineage}
            selected={selected}
            includeDrafts={includeDrafts}
            onSelect={onSelect}
            focusRequest={focusRequest}
            onTrack={onTrack}
          />
        ) : null}
        {tab === "timeline" ? (
          <TimelineView events={timeline} selected={selected} />
        ) : null}
        {tab === "conflicts" ? (
          <ConflictsView
            conflicts={conflicts}
            onResolve={onResolve}
            onSelect={onSelect}
          />
        ) : null}
        {tab === "notifications" ? (
          <NotificationsView
            items={notifications}
            onSelect={onSelect}
            onTrack={(tdoc) => onTrack(tdoc, true)}
          />
        ) : null}
        {tab === "log" ? <LogView items={log} onSelect={onSelect} /> : null}
      </div>
    </section>
  );
}
