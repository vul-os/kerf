// PointCloudWrapper.jsx
// Panel registry wrapper for the PointCloudPanel (laser-scan / point-cloud viewport).
//
// content JSON shape (all fields optional):
//   {
//     points?:         [[x,y,z], …]          — scan point positions (m)
//     deviations?:     [d0, d1, …]           — per-point signed deviation (m)
//     heatmapColors?:  [[R,G,B], …]          — pre-computed heatmap colours
//     stats?:          { n_points, density_per_m2, … }
//     aabb?:           { min_x, max_x, … }
//     planeResult?:    { success, normal, d, inlier_count, … }
//     pipeSegments?:   [ { axis_point, axis_direction, radius_m, diameter_m,
//                          nominal_dn_mm, centerline_start, centerline_end,
//                          length_m, inlier_count }, … ]
//     pipeRuns?:       [ { run_id, segment_ids, nominal_dn_mm, centerlines,
//                          elbows, total_length_m, diameter_m }, … ]
//     asbuiltOverlay?: { n_asbuilt, n_design, n_matched, matches, summary, … }
//     tolerance_m?:    number                — deviation tolerance (m)
//     width?:          number                — canvas pixel width
//     height?:         number                — canvas pixel height
//   }
//
// These keys match the output fields of the pointcloud_import,
// pointcloud_deviation_check, pointcloud_fit_plane,
// pointcloud_detect_pipes, and pointcloud_asbuilt_overlay LLM tools.

import Panel from '../../../components/civil/PointCloudPanel.jsx'

const DEFAULTS = {
  points: null,
  deviations: null,
  heatmapColors: null,
  stats: null,
  aabb: null,
  planeResult: null,
  pipeSegments: null,
  pipeRuns: null,
  asbuiltOverlay: null,
  tolerance_m: 0.01,
  width: 720,
  height: 480,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function PointCloudWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
