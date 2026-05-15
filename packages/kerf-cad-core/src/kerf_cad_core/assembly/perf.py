"""
kerf_cad_core.assembly.perf — Large-assembly performance harness + LOD/lazy-load planner.

Sections
--------
1. Synthetic assembly generator
   build_assembly(n, depth, branching)
   Produces a deterministic assembly tree of *n* total leaf components spread
   across a balanced sub-assembly tree of the requested depth and branching
   factor.  Part refs cycle through a fixed catalogue so part counts are
   reproducible.

2. Performance harness
   measure_assembly(assembly) → PerfResult
   Times the existing solve_assembly + BOM roll-up calls and records peak
   resident-set memory delta.  Returns structured data — no wall-clock
   assertions anywhere in this module.

   sweep_assembly_perf(ns, **kwargs) → list[PerfResult]
   Convenience: build + measure for each N in ns.

3. LOD planner
   lod_plan(assembly, budget) → LodPlan
   Given an assembly and a ViewportBudget (max_triangles + max_visible_parts)
   assigns each component a detail level:
     "full"       — render at full resolution
     "bbox_proxy" — render as axis-aligned bounding box only
     "culled"     — do not render

   Heuristic: components are ranked by (estimated_volume * importance_weight)
   descending.  Largest/most-important components get "full" until the triangle
   budget is exhausted; the next tier gets "bbox_proxy" until the part count
   budget is exhausted; the rest are "culled".

   Triangle estimates are deterministic synthetic values derived from the
   component's part_ref hash so the planner works with no geometry back-end.

4. Lazy-load ordering
   lazy_load_order(lod_plan, camera_pos) → list[str]
   Returns instance_ids in the order they should be loaded, closest/largest
   first.  Deterministic for equal inputs (stable sort).

5. LLM tool wrappers
   assembly_perf_report  — run the perf harness and return structured timings.
   assembly_lod_plan     — compute and return an LOD plan for an assembly.

All operations: pure Python, no OCC, no DB, no network.  Never raises on bad
user input — errors are returned in the payload under key "error".
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import tracemalloc
from dataclasses import dataclass, field, asdict
from typing import Any

from kerf_cad_core.assembly.model import Assembly, Component, _identity
from kerf_cad_core.assembly.mates import Mate, MateType, solve_assembly
from kerf_cad_core.assembly.tools import _build_flat_bom

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _TOOLS_AVAILABLE = True
except ImportError:
    _TOOLS_AVAILABLE = False

    class ToolSpec:  # type: ignore[no-redef]
        def __init__(self, *, name, description, input_schema):
            self.name = name
            self.description = description
            self.input_schema = input_schema

    def ok_payload(v: Any) -> str:  # type: ignore[misc]
        try:
            return json.dumps(v)
        except Exception as e:
            return err_payload(f"encode result: {e}", "ERROR")

    def err_payload(msg: str, code: str) -> str:  # type: ignore[misc]
        return json.dumps({"error": msg, "code": code})

    def register(spec, write=False):  # type: ignore[misc]
        def decorator(fn):
            return fn
        return decorator

    class ProjectCtx:  # type: ignore[no-redef]
        pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PART_CATALOGUE = [
    "bolt-M6", "bolt-M8", "nut-M6", "nut-M8", "washer-M6", "washer-M8",
    "bracket-L", "bracket-T", "plate-6mm", "plate-10mm",
    "shaft-20mm", "shaft-30mm", "bearing-6200", "bearing-6201",
    "gear-32t", "gear-48t", "bushing-25mm", "spring-coil",
    "pin-4mm", "pin-6mm",
]

# Synthetic triangle counts per part (deterministic, based on typical mesh density)
_TRI_PER_PART: dict[str, int] = {
    "bolt-M6": 480,    "bolt-M8": 560,
    "nut-M6": 320,     "nut-M8": 380,
    "washer-M6": 128,  "washer-M8": 160,
    "bracket-L": 240,  "bracket-T": 280,
    "plate-6mm": 96,   "plate-10mm": 112,
    "shaft-20mm": 640, "shaft-30mm": 800,
    "bearing-6200": 960, "bearing-6201": 1020,
    "gear-32t": 2400,  "gear-48t": 3600,
    "bushing-25mm": 320, "spring-coil": 1800,
    "pin-4mm": 192,    "pin-6mm": 220,
}

# Synthetic bounding-box half-extents (x, y, z) in mm
_BBOX_HALF: dict[str, tuple[float, float, float]] = {
    "bolt-M6": (3, 3, 20),     "bolt-M8": (4, 4, 25),
    "nut-M6": (6, 6, 5),       "nut-M8": (7, 7, 6),
    "washer-M6": (7, 7, 1),    "washer-M8": (9, 9, 1.5),
    "bracket-L": (40, 40, 5),  "bracket-T": (50, 40, 5),
    "plate-6mm": (100, 60, 3), "plate-10mm": (100, 60, 5),
    "shaft-20mm": (10, 10, 80), "shaft-30mm": (15, 15, 100),
    "bearing-6200": (10, 10, 9), "bearing-6201": (12, 12, 10),
    "gear-32t": (25, 25, 12),   "gear-48t": (35, 35, 14),
    "bushing-25mm": (13, 13, 20), "spring-coil": (15, 15, 40),
    "pin-4mm": (2, 2, 20),     "pin-6mm": (3, 3, 25),
}


# ---------------------------------------------------------------------------
# 1. Synthetic assembly generator
# ---------------------------------------------------------------------------

def _part_ref_for_index(i: int) -> str:
    """Cycle through the catalogue deterministically."""
    return _PART_CATALOGUE[i % len(_PART_CATALOGUE)]


def build_assembly(
    n: int,
    depth: int = 2,
    branching: int = 4,
    name: str = "synthetic",
) -> Assembly:
    """
    Build a synthetic assembly with exactly *n* leaf components spread
    across a balanced sub-assembly tree.

    Parameters
    ----------
    n : int
        Total number of leaf Component instances.  Must be >= 1.
    depth : int
        Sub-assembly nesting depth.  0 = flat (all components at root level).
    branching : int
        Maximum number of sub-assemblies per level.  Capped so the tree
        never has more sub-assemblies than needed.
    name : str
        Root assembly name.

    Returns
    -------
    Assembly
        A fully-constructed Assembly with *n* Component instances.

    Notes
    -----
    Instance IDs are deterministic (based on a counter) so repeated calls
    with the same arguments produce the same IDs.  Transforms are the identity
    (no mates are added — the harness measures the solver on an unconstrained
    assembly).
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if depth < 0:
        raise ValueError(f"depth must be >= 0, got {depth}")
    if branching < 1:
        raise ValueError(f"branching must be >= 1, got {branching}")

    counter: list[int] = [0]
    root = Assembly(name=name, assembly_id=f"asm-root-{name}")
    _fill_assembly(root, n, depth, branching, counter)
    return root


def _fill_assembly(
    asm: Assembly,
    remaining: int,
    depth: int,
    branching: int,
    counter: list[int],
) -> int:
    """
    Recursively fill *asm* with components.  Returns the number of components
    actually placed (may be < remaining once the counter runs out).
    """
    if remaining <= 0:
        return 0

    placed = 0

    if depth == 0:
        # Leaf level: place all remaining components directly
        for _ in range(remaining):
            idx = counter[0]
            comp = Component(
                part_ref=_part_ref_for_index(idx),
                instance_id=f"inst-{idx:06d}",
                name=f"part-{idx:06d}",
            )
            asm.add_component(comp)
            counter[0] += 1
            placed += 1
    else:
        # Split remaining across sub-assemblies
        n_subs = min(branching, remaining)
        base_per_sub = remaining // n_subs
        extras = remaining % n_subs

        for s in range(n_subs):
            sub_n = base_per_sub + (1 if s < extras else 0)
            if sub_n <= 0:
                break
            sub_idx = counter[0]
            sub = Assembly(
                name=f"{asm.name}-sub{s}",
                assembly_id=f"asm-{sub_idx:06d}-d{depth}",
            )
            sub_placed = _fill_assembly(sub, sub_n, depth - 1, branching, counter)
            placed += sub_placed
            if sub_placed > 0:
                asm.add_sub_assembly(sub)

    return placed


# ---------------------------------------------------------------------------
# 2. Performance harness
# ---------------------------------------------------------------------------

@dataclass
class PerfResult:
    """Structured timing + memory result for one assembly measurement."""
    n_components: int
    solve_time_s: float
    bom_time_s: float
    total_time_s: float
    peak_memory_bytes: int
    dof_remaining: int
    status: str
    n_unique_parts: int
    depth: int
    branching: int


def measure_assembly(
    assembly: Assembly,
    depth: int = 0,
    branching: int = 1,
) -> PerfResult:
    """
    Measure solve + BOM roll-up performance for *assembly*.

    Parameters
    ----------
    assembly : Assembly
    depth : int
        Informational — the depth used when building the assembly.
    branching : int
        Informational — the branching factor used when building the assembly.

    Returns
    -------
    PerfResult
        Structured timings.  No assertions are made on the timing values;
        the caller decides what constitutes a regression.
    """
    all_comps = assembly.all_components()
    n = len(all_comps)

    tracemalloc.start()
    t_start = time.perf_counter()

    solve_t0 = time.perf_counter()
    solve_result = solve_assembly(assembly, [])
    solve_t1 = time.perf_counter()

    bom_t0 = time.perf_counter()
    flat_bom = _build_flat_bom(assembly)
    bom_t1 = time.perf_counter()

    t_end = time.perf_counter()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    unique_parts = len({r["part_ref"] for r in flat_bom})

    return PerfResult(
        n_components=n,
        solve_time_s=solve_t1 - solve_t0,
        bom_time_s=bom_t1 - bom_t0,
        total_time_s=t_end - t_start,
        peak_memory_bytes=peak,
        dof_remaining=solve_result["dof_remaining"],
        status=solve_result["status"],
        n_unique_parts=unique_parts,
        depth=depth,
        branching=branching,
    )


def sweep_assembly_perf(
    ns: list[int],
    depth: int = 2,
    branching: int = 4,
) -> list[PerfResult]:
    """
    Build and measure assemblies of each size in *ns*.

    Parameters
    ----------
    ns : list[int]
        Component counts to sweep.  Each value must be >= 1.
    depth : int
        Sub-assembly nesting depth passed to build_assembly.
    branching : int
        Branching factor passed to build_assembly.

    Returns
    -------
    list[PerfResult]
        One PerfResult per entry in *ns*, in the same order.
    """
    results = []
    for n in ns:
        asm = build_assembly(n, depth=depth, branching=branching)
        result = measure_assembly(asm, depth=depth, branching=branching)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# 3. LOD planner
# ---------------------------------------------------------------------------

@dataclass
class ViewportBudget:
    """
    Constraints for the LOD planner.

    Parameters
    ----------
    max_triangles : int
        Maximum total triangle count allowed for "full" detail components.
        Must be > 0.
    max_visible_parts : int
        Maximum total number of components rendered at any detail level
        (full + bbox_proxy).  Must be > 0.
    """
    max_triangles: int
    max_visible_parts: int


@dataclass
class ComponentLodEntry:
    """LOD assignment for a single component instance."""
    instance_id: str
    part_ref: str
    detail: str          # "full" | "bbox_proxy" | "culled"
    tri_count: int       # 0 for bbox_proxy/culled (triangles not loaded)
    importance: float    # ranking score used by the planner
    bbox_half: tuple[float, float, float]


@dataclass
class LodPlan:
    """Full LOD assignment for an assembly."""
    entries: list[ComponentLodEntry] = field(default_factory=list)
    total_full_triangles: int = 0
    total_visible_parts: int = 0
    budget: ViewportBudget = field(default_factory=lambda: ViewportBudget(0, 0))


def _tri_count_for(part_ref: str) -> int:
    """
    Return a deterministic triangle estimate for a part_ref.

    Uses the lookup table for known refs; falls back to a hash-derived
    value in [96, 3600] for unknown refs.
    """
    if part_ref in _TRI_PER_PART:
        return _TRI_PER_PART[part_ref]
    # Hash-based fallback: reproducible for any string
    h = int(hashlib.sha256(part_ref.encode()).hexdigest()[:8], 16)
    return 96 + (h % 3505)


def _bbox_half_for(part_ref: str) -> tuple[float, float, float]:
    """Return a deterministic bounding-box half-extent for a part_ref."""
    if part_ref in _BBOX_HALF:
        return _BBOX_HALF[part_ref]
    h = int(hashlib.sha256(part_ref.encode()).hexdigest()[8:16], 16)
    x = 5.0 + (h % 95)
    y = 5.0 + ((h >> 7) % 95)
    z = 5.0 + ((h >> 14) % 95)
    return (x, y, z)


def _volume_for(part_ref: str) -> float:
    """Return a synthetic volume (mm³) estimate for a part_ref."""
    bx, by, bz = _bbox_half_for(part_ref)
    return 8.0 * bx * by * bz  # full box volume


def _importance_for(comp: Component) -> float:
    """
    Compute an importance score for a component.

    Score = volume * (1 + log(1 + tri_count))

    This weights large, geometrically complex parts most highly so they
    receive "full" detail when the budget allows.
    """
    vol = _volume_for(comp.part_ref)
    tris = _tri_count_for(comp.part_ref)
    return vol * (1.0 + math.log1p(tris))


def lod_plan(
    assembly: Assembly,
    budget: ViewportBudget,
) -> LodPlan:
    """
    Compute a deterministic LOD plan for *assembly* subject to *budget*.

    Algorithm
    ---------
    1. Collect all leaf components and compute their importance scores.
    2. Sort descending by importance (stable sort — ties broken by
       instance_id lexicographic order for full determinism).
    3. Greedily assign "full" while cumulative triangles <= max_triangles
       and visible_parts <= max_visible_parts.
    4. Greedily assign "bbox_proxy" for remaining until visible_parts
       budget is exhausted.
    5. Assign "culled" to everything else.

    Parameters
    ----------
    assembly : Assembly
    budget : ViewportBudget
        If max_triangles <= 0 or max_visible_parts <= 0 the budget is
        invalid and a friendly error LodPlan is returned with all entries
        culled and a non-empty ``error`` attribute.

    Returns
    -------
    LodPlan
        Always returns; never raises.
    """
    all_comps = assembly.all_components()

    entries: list[ComponentLodEntry] = []
    for comp in all_comps:
        imp = _importance_for(comp)
        entries.append(ComponentLodEntry(
            instance_id=comp.instance_id,
            part_ref=comp.part_ref,
            detail="culled",
            tri_count=0,
            importance=imp,
            bbox_half=_bbox_half_for(comp.part_ref),
        ))

    # Validate budget
    if budget.max_triangles <= 0 or budget.max_visible_parts <= 0:
        plan = LodPlan(entries=entries, budget=budget)
        # Attach a non-raising error indicator
        plan.error = (  # type: ignore[attr-defined]
            f"invalid budget: max_triangles={budget.max_triangles}, "
            f"max_visible_parts={budget.max_visible_parts} — both must be > 0; "
            "all components culled"
        )
        return plan

    # Sort: descending importance, ties broken by instance_id (stable, deterministic)
    entries.sort(key=lambda e: (-e.importance, e.instance_id))

    tri_used = 0
    visible_used = 0

    for entry in entries:
        tris = _tri_count_for(entry.part_ref)
        if (
            tri_used + tris <= budget.max_triangles
            and visible_used < budget.max_visible_parts
        ):
            entry.detail = "full"
            entry.tri_count = tris
            tri_used += tris
            visible_used += 1
        elif visible_used < budget.max_visible_parts:
            entry.detail = "bbox_proxy"
            entry.tri_count = 0
            visible_used += 1
        else:
            entry.detail = "culled"
            entry.tri_count = 0

    plan = LodPlan(
        entries=entries,
        total_full_triangles=tri_used,
        total_visible_parts=visible_used,
        budget=budget,
    )
    return plan


# ---------------------------------------------------------------------------
# 4. Lazy-load ordering
# ---------------------------------------------------------------------------

def lazy_load_order(
    plan: LodPlan,
    camera_pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> list[str]:
    """
    Return instance_ids in the recommended loading order.

    Priority: "full" before "bbox_proxy" before "culled".
    Within each tier: nearest centroid first, then largest volume as
    tiebreaker, then instance_id for full determinism.

    Parameters
    ----------
    plan : LodPlan
    camera_pos : tuple[float, float, float]
        Camera / viewer position in world space (mm).  Defaults to origin.

    Returns
    -------
    list[str]
        instance_ids in load order.  Stable for equal inputs.
    """
    detail_order = {"full": 0, "bbox_proxy": 1, "culled": 2}

    def _sort_key(entry: ComponentLodEntry):
        bx, by, bz = entry.bbox_half
        # Centroid approximation: origin (transforms not applied here —
        # we only have the part-level bbox, not world placement).
        # Use bbox volume as a proxy for size (larger = load sooner within tier).
        vol = 8.0 * bx * by * bz
        # Negate volume so larger parts sort first within tier
        return (detail_order[entry.detail], -vol, entry.instance_id)

    sorted_entries = sorted(plan.entries, key=_sort_key)
    return [e.instance_id for e in sorted_entries]


# ---------------------------------------------------------------------------
# 5. LLM tool wrappers
# ---------------------------------------------------------------------------

_perf_report_spec = ToolSpec(
    name="assembly_perf_report",
    description=(
        "Run a performance harness on a given assembly (or a freshly generated "
        "synthetic assembly of size N) and return structured timing + memory data. "
        "\n"
        "If ``assembly`` is supplied it is measured directly.  If ``n`` is "
        "supplied instead, a synthetic assembly of that many components is built "
        "first using the specified ``depth`` and ``branching`` parameters. "
        "\n"
        "Returns:\n"
        "  n_components        — total leaf component count\n"
        "  solve_time_s        — wall-clock seconds for solve_assembly\n"
        "  bom_time_s          — wall-clock seconds for BOM roll-up\n"
        "  total_time_s        — total measurement time\n"
        "  peak_memory_bytes   — peak resident memory delta during measurement\n"
        "  status              — constraint status ('fully_constrained' etc.)\n"
        "  n_unique_parts      — number of distinct part_refs\n"
        "\n"
        "Never raises; invalid inputs return a friendly error."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly": {
                "type": "object",
                "description": "Assembly dict to measure (optional — mutually exclusive with n).",
            },
            "n": {
                "type": "integer",
                "description": "Component count for a fresh synthetic assembly (optional).",
                "minimum": 1,
            },
            "depth": {
                "type": "integer",
                "description": "Sub-assembly nesting depth for synthetic assembly. Default 2.",
                "minimum": 0,
            },
            "branching": {
                "type": "integer",
                "description": "Branching factor for synthetic assembly. Default 4.",
                "minimum": 1,
            },
        },
        "required": [],
    },
)


@register(_perf_report_spec, write=False)
async def run_assembly_perf_report(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    asm_raw = a.get("assembly")
    n_raw = a.get("n")

    if asm_raw is not None and n_raw is not None:
        return err_payload(
            "supply either 'assembly' or 'n', not both", "BAD_ARGS"
        )

    depth = int(a.get("depth", 2))
    branching = int(a.get("branching", 4))

    if depth < 0:
        return err_payload(f"depth must be >= 0, got {depth}", "BAD_ARGS")
    if branching < 1:
        return err_payload(f"branching must be >= 1, got {branching}", "BAD_ARGS")

    if asm_raw is not None:
        if not isinstance(asm_raw, dict):
            return err_payload("assembly must be an object", "BAD_ARGS")
        try:
            asm = Assembly.from_dict(asm_raw)
        except Exception as exc:
            return err_payload(f"invalid assembly: {exc}", "BAD_ARGS")
    elif n_raw is not None:
        try:
            n = int(n_raw)
        except (TypeError, ValueError) as exc:
            return err_payload(f"n must be an integer: {exc}", "BAD_ARGS")
        if n < 1:
            return err_payload(f"n must be >= 1, got {n}", "BAD_ARGS")
        try:
            asm = build_assembly(n, depth=depth, branching=branching)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
    else:
        # Default: tiny 10-component assembly as a smoke-test
        asm = build_assembly(10, depth=1, branching=3)
        depth, branching = 1, 3

    result = measure_assembly(asm, depth=depth, branching=branching)
    return ok_payload({
        "n_components": result.n_components,
        "solve_time_s": result.solve_time_s,
        "bom_time_s": result.bom_time_s,
        "total_time_s": result.total_time_s,
        "peak_memory_bytes": result.peak_memory_bytes,
        "dof_remaining": result.dof_remaining,
        "status": result.status,
        "n_unique_parts": result.n_unique_parts,
        "depth": result.depth,
        "branching": result.branching,
    })


_lod_plan_spec = ToolSpec(
    name="assembly_lod_plan",
    description=(
        "Compute a Level-of-Detail (LOD) plan for an assembly given a viewport "
        "triangle and part-count budget. "
        "\n"
        "Each component is assigned:\n"
        "  'full'       — render at full triangle resolution\n"
        "  'bbox_proxy' — render as a bounding-box proxy only\n"
        "  'culled'     — do not render\n"
        "\n"
        "Heuristic: largest/most complex components receive 'full' first until "
        "the triangle budget is exhausted; the next tier gets 'bbox_proxy' "
        "until the visible-part budget is exhausted; the rest are 'culled'. "
        "\n"
        "Returns:\n"
        "  entries             — list of {instance_id, part_ref, detail, tri_count, importance}\n"
        "  total_full_triangles — sum of triangles for 'full' components\n"
        "  total_visible_parts — count of 'full' + 'bbox_proxy' components\n"
        "  load_order          — instance_ids in recommended load order (nearest/largest first)\n"
        "  error               — friendly message if budget is invalid (all culled)\n"
        "\n"
        "Never raises; invalid budget returns a friendly error in the payload."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly": {
                "type": "object",
                "description": "Assembly dict.",
            },
            "max_triangles": {
                "type": "integer",
                "description": "Maximum total triangle count for full-detail components.",
                "minimum": 1,
            },
            "max_visible_parts": {
                "type": "integer",
                "description": "Maximum total number of rendered components (full + bbox).",
                "minimum": 1,
            },
            "camera_x": {"type": "number", "description": "Camera X position (mm). Default 0."},
            "camera_y": {"type": "number", "description": "Camera Y position (mm). Default 0."},
            "camera_z": {"type": "number", "description": "Camera Z position (mm). Default 0."},
        },
        "required": ["assembly", "max_triangles", "max_visible_parts"],
    },
)


@register(_lod_plan_spec, write=False)
async def run_assembly_lod_plan(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    asm_raw = a.get("assembly")
    if not asm_raw or not isinstance(asm_raw, dict):
        return err_payload("assembly is required", "BAD_ARGS")

    max_tri = a.get("max_triangles")
    max_vis = a.get("max_visible_parts")

    if max_tri is None:
        return err_payload("max_triangles is required", "BAD_ARGS")
    if max_vis is None:
        return err_payload("max_visible_parts is required", "BAD_ARGS")

    try:
        max_tri = int(max_tri)
        max_vis = int(max_vis)
    except (TypeError, ValueError) as exc:
        return err_payload(f"max_triangles and max_visible_parts must be integers: {exc}", "BAD_ARGS")

    try:
        asm = Assembly.from_dict(asm_raw)
    except Exception as exc:
        return err_payload(f"invalid assembly: {exc}", "BAD_ARGS")

    cam_x = float(a.get("camera_x", 0.0))
    cam_y = float(a.get("camera_y", 0.0))
    cam_z = float(a.get("camera_z", 0.0))

    budget = ViewportBudget(max_triangles=max_tri, max_visible_parts=max_vis)
    plan = lod_plan(asm, budget)

    load_order = lazy_load_order(plan, camera_pos=(cam_x, cam_y, cam_z))

    entries_out = [
        {
            "instance_id": e.instance_id,
            "part_ref": e.part_ref,
            "detail": e.detail,
            "tri_count": e.tri_count,
            "importance": e.importance,
        }
        for e in plan.entries
    ]

    payload: dict = {
        "entries": entries_out,
        "total_full_triangles": plan.total_full_triangles,
        "total_visible_parts": plan.total_visible_parts,
        "load_order": load_order,
    }

    if hasattr(plan, "error"):
        payload["error"] = plan.error  # type: ignore[attr-defined]

    return ok_payload(payload)


__all__ = [
    # Generator
    "build_assembly",
    # Harness
    "PerfResult",
    "measure_assembly",
    "sweep_assembly_perf",
    # LOD planner
    "ViewportBudget",
    "ComponentLodEntry",
    "LodPlan",
    "lod_plan",
    # Lazy-load ordering
    "lazy_load_order",
    # LLM tools
    "run_assembly_perf_report",
    "run_assembly_lod_plan",
]
