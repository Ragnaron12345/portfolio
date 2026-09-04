import type { ExecutionEvent } from "../types";
import { formatDuration, formatTime, humanize } from "./Ui";

function stateFor(event: ExecutionEvent): string {
  const value = event.status.toLowerCase();
  if (value.includes("fail")) return "failed";
  if (value.includes("run") || value.includes("progress")) return "running";
  if (value.includes("wait") || value.includes("review")) return "waiting";
  if (value.includes("complete") || value.includes("success") || value === "done") return "completed";
  return "pending";
}

export function Timeline({ events, compact = false }: { events: ExecutionEvent[]; compact?: boolean }) {
  if (!events.length) return <p className="muted-copy">Timeline events have not been recorded yet.</p>;
  return (
    <ol className={`timeline${compact ? " timeline--compact" : ""}`}>
      {events.map((event) => {
        const state = stateFor(event);
        return (
          <li className={`timeline__item timeline__item--${state}`} key={event.id}>
            <span className="timeline__node" aria-label={humanize(state)}>{state === "completed" ? "✓" : state === "failed" ? "×" : ""}</span>
            <div className="timeline__content">
              <strong>{event.label || humanize(event.stage)}</strong>
              <span>{event.occurred_at ? formatTime(event.occurred_at) : humanize(event.status)}</span>
              {event.message ? <p>{event.message}</p> : null}
            </div>
            {event.duration_ms !== undefined ? <span className="timeline__duration">{formatDuration(event.duration_ms)}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
