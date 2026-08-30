import type { Job } from './types'

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ||
  'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (cause) {
    // A network failure is shown to the analyst as what it is. A demo that
    // silently substitutes fake data for an unreachable backend is worse than
    // one that visibly cannot reach it.
    throw new ApiError(
      `Cannot reach the AVANTA API at ${API_BASE}. ${(cause as Error).message}`,
      0,
    )
  }
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail ?? body)
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new ApiError(detail || `${response.status} ${response.statusText}`, response.status, detail)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<any>('/api/v1/health'),
  scenarios: () => request<{ scenarios: any[] }>('/api/v1/scenarios'),
  scenes: () => request<{ scenes: any[] }>('/api/v1/scenes'),
  scene: (id: string) => request<any>(`/api/v1/scenes/${id}`),
  detections: (id: string) => request<any>(`/api/v1/scenes/${id}/detections`),
  ingest: (body: Record<string, unknown>) =>
    request<{ job_id: string }>('/api/v1/scenes/ingest', { method: 'POST', body: JSON.stringify(body) }),
  generateCandidates: (body: Record<string, unknown>) =>
    request<{ job_id: string }>('/api/v1/candidates/generate', { method: 'POST', body: JSON.stringify(body) }),
  candidates: (sceneId: string) => request<any>(`/api/v1/candidates?scene_id=${sceneId}`),
  runAttribution: (body: Record<string, unknown>) =>
    request<{ job_id: string }>('/api/v1/attribution/run', { method: 'POST', body: JSON.stringify(body) }),
  attribution: (runId: string) => request<any>(`/api/v1/attribution/${runId}`),
  simulation: (runId: string, mmsi: string) =>
    request<any>(`/api/v1/attribution/${runId}/sim/${encodeURIComponent(mmsi)}`),
  dossier: (body: Record<string, unknown>) =>
    request<any>('/api/v1/dossier/generate', { method: 'POST', body: JSON.stringify(body) }),
  handoff: (body: Record<string, unknown>) =>
    request<any>('/api/v1/handoff/oosa', { method: 'POST', body: JSON.stringify(body) }),
  calibration: () => request<any>('/api/v1/calibration'),
  job: (id: string) => request<Job>(`/api/v1/jobs/${id}`),
  rasterUrl: (id: string) => `${API_BASE}/api/v1/scenes/${id}/raster.png`,
  dossierPdfUrl: (runId: string, mmsi: string) =>
    `${API_BASE}/api/v1/dossier/${runId}/${encodeURIComponent(mmsi)}/pdf`,
  dossierJsonUrl: (runId: string, mmsi: string) =>
    `${API_BASE}/api/v1/dossier/${runId}/${encodeURIComponent(mmsi)}/json`,
}

/** Poll a job to completion, reporting each named stage as it changes. */
export async function followJob(
  jobId: string,
  onProgress: (job: Job) => void,
  signal?: AbortSignal,
): Promise<Job> {
  for (;;) {
    if (signal?.aborted) throw new ApiError('Cancelled', 0)
    const job = await api.job(jobId)
    onProgress(job)
    if (job.status === 'succeeded') return job
    if (job.status === 'failed') {
      throw new ApiError(job.error || 'The job failed without reporting a reason.', 500, job.error ?? undefined)
    }
    await new Promise((resolve) => setTimeout(resolve, 700))
  }
}
