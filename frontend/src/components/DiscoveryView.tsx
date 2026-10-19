import type { DiscoveryItem } from "../types";

interface Props {
  items: DiscoveryItem[];
  onSelect: (tdoc: string) => void;
  onPromote?: (item: DiscoveryItem) => void;
  emptyTitle?: string;
  emptyBody?: string;
}

export function DiscoveryView({
  items,
  onSelect,
  onPromote,
  emptyTitle = "Nothing to review",
  emptyBody = "Discovery collects provisional numbers, filename hints, and agenda-only mail.",
}: Props) {
  if (items.length === 0) {
    return (
      <div className="empty-state">
        <h3>{emptyTitle}</h3>
        <p>{emptyBody}</p>
      </div>
    );
  }
  return (
    <ul className="discovery-list" aria-label="Discovery items">
      {items.map((item) => (
        <li key={`${item.kind}-${item.ref}-${item.title}`}>
          <div className="discovery-heading">
            <span className={`badge kind-${item.kind}`}>{item.kind}</span>
            <strong>{item.title}</strong>
            <span className="confidence">
              {Math.round(item.confidence * 100)}%
            </span>
          </div>
          {item.detail ? <p>{item.detail}</p> : null}
          <div className="discovery-actions">
            {item.agenda_item ? (
              <span className="badge">agenda {item.agenda_item}</span>
            ) : null}
            {item.tdocs.map((tdoc) => (
              <button
                key={tdoc}
                type="button"
                className="link-button"
                onClick={() => onSelect(tdoc)}
              >
                {tdoc}
              </button>
            ))}
            {item.action && onPromote ? (
              <button
                type="button"
                className="primary"
                onClick={() => onPromote(item)}
              >
                {item.action === "track" ? "Track" : "Promote"}
              </button>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
