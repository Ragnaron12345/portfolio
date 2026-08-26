import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { client, normalizeUtcTimestamp } from "./api/client";
import { AppShell } from "./components/AppShell";
import { Button } from "./components/Ui";
import { RequestConsolePage } from "./pages/RequestConsolePage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("Nexora shell", () => {
  it("treats timezone-free backend timestamps as UTC", () => {
    expect(normalizeUtcTimestamp("2026-08-21T22:50:23.000")).toBe("2026-08-21T22:50:23.000Z");
    expect(normalizeUtcTimestamp("2026-08-22T00:50:23+02:00")).toBe("2026-08-22T00:50:23+02:00");
  });

  it("renders the locked navigation and moves to the request console", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: "offline" }) }));
    render(<App />);
    expect(screen.getByText("Operations overview", { selector: "h1" })).toBeInTheDocument();
    expect(screen.getByLabelText("Local operator session")).toBeInTheDocument();
    expect(screen.queryByLabelText("All systems operational")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Request Console")[0]!);
    expect(await screen.findByText("Request Console", { selector: "h1" })).toBeInTheDocument();
  });

  it("renders mixed confidence metadata after a request without crashing", async () => {
    window.history.replaceState({}, "", "/console");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        request_id: "req-1",
        trace_id: "trace-1",
        status: "pending_review",
        response: "Freeze the card and route the case to a human reviewer.",
        citations: [],
        confidence: 0.82,
        confidence_details: {
          retrieval: 0.42,
          structured_output: true,
          method: "weighted workflow decision heuristic; not calibrated probability",
        },
        model_used: "mock:nexora-deterministic-v1",
        requires_review: true,
        intent: "high_risk",
        risk_level: "high",
        route_reason: "safety policy",
        tokens_in: 120,
        tokens_out: 40,
        stage_timings: { classification_ms: 1, retrieval_ms: 2, generation_ms: 3 },
        latency_ms: 8,
        estimated_cost: 0,
      }),
    }));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Run request/i }));

    expect(await screen.findByText("Freeze the card and route the case to a human reviewer.")).toBeInTheDocument();
    expect(screen.getByText("weighted workflow decision heuristic; not calibrated probability")).toBeInTheDocument();
  });

  it("exposes compact icon buttons and channel state to assistive technology", () => {
    const { rerender } = render(<Button icon="refresh">Refresh</Button>);
    expect(screen.getByRole("button", { name: "Refresh" })).toHaveAttribute("aria-label", "Refresh");
    rerender(<RequestConsolePage />);
    expect(screen.getByRole("button", { name: "web" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "email" }));
    expect(screen.getByRole("button", { name: "email" })).toHaveAttribute("aria-pressed", "true");
  });

  it("makes closed mobile navigation inert and reports its expanded state", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    render(<AppShell path="/" pageTitle="Overview"><main>Content</main></AppShell>);
    const menu = screen.getByRole("button", { name: "Open navigation" });
    const navigation = screen.getByLabelText("Primary navigation", { selector: "aside" });
    await waitFor(() => expect(navigation).toHaveAttribute("inert"));
    expect(menu).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(navigation).not.toHaveAttribute("inert");
  });

  it("requests resolved reviews when the UI asks for the complete queue", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    await client.getReviews(null);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/reviews?status=", expect.any(Object));
  });

  it("surfaces structured evaluation-lock errors instead of object coercion", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: { message: "Knowledge mutations are locked.", evaluation_run_id: "run-123", poll_url: "/api/v1/evaluations/run-123" } }),
    }));

    await expect(client.deleteDocument("doc-1")).rejects.toThrow("Knowledge mutations are locked. Evaluation run-123 is still running. Progress: /api/v1/evaluations/run-123");
  });
});
