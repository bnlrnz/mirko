import type {
  DiscoveryItem,
  Lineage,
  TimelineEvent,
} from "../types";
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
  conflicts: number;
  selected: string | null;
  onSelect: (tdoc: string) => void;
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
            {item.id === "conflicts" && conflicts > 0 ? (
              <span className="count">{conflicts}</span>
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
          <div className="empty-state">
            <h3>{conflicts > 0 ? "Open conflicts" : "No open conflicts"}</h3>
            <p>
              {conflicts > 0
                ? "Select a flagged TDoc to review the competing assertions."
                : "HTML, user, and hint assertions currently agree."}
            </p>
          </div>
        ) : null}
        {tab === "discovery" ? (
          <DiscoveryView items={discovery} onSelect={onSelect} />
        ) : null}
        {tab === "new" ? (
          <DiscoveryView
            items={discovery.filter((row) => row.kind === "provisional_tdoc")}
            onSelect={onSelect}
            emptyTitle="No provisional numbers"
            emptyBody="Working drafts whose numbers are not in the official agenda appear here."
          />
        ) : null}
      </div>
    </section>
  );
}
