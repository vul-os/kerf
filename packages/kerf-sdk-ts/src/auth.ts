/**
 * Env-var loading for Kerf SDK auth.
 *
 * KERF_API_TOKEN — required; must start with kerf_sk_
 * KERF_API_URL   — optional; defaults to https://kerf.sh
 */

export const DEFAULT_URL = "https://kerf.sh";

export function loadToken(): string {
  const token = (process.env["KERF_API_TOKEN"] ?? "").trim();
  if (!token) {
    throw new Error(
      "KERF_API_TOKEN is not set. " +
        "Generate one from workspace settings and export it.",
    );
  }
  return token;
}

export function loadUrl(): string {
  return (process.env["KERF_API_URL"] ?? DEFAULT_URL).replace(/\/$/, "");
}
