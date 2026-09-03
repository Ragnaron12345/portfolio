import { statusLabel } from "../lib/format";
import type { RunStatus } from "../types";

export function Status({ value }: { value: RunStatus }) {
  return <span className={`status status-${value}`}><i />{statusLabel(value)}</span>;
}
