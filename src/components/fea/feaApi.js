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

const API_URL = import.meta.env.VITE_API_URL || ''

/**
 * Submit a FEM job.
 * @param {{ pid: string, fid: string, token: string }} ctx
 * @param {object} body — analysis payload merged into input_spec
 * @returns {Promise<{ job_id: string, status: string }>}
 */
export async function submitFemJob(ctx, body) {
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

/**
 * Poll job status once.
 * @returns {Promise<{ status: string, result?: object, error?: string }>}
 */
export async function pollFemStatus(ctx) {
  const { pid, fid, token } = ctx
  const res = await fetch(`${API_URL}/api/projects/${pid}/files/${fid}/fem/status`, {
    headers: { authorization: `Bearer ${token}` },
  })
  if (!res.ok) return { status: 'unknown' }
  return res.json()
}

/**
 * Submit + poll until done/error. Returns a Promise that resolves with the
 * final status object. Pass `onStatus(s)` to receive intermediate updates.
 */
export async function runAndPoll(ctx, body, { onStatus, intervalMs = 3000 } = {}) {
  const sub = await submitFemJob(ctx, body)
  onStatus?.({ status: 'queued', job_id: sub.job_id })
  return new Promise((resolve, reject) => {
    const id = setInterval(async () => {
      try {
        const s = await pollFemStatus(ctx)
        onStatus?.(s)
        if (s.status === 'done' || s.status === 'error') {
          clearInterval(id)
          resolve(s)
        }
      } catch (e) {
        clearInterval(id)
        reject(e)
      }
    }, intervalMs)
  })
}
