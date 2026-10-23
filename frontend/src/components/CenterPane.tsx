import { useState } from "react";

import { MAX_LINEAGE_LABEL } from "../lineageTabs";
import type {
  Conflict,
  ConflictResolution,
  Filters,
  Lineage,
  LineageTab,
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
  | "timeline"
  | "conflicts"
  | "notifications"
  | "log"
  | `lineage:${string}`;

export function lineageTabKey(id: string): CenterTab {
  return `lineage:${id}`;
}

interface Props {
  tab: CenterTab;
  onTab: (tab: CenterTab) => void;
  lineageTabs: LineageTab[];
  onAddLineageTab: () => void;
  onCloseLineageTab: (id: string) => void;
  onRenameLineageTab: (id: string, label: string) => void;
  onLineageFilters: (id: string, filters: Filters) => void;
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
  onSelect: (tdoc: string, artifactId?: number) => void;
  onSelectDraft: (artifactId: number) => void;
  focusRequest: { tdoc: string; nonce: number } | null;
  newArtifactPaths: ReadonlySet<string>;
  newArtifactTdocs: ReadonlySet<string>;
  onResolve: (id: number, resolution: ConflictResolution) => void;
  onTrack: (tdoc: string, tracked: boolean) => void;
}

const TABS: { id: CenterTab; label: string }[] = [
  { id: "timeline", label: "Timeline" },
  { id: "conflicts", label: "Conflicts" },
  { id: "notifications", label: "Notifications" },
  { id: "log", label: "Log" },
];

export function CenterPane({
  tab,
  onTab,
  lineageTabs,
  onAddLineageTab,
  onCloseLineageTab,
  onRenameLineageTab,
  onLineageFilters,
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
  onSelect,
  onSelectDraft,
  focusRequest,
  newArtifactPaths,
  newArtifactTdocs,
  onResolve,
  onTrack,
}: Props) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const activeLineageTab =
    lineageTabs.find((item) => lineageTabKey(item.id) === tab) ??
    (tab.startsWith("lineage:") ? lineageTabs[0] : undefined);

  const beginRename = (item: LineageTab) => {
    setRenamingId(item.id);
    setRenameValue(item.label);
  };

  const finishRename = (item: LineageTab, save: boolean) => {
    if (save) {
      const label = renameValue.trim();
      if (label && label !== item.label) {
        onRenameLineageTab(item.id, label);
      }
    }
    setRenamingId(null);
  };

  return (
    <section className="center-pane">
      <nav className="tabs" role="tablist" aria-label="Center views">
        {lineageTabs.map((item) => {
          const active = activeLineageTab?.id === item.id;
          return (
            <span
              key={item.id}
              className={`lineage-tab${active ? " active" : ""}`}
            >
              {renamingId === item.id ? (
                <input
                  className="tab-rename"
                  aria-label={`Rename ${item.label}`}
                  value={renameValue}
                  maxLength={MAX_LINEAGE_LABEL}
                  autoFocus
                  onChange={(event) => setRenameValue(event.target.value)}
                  onBlur={() => finishRename(item, true)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      finishRename(item, true);
                    } else if (event.key === "Escape") {
                      setRenamingId(null);
                    }
                  }}
                />
              ) : (
                <button
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={active ? "active" : ""}
                  title="Double-click to rename"
                  onClick={() => onTab(lineageTabKey(item.id))}
                  onDoubleClick={() => beginRename(item)}
                >
                  {item.label}
                </button>
              )}
              {renamingId !== item.id ? (
                <button
                  type="button"
                  className="tab-edit"
                  aria-label={`Rename ${item.label}`}
                  title={`Rename ${item.label}`}
                  onClick={() => beginRename(item)}
                >
                  ✎
                </button>
              ) : null}
              {lineageTabs.length > 1 ? (
                <button
                  type="button"
                  className="tab-close"
                  aria-label={`Close ${item.label}`}
                  title={`Close ${item.label}`}
                  onClick={() => onCloseLineageTab(item.id)}
                >
                  ×
                </button>
              ) : null}
            </span>
          );
        })}
        <button
          type="button"
          className="tab-add"
          aria-label="New lineage tab"
          title="New lineage view"
          onClick={onAddLineageTab}
        >
          +
        </button>
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
        {activeLineageTab ? (
          <LineageView
            lineage={lineage}
            selected={selected}
            selectedDraft={selectedDraft}
            filters={activeLineageTab.filters}
            onFilters={(next) =>
              onLineageFilters(activeLineageTab.id, next)
            }
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
