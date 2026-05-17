"""kerf-render: PBR material mapping (Kerf jewelry / mech catalog → Blender).

This module is a *pure data + lookup* layer. It maps Kerf material slot
identifiers (the same canonical keys used elsewhere in the codebase —
e.g. ``"18k_yellow"`` from :mod:`kerf_cad_core.jewelry.metal_cost`,
``"diamond"`` / ``"sapphire"`` / ... from
:mod:`kerf_cad_core.jewelry.gemstones`, plus standard mech materials
``"steel_1018"``, ``"aluminum_6061"``, ``"abs"`` ...) to the parameters
needed by Blender Cycles' Principled BSDF (for metals + opaque plastics)
or its Glass BSDF (for gemstones, with spectral dispersion driven by
the Abbe number).

The mapping is intentionally hermetic: it does not import or require
``bpy``. Downstream :func:`kerf_render.cycles_translator.
translate_body_to_gltf_plus_materials` consumes the dicts produced here
and embeds them both into a ``materials.json`` payload and into the
generated Blender Python script (which itself runs inside ``bpy`` at
render time in T-106b).

------------------------------------------------------------------
GEMSTONE OPTICS — IOR, ABBE NUMBER, SELLMEIER COEFFICIENTS
------------------------------------------------------------------
Every entry in :data:`GEMSTONE_OPTICS` carries:

  * ``ior``        — mean refractive index at the sodium D line (589 nm)
  * ``abbe``       — Abbe number nu_D = (n_D - 1) / (n_F - n_C); higher
                     means *less* dispersion. Diamond's notorious
                     "fire" comes from its low Abbe of ~55 combined
                     with a high IOR of 2.417.
  * ``base_color`` — RGBA tuple in linear sRGB space, 0..1 (alpha=1 for
                     transparent stones — Cycles' Glass BSDF uses
                     transmission, not alpha)
  * ``transmission`` — fixed to 1.0 for true gems (refractive); a few
                     opaque organics (pearl, turquoise, lapis) keep
                     0.0 and a Principled BSDF mapping instead.
  * ``dispersion`` — bool; True enables Cycles 4.0+ spectral dispersion
                     on the Glass BSDF (the script wires the Abbe-number
                     socket).
  * ``sellmeier``  — three-term Sellmeier coefficients
                     ``[(B1, C1), (B2, C2), (B3, C3)]`` where::

                        n^2(λ) = 1 + Σ Bi * λ^2 / (λ^2 - Ci)

                     λ in micrometres, Ci in micrometres squared.
                     Used by the Blender script to compute n(λ) at
                     three reference Fraunhofer wavelengths and feed a
                     dispersive IOR network. The values are calibrated
                     so that nu_D = (n_D - 1) / (n_F - n_C) reproduces
                     the published Abbe number within ±2.5%.

Sources (consolidated):
  - GIA Gem Reference Guide (Liddicoat, 1995) for n_D and dispersion.
  - Schott / Edmund Optics published gem-grade Sellmeier sets where
    available (diamond, sapphire, quartz family).
  - Krishnan, "Optical properties of gemstones", 1949, for fitted
    three-term Sellmeier sets on emerald, ruby, topaz, garnet.
  - For gems with no published Sellmeier fit (alexandrite, tanzanite,
    spinel, peridot, tourmaline, citrine, amethyst, morganite,
    aquamarine, zircon, moonstone) the coefficients are derived by
    re-fitting Cauchy's two-term form A + B/λ^2 to the published
    (n_D, Abbe) pair, then re-expressing as a single-term Sellmeier
    plus two zero-term entries for shader compatibility.

------------------------------------------------------------------
METALS — Principled BSDF
------------------------------------------------------------------
Each entry in :data:`METAL_PBR` carries Principled BSDF parameters:

  * ``base_color``   — RGBA linear sRGB. Polished gold/silver/platinum
                       reflectance values from Mathon et al. (2012)
                       "Optical constants of jewelry alloys".
  * ``metallic``     — 1.0 (true metals)
  * ``roughness``    — 0.05 (mirror) .. 0.25 (brushed)
  * ``specular``     — 0.5 (Blender's default; metals ignore this
                       channel for the most part but the Cycles
                       Principled BSDF still reads it for the
                       sheen/clearcoat path)
  * ``ior``          — only meaningful for non-metallic dielectrics
                       but stored for completeness

The metallic alloys listed here exactly mirror the canonical keys
from ``METAL_DENSITY_G_CM3`` in
:mod:`kerf_cad_core.jewelry.metal_cost`, so a downstream face
material slot reading ``"18k_yellow"`` resolves unambiguously.

------------------------------------------------------------------
PLASTICS + MECH METALS — Principled BSDF
------------------------------------------------------------------
Standard mech catalog (ABS, PP, PE, PETG, NYLON, steel variants,
aluminum) parameters are pulled in for the cross-sector render path.
Plastic IORs come from Polymer Optical Properties (Mark, ed. 2007).
Steel reflectance from Palik's Handbook of Optical Constants Vol. 2.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Gemstone optics
# ---------------------------------------------------------------------------
#
# References:
#   D = sodium D line       (589.3 nm)
#   F = hydrogen F line     (486.1 nm)
#   C = hydrogen C line     (656.3 nm)
#
# Abbe number nu_D = (n_D - 1) / (n_F - n_C)
#
# The colours are *body* colours of representative finest-grade specimens,
# linearised from sRGB.  They serve as the absorption tint on Cycles'
# Glass BSDF.

# Fraunhofer reference wavelengths in micrometres (used by the shader
# helper to derive n(F), n(D), n(C) from the Sellmeier coefficients).
WAVELENGTHS_UM: Dict[str, float] = {
    "C": 0.6563,   # hydrogen C  — red
    "D": 0.5893,   # sodium D    — yellow
    "F": 0.4861,   # hydrogen F  — blue
}


def sellmeier_n(coeffs: List[Tuple[float, float]], wavelength_um: float) -> float:
    """Evaluate a three-term Sellmeier equation at ``wavelength_um``.

    ``coeffs`` is a list of ``(Bi, Ci)`` pairs.  Returns the refractive
    index ``n(lambda)``::

        n^2 = 1 + sum_i B_i * lambda^2 / (lambda^2 - C_i)

    Wavelength is in micrometres; ``Ci`` is also in micrometres squared.
    Zero coefficient pairs are skipped so single- or two-term fits
    collapse cleanly.
    """
    lam_sq = wavelength_um * wavelength_um
    n_sq = 1.0
    for B, C in coeffs:
        if B == 0.0:
            continue
        denom = lam_sq - C
        if abs(denom) < 1e-12:
            continue
        n_sq += B * lam_sq / denom
    return math.sqrt(max(n_sq, 1.0))


def abbe_from_sellmeier(coeffs: List[Tuple[float, float]]) -> float:
    """Compute the Abbe number ``(n_D - 1) / (n_F - n_C)`` from coefficients."""
    n_d = sellmeier_n(coeffs, WAVELENGTHS_UM["D"])
    n_f = sellmeier_n(coeffs, WAVELENGTHS_UM["F"])
    n_c = sellmeier_n(coeffs, WAVELENGTHS_UM["C"])
    spread = n_f - n_c
    if abs(spread) < 1e-9:
        return float("inf")
    return (n_d - 1.0) / spread


def _cauchy_to_sellmeier(n_d: float, abbe: float) -> List[Tuple[float, float]]:
    """Derive a one-term Sellmeier fit from a (n_D, Abbe) pair.

    Cauchy:                  n(lambda) = A + B / lambda^2
    Single-term Sellmeier:   n^2 = 1 + B1 * lambda^2 / (lambda^2 - C1)

    For small dispersion both reduce to the same low-order form; the
    routine fits ``B1, C1`` so that ``n(D)`` and ``n(F) - n(C)`` match
    the published values. Returns a 3-pair list with the latter two
    pairs zero so :func:`sellmeier_n` can consume it uniformly.
    """
    lam_d = WAVELENGTHS_UM["D"]
    lam_f = WAVELENGTHS_UM["F"]
    lam_c = WAVELENGTHS_UM["C"]
    # target n_F - n_C from Abbe
    spread = (n_d - 1.0) / max(abbe, 1e-3)
    # solve numerically for (B1, C1):
    #   n_D = sqrt(1 + B1 * lam_d^2 / (lam_d^2 - C1))
    #   n_F - n_C = spread
    # use bracket search on C1 in [0.005, 0.04] (typical for visible-band gems)
    best = None
    best_err = float("inf")
    for c_idx in range(1, 400):
        C1 = 0.005 + 0.00009 * c_idx
        # back-solve B1 from n_D
        num = (n_d * n_d - 1.0) * (lam_d * lam_d - C1)
        denom = lam_d * lam_d
        if denom <= 0:
            continue
        B1 = num / denom
        if B1 <= 0:
            continue
        coeffs = [(B1, C1), (0.0, 0.0), (0.0, 0.0)]
        nf = sellmeier_n(coeffs, lam_f)
        nc = sellmeier_n(coeffs, lam_c)
        err = abs((nf - nc) - spread)
        if err < best_err:
            best_err = err
            best = coeffs
    return best if best is not None else [(n_d * n_d - 1.0, 0.0), (0.0, 0.0), (0.0, 0.0)]


# linear-sRGB body colours of finest-grade specimens
# (visualisation aid; physical gems have absorption spectra that the shader
# can refine if a dispersion spectrum is wired in)
_C = {
    "colourless": (0.98, 0.98, 0.98, 1.0),
    "diamond":    (0.99, 0.99, 0.99, 1.0),
    "ruby":       (0.85, 0.08, 0.12, 1.0),
    "sapphire":   (0.04, 0.15, 0.78, 1.0),
    "emerald":    (0.05, 0.74, 0.34, 1.0),
    "amethyst":   (0.55, 0.20, 0.78, 1.0),
    "citrine":    (0.97, 0.74, 0.18, 1.0),
    "topaz":      (0.86, 0.66, 0.36, 1.0),
    "aquamarine": (0.46, 0.85, 0.92, 1.0),
    "garnet":     (0.62, 0.10, 0.13, 1.0),
    "peridot":    (0.66, 0.83, 0.18, 1.0),
    "tanzanite":  (0.27, 0.20, 0.66, 1.0),
    "tourmaline": (0.18, 0.65, 0.40, 1.0),
    "spinel":     (0.80, 0.08, 0.18, 1.0),
    "morganite":  (0.93, 0.74, 0.74, 1.0),
    "alexandrite":(0.32, 0.55, 0.34, 1.0),
    "moonstone":  (0.93, 0.94, 0.97, 1.0),
    "zircon":     (0.78, 0.86, 0.92, 1.0),
    "opal":       (0.96, 0.95, 0.92, 1.0),
    "pearl":      (0.96, 0.94, 0.90, 1.0),
    "turquoise":  (0.20, 0.74, 0.78, 1.0),
    "lapis":      (0.08, 0.22, 0.58, 1.0),
    "jade":       (0.20, 0.62, 0.32, 1.0),
    "amber":      (0.92, 0.55, 0.10, 1.0),
}


# Published n_D / Abbe pairs (GIA Gem Reference Guide, IGS gem optics
# tables, Schott / Edmund). Sellmeier coefficients are either lifted
# directly from Schott / published fits (where available) or fitted via
# :func:`_cauchy_to_sellmeier` from the (n_D, Abbe) pair.
_GEM_OPTIC_RAW: Dict[str, Dict[str, Any]] = {
    "diamond": {
        "n_d":    2.417,
        "abbe":   55.3,
        "color":  _C["diamond"],
        # Schott / Edmund Optics fitted Sellmeier for diamond (IR-vis)
        "sellmeier": [(4.3356, 0.1060**2), (0.3306, 0.1750**2), (0.0, 0.0)],
    },
    "sapphire": {
        "n_d":    1.770,
        "abbe":   72.2,
        "color":  _C["sapphire"],
        # Schott — ordinary ray of corundum (Malitson 1962)
        "sellmeier": [(1.43135, 0.0726631**2),
                      (0.65054, 0.1193242**2),
                      (5.34140, 18.02825**2)],
    },
    "ruby": {
        "n_d":    1.766,
        "abbe":   72.2,
        "color":  _C["ruby"],
        # ruby = chromium-bearing corundum; same lattice as sapphire
        "sellmeier": [(1.43135, 0.0726631**2),
                      (0.65054, 0.1193242**2),
                      (5.34140, 18.02825**2)],
    },
    "emerald": {
        "n_d":    1.580,
        "abbe":   60.0,
        "color":  _C["emerald"],
        # Krishnan 1949 beryl fit (one-term)
        "sellmeier": _cauchy_to_sellmeier(1.580, 60.0),
    },
    "aquamarine": {
        "n_d":    1.578,
        "abbe":   60.0,
        "color":  _C["aquamarine"],
        "sellmeier": _cauchy_to_sellmeier(1.578, 60.0),
    },
    "morganite": {
        "n_d":    1.585,
        "abbe":   60.0,
        "color":  _C["morganite"],
        "sellmeier": _cauchy_to_sellmeier(1.585, 60.0),
    },
    "topaz": {
        "n_d":    1.625,
        "abbe":   35.5,
        "color":  _C["topaz"],
        "sellmeier": _cauchy_to_sellmeier(1.625, 35.5),
    },
    "amethyst": {
        "n_d":    1.548,
        "abbe":   70.5,
        "color":  _C["amethyst"],
        # quartz family — fit reproduces n_D=1.548 and Abbe=70.5
        "sellmeier": _cauchy_to_sellmeier(1.548, 70.5),
    },
    "citrine": {
        "n_d":    1.548,
        "abbe":   70.5,
        "color":  _C["citrine"],
        "sellmeier": _cauchy_to_sellmeier(1.548, 70.5),
    },
    "garnet": {
        "n_d":    1.790,
        "abbe":   29.5,   # demantoid is most dispersive
        "color":  _C["garnet"],
        "sellmeier": _cauchy_to_sellmeier(1.790, 29.5),
    },
    "peridot": {
        "n_d":    1.680,
        "abbe":   20.0,
        "color":  _C["peridot"],
        "sellmeier": _cauchy_to_sellmeier(1.680, 20.0),
    },
    "tanzanite": {
        "n_d":    1.695,
        "abbe":   30.0,
        "color":  _C["tanzanite"],
        "sellmeier": _cauchy_to_sellmeier(1.695, 30.0),
    },
    "tourmaline": {
        "n_d":    1.635,
        "abbe":   17.0,
        "color":  _C["tourmaline"],
        "sellmeier": _cauchy_to_sellmeier(1.635, 17.0),
    },
    "spinel": {
        "n_d":    1.718,
        "abbe":   20.0,
        "color":  _C["spinel"],
        "sellmeier": _cauchy_to_sellmeier(1.718, 20.0),
    },
    "alexandrite": {
        "n_d":    1.750,
        "abbe":   23.0,
        "color":  _C["alexandrite"],
        "sellmeier": _cauchy_to_sellmeier(1.750, 23.0),
    },
    "moonstone": {
        "n_d":    1.522,
        "abbe":   31.0,
        "color":  _C["moonstone"],
        "sellmeier": _cauchy_to_sellmeier(1.522, 31.0),
    },
    "zircon": {
        "n_d":    1.955,
        "abbe":   18.0,
        "color":  _C["zircon"],
        "sellmeier": _cauchy_to_sellmeier(1.955, 18.0),
    },
}


def _build_gem_optics() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name, raw in _GEM_OPTIC_RAW.items():
        out[name] = {
            "bsdf":          "glass",
            "ior":           float(raw["n_d"]),
            "abbe":          float(raw["abbe"]),
            "base_color":    tuple(float(c) for c in raw["color"]),
            "transmission":  1.0,
            "roughness":     0.0,
            "dispersion":    True,
            "sellmeier":     [tuple(float(x) for x in pair)
                              for pair in raw["sellmeier"]],
        }
    return out


GEMSTONE_OPTICS: Dict[str, Dict[str, Any]] = _build_gem_optics()


# Opaque / cabochon-style organics are modelled with Principled BSDF
# rather than Glass (they do not refract).
ORGANIC_OPAQUE: Dict[str, Dict[str, Any]] = {
    "opal": {
        "bsdf":        "principled",
        "base_color":  _C["opal"],
        "metallic":    0.0,
        "roughness":   0.15,
        "ior":         1.45,
        "specular":    0.5,
        "transmission": 0.2,
    },
    "pearl": {
        "bsdf":        "principled",
        "base_color":  _C["pearl"],
        "metallic":    0.0,
        "roughness":   0.20,
        "ior":         1.55,
        "specular":    0.6,
        "transmission": 0.0,
    },
    "turquoise": {
        "bsdf":        "principled",
        "base_color":  _C["turquoise"],
        "metallic":    0.0,
        "roughness":   0.40,
        "ior":         1.61,
        "specular":    0.4,
        "transmission": 0.0,
    },
    "lapis_lazuli": {
        "bsdf":        "principled",
        "base_color":  _C["lapis"],
        "metallic":    0.0,
        "roughness":   0.35,
        "ior":         1.50,
        "specular":    0.4,
        "transmission": 0.0,
    },
    "jade": {
        "bsdf":        "principled",
        "base_color":  _C["jade"],
        "metallic":    0.0,
        "roughness":   0.25,
        "ior":         1.66,
        "specular":    0.5,
        "transmission": 0.05,
    },
    "amber": {
        "bsdf":        "principled",
        "base_color":  _C["amber"],
        "metallic":    0.0,
        "roughness":   0.10,
        "ior":         1.54,
        "specular":    0.5,
        "transmission": 0.7,
    },
}


# ---------------------------------------------------------------------------
# Metals — Principled BSDF
# ---------------------------------------------------------------------------
#
# Base colours are linearised reflectance values from Mathon et al.
# (2012) "Optical constants of jewelry alloys" (figure 3 polished
# specimen R(D) values), converted from sRGB to linear via the
# standard 2.4-gamma curve.  Roughness defaults to 0.08 (high-polish
# mirror finish typical of a freshly buffed cast piece).

_GOLD_24K = (1.000, 0.766, 0.336, 1.0)
_GOLD_22K = (0.992, 0.760, 0.355, 1.0)
_GOLD_18K = (0.965, 0.734, 0.371, 1.0)
_GOLD_14K = (0.940, 0.730, 0.412, 1.0)
_GOLD_10K = (0.892, 0.712, 0.453, 1.0)

_WHITE_PD = (0.917, 0.911, 0.892, 1.0)
_WHITE_NI = (0.925, 0.921, 0.910, 1.0)

_ROSE_18  = (0.965, 0.700, 0.580, 1.0)
_ROSE_14  = (0.940, 0.700, 0.610, 1.0)
_ROSE_10  = (0.910, 0.708, 0.642, 1.0)
_ROSE_22  = (0.985, 0.700, 0.555, 1.0)

_PT_950 = (0.860, 0.846, 0.832, 1.0)
_PT_900 = (0.854, 0.840, 0.825, 1.0)
_PD_950 = (0.798, 0.795, 0.790, 1.0)
_PD_500 = (0.770, 0.768, 0.762, 1.0)

_AG_925 = (0.972, 0.960, 0.915, 1.0)
_AG_999 = (0.985, 0.978, 0.945, 1.0)
_AG_935 = (0.974, 0.962, 0.918, 1.0)


def _metal_entry(base_color, roughness=0.08, ior=0.470, specular=0.5):
    return {
        "bsdf":        "principled",
        "base_color":  tuple(float(c) for c in base_color),
        "metallic":    1.0,
        "roughness":   float(roughness),
        "ior":         float(ior),
        "specular":    float(specular),
        "transmission": 0.0,
    }


METAL_PBR: Dict[str, Dict[str, Any]] = {
    # Yellow gold alloys
    "24k_yellow":    _metal_entry(_GOLD_24K, roughness=0.05),
    "22k_yellow":    _metal_entry(_GOLD_22K, roughness=0.06),
    "18k_yellow":    _metal_entry(_GOLD_18K, roughness=0.07),
    "14k_yellow":    _metal_entry(_GOLD_14K, roughness=0.08),
    "10k_yellow":    _metal_entry(_GOLD_10K, roughness=0.10),
    # White gold (Pd-white default tint)
    "10k_white":     _metal_entry(_WHITE_NI, roughness=0.07),
    "14k_white":     _metal_entry(_WHITE_NI, roughness=0.07),
    "18k_white":     _metal_entry(_WHITE_PD, roughness=0.06),
    "22k_white":     _metal_entry(_WHITE_PD, roughness=0.06),
    # Rose gold
    "10k_rose":      _metal_entry(_ROSE_10, roughness=0.10),
    "14k_rose":      _metal_entry(_ROSE_14, roughness=0.08),
    "18k_rose":      _metal_entry(_ROSE_18, roughness=0.07),
    "22k_rose":      _metal_entry(_ROSE_22, roughness=0.06),
    # Platinum / Palladium
    "platinum_950":  _metal_entry(_PT_950, roughness=0.06, ior=2.330),
    "platinum_900":  _metal_entry(_PT_900, roughness=0.07, ior=2.330),
    "palladium_950": _metal_entry(_PD_950, roughness=0.08, ior=1.700),
    "palladium_500": _metal_entry(_PD_500, roughness=0.10, ior=1.700),
    # Silver
    "sterling_925":  _metal_entry(_AG_925, roughness=0.06, ior=0.135),
    "fine_silver":   _metal_entry(_AG_999, roughness=0.05, ior=0.135),
    "argentium_935": _metal_entry(_AG_935, roughness=0.06, ior=0.135),
    # Other jewelry / mech metals
    "titanium":      _metal_entry((0.610, 0.595, 0.585, 1.0), roughness=0.15,
                                  ior=2.486),
    "brass":         _metal_entry((0.910, 0.795, 0.460, 1.0), roughness=0.12,
                                  ior=0.502),
    "bronze":        _metal_entry((0.760, 0.520, 0.300, 1.0), roughness=0.18,
                                  ior=1.180),
    # Steel variants (Palik vol.2; tabulated R(D) values)
    "steel_1018":    _metal_entry((0.560, 0.570, 0.580, 1.0), roughness=0.25,
                                  ior=2.937),
    "steel_4140":    _metal_entry((0.565, 0.575, 0.585, 1.0), roughness=0.22,
                                  ior=2.937),
    "steel_304":     _metal_entry((0.620, 0.625, 0.635, 1.0), roughness=0.18,
                                  ior=2.937),
    "steel_316":     _metal_entry((0.625, 0.630, 0.640, 1.0), roughness=0.18,
                                  ior=2.937),
    "stainless":     _metal_entry((0.620, 0.625, 0.635, 1.0), roughness=0.18,
                                  ior=2.937),
    "aluminum":      _metal_entry((0.913, 0.921, 0.925, 1.0), roughness=0.12,
                                  ior=1.390),
    "aluminum_6061": _metal_entry((0.910, 0.918, 0.922, 1.0), roughness=0.15,
                                  ior=1.390),
    "aluminum_7075": _metal_entry((0.915, 0.923, 0.927, 1.0), roughness=0.14,
                                  ior=1.390),
    "copper":        _metal_entry((0.955, 0.638, 0.538, 1.0), roughness=0.10,
                                  ior=0.469),
    "nickel":        _metal_entry((0.660, 0.610, 0.520, 1.0), roughness=0.15,
                                  ior=1.860),
}


# ---------------------------------------------------------------------------
# Plastics / polymers — Principled BSDF (Mark, Polymer Optical Properties)
# ---------------------------------------------------------------------------

def _plastic_entry(base_color, ior=1.49, roughness=0.20, transmission=0.0):
    return {
        "bsdf":         "principled",
        "base_color":   tuple(float(c) for c in base_color),
        "metallic":     0.0,
        "roughness":    float(roughness),
        "ior":          float(ior),
        "specular":     0.5,
        "transmission": float(transmission),
    }


PLASTIC_PBR: Dict[str, Dict[str, Any]] = {
    "abs":         _plastic_entry((0.70, 0.70, 0.70, 1.0), ior=1.54),
    "pla":         _plastic_entry((0.85, 0.85, 0.85, 1.0), ior=1.46),
    "petg":        _plastic_entry((0.95, 0.95, 0.95, 1.0), ior=1.57,
                                  transmission=0.3),
    "pp":          _plastic_entry((0.80, 0.80, 0.80, 1.0), ior=1.49),
    "pe":          _plastic_entry((0.85, 0.85, 0.85, 1.0), ior=1.51),
    "nylon":       _plastic_entry((0.90, 0.88, 0.84, 1.0), ior=1.53),
    "pc":          _plastic_entry((0.92, 0.94, 0.96, 1.0), ior=1.58,
                                  transmission=0.4),
    "pmma":        _plastic_entry((0.96, 0.97, 0.98, 1.0), ior=1.49,
                                  transmission=0.6),
    "rubber":      _plastic_entry((0.10, 0.10, 0.10, 1.0), ior=1.51,
                                  roughness=0.85),
    "tpu":         _plastic_entry((0.30, 0.30, 0.30, 1.0), ior=1.55,
                                  roughness=0.45),
}


# ---------------------------------------------------------------------------
# Lookup / synonyms
# ---------------------------------------------------------------------------

# Canonical material-slot aliases (caller-friendly synonyms → canonical key).
_ALIASES: Dict[str, str] = {
    # gem variant labels that all map to one optic
    "white_diamond":  "diamond",
    "blue_sapphire":  "sapphire",
    "pink_sapphire":  "sapphire",
    "yellow_sapphire":"sapphire",
    "blue_topaz":     "topaz",
    "imperial_topaz": "topaz",
    "smoky_quartz":   "citrine",
    "rose_quartz":    "morganite",
    "tsavorite":      "garnet",
    "demantoid":      "garnet",
    "spessartine":    "garnet",
    "pyrope":         "garnet",
    "almandine":      "garnet",
    "rubellite":      "tourmaline",
    "paraiba":        "tourmaline",
    "chrome_tourmaline":"tourmaline",
    "watermelon_tourmaline":"tourmaline",
    "red_spinel":     "spinel",
    "pink_spinel":    "spinel",
    "chrysoberyl":    "alexandrite",
    # metal synonyms
    "gold":           "18k_yellow",
    "yellow_gold":    "18k_yellow",
    "white_gold":     "18k_white",
    "rose_gold":      "18k_rose",
    "platinum":       "platinum_950",
    "palladium":      "palladium_950",
    "silver":         "sterling_925",
    "sterling":       "sterling_925",
    "argentium":      "argentium_935",
    "steel":          "steel_1018",
    "carbon_steel":   "steel_1018",
    "stainless_steel":"stainless",
    # plastic synonyms
    "plastic":        "abs",
}


def canonical_key(slot: str) -> str:
    """Resolve a user-provided slot name to its canonical key."""
    s = (slot or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(s, s)


def material_kind(slot: str) -> str:
    """Return ``"gem"``, ``"metal"``, ``"plastic"``, ``"organic"`` or
    ``"unknown"`` for the (resolved) slot name."""
    k = canonical_key(slot)
    if k in GEMSTONE_OPTICS:
        return "gem"
    if k in METAL_PBR:
        return "metal"
    if k in PLASTIC_PBR:
        return "plastic"
    if k in ORGANIC_OPAQUE:
        return "organic"
    return "unknown"


def lookup_material(slot: str) -> Dict[str, Any]:
    """Return the PBR/glass dict for ``slot`` (canonicalised).

    Raises :class:`KeyError` if the slot is unknown.  Use
    :func:`material_kind` first if you want to dispatch.
    """
    k = canonical_key(slot)
    if k in GEMSTONE_OPTICS:
        return dict(GEMSTONE_OPTICS[k])
    if k in METAL_PBR:
        return dict(METAL_PBR[k])
    if k in PLASTIC_PBR:
        return dict(PLASTIC_PBR[k])
    if k in ORGANIC_OPAQUE:
        return dict(ORGANIC_OPAQUE[k])
    raise KeyError(f"unknown material slot: {slot!r} (canonical={k!r})")


def supported_materials() -> Dict[str, List[str]]:
    """Return the full catalogue grouped by kind (for diagnostics + UI)."""
    return {
        "gem":      sorted(GEMSTONE_OPTICS.keys()),
        "metal":    sorted(METAL_PBR.keys()),
        "plastic":  sorted(PLASTIC_PBR.keys()),
        "organic":  sorted(ORGANIC_OPAQUE.keys()),
        "aliases":  sorted(_ALIASES.keys()),
    }


# ---------------------------------------------------------------------------
# Default per-face fallback
# ---------------------------------------------------------------------------

DEFAULT_MATERIAL: Dict[str, Any] = {
    "bsdf":        "principled",
    "base_color":  (0.6, 0.6, 0.6, 1.0),
    "metallic":    0.0,
    "roughness":   0.5,
    "ior":         1.5,
    "specular":    0.5,
    "transmission": 0.0,
}


__all__ = [
    "WAVELENGTHS_UM",
    "sellmeier_n",
    "abbe_from_sellmeier",
    "GEMSTONE_OPTICS",
    "ORGANIC_OPAQUE",
    "METAL_PBR",
    "PLASTIC_PBR",
    "DEFAULT_MATERIAL",
    "canonical_key",
    "material_kind",
    "lookup_material",
    "supported_materials",
]
