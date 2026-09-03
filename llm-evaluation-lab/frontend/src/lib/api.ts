const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      // The HTTP status remains the useful error when a proxy returns HTML.
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export function reportUrl(runId: string, format: "md" | "json" = "md"): string {
  return `${API_BASE}/reports/${runId}.${format}`;
}
