"""GK-P — Face color assignment by feature kind / curvature / orientation.

Per-face semantic color assignment for downstream rendering, STEP export, and
OBJ export.  Integrates with Wave 4CC ``feature_recognition`` and Wave 4Q
``surface_analysis`` without importing OCCT.

Public API
----------
assign_face_colors(body, scheme, palette) -> dict[int, tuple[int,int,int]]
    Assign RGB colors to each face of *body*.

palette_dict(palette) -> dict[str, tuple[int,int,int]]
    Return the named color palette as a feature-kind → RGB dict.

export_colors_to_step(body, face_colors, path)
    Write a STEP AP242 file with per-face color attributes (ISO 10303-242
    STYLED_ITEM / PRESENTATION_STYLE_ASSIGNMENT / COLOUR_RGB).

export_colors_to_obj(body, face_colors, path)
    Write an OBJ + MTL file pair with per-face material/color assignments.

References
----------
ISO 10303-242 Managed model-based 3D engineering (AP242 ed.2, §8.4 visual
appearance).  AP242 adds COLOUR_RGB + STYLED_ITEM / PRESENTATION_STYLE on top
of the AP214 B-rep entities already written by ``step_write.py``.

Standard CAD color conventions:
  Planar        — neutral gray
  Cylindrical   — blue (machined bore / revolved feature)
  Sphere        — green
  Fillet/blend  — red (edge treatment)
  Boss          — orange
  Rib           — purple
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Face,
    Plane,
    SphereSurface,
    TorusSurface,
)
from kerf_cad_core.geom.feature_recognition import (
    recognize_features,
    _is_cylinder_like,
    _is_plane,
    _is_sphere,
    _is_torus,
)

__all__ = [
    "assign_face_colors",
    "palette_dict",
    "export_colors_to_step",
    "export_colors_to_obj",
]

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

RGB = Tuple[int, int, int]
FaceColorMap = Dict[int, RGB]

# ---------------------------------------------------------------------------
# Built-in palettes
# ---------------------------------------------------------------------------

#: Default palette — feature-kind → (R, G, B) in 0-255 range.
_PALETTE_DEFAULT: Dict[str, RGB] = {
    "planar":      (192, 192, 192),   # neutral gray
    "cylindrical": (100, 150, 255),   # blue
    "sphere":      (150, 255, 150),   # green
    "fillet":      (255, 100, 100),   # red
    "boss":        (255, 200, 100),   # orange
    "rib":         (180, 100, 255),   # purple
    "torus":       (255, 180, 180),   # light pink (blend / groove)
    "chamfer":     (255, 230, 100),   # yellow
    "hole":        ( 80, 180, 220),   # cyan-blue (concave bore)
    "pocket":      (200, 230, 255),   # pale blue
    "unknown":     (128, 128, 128),   # fallback gray
}

#: Engineering palette — higher contrast, ISO-like.
_PALETTE_ENGINEERING: Dict[str, RGB] = {
    "planar":      (210, 210, 210),
    "cylindrical": (  0, 120, 215),
    "sphere":      (  0, 200,  80),
    "fillet":      (230,  60,  60),
    "boss":        (240, 140,   0),
    "rib":         (140,  60, 200),
    "torus":       (200, 100, 140),
    "chamfer":     (220, 200,   0),
    "hole":        ( 40, 160, 220),
    "pocket":      (160, 210, 240),
    "unknown":     (150, 150, 150),
}

#: Aesthetic palette — pastel, presentation-friendly.
_PALETTE_AESTHETIC: Dict[str, RGB] = {
    "planar":      (230, 230, 235),
    "cylindrical": (180, 210, 255),
    "sphere":      (180, 255, 200),
    "fillet":      (255, 190, 190),
    "boss":        (255, 230, 180),
    "rib":         (220, 190, 255),
    "torus":       (255, 215, 225),
    "chamfer":     (255, 245, 180),
    "hole":        (190, 225, 255),
    "pocket":      (220, 245, 255),
    "unknown":     (200, 200, 205),
}

_PALETTES = {
    "default":     _PALETTE_DEFAULT,
    "engineering": _PALETTE_ENGINEERING,
    "aesthetic":   _PALETTE_AESTHETIC,
}


# ---------------------------------------------------------------------------
# palette_dict
# ---------------------------------------------------------------------------


def palette_dict(palette: str = "default") -> Dict[str, RGB]:
    """Return the named feature-kind → RGB color palette.

    Parameters
    ----------
    palette : {'default', 'engineering', 'aesthetic'}

    Returns
    -------
    dict mapping feature kind string to (R, G, B) tuple (0-255 integers).
    """
    if palette not in _PALETTES:
        raise ValueError(
            f"Unknown palette {palette!r}. "
            f"Choose from: {sorted(_PALETTES)}"
        )
    return dict(_PALETTES[palette])


# ---------------------------------------------------------------------------
# Internal surface-kind helpers
# ---------------------------------------------------------------------------


def _face_surface_kind(face: Face) -> str:
    """Return a canonical surface-kind string for *face*.

    Returns one of: 'planar', 'cylindrical', 'sphere', 'torus', 'unknown'.
    Does NOT look at feature context (concavity etc.) — that is handled by
    the feature-recognition pass in ``assign_face_colors``.
    """
    s = face.surface
    if isinstance(s, Plane):
        return "planar"
    if isinstance(s, SphereSurface):
        return "sphere"
    if isinstance(s, TorusSurface):
        return "torus"
    if _is_cylinder_like(face):
        return "cylindrical"
    return "unknown"


def _face_normal_vec(face: Face) -> np.ndarray:
    """Return the outward unit surface normal at parameter (0.5, 0.5)."""
    try:
        n = np.asarray(face.surface_normal(0.5, 0.5), dtype=float)
        nrm = float(np.linalg.norm(n))
        if nrm > 1e-14:
            return n / nrm
    except Exception:
        pass
    return np.array([0.0, 0.0, 1.0])


# ---------------------------------------------------------------------------
# Scheme: feature
# ---------------------------------------------------------------------------


def _assign_feature_scheme(body: Body, pal: Dict[str, RGB]) -> FaceColorMap:
    """Assign colors based on feature-recognition classification.

    Feature-recognition priority rules:
    - hole, pocket, chamfer, boss → use the feature type directly.
    - fillet → use "fillet" ONLY when the surface is TorusSurface (true
      blend/fillet).  A CylinderSurface classified as "fillet" is simply
      a convex cylinder barrel (e.g. the side of a standalone cylinder
      body); in that case fall back to "cylindrical" for correct visual
      semantics per ISO 10303-242 standard viewer conventions.
    - Unclaimed faces → classify by surface type.

    This aligns with standard CAD viewer conventions where a cylindrical
    face is blue regardless of the topological concavity heuristic.
    """
    result = recognize_features(body)
    face_kind: Dict[int, str] = {}
    face_by_id = {f.id: f for f in body.all_faces()}

    for feat in result["features"]:
        ftype = feat["type"]
        kind: str
        if ftype == "hole":
            kind = "hole"
        elif ftype == "fillet":
            # A true fillet uses a TorusSurface (blend between two planes).
            # A CylinderSurface "fillet" is the barrel of a convex cylinder
            # (e.g. a standalone cylinder body) — color it as "cylindrical".
            for fid in feat["face_ids"]:
                f = face_by_id.get(fid)
                if f is not None and isinstance(f.surface, TorusSurface):
                    face_kind[fid] = "fillet"
                else:
                    face_kind[fid] = _face_surface_kind(f) if f else "fillet"
            continue  # already set per-face above
        elif ftype == "boss":
            kind = "boss"
        elif ftype == "pocket":
            kind = "pocket"
        elif ftype == "chamfer":
            kind = "chamfer"
        else:
            kind = "unknown"
        for fid in feat["face_ids"]:
            face_kind[fid] = kind

    # Faces not claimed by feature recognition → classify by surface type
    colors: FaceColorMap = {}
    for face in body.all_faces():
        fid = face.id
        if fid in face_kind:
            kind = face_kind[fid]
        else:
            kind = _face_surface_kind(face)
        colors[fid] = pal.get(kind, pal.get("unknown", (128, 128, 128)))

    return colors


# ---------------------------------------------------------------------------
# Scheme: curvature  (mean curvature → blue=concave, gray=flat, red=convex)
# ---------------------------------------------------------------------------


def _lerp_rgb(a: RGB, b: RGB, t: float) -> RGB:
    """Linear interpolate between two RGB tuples, t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


_COLOR_CONCAVE = (100, 150, 255)   # blue — concave (H < 0)
_COLOR_FLAT    = (192, 192, 192)   # gray — flat    (H ~ 0)
_COLOR_CONVEX  = (255, 100, 100)   # red  — convex  (H > 0)

_CURVATURE_SAMPLE_UV = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0),
                         (0.0, 0.5), (0.5, 0.0)]


def _mean_curvature_estimate(face: Face) -> float:
    """Estimate mean curvature H for analytic faces.

    Uses geometry-type analysis:
    - Plane          → H = 0
    - CylinderSurface → H = ±1 / (2r)  (positive if outward-pointing normal)
    - SphereSurface  → H = 1 / r  (always positive for outward normal)
    - TorusSurface   → H varies; sample the minor curvature 1/minor_r

    Returns the dominant mean curvature sign/magnitude.
    """
    s = face.surface
    if isinstance(s, Plane):
        return 0.0
    if isinstance(s, SphereSurface):
        r = float(s.radius)
        return 1.0 / r if r > 1e-14 else 0.0
    if isinstance(s, TorusSurface):
        r = float(s.minor_radius)
        return 1.0 / r if r > 1e-14 else 0.0
    if _is_cylinder_like(face):
        r = float(getattr(s, "radius", 1.0))
        # Convex outward cylinder has positive curvature; concave bore is negative.
        # Use the concavity test from feature_recognition.
        try:
            from kerf_cad_core.geom.feature_recognition import _cylinder_concavity
            concavity = _cylinder_concavity(face)  # >0 concave, <0 convex
            sign = -1.0 if concavity > 0.0 else 1.0
        except Exception:
            sign = 1.0
        return sign / (2.0 * r) if r > 1e-14 else 0.0
    return 0.0


def _assign_curvature_scheme(body: Body, pal: Dict[str, RGB]) -> FaceColorMap:  # noqa: ARG001
    """Assign colors based on mean curvature.

    blue=concave (H < 0), gray=flat (H ≈ 0), red=convex (H > 0).
    Curvature magnitudes are normalised to [0, 1] relative to the max absolute
    curvature seen in the body.
    """
    faces = list(body.all_faces())
    curvatures = {f.id: _mean_curvature_estimate(f) for f in faces}

    max_abs = max((abs(v) for v in curvatures.values()), default=1.0)
    if max_abs < 1e-14:
        max_abs = 1.0

    colors: FaceColorMap = {}
    for face in faces:
        h = curvatures[face.id]
        t = h / max_abs  # in [-1, 1]
        if t < 0.0:
            # concave: gray → blue
            rgb = _lerp_rgb(_COLOR_FLAT, _COLOR_CONCAVE, -t)
        elif t > 0.0:
            # convex: gray → red
            rgb = _lerp_rgb(_COLOR_FLAT, _COLOR_CONVEX, t)
        else:
            rgb = _COLOR_FLAT
        colors[face.id] = rgb

    return colors


# ---------------------------------------------------------------------------
# Scheme: orientation  (face normal direction → up/down/sides)
# ---------------------------------------------------------------------------

_COLOR_UP    = (180, 255, 180)   # green  — faces up   (+Z dominant)
_COLOR_DOWN  = (255, 200, 180)   # orange — faces down (-Z dominant)
_COLOR_SIDE  = (180, 210, 255)   # blue   — side faces

_Z_AXIS = np.array([0.0, 0.0, 1.0])


def _assign_orientation_scheme(body: Body, pal: Dict[str, RGB]) -> FaceColorMap:  # noqa: ARG001
    """Assign colors based on outward normal direction (for 3D-print setup)."""
    colors: FaceColorMap = {}
    for face in body.all_faces():
        n = _face_normal_vec(face)
        dot_z = float(np.dot(n, _Z_AXIS))
        if dot_z > 0.5:
            colors[face.id] = _COLOR_UP
        elif dot_z < -0.5:
            colors[face.id] = _COLOR_DOWN
        else:
            colors[face.id] = _COLOR_SIDE
    return colors


# ---------------------------------------------------------------------------
# Scheme: material  (delegates to kerf-lca if available)
# ---------------------------------------------------------------------------


def _assign_material_scheme(body: Body, pal: Dict[str, RGB]) -> FaceColorMap:
    """Assign colors based on part material assignment from kerf-lca.

    Falls back to the feature scheme when kerf-lca is not available or the
    body has no material assigned.
    """
    material_color: Optional[RGB] = None
    try:
        from kerf_lca.material_db import get_material_color  # type: ignore[import]
        mat = getattr(body, "material", None)
        if mat is not None:
            material_color = get_material_color(mat)
    except (ImportError, AttributeError, Exception):
        pass

    if material_color is None:
        # Fall back to feature scheme
        return _assign_feature_scheme(body, pal)

    # Single solid-color for the whole body
    return {f.id: material_color for f in body.all_faces()}


# ---------------------------------------------------------------------------
# assign_face_colors (main entry point)
# ---------------------------------------------------------------------------


def assign_face_colors(
    body: Body,
    scheme: str = "feature",
    palette: str = "default",
) -> FaceColorMap:
    """Assign a semantic RGB color to every face of *body*.

    Parameters
    ----------
    body : Body
        A :class:`~kerf_cad_core.geom.brep.Body` from any kerf geometry kernel
        primitive.
    scheme : {'feature', 'curvature', 'orientation', 'material'}
        Color-assignment strategy:

        - ``'feature'``: color by manufacturing feature type detected via
          Wave 4CC ``feature_recognition`` (planar=gray, cylindrical=blue,
          sphere=green, fillet=red, boss=orange, rib=purple, hole=cyan-blue,
          pocket=pale-blue, chamfer=yellow).
        - ``'curvature'``: mean curvature gradient
          (blue=concave, gray=flat, red=convex).
        - ``'orientation'``: face normal direction
          (green=top/+Z, orange=bottom/-Z, blue=sides).
        - ``'material'``: part material assignment from kerf-lca (falls back to
          feature scheme when kerf-lca is unavailable).

    palette : {'default', 'engineering', 'aesthetic'}
        Named RGB palette to use for the ``'feature'`` scheme (ignored for
        curvature and orientation schemes which use their own fixed gradients).

    Returns
    -------
    dict mapping face_id (int) → (R, G, B) integer triple (0-255).
    All faces of *body* are present in the returned dict.

    Examples
    --------
    >>> from kerf_cad_core.geom.brep import make_box
    >>> from kerf_cad_core.geom.face_color import assign_face_colors
    >>> body = make_box(1, 1, 1)
    >>> colors = assign_face_colors(body, scheme='feature')
    >>> set(colors.values())  # all 6 box faces are planar → gray
    {(192, 192, 192)}
    """
    valid_schemes = ("feature", "curvature", "orientation", "material")
    if scheme not in valid_schemes:
        raise ValueError(
            f"Unknown scheme {scheme!r}. Choose from: {valid_schemes}"
        )

    pal = palette_dict(palette)

    if scheme == "feature":
        return _assign_feature_scheme(body, pal)
    if scheme == "curvature":
        return _assign_curvature_scheme(body, pal)
    if scheme == "orientation":
        return _assign_orientation_scheme(body, pal)
    # scheme == "material"
    return _assign_material_scheme(body, pal)


# ---------------------------------------------------------------------------
# STEP export with per-face color (ISO 10303-242 COLOUR_RGB)
# ---------------------------------------------------------------------------


def _fmt(v: float) -> str:
    """Format a float for Part 21 (always includes a decimal point)."""
    s = f"{v:.14g}"
    if "." not in s and "e" not in s and "E" not in s:
        s = s + "."
    return s


def export_colors_to_step(
    body: Body,
    face_colors: FaceColorMap,
    path: str,
) -> None:
    """Write a STEP AP242 file with per-face color attributes.

    The base B-rep is written first using the existing ``step_write.write_step``
    function.  Color information is appended as ISO 10303-242 styled-item
    entities (COLOUR_RGB, FILL_AREA_STYLE_COLOUR, FILL_AREA_STYLE,
    SURFACE_SIDE_STYLE, SURFACE_STYLE_USAGE, PRESENTATION_STYLE_ASSIGNMENT,
    STYLED_ITEM) that reference each ADVANCED_FACE entity in the file.

    Parameters
    ----------
    body : Body
    face_colors : dict[face_id → (R, G, B)]
        Mapping returned by :func:`assign_face_colors`.
    path : str
        Output file path (overwrites existing file).

    Notes
    -----
    The STEP file schema is upgraded to AP242 (replacing AP214) so that
    compliant readers (Siemens NX, CATIA V5/V6, FreeCAD) interpret the
    color entities correctly.

    ``step_write.write_step`` sorts faces by shell and then by Python
    ``id()`` of the Face object.  ``export_colors_to_step`` replicates
    the same sort order to correlate face_ids with STEP entity IDs.

    References
    ----------
    ISO 10303-242 §8.4 "Representation of appearance information".
    STEP AP242 edition 2 (2020) — styled_item, colour_rgb,
    fill_area_style_colour, surface_side_style.
    """
    import re as _re
    from kerf_cad_core.geom.io.step_write import write_step

    # Generate base STEP text
    base_text = write_step(body)

    # Replicate step_write's face ordering: sorted by id() per shell
    # (see _collect in step_write.py: sorted_faces = sorted(shell.faces, key=id))
    ordered_faces = []
    for shell in sorted(body.all_shells(), key=id):
        for face in sorted(shell.faces, key=id):
            ordered_faces.append(face)

    # Parse ADVANCED_FACE entity IDs in document order (ascending eid)
    af_eids = [
        int(m.group(1))
        for m in _re.finditer(r"#(\d+)=ADVANCED_FACE\(", base_text)
    ]
    # af_eids should have same count as ordered_faces; build face_id → step eid
    face_eid_map: Dict[int, int] = {}
    for face, step_eid in zip(ordered_faces, af_eids):
        face_eid_map[face.id] = step_eid

    # Upgrade schema line from AP214 to AP242
    text = base_text.replace(
        "'AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'",
        "'MANAGED_MODEL_BASED_3D_ENGINEERING { 1 0 10303 242 1 1 4 }'"
    )

    # Find the last entity ID used
    eids = [int(m.group(1)) for m in _re.finditer(r"#(\d+)=", text)]
    next_id = max(eids, default=0) + 1

    color_lines: list[str] = []

    for face in body.all_faces():
        fid = face.id
        step_eid = face_eid_map.get(fid)
        if step_eid is None:
            continue
        rgb = face_colors.get(fid, (128, 128, 128))
        r_f, g_f, b_f = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0

        # COLOUR_RGB
        cid = next_id; next_id += 1
        color_lines.append(
            f"#{cid}=COLOUR_RGB('',{_fmt(r_f)},{_fmt(g_f)},{_fmt(b_f)});"
        )
        # FILL_AREA_STYLE_COLOUR
        fasc_id = next_id; next_id += 1
        color_lines.append(
            f"#{fasc_id}=FILL_AREA_STYLE_COLOUR('',#{cid});"
        )
        # FILL_AREA_STYLE
        fas_id = next_id; next_id += 1
        color_lines.append(
            f"#{fas_id}=FILL_AREA_STYLE('face_color',(#{fasc_id}));"
        )
        # SURFACE_STYLE_FILL_AREA
        ssfa_id = next_id; next_id += 1
        color_lines.append(
            f"#{ssfa_id}=SURFACE_STYLE_FILL_AREA(#{fas_id});"
        )
        # SURFACE_SIDE_STYLE
        sss_id = next_id; next_id += 1
        color_lines.append(
            f"#{sss_id}=SURFACE_SIDE_STYLE('',(#{ssfa_id}));"
        )
        # SURFACE_STYLE_USAGE
        ssu_id = next_id; next_id += 1
        color_lines.append(
            f"#{ssu_id}=SURFACE_STYLE_USAGE(.BOTH.,#{sss_id});"
        )
        # PRESENTATION_STYLE_ASSIGNMENT
        psa_id = next_id; next_id += 1
        color_lines.append(
            f"#{psa_id}=PRESENTATION_STYLE_ASSIGNMENT((#{ssu_id}));"
        )
        # STYLED_ITEM referencing ADVANCED_FACE
        si_id = next_id; next_id += 1
        color_lines.append(
            f"#{si_id}=STYLED_ITEM('color',(#{psa_id}),#{step_eid});"
        )

    # Splice color entities before ENDSEC (which ends the DATA section)
    # The file ends with: ... ENDSEC;\nEND-ISO-10303-21;\n
    if color_lines:
        insertion = "\n".join(color_lines) + "\n"
        # Replace the last ENDSEC; occurrence (end of DATA section)
        text = text[:text.rfind("ENDSEC;")] + insertion + "ENDSEC;\nEND-ISO-10303-21;\n"

    Path(path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# OBJ + MTL export with per-face colors
# ---------------------------------------------------------------------------


def export_colors_to_obj(
    body: Body,
    face_colors: FaceColorMap,
    path: str,
) -> None:
    """Write an OBJ + MTL file pair with per-face material/color assignments.

    Each unique (R, G, B) color in *face_colors* becomes one named material
    in the companion ``.mtl`` file.  Faces are triangulated by uniform
    parameter sampling across each face's surface bounding box.

    Parameters
    ----------
    body : Body
    face_colors : dict[face_id → (R, G, B)]
    path : str
        Path to the ``.obj`` file.  The companion ``.mtl`` file is written to
        the same directory with the same stem and ``.mtl`` extension.

    Notes
    -----
    The triangulation is a simple UV-grid tessellation — not watertight for
    trimmed NURBS faces.  For precision geometry prefer STEP export.
    """
    obj_path = Path(path)
    mtl_path = obj_path.with_suffix(".mtl")
    mtl_filename = mtl_path.name

    # Build unique material entries
    unique_colors: Dict[RGB, str] = {}  # rgb → material name
    for fid, rgb in face_colors.items():
        if rgb not in unique_colors:
            name = f"mat_{rgb[0]}_{rgb[1]}_{rgb[2]}"
            unique_colors[rgb] = name

    # ------------------------------------------------------------------
    # Write MTL
    # ------------------------------------------------------------------
    mtl_lines = ["# kerf face-color material library", ""]
    for rgb, name in unique_colors.items():
        r_f, g_f, b_f = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
        mtl_lines += [
            f"newmtl {name}",
            f"Ka {r_f:.6f} {g_f:.6f} {b_f:.6f}",
            f"Kd {r_f:.6f} {g_f:.6f} {b_f:.6f}",
            "Ks 0.100000 0.100000 0.100000",
            "Ns 96.078431",
            "d 1.0",
            "illum 2",
            "",
        ]
    mtl_path.write_text("\n".join(mtl_lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # Write OBJ
    # ------------------------------------------------------------------
    N_U, N_V = 4, 4  # grid resolution per face (keep small for hermetic tests)

    obj_lines = [
        "# kerf face-color OBJ export",
        f"mtllib {mtl_filename}",
        "",
    ]
    vert_offset = 0

    for face in body.all_faces():
        fid = face.id
        rgb = face_colors.get(fid, (128, 128, 128))
        mat_name = unique_colors.get(rgb, "mat_128_128_128")

        # Sample the surface in a regular UV grid
        # Surface domain:  use (0..1) × (0..1) or the actual parameter range
        u_vals = np.linspace(0.0, 1.0, N_U)
        v_vals = np.linspace(0.0, 1.0, N_V)

        pts: list[Tuple[float, float, float]] = []
        for u in u_vals:
            for v in v_vals:
                try:
                    p = face.surface.evaluate(u, v)
                    pts.append((float(p[0]), float(p[1]), float(p[2])))
                except Exception:
                    pts.append((0.0, 0.0, 0.0))

        obj_lines.append(f"g face_{fid}")
        obj_lines.append(f"usemtl {mat_name}")

        for x, y, z in pts:
            obj_lines.append(f"v {x:.8f} {y:.8f} {z:.8f}")

        # Build quad faces over the UV grid (1-based vertex indices)
        base = vert_offset + 1
        for i in range(N_U - 1):
            for j in range(N_V - 1):
                # 0-based local indices
                a = i * N_V + j
                b = i * N_V + j + 1
                c = (i + 1) * N_V + j + 1
                d = (i + 1) * N_V + j
                # OBJ 1-based: shift by vert_offset
                obj_lines.append(
                    f"f {base+a} {base+b} {base+c} {base+d}"
                )

        vert_offset += N_U * N_V
        obj_lines.append("")

    obj_path.write_text("\n".join(obj_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM tool registration
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
    # brep_assign_face_colors
    # ------------------------------------------------------------------

    _assign_spec = ToolSpec(
        name="brep_assign_face_colors",
        description=(
            "Assign semantic RGB colors to every face of a B-rep body. "
            "Supports four schemes:\n"
            "  'feature'     — color by manufacturing feature kind (planar=gray, "
            "cylindrical=blue, sphere=green, fillet=red, boss=orange, hole=cyan-blue).\n"
            "  'curvature'   — mean curvature gradient (blue=concave, gray=flat, red=convex).\n"
            "  'orientation' — face normal direction (green=+Z top, orange=-Z bottom, blue=sides).\n"
            "  'material'    — part material assignment (falls back to feature scheme).\n\n"
            "Palettes for the feature scheme: 'default', 'engineering', 'aesthetic'.\n\n"
            "Returns: {ok, colors: {face_id: [R,G,B]}, num_faces, scheme, palette}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_id": {
                    "type": "string",
                    "description": "Opaque body reference (project body key).",
                },
                "scheme": {
                    "type": "string",
                    "enum": ["feature", "curvature", "orientation", "material"],
                    "description": "Color assignment strategy. Default: 'feature'.",
                },
                "palette": {
                    "type": "string",
                    "enum": ["default", "engineering", "aesthetic"],
                    "description": "Named RGB palette for feature scheme. Default: 'default'.",
                },
                "primitive": {
                    "type": "string",
                    "enum": ["box", "cylinder", "sphere"],
                    "description": "Optional: create a test primitive body inline.",
                },
                "size": {
                    "type": "number",
                    "description": "Size parameter for inline test primitive (default 10).",
                },
            },
            "required": [],
        },
    )

    @register(_assign_spec)
    async def run_brep_assign_face_colors(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        scheme = str(a.get("scheme", "feature"))
        palette = str(a.get("palette", "default"))

        # Build or retrieve body
        body = None
        primitive = a.get("primitive")
        if primitive:
            try:
                size = float(a.get("size", 10.0))
                from kerf_cad_core.geom.brep import make_box, make_cylinder, make_sphere
                if primitive == "box":
                    body = make_box(size, size, size)
                elif primitive == "cylinder":
                    body = make_cylinder(radius=size / 2, height=size)
                elif primitive == "sphere":
                    body = make_sphere(radius=size / 2)
                else:
                    return err_payload(f"unknown primitive {primitive!r}", "BAD_ARGS")
            except Exception as exc:
                return err_payload(f"failed to create primitive: {exc}", "OP_FAILED")
        else:
            body_id = a.get("body_id")
            if not body_id:
                return err_payload(
                    "Either 'primitive' or 'body_id' must be provided", "BAD_ARGS"
                )
            try:
                body = ctx.get_body(body_id)  # type: ignore[attr-defined]
            except Exception as exc:
                return err_payload(f"body not found: {exc}", "BAD_ARGS")

        try:
            colors = assign_face_colors(body, scheme=scheme, palette=palette)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"color assignment failed: {exc}", "OP_FAILED")

        # Serialise: face_id → [R, G, B]
        color_payload = {str(fid): list(rgb) for fid, rgb in colors.items()}
        return ok_payload({
            "colors": color_payload,
            "num_faces": len(colors),
            "scheme": scheme,
            "palette": palette,
        })

    # ------------------------------------------------------------------
    # brep_export_step_with_colors
    # ------------------------------------------------------------------

    _step_color_spec = ToolSpec(
        name="brep_export_step_with_colors",
        description=(
            "Export a B-rep body to a STEP AP242 file with per-face color attributes "
            "(ISO 10303-242 COLOUR_RGB / STYLED_ITEM entities). Colors are assigned "
            "automatically using the specified scheme or may be supplied directly.\n\n"
            "Returns: {ok, path, num_faces_colored, scheme, palette}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body_id": {
                    "type": "string",
                    "description": "Opaque body reference (project body key).",
                },
                "path": {
                    "type": "string",
                    "description": "Output STEP file path.",
                },
                "scheme": {
                    "type": "string",
                    "enum": ["feature", "curvature", "orientation", "material"],
                    "description": "Color scheme. Default: 'feature'.",
                },
                "palette": {
                    "type": "string",
                    "enum": ["default", "engineering", "aesthetic"],
                    "description": "Palette for feature scheme. Default: 'default'.",
                },
                "primitive": {
                    "type": "string",
                    "enum": ["box", "cylinder", "sphere"],
                    "description": "Optional: create a test primitive body inline.",
                },
                "size": {
                    "type": "number",
                    "description": "Size parameter for inline test primitive (default 10).",
                },
            },
            "required": ["path"],
        },
    )

    @register(_step_color_spec)
    async def run_brep_export_step_with_colors(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        out_path = a.get("path")
        if not out_path:
            return err_payload("'path' is required", "BAD_ARGS")

        scheme = str(a.get("scheme", "feature"))
        palette = str(a.get("palette", "default"))

        # Build or retrieve body
        body = None
        primitive = a.get("primitive")
        if primitive:
            try:
                size = float(a.get("size", 10.0))
                from kerf_cad_core.geom.brep import make_box, make_cylinder, make_sphere
                if primitive == "box":
                    body = make_box(size, size, size)
                elif primitive == "cylinder":
                    body = make_cylinder(radius=size / 2, height=size)
                elif primitive == "sphere":
                    body = make_sphere(radius=size / 2)
                else:
                    return err_payload(f"unknown primitive {primitive!r}", "BAD_ARGS")
            except Exception as exc:
                return err_payload(f"failed to create primitive: {exc}", "OP_FAILED")
        else:
            body_id = a.get("body_id")
            if not body_id:
                return err_payload(
                    "Either 'primitive' or 'body_id' must be provided", "BAD_ARGS"
                )
            try:
                body = ctx.get_body(body_id)  # type: ignore[attr-defined]
            except Exception as exc:
                return err_payload(f"body not found: {exc}", "BAD_ARGS")

        try:
            colors = assign_face_colors(body, scheme=scheme, palette=palette)
            export_colors_to_step(body, colors, str(out_path))
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"STEP export failed: {exc}", "OP_FAILED")

        return ok_payload({
            "path": str(out_path),
            "num_faces_colored": len(colors),
            "scheme": scheme,
            "palette": palette,
        })
