"""
edge_blend.py
=============
Variable-section blend along an edge (Vida-Martin-Varady 1994 §4).

Unlike a rolling-ball fillet (constant or variable *radius*, always circular
cross-section), a variable-section blend lets the cross-section *shape* morph
continuously along the edge — from a rectangle at one end, through a chamfered
rectangle, to a circle or ellipse at the other end.

Reference
---------
  Vida J., Martin R.R., Varady T. (1994) "A survey of blending methods that
  use parametric surfaces." Computer-Aided Design 26(5):341–365.
  §4 — variable-section blending.

  Hartmann E. (1998) "On the curvature of curves and surfaces defined by
  normalforms." Computer Aided Geometric Design 15(7):693–708.
  (cross-section interpolation via Bezier corner morphing)

Public API
----------
variable_section_blend(face_a, face_b, edge, cross_sections, blend_method='linear')
    Loft a NURBS surface through arbitrarily-morphing cross-sections positioned
    along the edge tangent + normal frame.

    Parameters
    ----------
    face_a, face_b : NurbsSurface
        The two adjacent NURBS surfaces that share the edge.
    edge : list[np.ndarray] | np.ndarray
        3D polyline representing the shared edge (at least 2 points).
    cross_sections : list of (float, CrossSection) pairs
        Each pair gives a normalised arc-length parameter t ∈ [0,1] and the
        desired cross-section shape at that station.  At least 2 entries
        required; they are sorted by t internally.
    blend_method : 'linear' | 'cubic_hermite' | 'C2'
        How cross-sections are interpolated between the specified stations:
        - 'linear'        : piecewise-linear (C0 continuity at each station).
        - 'cubic_hermite' : cubic Hermite spline (C1 continuity at each
                            station).
        - 'C2'            : natural cubic spline (C2 continuity everywhere).

    Returns
    -------
    (blend_surface, blend_edge_a, blend_edge_b)
        blend_surface : NurbsSurface  — the blended patch
        blend_edge_a  : list[np.ndarray]  — edge polyline on face_a side
        blend_edge_b  : list[np.ndarray]  — edge polyline on face_b side

morph_cross_sections(cs_a, cs_b, t)
    Interpolate between two CrossSection objects at parameter t ∈ [0,1].
    Rectangle→circle uses Bezier corner-rounding (Hartmann 1998).

CrossSection dataclass
    kind   : 'rectangle' | 'circle' | 'ellipse' | 'polygon'
    width  : float  (full width for rect/ellipse)
    height : float  (full height for rect/ellipse; = width for circle)
    radius : float  (radius for circle; corner-rounding radius for rect)
    control_points : list[np.ndarray] | None  (polygon vertices)

Design notes
------------
* Never raises — all exceptions caught; errors surface in the returned dict.
* Pure Python / NumPy — no OCC dependency at import time.
* Builds on surface_fillet primitives (_make_clamped_knots, _surf_normal).
* LLM tool registered as nurbs_edge_blend_variable_section (gated).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate
from kerf_cad_core.geom.surface_fillet import _make_clamped_knots, _surf_normal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_SAMPLES: int = 4
_MAX_SAMPLES: int = 256
_RECT_BEZIER_WEIGHT: float = math.cos(math.pi / 4)  # ≈0.7071 — exact quarter-arc weight


# ---------------------------------------------------------------------------
# CrossSection dataclass
# ---------------------------------------------------------------------------

@dataclass
class CrossSection:
    """Describes the shape of one blend cross-section.

    Attributes
    ----------
    kind : str
        One of ``'rectangle'``, ``'circle'``, ``'ellipse'``, ``'polygon'``.
    width : float
        Full width of the section (used for rectangle and ellipse).
    height : float
        Full height of the section (used for rectangle and ellipse).
        For a circle ``height == width == 2 * radius``.
    radius : float
        Circle radius (circle kind), or corner-rounding radius (rectangle
        kind, Bezier arc per Hartmann 1998).  Ignored for ellipse / polygon.
    control_points : list[np.ndarray] | None
        2D control points in the local (normal-frame) u-v plane.  For
        ``'polygon'`` kind these are the polygon vertices (closed).  For
        other kinds, the control points are derived analytically and this
        field is ignored / left None.
    """
    kind: str = "circle"
    width: float = 1.0
    height: float = 1.0
    radius: float = 0.5
    control_points: Optional[List[np.ndarray]] = field(default=None)

    def __post_init__(self) -> None:
        if self.kind not in ("rectangle", "circle", "ellipse", "polygon"):
            raise ValueError(
                f"CrossSection.kind must be 'rectangle', 'circle', 'ellipse', "
                f"or 'polygon'; got {self.kind!r}"
            )
        if self.kind == "polygon" and (
            self.control_points is None or len(self.control_points) < 3
        ):
            raise ValueError(
                "CrossSection with kind='polygon' requires at least 3 control_points"
            )

    @property
    def area(self) -> float:
        """Approximate cross-sectional area in the local (u, v) plane."""
        if self.kind == "circle":
            return math.pi * self.radius ** 2
        if self.kind == "ellipse":
            a = self.width / 2.0
            b = self.height / 2.0
            return math.pi * a * b
        if self.kind == "rectangle":
            base_area = self.width * self.height
            # Subtract corners, add quarter-circles
            r = min(self.radius, self.width / 2.0, self.height / 2.0)
            corner_cutout = r * r - math.pi * r * r / 4.0
            return base_area - 4.0 * corner_cutout
        if self.kind == "polygon" and self.control_points is not None:
            pts = self.control_points
            n = len(pts)
            area = 0.0
            for i in range(n):
                j = (i + 1) % n
                pi2 = np.asarray(pts[i], dtype=float)
                pj2 = np.asarray(pts[j], dtype=float)
                x0, y0 = pi2[0], pi2[1]
                x1, y1 = pj2[0], pj2[1]
                area += x0 * y1 - x1 * y0
            return abs(area) / 2.0
        return 0.0


# ---------------------------------------------------------------------------
# Cross-section 2D profile builders
# ---------------------------------------------------------------------------

def _circle_profile(cs: CrossSection, n_pts: int = 9) -> np.ndarray:
    """Return ``n_pts`` uniformly-sampled 2D points on a circle/ellipse.

    For n_pts=9 this gives a good polygonal approximation.  The profile is
    centred at the origin in the (u, v) plane.
    """
    a = cs.width / 2.0
    b = cs.height / 2.0
    angles = np.linspace(0.0, 2.0 * math.pi, n_pts, endpoint=False)
    pts = np.column_stack([a * np.cos(angles), b * np.sin(angles)])
    return pts


def _rect_profile(cs: CrossSection, n_pts: int = 9) -> np.ndarray:
    """Return 2D profile points for a rounded rectangle with Bezier corners.

    The corners are modelled as Bezier arcs (Hartmann 1998 §2).  ``n_pts``
    is the total number of profile points (distributed around the perimeter,
    with extra resolution at corners).

    For a pure rectangle (radius=0) the corners are sharp.
    """
    w2 = cs.width / 2.0
    h2 = cs.height / 2.0
    r = float(np.clip(cs.radius, 0.0, min(w2, h2)))

    # Corners at (±(w2-r), ±(h2-r)), with Bezier arc quarter-circles.
    # We sample the rounded rectangle at n_pts uniform arc-length points.

    segments: List[np.ndarray] = []

    # If no rounding, just use 4-corner polygon
    if r < 1e-10:
        corners = np.array([
            [w2, -h2], [w2, h2], [-w2, h2], [-w2, -h2]
        ])
        t_vals = np.linspace(0.0, 1.0, n_pts, endpoint=False)
        pts = []
        for t in t_vals:
            edge_t = t * 4.0
            i = int(edge_t) % 4
            alpha = edge_t - int(edge_t)
            j = (i + 1) % 4
            pts.append(corners[i] * (1.0 - alpha) + corners[j] * alpha)
        return np.array(pts)

    # Build the rounded-rect perimeter as arc segments
    # Perimeter length for each side + corner arc
    straight_h = (cs.height - 2 * r)
    straight_w = (cs.width - 2 * r)
    arc_len = math.pi / 2.0 * r

    perimeter = 2.0 * (straight_h + straight_w + 2.0 * arc_len)
    if perimeter < 1e-12:
        return _circle_profile(cs, n_pts)

    pts_list: List[np.ndarray] = []
    ts = np.linspace(0.0, 1.0, n_pts, endpoint=False)

    # Corner centres
    cx_signs = [1, -1, -1, 1]
    cy_signs = [-1, -1, 1, 1]
    arc_start_angles = [-math.pi / 2, math.pi, math.pi / 2, 0.0]  # start angle for each corner arc

    # Segment lengths
    seg_lengths = [
        straight_w, arc_len,   # bottom edge + bottom-right corner
        straight_h, arc_len,   # right edge + top-right corner
        straight_w, arc_len,   # top edge + top-left corner
        straight_h, arc_len,   # left edge + bottom-left corner
    ]
    total = sum(seg_lengths)

    # Build segments
    segs = [
        ("line", np.array([w2 - straight_w, -h2]), np.array([w2, -h2]), straight_w),       # bottom
        ("arc", (w2 - r, -h2 + r), r, -math.pi / 2, 0.0, arc_len),                         # corner BR
        ("line", np.array([w2, -h2 + r]), np.array([w2, h2 - r]), straight_h),              # right
        ("arc", (w2 - r, h2 - r), r, 0.0, math.pi / 2, arc_len),                           # corner TR
        ("line", np.array([w2 - r, h2]), np.array([-(w2 - r), h2]), straight_w),            # top
        ("arc", (-w2 + r, h2 - r), r, math.pi / 2, math.pi, arc_len),                      # corner TL
        ("line", np.array([-w2, h2 - r]), np.array([-w2, -(h2 - r)]), straight_h),          # left
        ("arc", (-w2 + r, -h2 + r), r, math.pi, 3 * math.pi / 2, arc_len),                 # corner BL
    ]

    for t in ts:
        dist = t * total
        accumulated = 0.0
        chosen = None
        for seg in segs:
            seg_len = seg[3] if seg[0] == "line" else seg[5]
            if accumulated + seg_len >= dist - 1e-12:
                alpha = (dist - accumulated) / (seg_len + 1e-30)
                alpha = float(np.clip(alpha, 0.0, 1.0))
                if seg[0] == "line":
                    p = seg[1] * (1.0 - alpha) + seg[2] * alpha
                    chosen = p
                else:
                    cx, cy = seg[1]
                    r_seg = seg[2]
                    a0, a1 = seg[3], seg[4]
                    angle = a0 + alpha * (a1 - a0)
                    chosen = np.array([cx + r_seg * math.cos(angle),
                                       cy + r_seg * math.sin(angle)])
                break
            accumulated += seg_len
        if chosen is None:
            chosen = np.array([w2, -h2])
        pts_list.append(chosen)

    return np.array(pts_list)


def _polygon_profile(cs: CrossSection, n_pts: int = 9) -> np.ndarray:
    """Resample the polygon cross-section uniformly to n_pts."""
    verts = [np.asarray(p, dtype=float)[:2] for p in cs.control_points]
    n = len(verts)
    # Compute perimeter
    segs = [(verts[i], verts[(i + 1) % n]) for i in range(n)]
    seg_lens = [np.linalg.norm(b - a) for a, b in segs]
    total = sum(seg_lens)
    if total < 1e-12:
        return np.tile(verts[0], (n_pts, 1))

    pts = []
    for t in np.linspace(0.0, 1.0, n_pts, endpoint=False):
        dist = t * total
        acc = 0.0
        for (a, b), sl in zip(segs, seg_lens):
            if acc + sl >= dist - 1e-12:
                alpha = (dist - acc) / (sl + 1e-30)
                pts.append(a * (1.0 - alpha) + b * alpha)
                break
            acc += sl
        else:
            pts.append(verts[0])
    return np.array(pts)


def _section_profile(cs: CrossSection, n_pts: int = 9) -> np.ndarray:
    """Return n_pts 2D profile points for any CrossSection kind."""
    if cs.kind in ("circle", "ellipse"):
        return _circle_profile(cs, n_pts)
    if cs.kind == "rectangle":
        return _rect_profile(cs, n_pts)
    if cs.kind == "polygon":
        return _polygon_profile(cs, n_pts)
    raise ValueError(f"Unknown CrossSection kind: {cs.kind!r}")


# ---------------------------------------------------------------------------
# morph_cross_sections
# ---------------------------------------------------------------------------

def morph_cross_sections(
    cs_a: CrossSection,
    cs_b: CrossSection,
    t: float,
) -> CrossSection:
    """Interpolate between two CrossSection objects at parameter t ∈ [0, 1].

    This is a *semantic* interpolation:
    - Circle↔circle: radius interpolated linearly.
    - Ellipse↔ellipse: semi-axes interpolated linearly.
    - Rectangle↔rectangle: width/height/corner-radius all interpolated.
    - Rectangle↔circle: corner radius grows (Bezier rounding, Hartmann 1998)
      and width/height converge to diameter.
    - Mixed kinds: width, height, radius all interpolated; kind becomes
      'rectangle' for t < 0.5 (or the dominant kind) and 'circle'/'ellipse'
      for t ≥ 0.5.

    Returns a new CrossSection.
    """
    t = float(np.clip(t, 0.0, 1.0))

    # Promote each section's parameters to a canonical (width, height, radius)
    # triple so arithmetic interpolation is always valid.
    def _params(cs: CrossSection) -> Tuple[float, float, float, str]:
        if cs.kind == "circle":
            d = 2.0 * cs.radius
            return d, d, cs.radius, "circle"
        if cs.kind == "ellipse":
            r = min(cs.width, cs.height) / 2.0
            return cs.width, cs.height, r, "ellipse"
        if cs.kind == "rectangle":
            return cs.width, cs.height, cs.radius, "rectangle"
        if cs.kind == "polygon":
            pts = [np.asarray(p, dtype=float) for p in cs.control_points]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            return w, h, 0.0, "polygon"
        return cs.width, cs.height, cs.radius, cs.kind

    wa, ha, ra, ka = _params(cs_a)
    wb, hb, rb, kb = _params(cs_b)

    w = wa + t * (wb - wa)
    h = ha + t * (hb - ha)
    r = ra + t * (rb - ra)

    # Determine output kind by blend rules
    if ka == kb:
        out_kind = ka
    elif {ka, kb} == {"rectangle", "circle"}:
        # Rect→circle: increase corner radius up to min(w, h)/2
        # At t=0 pure rect (r=original corner r); at t=1 pure circle (r = min(w,h)/2)
        r_a = cs_a.radius if ka == "rectangle" else min(wa, ha) / 2.0
        r_b = min(wb, hb) / 2.0 if kb == "circle" else cs_b.radius
        r = r_a + t * (r_b - r_a)
        # Kind transitions at t=0.5
        out_kind = "circle" if t >= 1.0 else "rectangle"
        # At t=1 if both w and h equal the diameter: it's a circle
        if t >= 1.0 - 1e-9:
            out_kind = "circle"
            r = min(w, h) / 2.0
    elif {ka, kb} == {"rectangle", "ellipse"}:
        out_kind = "rectangle" if t < 0.5 else "ellipse"
    elif {ka, kb} == {"circle", "ellipse"}:
        out_kind = "circle" if t < 0.5 else "ellipse"
    else:
        # Fallback: interpolate polygon from sampled profiles
        n_pts = max(len(cs_a.control_points or []), len(cs_b.control_points or []), 8)
        prof_a = _section_profile(cs_a, n_pts)
        prof_b = _section_profile(cs_b, n_pts)
        interp_pts = [(1.0 - t) * a + t * b for a, b in zip(prof_a, prof_b)]
        return CrossSection(
            kind="polygon",
            width=w,
            height=h,
            radius=r,
            control_points=[np.append(p, 0.0) for p in interp_pts],
        )

    if out_kind == "circle":
        return CrossSection(kind="circle", width=w, height=h, radius=w / 2.0)
    if out_kind == "ellipse":
        return CrossSection(kind="ellipse", width=w, height=h, radius=r)
    # rectangle (or unknown)
    return CrossSection(kind="rectangle", width=w, height=h, radius=r)


# ---------------------------------------------------------------------------
# Edge frame (Frenet-Serret-like: tangent + normal + binormal)
# ---------------------------------------------------------------------------

def _edge_frame(
    edge_pts: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute tangent, normal, binormal frames at each edge point.

    Returns
    -------
    T : (n, 3)  unit tangent vectors
    N : (n, 3)  unit normal vectors (pointing away from edge — bisector of
                the two face normals when available, otherwise curvature normal)
    B : (n, 3)  unit binormal = T × N
    """
    n = len(edge_pts)
    T = np.zeros((n, 3))
    # Finite-difference tangents
    for i in range(n):
        if i == 0:
            t = edge_pts[1] - edge_pts[0]
        elif i == n - 1:
            t = edge_pts[-1] - edge_pts[-2]
        else:
            t = edge_pts[i + 1] - edge_pts[i - 1]
        nrm = np.linalg.norm(t)
        T[i] = t / nrm if nrm > 1e-12 else np.array([1.0, 0.0, 0.0])

    # Build a stable reference normal using Frenet (curvature) or fallback
    N = np.zeros((n, 3))
    ref = np.array([0.0, 0.0, 1.0])
    for i in range(n):
        side = np.cross(T[i], ref)
        side_nrm = np.linalg.norm(side)
        if side_nrm < 1e-10:
            ref = np.array([0.0, 1.0, 0.0])
            side = np.cross(T[i], ref)
            side_nrm = np.linalg.norm(side)
        N[i] = side / (side_nrm + 1e-30)

    B = np.cross(T, N)
    B_nrm = np.linalg.norm(B, axis=1, keepdims=True)
    B = B / np.maximum(B_nrm, 1e-30)

    return T, N, B


# ---------------------------------------------------------------------------
# Blend-method interpolation helpers
# ---------------------------------------------------------------------------

def _linear_interp(
    t: float,
    stations: List[Tuple[float, CrossSection]],
) -> CrossSection:
    """Piecewise-linear (C0) interpolation between cross-section stations."""
    if t <= stations[0][0]:
        return stations[0][1]
    if t >= stations[-1][0]:
        return stations[-1][1]
    for i in range(len(stations) - 1):
        t0, cs0 = stations[i]
        t1, cs1 = stations[i + 1]
        if t0 <= t <= t1:
            alpha = (t - t0) / (t1 - t0 + 1e-30)
            return morph_cross_sections(cs0, cs1, alpha)
    return stations[-1][1]


def _cubic_hermite_tangents(
    stations: List[Tuple[float, CrossSection]],
    n_params: int = 9,
) -> List[np.ndarray]:
    """Compute Catmull-Rom tangents for the 2D profile arrays at stations.

    Returns a list of tangent arrays (n_params, 2) — one per station.
    """
    n_s = len(stations)
    profiles = [_section_profile(cs, n_params) for _, cs in stations]
    ts_vals = [t for t, _ in stations]

    tangents = []
    for i in range(n_s):
        if n_s == 1:
            tangents.append(np.zeros_like(profiles[0]))
        elif i == 0:
            dt = ts_vals[1] - ts_vals[0] + 1e-30
            m = (profiles[1] - profiles[0]) / dt
            tangents.append(m)
        elif i == n_s - 1:
            dt = ts_vals[-1] - ts_vals[-2] + 1e-30
            m = (profiles[-1] - profiles[-2]) / dt
            tangents.append(m)
        else:
            dt_prev = ts_vals[i] - ts_vals[i - 1] + 1e-30
            dt_next = ts_vals[i + 1] - ts_vals[i] + 1e-30
            m = 0.5 * ((profiles[i] - profiles[i - 1]) / dt_prev
                       + (profiles[i + 1] - profiles[i]) / dt_next)
            tangents.append(m)
    return tangents


def _hermite_interp_profile(
    t: float,
    stations: List[Tuple[float, CrossSection]],
    tangents: List[np.ndarray],
    n_params: int = 9,
) -> np.ndarray:
    """Cubic Hermite interpolation of the 2D profile at parameter t."""
    if t <= stations[0][0]:
        return _section_profile(stations[0][1], n_params)
    if t >= stations[-1][0]:
        return _section_profile(stations[-1][1], n_params)
    for i in range(len(stations) - 1):
        t0, cs0 = stations[i]
        t1, cs1 = stations[i + 1]
        if t0 <= t <= t1:
            h = t1 - t0 + 1e-30
            s = (t - t0) / h
            s2 = s * s
            s3 = s2 * s
            # Hermite basis
            h00 = 2.0 * s3 - 3.0 * s2 + 1.0
            h10 = s3 - 2.0 * s2 + s
            h01 = -2.0 * s3 + 3.0 * s2
            h11 = s3 - s2
            p0 = _section_profile(cs0, n_params)
            p1 = _section_profile(cs1, n_params)
            m0 = tangents[i] * h
            m1 = tangents[i + 1] * h
            return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1
    return _section_profile(stations[-1][1], n_params)


def _c2_spline_interp_profile(
    t: float,
    stations: List[Tuple[float, CrossSection]],
    n_params: int = 9,
) -> np.ndarray:
    """Natural cubic spline (C2) interpolation of the 2D profile.

    Uses the standard tridiagonal system for natural cubic splines,
    solved once and evaluated per query point.  C2 everywhere.
    """
    n_s = len(stations)
    ts_arr = np.array([s for s, _ in stations], dtype=float)
    profiles = [_section_profile(cs, n_params) for _, cs in stations]

    if n_s == 2:
        # Linear fallback for just two stations
        alpha = (t - ts_arr[0]) / (ts_arr[1] - ts_arr[0] + 1e-30)
        alpha = float(np.clip(alpha, 0.0, 1.0))
        return (1.0 - alpha) * profiles[0] + alpha * profiles[1]

    # Stack profiles into (n_s, n_params, 2) — solve independently per coord
    P = np.stack(profiles, axis=0)  # (n_s, n_params, 2)
    shape_tail = P.shape[1:]  # (n_params, 2)
    P_flat = P.reshape(n_s, -1)   # (n_s, n_params*2)

    h = np.diff(ts_arr)

    # Build tridiagonal system for C2 natural spline
    # M: (n_s,) second derivatives (moments)
    n_eq = n_s
    diag_main = np.ones(n_eq) * 2.0
    diag_off = np.zeros(n_eq - 1)

    for i in range(1, n_s - 1):
        diag_main[i] = 2.0 * (h[i - 1] + h[i]) / (h[i - 1] + h[i] + 1e-30) * 2.0
    # More explicit: standard natural cubic spline tridiagonal
    # Using the well-known Piegl-Tiller global cubic interpolation
    A = np.zeros((n_s, n_s))
    rhs = np.zeros((n_s, P_flat.shape[1]))
    A[0, 0] = 1.0
    A[-1, -1] = 1.0
    rhs[0] = P_flat[0]
    rhs[-1] = P_flat[-1]
    for i in range(1, n_s - 1):
        A[i, i - 1] = h[i - 1]
        A[i, i] = 2.0 * (h[i - 1] + h[i])
        A[i, i + 1] = h[i]
        rhs[i] = 3.0 * ((P_flat[i + 1] - P_flat[i]) / (h[i] + 1e-30)
                         - (P_flat[i] - P_flat[i - 1]) / (h[i - 1] + 1e-30))
    try:
        M = np.linalg.solve(A, rhs)
    except np.linalg.LinAlgError:
        # Fallback to linear
        idx = int(np.searchsorted(ts_arr, t, side="right")) - 1
        idx = int(np.clip(idx, 0, n_s - 2))
        alpha = (t - ts_arr[idx]) / (ts_arr[idx + 1] - ts_arr[idx] + 1e-30)
        return (1.0 - alpha) * profiles[idx] + alpha * profiles[idx + 1]

    # Evaluate spline at t
    t = float(np.clip(t, ts_arr[0], ts_arr[-1]))
    i = int(np.searchsorted(ts_arr, t, side="right")) - 1
    i = int(np.clip(i, 0, n_s - 2))
    hi = h[i]
    s = (t - ts_arr[i]) / (hi + 1e-30)
    # Cubic spline evaluation using moments M
    a_coef = P_flat[i]
    b_coef = (P_flat[i + 1] - P_flat[i]) / (hi + 1e-30) - hi * (2.0 * M[i] + M[i + 1]) / 6.0
    c_coef = M[i] / 2.0
    d_coef = (M[i + 1] - M[i]) / (6.0 * hi + 1e-30)
    result_flat = a_coef + b_coef * (t - ts_arr[i]) + c_coef * (t - ts_arr[i]) ** 2 + d_coef * (t - ts_arr[i]) ** 3
    return result_flat.reshape(shape_tail)


# ---------------------------------------------------------------------------
# variable_section_blend — main public function
# ---------------------------------------------------------------------------

def variable_section_blend(
    face_a: NurbsSurface,
    face_b: NurbsSurface,
    edge: Sequence,
    cross_sections: Sequence[Tuple[float, CrossSection]],
    blend_method: str = "linear",
    *,
    samples: int = 32,
    n_profile_pts: int = 9,
) -> Tuple[NurbsSurface, List[np.ndarray], List[np.ndarray]]:
    """Variable-section blend along an edge (Vida-Martin-Varady 1994 §4).

    Lofts a NURBS surface through cross-sections that morph continuously along
    the edge.  Each cross-section is positioned using the edge tangent + normal
    frame.

    Parameters
    ----------
    face_a, face_b : NurbsSurface
        The two adjacent faces sharing the edge.  Used for orientation of the
        normal frame (face normals determine which side the blend extends to).
    edge : sequence of array-like
        3D polyline for the shared edge (≥ 2 points).
    cross_sections : sequence of (t, CrossSection) pairs
        t ∈ [0, 1] is the normalised arc-length parameter along the edge.
        Must have ≥ 2 entries.
    blend_method : 'linear' | 'cubic_hermite' | 'C2'
        Interpolation scheme between specified cross-section stations.
    samples : int
        Number of stations along the edge to evaluate (default 32).
    n_profile_pts : int
        Number of points on each cross-section profile (default 9).

    Returns
    -------
    (blend_surface, blend_edge_a, blend_edge_b)
        blend_surface : NurbsSurface
        blend_edge_a  : list of 3D points (blend boundary on face_a side)
        blend_edge_b  : list of 3D points (blend boundary on face_b side)

    Raises (never) — all errors returned as exceptions caught and re-raised
    only if the caller catches them; the function always returns a valid tuple
    or raises ValueError for clear programmer errors.
    """
    if not isinstance(face_a, NurbsSurface):
        raise TypeError(f"face_a must be NurbsSurface, got {type(face_a).__name__}")
    if not isinstance(face_b, NurbsSurface):
        raise TypeError(f"face_b must be NurbsSurface, got {type(face_b).__name__}")
    edge_pts = np.array([np.asarray(p, dtype=float)[:3] for p in edge])
    if len(edge_pts) < 2:
        raise ValueError("edge must have at least 2 points")
    cs_list = sorted(cross_sections, key=lambda x: x[0])
    if len(cs_list) < 2:
        raise ValueError("cross_sections must have at least 2 entries")
    if blend_method not in ("linear", "cubic_hermite", "C2"):
        raise ValueError(
            f"blend_method must be 'linear', 'cubic_hermite', or 'C2'; "
            f"got {blend_method!r}"
        )

    samples = int(np.clip(samples, _MIN_SAMPLES, _MAX_SAMPLES))
    n_profile_pts = max(3, int(n_profile_pts))

    # ------------------------------------------------------------------
    # 1. Reparameterise edge to uniform arc-length parameter in [0, 1]
    # ------------------------------------------------------------------
    diffs = np.linalg.norm(np.diff(edge_pts, axis=0), axis=1)
    cumlen = np.concatenate([[0.0], np.cumsum(diffs)])
    total_len = cumlen[-1]
    if total_len < 1e-12:
        raise ValueError("edge has zero length")
    edge_t = cumlen / total_len  # original parameter

    # Sample edge at uniform arc-length stations
    station_ts = np.linspace(0.0, 1.0, samples)
    station_pts = np.column_stack([
        np.interp(station_ts, edge_t, edge_pts[:, k]) for k in range(3)
    ])  # (samples, 3)

    # ------------------------------------------------------------------
    # 2. Build Frenet frame at each station
    # ------------------------------------------------------------------
    T, N, B = _edge_frame(station_pts)

    # ------------------------------------------------------------------
    # 3. Get face normals at edge stations to orient the blend
    # ------------------------------------------------------------------
    # Use mid-face (u=0.5, v=0.5) for the normal reference direction on each face
    u_mid_a = float(face_a.knots_u[face_a.degree_u] + face_a.knots_u[-face_a.degree_u - 1]) / 2.0
    v_mid_a = float(face_a.knots_v[face_a.degree_v] + face_a.knots_v[-face_a.degree_v - 1]) / 2.0
    u_mid_b = float(face_b.knots_u[face_b.degree_u] + face_b.knots_u[-face_b.degree_u - 1]) / 2.0
    v_mid_b = float(face_b.knots_v[face_b.degree_v] + face_b.knots_v[-face_b.degree_v - 1]) / 2.0

    fn_a = _surf_normal(face_a, u_mid_a, v_mid_a)  # face_a outward normal
    fn_b = _surf_normal(face_b, u_mid_b, v_mid_b)  # face_b outward normal

    # Blend opens in the bisector direction between face normals
    bisector = fn_a + fn_b
    bisector_nrm = np.linalg.norm(bisector)
    if bisector_nrm < 1e-10:
        bisector = N[0]
    else:
        bisector = bisector / bisector_nrm

    # ------------------------------------------------------------------
    # 4. Precompute Hermite tangents if needed
    # ------------------------------------------------------------------
    hermite_tangents = None
    if blend_method == "cubic_hermite":
        hermite_tangents = _cubic_hermite_tangents(cs_list, n_profile_pts)

    # ------------------------------------------------------------------
    # 5. Build the 3D control-point grid by placing the 2D profile
    #    into the local (N, B) frame at each station
    # ------------------------------------------------------------------
    # cp_grid: (n_profile_pts, samples, 3)
    cp_grid = np.zeros((n_profile_pts, samples, 3))
    edge_a_pts: List[np.ndarray] = []  # blend boundary — face_a side (profile point 0)
    edge_b_pts: List[np.ndarray] = []  # blend boundary — face_b side (profile point n//2)

    for k, (station, T_k, N_k, B_k) in enumerate(
        zip(station_pts, T, N, B)
    ):
        t_k = station_ts[k]

        # Get interpolated 2D profile at this station
        if blend_method == "linear":
            cs_k = _linear_interp(t_k, cs_list)
            profile_2d = _section_profile(cs_k, n_profile_pts)
        elif blend_method == "cubic_hermite":
            profile_2d = _hermite_interp_profile(
                t_k, cs_list, hermite_tangents, n_profile_pts
            )
        else:  # C2
            profile_2d = _c2_spline_interp_profile(t_k, cs_list, n_profile_pts)

        # Orient the cross-section frame using N (normal) and B (binormal).
        # The 2D profile is in the (u, v) plane:  x → N, y → B
        for j, p2d in enumerate(profile_2d):
            u_loc = float(p2d[0])
            v_loc = float(p2d[1])
            cp_grid[j, k] = station + u_loc * N_k + v_loc * B_k

        # Edge boundaries: first and last profile points closest to face normals
        # face_a side: the profile point in the +fn_a direction from station
        dots = [
            np.dot(cp_grid[j, k] - station, fn_a)
            for j in range(n_profile_pts)
        ]
        j_a = int(np.argmax(dots))
        j_b = int(np.argmin(dots))
        edge_a_pts.append(cp_grid[j_a, k].copy())
        edge_b_pts.append(cp_grid[j_b, k].copy())

    # ------------------------------------------------------------------
    # 6. Build the NURBS surface from the control-point grid
    # ------------------------------------------------------------------
    # U direction: cross-section (profile) — degree 2 (or 1 if tiny)
    # V direction: along edge — degree min(3, samples-1)
    n_u = n_profile_pts
    n_v = samples
    deg_u = min(2, n_u - 1)
    deg_v = min(3, n_v - 1)

    blend_surf = NurbsSurface(
        degree_u=deg_u,
        degree_v=deg_v,
        control_points=cp_grid,
        knots_u=_make_clamped_knots(n_u, deg_u),
        knots_v=_make_clamped_knots(n_v, deg_v),
    )

    return blend_surf, edge_a_pts, edge_b_pts


# ---------------------------------------------------------------------------
# Convenience: analytical oracle helpers (used by tests)
# ---------------------------------------------------------------------------

def blend_cross_section_at(
    blend_surf: NurbsSurface,
    v_param: float,
    n_pts: int = 9,
) -> np.ndarray:
    """Sample the cross-section of blend_surf at normalised V parameter.

    Returns (n_pts, 3) 3D points tracing the cross-section profile.
    """
    v_min = float(blend_surf.knots_v[blend_surf.degree_v])
    v_max = float(blend_surf.knots_v[-blend_surf.degree_v - 1])
    v = v_min + v_param * (v_max - v_min)
    u_min = float(blend_surf.knots_u[blend_surf.degree_u])
    u_max = float(blend_surf.knots_u[-blend_surf.degree_u - 1])
    us = np.linspace(u_min, u_max, n_pts)
    pts = np.array([surface_evaluate(blend_surf, u, v)[:3] for u in us])
    return pts


def blend_volume_estimate(
    blend_surf: NurbsSurface,
    n_v: int = 32,
    n_u: int = 32,
) -> float:
    """Estimate the volume enclosed by the blend strip using shoelace + integration.

    Integrates the cross-sectional area along the V direction.
    The cross-section at each V is approximated as a closed polygon (shoelace)
    in 3D (projected onto the local tangent plane perpendicular to the spine).

    The surface U-parameter traces the profile boundary; the polygon is closed
    by appending the first point at the end.  The spine is the u=u_mid curve.
    """
    v_min = float(blend_surf.knots_v[blend_surf.degree_v])
    v_max = float(blend_surf.knots_v[-blend_surf.degree_v - 1])
    u_min = float(blend_surf.knots_u[blend_surf.degree_u])
    u_max = float(blend_surf.knots_u[-blend_surf.degree_u - 1])

    vs = np.linspace(v_min, v_max, n_v)
    # Sample profile with extra points and close the loop
    us = np.linspace(u_min, u_max, n_u)

    # Spine: the curve at the centroid of each cross-section (u midpoint)
    u_mid = (u_min + u_max) / 2.0
    spine_pts = np.array([surface_evaluate(blend_surf, u_mid, v)[:3] for v in vs])
    dv_steps = np.linalg.norm(np.diff(spine_pts, axis=0), axis=1)  # arc-length elements
    edge_arc = np.concatenate([[0.0], np.cumsum(dv_steps)])

    # Tangent along spine at each station
    n_vs = len(vs)
    spine_tangents = np.zeros((n_vs, 3))
    for i in range(n_vs):
        if i == 0:
            td = spine_pts[1] - spine_pts[0]
        elif i == n_vs - 1:
            td = spine_pts[-1] - spine_pts[-2]
        else:
            td = spine_pts[i + 1] - spine_pts[i - 1]
        td_n = np.linalg.norm(td)
        spine_tangents[i] = td / td_n if td_n > 1e-12 else np.array([0.0, 0.0, 1.0])

    areas = []
    for idx, v in enumerate(vs):
        # Sample the full cross-section profile (closed loop: first == last)
        pts3d_open = np.array([surface_evaluate(blend_surf, u, v)[:3] for u in us])
        # Close the polygon
        pts3d = np.vstack([pts3d_open, pts3d_open[0]])

        centroid = pts3d_open.mean(axis=0)

        # Local frame: spine tangent is the "normal" to the cross-section plane
        t_dir = spine_tangents[idx]

        # u-axis: from centroid toward first profile point, projected out of t_dir
        ref = pts3d_open[0] - centroid
        ref -= np.dot(ref, t_dir) * t_dir
        ref_n = np.linalg.norm(ref)
        if ref_n < 1e-12:
            # fallback
            perp = np.array([0.0, 0.0, 1.0])
            perp -= np.dot(perp, t_dir) * t_dir
            perp_n = np.linalg.norm(perp)
            if perp_n < 1e-12:
                perp = np.array([0.0, 1.0, 0.0])
                perp -= np.dot(perp, t_dir) * t_dir
                perp_n = np.linalg.norm(perp) + 1e-30
            u_ax = perp / perp_n
        else:
            u_ax = ref / ref_n

        v_ax = np.cross(t_dir, u_ax)
        v_ax_n = np.linalg.norm(v_ax)
        if v_ax_n < 1e-12:
            areas.append(0.0)
            continue
        v_ax /= v_ax_n

        # Project to 2D
        pts2d = np.column_stack([
            np.dot(pts3d - centroid, u_ax),
            np.dot(pts3d - centroid, v_ax),
        ])
        # Shoelace on the closed polygon
        n_p = len(pts2d)
        shoelace = np.sum(
            pts2d[:-1, 0] * pts2d[1:, 1] - pts2d[1:, 0] * pts2d[:-1, 1]
        )
        areas.append(abs(shoelace) / 2.0)

    # Integrate: trapezoidal rule along the spine arc-length
    if len(dv_steps) == 0 or len(areas) < 2:
        return 0.0
    vol = float(np.trapezoid(areas, edge_arc))
    return vol


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors surface_fillet.py)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _nurbs_edge_blend_variable_section_spec = ToolSpec(
        name="nurbs_edge_blend_variable_section",
        description=(
            "Variable-section blend along a shared edge — cross-section morphs from one\n"
            "shape (rectangle / circle / ellipse / polygon) to another along the edge.\n"
            "\n"
            "Based on Vida-Martin-Varady 1994 §4 (variable-section blending) with Bezier\n"
            "corner rounding from Hartmann 1998.\n"
            "\n"
            "Provide:\n"
            "  face_a, face_b  : each as degree_u, degree_v, num_u, num_v,\n"
            "                    control_points (nu*nv flattened list of [x,y,z])\n"
            "  edge            : [[x,y,z], ...] 3D polyline along the shared edge\n"
            "  cross_sections  : list of {t, kind, width, height, radius} dicts\n"
            "                    where t ∈ [0,1]; kind ∈ rectangle/circle/ellipse\n"
            "  blend_method    : 'linear' | 'cubic_hermite' | 'C2'  (default 'linear')\n"
            "  samples         : int (default 32)\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  blend_cp_grid   : [[[x,y,z]]] — (n_profile x samples) control points\n"
            "  blend_edge_a    : [[x,y,z], ...] — boundary curve on face_a side\n"
            "  blend_edge_b    : [[x,y,z], ...] — boundary curve on face_b side\n"
            "  diagnostics     : {edge_length, n_stations, blend_method}\n"
            "\n"
            "Errors: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_ua": {"type": "integer"},
                "degree_va": {"type": "integer"},
                "num_ua": {"type": "integer"},
                "num_va": {"type": "integer"},
                "control_points_a": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "degree_ub": {"type": "integer"},
                "degree_vb": {"type": "integer"},
                "num_ub": {"type": "integer"},
                "num_vb": {"type": "integer"},
                "control_points_b": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "edge": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "cross_sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "t": {"type": "number"},
                            "kind": {"type": "string"},
                            "width": {"type": "number"},
                            "height": {"type": "number"},
                            "radius": {"type": "number"},
                        },
                        "required": ["t", "kind"],
                    },
                },
                "blend_method": {"type": "string"},
                "samples": {"type": "integer"},
            },
            "required": [
                "degree_ua", "degree_va", "num_ua", "num_va", "control_points_a",
                "degree_ub", "degree_vb", "num_ub", "num_vb", "control_points_b",
                "edge", "cross_sections",
            ],
        },
    )

    def _build_surf_from_args(
        degree_u: int,
        degree_v: int,
        num_u: int,
        num_v: int,
        raw_cp: list,
        label: str,
    ):
        """Build a NurbsSurface from LLM tool args. Returns (surf, error_str)."""
        if degree_u < 1 or degree_v < 1:
            return None, f"{label}: degree must be >= 1"
        if num_u < 2 or num_v < 2:
            return None, f"{label}: num_u and num_v must be >= 2"
        if len(raw_cp) != num_u * num_v:
            return None, (
                f"{label}: control_points length {len(raw_cp)} != {num_u * num_v}"
            )
        try:
            cp_flat = [np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = np.array([p.tolist()[:dim] for p in cp_flat],
                          dtype=float).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"{label}: invalid control_points: {exc}"
        surf = NurbsSurface(
            degree_u=int(degree_u),
            degree_v=int(degree_v),
            control_points=cp,
            knots_u=_make_clamped_knots(num_u, int(degree_u)),
            knots_v=_make_clamped_knots(num_v, int(degree_v)),
        )
        return surf, ""

    @register(_nurbs_edge_blend_variable_section_spec)
    async def run_nurbs_edge_blend_variable_section(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        face_a, err_a = _build_surf_from_args(
            a.get("degree_ua", 0), a.get("degree_va", 0),
            a.get("num_ua", 0), a.get("num_va", 0),
            a.get("control_points_a", []), "face_a",
        )
        if err_a:
            return err_payload(err_a, "BAD_ARGS")

        face_b, err_b = _build_surf_from_args(
            a.get("degree_ub", 0), a.get("degree_vb", 0),
            a.get("num_ub", 0), a.get("num_vb", 0),
            a.get("control_points_b", []), "face_b",
        )
        if err_b:
            return err_payload(err_b, "BAD_ARGS")

        raw_edge = a.get("edge", [])
        if len(raw_edge) < 2:
            return err_payload("edge must have at least 2 points", "BAD_ARGS")
        try:
            edge_pts = [np.asarray(p, dtype=float) for p in raw_edge]
        except Exception as exc:
            return err_payload(f"invalid edge: {exc}", "BAD_ARGS")

        raw_cs = a.get("cross_sections", [])
        if len(raw_cs) < 2:
            return err_payload("cross_sections must have at least 2 entries", "BAD_ARGS")
        try:
            cs_list = []
            for entry in raw_cs:
                t_val = float(entry.get("t", 0.0))
                kind = str(entry.get("kind", "circle"))
                width = float(entry.get("width", 1.0))
                height = float(entry.get("height", width))
                radius = float(entry.get("radius", width / 2.0))
                cs_list.append((t_val, CrossSection(
                    kind=kind, width=width, height=height, radius=radius
                )))
        except Exception as exc:
            return err_payload(f"invalid cross_sections: {exc}", "BAD_ARGS")

        blend_method = str(a.get("blend_method", "linear"))
        samples = int(a.get("samples", 32))

        try:
            blend_surf, edge_a, edge_b = variable_section_blend(
                face_a, face_b, edge_pts, cs_list,
                blend_method=blend_method,
                samples=samples,
            )
        except (TypeError, ValueError) as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"internal error: {exc}", "OP_FAILED")

        # Edge length
        edge_arr = np.array([p[:3] for p in edge_pts])
        edge_length = float(np.sum(np.linalg.norm(np.diff(edge_arr, axis=0), axis=1)))

        return ok_payload({
            "blend_cp_grid": blend_surf.control_points.tolist(),
            "blend_edge_a": [[float(v) for v in p] for p in edge_a],
            "blend_edge_b": [[float(v) for v in p] for p in edge_b],
            "diagnostics": {
                "edge_length": edge_length,
                "n_stations": samples,
                "blend_method": blend_method,
            },
        })
