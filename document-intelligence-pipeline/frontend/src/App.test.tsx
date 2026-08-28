import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import { App } from "./App"
import { EvaluationsPage } from "./pages/EvaluationsPage"

const metrics = {
  documents_processed: { value: 64, unit: "documents", definition: "Persisted documents." },
  auto_accept_rate: { value: 70, unit: "%", definition: "Accepted." },
  review_rate: { value: 25, unit: "%", definition: "Review." },
  failed_processing_rate: { value: 5, unit: "%", definition: "Failed." },
  average_latency: { value: 1200, unit: "ms", definition: "Mean." },
  p95_latency: { value: 2200, unit: "ms", definition: "p95." },
  document_type_distribution: { invoice: 20, bank_statement: 20, customer_application: 20, unknown: 4 },
  common_validation_failures: [],
  recent_activity: [],
}

beforeEach(() => {
  window.location.hash = "#overview"
  window.localStorage.clear()
  vi.restoreAllMocks()
})

it("renders actual overview metrics and navigates to documents", async () => {
  vi.spyOn(window, "fetch").mockImplementation((input) => {
    const url = String(input)
    return Promise.resolve(new Response(JSON.stringify(url.endsWith("/metrics") ? metrics : []), { status: 200 }))
  })
  render(<App />)
  expect(await screen.findByText("64")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Documents" }))
  await waitFor(() => expect(window.location.hash).toBe("#documents"))
})

it("persists the selected historical evaluation run", async () => {
  window.localStorage.setItem("docintel:selected-evaluation:v1", "run-older")
  const runs = [
    { id: "run-new", name: "New", status: "completed", dataset_size: 60, started_at: "2026-05-24T10:00:00Z", completed_at: "2026-05-24T10:01:00Z" },
    { id: "run-older", name: "Older", status: "completed", dataset_size: 60, started_at: "2026-05-23T10:00:00Z", completed_at: "2026-05-23T10:01:00Z" },
  ]
  const detail = {
    ...runs[1],
    config: { baseline: "Baseline config", improved: "Improved config", dataset_sha256: "abc", dataset: "synthetic" },
    metrics: [],
    details: { document_counts: {}, most_improved: [], remaining_failures: [], methodology: "Measured." },
  }
  vi.spyOn(window, "fetch").mockImplementation((input) => {
    const url = String(input)
    return Promise.resolve(new Response(JSON.stringify(url.endsWith("/evals/runs") ? runs : detail), { status: 200 }))
  })
  render(<EvaluationsPage />)
  expect((await screen.findAllByText("Older")).length).toBeGreaterThan(0)
  await waitFor(() => expect(window.localStorage.getItem("docintel:selected-evaluation:v1")).toBe("run-older"))
})
