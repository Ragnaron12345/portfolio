import { selectedRunId } from "./router";

describe("historical run routing", () => {
  it("reads a run from a path and keeps it independent of latest-run state", () => {
    expect(selectedRunId("/runs/run_historical_123")).toBe("run_historical_123");
  });

  it("reads a run from a query parameter for inspectors", () => {
    expect(selectedRunId("/failures?runId=run_old_9&regressions=1")).toBe("run_old_9");
  });
});
