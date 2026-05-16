# Scan-to-CAD Point Cloud Fitting

Pure-Python RANSAC-based primitive fitting for scan-to-CAD workflows. Ingests a
raw point cloud, fits planes, spheres, and cylinders using RANSAC, and segments
a mixed cloud into multiple primitives. No OCC dependency. Units: any consistent
unit (millimetres or metres) — all inputs/outputs use the same unit as the cloud.

---

## When to use

Reach for this module when the user asks about:

- fitting a plane, sphere, or cylinder to 3D scan data or a point cloud
- extracting geometric primitives from a scanned part or environment
- segmenting a mixed scan into planes, cylinders, and spheres
- as-built geometry extraction from a LiDAR or structured-light scan
- finding the axis and radius of a scanned pipe or cylinder
- fitting a best-fit plane to a scanned flat surface
- reverse engineering primitives from a point cloud for CAD reconstruction

---

## Tools

### `scan_load`

Ingest a raw point cloud (list of `[x, y, z]` triples) and return summary
statistics: point count, axis-aligned bounding box, and centroid. Use this as the
first step to validate the cloud before fitting.

### `scan_fit_plane`

Fit a plane to a point cloud using RANSAC + PCA least-squares normal estimation.
Returns unit normal, plane offset `d` (normal · p = d), centroid, inlier ratio,
and RMS residual. Deterministic: same points + same seed → same result.

### `scan_fit_sphere`

Fit a sphere to a point cloud using RANSAC + algebraic least squares. Requires
minimum 4 points. Returns centre, radius, inlier ratio, and residual. Deterministic
with fixed seed.

### `scan_fit_cylinder`

Fit a cylinder to a point cloud using RANSAC + PCA axis + 2-D algebraic circle
fit on projected points. Requires minimum 6 points. Returns unit axis vector,
axis point, radius, inlier ratio, and residual. Deterministic with fixed seed.

### `scan_segment`

Greedy multi-primitive segmentation of a mixed point cloud. Iteratively finds the
dominant primitive (plane, sphere, or cylinder), peels off its inliers, and
repeats until no primitive exceeds `min_inlier_ratio` of remaining points. Returns
a list of segments each with primitive type, fit parameters, and inlier count,
plus unassigned point count. Use `primitives` to restrict which types are searched.

---

## Example

**User ask:** "I scanned a pipe with a flat endplate. Can you extract the pipe axis
and the flat face from this cloud?"

```
1. scan_load  points:[[x,y,z], …]
   → {count:1500, bbox:{…}, centroid:[…]}

2. scan_segment  points:[same cloud]  primitives:["plane","cylinder"]
                 threshold:0.005  min_inlier_ratio:0.15
   → {segments:[
        {primitive:"cylinder", axis:[0,0,1], axis_point:[0.05,0.05,0],
         radius:0.025, inlier_count:900, residual:0.003},
        {primitive:"plane", normal:[0,0,1], d:0.5,
         inlier_count:480, residual:0.002}
      ],
      unassigned_count:120}
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- RANSAC is deterministic: same `points` + same `seed` → same result every time.
- Default RANSAC: 200 iterations, inlier threshold 0.01 (in input units), seed 42.
- `scan_segment` uses greedy peeling — order of primitives returned reflects
  dominance (largest inlier set found first).
- All tools return `{ok:false, reason:...}` on bad input — never raise.
