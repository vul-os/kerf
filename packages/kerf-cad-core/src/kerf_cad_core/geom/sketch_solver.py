"""Parametric 2D sketch constraint solver.

Architecture: Sutherland 1963 Sketchpad-style constraint propagation implemented
as a Newton-Raphson residual minimisation over the sketch DOF vector, following
Hoffmann-Joan-Arinyo 2001 "Symbolic constraints in constructive geometric
constraint solving" and the SolveSpace architecture.

Public API
----------
SketchEntity   — dataclass: kind, id, parameters (mutable DOFs)
Constraint     — dataclass: kind, entity_ids, parameter
SolveResult    — dataclass: converged, iters, residual, entities
solve_sketch   — full Newton-Raphson solve with damped line-search
check_consistency — over/under-constraint detection via Jacobian rank
drag_entity    — interactive-drag re-solve (fix one entity, solve rest)

Supported constraint kinds
--------------------------
  coincident, horizontal, vertical, parallel, perpendicular, tangent,
  distance, angle, equal, on_curve

Supported entity kinds
----------------------
  point  — params: [x, y]
  line   — params: [x0, y0, x1, y1]  (start/end)
  circle — params: [cx, cy, r]
  arc    — params: [cx, cy, r, t0, t1]  (centre, radius, start/end angle rad)

References
----------
- I. Sutherland, "Sketchpad: A Man-Machine Graphical Communication System,"
  MIT PhD thesis, 1963.
- C. Hoffmann & R. Joan-Arinyo, "A brief on constraint solving,"
  Computer-Aided Design and Applications 2(5), 2005.
- SolveSpace open-source parametric CAD, slvs.h architecture.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

_ENTITY_DOFS = {
    "point": 2,   # x, y
    "line": 4,    # x0, y0, x1, y1
    "circle": 3,  # cx, cy, r
    "arc": 5,     # cx, cy, r, t0, t1
}

_VALID_ENTITY_KINDS = set(_ENTITY_DOFS.keys())
_VALID_CONSTRAINT_KINDS = {
    "coincident", "horizontal", "vertical", "parallel",
    "perpendicular", "tangent", "distance", "angle", "equal", "on_curve",
}


@dataclass
class SketchEntity:
    """A geometric entity in a 2-D sketch.

    Attributes
    ----------
    kind : str
        One of 'point', 'line', 'circle', 'arc'.
    id : str
        Unique identifier within the sketch.
    params : list[float]
        Mutable DOF vector.  Lengths: point=2, line=4, circle=3, arc=5.
    fixed : bool
        When True the entity's params are frozen during solve (ground anchor).
    """
    kind: str
    id: str
    params: list[float]
    fixed: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _VALID_ENTITY_KINDS:
            raise ValueError(f"unknown entity kind {self.kind!r}")
        expected = _ENTITY_DOFS[self.kind]
        if len(self.params) != expected:
            raise ValueError(
                f"entity kind {self.kind!r} expects {expected} params, "
                f"got {len(self.params)}"
            )


@dataclass
class Constraint:
    """A geometric or dimensional constraint between sketch entities.

    Attributes
    ----------
    kind : str
        Constraint type.
    entity_ids : list[str]
        Ordered list of entity ids this constraint applies to.
    parameter : float | None
        Dimensional value (distance, angle in radians, etc.) when relevant.
    """
    kind: str
    entity_ids: list[str]
    parameter: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in _VALID_CONSTRAINT_KINDS:
            raise ValueError(f"unknown constraint kind {self.kind!r}")


@dataclass
class SolveResult:
    """Result returned by solve_sketch."""
    converged: bool
    iters: int
    residual: float
    entities: list[SketchEntity]
    message: str = ""


# ---------------------------------------------------------------------------
# DOF vector helpers
# ---------------------------------------------------------------------------

def _pack(entities: list[SketchEntity]) -> tuple[np.ndarray, list[int]]:
    """Flatten free entity params into a 1-D DOF vector.

    Returns (x0, offsets) where offsets[i] is the start index of entity i
    in x0, or -1 if entity i is fixed.
    """
    offsets: list[int] = []
    parts: list[np.ndarray] = []
    cursor = 0
    for ent in entities:
        if ent.fixed:
            offsets.append(-1)
        else:
            offsets.append(cursor)
            parts.append(np.array(ent.params, dtype=float))
            cursor += len(ent.params)
    x0 = np.concatenate(parts) if parts else np.zeros(0)
    return x0, offsets


def _unpack(x: np.ndarray, entities: list[SketchEntity], offsets: list[int]) -> None:
    """Write DOF vector back into entity param lists (in-place)."""
    for i, ent in enumerate(entities):
        if offsets[i] < 0:
            continue
        n = len(ent.params)
        ent.params = x[offsets[i]: offsets[i] + n].tolist()


# ---------------------------------------------------------------------------
# Constraint residual functions
# ---------------------------------------------------------------------------
# Each function receives the *current* entity list (params already written) and
# the constraint, and returns a 1-D numpy array of residuals that should equal
# zero when the constraint is satisfied.

def _ent(entities: list[SketchEntity], eid: str) -> SketchEntity:
    for e in entities:
        if e.id == eid:
            return e
    raise KeyError(f"entity {eid!r} not found")


def _residual_coincident(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    """Two points share the same position, or endpoint of line == point."""
    a = _ent(entities, c.entity_ids[0])
    b = _ent(entities, c.entity_ids[1])

    def _endpoint(e: SketchEntity, which: str = "start") -> np.ndarray:
        if e.kind == "point":
            return np.array(e.params[:2])
        if e.kind == "line":
            return np.array(e.params[:2]) if which == "start" else np.array(e.params[2:4])
        if e.kind in ("circle", "arc"):
            return np.array(e.params[:2])
        raise ValueError(f"cannot get endpoint of {e.kind!r}")

    pa = _endpoint(a)
    pb = _endpoint(b)
    return pa - pb  # 2 residuals


def _residual_horizontal(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    e = _ent(entities, c.entity_ids[0])
    if e.kind == "line":
        return np.array([e.params[1] - e.params[3]])  # y0 - y1 = 0
    if e.kind == "point" and len(c.entity_ids) == 2:
        a = _ent(entities, c.entity_ids[0])
        b = _ent(entities, c.entity_ids[1])
        return np.array([a.params[1] - b.params[1]])
    return np.zeros(0)


def _residual_vertical(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    e = _ent(entities, c.entity_ids[0])
    if e.kind == "line":
        return np.array([e.params[0] - e.params[2]])  # x0 - x1 = 0
    if e.kind == "point" and len(c.entity_ids) == 2:
        a = _ent(entities, c.entity_ids[0])
        b = _ent(entities, c.entity_ids[1])
        return np.array([a.params[0] - b.params[0]])
    return np.zeros(0)


def _line_dir(e: SketchEntity) -> np.ndarray:
    dx = e.params[2] - e.params[0]
    dy = e.params[3] - e.params[1]
    return np.array([dx, dy])


def _residual_parallel(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    a = _ent(entities, c.entity_ids[0])
    b = _ent(entities, c.entity_ids[1])
    da = _line_dir(a)
    db = _line_dir(b)
    # cross product = 0  ⟺  parallel (or anti-parallel)
    cross = da[0] * db[1] - da[1] * db[0]
    return np.array([cross])


def _residual_perpendicular(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    a = _ent(entities, c.entity_ids[0])
    b = _ent(entities, c.entity_ids[1])
    da = _line_dir(a)
    db = _line_dir(b)
    # dot product = 0  ⟺  perpendicular
    dot = da[0] * db[0] + da[1] * db[1]
    return np.array([dot])


def _residual_tangent(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    """Line tangent to circle: dist(centre, line) = radius."""
    # entity_ids[0] = circle, entity_ids[1] = line  (or reversed)
    a = _ent(entities, c.entity_ids[0])
    b = _ent(entities, c.entity_ids[1])
    if a.kind == "line" and b.kind in ("circle", "arc"):
        line, circ = a, b
    elif a.kind in ("circle", "arc") and b.kind == "line":
        circ, line = a, b
    else:
        # point on circle tangency — fallback
        return np.zeros(0)

    cx, cy, r = circ.params[0], circ.params[1], circ.params[2]
    x0, y0, x1, y1 = line.params
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return np.zeros(1)
    # signed distance from centre to line
    dist = (dx * (y0 - cy) - dy * (x0 - cx)) / length
    return np.array([abs(dist) - r])


def _residual_distance(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    """Distance between two points == parameter."""
    target = float(c.parameter or 0.0)
    a = _ent(entities, c.entity_ids[0])
    b = _ent(entities, c.entity_ids[1])

    def _pt(e: SketchEntity) -> np.ndarray:
        if e.kind == "point":
            return np.array(e.params[:2])
        if e.kind == "line":
            return np.array(e.params[:2])
        return np.array(e.params[:2])

    pa, pb = _pt(a), _pt(b)
    dist = np.linalg.norm(pa - pb)
    return np.array([dist - target])


def _residual_angle(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    """Angle between two lines == parameter (radians)."""
    target = float(c.parameter or 0.0)
    a = _ent(entities, c.entity_ids[0])
    b = _ent(entities, c.entity_ids[1])
    da = _line_dir(a)
    db = _line_dir(b)
    na = np.linalg.norm(da)
    nb = np.linalg.norm(db)
    if na < 1e-12 or nb < 1e-12:
        return np.zeros(1)
    cos_ab = np.dot(da, db) / (na * nb)
    cos_ab = np.clip(cos_ab, -1.0, 1.0)
    angle = math.acos(cos_ab)
    return np.array([angle - target])


def _residual_equal(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    """Two lines have the same length, or two circles the same radius."""
    a = _ent(entities, c.entity_ids[0])
    b = _ent(entities, c.entity_ids[1])

    def _measure(e: SketchEntity) -> float:
        if e.kind == "line":
            da = _line_dir(e)
            return float(np.linalg.norm(da))
        if e.kind in ("circle", "arc"):
            return float(e.params[2])
        return 0.0

    return np.array([_measure(a) - _measure(b)])


def _residual_on_curve(entities: list[SketchEntity], c: Constraint) -> np.ndarray:
    """Point lies on a circle or arc."""
    pt = _ent(entities, c.entity_ids[0])
    curve = _ent(entities, c.entity_ids[1])
    px, py = pt.params[0], pt.params[1]
    cx, cy, r = curve.params[0], curve.params[1], curve.params[2]
    dist = math.hypot(px - cx, py - cy)
    return np.array([dist - r])


_RESIDUAL_DISPATCH: dict[str, Any] = {
    "coincident": _residual_coincident,
    "horizontal": _residual_horizontal,
    "vertical": _residual_vertical,
    "parallel": _residual_parallel,
    "perpendicular": _residual_perpendicular,
    "tangent": _residual_tangent,
    "distance": _residual_distance,
    "angle": _residual_angle,
    "equal": _residual_equal,
    "on_curve": _residual_on_curve,
}


def _build_residual_vector(entities: list[SketchEntity], constraints: list[Constraint]) -> np.ndarray:
    parts: list[np.ndarray] = []
    for c in constraints:
        fn = _RESIDUAL_DISPATCH.get(c.kind)
        if fn is None:
            continue
        try:
            r = fn(entities, c)
            parts.append(np.asarray(r, dtype=float))
        except (KeyError, ValueError):
            pass
    return np.concatenate(parts) if parts else np.zeros(0)


# ---------------------------------------------------------------------------
# Jacobian via numerical differentiation
# ---------------------------------------------------------------------------

def _build_jacobian(
    x: np.ndarray,
    entities: list[SketchEntity],
    offsets: list[int],
    constraints: list[Constraint],
    h: float = 1e-7,
) -> np.ndarray:
    """Numerical Jacobian J[i,j] = dF_i/dx_j using central differences."""
    _unpack(x, entities, offsets)
    f0 = _build_residual_vector(entities, constraints)
    n_res = len(f0)
    n_dof = len(x)
    J = np.zeros((n_res, n_dof))
    for j in range(n_dof):
        xp = x.copy(); xp[j] += h
        _unpack(xp, entities, offsets)
        fp = _build_residual_vector(entities, constraints)
        xm = x.copy(); xm[j] -= h
        _unpack(xm, entities, offsets)
        fm = _build_residual_vector(entities, constraints)
        if n_res > 0:
            J[:, j] = (fp - fm) / (2 * h)
    _unpack(x, entities, offsets)  # restore
    return J


# ---------------------------------------------------------------------------
# Newton-Raphson solver
# ---------------------------------------------------------------------------

def solve_sketch(
    entities: list[SketchEntity],
    constraints: list[Constraint],
    max_iters: int = 100,
    tol: float = 1e-6,
) -> SolveResult:
    """Solve the sketch using damped Newton-Raphson.

    Parameters
    ----------
    entities : list[SketchEntity]
        Entities whose params are updated in-place.
    constraints : list[Constraint]
        Constraints to satisfy.
    max_iters : int
        Maximum Newton iterations.
    tol : float
        Convergence tolerance on the residual norm.

    Returns
    -------
    SolveResult
        Contains updated entity list, convergence flag, iteration count, and
        final residual norm.
    """
    import copy
    entities = copy.deepcopy(entities)

    x, offsets = _pack(entities)
    n_dof = len(x)

    if n_dof == 0:
        # Nothing to solve — all entities fixed
        _unpack(x, entities, offsets)
        f = _build_residual_vector(entities, constraints)
        res = float(np.linalg.norm(f)) if len(f) > 0 else 0.0
        return SolveResult(
            converged=res <= tol, iters=0, residual=res,
            entities=entities, message="all entities fixed"
        )

    for it in range(max_iters):
        _unpack(x, entities, offsets)
        f = _build_residual_vector(entities, constraints)
        if len(f) == 0:
            break
        res = float(np.linalg.norm(f))
        if res <= tol:
            return SolveResult(
                converged=True, iters=it, residual=res, entities=entities
            )

        J = _build_jacobian(x, entities, offsets, constraints)
        _unpack(x, entities, offsets)  # restore after jacobian perturbations
        f = _build_residual_vector(entities, constraints)

        # Least-squares step: dx = -pinv(J) @ f
        try:
            dx, _, _, _ = np.linalg.lstsq(J, -f, rcond=None)
        except np.linalg.LinAlgError:
            break

        # Damped line-search (Armijo backtrack)
        alpha = 1.0
        res_old = float(np.linalg.norm(f))
        for _ in range(12):
            x_try = x + alpha * dx
            _unpack(x_try, entities, offsets)
            f_try = _build_residual_vector(entities, constraints)
            res_try = float(np.linalg.norm(f_try))
            if res_try < res_old:
                break
            alpha *= 0.5
        x = x + alpha * dx
        _unpack(x, entities, offsets)

    # Final residual
    f = _build_residual_vector(entities, constraints)
    res = float(np.linalg.norm(f)) if len(f) > 0 else 0.0
    converged = res <= tol
    msg = "" if converged else f"did not converge after {max_iters} iters (residual={res:.3e})"
    return SolveResult(
        converged=converged, iters=max_iters, residual=res,
        entities=entities, message=msg,
    )


# ---------------------------------------------------------------------------
# Consistency checker
# ---------------------------------------------------------------------------

def check_consistency(
    entities: list[SketchEntity],
    constraints: list[Constraint],
) -> dict:
    """Detect over-constrained, under-constrained, or contradictory sets.

    Returns a dict with keys:
      dof          — remaining degrees of freedom (0 = fully constrained)
      n_equations  — total constraint equations
      n_dof        — total free DOFs in entity set
      rank         — rank of the constraint Jacobian
      status       — 'under', 'fully', or 'over'
      redundant    — True if the system is over-determined (rank < n_equations)
      message      — human-readable summary
    """
    x, offsets = _pack(entities)
    n_dof = len(x)

    # Count how many scalar residuals the constraints produce
    _unpack(x, entities, offsets)
    f = _build_residual_vector(entities, constraints)
    n_eq = len(f)

    if n_dof == 0:
        return {
            "dof": 0, "n_equations": n_eq, "n_dof": 0,
            "rank": 0, "status": "fully" if n_eq == 0 else "over",
            "redundant": n_eq > 0, "message": "no free DOFs",
        }

    if n_eq == 0:
        return {
            "dof": n_dof, "n_equations": 0, "n_dof": n_dof,
            "rank": 0, "status": "under",
            "redundant": False, "message": f"no constraints, {n_dof} free DOFs",
        }

    J = _build_jacobian(x, entities, offsets, constraints)
    rank = int(np.linalg.matrix_rank(J, tol=1e-8))

    # redundant = more equations than independent ones
    redundant = n_eq > rank

    # Structural over-constraint: more equations supplied than free DOFs.
    # This is the Hoffmann-Joan-Arinyo definition: n_eq > n_dof means the
    # system is over-determined regardless of how many equations are linearly
    # independent (which may be less if they are redundant copies).
    if n_eq > n_dof:
        status = "over"
        dof_remaining = 0
        msg = (
            f"over-constrained: {n_eq} equations for {n_dof} DOF(s) "
            f"(rank={rank}, redundant equations: {n_eq - rank})"
        )
    elif rank >= n_dof:
        status = "fully"
        dof_remaining = 0
        msg = "fully constrained"
    else:
        status = "under"
        dof_remaining = n_dof - rank
        msg = f"under-constrained: {dof_remaining} DOF(s) remain free"

    return {
        "dof": max(0, dof_remaining),
        "n_equations": n_eq,
        "n_dof": n_dof,
        "rank": rank,
        "status": status,
        "redundant": redundant,
        "message": msg,
    }


# ---------------------------------------------------------------------------
# Drag operation
# ---------------------------------------------------------------------------

def drag_entity(
    entities: list[SketchEntity],
    constraints: list[Constraint],
    entity_id: str,
    new_position: list[float],
) -> list[SketchEntity]:
    """Re-solve with the named entity moved to new_position.

    The dragged entity is temporarily fixed at new_position, the remaining
    entities are solved, then the entity is un-fixed and the solution list is
    returned.

    Parameters
    ----------
    entities : list[SketchEntity]
        Current entity list (not mutated).
    constraints : list[Constraint]
        Active constraints.
    entity_id : str
        Id of the entity being dragged.
    new_position : list[float]
        New parameter vector for the dragged entity.

    Returns
    -------
    list[SketchEntity]
        Updated entities after re-solve.
    """
    import copy
    ents = copy.deepcopy(entities)
    for ent in ents:
        if ent.id == entity_id:
            n = len(ent.params)
            np_ = new_position[:n]
            if len(np_) < n:
                np_ = np_ + ent.params[len(np_):]
            ent.params = list(np_)
            ent.fixed = True
            break

    result = solve_sketch(ents, constraints)

    # Un-fix the dragged entity in the result
    for ent in result.entities:
        if ent.id == entity_id:
            ent.fixed = False
            break

    return result.entities


# ---------------------------------------------------------------------------
# LLM tool registration (optional — only when kerf_chat is importable)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    # ------------------------------------------------------------------
    # nurbs_sketch_solver
    # ------------------------------------------------------------------
    _sketch_solver_spec = ToolSpec(
        name="nurbs_sketch_solver",
        description=(
            "Solve a parametric 2-D sketch: apply geometric constraints "
            "(coincident, horizontal, vertical, parallel, perpendicular, tangent, "
            "distance, angle, equal, on_curve) to a set of entities (point, line, "
            "circle, arc) using Newton-Raphson constraint propagation "
            "(Sutherland 1963 / Hoffmann 2001).\n\n"
            "Input  — entities: [{kind, id, params, fixed?}], "
            "constraints: [{kind, entity_ids, parameter?}], "
            "max_iters (default 100), tol (default 1e-6).\n\n"
            "Returns {converged, iters, residual, entities, consistency} where "
            "consistency contains DOF accounting (dof, status, redundant)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "description": "List of sketch entities.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["point", "line", "circle", "arc"]},
                            "id": {"type": "string"},
                            "params": {"type": "array", "items": {"type": "number"}},
                            "fixed": {"type": "boolean"},
                        },
                        "required": ["kind", "id", "params"],
                    },
                },
                "constraints": {
                    "type": "array",
                    "description": "List of constraints to enforce.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "coincident", "horizontal", "vertical",
                                    "parallel", "perpendicular", "tangent",
                                    "distance", "angle", "equal", "on_curve",
                                ],
                            },
                            "entity_ids": {"type": "array", "items": {"type": "string"}},
                            "parameter": {"type": "number"},
                        },
                        "required": ["kind", "entity_ids"],
                    },
                },
                "max_iters": {"type": "integer", "default": 100},
                "tol": {"type": "number", "default": 1e-6},
            },
            "required": ["entities", "constraints"],
        },
    )

    @register(_sketch_solver_spec)
    async def run_nurbs_sketch_solver(ctx: "ProjectCtx", args: bytes) -> str:  # type: ignore[misc]
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            entities = [
                SketchEntity(
                    kind=e["kind"],
                    id=e["id"],
                    params=list(map(float, e["params"])),
                    fixed=bool(e.get("fixed", False)),
                )
                for e in a.get("entities", [])
            ]
            constraints = [
                Constraint(
                    kind=c["kind"],
                    entity_ids=list(c["entity_ids"]),
                    parameter=float(c["parameter"]) if c.get("parameter") is not None else None,
                )
                for c in a.get("constraints", [])
            ]
        except (KeyError, ValueError, TypeError) as exc:
            return err_payload(f"malformed input: {exc}", "BAD_ARGS")

        max_iters = int(a.get("max_iters", 100))
        tol = float(a.get("tol", 1e-6))

        result = solve_sketch(entities, constraints, max_iters=max_iters, tol=tol)
        consistency = check_consistency(result.entities, constraints)

        return ok_payload({
            "converged": result.converged,
            "iters": result.iters,
            "residual": result.residual,
            "message": result.message,
            "entities": [
                {"kind": e.kind, "id": e.id, "params": e.params, "fixed": e.fixed}
                for e in result.entities
            ],
            "consistency": consistency,
        })

    # ------------------------------------------------------------------
    # nurbs_sketch_drag
    # ------------------------------------------------------------------
    _sketch_drag_spec = ToolSpec(
        name="nurbs_sketch_drag",
        description=(
            "Interactively drag a sketch entity to a new position and re-solve "
            "all constraints.  This is the canonical 'grab + drag' operation used "
            "in constraint-based sketch editors (SolveSpace / FreeCAD Sketcher style).\n\n"
            "Input — entities, constraints (same schema as nurbs_sketch_solver), "
            "entity_id: str, new_position: [float, ...] (new params for the entity).\n\n"
            "Returns {entities} with updated positions after re-solve."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["point", "line", "circle", "arc"]},
                            "id": {"type": "string"},
                            "params": {"type": "array", "items": {"type": "number"}},
                            "fixed": {"type": "boolean"},
                        },
                        "required": ["kind", "id", "params"],
                    },
                },
                "constraints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "entity_ids": {"type": "array", "items": {"type": "string"}},
                            "parameter": {"type": "number"},
                        },
                        "required": ["kind", "entity_ids"],
                    },
                },
                "entity_id": {
                    "type": "string",
                    "description": "ID of the entity to drag.",
                },
                "new_position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "New param vector for the dragged entity.",
                },
            },
            "required": ["entities", "constraints", "entity_id", "new_position"],
        },
    )

    @register(_sketch_drag_spec)
    async def run_nurbs_sketch_drag(ctx: "ProjectCtx", args: bytes) -> str:  # type: ignore[misc]
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            entities = [
                SketchEntity(
                    kind=e["kind"],
                    id=e["id"],
                    params=list(map(float, e["params"])),
                    fixed=bool(e.get("fixed", False)),
                )
                for e in a.get("entities", [])
            ]
            constraints = [
                Constraint(
                    kind=c["kind"],
                    entity_ids=list(c["entity_ids"]),
                    parameter=float(c["parameter"]) if c.get("parameter") is not None else None,
                )
                for c in a.get("constraints", [])
            ]
            entity_id = str(a["entity_id"])
            new_position = list(map(float, a["new_position"]))
        except (KeyError, ValueError, TypeError) as exc:
            return err_payload(f"malformed input: {exc}", "BAD_ARGS")

        updated = drag_entity(entities, constraints, entity_id, new_position)

        return ok_payload({
            "entities": [
                {"kind": e.kind, "id": e.id, "params": e.params, "fixed": e.fixed}
                for e in updated
            ]
        })
