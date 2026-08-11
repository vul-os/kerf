/**
 * Display formatting for the Settings usage panel.
 *
 * Separate from Settings.tsx because that file exports React components and
 * fast refresh only works when a module exports components alone.
 */

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  moonshot: 'Moonshot',
  gemini: 'Google Gemini',
}

/** Display name for a provider id, capitalising anything unrecognised. */
export function providerLabel(id: string): string {
  return PROVIDER_LABELS[id] || id.charAt(0).toUpperCase() + id.slice(1)
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`
  return String(n)
}

export function formatUsd(n: number): string {
  if (n === 0) return '$0.00'
  // Sub-cent totals are normal for a few short turns; rounding them to $0.00
  // makes the meter look broken.
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

export function formatBytes(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`
  if (abs >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`
  if (abs >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}
