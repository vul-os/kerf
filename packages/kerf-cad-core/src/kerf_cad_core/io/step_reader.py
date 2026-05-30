"""Pure-Python STEP Part 21 reader — AP203 / AP214 B-rep subset.

Parses a STEP Part 21 file and constructs a Kerf ``Body`` from
``MANIFOLD_SOLID_BREP`` / ``CLOSED_SHELL`` entities.

Supported entity subset
-----------------------
Geometry primitives
    CARTESIAN_POINT, DIRECTION, VECTOR, AXIS2_PLACEMENT_3D,
    LINE, CIRCLE, B_SPLINE_CURVE_WITH_KNOTS (ignored — edges fall
    back to straight-line approximation)

Surfaces
    PLANE, CYLINDRICAL_SURFACE, SPHERICAL_SURFACE,
    CONICAL_SURFACE (treated as plane at apex), TOROIDAL_SURFACE

Topology
    VERTEX_POINT, EDGE_CURVE, ORIENTED_EDGE, EDGE_LOOP,
    FACE_OUTER_BOUND, FACE_BOUND, ADVANCED_FACE,
    CLOSED_SHELL, OPEN_SHELL, MANIFOLD_SOLID_BREP,
    ADVANCED_BREP_SHAPE_REPRESENTATION,
    BREP_WITH_VOIDS (outer shell only, voids skipped)

Everything else is silently ignored so that real AP214 files that
include product-structure, tolerance, colour, and material entities
still parse correctly.

Usage
-----
    from kerf_cad_core.io.step_reader import read_step

    body = read_step("path/to/part.step")
    # or
    body = read_step(pathlib.Path("part.step"))
    # or from a string
    body = read_step(step_text, source="<string>")

Returns a :class:`kerf_cad_core.geom.brep.Body`.
Raises :class:`StepReadError` on unrecoverable parse failures.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
    Coedge,
    CylinderSurface,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    SphereSurface,
    TorusSurface,
    Vertex,
    validate_body,
)

__all__ = ["read_step", "StepReadError", "StepReadResult", "HealStats"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class HealStats:
    """Per-body heal statistics produced by the auto-heal pass."""
    vertices_merged: int = 0
    edges_stitched: int = 0
    faces_orientation_fixed: int = 0

    def is_clean(self, vert_tol: int = 2, edge_tol: int = 1) -> bool:
        """Return True if the body was already nearly clean (near-zero repairs)."""
        return (
            self.vertices_merged <= vert_tol
            and self.edges_stitched <= edge_tol
        )


@dataclass
class StepReadResult:
    """Result of :func:`read_step` when ``auto_heal=True`` or when a caller
    requests the rich result object.

    The object is also **iterable** as the plain bodies list so that existing
    callers that do ``body, = read_step(...)`` or ``for b in read_step(...)``
    continue to work after upgrading to return ``StepReadResult``.

    Attributes
    ----------
    bodies:
        List of :class:`~kerf_cad_core.geom.brep.Body` objects — one per
        ``MANIFOLD_SOLID_BREP`` found in the file (typically one).
    heal_stats:
        Per-body :class:`HealStats` dict keyed by body index.
        Empty when ``auto_heal=False``.
    heal_warnings:
        List of body indices where heal raised an exception (graceful
        degradation — the un-healed body is still returned).
    """
    bodies: List[Body] = field(default_factory=list)
    heal_stats: Dict[int, HealStats] = field(default_factory=dict)
    heal_warnings: List[int] = field(default_factory=list)

    # ---- iterable protocol so legacy callers still work --------------------

    def __iter__(self):
        """Iterate over bodies so ``body, = read_step(...)`` still works."""
        return iter(self.bodies)

    def __len__(self):
        return len(self.bodies)

    def __getitem__(self, index):
        return self.bodies[index]


# ---------------------------------------------------------------------------
# Public error type
# ---------------------------------------------------------------------------


class StepReadError(RuntimeError):
    """Raised for unrecoverable STEP parse/build errors."""


# ---------------------------------------------------------------------------
# Lexer / parser
# ---------------------------------------------------------------------------

# Regex for a single entity-instance line after normalisation.
# Matches:  #NNN = ENTITY_NAME ( ... ) ;
_ENTITY_RE = re.compile(
    r"#(\d+)\s*=\s*([A-Z_][A-Z0-9_]*)\s*\((.*)$",
    re.DOTALL,
)

# A reference to another entity: #NNN
_REF_RE = re.compile(r"#(\d+)")

# Floating-point number (STEP uses E not e, and no leading sign in exponent)
_REAL_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][+-]?\d+)?")

# STEP enum literal  .ENUMVAL.
_ENUM_RE = re.compile(r"\.([A-Z_][A-Z0-9_]*)\.")

# Logical/boolean literals
_TRUE_ENUMS = {"T", "TRUE", "F_OR_T"}  # same_sense .T.
_FALSE_ENUMS = {"F", "FALSE"}


def _strip_comments(text: str) -> str:
    """Remove /* ... */ STEP comments (possibly multi-line)."""
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)


def _logical(token: str) -> bool:
    """Convert STEP logical/boolean token to Python bool."""
    if isinstance(token, bool):
        return token
    token = token.strip(" .")
    return token.upper() in _TRUE_ENUMS


def _normalise(text: str) -> str:
    """Strip comments and join line continuations."""
    text = _strip_comments(text)
    # STEP line-continuation: a line ending with = continued on next
    # In practice Part 21 just wraps long lines — we join all physical
    # lines to logical lines terminated by ';'
    return text


def _tokenise_list(s: str) -> List[str]:
    """Split a comma-delimited argument string respecting nested parens.

    Returns a list of raw token strings.
    """
    tokens: List[str] = []
    depth = 0
    cur: List[str] = []
    for ch in s:
        if ch == "(" :
            depth += 1
            cur.append(ch)
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            tokens.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur).strip())
    return tokens


def _parse_list(s: str) -> List[str]:
    """Parse the outer parenthesised list '(a,b,c)' → ['a','b','c']."""
    s = s.strip()
    if s.startswith("(") and s.endswith(")"):
        return _tokenise_list(s[1:-1])
    return _tokenise_list(s)


def _parse_real(s: str) -> float:
    s = s.strip()
    m = _REAL_RE.match(s)
    if m:
        return float(m.group())
    raise StepReadError(f"Cannot parse real: {s!r}")


def _parse_refs(s: str) -> List[int]:
    """Extract all #NNN references from a token string."""
    return [int(m.group(1)) for m in _REF_RE.finditer(s)]


def _parse_point_list(tokens: List[str]) -> List[float]:
    """Parse a STEP coordinate list  ( x, y, z ) from one token."""
    inner = tokens[0].strip()
    if inner.startswith("(") and inner.endswith(")"):
        parts = _parse_list(inner)
    else:
        parts = tokens
    return [_parse_real(p) for p in parts]


# ---------------------------------------------------------------------------
# Entity catalogue
# ---------------------------------------------------------------------------

EntityDict = Dict[int, Any]  # ref_id → entity


class _StepParser:
    """Two-pass parser: first build a raw entity map, then resolve."""

    def __init__(self, source: str):
        self._raw: Dict[int, Tuple[str, str]] = {}  # id → (typename, args_str)
        self._cache: Dict[int, Any] = {}
        self._parse_raw(source)

    # --- first pass: extract raw entity records ----------------------------

    def _parse_raw(self, text: str) -> None:
        text = _normalise(text)
        # Find DATA section
        m = re.search(r"\bDATA\s*;", text, re.IGNORECASE)
        if not m:
            raise StepReadError("No DATA section found in STEP file")
        data_text = text[m.end():]

        # Walk character-by-character collecting logical lines terminated by ;
        # This handles multi-line string args correctly.
        # We collect tokens up to the next ';' that is not inside parentheses
        depth = 0
        in_string = False
        buf: List[str] = []
        i = 0
        while i < len(data_text):
            ch = data_text[i]
            if in_string:
                buf.append(ch)
                if ch == "'":
                    # STEP strings end at unescaped quote
                    in_string = False
            elif ch == "'":
                in_string = True
                buf.append(ch)
            elif ch == "(":
                depth += 1
                buf.append(ch)
            elif ch == ")":
                depth -= 1
                buf.append(ch)
            elif ch == ";" and depth == 0:
                line = "".join(buf).strip()
                buf = []
                self._handle_line(line)
                # Stop at ENDSEC
                if re.match(r"^ENDSEC", line, re.IGNORECASE):
                    break
            else:
                buf.append(ch)
            i += 1

    def _handle_line(self, line: str) -> None:
        m = _ENTITY_RE.match(line)
        if not m:
            return
        ref_id = int(m.group(1))
        typename = m.group(2).upper()
        # group(3) captures everything after the opening '(' to end-of-line,
        # which includes the entity's closing ')' (and possibly more if the
        # regex captured too far).  We strip exactly ONE trailing ')' that
        # belongs to the outermost entity call, but leave all inner ')' intact.
        raw = m.group(3)
        # Remove the last ')' that closes the entity (may be followed by whitespace)
        raw = raw.rstrip()
        if raw.endswith(")"):
            raw = raw[:-1]
        args_str = raw
        self._raw[ref_id] = (typename, args_str)

    # --- second pass: resolve entities on demand ---------------------------

    def get(self, ref_id: int) -> Any:
        """Resolve entity #ref_id to a Python object (cached)."""
        if ref_id in self._cache:
            return self._cache[ref_id]
        if ref_id not in self._raw:
            raise StepReadError(f"Undefined entity reference #{ref_id}")
        typename, args_str = self._raw[ref_id]
        result = self._resolve(ref_id, typename, args_str)
        self._cache[ref_id] = result
        return result

    def typename(self, ref_id: int) -> str:
        if ref_id not in self._raw:
            return ""
        return self._raw[ref_id][0]

    def _args(self, args_str: str) -> List[str]:
        """Split top-level comma-separated args."""
        return _tokenise_list(args_str)

    def _resolve(self, ref_id: int, typename: str, args_str: str) -> Any:
        """Dispatch to type-specific resolver."""
        args = self._args(args_str)
        method = getattr(self, f"_resolve_{typename}", None)
        if method is not None:
            return method(ref_id, args)
        # Complex / supertype entities: try to find the first known type
        # in the token stream (the (A() B() C()) form)
        return self._resolve_complex(ref_id, typename, args_str, args)

    def _resolve_complex(self, ref_id: int, typename: str,
                          args_str: str, args: List[str]) -> Any:
        """Handle complex entities like GEOMETRIC_REPRESENTATION_CONTEXT."""
        # We only care about specific types; everything else → None
        return None

    # --- geometry primitives -----------------------------------------------

    def _resolve_CARTESIAN_POINT(self, ref_id: int, args: List[str]) -> np.ndarray:
        # CARTESIAN_POINT ( name, (x, y, z) )
        if len(args) < 2:
            return np.zeros(3)
        coords_tok = args[1].strip()
        coords = _parse_list(coords_tok)
        vals = [_parse_real(c) for c in coords if c.strip()]
        while len(vals) < 3:
            vals.append(0.0)
        return np.array(vals[:3], dtype=float)

    def _resolve_DIRECTION(self, ref_id: int, args: List[str]) -> np.ndarray:
        # DIRECTION ( name, (dx, dy, dz) )
        if len(args) < 2:
            return np.array([1.0, 0.0, 0.0])
        coords_tok = args[1].strip()
        coords = _parse_list(coords_tok)
        vals = [_parse_real(c) for c in coords if c.strip()]
        while len(vals) < 3:
            vals.append(0.0)
        return np.array(vals[:3], dtype=float)

    def _resolve_VECTOR(self, ref_id: int, args: List[str]) -> np.ndarray:
        # VECTOR ( name, direction_ref, magnitude )
        if len(args) < 3:
            return np.array([1.0, 0.0, 0.0])
        dir_ref = _parse_refs(args[1])
        mag = _parse_real(args[2])
        if dir_ref:
            direction = self.get(dir_ref[0])
            if direction is not None:
                n = np.linalg.norm(direction)
                if n > 1e-14:
                    return direction / n * mag
        return np.array([mag, 0.0, 0.0])

    def _resolve_AXIS2_PLACEMENT_3D(self, ref_id: int, args: List[str]) -> dict:
        # AXIS2_PLACEMENT_3D ( name, origin_ref, axis_ref, ref_direction_ref )
        origin = np.zeros(3)
        axis = np.array([0.0, 0.0, 1.0])
        ref_dir = np.array([1.0, 0.0, 0.0])

        if len(args) >= 2 and "#" in args[1]:
            refs = _parse_refs(args[1])
            if refs:
                pt = self.get(refs[0])
                if pt is not None:
                    origin = np.asarray(pt, dtype=float)

        if len(args) >= 3 and "#" in args[2]:
            refs = _parse_refs(args[2])
            if refs:
                d = self.get(refs[0])
                if d is not None:
                    axis = _unit(np.asarray(d, dtype=float))

        if len(args) >= 4 and "#" in args[3]:
            refs = _parse_refs(args[3])
            if refs:
                d = self.get(refs[0])
                if d is not None:
                    ref_dir = _unit(np.asarray(d, dtype=float))

        # Build orthonormal frame: z=axis, x=ref_dir re-orthogonalised
        z = _unit(axis)
        x = _unit(ref_dir - np.dot(ref_dir, z) * z)
        if np.linalg.norm(x) < 1e-10:
            x = _perp(z)
        y = _unit(np.cross(z, x))
        return {"origin": origin, "x": x, "y": y, "z": z}

    def _resolve_LINE(self, ref_id: int, args: List[str]) -> dict:
        # LINE ( name, origin_point_ref, direction_vector_ref )
        origin = np.zeros(3)
        direction = np.array([1.0, 0.0, 0.0])
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                pt = self.get(refs[0])
                if pt is not None:
                    origin = np.asarray(pt, dtype=float)
        if len(args) >= 3:
            refs = _parse_refs(args[2])
            if refs:
                v = self.get(refs[0])
                if v is not None:
                    direction = _unit(np.asarray(v, dtype=float))
        return {"type": "LINE", "origin": origin, "direction": direction}

    def _resolve_CIRCLE(self, ref_id: int, args: List[str]) -> dict:
        # CIRCLE ( name, placement_ref, radius )
        placement = None
        radius = 1.0
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                placement = self.get(refs[0])
        if len(args) >= 3:
            radius = _parse_real(args[2])
        return {"type": "CIRCLE", "placement": placement, "radius": radius}

    def _resolve_B_SPLINE_CURVE_WITH_KNOTS(self, ref_id: int, args: List[str]) -> dict:
        # We don't evaluate B-splines; fall back to straight line in edge builder
        return {"type": "BSPLINE"}

    def _resolve_B_SPLINE_CURVE(self, ref_id: int, args: List[str]) -> dict:
        return {"type": "BSPLINE"}

    # --- surfaces ----------------------------------------------------------

    def _resolve_PLANE(self, ref_id: int, args: List[str]) -> Plane:
        # PLANE ( name, placement_ref )
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                pl = self.get(refs[0])
                if pl is not None and isinstance(pl, dict):
                    return Plane(
                        origin=pl["origin"],
                        x_axis=pl["x"],
                        y_axis=pl["y"],
                    )
        return Plane(origin=np.zeros(3), x_axis=np.array([1., 0., 0.]),
                     y_axis=np.array([0., 1., 0.]))

    def _resolve_CYLINDRICAL_SURFACE(self, ref_id: int, args: List[str]) -> CylinderSurface:
        # CYLINDRICAL_SURFACE ( name, placement_ref, radius )
        placement = None
        radius = 1.0
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                placement = self.get(refs[0])
        if len(args) >= 3:
            radius = _parse_real(args[2])
        if placement and isinstance(placement, dict):
            return CylinderSurface(
                center=placement["origin"],
                axis=placement["z"],
                radius=radius,
                x_ref=placement["x"],
            )
        return CylinderSurface(
            center=np.zeros(3),
            axis=np.array([0., 0., 1.]),
            radius=radius,
        )

    def _resolve_SPHERICAL_SURFACE(self, ref_id: int, args: List[str]) -> SphereSurface:
        # SPHERICAL_SURFACE ( name, placement_ref, radius )
        placement = None
        radius = 1.0
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                placement = self.get(refs[0])
        if len(args) >= 3:
            radius = _parse_real(args[2])
        if placement and isinstance(placement, dict):
            return SphereSurface(center=placement["origin"], radius=radius)
        return SphereSurface(center=np.zeros(3), radius=radius)

    def _resolve_TOROIDAL_SURFACE(self, ref_id: int, args: List[str]) -> TorusSurface:
        # TOROIDAL_SURFACE ( name, placement_ref, major_radius, minor_radius )
        placement = None
        major = 1.0
        minor = 0.25
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                placement = self.get(refs[0])
        if len(args) >= 3:
            major = _parse_real(args[2])
        if len(args) >= 4:
            minor = _parse_real(args[3])
        if placement and isinstance(placement, dict):
            return TorusSurface(
                center=placement["origin"],
                axis=placement["z"],
                major_radius=major,
                minor_radius=minor,
            )
        return TorusSurface(
            center=np.zeros(3),
            axis=np.array([0., 0., 1.]),
            major_radius=major,
            minor_radius=minor,
        )

    def _resolve_CONICAL_SURFACE(self, ref_id: int, args: List[str]) -> Plane:
        # Approximate conical surface as a plane at the apex position
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                pl = self.get(refs[0])
                if pl is not None and isinstance(pl, dict):
                    return Plane(origin=pl["origin"], x_axis=pl["x"], y_axis=pl["y"])
        return Plane(origin=np.zeros(3), x_axis=np.array([1., 0., 0.]),
                     y_axis=np.array([0., 1., 0.]))

    def _resolve_SURFACE_OF_LINEAR_EXTRUSION(self, ref_id: int, args: List[str]) -> Plane:
        return Plane(origin=np.zeros(3), x_axis=np.array([1., 0., 0.]),
                     y_axis=np.array([0., 1., 0.]))

    def _resolve_SURFACE_OF_REVOLUTION(self, ref_id: int, args: List[str]) -> Plane:
        return Plane(origin=np.zeros(3), x_axis=np.array([1., 0., 0.]),
                     y_axis=np.array([0., 1., 0.]))

    # --- topology ----------------------------------------------------------

    def _resolve_VERTEX_POINT(self, ref_id: int, args: List[str]) -> Vertex:
        # VERTEX_POINT ( name, point_ref )
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                pt = self.get(refs[0])
                if pt is not None:
                    return Vertex(np.asarray(pt, dtype=float), tol=1e-7)
        return Vertex(np.zeros(3), tol=1e-7)

    def _resolve_EDGE_CURVE(self, ref_id: int, args: List[str]) -> dict:
        # EDGE_CURVE ( name, v_start_ref, v_end_ref, curve_ref, same_sense )
        v_start = v_end = None
        curve = None
        same_sense = True

        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                v_start = self.get(refs[0])
        if len(args) >= 3:
            refs = _parse_refs(args[2])
            if refs:
                v_end = self.get(refs[0])
        if len(args) >= 4:
            refs = _parse_refs(args[3])
            if refs:
                curve = self.get(refs[0])
        if len(args) >= 5:
            same_sense = _logical(args[4])

        return {
            "type": "EDGE_CURVE",
            "v_start": v_start,
            "v_end": v_end,
            "curve": curve,
            "same_sense": same_sense,
        }

    def _resolve_ORIENTED_EDGE(self, ref_id: int, args: List[str]) -> dict:
        # ORIENTED_EDGE ( name, *, *, edge_element_ref, orientation )
        edge_element = None
        orientation = True
        # Find the last two meaningful args (edge_element_ref and orientation)
        # Standard form: ( name, *, *, ref, bool )
        refs_found = _parse_refs(args[3]) if len(args) >= 4 else []
        if refs_found:
            edge_element = self.get(refs_found[0])
        if len(args) >= 5:
            orientation = _logical(args[4])
        return {
            "type": "ORIENTED_EDGE",
            "edge_element": edge_element,
            "orientation": orientation,
        }

    def _resolve_EDGE_LOOP(self, ref_id: int, args: List[str]) -> dict:
        # EDGE_LOOP ( name, (oriented_edge_refs...) )
        oriented_edges = []
        if len(args) >= 2:
            # args[1] is  ( #NN, #MM, ... )
            refs = _parse_refs(args[1])
            oriented_edges = [self.get(r) for r in refs]
        return {"type": "EDGE_LOOP", "oriented_edges": oriented_edges}

    def _resolve_FACE_OUTER_BOUND(self, ref_id: int, args: List[str]) -> dict:
        # FACE_OUTER_BOUND ( name, loop_ref, orientation )
        loop = None
        orientation = True
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                loop = self.get(refs[0])
        if len(args) >= 3:
            orientation = _logical(args[2])
        return {"type": "FACE_OUTER_BOUND", "loop": loop, "orientation": orientation,
                "is_outer": True}

    def _resolve_FACE_BOUND(self, ref_id: int, args: List[str]) -> dict:
        # FACE_BOUND ( name, loop_ref, orientation )
        loop = None
        orientation = True
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                loop = self.get(refs[0])
        if len(args) >= 3:
            orientation = _logical(args[2])
        return {"type": "FACE_BOUND", "loop": loop, "orientation": orientation,
                "is_outer": False}

    def _resolve_ADVANCED_FACE(self, ref_id: int, args: List[str]) -> dict:
        # ADVANCED_FACE ( name, (bounds...), surface_ref, same_sense )
        bounds = []
        surface = None
        same_sense = True
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            bounds = [self.get(r) for r in refs]
        if len(args) >= 3:
            refs = _parse_refs(args[2])
            if refs:
                surface = self.get(refs[0])
        if len(args) >= 4:
            same_sense = _logical(args[3])
        return {
            "type": "ADVANCED_FACE",
            "bounds": bounds,
            "surface": surface,
            "same_sense": same_sense,
        }

    def _resolve_CLOSED_SHELL(self, ref_id: int, args: List[str]) -> dict:
        # CLOSED_SHELL ( name, (face_refs...) )
        face_refs = []
        if len(args) >= 2:
            face_refs = _parse_refs(args[1])
        return {"type": "CLOSED_SHELL", "face_refs": face_refs, "is_closed": True}

    def _resolve_OPEN_SHELL(self, ref_id: int, args: List[str]) -> dict:
        face_refs = []
        if len(args) >= 2:
            face_refs = _parse_refs(args[1])
        return {"type": "OPEN_SHELL", "face_refs": face_refs, "is_closed": False}

    def _resolve_CONNECTED_FACE_SET(self, ref_id: int, args: List[str]) -> dict:
        face_refs = []
        if len(args) >= 2:
            face_refs = _parse_refs(args[1])
        return {"type": "CLOSED_SHELL", "face_refs": face_refs, "is_closed": True}

    def _resolve_MANIFOLD_SOLID_BREP(self, ref_id: int, args: List[str]) -> dict:
        # MANIFOLD_SOLID_BREP ( name, outer_shell_ref )
        outer_shell = None
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                outer_shell = self.get(refs[0])
        return {"type": "MANIFOLD_SOLID_BREP", "outer_shell": outer_shell}

    def _resolve_BREP_WITH_VOIDS(self, ref_id: int, args: List[str]) -> dict:
        # BREP_WITH_VOIDS ( name, outer_shell_ref, (void_shells...) )
        outer_shell = None
        if len(args) >= 2:
            refs = _parse_refs(args[1])
            if refs:
                outer_shell = self.get(refs[0])
        return {"type": "MANIFOLD_SOLID_BREP", "outer_shell": outer_shell}

    def _resolve_ADVANCED_BREP_SHAPE_REPRESENTATION(
            self, ref_id: int, args: List[str]) -> dict:
        # ADVANCED_BREP_SHAPE_REPRESENTATION ( name, (items...), context_ref )
        item_refs: List[int] = []
        if len(args) >= 2:
            item_refs = _parse_refs(args[1])
        return {
            "type": "ADVANCED_BREP_SHAPE_REPRESENTATION",
            "item_refs": item_refs,
        }

    def _resolve_SHAPE_REPRESENTATION(self, ref_id: int, args: List[str]) -> dict:
        return self._resolve_ADVANCED_BREP_SHAPE_REPRESENTATION(ref_id, args)

    # --- passthrough for unneeded entities --------------------------------

    def _resolve_UNCERTAINTY_MEASURE_WITH_UNIT(self, ref_id: int, args: List[str]) -> None:
        return None

    def _resolve_LENGTH_MEASURE(self, ref_id: int, args: List[str]) -> None:
        return None

    # --- collect all MANIFOLD_SOLID_BREP entities -------------------------

    def find_bodies(self) -> List[int]:
        """Return ref_ids of all MANIFOLD_SOLID_BREP entities."""
        return [
            rid for rid, (tn, _) in self._raw.items()
            if tn in ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS")
        ]


# ---------------------------------------------------------------------------
# B-rep builder helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _perp(axis: np.ndarray) -> np.ndarray:
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(ref, axis))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    return _unit(np.cross(axis, ref))


def _make_edge_curve(edge_curve_dict: dict, vertex_pool: Dict[int, Vertex]) -> Edge:
    """Build a Kerf Edge from an EDGE_CURVE entity dict.

    STEP ``EDGE_CURVE.same_sense`` indicates whether the underlying curve
    parameter increases from ``v_start`` to ``v_end`` (.T.) or in the
    reverse direction (.F.).  For our purposes, the Kerf ``Edge`` always
    has ``t0`` pointing at ``v_start`` and ``t1`` at ``v_end``.  We
    build the underlying curve such that ``curve.evaluate(t0) ≈ v_start``
    and ``curve.evaluate(t1) ≈ v_end``, absorbing the same_sense flag
    into the geometry parametrisation where needed (for arcs).

    The STEP ``ORIENTED_EDGE.orientation`` flag is applied later in
    ``_build_loop`` via the ``Coedge.orientation`` field.
    """
    ec = edge_curve_dict
    v_start_raw = ec.get("v_start")
    v_end_raw = ec.get("v_end")

    # v_start and v_end are Vertex objects from the parser
    v_start = _intern_vertex(v_start_raw, vertex_pool)
    v_end = _intern_vertex(v_end_raw, vertex_pool)

    curve_raw = ec.get("curve")
    same_sense = ec.get("same_sense", True)

    # Build geometry — the returned (curve, t0, t1) already accounts for
    # same_sense so that curve.evaluate(t0) ≈ v_start.point
    curve, t0, t1 = _build_curve_geometry(curve_raw, v_start, v_end, same_sense)

    return Edge(curve, t0, t1, v_start, v_end, tol=1e-7)


def _intern_vertex(v_raw: Any, pool: Dict[int, Vertex]) -> Vertex:
    """Return a shared Vertex from pool by identity of the input object."""
    if v_raw is None:
        return Vertex(np.zeros(3), tol=1e-7)
    key = id(v_raw)
    if key not in pool:
        pool[key] = v_raw if isinstance(v_raw, Vertex) else Vertex(
            np.asarray(v_raw, dtype=float), tol=1e-7
        )
    return pool[key]


def _build_curve_geometry(curve_raw: Any, v_start: Vertex, v_end: Vertex,
                           same_sense: bool) -> Tuple[Any, float, float]:
    """Return (curve_obj, t0, t1) from raw parsed curve entity."""
    if curve_raw is None or not isinstance(curve_raw, dict):
        # Fall back to straight line between vertices
        return Line3(v_start.point, v_end.point), 0.0, 1.0

    ctype = curve_raw.get("type", "")

    if ctype == "LINE":
        # Parametrise as t in [0,1] where 0=start, 1=end
        return Line3(v_start.point, v_end.point), 0.0, 1.0

    elif ctype == "CIRCLE":
        placement = curve_raw.get("placement")
        radius = float(curve_raw.get("radius", 1.0))
        if placement and isinstance(placement, dict):
            center = placement["origin"]
            x_axis = placement["x"]
            y_axis = placement["y"]
        else:
            center = np.zeros(3)
            x_axis = np.array([1.0, 0.0, 0.0])
            y_axis = np.array([0.0, 1.0, 0.0])

        # Compute start/end angles from vertex positions
        def _angle(pt: np.ndarray) -> float:
            d = pt - center
            return math.atan2(float(np.dot(d, y_axis)),
                              float(np.dot(d, x_axis)))

        t0 = _angle(v_start.point)
        t1 = _angle(v_end.point)
        if same_sense and t1 <= t0:
            t1 += 2.0 * math.pi
        elif not same_sense and t0 <= t1:
            t0 += 2.0 * math.pi

        return CircleArc3(center, radius, x_axis, y_axis, min(t0, t1),
                          max(t0, t1)), min(t0, t1), max(t0, t1)

    else:
        # B-spline or unknown — approximate as straight line
        return Line3(v_start.point, v_end.point), 0.0, 1.0


# ---------------------------------------------------------------------------
# Shell builder
# ---------------------------------------------------------------------------


def _build_shell(shell_dict: dict, parser: _StepParser) -> Shell:
    """Convert a CLOSED_SHELL / OPEN_SHELL dict into a Kerf Shell."""
    face_refs = shell_dict.get("face_refs", [])
    is_closed = shell_dict.get("is_closed", True)

    # Shared vertex pool: keyed by id() of the raw Vertex object from parser
    vertex_pool: Dict[int, Vertex] = {}
    # Edge pool: keyed by the edge_curve entity's id() to share across faces
    edge_pool: Dict[int, Edge] = {}

    faces: List[Face] = []
    for fref in face_refs:
        af = parser.get(fref)
        if af is None or not isinstance(af, dict):
            continue
        face = _build_face(af, parser, vertex_pool, edge_pool)
        if face is not None:
            faces.append(face)

    return Shell(faces, is_closed=is_closed)


def _build_face(af: dict, parser: _StepParser,
                vertex_pool: Dict[int, Vertex],
                edge_pool: Dict[int, Edge]) -> Optional[Face]:
    """Build a Kerf Face from an ADVANCED_FACE entity dict."""
    bounds = af.get("bounds", [])
    surface = af.get("surface")
    same_sense = af.get("same_sense", True)

    if surface is None:
        surface = Plane(
            origin=np.zeros(3),
            x_axis=np.array([1., 0., 0.]),
            y_axis=np.array([0., 1., 0.]),
        )

    loops: List[Loop] = []
    for bound in bounds:
        if bound is None or not isinstance(bound, dict):
            continue
        loop = _build_loop(bound, parser, vertex_pool, edge_pool)
        if loop is not None:
            loops.append(loop)

    if not loops:
        return None

    return Face(surface, loops, orientation=same_sense, tol=1e-7)


def _build_loop(bound: dict, parser: _StepParser,
                vertex_pool: Dict[int, Vertex],
                edge_pool: Dict[int, Edge]) -> Optional[Loop]:
    """Build a Kerf Loop from a FACE_OUTER_BOUND / FACE_BOUND dict."""
    is_outer = bound.get("is_outer", True)
    loop_data = bound.get("loop")
    # bound orientation
    bound_orient = bound.get("orientation", True)

    if loop_data is None or not isinstance(loop_data, dict):
        return None
    if loop_data.get("type") != "EDGE_LOOP":
        return None

    oriented_edges = loop_data.get("oriented_edges", [])
    coedges: List[Coedge] = []

    for oe in oriented_edges:
        if oe is None or not isinstance(oe, dict):
            continue
        edge_element = oe.get("edge_element")
        oe_orientation = oe.get("orientation", True)
        if edge_element is None or not isinstance(edge_element, dict):
            continue
        if edge_element.get("type") != "EDGE_CURVE":
            continue

        ec_id = id(edge_element)
        if ec_id not in edge_pool:
            edge_pool[ec_id] = _make_edge_curve(edge_element, vertex_pool)
        edge = edge_pool[ec_id]

        # ORIENTED_EDGE orientation w.r.t. EDGE_CURVE same_sense already
        # resolved in _make_edge_curve; here we apply the oriented_edge sense.
        # The coedge orientation: True => forward along edge (v_start→v_end)
        coedge_orient = oe_orientation
        if not bound_orient:
            coedge_orient = not coedge_orient

        coedges.append(Coedge(edge, coedge_orient))

    if not coedges:
        return None

    return Loop(coedges, is_outer=is_outer)


# ---------------------------------------------------------------------------
# Volume helper (divergence theorem — polygonal approximation)
# ---------------------------------------------------------------------------


def _body_volume(body: Body) -> float:
    """Signed-divergence-theorem volume estimate (triangle fan per face loop)."""
    vol = 0.0
    for face in body.all_faces():
        outer = face.outer_loop()
        if outer is None or len(outer.coedges) < 3:
            continue
        pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
        p0 = pts[0]
        for i in range(1, len(pts) - 1):
            a = pts[i] - p0
            b = pts[i + 1] - p0
            cross = np.cross(a, b)
            vol += float(np.dot(p0, cross))
    return abs(vol) / 6.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _compute_heal_stats(body_before: Body, body_after: Body) -> HealStats:
    """Compute HealStats by comparing vertex / edge counts before and after heal.

    ``vertices_merged`` = vertices_before − vertices_after (net reduction).
    ``edges_stitched``  = edges_before − edges_after.
    ``faces_orientation_fixed`` is not directly observable from topology counts
    alone; we leave it as 0 (conservative — a deeper diff would need face
    orientation comparison, out of scope for the lightweight pass).
    """
    v_before = len(body_before.all_vertices())
    v_after = len(body_after.all_vertices())
    e_before = len(body_before.all_edges())
    e_after = len(body_after.all_edges())
    return HealStats(
        vertices_merged=max(0, v_before - v_after),
        edges_stitched=max(0, e_before - e_after),
        faces_orientation_fixed=0,
    )


def read_step(
    source: Union[str, Path],
    *,
    validate: bool = True,
    auto_heal: bool = False,
    heal_options: Optional[Dict[str, Any]] = None,
) -> Union[Body, StepReadResult]:
    """Parse a STEP Part 21 file and return a Kerf :class:`Body` or
    :class:`StepReadResult`.

    Parameters
    ----------
    source:
        A file path (``str`` or ``pathlib.Path``) or the raw STEP text.
        If *source* is a string that looks like a path (no newline and
        the path exists), it is read from disk.  Otherwise it is treated
        as inline STEP text.
    validate:
        If ``True`` (default) call :func:`validate_body` and raise
        :class:`StepReadError` if the result is invalid.
    auto_heal:
        If ``True``, run :func:`~kerf_cad_core.geom.body_heal.heal_body`
        on each imported body after parsing.  Returns a
        :class:`StepReadResult` (which is also iterable as the bodies list
        for backward compatibility).  If a heal pass raises an exception
        for a particular body, the un-healed body is returned and the body
        index is appended to :attr:`StepReadResult.heal_warnings`.
        Default: ``False``.
    heal_options:
        Optional dict of keyword arguments forwarded to
        :func:`~kerf_cad_core.geom.body_heal.heal_body`.  Currently
        supports ``tol`` (float, default ``1e-6``).  Ignored when
        ``auto_heal=False``.

    Returns
    -------
    Body
        When ``auto_heal=False`` (default): the first
        ``MANIFOLD_SOLID_BREP`` in the file assembled into a Kerf
        ``Body``.  If the file contains multiple solids they are all
        assembled into the same ``Body`` as separate ``Solid`` items.
    StepReadResult
        When ``auto_heal=True``: a dataclass with ``bodies``,
        ``heal_stats`` (per-body :class:`HealStats`), and
        ``heal_warnings``.  The object supports ``__iter__`` / ``__len__``
        / ``__getitem__`` so existing callers that unpack or iterate the
        return value continue to work.

    Raises
    ------
    StepReadError
        On parse failure, missing required entities, or (when
        *validate* is True) topology validation failure.
    FileNotFoundError
        When *source* is a path that does not exist.
    """
    # Resolve text
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8", errors="replace")
    elif isinstance(source, str) and "\n" not in source and Path(source).exists():
        text = Path(source).read_text(encoding="utf-8", errors="replace")
    else:
        text = str(source)

    parser = _StepParser(text)

    body_refs = parser.find_bodies()
    if not body_refs:
        # Try to find shells directly (some files have CLOSED_SHELL at top)
        shell_refs = [
            rid for rid, (tn, _) in parser._raw.items()
            if tn in ("CLOSED_SHELL", "OPEN_SHELL")
        ]
        if not shell_refs:
            raise StepReadError(
                "No MANIFOLD_SOLID_BREP or CLOSED_SHELL entity found in STEP file"
            )
        solids = []
        for sref in shell_refs:
            sd = parser.get(sref)
            if sd is None:
                continue
            shell = _build_shell(sd, parser)
            solids.append(Solid([shell]))
        body = Body(solids=solids)
        raw_bodies: List[Body] = [body]
    else:
        # Build one Body per MANIFOLD_SOLID_BREP (multi-body aware)
        raw_bodies = []
        for bref in body_refs:
            msb = parser.get(bref)
            if msb is None or not isinstance(msb, dict):
                continue
            outer_shell_dict = msb.get("outer_shell")
            if outer_shell_dict is None or not isinstance(outer_shell_dict, dict):
                continue
            shell = _build_shell(outer_shell_dict, parser)
            raw_bodies.append(Body(solids=[Solid([shell])]))

        if not raw_bodies:
            raise StepReadError("STEP file parsed but produced no bodies")

        # Legacy path: collapse into a single Body (all solids merged)
        # Kept for full backward compatibility when auto_heal=False.
        body = Body(solids=[s for b in raw_bodies for s in b.solids])

    if not body.all_faces():
        raise StepReadError("STEP file parsed but produced zero faces")

    if validate:
        result = validate_body(body)
        if not result["ok"]:
            errs = "\n  ".join(result["errors"])
            raise StepReadError(
                f"B-rep validation failed after STEP read:\n  {errs}"
            )

    # ------------------------------------------------------------------
    # auto_heal=False → legacy single-Body return (unchanged behaviour)
    # ------------------------------------------------------------------
    if not auto_heal:
        return body

    # ------------------------------------------------------------------
    # auto_heal=True → heal each body, collect stats, return StepReadResult
    # ------------------------------------------------------------------
    from kerf_cad_core.geom.body_heal import heal_body  # deferred import

    opts = heal_options or {}
    tol = float(opts.get("tol", 1e-6))

    healed_bodies: List[Body] = []
    heal_stats: Dict[int, HealStats] = {}
    heal_warnings: List[int] = []

    for idx, raw_body in enumerate(raw_bodies):
        try:
            healed = heal_body(raw_body, tol=tol)
            stats = _compute_heal_stats(raw_body, healed)
            healed_bodies.append(healed)
            heal_stats[idx] = stats
            logger.debug(
                "step_read auto_heal body[%d]: merged=%d stitched=%d",
                idx, stats.vertices_merged, stats.edges_stitched,
            )
        except Exception as exc:
            logger.warning(
                "step_read auto_heal body[%d] failed (returning un-healed): %s",
                idx, exc,
            )
            healed_bodies.append(raw_body)
            heal_stats[idx] = HealStats()
            heal_warnings.append(idx)

    return StepReadResult(
        bodies=healed_bodies,
        heal_stats=heal_stats,
        heal_warnings=heal_warnings,
    )


def body_volume(body: Body) -> float:
    """Compute the volume of a :class:`Body` using the divergence theorem.

    This is the same helper used internally; exposed for test convenience.
    """
    return _body_volume(body)
