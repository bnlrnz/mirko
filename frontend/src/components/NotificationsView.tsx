import type { NotificationItem } from "../types";

interface Props {
  items: NotificationItem[];
  onSelect: (tdoc: string) => void;
  onTrack: (tdoc: string) => void;
}

function when(value: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function NotificationsView({ items, onSelect, onTrack }: Props) {
  if (items.length === 0) {
    return (
      <div className="empty-state">
        <h3>No tracked updates</h3>
        <p>
          New files, state changes, and newly connected nodes for tracked TDocs
          appear here.
        </p>
      </div>
    );
  }

  return (
    <ul className="notification-list" aria-label="Tracked TDoc updates">
      {items.map((item) => (
        <li key={`${item.kind}-${item.ref}`} className={`notification-${item.kind}`}>
          <div className="notification-heading">
            <span className={`badge kind-${item.kind}`}>{item.kind}</span>
            {item.agenda_item ? <span className="badge">{item.agenda_item}</span> : null}
            <small className="created-at">{when(item.created_at)}</small>
          </div>
          <button
            type="button"
            className="notification-title"
            onClick={() => onSelect(item.tdocs[0] ?? item.action_ref ?? "")}
          >
            {item.title}
          </button>
          {item.detail ? <p>{item.detail}</p> : null}
          <div className="notification-actions">
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
            {item.action === "track" && item.action_ref ? (
              <button
                type="button"
                className="primary"
                onClick={() => onTrack(item.action_ref as string)}
              >
                Track {item.action_ref}
              </button>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
