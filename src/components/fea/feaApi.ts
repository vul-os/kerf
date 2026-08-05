// feaApi.js — shared fetch helper for all FEA solve panels.
//
// All panels POST to /api/projects/{pid}/files/{fid}/fem with an
// appropriate analysis_type. Results are polled via
// GET /api/projects/{pid}/files/{fid}/fem/status.
//
// For tools that map 1-to-1 to a named solver tool the body is:
//   { analysis_type: '<type>', ...options }
//
// The backend routes.py at /api/projects/{pid}/files/{fid}/fem stores the
// body as input_spec and passes it to the FEMWorker which calls the
// appropriate engine function.

import type { FemJobContext, FemJobStatus, FemSubmitResponse } from './femTypes'

const API_URL: string = import.meta.env.VITE_API_URL || ''

/**
 * Submit a FEM job.
 * @param body — analysis payload merged into input_spec. Shape varies per `analysis_type`
 *   (~30 distinct backend tools), so it's a boundary this slice does not own; see femTypes.ts.
 */
export async function submitFemJob(
  ctx: FemJobContext,
  body: Record<string, unknown>,
): Promise<FemSubmitResponse> {
  const { pid, fid, token } = ctx
  const res = await fetch(`${API_URL}/api/projects/${pid}/files/${fid}/fem`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const txt = await res.text()
    throw new Error(`${res.status}: ${txt}`)
  }
  return res.json()
}

/** Poll job status once. */
export async function pollFemStatus(ctx: FemJobContext): Promise<FemJobStatus> {
  const { pid, fid, token } = ctx
  const res = await fetch(`${API_URL}/api/projects/${pid}/files/${fid}/fem/status`, {
    headers: { authorization: `Bearer ${token}` },
  })
  if (!res.ok) return { status: 'unknown' }
  return res.json()
}

export interface RunAndPollOptions {
  onStatus?: (status: FemJobStatus | { status: 'queued'; job_id?: string }) => void
  intervalMs?: number
}

/**
 * Submit + poll until done/error. Returns a Promise that resolves with the
 * final status object. Pass `onStatus(s)` to receive intermediate updates.
 */
export async function runAndPoll(
  ctx: FemJobContext,
  body: Record<string, unknown>,
  { onStatus, intervalMs = 3000 }: RunAndPollOptions = {},
): Promise<FemJobStatus> {
  const sub = await submitFemJob(ctx, body)
  onStatus?.({ status: 'queued', job_id: sub.job_id })
  return new Promise((resolve, reject) => {
    const id = setInterval(async () => {
      try {
        const st = await pollFemStatus(ctx)
        onStatus?.(st)
        if (st.status === 'done' || st.status === 'error') {
          clearInterval(id)
          resolve(st)
        }
      } catch (e) {
        clearInterval(id)
        reject(e instanceof Error ? e : new Error(String(e)))
      }
    }, intervalMs)
  })
}
