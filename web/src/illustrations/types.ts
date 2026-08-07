// types.ts — shared prop shape for the sector illustration library (T-508).
//
// Every per-sector illustration (mechanical.tsx, electronics.tsx, ...) is a small,
// stateless, stroke-based SVG component sharing the exact same public surface:
// an optional `className` forwarded to the <svg>, and an optional `size` (px,
// applied to both width and height, default 120 — see SECTOR_ILLUSTRATIONS'
// shared viewBox="0 0 120 120" convention in SectorIllustration.tsx).
//
// Not a domain type (nothing here comes from src/types/geometry.ts etc.), so it
// lives locally in this presentational-only slice rather than in the shared barrel.
export interface IllustrationProps {
  className?: string
  size?: number
  /**
   * Forwarded by SectorIllustration's router for CSS/test hooks. No individual
   * illustration destructures or re-forwards it today (pre-existing behaviour,
   * unchanged by this migration) — declared here only so passing it through
   * `<Component {...} data-sector={sector} />` type-checks.
   */
  'data-sector'?: string
}
