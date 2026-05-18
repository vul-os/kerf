/**
 * webSerialBridge.js — thin wrapper around the browser WebSerial API.
 *
 * Public API
 * ──────────
 *   requestPort(options?) -> Promise<SerialPort>
 *     Prompts the user to pick a serial port and returns the native
 *     SerialPort object. Rejects with a helpful message when WebSerial is
 *     not available in the current browser / context.
 *
 *   SerialReader(port, baud) -> AsyncIterable<string>
 *     Async-iterable that yields decoded UTF-8 lines from `port` once it is
 *     opened. Each string has leading/trailing whitespace stripped.
 *     The reader opens the port on first iteration and closes it on return /
 *     throw (i.e. when the caller breaks or the generator is GC'd via
 *     `reader.return()`).
 *
 * Browser compatibility
 * ─────────────────────
 *   WebSerial is supported in Chromium-based browsers (Chrome 89+, Edge 89+)
 *   on HTTPS origins or localhost. Firefox and Safari do not yet implement it.
 *   When `navigator.serial` is absent, requestPort() rejects with a
 *   descriptive error and SerialReader throws on construction.
 *
 * Usage
 * ─────
 *   import { requestPort, SerialReader } from '@/lib/webSerialBridge'
 *
 *   const port = await requestPort()
 *   for await (const line of new SerialReader(port, 115200)) {
 *     console.log(line)
 *   }
 */

// ── compatibility guard ───────────────────────────────────────────────────────

const WEBSERIAL_NOT_AVAILABLE_MSG =
  'WebSerial is not available in this browser. ' +
  'Use Chrome 89+ or Edge 89+ on an HTTPS origin or localhost.'

function isWebSerialAvailable() {
  return (
    typeof navigator !== 'undefined' &&
    navigator.serial != null &&
    typeof navigator.serial.requestPort === 'function'
  )
}

// ── requestPort ───────────────────────────────────────────────────────────────

/**
 * Prompt the user to select a serial port.
 *
 * @param {SerialPortRequestOptions} [options] - Optional port filters, e.g.
 *   `{ filters: [{ usbVendorId: 0x2341 }] }`.
 * @returns {Promise<SerialPort>}
 */
export async function requestPort(options = {}) {
  if (!isWebSerialAvailable()) {
    throw new Error(WEBSERIAL_NOT_AVAILABLE_MSG)
  }
  return navigator.serial.requestPort(options)
}

// ── SerialReader ──────────────────────────────────────────────────────────────

/**
 * Async-iterable line reader over a WebSerial port.
 *
 * @example
 * const port = await requestPort()
 * for await (const line of new SerialReader(port, 9600)) {
 *   appendToMonitor(line)
 * }
 */
export class SerialReader {
  /**
   * @param {SerialPort} port - An open or unopened SerialPort object.
   * @param {number} [baud=115200] - Baud rate to pass to `port.open()`.
   */
  constructor(port, baud = 115200) {
    if (!isWebSerialAvailable()) {
      throw new Error(WEBSERIAL_NOT_AVAILABLE_MSG)
    }
    this._port = port
    this._baud = baud
  }

  /**
   * Iterate decoded lines. Opens the port on first call, closes on exit.
   * @returns {AsyncGenerator<string>}
   */
  async *[Symbol.asyncIterator]() {
    const port = this._port
    const baud = this._baud

    // Open the port (no-op if already open — SerialPort tracks its own state)
    if (!port.readable) {
      await port.open({ baudRate: baud })
    }

    const decoder = new TextDecoderStream()
    const readable = port.readable.pipeThrough(decoder)
    const reader = readable.getReader()

    // Buffer incomplete lines across chunks
    let buffer = ''

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += value
        const lines = buffer.split('\n')
        // The last element may be an incomplete line — keep it in the buffer
        buffer = lines.pop() ?? ''

        for (const raw of lines) {
          const line = raw.replace(/\r$/, '').trim()
          if (line.length > 0) {
            yield line
          }
        }
      }

      // Flush any remaining content when the stream closes
      if (buffer.trim().length > 0) {
        yield buffer.trim()
      }
    } finally {
      try {
        reader.releaseLock()
      } catch (_) {
        // already released
      }
      try {
        await port.close()
      } catch (_) {
        // port may already be closed
      }
    }
  }
}
