/**
 * Tests for the JSON-RPC client — asserts envelope shape, auth header,
 * error mapping, and namespace wrappers.
 *
 * Uses vi.stubGlobal to mock the global fetch so no real network traffic.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { connect, fromEnv, KerfError } from "../src/index.js";

const BASE = "https://kerf.sh";
const TOKEN = "kerf_sk_testtoken123";

/** Build a minimal successful fetch mock returning `result`. */
function mockFetch(result: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({ jsonrpc: "2.0", result, id: "mock-id" }),
  });
}

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchSpy = mockFetch([]);
  vi.stubGlobal("fetch", fetchSpy);
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env["KERF_API_TOKEN"];
  delete process.env["KERF_API_URL"];
});

// ---------------------------------------------------------------------------
// 1. Envelope shape
// ---------------------------------------------------------------------------
describe("invoke sends the correct JSON-RPC 2.0 envelope", () => {
  it("includes jsonrpc, method, params, and id", async () => {
    const k = connect(TOKEN, BASE);
    await k.invoke("files.list", { project_id: "proj-1" });

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];

    expect(url).toBe(`${BASE}/v1/rpc`);
    const body = JSON.parse(init.body as string);
    expect(body.jsonrpc).toBe("2.0");
    expect(body.method).toBe("files.list");
    expect(body.params).toEqual({ project_id: "proj-1" });
    expect(typeof body.id).toBe("string");
    expect(body.id.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// 2. Auth header
// ---------------------------------------------------------------------------
describe("invoke sets the Bearer auth header", () => {
  it("sends Authorization: Bearer <token>", async () => {
    const k = connect(TOKEN, BASE);
    await k.invoke("files.read", { project_id: "p", file_id: "f" });

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });
});

// ---------------------------------------------------------------------------
// 3. Error mapping
// ---------------------------------------------------------------------------
describe("error mapping", () => {
  it("throws KerfError when the server returns an RPC error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            jsonrpc: "2.0",
            error: { code: -32600, message: "project not found" },
            id: "mock-id",
          }),
      }),
    );

    const k = connect(TOKEN, BASE);
    await expect(
      k.invoke("files.list", { project_id: "missing" }),
    ).rejects.toSatisfy((err: unknown) => {
      return (
        err instanceof KerfError &&
        err.code === -32600 &&
        err.message === "project not found"
      );
    });
  });

  it("throws a plain Error on non-2xx HTTP status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: "Unauthorized",
        json: () => Promise.resolve({}),
      }),
    );

    const k = connect(TOKEN, BASE);
    await expect(
      k.invoke("files.list", { project_id: "p" }),
    ).rejects.toThrow("HTTP 401");
  });
});

// ---------------------------------------------------------------------------
// 4. Namespace wrapper
// ---------------------------------------------------------------------------
describe("namespace wrappers", () => {
  it("k.files.list() invokes files.list with project_id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            jsonrpc: "2.0",
            result: [{ id: "f1", name: "part.jscad", kind: "jscad", parent_id: null }],
            id: "mock-id",
          }),
      }),
    );

    const k = connect(TOKEN, BASE);
    const files = await k.files.list("proj-1");

    expect(files[0]?.name).toBe("part.jscad");

    const [, init] = (vi.mocked(fetch).mock.calls[0] as [string, RequestInit]);
    const body = JSON.parse(init.body as string);
    expect(body.method).toBe("files.list");
    expect(body.params.project_id).toBe("proj-1");
  });
});

// ---------------------------------------------------------------------------
// 5. fromEnv() reads env vars
// ---------------------------------------------------------------------------
describe("fromEnv()", () => {
  it("reads KERF_API_TOKEN and KERF_API_URL from the environment", async () => {
    process.env["KERF_API_TOKEN"] = "kerf_sk_envtoken";
    process.env["KERF_API_URL"] = BASE;

    const k = fromEnv();
    await k.files.list("p");

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer kerf_sk_envtoken");
  });
});

// ---------------------------------------------------------------------------
// 6. Missing token throws
// ---------------------------------------------------------------------------
describe("fromEnv() with missing token", () => {
  it("throws when KERF_API_TOKEN is not set", () => {
    // env var was deleted in afterEach; explicitly ensure absence
    delete process.env["KERF_API_TOKEN"];

    expect(() => fromEnv()).toThrow("KERF_API_TOKEN");
  });
});

// ---------------------------------------------------------------------------
// 7. AsyncDisposable / await using
// ---------------------------------------------------------------------------
describe("AsyncDisposable", () => {
  it("client has Symbol.asyncDispose and resolves cleanly", async () => {
    const k = connect(TOKEN, BASE);
    expect(typeof k[Symbol.asyncDispose]).toBe("function");
    // should not throw
    await expect(k[Symbol.asyncDispose]()).resolves.toBeUndefined();
  });
});
