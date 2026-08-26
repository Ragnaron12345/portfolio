import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { client } from "../api/client";
import { SourceDocumentDialog } from "../components/SourceDocumentDialog";
import type { EvaluationResult, EvaluationRun, KnowledgeDocument, KnowledgeDocumentDetail } from "../types";
import { EvaluationsPage } from "./EvaluationsPage";
import { KnowledgeBasePage } from "./KnowledgeBasePage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const documents: KnowledgeDocument[] = [
  {
    id: "doc-risk",
    title: "Fraud Escalation Policy",
    filename: "fraud-policy.md",
    source: "Risk & Compliance",
    mime_type: "text/markdown",
    created_at: "2026-08-21T10:00:00Z",
    chunk_count: 2,
    status: "indexed",
    metadata: { owner: "Risk" },
  },
  {
    id: "doc-support",
    title: "Support Handbook",
    filename: "handbook.md",
    source: "Support Operations",
    mime_type: "text/markdown",
    created_at: "2026-08-21T11:00:00Z",
    chunk_count: 1,
    status: "indexed",
  },
];

const detail: KnowledgeDocumentDetail = {
  ...documents[0]!,
  content: "# Fraud escalation\n\nFreeze a **stolen card** before replacement.\n\n| Priority | Action |\n| --- | --- |\n| P1 | Escalate |",
  chunks: [
    { id: "chunk-1", chunk_index: 0, page_number: null, content: "Freeze a stolen card before replacement." },
    { id: "chunk-2", chunk_index: 1, page_number: 2, content: "Escalate an unrecognized charge as P1." },
  ],
  content_total: 61,
  content_complete: true,
  next_content_offset: null,
  chunk_total: 2,
  chunks_complete: true,
  next_chunk_offset: null,
};

function evaluationResult(run: string, caseId: string, configuration: "baseline" | "improved", passed: boolean, latency: number): EvaluationResult {
  return {
    id: `${run}-${caseId}-${configuration}`,
    case_id: caseId,
    configuration,
    category: "factual",
    model: "mock:test",
    passed,
    correctness_score: passed ? 1 : 0.5,
    groundedness_score: passed ? 1 : 0.5,
    retrieval_score: passed ? 0.8 : 0.2,
    latency_ms: latency,
    estimated_cost: 0,
    details: { question: `Question for ${caseId}`, pass_gates: { content: passed } },
  };
}

function evaluationRun(id: string, name: string, improvedPass: number, latency: number): EvaluationRun {
  return {
    id,
    name,
    status: "completed",
    started_at: id === "run-new" ? "2026-08-22T10:00:00Z" : "2026-08-21T10:00:00Z",
    completed_at: id === "run-new" ? "2026-08-22T10:01:00Z" : "2026-08-21T10:01:00Z",
    config: {
      case_count: 2,
      request_fingerprint: "abc1234567890provenance",
      dataset: { name: "Fintech support", version: "v1", sha256: "dataset1234567890" },
      evaluator: { version: "v5", sha256: "evaluator1234567890" },
      pipeline: { sha256: "pipeline1234567890" },
      knowledge_snapshot: { sha256: "knowledge1234567890", document_count: 5, chunk_count: 12 },
      runtime_settings: { embedding_provider: "local-hash", embedding_model: "local-hash-v1", embedding_dimensions: 64 },
      provider_mode: "mock", routing_strategy: "cheapest_adequate",
      model_registry: [{ model: "nexora-deterministic-v1" }],
    },
    configuration_metrics: {
      baseline: { pass_rate: 0.5, intent_accuracy: 1, p95_latency_ms: latency - 2, estimated_cost: 0 },
      improved: { pass_rate: improvedPass, intent_accuracy: 1, p95_latency_ms: latency, estimated_cost: 0 },
    },
    results: [
      evaluationResult(id, "factual-001", "baseline", true, latency - 2),
      evaluationResult(id, "factual-002", "baseline", false, latency - 1),
      evaluationResult(id, "factual-001", "improved", true, latency),
      evaluationResult(id, "factual-002", "improved", improvedPass === 1, latency + 1),
    ],
  };
}

describe("Knowledge Base evidence reader", () => {
  it("filters on real source metadata and opens the full document and its chunks", async () => {
    vi.spyOn(client, "getDocuments").mockResolvedValue(documents);
    vi.spyOn(client, "getDocument").mockImplementation(async (id) => id === detail.id ? detail : { ...documents[1]!, content: "Support", chunks: [] });

    render(<KnowledgeBasePage />);
    expect(await screen.findByRole("option", { name: "Risk & Compliance" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Source metadata"), { target: { value: "Risk & Compliance" } });
    expect(screen.getByRole("button", { name: "Fraud Escalation Policy" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Support Handbook" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Fraud Escalation Policy" }));
    const dialog = await screen.findByRole("dialog", { name: "Fraud Escalation Policy" });
    expect(within(dialog).getByText("stolen card", { selector: "strong" }).closest("p")).toHaveTextContent("Freeze a stolen card before replacement.");
    expect(within(dialog).getByRole("columnheader", { name: "Priority" })).toBeInTheDocument();
    expect(within(dialog).getByRole("cell", { name: "P1" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /Indexed chunks/ }));
    expect(within(dialog).getByText("Escalate an unrecognized charge as P1.")).toBeInTheDocument();
    expect(within(dialog).getByText("Page 2")).toBeInTheDocument();
  });

  it("communicates the 100 MB upload boundary and indexing profile", async () => {
    vi.spyOn(client, "getDocuments").mockResolvedValue([]);
    render(<KnowledgeBasePage />);
    expect(await screen.findByText("How indexing works")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Upload document" })[0]!);
    expect(screen.getByText(/maximum transport size 100 MB/i)).toBeInTheDocument();
    expect(screen.getByText(/20 million decoded characters/i)).toBeInTheDocument();
    expect(screen.getByText(/25,000 indexed chunks/i)).toBeInTheDocument();
    expect(screen.getByText(/Origin or owner/i)).toBeInTheDocument();
    expect(screen.getByText(/Ingestion is atomic/i)).toBeInTheDocument();
    expect(screen.getByText("Not stored")).toBeInTheDocument();
  });

  it("fetches large document text and chunks page by page", async () => {
    vi.spyOn(client, "getDocuments").mockResolvedValue([documents[0]!]);
    const firstPage: KnowledgeDocumentDetail = {
      ...documents[0]!, content: "Part one. ", chunks: [detail.chunks[0]!],
      content_total: 19, content_complete: false, next_content_offset: 10,
      chunk_total: 2, chunks_complete: false, next_chunk_offset: 1,
    };
    const getDocument = vi.spyOn(client, "getDocument").mockImplementation(async (_id, options) => {
      if (options?.content_offset === 10) return {
        ...firstPage, content: "Part two.", chunks: [], content_offset: 10,
        content_complete: true, next_content_offset: null,
      };
      if (options?.chunk_offset === 1) return {
        ...firstPage, content: "", chunks: [detail.chunks[1]!], chunk_offset: 1,
        chunks_complete: true, next_chunk_offset: null,
      };
      return firstPage;
    });

    render(<KnowledgeBasePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Fraud Escalation Policy" }));
    const dialog = await screen.findByRole("dialog", { name: "Fraud Escalation Policy" });
    fireEvent.click(within(dialog).getByRole("button", { name: /Show next 9 characters/i }));
    expect(await within(dialog).findByText("Part one. Part two.")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /Indexed chunks/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: /Show next 1 chunks/i }));
    expect(await within(dialog).findByText("Escalate an unrecognized charge as P1.")).toBeInTheDocument();
    expect(getDocument).toHaveBeenCalledTimes(3);
  });

  it("does not append a stale Knowledge Base content page after closing and reopening the reader", async () => {
    vi.spyOn(client, "getDocuments").mockResolvedValue([documents[0]!]);
    let resolveOldPage!: (value: KnowledgeDocumentDetail) => void;
    let initialLoads = 0;
    const first: KnowledgeDocumentDetail = {
      ...detail,
      content: "First page. ",
      content_total: 22,
      content_complete: false,
      next_content_offset: 12,
    };
    const fresh: KnowledgeDocumentDetail = {
      ...detail,
      content: "Fresh document.",
      content_total: 15,
      content_complete: true,
      next_content_offset: null,
    };
    vi.spyOn(client, "getDocument").mockImplementation(async (_id, options) => {
      if (options?.content_offset === 12) {
        return new Promise<KnowledgeDocumentDetail>((resolve) => { resolveOldPage = resolve; });
      }
      initialLoads += 1;
      return initialLoads === 1 ? first : fresh;
    });

    render(<KnowledgeBasePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Fraud Escalation Policy" }));
    let dialog = await screen.findByRole("dialog", { name: "Fraud Escalation Policy" });
    fireEvent.click(within(dialog).getByRole("button", { name: /Show next 10 characters/i }));
    await waitFor(() => expect(resolveOldPage).toBeTypeOf("function"));

    fireEvent.click(within(dialog).getByRole("button", { name: "Close document reader" }));
    fireEvent.click(screen.getByRole("button", { name: "Fraud Escalation Policy" }));
    dialog = await screen.findByRole("dialog", { name: "Fraud Escalation Policy" });
    expect(await within(dialog).findByText("Fresh document.")).toBeInTheDocument();
    await act(async () => resolveOldPage({
      ...first,
      content: "STALE CONTENT PAGE",
      content_offset: 12,
      content_complete: true,
      next_content_offset: null,
    }));
    expect(within(dialog).getByText("Fresh document.")).toBeInTheDocument();
    expect(within(dialog).queryByText(/STALE CONTENT PAGE/)).not.toBeInTheDocument();
  });

  it("does not append a stale Knowledge Base chunk page after closing and reopening the reader", async () => {
    vi.spyOn(client, "getDocuments").mockResolvedValue([documents[0]!]);
    let resolveOldPage!: (value: KnowledgeDocumentDetail) => void;
    let initialLoads = 0;
    const first: KnowledgeDocumentDetail = {
      ...detail,
      chunks: [detail.chunks[0]!],
      chunk_total: 2,
      chunks_complete: false,
      next_chunk_offset: 1,
    };
    const freshChunk = { ...detail.chunks[0]!, id: "fresh-chunk", content: "Fresh chunk." };
    const fresh: KnowledgeDocumentDetail = {
      ...detail,
      chunks: [freshChunk],
      chunk_total: 1,
      chunks_complete: true,
      next_chunk_offset: null,
    };
    vi.spyOn(client, "getDocument").mockImplementation(async (_id, options) => {
      if (options?.chunk_offset === 1) {
        return new Promise<KnowledgeDocumentDetail>((resolve) => { resolveOldPage = resolve; });
      }
      initialLoads += 1;
      return initialLoads === 1 ? first : fresh;
    });

    render(<KnowledgeBasePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Fraud Escalation Policy" }));
    let dialog = await screen.findByRole("dialog", { name: "Fraud Escalation Policy" });
    fireEvent.click(within(dialog).getByRole("button", { name: /Indexed chunks/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: /Show next 1 chunks/i }));
    await waitFor(() => expect(resolveOldPage).toBeTypeOf("function"));

    fireEvent.click(within(dialog).getByRole("button", { name: "Close document reader" }));
    fireEvent.click(screen.getByRole("button", { name: "Fraud Escalation Policy" }));
    dialog = await screen.findByRole("dialog", { name: "Fraud Escalation Policy" });
    fireEvent.click(within(dialog).getByRole("button", { name: /Indexed chunks/ }));
    expect(await within(dialog).findByText("Fresh chunk.")).toBeInTheDocument();
    await act(async () => resolveOldPage({
      ...first,
      chunks: [{ ...detail.chunks[1]!, content: "STALE CHUNK PAGE" }],
      chunk_offset: 1,
      chunks_complete: true,
      next_chunk_offset: null,
    }));
    expect(within(dialog).getByText("Fresh chunk.")).toBeInTheDocument();
    expect(within(dialog).queryByText(/STALE CHUNK PAGE/)).not.toBeInTheDocument();
  });

  it("pages the server-side document catalog beyond the first 100 records", async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => ({
      ...documents[0]!, id: `doc-${index}`, title: `Policy ${index}`, filename: `policy-${index}.md`,
    }));
    const getDocuments = vi.spyOn(client, "getDocuments").mockImplementation(async (options) => options?.offset === 100 ? [documents[1]!] : firstPage);

    render(<KnowledgeBasePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Load next 100 documents" }));
    expect(await screen.findByRole("button", { name: "Support Handbook" })).toBeInTheDocument();
    expect(getDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 100, offset: 100 }));
  });

  it("ignores a stale catalog response after the server-side search changes", async () => {
    let resolveInitial!: (value: KnowledgeDocument[]) => void;
    vi.spyOn(client, "getDocuments").mockImplementation(async (options) => {
      if (options?.search === "Support") return [documents[1]!];
      return new Promise<KnowledgeDocument[]>((resolve) => { resolveInitial = resolve; });
    });

    render(<KnowledgeBasePage />);
    await waitFor(() => expect(resolveInitial).toBeTypeOf("function"));
    fireEvent.change(screen.getByPlaceholderText("Search title or filename…"), { target: { value: "Support" } });
    expect(await screen.findByRole("button", { name: "Support Handbook" })).toBeInTheDocument();
    await act(async () => { resolveInitial([documents[0]!]); });
    expect(screen.getByRole("button", { name: "Support Handbook" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fraud Escalation Policy" })).not.toBeInTheDocument();
  });

  it("does not append a stale document page after closing and reopening the same citation", async () => {
    let resolveOldPage!: (value: KnowledgeDocumentDetail) => void;
    let initialLoads = 0;
    const first = { ...detail, content: "First page. ", content_total: 22, content_complete: false, next_content_offset: 12 };
    const fresh = { ...detail, content: "Fresh document.", content_total: 15, content_complete: true, next_content_offset: null };
    vi.spyOn(client, "getDocument").mockImplementation(async (_id, options) => {
      if (options?.content_offset === 12) return new Promise<KnowledgeDocumentDetail>((resolve) => { resolveOldPage = resolve; });
      initialLoads += 1;
      return initialLoads === 1 ? first : fresh;
    });
    const citation = { document_id: detail.id, chunk_id: "chunk-1", chunk_index: 0, title: detail.title, source: detail.source, excerpt: "Matched evidence" };
    const { rerender } = render(<SourceDocumentDialog citation={citation} onClose={() => undefined} />);
    expect(await screen.findByText("First page.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Show next 10 characters/i }));
    await waitFor(() => expect(resolveOldPage).toBeTypeOf("function"));

    rerender(<SourceDocumentDialog citation={null} onClose={() => undefined} />);
    rerender(<SourceDocumentDialog citation={{ ...citation }} onClose={() => undefined} />);
    expect(await screen.findByText("Fresh document.")).toBeInTheDocument();
    await act(async () => resolveOldPage({ ...first, content: "STALE PAGE", content_offset: 12, content_complete: true, next_content_offset: null }));
    expect(screen.getByText("Fresh document.")).toBeInTheDocument();
    expect(screen.queryByText(/STALE PAGE/)).not.toBeInTheDocument();
  });
});

describe("Evaluation snapshots", () => {
  it("requires an explicit 80-execution cost confirmation before starting", async () => {
    const created = evaluationRun("run-new", "Confirmed run", 1, 14);
    vi.spyOn(client, "getEvaluationRuns").mockResolvedValue([]);
    const run = vi.spyOn(client, "runEvaluation").mockResolvedValue(created);

    render(<EvaluationsPage />);
    await screen.findByText("No evaluation runs");
    fireEvent.click(screen.getAllByRole("button", { name: "Run 80 executions" })[0]!);
    const confirmation = screen.getByRole("alertdialog", { name: "Run the full comparison?" });
    expect(confirmation).toHaveTextContent("40 cases × 2 configurations");
    expect(confirmation).toHaveTextContent("incur provider charges");
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Confirm & run 80" }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
  });

  it("preserves the selected case and configuration while loading another run's real data", async () => {
    const latest = evaluationRun("run-new", "Current snapshot", 1, 14);
    const earlier = evaluationRun("run-old", "Earlier snapshot", 0.75, 25);
    vi.spyOn(client, "getEvaluationRuns").mockResolvedValue([
      { ...latest, results: [] },
      { ...earlier, results: [] },
    ]);
    vi.spyOn(client, "getEvaluationRun").mockImplementation(async (id) => id === latest.id ? latest : earlier);

    render(<EvaluationsPage />);
    await screen.findByText("Current snapshot", { selector: ".evaluation-config strong" });
    fireEvent.click(screen.getByText("Provenance"));
    expect(screen.getByText("abc1234567890provenance")).toBeInTheDocument();
    expect(screen.getByText(/local-hash-v1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "factual-002" }));
    expect(screen.getByLabelText("Evaluation case detail")).toHaveTextContent("factual-002");

    fireEvent.click(screen.getByRole("button", { name: /Earlier snapshot/ }));
    await waitFor(() => expect(screen.getByLabelText("Evaluation case detail")).toHaveTextContent("run run-old · improved"));
    expect(screen.getByLabelText("Evaluation case detail")).toHaveTextContent("factual-002");
    expect(screen.getByText("Earlier snapshot", { selector: ".evaluation-config strong" })).toBeInTheDocument();
    expect(screen.getByText("75%", { selector: ".eval-metric-table strong" })).toBeInTheDocument();
  });

  it("keeps the case ID when comparing baseline with improved execution", async () => {
    const latest = evaluationRun("run-new", "Current snapshot", 1, 14);
    vi.spyOn(client, "getEvaluationRuns").mockResolvedValue([{ ...latest, results: undefined }]);
    vi.spyOn(client, "getEvaluationRun").mockResolvedValue(latest);

    render(<EvaluationsPage />);
    await screen.findByRole("button", { name: "factual-002" });
    fireEvent.click(screen.getByRole("button", { name: "factual-002" }));
    fireEvent.click(screen.getByRole("button", { name: "baseline" }));
    expect(screen.getByLabelText("Evaluation case detail")).toHaveTextContent("factual-002");
    expect(screen.getByLabelText("Evaluation case detail")).toHaveTextContent("baseline");
  });

  it("withholds aggregate comparisons when provenance drift invalidates a run", async () => {
    const invalid = {
      ...evaluationRun("run-new", "Drifted snapshot", 1, 14),
      status: "invalid",
      provenance_valid: false,
      invalid_reason: "Knowledge snapshot changed during execution.",
    };
    vi.spyOn(client, "getEvaluationRuns").mockResolvedValue([{ ...invalid, results: undefined }]);
    vi.spyOn(client, "getEvaluationRun").mockResolvedValue(invalid);

    render(<EvaluationsPage />);
    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("not valid comparison evidence");
    expect(warning).toHaveTextContent("Knowledge snapshot changed during execution");
    expect(screen.queryByRole("table", { name: /Baseline and improved results/i })).not.toBeInTheDocument();
    expect(screen.getByText("Not comparable", { selector: ".run-history b" })).toBeInTheDocument();
    expect(screen.getByText("Diagnostic case results")).toBeInTheDocument();
  });

  it("withholds aggregate comparisons when a run fails after recording a completion time", async () => {
    const failed = { ...evaluationRun("run-new", "Failed snapshot", 1, 14), status: "failed" };
    vi.spyOn(client, "getEvaluationRuns").mockResolvedValue([{ ...failed, results: undefined }]);
    vi.spyOn(client, "getEvaluationRun").mockResolvedValue(failed);

    render(<EvaluationsPage />);
    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("did not complete and is not comparison evidence");
    expect(screen.getByText("Failed · not comparable")).toBeInTheDocument();
    expect(screen.queryByText("Pass rate vs. latency / cost")).not.toBeInTheDocument();
  });

  it("withholds aggregate comparisons for a legacy run without a reproducible fingerprint", async () => {
    const legacy = evaluationRun("run-legacy", "Legacy snapshot", 0.9, 18);
    legacy.config = { case_count: 2, dataset: { name: "Legacy support", version: "v0" } };
    vi.spyOn(client, "getEvaluationRuns").mockResolvedValue([legacy]);
    vi.spyOn(client, "getEvaluationRun").mockResolvedValue(legacy);

    render(<EvaluationsPage />);

    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("Comparable provenance missing");
    expect(warning).toHaveTextContent("not comparison evidence");
    expect(screen.queryByRole("table", { name: /Baseline and improved results/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Quality, speed, and cost trade-off/i)).not.toBeInTheDocument();
    expect(screen.getByText("Legacy · not comparable")).toBeInTheDocument();
  });
});
