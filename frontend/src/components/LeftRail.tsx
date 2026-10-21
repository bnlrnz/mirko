import type { NotificationItem, TdocSummary } from "../types";

interface Props {
  tdocs: TdocSummary[];
  selected: string | null;
  notifications: NotificationItem[];
  seenNotifications: ReadonlySet<string>;
  onSelect: (tdoc: string) => void;
  onFocusTdoc: (tdoc: string) => void;
  onTrack: (tdoc: string, tracked: boolean) => void;
}

function markerLabel(item: NotificationItem): string {
  const text = `${item.title} ${item.detail ?? ""}`.toLowerCase();
  if (item.kind === "artifact") {
    return text.includes("draft") ? "draft" : "file";
  }
  if (item.kind === "lineage") {
    if (text.includes("merged_into")) {
      return "merge";
    }
    if (text.includes("revision_of")) {
      return "revision";
    }
    return "link";
  }
  if (item.kind === "decision") {
    return "state";
  }
  return item.kind;
}

export function LeftRail({
  tdocs,
  selected,
  notifications,
  seenNotifications,
  onSelect,
  onFocusTdoc,
  onTrack,
}: Props) {
  return (
    <aside className="left-rail" aria-label="Tracked TDoc favourites">
      <section className="tdoc-list">
        <h2>
          Favourites <span>{tdocs.length}</span>
        </h2>
        {tdocs.length === 0 ? (
          <p className="empty">
            Track a TDoc to keep it in this list.
          </p>
        ) : (
          <ul>
            {tdocs.map((row) => {
              const related = notifications.filter(
                (item) =>
                  !seenNotifications.has(item.ref) &&
                  item.tdocs.includes(row.tdoc_number),
              );
              const marker = related[0] ? markerLabel(related[0]) : null;
              return (
                <li key={row.tdoc_number} className="tdoc-row favourite-row">
                  <button
                    type="button"
                    className={`tdoc-select${
                      selected === row.tdoc_number ? " selected" : ""
                    }`}
                    aria-current={selected === row.tdoc_number || undefined}
                    onClick={() => onSelect(row.tdoc_number)}
                    onDoubleClick={() => onFocusTdoc(row.tdoc_number)}
                  >
                    <span className="tdoc-number">{row.tdoc_number}</span>
                    <span className="tdoc-title">
                      {row.title ?? row.topic}
                    </span>
                    {marker ? (
                      <span
                        className="favorite-update"
                        title={related.map((item) => item.title).join("\n")}
                      >
                        {marker}
                        {related.length > 1 ? ` ${related.length}` : ""}
                      </span>
                    ) : null}
                    {row.is_provisional ? (
                      <span className="favorite-flag">new</span>
                    ) : null}
                    {row.has_conflict ? (
                      <span className="favorite-flag conflict">!</span>
                    ) : null}
                  </button>
                  <button
                    type="button"
                    className={`track-toggle${row.is_tracked ? " tracked" : ""}`}
                    aria-label={`${row.is_tracked ? "Untrack" : "Track"} ${
                      row.tdoc_number
                    }`}
                    aria-pressed={row.is_tracked}
                    title={row.is_tracked ? "Untrack TDoc" : "Track TDoc"}
                    onClick={() => onTrack(row.tdoc_number, !row.is_tracked)}
                  >
                    {row.is_tracked ? "★" : "☆"}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </aside>
  );
}
