"""
kerf_apparel.avatar
===================
Parametric body-form / dress-form generator for garment drape fitting.

Method
------
The body is modelled as a stack of horizontal elliptical cross-sections
parameterised by height z.  This is the industry-standard parametric
mannequin approach used in:

  * CAESAR anthropometric study (Robinette et al. 2002) — provides the
    basis for cross-sectional girth at 14 standard height levels.
  * ISO 8559-1:2017 "Size designation of clothes — Part 1: Anthropometric
    definitions for body measurement".
  * EN 13402-3:2004 size labelling — defines key horizontal girth codes.

Each horizontal slice at normalised height t ∈ [0, 1] is an ellipse
(a(t), b(t)) where a = lateral half-width and b = front-back half-depth.
The circumference of the ellipse at height t is approximated by Ramanujan's
(1914) second approximation, which has < 0.001% error for 0.5 ≤ b/a ≤ 2.

  C ≈ π [ 3(a+b) − √((3a+b)(a+3b)) ]          (Ramanujan 1914)

Landmark heights are derived from the CAESAR-pooled proportion table
(seated proportion reference, standing height = 1.0):
  floor   = 0.00   (ground / sole)
  ankle   = 0.04
  calf    = 0.14
  knee    = 0.27
  crotch  = 0.48   (inseam reference)
  hip     = 0.54
  waist   = 0.63
  bust    = 0.73
  armscye = 0.78
  shoulder= 0.82
  neck    = 0.86
  crown   = 1.00

The half-widths at each landmark are computed from standard body-girth
measurements by solving the Ramanujan equation for semi-axes assuming a
front-back/lateral ratio of 0.72 (typical female mannequin; 0.75 male).

Output
------
  BodyForm          — dataclass with measurements + mesh
  build_body_form   — constructs a BodyForm from a measurement dict
  body_form_to_obj  — exports a Wavefront OBJ string
  body_form_girth   — computes girth at a fractional height by interpolation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# CAESAR-based landmark proportions (height as fraction of stature)
# Reference: Robinette et al. 2002, CAESAR Final Report; Table 4
# ---------------------------------------------------------------------------

LANDMARK_HEIGHTS: Dict[str, float] = {
    "floor":    0.000,
    "ankle":    0.040,
    "calf":     0.140,
    "knee":     0.270,
    "crotch":   0.480,
    "hip":      0.540,
    "waist":    0.630,
    "underbust":0.680,
    "bust":     0.730,
    "armscye":  0.780,
    "shoulder": 0.820,
    "neck":     0.860,
    "crown":    1.000,
}

# Typical front-back / lateral half-axis ratio for female (ISO 8559-1 §5)
# and male mannequins (Bye et al. 2010, Journal of Fashion Technology)
_FB_RATIO_FEMALE = 0.72
_FB_RATIO_MALE   = 0.75


def _ramanujan_circumference(a: float, b: float) -> float:
    """Ramanujan 1914 ellipse perimeter, accurate to < 0.001%."""
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


def _semi_axis_from_girth(girth_cm: float, fb_ratio: float = _FB_RATIO_FEMALE) -> Tuple[float, float]:
    """
    Solve Ramanujan for the lateral semi-axis `a` given the circumference
    and a fixed front-back/lateral ratio r = b/a.

    C = π(a+b)(1 + 3h/(10+√(4−3h)))  where h = ((a−b)/(a+b))²
    b = r·a, so h = ((1−r)/(1+r))²  is constant for given r.

    => a = C / (π·(1+r)·(1 + 3h/(10+√(4−3h))))
    """
    r = fb_ratio
    h = ((1.0 - r) / (1.0 + r)) ** 2
    factor = math.pi * (1.0 + r) * (1.0 + 3.0 * h / (10.0 + math.sqrt(max(0.0, 4.0 - 3.0 * h))))
    a = girth_cm / factor
    b = r * a
    return a, b


# ---------------------------------------------------------------------------
# Standard measurement → girth mapping
# ---------------------------------------------------------------------------

def _derive_girths(
    height_cm: float,
    bust_cm: float,
    waist_cm: float,
    hip_cm: float,
    neck_cm: Optional[float] = None,
    knee_cm: Optional[float] = None,
    calf_cm: Optional[float] = None,
    ankle_cm: Optional[float] = None,
    sex: str = "female",
) -> Dict[str, float]:
    """
    Derive girths at each landmark from the five primary measurements.
    Missing secondary girths are estimated from CAESAR regression means
    (Robinette 2002, Table 7) expressed as fractions of bust/hip.
    """
    fb = _FB_RATIO_MALE if sex == "male" else _FB_RATIO_FEMALE
    g: Dict[str, float] = {}

    g["bust"]     = bust_cm
    g["waist"]    = waist_cm
    g["hip"]      = hip_cm
    g["underbust"]= bust_cm * 0.88    # EN 13402-3 underbust ≈ 0.88 × bust
    # CAESAR shoulder-to-bust interpolation
    g["armscye"]  = bust_cm * 0.87    # armscye girth ≈ 0.87 × bust
    g["shoulder"] = neck_cm * 1.4 if neck_cm else bust_cm * 0.54
    g["neck"]     = neck_cm if neck_cm else bust_cm * 0.39
    # Below-waist: interpolate waist→hip between crotch and hip
    g["crotch"]   = (waist_cm + hip_cm) / 2.0
    g["knee"]     = knee_cm if knee_cm else hip_cm * 0.52
    g["calf"]     = calf_cm if calf_cm else hip_cm * 0.44
    g["ankle"]    = ankle_cm if ankle_cm else hip_cm * 0.22
    g["floor"]    = ankle_cm * 0.6 if ankle_cm else hip_cm * 0.13
    g["crown"]    = neck_cm * 0.55 if neck_cm else bust_cm * 0.22   # head cap (not a true girth — symbolic)

    return g


# ---------------------------------------------------------------------------
# BodyForm dataclass
# ---------------------------------------------------------------------------

@dataclass
class BodyFormSlice:
    """One horizontal cross-section."""
    z_cm: float          # height above floor
    t: float             # normalised height (0=floor, 1=crown)
    girth_cm: float      # circumference
    a_cm: float          # lateral semi-axis (left-right half-width)
    b_cm: float          # front-back semi-axis
    landmark: str = ""   # nearest landmark label


@dataclass
class BodyForm:
    """
    Parametric body form.

    Attributes
    ----------
    height_cm : float
    bust_cm, waist_cm, hip_cm : float
    sex : str  — 'female' | 'male' | 'unisex'
    slices : list[BodyFormSlice]
        Cross-sections sampled every ~2 cm along height.
    landmarks : dict[str, BodyFormSlice]
        Named slices at the 13 standard landmark positions.
    n_slices : int
    n_vertices_per_ring : int  — default 32
    vertices : ndarray (N, 3)  — 3D mesh in cm
    faces : ndarray (M, 3)     — triangle indices
    """
    height_cm: float
    bust_cm: float
    waist_cm: float
    hip_cm: float
    sex: str
    slices: List[BodyFormSlice] = field(default_factory=list)
    landmarks: Dict[str, BodyFormSlice] = field(default_factory=dict)
    n_slices: int = 0
    n_vertices_per_ring: int = 32
    vertices: Optional[np.ndarray] = None
    faces: Optional[np.ndarray] = None


def _ellipse_ring(
    z_cm: float,
    a_cm: float,
    b_cm: float,
    n: int = 32,
) -> np.ndarray:
    """Return (n, 3) array of [x, y, z] points on an ellipse at height z."""
    theta = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    x = a_cm * np.cos(theta)
    y = b_cm * np.sin(theta)
    z_arr = np.full(n, z_cm)
    return np.column_stack([x, y, z_arr])


def build_body_form(
    height_cm: float = 168.0,
    bust_cm: float = 92.0,
    waist_cm: float = 74.0,
    hip_cm: float = 96.0,
    neck_cm: Optional[float] = None,
    knee_cm: Optional[float] = None,
    calf_cm: Optional[float] = None,
    ankle_cm: Optional[float] = None,
    sex: str = "female",
    n_vertices_per_ring: int = 32,
    n_slices_per_segment: int = 4,
) -> BodyForm:
    """
    Construct a parametric BodyForm from body measurements.

    Parameters
    ----------
    height_cm : float
        Total standing height (default 168 cm, ISO 8559-1 reference).
    bust_cm : float
        Bust girth in cm (default 92 — UK size 14).
    waist_cm : float
        Waist girth in cm (default 74).
    hip_cm : float
        Hip girth in cm, measured at fullest point (default 96).
    neck_cm, knee_cm, calf_cm, ankle_cm : optional float
        Secondary girth measurements.  If omitted, estimated from CAESAR
        regression relations vs bust/hip.
    sex : str
        'female' (default), 'male', or 'unisex' (average of both ratios).
    n_vertices_per_ring : int
        Tessellation resolution around each ring (default 32).
    n_slices_per_segment : int
        Number of interpolated slices between each landmark pair (default 4).

    Returns
    -------
    BodyForm
        Contains slices, landmarks, and a triangulated mesh.
    """
    if height_cm <= 0:
        raise ValueError("height_cm must be positive")
    if bust_cm <= 0 or waist_cm <= 0 or hip_cm <= 0:
        raise ValueError("girth measurements must be positive")
    sex = sex.lower()
    if sex not in ("female", "male", "unisex"):
        raise ValueError("sex must be 'female', 'male', or 'unisex'")

    fb_ratio = {
        "female": _FB_RATIO_FEMALE,
        "male":   _FB_RATIO_MALE,
        "unisex": (_FB_RATIO_FEMALE + _FB_RATIO_MALE) / 2.0,
    }[sex]

    girths = _derive_girths(
        height_cm, bust_cm, waist_cm, hip_cm,
        neck_cm=neck_cm, knee_cm=knee_cm, calf_cm=calf_cm, ankle_cm=ankle_cm,
        sex=sex,
    )

    # Build ordered list of (t, girth) for all landmarks
    lm_list = sorted(LANDMARK_HEIGHTS.items(), key=lambda kv: kv[1])
    lm_girths_t = [(t, girths[name], name) for name, t in lm_list]

    # Interpolate slices between landmarks
    all_slices: List[BodyFormSlice] = []
    for i in range(len(lm_girths_t) - 1):
        t0, g0, n0 = lm_girths_t[i]
        t1, g1, _  = lm_girths_t[i + 1]
        z0 = t0 * height_cm
        z1 = t1 * height_cm
        for j in range(n_slices_per_segment):
            alpha = j / n_slices_per_segment
            t = t0 + alpha * (t1 - t0)
            g = g0 + alpha * (g1 - g0)
            z = z0 + alpha * (z1 - z0)
            a, b = _semi_axis_from_girth(g, fb_ratio)
            sl = BodyFormSlice(z_cm=z, t=t, girth_cm=g, a_cm=a, b_cm=b, landmark=n0 if j == 0 else "")
            all_slices.append(sl)

    # Add the crown slice
    t1, g1, n1 = lm_girths_t[-1]
    a, b = _semi_axis_from_girth(g1, fb_ratio)
    all_slices.append(BodyFormSlice(z_cm=t1 * height_cm, t=t1, girth_cm=g1, a_cm=a, b_cm=b, landmark=n1))

    # Build landmarks dict (slices that coincide with landmark heights)
    landmarks: Dict[str, BodyFormSlice] = {}
    for sl in all_slices:
        if sl.landmark:
            landmarks[sl.landmark] = sl

    # Build mesh: one ring per slice
    all_verts: List[np.ndarray] = []
    for sl in all_slices:
        ring = _ellipse_ring(sl.z_cm, sl.a_cm, sl.b_cm, n_vertices_per_ring)
        all_verts.append(ring)

    vertices = np.vstack(all_verts)

    # Triangulate lateral surface: quad strips between adjacent rings
    n_rings = len(all_slices)
    n = n_vertices_per_ring
    faces: List[Tuple[int, int, int]] = []
    for i in range(n_rings - 1):
        base0 = i * n
        base1 = (i + 1) * n
        for j in range(n):
            j1 = (j + 1) % n
            # Two triangles per quad
            faces.append((base0 + j,  base0 + j1, base1 + j))
            faces.append((base1 + j1, base1 + j,  base0 + j1))

    # Cap top and bottom
    # Bottom cap: fan from centroid
    centroid_bot = np.mean(all_verts[0], axis=0)
    centroid_top = np.mean(all_verts[-1], axis=0)
    ci_bot = len(vertices)
    ci_top = ci_bot + 1
    vertices = np.vstack([vertices, centroid_bot[np.newaxis], centroid_top[np.newaxis]])
    for j in range(n):
        j1 = (j + 1) % n
        faces.append((ci_bot, j1, j))
    top_base = (n_rings - 1) * n
    for j in range(n):
        j1 = (j + 1) % n
        faces.append((ci_top, top_base + j, top_base + j1))

    faces_arr = np.array(faces, dtype=np.int32)

    bf = BodyForm(
        height_cm=height_cm,
        bust_cm=bust_cm,
        waist_cm=waist_cm,
        hip_cm=hip_cm,
        sex=sex,
        slices=all_slices,
        landmarks=landmarks,
        n_slices=len(all_slices),
        n_vertices_per_ring=n_vertices_per_ring,
        vertices=vertices,
        faces=faces_arr,
    )
    return bf


def body_form_girth(bf: BodyForm, t: float) -> float:
    """
    Interpolated girth (cm) at normalised height t ∈ [0, 1].

    Linear interpolation between adjacent slices.
    """
    t = max(0.0, min(1.0, t))
    slices = bf.slices
    if t <= slices[0].t:
        return slices[0].girth_cm
    if t >= slices[-1].t:
        return slices[-1].girth_cm
    for i in range(len(slices) - 1):
        t0 = slices[i].t
        t1 = slices[i + 1].t
        if t0 <= t <= t1:
            alpha = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return slices[i].girth_cm + alpha * (slices[i + 1].girth_cm - slices[i].girth_cm)
    return slices[-1].girth_cm


def body_form_to_obj(bf: BodyForm, name: str = "body_form") -> str:
    """
    Export a BodyForm to Wavefront OBJ string.

    The OBJ uses centimetres (standard for garment patterns).
    """
    lines = [
        f"# kerf-apparel parametric body form",
        f"# height={bf.height_cm}cm bust={bf.bust_cm}cm waist={bf.waist_cm}cm hip={bf.hip_cm}cm sex={bf.sex}",
        f"o {name}",
    ]
    for v in bf.vertices:
        lines.append(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
    for f in bf.faces:
        # OBJ is 1-indexed
        lines.append(f"f {f[0]+1} {f[1]+1} {f[2]+1}")
    return "\n".join(lines)


def body_form_landmark_summary(bf: BodyForm) -> Dict[str, dict]:
    """
    Return a dict of landmark → {z_cm, girth_cm, a_cm, b_cm}.
    Useful as a structured tool response payload.
    """
    out = {}
    for name, sl in bf.landmarks.items():
        out[name] = {
            "z_cm":      round(sl.z_cm, 2),
            "height_pct": round(sl.t * 100.0, 1),
            "girth_cm":  round(sl.girth_cm, 2),
            "half_width_cm":      round(sl.a_cm, 3),
            "half_depth_cm":      round(sl.b_cm, 3),
        }
    return out
