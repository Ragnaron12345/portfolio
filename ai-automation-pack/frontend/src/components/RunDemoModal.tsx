import { useEffect, useRef, useState } from "react";
import { client } from "../api/client";
import type { DemoScenario, Execution, WorkflowKey } from "../types";
import { Button, ErrorBanner, LoadingState, humanize } from "./Ui";
import { Icon } from "./Icon";

const workflowLabels: Record<WorkflowKey, string> = {
  support: "AI Support Triage",
  invoice: "Invoice Processing",
  incident: "Incident Intelligence",
};

export function RunDemoModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (execution: Execution) => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [loadVersion, setLoadVersion] = useState(0);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError(null);
    void client.getDemoScenarios()
      .then((items) => {
        if (!active) return;
        setScenarios(items);
        setSelected((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null);
      })
      .catch((candidate) => {
        if (active) setError(candidate instanceof Error ? candidate : new Error("Could not load demo scenarios."));
      })
      .finally(() => { if (active) setLoading(false); });
    window.requestAnimationFrame(() => closeRef.current?.focus());
    return () => { active = false; };
  }, [open, loadVersion]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !running) onClose();
      if (event.key !== "Tab") return;
      const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled])") ?? []);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, open, running]);

  if (!open) return null;
  const selectedScenario = scenarios.find((scenario) => scenario.id === selected);

  async function run() {
    if (!selected) return;
    setRunning(true);
    setError(null);
    try {
      onCreated(await client.runDemoScenario(selected));
    } catch (candidate) {
      setError(candidate instanceof Error ? candidate : new Error("The demo scenario could not be started."));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !running) onClose(); }}>
      <div ref={dialogRef} className="demo-modal" role="dialog" aria-modal="true" aria-labelledby="demo-modal-title">
        <header className="demo-modal__header">
          <div><h2 id="demo-modal-title">Run a workflow demo</h2><p>Launch deterministic local scenarios through the real orchestration API.</p></div>
          <button ref={closeRef} className="icon-button" onClick={onClose} aria-label="Close demo launcher" disabled={running}><Icon name="close" /></button>
        </header>
        <div className="demo-modal__content">
          {error ? <ErrorBanner error={error} onRetry={loading ? undefined : () => setLoadVersion((value) => value + 1)} /> : null}
          {loading ? <LoadingState label="Loading demo scenarios" /> : null}
          {!loading && !error && scenarios.length === 0 ? <p className="muted-copy">No demo scenarios are currently available.</p> : null}
          {!loading && scenarios.length > 0 ? (
            <fieldset className="scenario-list">
              <legend className="sr-only">Choose a demo scenario</legend>
              {scenarios.map((scenario) => (
                <label className={`scenario-card${selected === scenario.id ? " scenario-card--selected" : ""}`} key={scenario.id}>
                  <input type="radio" name="scenario" value={scenario.id} checked={selected === scenario.id} onChange={() => setSelected(scenario.id)} />
                  <span className={`workflow-glyph workflow-glyph--${scenario.workflow}`}><Icon name={scenario.workflow === "support" ? "reviews" : scenario.workflow === "invoice" ? "file" : "warning"} /></span>
                  <span className="scenario-card__copy">
                    <span className="scenario-card__workflow">{workflowLabels[scenario.workflow]}</span>
                    <strong>{scenario.name}</strong>
                    <span>{scenario.description}</span>
                    <small>Expected: {scenario.outcome}{scenario.risk ? ` · ${humanize(scenario.risk)} risk` : ""}</small>
                  </span>
                  <span className="scenario-card__radio" aria-hidden="true" />
                </label>
              ))}
            </fieldset>
          ) : null}
        </div>
        <footer className="demo-modal__footer">
          <Button onClick={onClose} disabled={running}>Cancel</Button>
          <Button variant="primary" onClick={() => void run()} disabled={!selectedScenario || running}>
            {running ? <><span className="button-spinner" /> Starting workflow…</> : <><Icon name="play" /> Run {selectedScenario ? selectedScenario.name : "scenario"}</>}
          </Button>
        </footer>
      </div>
    </div>
  );
}
