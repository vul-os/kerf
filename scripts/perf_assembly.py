#!/usr/bin/env python3
"""
scripts/perf_assembly.py — Large-assembly performance harness (T-320).

Loads N synthetic parts (N ∈ {100, 1k, 5k, 10k}), runs the LOD decimation
pipeline, and reports:

  - time_to_interactive_ms  : time to load + parse + LOD-select all N components
  - fps_proxy               : modelled FPS estimate (see Methodology below)
  - memory_peak_kb          : peak RSS delta during the run (via tracemalloc)
  - triangle_count_full     : total triangles if all parts were rendered at full res
  - triangle_count_lod      : total triangles after LOD proxy substitution
  - draw_calls_full         : draw call count at full resolution
  - draw_calls_lod          : draw call count after LOD

Methodology (modelled metrics — no GPU available in CI)
--------------------------------------------------------
Triangle count drives GPU rasterisation throughput.  Modern desktop GPUs sustain
~1–2 Gtri/s at 1080p.  Using a conservative 500 Mtri/s budget and a 16 ms frame
budget (60 FPS target):

    max_tris_per_frame = 500e6 * 0.016 = 8_000_000

Modelled FPS = min(60, 8_000_000 / max(1, triangle_count))

Draw calls are modelled as one per unique part (instanced), capped at the
component count for un-instanced assemblies.  Each draw call adds ~0.03 ms
of CPU overhead (driver overhead estimate); we fold that into the modelled FPS.

These are explicitly documented estimates, not measured GPU timings.  The
decimation ratio and frustum-cull logic are directly verified by the unit tests
in tests/perf/test_large_assembly.py.

Usage
-----
    python scripts/perf_assembly.py
    python scripts/perf_assembly.py --json          # machine-readable JSON to stdout
    python scripts/perf_assembly.py --json > out.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import tracemalloc
from typing import Any

# ---------------------------------------------------------------------------
# Synthetic part generator
# ---------------------------------------------------------------------------

def _make_icosphere(radius: float = 1.0, subdivisions: int = 2) -> dict:
    """Return a simple icosphere as {verts, faces}.

    verts: list of [x, y, z]
    faces: list of [i, j, k]

    Subdivisions controls density: 0 → 20 faces, 1 → 80, 2 → 320, 3 → 1280.
    We use subdivisions=2 for the LOD-full mesh (~320 tris) and
    subdivisions=0 for the proxy (~20 tris) so the ratio is ~6%.
    """
    # Base icosahedron
    t = (1.0 + math.sqrt(5.0)) / 2.0
    raw_verts = [
        [-1,  t,  0], [ 1,  t,  0], [-1, -t,  0], [ 1, -t,  0],
        [ 0, -1,  t], [ 0,  1,  t], [ 0, -1, -t], [ 0,  1, -t],
        [ t,  0, -1], [ t,  0,  1], [-t,  0, -1], [-t,  0,  1],
    ]
    # Normalise to unit sphere
    verts = []
    for v in raw_verts:
        n = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
        verts.append([v[0]/n * radius, v[1]/n * radius, v[2]/n * radius])

    faces = [
        [0,11,5],[0,5,1],[0,1,7],[0,7,10],[0,10,11],
        [1,5,9],[5,11,4],[11,10,2],[10,7,6],[7,1,8],
        [3,9,4],[3,4,2],[3,2,6],[3,6,8],[3,8,9],
        [4,9,5],[2,4,11],[6,2,10],[8,6,7],[9,8,1],
    ]

    for _ in range(subdivisions):
        new_faces = []
        midpoints: dict[tuple[int,int], int] = {}

        def midpoint(a: int, b: int) -> int:
            key = (min(a, b), max(a, b))
            if key not in midpoints:
                va, vb = verts[a], verts[b]
                mx = (va[0]+vb[0])/2
                my = (va[1]+vb[1])/2
                mz = (va[2]+vb[2])/2
                nn = math.sqrt(mx**2+my**2+mz**2)
                midpoints[key] = len(verts)
                verts.append([mx/nn*radius, my/nn*radius, mz/nn*radius])
            return midpoints[key]

        for f in faces:
            a, b, c = f
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            new_faces += [[a,ab,ca],[b,bc,ab],[c,ca,bc],[ab,bc,ca]]
        faces = new_faces

    return {"verts": verts, "faces": faces}


# Pre-generate the two LOD levels once — all synthetic "parts" share geometry.
_FULL_MESH = _make_icosphere(radius=1.0, subdivisions=2)   # 320 tris
_PROXY_MESH = _make_icosphere(radius=1.0, subdivisions=0)  # 20 tris
_TRIS_FULL = len(_FULL_MESH["faces"])
_TRIS_PROXY = len(_PROXY_MESH["faces"])


# ---------------------------------------------------------------------------
# LOD selection (mirrors src/lib/lod.js angular-size logic in Python)
# ---------------------------------------------------------------------------

# Angular-size threshold in radians below which we use the proxy mesh.
# Matches the JS constant LOD_ANGULAR_THRESHOLD = 0.02 rad.
LOD_ANGULAR_THRESHOLD = 0.02
LOD_THRESHOLD_COUNT = 500  # fallback: always proxy above this many visible parts


def angular_size(bbox_radius: float, distance: float) -> float:
    """Subtended angle of a sphere with *bbox_radius* at *distance* from camera."""
    if distance <= 0:
        return math.pi
    return 2.0 * math.atan(bbox_radius / max(distance, 1e-9))


def select_lod(visible_index: int, distance: float, bbox_radius: float) -> str:
    """Return 'full' or 'proxy' for a part at *distance* with *bbox_radius*.

    Two criteria (either triggers proxy):
    1. angular size < LOD_ANGULAR_THRESHOLD
    2. visible_index >= LOD_THRESHOLD_COUNT
    """
    if visible_index >= LOD_THRESHOLD_COUNT:
        return "proxy"
    ang = angular_size(bbox_radius, distance)
    return "proxy" if ang < LOD_ANGULAR_THRESHOLD else "full"


# ---------------------------------------------------------------------------
# Modelled FPS computation
# ---------------------------------------------------------------------------

GPU_TRIS_PER_SEC = 500_000_000   # conservative: 500 Mtri/s
FRAME_BUDGET_SEC = 1.0 / 60.0    # 16.67 ms
MAX_TRIS_PER_FRAME = int(GPU_TRIS_PER_SEC * FRAME_BUDGET_SEC)  # 8_333_333
DRAW_CALL_OVERHEAD_MS = 0.03     # ms per draw call (driver estimate)
MAX_DRAW_CALLS_60FPS = int(FRAME_BUDGET_SEC * 1000 / DRAW_CALL_OVERHEAD_MS)  # ~556


def model_fps(triangle_count: int, draw_calls: int) -> float:
    """Return a modelled FPS estimate (no GPU).

    fps_tris  = min(60, 500Mtri/s / tris_per_frame)
    fps_dc    = min(60, 16.67ms / (draw_calls × 0.03ms))
    fps       = min(fps_tris, fps_dc)
    """
    tris_budget = MAX_TRIS_PER_FRAME / max(1, triangle_count)
    fps_tris = min(60.0, tris_budget * 60.0)

    dc_budget = FRAME_BUDGET_SEC * 1000 / max(1, draw_calls * DRAW_CALL_OVERHEAD_MS)
    fps_dc = min(60.0, dc_budget)

    return round(min(fps_tris, fps_dc), 1)


# ---------------------------------------------------------------------------
# Assembly simulation
# ---------------------------------------------------------------------------

def _lcg(seed: int) -> int:
    return (seed * 1664525 + 1013904223) & 0xFFFF_FFFF


def make_synthetic_assembly(n: int, num_part_types: int = 20) -> list[dict]:
    """Generate N component dicts with deterministic transforms."""
    components = []
    seed = 12345
    for i in range(n):
        seed = _lcg(seed)
        x = ((seed & 0xFFFF) * 0.01) - 327.68
        seed = _lcg(seed)
        y = ((seed & 0xFFFF) * 0.01) - 327.68
        seed = _lcg(seed)
        z = ((seed & 0xFFFF) * 0.01) - 327.68
        components.append({
            "id": f"c-{i}",
            "file_id": f"part-{i % num_part_types}",
            "object_id": f"body-{i % 3}",
            "transform": [1,0,0,x, 0,1,0,y, 0,0,1,z, 0,0,0,1],
            "bbox_radius": 1.0,  # unit sphere
        })
    return components


def run_lod_pass(components: list[dict], camera_pos: list[float]) -> dict:
    """Run LOD selection for all components; return summary stats."""
    cx, cy, cz = camera_pos
    tri_full = 0
    tri_lod = 0
    draw_full = 0
    draw_lod = 0
    unique_parts_lod: set[str] = set()

    for idx, comp in enumerate(components):
        t = comp["transform"]
        # Translation is in indices 3, 7, 11 of the row-major 4x4.
        px, py, pz = t[3], t[7], t[11]
        dist = math.sqrt((px-cx)**2 + (py-cy)**2 + (pz-cz)**2)
        lod = select_lod(idx, dist, comp["bbox_radius"])

        # Full-res accounting (as if no LOD)
        tri_full += _TRIS_FULL
        draw_full += 1

        # LOD accounting
        if lod == "full":
            tri_lod += _TRIS_FULL
        else:
            tri_lod += _TRIS_PROXY
        # Draw calls collapse per unique part type (instanced)
        part_key = f"{comp['file_id']}::{lod}"
        unique_parts_lod.add(part_key)

    draw_lod = len(unique_parts_lod)
    return {
        "tri_full": tri_full,
        "tri_lod": tri_lod,
        "draw_full": draw_full,
        "draw_lod": draw_lod,
    }


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------

SCALES = [100, 1_000, 5_000, 10_000]
CAMERA_POS = [0.0, 0.0, 500.0]  # camera 500 units back on Z


def run_scale(n: int) -> dict[str, Any]:
    tracemalloc.start()
    t0 = time.perf_counter()

    components = make_synthetic_assembly(n)
    t_parse = time.perf_counter()

    lod_stats = run_lod_pass(components, CAMERA_POS)
    t_lod = time.perf_counter()

    _, mem_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    time_to_interactive_ms = (t_lod - t0) * 1000
    parse_ms = (t_parse - t0) * 1000
    lod_ms = (t_lod - t_parse) * 1000

    fps_full  = model_fps(lod_stats["tri_full"],  lod_stats["draw_full"])
    fps_lod   = model_fps(lod_stats["tri_lod"],   lod_stats["draw_lod"])
    speedup   = round(fps_lod / max(fps_full, 0.001), 1)

    return {
        "n": n,
        "parse_ms": round(parse_ms, 2),
        "lod_ms": round(lod_ms, 2),
        "time_to_interactive_ms": round(time_to_interactive_ms, 2),
        "memory_peak_kb": round(mem_peak / 1024, 1),
        "triangle_count_full": lod_stats["tri_full"],
        "triangle_count_lod": lod_stats["tri_lod"],
        "draw_calls_full": lod_stats["draw_full"],
        "draw_calls_lod": lod_stats["draw_lod"],
        "fps_proxy_modelled": fps_lod,
        "fps_full_modelled": fps_full,
        "fps_speedup": speedup,
        "methodology": "modelled (no GPU): 500Mtri/s budget + 0.03ms/draw-call overhead",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Large-assembly performance harness (T-320)")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args()

    all_results = []
    for n in SCALES:
        r = run_scale(n)
        all_results.append(r)

    if args.json:
        print(json.dumps({"scales": all_results}, indent=2))
        return

    # Human-readable table
    hdr = (
        f"{'N':>7}  {'parse_ms':>9}  {'lod_ms':>7}  {'tti_ms':>8}  "
        f"{'mem_kb':>8}  {'tris_full':>10}  {'tris_lod':>9}  "
        f"{'dc_full':>8}  {'dc_lod':>7}  {'fps_full':>9}  {'fps_lod':>8}  {'speedup':>8}"
    )
    print("\nLarge-assembly performance harness (T-320)")
    print("Modelled metrics — no GPU; see --help for methodology\n")
    print(hdr)
    print("-" * len(hdr))
    for r in all_results:
        print(
            f"{r['n']:>7}  {r['parse_ms']:>9.2f}  {r['lod_ms']:>7.2f}  "
            f"{r['time_to_interactive_ms']:>8.2f}  {r['memory_peak_kb']:>8.1f}  "
            f"{r['triangle_count_full']:>10}  {r['triangle_count_lod']:>9}  "
            f"{r['draw_calls_full']:>8}  {r['draw_calls_lod']:>7}  "
            f"{r['fps_full_modelled']:>9.1f}  {r['fps_proxy_modelled']:>8.1f}  "
            f"{r['fps_speedup']:>7.1f}x"
        )
    print()
    print("Columns: N parts | parse ms | lod-select ms | time-to-interactive ms | "
          "peak mem KB | triangles full | triangles after LOD | draw calls full | "
          "draw calls LOD | fps full (modelled) | fps LOD (modelled) | speedup")


if __name__ == "__main__":
    main()
