import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const executionList = {
  items: [
    {
      id: "EXE-new",
      correlation_id: "corr-new",
      workflow: "invoice",
      current_stage: "AUDITED",
      status: "completed",
      input_data: { document_name: "new.txt" },
      decision_summary: { outcome: "submit_to_erp", reason: "All checks passed." },
      retry_count: 0,
      started_at: "2026-09-03T10:02:00Z",
      completed_at: "2026-09-03T10:02:01Z",
      duration_ms: 1000,
    },
    {
      id: "EXE-old",
      correlation_id: "corr-old",
      workflow: "support",
      current_stage: "REVIEW_CREATED",
      status: "waiting_for_review",
      input_data: { subject: "Stolen card", message: "My card was stolen." },
      decision_summary: {
        outcome: "human_review",
        reason: "Stolen card requires mandatory security review.",
        classification: { category: "suspected_fraud", risk_level: "high", confidence: 0.98, reason: "Message reports a stolen card.", needs_human: true },
        sources: [{ id: "policy", title: "Stolen card policy", relevance_score: 0.96 }],
        draft: "Freeze the card and escalate.",
      },
      retry_count: 0,
      started_at: "2026-09-03T10:00:00Z",
      duration_ms: 1900,
    },
  ],
  total: 2,
};

const metrics = {
  executions_today: 2,
  success_rate_percent: 50,
  failure_rate_percent: 0,
  review_rate_percent: 50,
  average_latency_ms: 1450,
  p95_latency_ms: 1900,
  workflows: {
    support: { executions: 1, success: 0, review: 1, failures: 0, average_latency_ms: 1900 },
    invoice: { executions: 1, success: 1, review: 0, failures: 0, average_latency_ms: 1000 },
    incident: { executions: 0, success: 0, review: 0, failures: 0, average_latency_ms: 0 },
  },
};

const events = {
  items: [
    { id: "ev-1", stage: "RECEIVED", status: "running", message: "Request received", created_at: "2026-09-03T10:00:00Z" },
    { id: "ev-2", stage: "REVIEW_CREATED", status: "waiting_for_review", message: "Review created", created_at: "2026-09-03T10:00:01Z" },
  ],
  total: 2,
};

function json(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }));
}

function pathOf(input: RequestInfo | URL): string {
  const value = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  return new URL(value, "http://flowline.test").pathname;
}

describe("Flowline application workflows", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("keeps an older selected execution in the URL while polling refreshes a newer list", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.history.replaceState({}, "", "/executions?execution=EXE-old");
    const detailRequests: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path === "/api/v1/health") return json({ status: "healthy" });
      if (path === "/api/v1/metrics") return json(metrics);
      if (path === "/api/v1/executions") return json(executionList);
      if (path === "/api/v1/executions/EXE-old/events") return json(events);
      if (path === "/api/v1/executions/EXE-old") {
        detailRequests.push(path);
        return json({ ...executionList.items[1], events: events.items });
      }
      return json({ error: { message: "Not found" } }, 404);
    }));

    render(<App />);
    expect(await screen.findByText("Stolen card policy")).toBeInTheDocument();
    expect(window.location.search).toContain("execution=EXE-old");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_100);
    });

    expect(window.location.search).toContain("execution=EXE-old");
    expect(document.querySelector(".execution-list-item--selected")?.textContent).toContain("EXE-old");
    expect(detailRequests.length).toBeGreaterThanOrEqual(2);
  });

  it.each([
    ["Approve", "approve", "Approval recorded"],
    ["Reject", "reject", "Rejection recorded"],
  ])("submits the %s review action through the protected endpoint", async (buttonLabel, endpoint, confirmation) => {
    window.history.replaceState({}, "", "/reviews?review=APR-1");
    const posts: Array<{ path: string; body: unknown }> = [];
    const approval = {
      id: "APR-1",
      execution_id: "EXE-old",
      workflow: "support",
      reason: "A stolen card is a high-risk security event and requires mandatory review.",
      decision_context: executionList.items[1].decision_summary,
      status: "pending",
      created_at: "2026-09-03T10:00:01Z",
      resolved_at: null,
      decisions: [],
      original_input: executionList.items[1].input_data,
      execution: executionList.items[1],
    };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/v1/health") return json({ status: "healthy" });
      if (path === "/api/v1/approvals") return json({ items: [approval], total: 1 });
      if (path === "/api/v1/approvals/APR-1" && (!init?.method || init.method === "GET")) return json(approval);
      if (path === "/api/v1/executions/EXE-old") return json({ ...executionList.items[1], events: events.items });
      if (path === "/api/v1/executions/EXE-old/events") return json(events);
      if (path === `/api/v1/approvals/APR-1/${endpoint}` && init?.method === "POST") {
        posts.push({ path, body: JSON.parse(String(init.body)) });
        return json({
          ...approval,
          status: endpoint === "approve" ? "approved" : "rejected",
          execution: endpoint === "approve" ? { ...executionList.items[1], status: "completed" } : executionList.items[1],
        });
      }
      return json({ error: { message: "Not found" } }, 404);
    }));

    render(<App />);
    const button = await screen.findByRole("button", { name: new RegExp(`^${buttonLabel}`) });
    fireEvent.click(button);
    expect(await screen.findByText(new RegExp(confirmation))).toBeInTheDocument();
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toEqual({ reviewer: "Ops Operator", note: "" });
    expect(window.location.search).toContain("review=APR-1");
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("shows an exact side-effect failure even though the approval decision was recorded", async () => {
    window.history.replaceState({}, "", "/reviews?review=APR-FAILED-ACTION");
    const approval = {
      id: "APR-FAILED-ACTION",
      execution_id: "EXE-old",
      workflow: "support",
      reason: "A protected action requires approval.",
      decision_context: executionList.items[1].decision_summary,
      status: "pending",
      created_at: "2026-09-03T10:00:01Z",
      resolved_at: null,
      decisions: [],
      original_input: executionList.items[1].input_data,
      execution: executionList.items[1],
    };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/v1/health") return json({ status: "healthy" });
      if (path === "/api/v1/approvals") return json({ items: [approval], total: 1 });
      if (path === "/api/v1/approvals/APR-FAILED-ACTION" && (!init?.method || init.method === "GET")) return json(approval);
      if (path === "/api/v1/executions/EXE-old") return json({ ...executionList.items[1], events: events.items });
      if (path === "/api/v1/executions/EXE-old/events") return json(events);
      if (path === "/api/v1/approvals/APR-FAILED-ACTION/approve" && init?.method === "POST") {
        return json({
          ...approval,
          status: "approved",
          execution: {
            ...executionList.items[1],
            status: "failed",
            error: { code: "crm_unavailable", message: "CRM mock rejected the approved action." },
          },
        });
      }
      return json({ error: { message: "Not found" } }, 404);
    }));

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /^Approve/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Approval recorded, but the authorized side effect failed: crm_unavailable · CRM mock rejected the approved action\./,
    );
  });

  it("switches from a pending review to a resolved item without retaining stale detail", async () => {
    window.history.replaceState({}, "", "/reviews?review=APR-PENDING");
    const pending = {
      id: "APR-PENDING",
      execution_id: "EXE-old",
      workflow: "support",
      reason: "Pending operator decision.",
      decision_context: {},
      status: "pending",
      created_at: "2026-09-03T10:00:00Z",
      resolved_at: null,
      original_input: { subject: "Pending subject" },
      execution: { ...executionList.items[1], input_data: { subject: "Pending subject" } },
    };
    const resolved = {
      ...pending,
      id: "APR-RESOLVED",
      execution_id: "EXE-new",
      status: "approved",
      reason: "Approved after evidence review.",
      created_at: "2026-09-03T09:00:00Z",
      resolved_at: "2026-09-03T11:00:00Z",
      original_input: { subject: "Resolved subject" },
      execution: { ...executionList.items[0], input_data: { subject: "Resolved subject" } },
    };

    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, "http://flowline.test");
      if (url.pathname === "/api/v1/health") return json({ status: "healthy" });
      if (url.pathname === "/api/v1/approvals") {
        if (url.searchParams.get("status") === "approved") return json({ items: [resolved], total: 1 });
        if (url.searchParams.get("status") === "rejected") return json({ items: [], total: 0 });
        return json({ items: [pending], total: 1 });
      }
      if (url.pathname === "/api/v1/approvals/APR-PENDING") return json(pending);
      if (url.pathname === "/api/v1/approvals/APR-RESOLVED") return json(resolved);
      if (url.pathname === "/api/v1/executions/EXE-old/events" || url.pathname === "/api/v1/executions/EXE-new/events") return json(events);
      return json({ error: { message: "Not found" } }, 404);
    }));

    render(<App />);
    expect(await screen.findByRole("heading", { name: "Pending subject" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resolved" }));

    expect(await screen.findByRole("heading", { name: "Resolved subject" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Pending subject" })).not.toBeInTheDocument();
    expect(window.location.search).toContain("status=resolved");
    expect(window.location.search).toContain("review=APR-RESOLVED");
  });
});
