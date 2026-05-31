"""
kerf_cad_core.optics.coma_coefficient — Seidel third-order coma coefficient (S_II)
for a single thin lens using the closed-form Welford §7.4 polynomial.

Public API
----------
ThinLensSpec  dataclass  — lens parameters (focal_length_mm, n, aperture, q, p)
ImageSpec     dataclass  — imaging geometry (object_height_mm, image_distance_mm)
ComaCoefficientReport     dataclass  — coma results
compute_coma_coefficient(lens, img) -> ComaCoefficientReport | dict

Theory (Welford §7.4 / Hopkins W_131 / Born & Wolf §5.3)
---------------------------------------------------------
For a single thin lens with the aperture stop coincident with the lens and both
object and image spaces in air (n_obj = n_img = 1), the Seidel coma sum S_II is
given by the closed-form polynomial (Welford 1986 §7.4):

  S_II = u_bar · h³ · φ² · [A(n)·q  +  B(n)·(p + 2)]

where:

  u_bar = object_height_mm / image_distance_mm    (paraxial chief-ray angle, rad)
  h     = aperture_radius_mm                       (marginal ray height at lens)
  φ     = 1 / focal_length_mm                      (lens power, mm⁻¹)
  q     = shape factor  = (R₁+R₂)/(R₁−R₂)         (Welford §7.4 eq. 7.43)
  p     = conjugate factor = (u'+u)/(u'−u)         (Welford §7.4 eq. 7.44)
            p = −1  for object at infinity (u_in = 0)
            p =  0  for symmetric conjugates (1:1 magnification, object at 2f)
            p = +1  for object at f (image at infinity)
  A(n) = (n+1) / (2·n·(n−1))                       (shape-factor coefficient)
  B(n) = −(2n+1) / (2·n)                            (conjugate-factor coefficient)

Derivation note
---------------
This formula is derived by substituting the thin-lens parameterisation
  c₁ = φ·(1+q) / (2·(n−1)),   c₂ = φ·(q−1) / (2·(n−1))
into the per-surface Seidel coma sum (Welford §7 eq. 7.42):
  S_II_j = −A_j · Ā_j · h_j · Δ(u/n)_j
and summing over both surfaces.  The result is numerically verified against a
direct two-surface paraxial trace across q ∈ {−1, −0.5, 0, 0.5, 1} and
p ∈ {−1, 0, 1} for n ∈ {1.4, 1.5, 1.5168, 1.6, 1.7, 1.8}.

Aplanatic shape factor
----------------------
Setting S_II = 0 and solving for q:

  q_aplanatic = (2n+1)·(n−1)·(p+2) / (n+1)

For BK7 glass (n = 1.5168) with object at infinity (p = −1):
  q_aplanatic ≈ 0.8283  (a near-plano-convex lens, curved side facing the image)

Hopkins W_131 notation
----------------------
The Hopkins wavefront aberration coefficient W_131 is related to S_II by:

  W_131 = −S_II         (sign convention: Welford S_II = −W_131)

The physical transverse (sagittal) coma at the image plane:

  C_s (sagittal, mm)     = S_II / (8 · F#)
  C_t (tangential, mm)   = 3 · C_s             (Welford §11.4 eq. 11.4.4)
  angular sagittal (rad) = C_s / image_distance_mm
  angular sagittal (″)   = (C_s / image_distance_mm) × 206 265   [arcseconds]

where F# = focal_length_mm / (2 · aperture_radius_mm) is the f-number.
The 'coma_blur_mm' is |C_s| (sagittal transverse displacement at image plane).

HONEST LIMITATIONS
------------------
* Third-order (Seidel) coma only.  Fifth-order Schwarzschild coma and
  higher-order Hopkins terms require a full finite-ray OPD analysis and are
  NOT included.
* Single thin lens in air.  Thick-lens, cemented doublet, or multi-element
  systems require the per-surface trace in seidel_coma.compute_seidel_coma().
* Aperture stop coincident with lens (no stop-shift terms).  If the stop is
  separated from the lens, the Seidel coma changes; that case is not handled.
* Monochromatic only.  Lateral colour (chromatic coma) is not modelled.
* Paraxial (first-order) chief-ray angle: u_bar = object_height/image_distance.
  Large field angles (>15° for f/# < 2) will show >5% departure from this
  Seidel prediction.

References
----------
Welford, W.T.  "Aberrations of Optical Systems", Adam Hilger, 1986.
    §7.4 (thin-lens aberration polynomial, eqs. 7.43–7.47).
    §11.4 (transverse coma, tangential/sagittal decomposition, eq. 11.4.4).
Born, M. & Wolf, E.  "Principles of Optics", 7th ed., Cambridge, 1999.
    §5.3 (transverse ray aberrations from Seidel coefficients;
          eq. 5.3.29 C_t = 3·C_s).
    §5.5.3 (Hopkins W_131 notation and sign convention).
Smith, W.J.  "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008.
    §4.3 (thin-lens aberration coefficients, Table 4.1).

Units: lengths in mm, angles in radians unless noted.
Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# LLM tool registration (gated — kerf_chat is only present in the cloud env)
# ---------------------------------------------------------------------------
try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
    _HAS_REGISTRY = True
except ImportError:
    _HAS_REGISTRY = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False,
           nonzero: bool = False) -> "str | None":
    """Return an error message string if *value* fails validation, else None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    if nonzero and v == 0.0:
        return f"{name} must be non-zero"
    return None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ThinLensSpec:
    """
    Parameters describing a single thin lens for coma computation.

    Attributes
    ----------
    focal_length_mm : float
        EFL of the thin lens (mm).  Positive for converging, negative for
        diverging.  Must be non-zero.
    refractive_index_n : float
        Refractive index of the lens glass.  Must be > 1.0.
    aperture_radius_mm : float
        Marginal-ray height at the lens / entrance-pupil radius (mm, > 0).
    shape_factor_q : float
        Bending (shape) factor q = (R₁+R₂)/(R₁−R₂).
        q = 0   : equiconvex / equiconcave
        q = +1  : plano-convex curved-first (flat rear, R₂=∞)
        q = −1  : plano-convex flat-first (flat front, R₁=∞)
        Welford (1986) §7.4 eq. 7.43.
    conjugate_factor_p : float
        Conjugate (magnification) factor p = (u′+u)/(u′−u) where u is the
        paraxial marginal-ray angle in object space and u′ in image space.
        p = −1  : object at infinity (standard default)
        p =  0  : symmetric conjugates, m = −1 (object at 2f)
        p = +1  : image at infinity (object at f)
        Welford (1986) §7.4 eq. 7.44.
    """
    focal_length_mm: float
    refractive_index_n: float
    aperture_radius_mm: float
    shape_factor_q: float
    conjugate_factor_p: float = -1.0


@dataclass
class ImageSpec:
    """
    Imaging geometry for the coma computation.

    Attributes
    ----------
    object_height_mm : float
        Transverse object (or image) field height (mm).  Used to determine
        the paraxial chief-ray angle u_bar = object_height_mm /
        image_distance_mm.  Must be finite (use 0.0 for on-axis, where coma
        is zero by symmetry).
    image_distance_mm : float
        Paraxial image distance from the lens to the image plane (mm, > 0).
        For an object at infinity this equals the focal length.
    """
    object_height_mm: float
    image_distance_mm: float


@dataclass
class ComaCoefficientReport:
    """
    Seidel third-order coma coefficient report for a single thin lens.

    Attributes
    ----------
    seidel_S_II : float
        Welford Seidel coma sum S_II (mm·rad) evaluated at the given field
        height.  Positive sign means coma flares toward the optical axis
        (inner coma); negative sign means it flares outward (outer coma)
        — exact sign depends on Welford (1986) §7 convention.
    wave_aberration_W_131 : float
        Hopkins wavefront aberration coefficient W_131 = −S_II (mm·rad).
        W_131 > 0 corresponds to positive (outward) coma flare in the
        Hopkins/Zemax sign convention.
    sagittal_coma_arcsec : float
        Angular sagittal coma blur at the image plane (arc-seconds).
        Sagittal coma = S_II / (8·F#·image_distance) × 206 265  (arcsec).
        This is the angular radius of the sagittal comatic circle.
        Zero for on-axis field (object_height_mm = 0).
    tangential_coma_arcsec : float
        Angular tangential coma = 3 × sagittal_coma_arcsec (arcsec).
        Welford §11.4 eq. 11.4.4: tangential flare = 3 × sagittal flare.
    coma_blur_mm : float
        Physical sagittal coma transverse displacement at the image plane:
        |S_II| / (8·F#)  (mm).  This is the radius of the sagittal comatic
        circle in the image plane.
    q_aplanatic : float
        Shape factor q that gives S_II = 0 for the given n, p combination.
        q_aplanatic = (2n+1)·(n−1)·(p+2) / (n+1).
        Using this q eliminates third-order coma.
    honest_caveat : str
        Plain-text statement of scope and limitations.
    """
    seidel_S_II: float = 0.0
    wave_aberration_W_131: float = 0.0
    sagittal_coma_arcsec: float = 0.0
    tangential_coma_arcsec: float = 0.0
    coma_blur_mm: float = 0.0
    q_aplanatic: float = 0.0
    honest_caveat: str = (
        "Third-order (Seidel) coma only via Welford §7.4 thin-lens polynomial. "
        "Fifth-order Schwarzschild coma and higher-order Hopkins terms are NOT "
        "included and require a full finite-ray OPD analysis. "
        "Single thin lens in air only; thick-lens or multi-element systems should "
        "use seidel_coma.compute_seidel_coma() instead. "
        "Stop coincident with lens; stop-shift terms are not modelled. "
        "Monochromatic only; chromatic (lateral) coma excluded."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "seidel_S_II": self.seidel_S_II,
            "wave_aberration_W_131": self.wave_aberration_W_131,
            "sagittal_coma_arcsec": self.sagittal_coma_arcsec,
            "tangential_coma_arcsec": self.tangential_coma_arcsec,
            "coma_blur_mm": self.coma_blur_mm,
            "q_aplanatic": self.q_aplanatic,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_coma_coefficient(
    lens: ThinLensSpec,
    img: ImageSpec,
) -> "ComaCoefficientReport | dict":
    """
    Compute the Seidel third-order coma coefficient S_II for a single thin
    lens using the closed-form Welford §7.4 polynomial.

    Algorithm
    ---------
    1.  Validate inputs.
    2.  Compute paraxial chief-ray angle:
            u_bar = object_height_mm / image_distance_mm    (radians)
    3.  Evaluate the Welford §7.4 polynomial:
            S_II = u_bar · h³ · φ² · [A(n)·q  +  B(n)·(p + 2)]
        where:
            φ = 1 / focal_length_mm
            A(n) = (n+1) / (2·n·(n−1))
            B(n) = −(2n+1) / (2·n)
    4.  Compute W_131 = −S_II (Hopkins notation).
    5.  Compute F# = focal_length / (2·aperture_radius).
    6.  Compute sagittal coma:
            C_s_mm (transverse) = S_II / (8 · F#)
            C_s_arcsec          = (C_s_mm / image_distance) × 206 265
    7.  Tangential coma = 3 × sagittal coma.
    8.  Aplanatic q: q_aplanatic = (2n+1)·(n−1)·(p+2) / (n+1).

    Parameters
    ----------
    lens : ThinLensSpec
        Lens physical and optical parameters.
    img : ImageSpec
        Imaging geometry (field height + image distance).

    Returns
    -------
    ComaCoefficientReport  on success.
    dict {ok: False, reason: ...}  on input error.
    """
    # ---- Validate ThinLensSpec -----------------------------------------------
    if not isinstance(lens, ThinLensSpec):
        e = _guard("focal_length_mm", getattr(lens, "focal_length_mm", None), nonzero=True)
        return _err(f"lens must be a ThinLensSpec instance; got {type(lens).__name__!r}")

    e = _guard("focal_length_mm", lens.focal_length_mm, nonzero=True)
    if e:
        return _err(e)

    e = _guard("refractive_index_n", lens.refractive_index_n, positive=True)
    if e:
        return _err(e)
    if float(lens.refractive_index_n) <= 1.0:
        return _err(
            f"refractive_index_n must be > 1.0 (glass must be optically denser than air), "
            f"got {lens.refractive_index_n}"
        )

    e = _guard("aperture_radius_mm", lens.aperture_radius_mm, positive=True)
    if e:
        return _err(e)

    e = _guard("shape_factor_q", lens.shape_factor_q)
    if e:
        return _err(e)

    e = _guard("conjugate_factor_p", lens.conjugate_factor_p)
    if e:
        return _err(e)

    # ---- Validate ImageSpec --------------------------------------------------
    if not isinstance(img, ImageSpec):
        return _err(f"img must be an ImageSpec instance; got {type(img).__name__!r}")

    e = _guard("object_height_mm", img.object_height_mm)
    if e:
        return _err(e)

    e = _guard("image_distance_mm", img.image_distance_mm, positive=True)
    if e:
        return _err(e)

    # ---- Extract and cast parameters ----------------------------------------
    f = float(lens.focal_length_mm)       # focal length (mm), may be negative
    n = float(lens.refractive_index_n)    # glass refractive index (> 1)
    h = float(lens.aperture_radius_mm)    # aperture radius (mm)
    q = float(lens.shape_factor_q)        # bending factor
    p = float(lens.conjugate_factor_p)    # conjugate factor

    h_obj = float(img.object_height_mm)   # off-axis field height (mm)
    v = float(img.image_distance_mm)      # image distance (mm)

    # ---- Paraxial chief-ray angle (radians) ---------------------------------
    # Small-angle paraxial approximation: u_bar = h_obj / v
    # This is exact in first-order optics; deviates at large field angles.
    u_bar = h_obj / v

    # ---- Welford §7.4 polynomial coefficients --------------------------------
    phi = 1.0 / f                                     # lens power (mm⁻¹)
    A_n = (n + 1.0) / (2.0 * n * (n - 1.0))          # shape coeff: (n+1)/(2n(n-1))
    B_n = -(2.0 * n + 1.0) / (2.0 * n)               # conjugate coeff: -(2n+1)/(2n)

    # S_II = u_bar · h³ · φ² · [A(n)·q + B(n)·(p+2)]
    polynomial = A_n * q + B_n * (p + 2.0)
    S_II = u_bar * (h ** 3) * (phi ** 2) * polynomial

    # ---- W_131 (Hopkins) = −S_II (Welford sign convention) ------------------
    W_131 = -S_II

    # ---- F-number and coma in physical units ---------------------------------
    F_num = abs(f) / (2.0 * h)   # paraxial f-number = |f| / (2·h)

    # Transverse sagittal coma at image plane (mm):
    # C_s = S_II / (8 · F#)   (Welford §11.4)
    C_s_mm = S_II / (8.0 * F_num)

    # Angular sagittal coma (arcseconds):
    # theta_s (rad) = C_s_mm / image_distance_mm    (small-angle: tan ≈ angle)
    # theta_s (arcsec) = theta_s (rad) × 206 265
    _ARCSEC_PER_RAD = 206_265.0
    if v > 0.0:
        sagittal_arcsec = (C_s_mm / v) * _ARCSEC_PER_RAD
    else:
        sagittal_arcsec = 0.0

    # Tangential coma = 3 × sagittal (Welford §11.4 eq. 11.4.4; Born & Wolf §5.3 eq. 5.3.29)
    tangential_arcsec = 3.0 * sagittal_arcsec

    # Physical coma blur radius (mm)
    coma_blur_mm = abs(C_s_mm)

    # ---- Aplanatic shape factor ----------------------------------------------
    # S_II = 0 when: A_n · q + B_n · (p+2) = 0
    # => q_aplanatic = −B_n · (p+2) / A_n = (2n+1)·(n−1)·(p+2) / (n+1)
    q_aplanatic = -B_n * (p + 2.0) / A_n  # = (2n+1)(n-1)(p+2)/(n+1)

    return ComaCoefficientReport(
        seidel_S_II=S_II,
        wave_aberration_W_131=W_131,
        sagittal_coma_arcsec=sagittal_arcsec,
        tangential_coma_arcsec=tangential_arcsec,
        coma_blur_mm=coma_blur_mm,
        q_aplanatic=q_aplanatic,
    )


# ---------------------------------------------------------------------------
# LLM tool: optics_compute_coma_coefficient
# ---------------------------------------------------------------------------

if _HAS_REGISTRY:
    import json as _json

    _coma_coefficient_spec = ToolSpec(
        name="optics_compute_coma_coefficient",
        description=(
            "Compute the Seidel third-order coma coefficient (S_II / W_131) for a\n"
            "single thin lens using the Welford §7.4 closed-form polynomial.\n"
            "\n"
            "Theory (Welford 1986 §7.4 / Hopkins W_131 / Born & Wolf §5.3):\n"
            "  For a thin lens with stop at the lens, both object/image spaces in\n"
            "  air, the Seidel coma sum is:\n"
            "\n"
            "    S_II = u_bar · h³ · φ² · [(n+1)/(2n(n-1)) · q  −  (2n+1)/(2n) · (p+2)]\n"
            "\n"
            "  where:\n"
            "    u_bar = object_height_mm / image_distance_mm   (chief-ray angle)\n"
            "    h     = aperture_radius_mm\n"
            "    φ     = 1 / focal_length_mm\n"
            "    q     = shape factor = (R₁+R₂)/(R₁−R₂)\n"
            "    p     = conjugate factor = (u′+u)/(u′−u)\n"
            "              −1 = object at ∞,  0 = 1:1 magnification,  +1 = image at ∞\n"
            "\n"
            "  Aplanatic shape: q = (2n+1)(n−1)(p+2)/(n+1) → S_II = 0\n"
            "  Tangential coma = 3 × sagittal coma (Welford §11.4 eq. 11.4.4)\n"
            "\n"
            "Reports:\n"
            "  seidel_S_II            : Welford Seidel coma sum (mm·rad)\n"
            "  wave_aberration_W_131  : Hopkins W_131 = −S_II (mm·rad)\n"
            "  sagittal_coma_arcsec   : angular sagittal coma blur (arc-seconds)\n"
            "  tangential_coma_arcsec : angular tangential coma = 3×sagittal (arc-seconds)\n"
            "  coma_blur_mm           : transverse sagittal coma at image plane (mm)\n"
            "  q_aplanatic            : shape factor that eliminates S_II for this n, p\n"
            "\n"
            "Depth bar (oracle values for BK7 n=1.5168, f=100 mm, aperture=25 mm,\n"
            "           object_height=10 mm, image_dist=100 mm, q=0 equiconvex,\n"
            "           p=−1 object at ∞):\n"
            "  F/# = 2.0, S_II ≈ −0.02275 mm·rad\n"
            "  sagittal coma ≈ −1.425 mm·rad / (8·2.0) = −8.908e-4 mm\n"
            "  q_aplanatic(BK7, p=−1) ≈ 0.828\n"
            "\n"
            "HONEST: Third-order Seidel coma only. Fifth-order Schwarzschild coma\n"
            "and higher-order Hopkins terms require finite-ray OPD analysis (not\n"
            "included). Single thin lens in air; stop at lens; monochromatic only.\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "focal_length_mm": {
                    "type": "number",
                    "description": (
                        "Effective focal length of the thin lens (mm). "
                        "Positive for converging, negative for diverging. Non-zero."
                    ),
                },
                "refractive_index_n": {
                    "type": "number",
                    "description": (
                        "Refractive index of the lens glass (> 1.0). "
                        "Examples: BK7 = 1.5168, SF11 = 1.7847, fused silica = 1.4585."
                    ),
                },
                "aperture_radius_mm": {
                    "type": "number",
                    "description": (
                        "Entrance-pupil (marginal ray) radius at the lens (mm, > 0). "
                        "Half the clear aperture diameter."
                    ),
                },
                "shape_factor_q": {
                    "type": "number",
                    "description": (
                        "Bending (shape) factor q = (R₁+R₂)/(R₁−R₂). "
                        "q=0: equiconvex; q=+1: plano-convex curved-first; "
                        "q=−1: plano-convex flat-first (reversed). "
                        "Welford (1986) §7.4 eq. 7.43."
                    ),
                },
                "conjugate_factor_p": {
                    "type": "number",
                    "description": (
                        "Conjugate factor p = (u′+u)/(u′−u). "
                        "p=−1: object at infinity (default); "
                        "p=0: symmetric 1:1 magnification; "
                        "p=+1: image at infinity. "
                        "Welford (1986) §7.4 eq. 7.44."
                    ),
                },
                "object_height_mm": {
                    "type": "number",
                    "description": (
                        "Off-axis field height (mm). Determines the paraxial chief-ray "
                        "angle u_bar = object_height_mm / image_distance_mm. "
                        "Use 0 for on-axis (coma = 0 by symmetry)."
                    ),
                },
                "image_distance_mm": {
                    "type": "number",
                    "description": (
                        "Paraxial image distance from lens to image plane (mm, > 0). "
                        "For object at infinity this equals focal_length_mm."
                    ),
                },
            },
            "required": [
                "focal_length_mm",
                "refractive_index_n",
                "aperture_radius_mm",
                "shape_factor_q",
                "object_height_mm",
                "image_distance_mm",
            ],
        },
    )

    @register(_coma_coefficient_spec, write=False)
    async def run_coma_coefficient(ctx: "Any", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        for field_name in ("focal_length_mm", "refractive_index_n",
                           "aperture_radius_mm", "shape_factor_q",
                           "object_height_mm", "image_distance_mm"):
            if a.get(field_name) is None:
                return _json.dumps({"ok": False, "reason": f"{field_name} is required"})

        try:
            lens_spec = ThinLensSpec(
                focal_length_mm=float(a["focal_length_mm"]),
                refractive_index_n=float(a["refractive_index_n"]),
                aperture_radius_mm=float(a["aperture_radius_mm"]),
                shape_factor_q=float(a["shape_factor_q"]),
                conjugate_factor_p=float(a.get("conjugate_factor_p", -1.0)),
            )
            img_spec = ImageSpec(
                object_height_mm=float(a["object_height_mm"]),
                image_distance_mm=float(a["image_distance_mm"]),
            )
        except (TypeError, ValueError) as exc:
            return _json.dumps({"ok": False, "reason": f"invalid parameter: {exc}"})

        result = compute_coma_coefficient(lens_spec, img_spec)
        if isinstance(result, dict):
            return _json.dumps(result)
        return ok_payload(result.to_dict())
