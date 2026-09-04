import { afterEach, describe, expect, it, vi } from "vitest";
import { client, normalizeExecution } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("execution API normalization", () => {
  it("maps the backend support decision contract into readable operator fields", () => {
    const execution = normalizeExecution({
      id: "EXE-SUPPORT-1",
      correlation_id: "corr-1",
      workflow: "support",
      current_stage: "REVIEW_CREATED",
      status: "waiting_for_review",
      input_data: { subject: "Urgent card security", message: "My card was stolen." },
      decision_summary: {
        outcome: "human_review",
        reason: "The message reports a stolen card and requires mandatory security review.",
        classification: {
          category: "suspected_fraud",
          risk_level: "high",
          confidence: 0.98,
          reason: "The message explicitly reports a stolen card, which creates a security risk.",
          needs_human: true,
          confidence_basis: ["Explicit stolen-card phrase"],
        },
        sources: [{ id: "kb-1", title: "Stolen card policy", content: "Freeze the card first.", relevance_score: 0.96 }],
        draft: "Freeze the card immediately and escalate to the fraud team.",
      },
      retry_count: 0,
      started_at: "2026-09-03T10:00:00Z",
      duration_ms: 1200,
      events: [
        { id: "e1", stage: "RECEIVED", status: "running", message: "Received", created_at: "2026-09-03T10:00:00Z" },
        { id: "e2", stage: "REVIEW_CREATED", status: "waiting_for_review", message: "Review created", created_at: "2026-09-03T10:00:01Z" },
      ],
    });

    expect(execution.workflow).toBe("AI Support Triage");
    expect(execution.input.message).toBe("My card was stolen.");
    expect(execution.classification).toMatchObject({ category: "suspected_fraud", risk_level: "high", needs_human: true });
    expect(execution.sources[0]).toMatchObject({ title: "Stolen card policy", relevance: 0.96 });
    expect(execution.generated_draft).toContain("Freeze the card");
    expect(execution.ai_attempt_count).toBeNull();
    expect(execution.events[0]?.status).toBe("completed");
    expect(execution.events[1]?.status).toBe("waiting_for_review");
  });

  it("hides malformed extraction payloads and preserves the exact review reason", () => {
    const execution = normalizeExecution({
      id: "EXE-INVOICE-1",
      workflow: "invoice",
      status: "waiting_for_review",
      input_data: { document_name: "corrupted.txt" },
      decision_summary: {
        outcome: "human_review",
        reason: "Invoice extraction remained malformed after one bounded repair retry; raw provider output is hidden.",
        extracted_fields: null,
        raw_output_exposed: false,
      },
      started_at: "2026-09-03T10:00:00Z",
    });

    expect(execution.extracted_fields).toEqual([]);
    expect(execution.decision_reason).toContain("raw provider output is hidden");
    expect(JSON.stringify(execution)).not.toContain("%%% malformed model output");
  });

  it("turns structured execution failures into a readable exact reason", () => {
    const execution = normalizeExecution({
      id: "EXE-FAILED-1",
      workflow: "incident",
      status: "failed",
      started_at: "2026-09-03T10:00:00Z",
      error: {
        code: "N8N_TIMEOUT",
        message: "Incident workflow exceeded its 30 second deadline.",
        details: { field: "webhook_response" },
      },
      ai_calls: [{ attempt: 1 }, { attempt: 2 }],
    });

    expect(execution.error).toBe("N8N_TIMEOUT · Incident workflow exceeded its 30 second deadline. · Field: webhook_response");
    expect(execution.ai_attempt_count).toBe(2);
  });
});

describe("approval API contract", () => {
  it("merges approved and rejected requests for the resolved view without sending an invalid status", async () => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://flowline.test");
      requested.push(`${url.pathname}${url.search}`);
      const status = url.searchParams.get("status");
      const item = {
        id: `APR-${status}`,
        execution_id: `EXE-${status}`,
        workflow: "support",
        reason: "Operator decision recorded.",
        decision_context: {},
        status,
        created_at: "2026-09-03T10:00:00Z",
        resolved_at: status === "approved" ? "2026-09-03T10:03:00Z" : "2026-09-03T10:02:00Z",
      };
      return Promise.resolve(new Response(JSON.stringify({ items: [item], total: 1 }), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));

    const result = await client.getApprovals("resolved");

    expect(requested).toEqual(["/api/v1/approvals?status=approved", "/api/v1/approvals?status=rejected"]);
    expect(requested.join(" ")).not.toContain("status=resolved");
    expect(result.items.map((item) => item.status)).toEqual(["approved", "rejected"]);
    expect(result.total).toBe(2);
  });
});
