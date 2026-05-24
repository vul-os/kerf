"""
kerf_cad_core.gearbox.planetary — Planetary / epicyclic gearbox design.

Implements:
  - Single-stage planetary (sun + planets + ring + carrier)
  - Three operating modes (carrier-output, ring-output, sun-output)
  - Efficiency via torque method
  - Compound (stacked) planetary for two-stage compositions
  - Module/tooth-count sizing helper

Terminology
-----------
sun     — central sun gear (Z_sun teeth)
planet  — planet gears (Z_planet teeth each), N_planets of them
ring    — internal ring gear (Z_ring teeth), sometimes called annulus
carrier — the spider/arm that holds the planet axles

Fundamental constraint (pitch-circle geometry):
    Z_ring = Z_sun + 2·Z_planet

Assembly constraint (equal-spaced planets must mesh simultaneously):
    (Z_sun + Z_ring) / N_planets  ∈  ℤ

Operating modes
---------------
  a) CARRIER_OUTPUT  — carrier is output, ring is fixed (grounded)
       ratio = n_in / n_out = 1 + Z_ring / Z_sun  (>1, reduction)
  b) RING_OUTPUT     — ring is output, carrier is fixed (grounded)
       ratio = n_in / n_out = -Z_ring / Z_sun  (negative = reversal)
  c) SUN_OUTPUT      — sun is output, ring is fixed (input on carrier)
       ratio = n_in / n_out = Z_sun / (Z_sun + Z_ring)  (<1, step-up)

Torque sum on a 3-port epicyclic:
    T_sun + T_ring + T_carrier = 0  (Willys–Ravigneaux identity)

Efficiency — torque method (Müller, 1982):
    The torque on the fixed member must be supplied by the frame.
    Power loss = |T_fixed| · |ω_fixed_if_free| · (1 - η_mesh)
    For CARRIER_OUTPUT (ring fixed):
        η = 1 - (1 - η_mesh²) · Z_ring / (Z_sun + Z_ring)
    For RING_OUTPUT (carrier fixed):
        η = η_mesh²  (two meshing pairs, both active)
    For SUN_OUTPUT (ring fixed, carrier driving):
        η = (Z_sun + Z_ring) / (Z_sun + Z_ring / η_mesh²)  ← approximate

References
----------
Müller, H.W. (1982) Epicyclic Drive Trains. Wayne State U. Press.
Shigley's MED (10th ed.) §13-7 Planetary Gear Trains.
Lynwander, P. (1983) Gear Drive Systems §6.

Author: imranparuk
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ETA_MESH_DEFAULT = 0.98   # per-mesh efficiency for ground spur gears
_Z_MIN = 3                 # absolute minimum tooth count


# ---------------------------------------------------------------------------
# Constraint helpers
# ---------------------------------------------------------------------------

def _check_tooth_constraint(Z_sun: int, Z_planet: int, Z_ring: int) -> list[str]:
    """
    Verify Z_ring == Z_sun + 2·Z_planet.

    Returns a list of error strings (empty means OK).
    """
    expected = Z_sun + 2 * Z_planet
    if Z_ring != expected:
        return [
            f"Tooth-count constraint violated: Z_ring={Z_ring} != "
            f"Z_sun + 2·Z_planet = {Z_sun} + 2·{Z_planet} = {expected}. "
            "All gears must share the same module and pressure angle."
        ]
    return []


def _check_assembly_constraint(Z_sun: int, Z_ring: int, N_planets: int) -> list[str]:
    """
    Verify (Z_sun + Z_ring) / N_planets is an integer.

    Equal-spaced planets can only mesh if the tooth spacing divides evenly.
    Returns a list of error strings (empty means OK).
    """
    if N_planets < 2:
        return [f"N_planets={N_planets} must be >= 2."]
    total = Z_sun + Z_ring
    if total % N_planets != 0:
        return [
            f"Assembly constraint violated: (Z_sun + Z_ring) / N_planets = "
            f"({Z_sun} + {Z_ring}) / {N_planets} = {total / N_planets:.4f} ∉ ℤ. "
            "Planets cannot be equally spaced."
        ]
    return []


# ---------------------------------------------------------------------------
# Efficiency — torque method
# ---------------------------------------------------------------------------

def _efficiency_carrier_output(eta_mesh: float, Z_sun: int, Z_ring: int) -> float:
    """
    Overall efficiency: ring fixed, carrier output (most common automotive mode).

    Derivation (Müller 1982 §3.2):
        ω_carrier / ω_sun = Z_sun / (Z_sun + Z_ring)   [kinematic]
        Power flow passes through two mesh interfaces (sun-planet, planet-ring).
        Loss at each mesh: (1 - η_mesh) of the circulating power.

        η = 1 - (1 - η_mesh²) · Z_ring / (Z_sun + Z_ring)

    This is the standard textbook result for a single-planet-stage with
    fixed ring (Shigley §13-7, Lynwander §6.3).
    """
    return 1.0 - (1.0 - eta_mesh ** 2) * Z_ring / (Z_sun + Z_ring)


def _efficiency_ring_output(eta_mesh: float) -> float:
    """
    Overall efficiency: carrier fixed, ring output.

    Sun drives through planet to ring; both meshes (sun-planet, planet-ring)
    are active. Two serial mesh losses → η_total = η_mesh².
    """
    return eta_mesh ** 2


def _efficiency_sun_output(eta_mesh: float, Z_sun: int, Z_ring: int) -> float:
    """
    Overall efficiency: ring fixed, carrier driving, sun output (speed increase).

    Approximate torque-method result (reciprocal drive of CARRIER_OUTPUT mode):
        η_fwd = _efficiency_carrier_output(η_mesh, Z_sun, Z_ring)
        For back-drive: η_back ≈ (2 - 1/η_fwd) is one common form, but
        the cleaner textbook form for the sun-output mode is:

        η = Z_sun / (Z_sun + Z_ring·(1 - η_mesh²))

    Reference: Müller 1982, eq. (3.19).
    """
    return Z_sun / (Z_sun + Z_ring * (1.0 - eta_mesh ** 2))


# ---------------------------------------------------------------------------
# Single-stage planetary
# ---------------------------------------------------------------------------

_MODE_CARRIER_OUTPUT = "carrier_output"
_MODE_RING_OUTPUT    = "ring_output"
_MODE_SUN_OUTPUT     = "sun_output"

_VALID_MODES = {_MODE_CARRIER_OUTPUT, _MODE_RING_OUTPUT, _MODE_SUN_OUTPUT}


def planetary_stage(
    Z_sun: int,
    Z_planet: int,
    Z_ring: int,
    N_planets: int,
    input_torque_Nm: float,
    mode: str = _MODE_CARRIER_OUTPUT,
    eta_mesh: float = _ETA_MESH_DEFAULT,
) -> dict[str, Any]:
    """
    Analyse a single-stage planetary (epicyclic) gearbox.

    Parameters
    ----------
    Z_sun          : tooth count on the sun gear
    Z_planet       : tooth count on each planet gear
    Z_ring         : tooth count on the ring (annulus) gear
    N_planets      : number of planet gears (>= 2)
    input_torque_Nm: torque at the input member (N·m)
    mode           : operating mode — one of:
                       "carrier_output"  (ring fixed, carrier driven out)
                       "ring_output"     (carrier fixed, ring driven out)
                       "sun_output"      (ring fixed, carrier is input)
    eta_mesh       : per-mesh efficiency (default 0.98)

    Returns
    -------
    dict with keys:
        ok                       bool
        mode                     str
        Z_sun, Z_planet, Z_ring  int
        N_planets                int
        ratio                    float  n_in / n_out (positive = same direction)
        efficiency               float  overall η
        T_sun_Nm                 float  torque on sun gear (N·m)
        T_ring_Nm                float  torque on ring gear (N·m)
        T_carrier_Nm             float  torque on carrier (N·m)
        F_tangential_per_planet_N float  tangential load per planet (N), module=1 basis
        r_sun_mm                 float  sun pitch radius (module=1 basis, mm)
        assembly_integer         int    (Z_sun + Z_ring) / N_planets
        tooth_constraint_ok      bool
        assembly_constraint_ok   bool
        warnings                 list[str]
        errors                   list[str]

    Notes
    -----
    Pitch radius r_sun is given on a module=1 basis.
    To get actual radius for module m: multiply by m.
    F_tangential is likewise on a module=1 basis (T / r_sun).

    Torque signs follow the Willys–Ravigneaux identity:
        T_sun + T_ring + T_carrier = 0
    where the sign encodes direction (positive = driving, negative = reacting).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── Basic validation ───────────────────────────────────────────────────
    for name, val in [("Z_sun", Z_sun), ("Z_planet", Z_planet), ("Z_ring", Z_ring)]:
        if not isinstance(val, int) or val < _Z_MIN:
            errors.append(f"{name}={val!r} must be an integer >= {_Z_MIN}.")
    if not isinstance(N_planets, int) or N_planets < 2:
        errors.append(f"N_planets={N_planets!r} must be an integer >= 2.")
    if not isinstance(input_torque_Nm, (int, float)) or input_torque_Nm <= 0:
        errors.append(f"input_torque_Nm={input_torque_Nm!r} must be > 0.")
    if mode not in _VALID_MODES:
        errors.append(
            f"mode={mode!r} not recognised. "
            f"Valid modes: {sorted(_VALID_MODES)}."
        )
    if not (0 < eta_mesh <= 1.0):
        errors.append(f"eta_mesh={eta_mesh!r} must be in (0, 1].")

    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}

    # ── Fundamental tooth-count constraint ────────────────────────────────
    tc_errs = _check_tooth_constraint(Z_sun, Z_planet, Z_ring)
    assembly_errs = _check_assembly_constraint(Z_sun, Z_ring, N_planets)

    tooth_constraint_ok    = len(tc_errs) == 0
    assembly_constraint_ok = len(assembly_errs) == 0

    errors.extend(tc_errs)
    errors.extend(assembly_errs)

    if errors:
        return {
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "tooth_constraint_ok": tooth_constraint_ok,
            "assembly_constraint_ok": assembly_constraint_ok,
        }

    assembly_integer = (Z_sun + Z_ring) // N_planets

    # ── Gear ratio ─────────────────────────────────────────────────────────
    # Willis / tabular method:
    #   CARRIER_OUTPUT (ring fixed):  i = 1 + Z_ring/Z_sun
    #   RING_OUTPUT (carrier fixed):  i = -Z_ring/Z_sun  (reversal)
    #   SUN_OUTPUT (ring fixed, carrier in): i = Z_sun/(Z_sun+Z_ring)  [<1, step-up]
    if mode == _MODE_CARRIER_OUTPUT:
        ratio = 1.0 + Z_ring / Z_sun
    elif mode == _MODE_RING_OUTPUT:
        ratio = -Z_ring / Z_sun
    else:  # _MODE_SUN_OUTPUT
        ratio = Z_sun / (Z_sun + Z_ring)

    # ── Efficiency ─────────────────────────────────────────────────────────
    if mode == _MODE_CARRIER_OUTPUT:
        eta = _efficiency_carrier_output(eta_mesh, Z_sun, Z_ring)
    elif mode == _MODE_RING_OUTPUT:
        eta = _efficiency_ring_output(eta_mesh)
    else:  # _MODE_SUN_OUTPUT
        eta = _efficiency_sun_output(eta_mesh, Z_sun, Z_ring)

    # ── Torque distribution ────────────────────────────────────────────────
    # We apply the sign convention that the input torque is positive (driving).
    # T_sun + T_ring + T_carrier = 0  (Willys identity)
    #
    # CARRIER_OUTPUT (ring fixed):
    #   input = sun, output = carrier, reaction = ring
    #   T_carrier = -T_sun * (1 + Z_ring/Z_sun) * eta  = -T_sun * ratio * eta
    #   T_ring    = -(T_sun + T_carrier)
    #
    # RING_OUTPUT (carrier fixed):
    #   input = sun, output = ring, reaction = carrier
    #   T_ring    = -T_sun * (Z_ring/Z_sun) * eta
    #   T_carrier = -(T_sun + T_ring)
    #
    # SUN_OUTPUT (ring fixed, carrier driving):
    #   input = carrier, output = sun, reaction = ring
    #   T_sun     = -T_carrier * ratio * eta   where ratio = Z_sun/(Z_sun+Z_ring)
    #   T_ring    = -(T_sun + T_carrier)

    T_in = float(input_torque_Nm)

    if mode == _MODE_CARRIER_OUTPUT:
        T_sun     = T_in
        T_carrier = -T_sun * ratio * eta
        T_ring    = -(T_sun + T_carrier)
    elif mode == _MODE_RING_OUTPUT:
        T_sun     = T_in
        T_ring    = -T_sun * abs(ratio) * eta
        T_carrier = -(T_sun + T_ring)
    else:  # _MODE_SUN_OUTPUT
        T_carrier = T_in
        T_sun     = -T_carrier * ratio * eta
        T_ring    = -(T_sun + T_carrier)

    # Verify torque identity (should be zero to floating-point precision)
    torque_residual = abs(T_sun + T_ring + T_carrier)
    if torque_residual > 1e-9 * abs(T_in):
        warnings.append(
            f"Torque identity residual {torque_residual:.2e} N·m — "
            "rounding may have accumulated."
        )

    # ── Per-planet load (on module=1 basis) ───────────────────────────────
    # r_sun = m · Z_sun / 2; on m=1 basis: r_sun = Z_sun / 2
    r_sun_mm = Z_sun / 2.0
    # F_tang = T_sun / (N_planets · r_sun)
    # Use |T_sun| since we want the magnitude of the load.
    F_tang = abs(T_sun) / (N_planets * r_sun_mm)

    return {
        "ok":                       True,
        "mode":                     mode,
        "Z_sun":                    Z_sun,
        "Z_planet":                 Z_planet,
        "Z_ring":                   Z_ring,
        "N_planets":                N_planets,
        "ratio":                    round(ratio, 10),
        "efficiency":               round(eta, 10),
        "T_sun_Nm":                 round(T_sun, 10),
        "T_ring_Nm":                round(T_ring, 10),
        "T_carrier_Nm":             round(T_carrier, 10),
        "r_sun_mm_per_module":      round(r_sun_mm, 10),
        "F_tangential_per_planet_N_per_module": round(F_tang, 10),
        "assembly_integer":         assembly_integer,
        "tooth_constraint_ok":      tooth_constraint_ok,
        "assembly_constraint_ok":   assembly_constraint_ok,
        "warnings":                 warnings,
        "errors":                   [],
    }


# ---------------------------------------------------------------------------
# Compound (stacked) planetary
# ---------------------------------------------------------------------------

def compound_planetary(
    stage1: dict[str, Any],
    stage2: dict[str, Any],
) -> dict[str, Any]:
    """
    Compose two single-stage planetary gearboxes in series (stacked).

    Each stage dict must contain the same keyword arguments accepted by
    planetary_stage() (Z_sun, Z_planet, Z_ring, N_planets, input_torque_Nm,
    mode, eta_mesh).

    The output torque of stage 1 becomes the input torque of stage 2.

    This covers the "simple Ravigneaux-like stacked" arrangement where two
    independent epicyclic stages share a common shaft.  For a true Ravigneaux
    compound (shared planet set), the tooth geometry is more complex and is
    noted as a future extension.

    Returns
    -------
    dict with:
        ok                 bool
        combined_ratio     float  stage1.ratio × stage2.ratio
        combined_efficiency float  stage1.η × stage2.η
        stage1             dict   full result of planetary_stage(stage1)
        stage2             dict   full result of planetary_stage(stage2)
        errors             list
        warnings           list
        note               str   brief design note
    """
    errors: list[str] = []
    warnings_out: list[str] = []

    if not isinstance(stage1, dict) or not isinstance(stage2, dict):
        return {
            "ok": False,
            "errors": ["stage1 and stage2 must be dicts of planetary_stage arguments."],
            "warnings": [],
        }

    r1 = planetary_stage(**stage1)
    if not r1["ok"]:
        return {
            "ok": False,
            "errors": [f"Stage 1 error: {e}" for e in r1["errors"]],
            "warnings": r1.get("warnings", []),
        }

    # Propagate stage1 output torque to stage2 input
    stage2_with_torque = dict(stage2)
    # Output torque of stage1 is the torque on the output member.
    # For CARRIER_OUTPUT: T_carrier is the output (negative by sign convention → use abs).
    mode1 = r1["mode"]
    if mode1 == _MODE_CARRIER_OUTPUT:
        t_out_stage1 = abs(r1["T_carrier_Nm"])
    elif mode1 == _MODE_RING_OUTPUT:
        t_out_stage1 = abs(r1["T_ring_Nm"])
    else:  # SUN_OUTPUT
        t_out_stage1 = abs(r1["T_sun_Nm"])

    stage2_with_torque["input_torque_Nm"] = t_out_stage1

    r2 = planetary_stage(**stage2_with_torque)
    if not r2["ok"]:
        return {
            "ok": False,
            "errors": [f"Stage 2 error: {e}" for e in r2["errors"]],
            "warnings": r2.get("warnings", []),
        }

    combined_ratio = r1["ratio"] * r2["ratio"]
    combined_eta   = r1["efficiency"] * r2["efficiency"]

    warnings_out.extend(r1.get("warnings", []))
    warnings_out.extend(r2.get("warnings", []))

    return {
        "ok":                   True,
        "combined_ratio":       round(combined_ratio, 10),
        "combined_efficiency":  round(combined_eta, 10),
        "stage1":               r1,
        "stage2":               r2,
        "errors":               [],
        "warnings":             warnings_out,
        "note": (
            "Two independent epicyclic stages stacked on a common shaft. "
            "For a true Ravigneaux compound (shared long/short planets), "
            "a separate solver is required."
        ),
    }


# ---------------------------------------------------------------------------
# Sizing helper
# ---------------------------------------------------------------------------

# Standard ISO metric modules (ISO 54:1996)
_ISO_MODULES = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]


def planetary_module_select(
    target_ratio: float,
    target_input_torque_Nm: float,
    allowable_planet_load_N: float,
    mode: str = _MODE_CARRIER_OUTPUT,
    eta_mesh: float = _ETA_MESH_DEFAULT,
    N_planets: int = 3,
    ratio_tolerance: float = 0.02,
    Z_sun_min: int = 12,
    Z_sun_max: int = 40,
) -> dict[str, Any]:
    """
    Propose module and tooth counts for a planetary stage meeting constraints.

    Algorithm
    ---------
    1. For each ISO module and sun-tooth-count Z_sun in [Z_sun_min, Z_sun_max]:
       a. Compute required Z_ring for the target ratio (mode-dependent).
       b. Derive Z_planet from the tooth constraint.
       c. Check all integer and assembly constraints.
       d. Compute actual ratio and check it is within ratio_tolerance.
       e. Compute per-planet tangential load F = T_sun / (N_planets · r_sun).
       f. If F ≤ allowable_planet_load_N → candidate.
    2. Return the first (smallest module) valid candidate, or all candidates
       if none satisfies the load constraint (with a warning).

    Parameters
    ----------
    target_ratio              : desired n_in / n_out  (must be > 1 for CARRIER_OUTPUT)
    target_input_torque_Nm    : input torque at the driving member (N·m)
    allowable_planet_load_N   : maximum tangential load per planet (N)
    mode                      : operating mode (default CARRIER_OUTPUT)
    eta_mesh                  : per-mesh efficiency
    N_planets                 : number of planets (default 3)
    ratio_tolerance           : fractional tolerance on ratio match (default 0.02 = 2%)
    Z_sun_min, Z_sun_max      : search bounds for sun tooth count

    Returns
    -------
    dict with:
        ok              bool
        candidates      list of dicts, each with module, Z_sun, Z_planet, Z_ring,
                        actual_ratio, F_tangential_N, efficiency
        best            dict or None  — best (first valid, smallest module) candidate
        errors          list
        warnings        list
    """
    errors: list[str] = []
    warnings: list[str] = []

    if target_ratio == 0:
        errors.append("target_ratio must not be zero.")
    if target_input_torque_Nm <= 0:
        errors.append("target_input_torque_Nm must be > 0.")
    if allowable_planet_load_N <= 0:
        errors.append("allowable_planet_load_N must be > 0.")
    if mode not in _VALID_MODES:
        errors.append(f"mode={mode!r} not in {sorted(_VALID_MODES)}.")
    if N_planets < 2:
        errors.append("N_planets must be >= 2.")
    if Z_sun_min < _Z_MIN:
        errors.append(f"Z_sun_min={Z_sun_min} must be >= {_Z_MIN}.")

    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings,
                "candidates": [], "best": None}

    candidates: list[dict[str, Any]] = []

    for m in _ISO_MODULES:
        for Z_sun in range(Z_sun_min, Z_sun_max + 1):
            # ── Infer Z_ring from target ratio ─────────────────────────
            if mode == _MODE_CARRIER_OUTPUT:
                # ratio = 1 + Z_ring / Z_sun  →  Z_ring = (ratio - 1) * Z_sun
                Z_ring_f = (target_ratio - 1.0) * Z_sun
            elif mode == _MODE_RING_OUTPUT:
                # |ratio| = Z_ring / Z_sun  →  Z_ring = |ratio| * Z_sun
                Z_ring_f = abs(target_ratio) * Z_sun
            else:  # SUN_OUTPUT
                # ratio = Z_sun / (Z_sun + Z_ring)  →  Z_ring = Z_sun*(1/ratio - 1)
                if target_ratio <= 0:
                    continue
                Z_ring_f = Z_sun * (1.0 / target_ratio - 1.0)

            Z_ring = round(Z_ring_f)
            if Z_ring < _Z_MIN:
                continue

            # ── Derive Z_planet ────────────────────────────────────────
            # Z_ring = Z_sun + 2·Z_planet  →  Z_planet = (Z_ring - Z_sun) / 2
            Z_planet_f = (Z_ring - Z_sun) / 2.0
            if Z_planet_f != int(Z_planet_f):
                continue  # must be integer
            Z_planet = int(Z_planet_f)
            if Z_planet < _Z_MIN:
                continue

            # ── Re-check constraints ───────────────────────────────────
            if _check_tooth_constraint(Z_sun, Z_planet, Z_ring):
                continue  # should not happen if math is right, but guard
            if _check_assembly_constraint(Z_sun, Z_ring, N_planets):
                continue

            # ── Actual ratio ───────────────────────────────────────────
            r = planetary_stage(
                Z_sun=Z_sun,
                Z_planet=Z_planet,
                Z_ring=Z_ring,
                N_planets=N_planets,
                input_torque_Nm=target_input_torque_Nm,
                mode=mode,
                eta_mesh=eta_mesh,
            )
            if not r["ok"]:
                continue

            actual_ratio = r["ratio"]
            if abs((abs(actual_ratio) - abs(target_ratio)) / abs(target_ratio)) > ratio_tolerance:
                continue

            # ── Tangential load (actual module m) ─────────────────────
            # r_sun (actual) = m · Z_sun / 2
            # F = |T_sun| / (N_planets · r_sun_actual)
            # r["F_tangential_per_planet_N_per_module"] is for m=1, so:
            F_actual = r["F_tangential_per_planet_N_per_module"] / m

            candidates.append({
                "module":        m,
                "Z_sun":         Z_sun,
                "Z_planet":      Z_planet,
                "Z_ring":        Z_ring,
                "actual_ratio":  round(actual_ratio, 6),
                "efficiency":    round(r["efficiency"], 6),
                "F_tangential_N": round(F_actual, 4),
                "assembly_integer": r["assembly_integer"],
                "load_ok":        F_actual <= allowable_planet_load_N,
            })

    # Sort: load-OK first, then by module (smallest preferred), then by ratio accuracy
    valid = [c for c in candidates if c["load_ok"]]
    if not valid:
        warnings.append(
            "No candidate meets the allowable planet load. "
            "Returning all ratio-matching candidates."
        )

    best = valid[0] if valid else (candidates[0] if candidates else None)

    return {
        "ok":         True,
        "candidates": candidates,
        "best":       best,
        "errors":     [],
        "warnings":   warnings,
    }
