import type {
  Conflict,
  ConflictResolution,
  Lineage,
  NotificationItem,
  TimelineEvent,
} from "../types";
import { ConflictsView } from "./ConflictsView";
import { LineageView } from "./LineageView";
import { NotificationsView } from "./NotificationsView";
import { TimelineView } from "./TimelineView";

export type CenterTab =
  | "lineage"
  | "timeline"
  | "conflicts"
  | "notifications";

interface Props {
  tab: CenterTab;
  onTab: (tab: CenterTab) => void;
  lineage: Lineage;
  timeline: TimelineEvent[];
  notifications: NotificationItem[];
  conflicts: Conflict[];
  selected: string | null;
  onSelect: (tdoc: string) => void;
  onResolve: (id: number, resolution: ConflictResolution) => void;
  onTrack: (tdoc: string, tracked: boolean) => void;
}

const TABS: { id: CenterTab; label: string }[] = [
  { id: "lineage", label: "Lineage" },
  { id: "timeline", label: "Timeline" },
  { id: "conflicts", label: "Conflicts" },
  { id: "notifications", label: "Notifications" },
];

export function CenterPane({
  tab,
  onTab,
  lineage,
  timeline,
  notifications,
  conflicts,
  selected,
  onSelect,
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
          </button>
        ))}
      </nav>
      <div className="tab-panel" role="tabpanel">
        {tab === "lineage" ? (
          <LineageView
            lineage={lineage}
            selected={selected}
            onSelect={onSelect}
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
      </div>
    </section>
  );
}
