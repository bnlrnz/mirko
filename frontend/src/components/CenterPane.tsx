import type {
  Conflict,
  ConflictResolution,
  DiscoveryItem,
  Lineage,
  TimelineEvent,
} from "../types";
import { ConflictsView } from "./ConflictsView";
import { DiscoveryView } from "./DiscoveryView";
import { LineageView } from "./LineageView";
import { TimelineView } from "./TimelineView";

export type CenterTab =
  | "lineage"
  | "timeline"
  | "conflicts"
  | "discovery"
  | "new";

interface Props {
  tab: CenterTab;
  onTab: (tab: CenterTab) => void;
  lineage: Lineage;
  timeline: TimelineEvent[];
  discovery: DiscoveryItem[];
  conflicts: Conflict[];
  selected: string | null;
  onSelect: (tdoc: string) => void;
  onResolve: (id: number, resolution: ConflictResolution) => void;
  onPromote: (item: DiscoveryItem) => void;
}

const TABS: { id: CenterTab; label: string }[] = [
  { id: "lineage", label: "Lineage" },
  { id: "timeline", label: "Timeline" },
  { id: "conflicts", label: "Conflicts" },
  { id: "discovery", label: "Discovery" },
  { id: "new", label: "New numbers" },
];

export function CenterPane({
  tab,
  onTab,
  lineage,
  timeline,
  discovery,
  conflicts,
  selected,
  onSelect,
  onResolve,
  onPromote,
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
            {item.id === "new" ? (
              <span className="count">
                {discovery.filter((row) => row.kind === "provisional_tdoc").length}
              </span>
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
        {tab === "discovery" ? (
          <DiscoveryView
            items={discovery}
            onSelect={onSelect}
            onPromote={onPromote}
          />
        ) : null}
        {tab === "new" ? (
          <DiscoveryView
            items={discovery.filter((row) => row.kind === "provisional_tdoc")}
            onSelect={onSelect}
            onPromote={onPromote}
            emptyTitle="No provisional numbers"
            emptyBody="Working drafts whose numbers are not in the official agenda appear here."
          />
        ) : null}
      </div>
    </section>
  );
}
