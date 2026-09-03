import { useState } from "react";
import { Icon } from "./Icon";

export function MetricHelp({ definition, direction }: { definition: string; direction: "higher" | "lower" }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="metric-help">
      <button aria-label="Metric definition" aria-expanded={open} onClick={() => setOpen((value) => !value)} title={`${definition} ${direction} is better.`}>
        <Icon name="info" />
      </button>
      {open ? <span className="metric-popover" role="tooltip">{definition}<strong>{direction} is better</strong></span> : null}
    </span>
  );
}
