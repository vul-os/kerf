/**
 * kerf-sdk — TypeScript SDK for Kerf (https://kerf.sh).
 *
 * Quickstart:
 *   import { fromEnv } from 'kerf-sdk'
 *   const k = fromEnv()
 *   const files = await k.files.list('<project-id>')
 *
 * Auth: set KERF_API_TOKEN (and optionally KERF_API_URL) in your environment,
 * or pass token/baseUrl explicitly to connect().
 */

export { Kerf, KerfError } from "./client.js";
export type { RpcError, RpcResponse } from "./client.js";
export { loadToken, loadUrl, DEFAULT_URL } from "./auth.js";

// DSTV NC1 steel-fabrication export (client-side writer + panel helpers)
export {
  fmtNum,
  writeNC1,
  parseNC1Header,
  createDefaultPanelState,
  runClientExport,
  downloadNC1,
  VALID_FACES,
  FACE_LABELS,
} from "./dstv_nc1.js";
export type {
  FaceId,
  NC1Hole,
  NC1ContourPoint,
  NC1Contour,
  NC1Stamp,
  NC1MemberSpec,
  NC1Header,
  DSTVExportPanelState,
} from "./dstv_nc1.js";

import { loadToken, loadUrl } from "./auth.js";
import { Kerf } from "./client.js";

/** Create a Kerf client with an explicit token and server URL. */
export function connect(
  token: string,
  baseUrl = "https://kerf.sh",
): Kerf {
  return new Kerf(token, baseUrl);
}

/** Create a Kerf client from KERF_API_TOKEN + KERF_API_URL env vars. */
export function fromEnv(): Kerf {
  return new Kerf(loadToken(), loadUrl());
}
