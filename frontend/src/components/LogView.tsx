import type { UserAction } from "../types";

interface Props {
  items: UserAction[];
  onSelect: (tdoc: string) => void;
}

function label(action: string): string {
  return action.replaceAll("_", " ");
}

export function LogView({ items, onSelect }: Props) {
  if (items.length === 0) {
    return (
      <div className="empty-state">
        <h3>No user actions yet</h3>
        <p>Tracking changes and notes will appear here.</p>
      </div>
    );
  }
  return (
    <ul className="log-list" aria-label="User action log">
      {items.map((item) => (
        <li key={item.id}>
          <span className="log-action">{label(item.action)}</span>
          {item.target_ref ? (
            item.target_kind === "tdoc" ? (
              <button
                type="button"
                className="link-button"
                onClick={() => onSelect(item.target_ref as string)}
              >
                {item.target_ref}
              </button>
            ) : (
              <span>{item.target_ref}</span>
            )
          ) : null}
          {item.detail ? <p>{item.detail}</p> : null}
          {item.created_at ? (
            <time dateTime={item.created_at}>{item.created_at}</time>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
