import type {
  Conflict,
  ConflictResolution,
  Filters,
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
  unreadNotificationCount: number;
  seenNotifications: ReadonlySet<string>;
  onNotificationSeen: (refs: Iterable<string>) => void;
  log: UserAction[];
  conflicts: Conflict[];
  selected: string | null;
  selectedDraft: number | null;
  filters: Filters;
  favoriteOrder: readonly string[];
  onFilters: (filters: Filters) => void;
  onSelect: (tdoc: string, artifactId?: number) => void;
  onSelectDraft: (artifactId: number) => void;
  focusRequest: { tdoc: string; nonce: number } | null;
  newArtifactPaths: ReadonlySet<string>;
  newArtifactTdocs: ReadonlySet<string>;
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
  unreadNotificationCount,
  seenNotifications,
  onNotificationSeen,
  log,
  conflicts,
  selected,
  selectedDraft,
  filters,
  favoriteOrder,
  onFilters,
  onSelect,
  onSelectDraft,
  focusRequest,
  newArtifactPaths,
  newArtifactTdocs,
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
            {item.id === "notifications" && unreadNotificationCount > 0 ? (
              <span className="count">{unreadNotificationCount}</span>
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
            selectedDraft={selectedDraft}
            filters={filters}
            onFilters={onFilters}
            nodeOrder={favoriteOrder}
            onSelect={onSelect}
            onSelectDraft={onSelectDraft}
            focusRequest={focusRequest}
            newArtifactPaths={newArtifactPaths}
            newArtifactTdocs={newArtifactTdocs}
            onTrack={onTrack}
          />
        ) : null}
        {tab === "timeline" ? (
          <TimelineView events={timeline} selected={selected} />
        ) : null}
        {tab === "conflicts" ? (
          <ConflictsView
            conflicts={conflicts}
            lineage={lineage}
            onResolve={onResolve}
            onSelect={onSelect}
          />
        ) : null}
        {tab === "notifications" ? (
          <NotificationsView
            items={notifications}
            seen={seenNotifications}
            onSeen={onNotificationSeen}
            onSelect={onSelect}
            onTrack={(tdoc) => onTrack(tdoc, true)}
          />
        ) : null}
        {tab === "log" ? <LogView items={log} onSelect={onSelect} /> : null}
      </div>
    </section>
  );
}
