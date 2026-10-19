import type { TimelineEvent } from "../types";

interface Props {
  events: TimelineEvent[];
  selected: string | null;
}

function when(value: string | null): string {
  if (!value) {
    return "unknown time";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function TimelineView({ events, selected }: Props) {
  if (!selected) {
    return (
      <div className="empty-state">
        <h3>Select a TDoc</h3>
        <p>The timeline shows its drafts, mail, state changes, and notes.</p>
      </div>
    );
  }
  if (events.length === 0) {
    return (
      <div className="empty-state">
        <h3>No events</h3>
        <p>Nothing has been observed for {selected} yet.</p>
      </div>
    );
  }
  return (
    <ol className="timeline" aria-label={`Timeline for ${selected}`}>
      {events.map((event) => (
        <li
          key={`${event.sequence}-${event.kind}-${event.occurred_at}`}
          className={`timeline-event kind-${event.kind} ${
            event.ephemeral ? "ephemeral" : ""
          }`}
        >
          <span className="timeline-marker" aria-hidden="true" />
          <div className="timeline-body">
            <div className="timeline-heading">
              <span className="event-kind">{event.kind}</span>
              <time dateTime={event.occurred_at ?? undefined}>
                {when(event.occurred_at)}
              </time>
            </div>
            <strong>{event.title ?? "Untitled event"}</strong>
            {event.detail ? <p>{event.detail}</p> : null}
            <small>
              {event.source ?? "unknown source"}
              {event.ephemeral ? " · ephemeral working draft" : ""}
            </small>
          </div>
        </li>
      ))}
    </ol>
  );
}
