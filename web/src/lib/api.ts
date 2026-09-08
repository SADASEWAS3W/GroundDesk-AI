import type { ChatRequest, JobAccepted, JobStatus } from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function submitChat(request: ChatRequest): Promise<JobAccepted> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Request failed with status ${res.status}`);
  }

  return res.json();
}

export async function getJobStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatus> {
  const res = await fetch(`${API_URL}/api/jobs/${encodeURIComponent(jobId)}`, {
    signal,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      body.error ?? `Request failed with status ${res.status}`,
      res.status,
    );
  }

  return res.json();
}

export async function submitReview(
  jobId: string,
  action: "approve" | "edit" | "reject",
  answer?: string,
): Promise<JobStatus> {
  const res = await fetch(`${API_URL}/api/reviews/${encodeURIComponent(jobId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, answer }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Request failed with status ${res.status}`);
  }
  return res.json();
}

export async function checkHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`, { signal });
    if (!res.ok) return false;
    const body = await res.json();
    return body.status === "ok";
  } catch {
    return false;
  }
}
