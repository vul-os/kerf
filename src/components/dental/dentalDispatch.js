/**
 * dentalDispatch.js — pure payload-builder helpers shared by the dental panels.
 *
 * Keeping payload construction out of JSX makes it:
 *   1. Unit-testable without a DOM or @testing-library/react.
 *   2. Easy to validate that the correct tool names + required fields are present
 *      before the network call.
 */

// ---------------------------------------------------------------------------
// dental_crown_design payload
// ---------------------------------------------------------------------------

/**
 * Build the POST body for a `dental_crown_design` tool call.
 *
 * @param {object} opts
 * @param {number[][]} opts.margin_line        — 3-D polygon (≥3 pts)
 * @param {number[]}   opts.opposing_cusp_heights_mm — cusp heights (≥1 val)
 * @param {string}     [opts.material]         — default 'zirconia'
 * @param {number}     [opts.occlusal_clearance_mm] — default 0.3
 * @param {number}     [opts.n_cusps]          — 2 or 4, default 2
 * @param {number}     [opts.cusp_depth_fraction] — 0.10-0.30, default 0.20
 * @returns {{ tool: string, args: object }}
 */
export function buildCrownDesignPayload({
  margin_line,
  opposing_cusp_heights_mm,
  material = 'zirconia',
  occlusal_clearance_mm = 0.3,
  n_cusps = 2,
  cusp_depth_fraction = 0.20,
}) {
  if (!Array.isArray(margin_line) || margin_line.length < 3) {
    throw new Error('margin_line must be an array with at least 3 points')
  }
  if (!Array.isArray(opposing_cusp_heights_mm) || opposing_cusp_heights_mm.length < 1) {
    throw new Error('opposing_cusp_heights_mm must be a non-empty array')
  }
  return {
    tool: 'dental_crown_design',
    args: {
      margin_line,
      opposing_cusp_heights_mm,
      material: String(material),
      occlusal_clearance_mm: Number(occlusal_clearance_mm),
      n_cusps: Number(n_cusps),
      cusp_depth_fraction: Number(cusp_depth_fraction),
    },
  }
}

// ---------------------------------------------------------------------------
// dental_surgical_guide payload (implant placement + surgical guide)
// ---------------------------------------------------------------------------

/**
 * Build the POST body for a `dental_surgical_guide` tool call.
 *
 * @param {object} opts
 * @param {number[][]} opts.jaw_surface_pts — jaw surface points (≥3 pts)
 * @param {Array<{
 *   position: number[],
 *   axis_direction: number[],
 *   diameter_mm?: number,
 *   length_mm?: number
 * }>} opts.implants — at least 1 implant spec
 * @returns {{ tool: string, args: object }}
 */
export function buildSurgicalGuidePayload({ jaw_surface_pts, implants }) {
  if (!Array.isArray(jaw_surface_pts) || jaw_surface_pts.length < 3) {
    throw new Error('jaw_surface_pts must be an array with at least 3 points')
  }
  if (!Array.isArray(implants) || implants.length < 1) {
    throw new Error('implants must be a non-empty array')
  }
  const normalised = implants.map((imp) => ({
    position: imp.position,
    axis_direction: imp.axis_direction,
    diameter_mm: imp.diameter_mm != null ? Number(imp.diameter_mm) : 4.0,
    length_mm: imp.length_mm != null ? Number(imp.length_mm) : 10.0,
  }))
  return {
    tool: 'dental_surgical_guide',
    args: {
      jaw_surface_pts,
      implants: normalised,
    },
  }
}
