/**
 * sseClient.js
 *
 * Minimal SSE client for POST-based server-sent events.
 *
 * The browser's built-in EventSource only supports GET. We use fetch() +
 * ReadableStream to support POST bodies, custom headers, and AbortSignal.
 *
 * Usage:
 *   for await (const { event, data } of streamSse(url, body, { signal, headers })) {
 *     // event: string (e.g. "assistant_text_delta")
 *     // data: parsed JSON object
 *   }
 *
 * Heartbeat comments (lines starting with ":") are silently skipped.
 * Multi-line data fields are concatenated with "\n" before JSON.parse.
 */

export interface SseFrame {
  event: string
  data: any
}

/**
 * Parse a single SSE frame (one block between double-newlines) into
 * { event, data } or null if the frame has no data.
 *
 * @param block - raw text between blank lines
 */
function parseFrame(block: string): SseFrame | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of block.split('\n')) {
    if (line.startsWith(':')) {
      // Comment / heartbeat — skip
      continue
    }
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (dataLines.length === 0) return null

  const raw = dataLines.join('\n')
  let data: any
  try {
    data = JSON.parse(raw)
  } catch {
    data = raw
  }

  return { event, data }
}

export interface StreamSseOptions {
  signal?: AbortSignal
  headers?: Record<string, string>
}

/**
 * Async generator that opens a POST SSE connection and yields parsed events.
 *
 * @param url
 * @param body - will be JSON.stringify'd
 */
export async function* streamSse(
  url: string,
  body: any,
  options: StreamSseOptions = {}
): AsyncGenerator<SseFrame, void, unknown> {
  const { signal, headers = {} } = options

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'text/event-stream',
      ...headers,
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j?.detail || j?.message || detail
    } catch { /* ignore */ }
    throw new Error(`SSE request failed: ${res.status} ${detail}`)
  }

  // A 200 with no body is legal HTTP and would otherwise throw an opaque
  // "Cannot read properties of null" several frames from here.
  if (!res.body) throw new Error('SSE request returned no body')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      if (signal?.aborted) break

      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // SSE frames are separated by blank lines (\n\n).
      // We may receive a partial frame; keep the tail in buffer.
      const parts = buffer.split('\n\n')
      // The last part may be incomplete — keep it in buffer.
      buffer = parts.pop() ?? ''

      for (const part of parts) {
        const trimmed = part.trim()
        if (!trimmed) continue

        const frame = parseFrame(trimmed)
        if (frame) {
          yield frame
        }
      }
    }

    // Flush any remaining buffer content (stream ended without trailing \n\n)
    if (buffer.trim()) {
      const frame = parseFrame(buffer.trim())
      if (frame) yield frame
    }
  } finally {
    reader.releaseLock()
  }
}
