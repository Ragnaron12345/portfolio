import { formatDelta } from "./RunDetailPage";

describe("delta semantics", () => {
  it("shows latency as a signed millisecond delta", () => {
    expect(formatDelta(-18, "ms", "ms")).toBe("-18.0 ms");
  });

  it("shows rates in percentage points", () => {
    expect(formatDelta(0.075, "percentage points", "%")).toBe("+7.5 pp");
  });
});
