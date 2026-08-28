import type {
  DocumentDetail,
  DocumentSummary,
  EvaluationDetail,
  EvaluationSummary,
  Metrics,
  ReviewDetail,
  ReviewSummary,
} from "../types"

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1"

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const message = typeof payload?.detail === "string" ? payload.detail : payload?.detail?.message
    throw new Error(message || `Request failed (${response.status})`)
  }
  return payload as T
}

export const api = {
  documents: () => request<DocumentSummary[]>("/documents"),
  document: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  text: (id: string) => request<{ text: string }>(`/documents/${id}/text`),
  fileUrl: (id: string) => `${API_BASE}/documents/${id}/file`,
  retry: (id: string) => request<DocumentDetail>(`/documents/${id}/retry`, { method: "POST" }),
  rerunOcr: (id: string) => request<DocumentDetail>(`/documents/${id}/rerun-ocr`, { method: "POST" }),
  reviews: (status = "pending") => request<ReviewSummary[]>(`/reviews?status=${status}`),
  review: (id: string) => request<ReviewDetail>(`/reviews/${id}`),
  approve: (id: string, notes: string) =>
    request<ReviewDetail>(`/reviews/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    }),
  reject: (id: string, notes: string) =>
    request<ReviewDetail>(`/reviews/${id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    }),
  editApprove: (id: string, fields: Record<string, unknown>, notes: string) =>
    request<ReviewDetail>(`/reviews/${id}/edit-and-approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, notes }),
    }),
  metrics: () => request<Metrics>("/metrics"),
  evaluationRuns: () => request<EvaluationSummary[]>("/evals/runs"),
  evaluation: (id: string) => request<EvaluationDetail>(`/evals/runs/${id}`),
  runEvaluation: () =>
    request<EvaluationDetail>("/evals/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: `Synthetic dataset · ${new Date().toLocaleString()}` }),
    }),
}

export function uploadDocument(
  file: File,
  onProgress: (progress: number) => void,
): Promise<DocumentDetail> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const body = new FormData()
    body.append("file", file)
    xhr.open("POST", `${API_BASE}/documents`)
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    })
    xhr.addEventListener("load", () => {
      const payload = JSON.parse(xhr.responseText || "null")
      if (xhr.status >= 200 && xhr.status < 300) resolve(payload as DocumentDetail)
      else reject(new Error(typeof payload?.detail === "string" ? payload.detail : `Upload failed (${xhr.status})`))
    })
    xhr.addEventListener("error", () => reject(new Error("Upload failed because the API is unreachable.")))
    xhr.send(body)
  })
}
