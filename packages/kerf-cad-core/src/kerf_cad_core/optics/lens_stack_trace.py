"""
kerf_cad_core.optics.lens_stack_trace — sequential paraxial & meridional
ray tracing through a multi-element lens stack.

Public API
----------
trace_lens_stack(surfaces, ray_h, ray_u, n_object=1.0)
    Sequential ray trace through a list of optical surfaces.

paraxial_properties(surfaces, n_object=1.0)
    Derive effective focal length (EFL), back focal length (BFL), and
    front focal length (FFL) from the marginal-ray trace.

Surface specification (dict)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  c        : float  curvature = 1/R (mm^-1).  0 = flat.
  t        : float  thickness to next surface (mm).  Last surface: 0.
  n        : float  refractive index AFTER this surface (image-space side).
  k        : float  conic constant (default 0, sphere).  Used for
                    meridional intersect; paraxial ignores k.

Ray specification
~~~~~~~~~~~~~~~~~
  ray_h : float  paraxial height at first surface (mm).
  ray_u : float  paraxial angle in object space (rad, signed, small).

Paraxial trace (Welford 1986 §3.3)
-----------------------------------
At surface j with curvature c_j, the paraxial refraction equation is

    n_prime * u_prime = n * u - h * c * (n_prime - n)   [nu-form]

followed by the transfer to the next surface

    h_{j+1} = h_j + t_j * u_prime_j

Meridional (real) trace (Welford 1986 §5)
------------------------------------------
Uses exact Snell's law with full sin/cos.  The ray is described by its
height Y above the axis and direction cosines (L, M) in the meridional
plane (L = cos of angle to axis, M = sin of angle to axis).

At each surface:
  1.  Find intersect height Y* with the conic surface using Newton-Raphson.
  2.  Compute surface normal direction cosines at Y*.
  3.  Apply exact Snell (vector form): n * d = n_prime * d_prime + ...
  4.  Transfer to next surface vertex.

Scope / limitations
--------------------
v1 implements paraxial + meridional ray heights and angles at each
surface, plus derived EFL / BFL / FFL.

OUT OF SCOPE (v1):
  - Seidel / wavefront aberration coefficients
  - Multi-wavelength (polychromatic) aberration / dispersion traces
  - Vignetting / aperture-stop clipping
  - Aspheric (higher-order) terms beyond the conic
  - Skew rays / full 3-D ray trace

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §3.3 (paraxial trace), §5 (exact ray trace through conic surfaces).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §6.4 (thin lens, lensmaker's eq.).  Oracle: biconvex BK7 f ~48.4 mm.
Kingslake, R. -- "Lens Design Fundamentals", Academic Press, 1978,
    §10.1 (Cooke triplet paraxial trace).

Units: lengths in mm, angles in radians.

Author: imranparuk
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False,
           finite: bool = True) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if finite and not math.isfinite(v):
        return f"{name} must be finite"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    return None


def _validate_surface(s: Any, idx: int) -> str | None:
    if not isinstance(s, dict):
        return f"surface[{idx}] must be a dict"
    for field in ("c", "t", "n"):
        if field not in s:
            return f"surface[{idx}] missing required field '{field}'"
        err = _guard(f"surface[{idx}].{field}", s[field])
        if err:
            return err
    if float(s["n"]) < 1.0:
        return f"surface[{idx}].n must be >= 1.0"
    return None


# ---------------------------------------------------------------------------
# Paraxial trace
# ---------------------------------------------------------------------------

def _paraxial_refract(h: float, u: float, n: float, n_prime: float,
                      c: float) -> float:
    """
    Paraxial refraction at a single surface (Welford 1986 §3.3).

    nu-form: n_prime * u_prime = n * u - h * c * (n_prime - n)

    Returns u_prime (paraxial angle after refraction).
    """
    nu_prime = n * u - h * c * (n_prime - n)
    return nu_prime / n_prime


def _paraxial_transfer(h: float, u_prime: float, t: float) -> float:
    """
    Transfer to next surface vertex.

        h_{j+1} = h_j + t * u_prime_j
    """
    return h + t * u_prime


# ---------------------------------------------------------------------------
# Meridional (real) trace helpers
# ---------------------------------------------------------------------------

def _conic_sag(Y: float, c: float, k: float) -> float:
    """
    Sag z of a conic surface at height Y (Welford 1986 §5.1).

        z = c * Y^2 / (1 + sqrt(1 - (1+k) * c^2 * Y^2))

    Returns math.nan if the discriminant is negative (ray misses surface).
    """
    disc = 1.0 - (1.0 + k) * c * c * Y * Y
    if disc < 0.0:
        return math.nan
    return c * Y * Y / (1.0 + math.sqrt(disc))


def _surface_normal_cosines(Y: float, c: float, k: float
                             ) -> tuple[float, float]:
    """
    Direction cosines (cos_z, cos_Y) of the outward surface normal
    in the meridional plane (Welford 1986 §5.2).

    For a conic z(Y):
        dz/dY = c * Y / sqrt(1 - (1+k) * c^2 * Y^2)

    The outward normal direction (z, Y): (-dz/dY, 1) unnormalised,
    then normalised so that cos_z^2 + cos_Y^2 = 1.
    """
    disc = 1.0 - (1.0 + k) * c * c * Y * Y
    if disc <= 0.0:
        return math.nan, math.nan
    dz_dY = c * Y / math.sqrt(disc)
    mag = math.sqrt(1.0 + dz_dY * dz_dY)
    cos_z = 1.0 / mag
    cos_Y = -dz_dY / mag
    return cos_z, cos_Y


def _meridional_refract(
    Y: float,
    L: float,    # direction cosine along optical axis (z)
    M: float,    # direction cosine along transverse (Y)
    n: float,
    n_prime: float,
    c: float,
    k: float,
) -> tuple[float, float, bool]:
    """
    Exact meridional refraction at a single conic surface (Welford 1986 §5.2).

    Returns (L_prime, M_prime, tir_flag).

    Vector form of Snell's law (Born & Wolf §1.5.3):
        d_prime = (n/n_prime) * d + ((n/n_prime) * cos_i - cos_t) * N_in

    where N_in is the inward unit normal (pointing into n_prime medium),
    cos_i = dot(d, N_in), cos_t = sqrt(1 - (n/n_prime)^2 * (1 - cos_i^2)).
    """
    cos_z, cos_Y = _surface_normal_cosines(Y, c, k)
    if math.isnan(cos_z):
        return math.nan, math.nan, False

    # The inward normal points toward the centre of curvature (into n_prime).
    # For a surface with c > 0, centre is to the right (+z), so inward
    # normal has positive z-component.
    Nz, NY = cos_z, cos_Y

    # cos of angle of incidence: dot(ray, inward_normal)
    cos_i = L * Nz + M * NY

    # If negative, ray hits the surface from the wrong side — flip normal
    if cos_i < 0.0:
        Nz, NY = -Nz, -NY
        cos_i = -cos_i

    ratio = n / n_prime
    sin2_t = ratio * ratio * (1.0 - cos_i * cos_i)
    if sin2_t > 1.0:
        return math.nan, math.nan, True  # TIR

    cos_t = math.sqrt(1.0 - sin2_t)
    # Vector form of Snell's law (Born & Wolf §1.5.3, eq. 1.5.23):
    #   n' * d' = n * d + (n' * cos_t - n * cos_i) * N
    #   => d' = (n/n') * d + (cos_t - (n/n') * cos_i) * N
    # Note the MINUS sign: the refraction term subtracts from the normal component.
    refr = cos_t - ratio * cos_i
    L_prime = ratio * L + refr * Nz
    M_prime = ratio * M + refr * NY

    # Re-normalise
    mag = math.sqrt(L_prime * L_prime + M_prime * M_prime)
    if mag > 0.0:
        L_prime /= mag
        M_prime /= mag

    return L_prime, M_prime, False


def _meridional_transfer_full(
    Y: float,
    L: float,
    M: float,
    c_cur: float,
    k_cur: float,
    t: float,
    c_next: float,
    k_next: float,
) -> tuple[float, float]:
    """
    Newton-Raphson intersection of the transferred ray with the next conic
    surface (Welford 1986 §5.3).

    Ray parametric in frame of next surface vertex:
        z(s) = z0 + L*s,  Y(s) = Y0 + M*s
    where z0 = sag(Y, c_cur, k_cur) - t.

    Conic intersection: F(s) = z(s) - sag(Y(s)) = 0.
    Newton: s <- s - F(s)/F'(s).
    """
    z_sag = _conic_sag(Y, c_cur, k_cur)
    if math.isnan(z_sag):
        return math.nan, math.nan

    z0 = z_sag - t
    Y0 = Y

    # Initial guess: flat-plane intercept
    s = (-z0 / L) if abs(L) > 1e-15 else 0.0

    for _ in range(20):
        Ys = Y0 + M * s
        zs = z0 + L * s
        disc = 1.0 - (1.0 + k_next) * c_next * c_next * Ys * Ys
        if disc <= 0.0:
            return math.nan, math.nan
        sag_val = c_next * Ys * Ys / (1.0 + math.sqrt(disc))
        F = zs - sag_val
        dz_dY = c_next * Ys / math.sqrt(disc)
        dF = L - dz_dY * M
        if abs(dF) < 1e-18:
            break
        ds = -F / dF
        s += ds
        if abs(ds) < 1e-12:
            break

    Y_next = Y0 + M * s
    return Y_next, M


# ---------------------------------------------------------------------------
# Main trace function
# ---------------------------------------------------------------------------

def trace_lens_stack(
    surfaces: list[dict],
    ray_h: float,
    ray_u: float,
    n_object: float = 1.0,
) -> dict:
    """
    Sequential paraxial + meridional ray trace through a multi-element
    lens stack.

    Parameters
    ----------
    surfaces : list of dicts, each with:
        c  : curvature 1/R (mm^-1)
        t  : thickness to next surface vertex (mm)
        n  : refractive index of medium AFTER this surface
        k  : conic constant (default 0 = sphere)
    ray_h : float
        Ray height at first surface (mm).
    ray_u : float
        Ray angle in object space (rad).
    n_object : float
        Refractive index of the object-space medium (default 1.0 = air).

    Returns
    -------
    dict
        ok                         : True
        paraxial_surfaces          : list of per-surface paraxial data
        meridional_surfaces        : list of per-surface meridional data
        paraxial_image_distance_mm : distance from last surface to paraxial image (mm)
        meridional_image_Y_mm      : meridional ray Y at paraxial image plane (mm)
        n_surfaces                 : number of surfaces traced
        tir                        : True if any TIR encountered

    References
    ----------
    Paraxial: Welford (1986) §3.3 nu-form.
    Meridional: exact Snell + Newton-Raphson conic intersect (Welford 1986 §5).
    Seidel aberration coefficients are OUT OF SCOPE for v1.
    """
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    for nm, val in [("ray_h", ray_h), ("ray_u", ray_u), ("n_object", n_object)]:
        e = _guard(nm, val)
        if e:
            return _err(e)
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    # ---- Paraxial trace ---------------------------------------------------
    h = float(ray_h)
    u = float(ray_u)
    n = float(n_object)

    paraxial_log = []

    for idx, surf in enumerate(surfaces):
        c = float(surf["c"])
        t = float(surf["t"])
        n_prime = float(surf["n"])

        u_prime = _paraxial_refract(h, u, n, n_prime, c)
        paraxial_log.append({
            "surface": idx,
            "h_mm": h,
            "u_rad": u,
            "u_prime_rad": u_prime,
            "n_in": n,
            "n_out": n_prime,
            "c_mm_inv": c,
        })

        h = _paraxial_transfer(h, u_prime, t)
        u = u_prime
        n = n_prime

    # Image distance from last surface: h + u * d_img = 0
    if abs(u) < 1e-18:
        paraxial_image_dist = math.inf
    else:
        paraxial_image_dist = -h / u

    # ---- Meridional trace -------------------------------------------------
    ang = float(ray_u)
    M_val = math.sin(ang)
    L_val = math.cos(ang)

    Y = float(ray_h)

    meridional_log = []
    tir_flag = False

    n_mer = float(n_object)
    for idx, surf in enumerate(surfaces):
        c = float(surf["c"])
        k = float(surf.get("k", 0.0))
        t = float(surf["t"])
        n_prime = float(surf["n"])

        L_prime, M_prime, tir = _meridional_refract(Y, L_val, M_val, n_mer, n_prime, c, k)
        if tir:
            tir_flag = True

        meridional_log.append({
            "surface": idx,
            "Y_mm": Y,
            "L_in": L_val,
            "M_in": M_val,
            "L_out": L_prime,
            "M_out": M_prime,
            "n_in": n_mer,
            "n_out": n_prime,
            "tir": tir,
        })

        if tir or math.isnan(L_prime):
            L_val, M_val = math.nan, math.nan
            Y = math.nan
            n_mer = n_prime
            continue

        # Transfer to next surface
        if t == 0.0 or idx == len(surfaces) - 1:
            # Last surface or zero thickness: propagate to axis intersection
            if abs(L_prime) > 1e-15:
                z_sag = _conic_sag(Y, c, k)
                if not math.isnan(z_sag):
                    Y_next = Y + (M_prime / L_prime) * (-z_sag)
                else:
                    Y_next = Y
            else:
                Y_next = Y
        else:
            next_surf = surfaces[idx + 1]
            c_next = float(next_surf["c"])
            k_next = float(next_surf.get("k", 0.0))
            Y_next, _ = _meridional_transfer_full(
                Y, L_prime, M_prime, c, k, t, c_next, k_next
            )

        Y = Y_next
        L_val = L_prime
        M_val = M_prime
        n_mer = n_prime

    # Propagate to paraxial image plane
    if math.isnan(Y) or math.isnan(L_val) or abs(L_val) < 1e-15:
        meridional_image_Y = math.nan
    else:
        meridional_image_Y = Y + (M_val / L_val) * paraxial_image_dist

    return {
        "ok": True,
        "n_surfaces": len(surfaces),
        "paraxial_surfaces": paraxial_log,
        "meridional_surfaces": meridional_log,
        "paraxial_image_distance_mm": paraxial_image_dist,
        "meridional_image_Y_mm": meridional_image_Y,
        "tir": tir_flag,
    }


# ---------------------------------------------------------------------------
# Paraxial system properties
# ---------------------------------------------------------------------------

def paraxial_properties(
    surfaces: list[dict],
    n_object: float = 1.0,
) -> dict:
    """
    Derive EFL, BFL, and FFL from canonical paraxial ray traces.

    Uses a marginal ray (h=1, u=0) for EFL and BFL, and a reverse
    marginal ray for FFL.

    Parameters
    ----------
    surfaces   : list of surface dicts (same format as trace_lens_stack).
    n_object   : refractive index of object space (default 1.0).

    Returns
    -------
    dict
        ok             : True
        EFL_mm         : effective focal length (mm)
        BFL_mm         : back focal length (mm)
        FFL_mm         : front focal length (mm, negative = to left of first surface)
        power_mm_inv   : system optical power (mm^-1)

    References
    ----------
    Hecht §5.2 (principal planes, EFL, BFL, FFL).
    Welford (1986) §3.5 (marginal ray derived properties).
    """
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    # Marginal ray: h=1, u=0 (collimated input from infinity)
    result_m = trace_lens_stack(surfaces, ray_h=1.0, ray_u=0.0, n_object=n_object)
    if not result_m["ok"]:
        return result_m

    bfl = result_m["paraxial_image_distance_mm"]

    # EFL from u_final of marginal ray (h_in=1, u_in=0)
    last_log = result_m["paraxial_surfaces"][-1]
    u_final = last_log["u_prime_rad"]

    if abs(u_final) < 1e-18:
        efl = math.inf
        power = 0.0
    else:
        efl = -1.0 / u_final   # h_in=1, Welford §3.5
        power = 1.0 / efl

    # FFL via reverse trace
    # Build reversed system: flip curvature signs, reorder thicknesses
    n_s = len(surfaces)
    n_image_val = float(surfaces[-1]["n"])
    rev_surfaces = []
    for i, s in enumerate(reversed(surfaces)):
        # Thickness for reversed surface i: the gap *before* original surface (n_s-1-i)
        # = thickness of original surface (n_s-2-i) for i < n_s-1, else 0
        t_rev = float(surfaces[n_s - 2 - i]["t"]) if i < n_s - 1 else 0.0
        rev_surfaces.append({
            "c": -float(s["c"]),
            "t": t_rev,
            "n": float(s["n"]),
            "k": float(s.get("k", 0.0)),
        })
    # Fix the n values for the reversed system: n_out of reversed surface i =
    # n_in of original surface (n_s-1-i) = n_object for i=n_s-1, else n of surface (n_s-2-i).
    # Actually: in the reversed system, the medium between surfaces is the same glass.
    # Simpler: rebuild n values from scratch using reversed order.
    #   The reversed system in medium n_image_val encounters surfaces from back to front.
    #   Medium sequence (reversed): n_image → ... → n_object
    rev2 = []
    n_seq = [float(n_object)] + [float(s["n"]) for s in surfaces]
    # reversed order: surface i encounters medium transition n_seq[n_s-i] -> n_seq[n_s-i-1]
    for i in range(n_s):
        orig_idx = n_s - 1 - i
        t_rev = float(surfaces[orig_idx - 1]["t"]) if orig_idx > 0 else 0.0
        rev2.append({
            "c": -float(surfaces[orig_idx]["c"]),
            "t": t_rev,
            "n": n_seq[orig_idx],   # medium after this surface in reversed trace
            "k": float(surfaces[orig_idx].get("k", 0.0)),
        })
    rev2[-1]["t"] = 0.0

    result_r = trace_lens_stack(rev2, ray_h=1.0, ray_u=0.0, n_object=n_image_val)
    if result_r["ok"]:
        ffl = -result_r["paraxial_image_distance_mm"]
    else:
        ffl = math.nan

    return {
        "ok": True,
        "EFL_mm": efl,
        "BFL_mm": bfl,
        "FFL_mm": ffl,
        "power_mm_inv": power,
    }
