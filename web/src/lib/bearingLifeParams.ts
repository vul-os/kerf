/**
 * Formatting and request-parameter builders for the bearing life panel.
 *
 * Split out of BearingLifePanel.tsx: Vite fast refresh only works when a
 * module exports components alone, so one non-component export disables hot
 * reload for the whole component.
 */

export interface BearingFormState {
  [key: string]: string | boolean | undefined
}


export function fmtNum(v: number | null | undefined, dp = 2): string {
  if (v == null || !isFinite(v)) return '—'
  return v.toFixed(dp)
}


export function resultTagClass(ok: boolean | null): string {
  if (ok === true) return 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
  if (ok === false) return 'bg-red-500/20 text-red-300 border border-red-500/30'
  return 'bg-ink-800 text-ink-400'
}


export function buildSelectParams(s: BearingFormState) {
  return {
    series: s.series || '6200',
    Fr: parseFloat(s.Fr as string) || 0,
    Fa: parseFloat(s.Fa as string) || 0,
    n_rpm: parseFloat(s.n_rpm as string) || 0,
    Lh_min: parseFloat(s.Lh_min as string) || 20000,
    bearing_type: s.bearing_type || 'ball',
    a1: parseFloat(s.a1 as string) || 1.0,
    a23: parseFloat(s.a23 as string) || 1.0,
  }
}


export function buildLifeParams(s: BearingFormState) {
  return {
    C: parseFloat(s.C as string) || 0,
    P: parseFloat(s.P as string) || 0,
    n_rpm: parseFloat(s.n_rpm as string) || 0,
    bearing_type: s.bearing_type || 'ball',
    a1: parseFloat(s.a1 as string) || 1.0,
    a23: parseFloat(s.a23 as string) || 1.0,
  }
}


export function buildIso16281Params(s: BearingFormState) {
  return {
    C: parseFloat(s.C as string) || 0,
    P: parseFloat(s.P as string) || 0,
    n_rpm: parseFloat(s.n_rpm as string) || 0,
    kappa: parseFloat(s.kappa as string) || 1.0,
    eC: parseFloat(s.eC as string) || 0.5,
    Cu_N: parseFloat(s.Cu_N as string) || 0,
    bearing_type: s.bearing_type || 'ball',
    a1: parseFloat(s.a1 as string) || 1.0,
    fatigue_limited: s.fatigue_limited ?? false,
  }
}
