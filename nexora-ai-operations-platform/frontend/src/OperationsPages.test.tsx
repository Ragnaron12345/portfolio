import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { client } from "./api/client";
import { OverviewPage } from "./pages/OverviewPage";
import { RequestConsolePage } from "./pages/RequestConsolePage";
import { ReviewQueuePage } from "./pages/ReviewQueuePage";

const MODELS = [
  { provider: "AI Prime Tech", model: "claude-fable-5", display_name: "Claude Fable 5", role: "Fast classification", enabled: true, availability: "configured_unverified" as const },
  { provider: "AI Prime Tech", model: "claude-sonnet-5", display_name: "Claude Sonnet 5", role: "Routine grounded support", enabled: true, availability: "configured_unverified" as const },
  { provider: "AI Prime Tech", model: "claude-opus-5", display_name: "Claude Opus 5", role: "High-risk reasoning", enabled: true, availability: "configured_unverified" as const },
];

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Operations surfaces", () => {
  it("labels both overview chart axes and explains the configured model portfolio and zero spend", async () => {
    vi.spyOn(client, "getMetrics").mockResolvedValue({
      total_requests: 8, success_rate: 1, escalation_rate: 0.25, average_latency_ms: 1200,
      p95_latency_ms: 1800, total_tokens: 640, estimated_spend: 0, error_rate: 0,
      retrieval_hit_rate: 0.9, pending_reviews: 2,
      timeline: [
        { bucket: "2026-08-20", requests: 2, latency_ms: 900 },
        { bucket: "2026-08-21", requests: 6, latency_ms: 1400 },
      ],
      recent_traces: [],
    });
    vi.spyOn(client, "getModelMetrics").mockResolvedValue([
      { provider: "mock", model: "deterministic", requests: 8, tokens_in: 500, tokens_out: 140, cost: 0, average_latency_ms: 11 },
    ]);
    vi.spyOn(client, "getReviews").mockResolvedValue([]);
    vi.spyOn(client, "getModels").mockResolvedValue(MODELS);

    render(<OverviewPage />);

    expect(await screen.findByText("Claude Opus 5")).toBeInTheDocument();
    expect(screen.getByText("Left axis")).toBeInTheDocument();
    expect(screen.getByText("Right axis")).toBeInTheDocument();
    expect(screen.getByText("Latest volume")).toBeInTheDocument();
    expect(screen.getAllByText(/live catalog unverified/i)).toHaveLength(3);
    expect(screen.getByText("Why is spend $0?")).toBeInTheDocument();
    expect(screen.getByText(/No billable cost was recorded/i)).toBeInTheDocument();
  });

  it("does not present expected remote models as enabled in a mock-only runtime", async () => {
    vi.spyOn(client, "getMetrics").mockResolvedValue({
      total_requests: 0, success_rate: 0, escalation_rate: 0, average_latency_ms: 0,
      p95_latency_ms: 0, total_tokens: 0, estimated_spend: 0, error_rate: 0,
      retrieval_hit_rate: 0, pending_reviews: 0, timeline: [], recent_traces: [],
    });
    vi.spyOn(client, "getModelMetrics").mockResolvedValue([]);
    vi.spyOn(client, "getReviews").mockResolvedValue([]);
    vi.spyOn(client, "getModels").mockResolvedValue([
      { provider: "mock", model: "nexora-deterministic-v1", enabled: true, fallback_only: true },
    ]);

    render(<OverviewPage />);

    expect(await screen.findByText("No remote models enabled")).toBeInTheDocument();
    expect(screen.queryByText("Claude Opus 5")).not.toBeInTheDocument();
    expect(screen.getByText(/0 configured/)).toBeInTheDocument();
  });

  it("renders readable grounded tables and exposes pipeline, sources, tool arguments and results", async () => {
    vi.spyOn(client, "getModels").mockResolvedValue(MODELS);
    vi.spyOn(client, "createRequest").mockResolvedValue({
      request_id: "req-1002",
      trace_id: "trace-1002",
      status: "pending_review",
      response: "## Replacement reasons\n\nUse **verified policy** only.\n\n| Reason | Fee | Handling |\n| --- | ---: | --- |\n| Stolen | EUR 0 | Freeze first; |",
      citations: [{ document_id: "doc-card", chunk_id: "chunk-3", title: "Card replacement procedure", source: "Operations policy", chunk_index: 3, score: 0.91, excerpt: "Freeze the stolen card before replacement." }],
      confidence: 0.82,
      confidence_details: { retrieval_quality: 0.91, grounding: 0.86, method: "weighted workflow heuristic", routing: { strategy: "cheapest_adequate" } },
      model_used: "claude-opus-5",
      requires_review: true,
      topic: "card_security",
      topic_reason: "The customer reports a stolen card.",
      intent: "account_or_customer_action",
      risk_level: "high",
      risk_reason: "A card freeze affects account access.",
      risk_factors: ["stolen payment instrument", "account-changing action"],
      classification_reason: "Card security request requiring retrieval and action.",
      needs_retrieval: true,
      needs_tools: true,
      route_reason: "Opus selected because high-risk cases require the strongest reasoning tier.",
      escalation_reasons: ["high-risk request"],
      decision_factors: { strategy: "cheapest_adequate", risk_tier: "high" },
      provider_attempts: [{ provider: "AI Prime Tech", model: "claude-opus-5", success: true, latency_ms: 900, estimated_cost: 0.012 }],
      tool_calls: [{ id: "tool-1", tool_name: "get_customer_summary", arguments: { customer_id: "CUST-1002" }, result: { card_status: "active" }, status: "succeeded", latency_ms: 3 }],
      tokens_in: 200,
      tokens_out: 80,
      latency_ms: 1200,
      estimated_cost: 0.012,
      stage_timings: { classification_ms: 40, retrieval_ms: 20, generation_ms: 900, validation_and_persistence_ms: 30 },
    });
    vi.spyOn(client, "getDocument").mockResolvedValue({
      id: "doc-card", title: "Card replacement procedure", filename: "cards.md", source: "Operations policy",
      mime_type: "text/markdown", created_at: "2026-08-20T00:00:00Z", chunk_count: 1,
      content: "Card security policy\n\nFreeze a stolen card before issuing its replacement.",
      chunks: [{ id: "chunk-3", chunk_index: 3, content: "Freeze the stolen card before replacement." }],
    });

    render(<RequestConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: /Run request/i }));

    expect(await screen.findByText("Human decision required before release")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Stolen" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "EUR 0" })).toBeInTheDocument();
    expect(screen.getByText("verified policy", { selector: "strong" })).toBeInTheDocument();
    expect(screen.queryByText(/\*\*verified policy\*\*/)).not.toBeInTheDocument();
    expect(screen.getByText("91%", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByText(/customer_id/)).toBeInTheDocument();
    expect(screen.getByText(/card_status/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Retrieve Complete/i }));
    expect(screen.getByText(/91% similarity/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Route Complete/i }));
    expect(screen.getAllByText(/Opus selected because high-risk/i).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Card replacement procedure/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Matched chunk")).toBeInTheDocument();
    expect(within(dialog).getByText(/Card security policy/)).toBeInTheDocument();
  });

  it("marks failed and skipped pipeline stages instead of claiming every step completed", async () => {
    vi.spyOn(client, "getModels").mockResolvedValue(MODELS);
    vi.spyOn(client, "createRequest").mockResolvedValue({
      request_id: "req-failed", trace_id: "trace-failed", status: "failed", response: null,
      citations: [], confidence: 0, requires_review: true, intent: "knowledge_request",
      risk_level: "medium", needs_retrieval: false, needs_tools: false,
      route_reason: "Sonnet was selected before the provider failed.", model_used: "claude-sonnet-5",
      escalation_reasons: ["provider execution unavailable"],
      provider_attempts: [{ provider: "AI Prime Tech", model: "claude-sonnet-5", success: false, error: "provider unavailable" }],
      tool_calls: [], tokens_in: 0, tokens_out: 0, latency_ms: 90, estimated_cost: 0,
      stage_timings: { classification_ms: 20, routing_ms: 2 },
    });

    render(<RequestConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: /Run request/i }));

    expect(await screen.findByText("Processing failed; investigation required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Classify Complete/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retrieve Skipped/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate Failed/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Validate Failed/i })).toBeInTheDocument();
  });

  it("marks a zero-duration failed retrieval from the explicit persisted stage status", async () => {
    vi.spyOn(client, "getModels").mockResolvedValue(MODELS);
    vi.spyOn(client, "createRequest").mockResolvedValue({
      request_id: "req-retrieval-failed", trace_id: "trace-retrieval-failed", status: "failed", response: null,
      citations: [], confidence: 0, model_used: null, requires_review: true, intent: "knowledge_request", topic: "policy_lookup",
      risk_level: "low", needs_retrieval: true, needs_tools: false,
      decision_factors: { retrieval_attempted: true, retrieval_mode: "required", retrieval_status: "failed" },
      escalation_reasons: ["Pipeline failure requires human investigation."], provider_attempts: [], tool_calls: [],
      tokens_in: 0, tokens_out: 0, latency_ms: 30, estimated_cost: 0,
      stage_timings: { classification_ms: 20, retrieval_ms: 0, validation_and_persistence_ms: 10 },
    });

    render(<RequestConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: /Run request/i }));
    expect(await screen.findByRole("button", { name: /Retrieve Failed/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Retrieve Failed/i }));
    expect(screen.getByText(/failed before a trustworthy evidence result/i)).toBeInTheDocument();
  });

  it("shows request status, detailed escalation evidence and newest-first decision history", async () => {
    vi.spyOn(client, "getReviews").mockResolvedValue([{
      id: "review-1", request_id: "req-1002", status: "pending", request_status: "pending_review",
      reason: "high-risk request", escalation_reasons: ["Model quality gate: mock tier 1 is below required quality tier 5.", "high-risk request"], created_at: "2026-08-20T10:00:00Z",
      message: "Customer CUST-1002 says their card is stolen. What should we do?", response: "Freeze the card.",
      risk_level: "high", confidence: 0.82, topic: "card_security", intent: "account_or_customer_action",
      model: "claude-opus-5", topic_reason: "Stolen card report.", risk_reason: "Account-changing action.",
      risk_factors: ["stolen payment instrument"], route_reason: "Strongest tier for high risk.", citations: [],
    }]);

    render(<ReviewQueuePage />);

    expect((await screen.findAllByText("Pending Review", { selector: ".status-mark" })).length).toBeGreaterThan(0);
    expect(screen.getByText("Card-security action requires oversight")).toBeInTheDocument();
    expect(screen.getByText(/Freezing access, identity-safe verification/i)).toBeInTheDocument();
    expect(screen.getByText("Model quality floor not met")).toBeInTheDocument();
    expect(screen.queryByText("Provider execution unavailable")).not.toBeInTheDocument();
    const history = screen.getByText(/Newest first/i).closest("section")!;
    const events = within(history).getAllByRole("listitem");
    expect(events[0]).toHaveTextContent("Current");
    expect(events[1]).toHaveTextContent("Automatically escalated");
  });

  it("keeps a safely failed review decision visible and retryable", async () => {
    vi.spyOn(client, "getReviews").mockResolvedValue([{
      id: "review-retry", request_id: "req-retry", status: "decision_failed", request_status: "pending_review",
      reason: "tool approval required", created_at: "2026-08-20T10:00:00Z", message: "Freeze the card.", response: "Draft response.",
      risk_level: "high", confidence: 0.7, citations: [], decision_error: "RuntimeError: decision processing failed",
      decision_history: [
        { event: "claimed", action: "approve", status: "approval_in_progress", at: "2026-08-20T10:01:00Z" },
        { event: "failed", action: "approve", status: "decision_failed", error_type: "RuntimeError", at: "2026-08-20T10:02:00Z" },
      ],
    }]);

    render(<ReviewQueuePage />);
    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("Previous decision attempt failed safely");
    expect(screen.getByRole("button", { name: "Retry approve" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Retry approve" })).toBeEnabled();
    const history = screen.getByText(/Newest first/i).closest("section")!;
    expect(within(history).getAllByRole("listitem")[0]).toHaveTextContent("Failed · Approve · Decision Failed");
  });

  it("offers a server-guarded retry for an in-progress decision lease", async () => {
    vi.spyOn(client, "getReviews").mockResolvedValue([{
      id: "review-lease", request_id: "req-lease", status: "approval_in_progress", request_status: "pending_review",
      reason: "high-risk request", created_at: "2026-08-20T10:00:00Z", decision_started_at: "2026-08-20T10:01:00Z",
      message: "Freeze card.", response: "Draft.", risk_level: "high", confidence: 0.7, citations: [],
    }]);

    render(<ReviewQueuePage />);
    expect(await screen.findByText("Decision is actively claimed")).toBeInTheDocument();
    expect(screen.getByText(/stale lease is reclaimed/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Retry approve" })).toBeEnabled();
  });
});
