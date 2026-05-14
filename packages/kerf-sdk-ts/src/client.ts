/**
 * fetch-based JSON-RPC 2.0 client for the Kerf /v1/rpc endpoint.
 *
 * Auth: Bearer kerf_sk_* token in Authorization header.
 * Envelope: { jsonrpc: "2.0", method, params, id: "<uuid>" }
 */

import {
  FilesNamespace,
  EquationsNamespace,
  ConfigurationsNamespace,
  RevisionsNamespace,
  DocsNamespace,
} from "./tools.js";

export interface RpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface RpcResponse<T = unknown> {
  jsonrpc: "2.0";
  id: string | null;
  result?: T;
  error?: RpcError;
}

/** Thrown when the server returns a JSON-RPC error object. */
export class KerfError extends Error {
  readonly code: number;
  readonly data?: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = "KerfError";
    this.code = code;
    this.data = data;
  }
}

export class Kerf {
  private readonly _baseUrl: string;
  private readonly _headers: Record<string, string>;

  readonly files: FilesNamespace;
  readonly equations: EquationsNamespace;
  readonly configurations: ConfigurationsNamespace;
  readonly revisions: RevisionsNamespace;
  readonly docs: DocsNamespace;

  constructor(token: string, baseUrl: string) {
    this._baseUrl = baseUrl.replace(/\/$/, "");
    this._headers = {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
    };

    this.files = new FilesNamespace(this);
    this.equations = new EquationsNamespace(this);
    this.configurations = new ConfigurationsNamespace(this);
    this.revisions = new RevisionsNamespace(this);
    this.docs = new DocsNamespace(this);
  }

  /**
   * Send a single JSON-RPC 2.0 call and return the result.
   *
   * Throws KerfError on a JSON-RPC error response.
   * Throws on non-2xx HTTP status.
   */
  async invoke<T = unknown>(
    method: string,
    params: Record<string, unknown>,
  ): Promise<T> {
    const id = crypto.randomUUID();
    const payload = {
      jsonrpc: "2.0" as const,
      method,
      params,
      id,
    };

    const response = await fetch(`${this._baseUrl}/v1/rpc`, {
      method: "POST",
      headers: this._headers,
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const body = (await response.json()) as RpcResponse<T>;

    if (body.error != null) {
      throw new KerfError(
        body.error.code ?? -1,
        body.error.message ?? "unknown error",
        body.error.data,
      );
    }

    return body.result as T;
  }

  /**
   * AsyncDisposable — fetch is stateless so nothing to tear down.
   * Useful for `await using k = fromEnv()` in TypeScript 5.2+.
   */
  async [Symbol.asyncDispose](): Promise<void> {
    // no-op: fetch is connectionless
  }
}
