"""
tools_pointcloud_plant.py — LLM tools for plant/infrastructure point-cloud
(laser scan) integration.

These tools target the brownfield / as-built use case for process plant,
refinery, piping, and infrastructure — complementing the surveying/terrain
pointcloud tools already in tools_parcels_pointcloud_sheets.py.

Tools
-----
  pointcloud_import          — import PLY (ASCII + binary), XYZ, or LAS;
                               parse, stats, optional voxel downsample and SOR
                               outlier removal; return AABB + reduced cloud.

  pointcloud_deviation_check — compare a scanned point cloud to a CAD mesh
                               (vertices + face indices); return per-point
                               signed deviation distances + heatmap statistics
                               for scan-vs-model QA / as-built verification.

  pointcloud_fit_plane       — RANSAC plane extraction from a subset of the
                               scan for as-built pipe-rack / floor / wall
                               detection.

References
----------
Fischler & Bolles (1981). RANSAC. Commun. ACM 24(6):381-395.
Rusu & Cousins (2011). PCL. IEEE ICRA. (SOR, VoxelGrid)
Eberly (2003). Point-to-triangle distance. Geometric Tools.
ASPRS LAS Spec 1.4-R15.
"""

from __future__ import annotations

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_civil._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ===========================================================================
# Tool: pointcloud_import
# ===========================================================================

pointcloud_import_spec = ToolSpec(
    name="pointcloud_import",
    description=(
        "Import a laser-scan point cloud for plant/infrastructure brownfield work.\n"
        "\n"
        "Supported formats:\n"
        "  'xyz'        — space/tab/comma XYZ text (inline data or file path)\n"
        "  'ply_ascii'  — ASCII PLY with x y z vertex properties\n"
        "  'ply_binary' — binary PLY (little-endian or big-endian; file path)\n"
        "  'las'        — LAS/LAZ file path (requires laspy >= 2.0)\n"
        "\n"
        "Processing pipeline (optional):\n"
        "  1. voxel_cell_size > 0 → voxel-grid downsample (Zhang 2003)\n"
        "  2. sor_k > 0           → Statistical Outlier Removal (Rusu & Cousins 2011)\n"
        "\n"
        "Returns cloud stats (AABB, n_points, density) plus the processed\n"
        "point array as a JSON-serialisable list (truncated to max_return_pts\n"
        "for payload size management).\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "format         : 'xyz', 'ply_ascii', 'ply_binary', or 'las'\n"
        "data           : inline XYZ/PLY text, or file path for binary/LAS formats\n"
        "voxel_cell_size: float — voxel edge length (m) for downsampling; 0 = skip\n"
        "sor_k          : int   — SOR nearest-neighbour count; 0 = skip\n"
        "sor_std_ratio  : float — SOR std-ratio threshold (default 2.0)\n"
        "max_return_pts : int   — max points to include in response payload\n"
        "                         (default 5000; set 0 to omit points array)\n"
        "\n"
        "Returns\n"
        "-------\n"
        "ok, n_points_raw, n_points_out, aabb (min/max/size xyz, diagonal_m,\n"
        "volume_m3, centroid), stats (x/y/z range, density_per_m2),\n"
        "points (list of [x,y,z]) up to max_return_pts.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["xyz", "ply_ascii", "ply_binary", "las"],
                "description": "Input point-cloud format.",
            },
            "data": {
                "type": "string",
                "description": "Inline XYZ/PLY text or file path (for binary/LAS).",
            },
            "voxel_cell_size": {
                "type": "number",
                "description": "Voxel grid cell size (m) for downsampling; 0 = skip.",
                "default": 0.0,
            },
            "sor_k": {
                "type": "integer",
                "description": "SOR k nearest neighbours; 0 = skip outlier removal.",
                "default": 0,
                "minimum": 0,
            },
            "sor_std_ratio": {
                "type": "number",
                "description": "SOR std-deviation multiplier threshold.",
                "default": 2.0,
            },
            "max_return_pts": {
                "type": "integer",
                "description": "Max points to include in the response payload (0 = omit).",
                "default": 5000,
                "minimum": 0,
            },
        },
        "required": ["format", "data"],
    },
)


async def run_pointcloud_import(params: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_civil.pointcloud import (
            read_xyz,
            read_ply_ascii,
            read_ply_binary,
            read_las,
            voxel_downsample,
            statistical_outlier_removal,
            point_cloud_stats,
            point_cloud_aabb,
        )

        fmt = params.get("format", "xyz")
        data = params.get("data", "")
        voxel = float(params.get("voxel_cell_size", 0.0))
        sor_k = int(params.get("sor_k", 0))
        sor_std = float(params.get("sor_std_ratio", 2.0))
        max_pts = int(params.get("max_return_pts", 5000))

        # --- Ingest ---
        if fmt == "xyz":
            pts = read_xyz(data)
        elif fmt == "ply_ascii":
            pts = read_ply_ascii(data)
        elif fmt == "ply_binary":
            pts = read_ply_binary(data)
        elif fmt == "las":
            pts = read_las(data)
        else:
            return err_payload(f"unknown format {fmt!r}", "BAD_ARGS")

        n_raw = int(len(pts))

        # --- Optional voxel downsample ---
        if voxel > 0:
            pts = voxel_downsample(pts, voxel)

        # --- Optional SOR outlier removal ---
        if sor_k > 0:
            pts = statistical_outlier_removal(pts, k=sor_k, std_ratio=sor_std)

        n_out = int(len(pts))
        stats = point_cloud_stats(pts)
        aabb = point_cloud_aabb(pts)

        # --- Build response points (truncated) ---
        pts_out = None
        if max_pts > 0:
            stride = max(1, n_out // max_pts)
            sample = pts[::stride, :3]
            pts_out = sample.tolist()

        payload = {
            "ok": True,
            "format": fmt,
            "n_points_raw": n_raw,
            "n_points_out": n_out,
            "reduction_pct": round((1.0 - n_out / max(n_raw, 1)) * 100, 2),
            "aabb": aabb,
            "stats": stats,
        }
        if pts_out is not None:
            payload["points"] = pts_out
            payload["points_count_returned"] = len(pts_out)

        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "POINTCLOUD_IMPORT_ERROR")


# ===========================================================================
# Tool: pointcloud_deviation_check
# ===========================================================================

pointcloud_deviation_check_spec = ToolSpec(
    name="pointcloud_deviation_check",
    description=(
        "Compare a scanned point cloud to a CAD mesh for scan-vs-model deviation.\n"
        "\n"
        "Computes per-point signed distance from each scan point to the nearest\n"
        "triangle of the reference mesh.  Sign is positive (protrusion) when the\n"
        "point is on the outward-normal side of the nearest face, negative\n"
        "(depression/gap) when inside.\n"
        "\n"
        "Use for:\n"
        "  • As-built / as-designed brownfield comparison\n"
        "  • Clash and gap detection against piping or structural CAD model\n"
        "  • Corrosion / deformation inspection (positive deviation = swelling)\n"
        "\n"
        "Method: per-point nearest-triangle distance (Eberly 2003 barycentric\n"
        "parameterisation); sign from face-normal dot product.\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "points    : list of [x, y, z] — scan point cloud (metres)\n"
        "vertices  : list of [x, y, z] — mesh vertex positions\n"
        "triangles : list of [i, j, k] — mesh face vertex indices\n"
        "tolerance_m : float — tolerance for pass/fail classification (default 0.01 m)\n"
        "\n"
        "Returns\n"
        "-------\n"
        "ok, n_points, n_triangles,\n"
        "deviation_min_m, deviation_max_m, deviation_mean_m, deviation_rms_m,\n"
        "n_within_tolerance, fraction_within_pct,\n"
        "n_protrusions, n_depressions,\n"
        "histogram (10 bins), deviations (list of floats per point),\n"
        "heatmap_colors (list of [R,G,B] 0-255 for viewport rendering).\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": "Scan point cloud as [[x,y,z], …].",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 1,
            },
            "vertices": {
                "type": "array",
                "description": "Mesh vertex positions as [[x,y,z], …].",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 3,
            },
            "triangles": {
                "type": "array",
                "description": "Mesh triangle face indices as [[i,j,k], …].",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 1,
            },
            "tolerance_m": {
                "type": "number",
                "description": "Tolerance for pass/fail classification (m).",
                "default": 0.01,
            },
        },
        "required": ["points", "vertices", "triangles"],
    },
)


async def run_pointcloud_deviation_check(params: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_civil.pointcloud import cloud_to_mesh_deviation

        pts_raw = params.get("points", [])
        verts_raw = params.get("vertices", [])
        tris_raw = params.get("triangles", [])
        tolerance = float(params.get("tolerance_m", 0.01))

        if len(pts_raw) == 0:
            return err_payload("points must be non-empty", "BAD_ARGS")
        if len(verts_raw) < 3:
            return err_payload("vertices must have >= 3 entries", "BAD_ARGS")
        if len(tris_raw) == 0:
            return err_payload("triangles must be non-empty", "BAD_ARGS")

        pts = np.array(pts_raw, dtype=np.float64)
        verts = np.array(verts_raw, dtype=np.float64)
        tris = np.array(tris_raw, dtype=np.int64)

        deviations = cloud_to_mesh_deviation(pts, verts, tris)

        n_pts = len(deviations)
        dev_min = float(deviations.min())
        dev_max = float(deviations.max())
        dev_mean = float(deviations.mean())
        dev_rms = float(np.sqrt((deviations ** 2).mean()))

        abs_dev = np.abs(deviations)
        n_within = int((abs_dev <= tolerance).sum())
        n_protrusion = int((deviations > tolerance).sum())
        n_depression = int((deviations < -tolerance).sum())

        # Histogram (10 bins)
        hist, bin_edges = np.histogram(deviations, bins=10)
        histogram = [
            {
                "bin_low": round(float(bin_edges[i]), 6),
                "bin_high": round(float(bin_edges[i + 1]), 6),
                "count": int(hist[i]),
            }
            for i in range(len(hist))
        ]

        # Heatmap colours: blue (negative) → green (zero) → red (positive)
        # Normalise to [-1, 1] range clamped to [-dev_range, +dev_range]
        dev_range = max(abs(dev_min), abs(dev_max), 1e-9)

        def _dev_to_rgb(d: float) -> list[int]:
            t = max(-1.0, min(1.0, d / dev_range))
            if t < 0:
                # blue → green
                r = 0
                g = int(255 * (1 + t))
                b = int(255 * (-t))
            else:
                # green → red
                r = int(255 * t)
                g = int(255 * (1 - t))
                b = 0
            return [r, g, b]

        heatmap_colors = [_dev_to_rgb(float(d)) for d in deviations]

        return ok_payload({
            "ok": True,
            "n_points": n_pts,
            "n_triangles": len(tris),
            "deviation_min_m": round(dev_min, 6),
            "deviation_max_m": round(dev_max, 6),
            "deviation_mean_m": round(dev_mean, 6),
            "deviation_rms_m": round(dev_rms, 6),
            "tolerance_m": tolerance,
            "n_within_tolerance": n_within,
            "fraction_within_pct": round(n_within / max(n_pts, 1) * 100, 2),
            "n_protrusions": n_protrusion,
            "n_depressions": n_depression,
            "histogram": histogram,
            "deviations": deviations.tolist(),
            "heatmap_colors": heatmap_colors,
        })

    except Exception as exc:
        return err_payload(str(exc), "POINTCLOUD_DEVIATION_ERROR")


# ===========================================================================
# Tool: pointcloud_fit_plane
# ===========================================================================

pointcloud_fit_plane_spec = ToolSpec(
    name="pointcloud_fit_plane",
    description=(
        "Fit a plane to a point cloud using RANSAC for as-built extraction.\n"
        "\n"
        "Use for:\n"
        "  • Detect floors, walls, pipe racks, vessel faces from laser scan\n"
        "  • As-built plane orientation vs. design (check levelness / plumb)\n"
        "  • Segment the inlier/outlier subsets for further processing\n"
        "\n"
        "Method: Fischler & Bolles (1981) RANSAC — iteratively sample 3\n"
        "random points, fit plane ax+by+cz+d=0 with (a,b,c) unit normal;\n"
        "count inliers within threshold distance; refine by SVD least-squares\n"
        "on inlier set.\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "points         : list of [x, y, z] — input point cloud (m)\n"
        "threshold_m    : inlier distance threshold (m; default 0.02 m)\n"
        "max_iterations : RANSAC iteration budget (default 1000)\n"
        "min_inliers    : minimum inliers for a valid plane (default 10)\n"
        "seed           : random seed for reproducibility (optional)\n"
        "\n"
        "Returns\n"
        "-------\n"
        "ok, success (bool), normal [a,b,c], d (plane constant),\n"
        "inlier_count, inlier_fraction, rmse_m, centroid [x,y,z],\n"
        "iterations (RANSAC iters run),\n"
        "dip_deg (inclination from horizontal), strike_deg (azimuth of dip),\n"
        "inlier_mask (list of bool — per input point).\n"
        "\n"
        "Plane orientation diagnostics:\n"
        "  level_check : 'PASS' if |dip_deg| < 1° (floor/horizontal surface)\n"
        "  plumb_check : 'PASS' if dip_deg > 89° (wall/vertical surface)\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": "Point cloud as [[x,y,z], …].",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 3,
            },
            "threshold_m": {
                "type": "number",
                "description": "RANSAC inlier distance threshold (m).",
                "default": 0.02,
            },
            "max_iterations": {
                "type": "integer",
                "description": "RANSAC iteration budget.",
                "default": 1000,
                "minimum": 10,
            },
            "min_inliers": {
                "type": "integer",
                "description": "Minimum inlier count for a valid plane.",
                "default": 10,
                "minimum": 3,
            },
            "seed": {
                "type": "integer",
                "description": "RNG seed for reproducibility.",
            },
        },
        "required": ["points"],
    },
)


async def run_pointcloud_fit_plane(params: dict, ctx: "ProjectCtx") -> str:
    try:
        import math
        import numpy as np
        from kerf_civil.pointcloud import ransac_fit_plane

        pts_raw = params.get("points", [])
        threshold = float(params.get("threshold_m", 0.02))
        max_iter = int(params.get("max_iterations", 1000))
        min_inl = int(params.get("min_inliers", 10))
        seed = params.get("seed")
        if seed is not None:
            seed = int(seed)

        if len(pts_raw) < 3:
            return err_payload("points must have >= 3 entries", "BAD_ARGS")

        pts = np.array(pts_raw, dtype=np.float64)

        result = ransac_fit_plane(
            pts,
            threshold=threshold,
            max_iterations=max_iter,
            min_inliers=min_inl,
            seed=seed,
        )

        # Derived diagnostics
        nx, ny, nz = result["normal"]
        # Dip angle: angle from horizontal plane (0° = horizontal, 90° = vertical)
        dip_deg = round(math.degrees(math.asin(abs(nz))), 2)
        # Strike: azimuth of the dip direction (compass bearing of steepest slope)
        if abs(nx) > 1e-9 or abs(ny) > 1e-9:
            strike_deg = round(math.degrees(math.atan2(nx, ny)) % 360, 2)
        else:
            strike_deg = 0.0

        level_check = "PASS" if dip_deg > 89.0 else "FAIL"   # vertical
        plumb_check = "PASS" if dip_deg < 1.0 else "FAIL"    # horizontal

        result["ok"] = True
        result["dip_deg"] = dip_deg
        result["strike_deg"] = strike_deg
        result["level_check"] = level_check  # horizontal (floor)
        result["plumb_check"] = plumb_check  # vertical (wall)
        result["threshold_m"] = threshold

        return ok_payload(result)

    except Exception as exc:
        return err_payload(str(exc), "POINTCLOUD_FIT_PLANE_ERROR")


# ===========================================================================
# TOOLS list consumed by plugin
# ===========================================================================

TOOLS = [
    (
        "pointcloud_import",
        pointcloud_import_spec,
        run_pointcloud_import,
    ),
    (
        "pointcloud_deviation_check",
        pointcloud_deviation_check_spec,
        run_pointcloud_deviation_check,
    ),
    (
        "pointcloud_fit_plane",
        pointcloud_fit_plane_spec,
        run_pointcloud_fit_plane,
    ),
]
