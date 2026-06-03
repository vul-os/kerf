"""
kerf_cad_core.aerospace.aerospace_tools — LLM tool wrappers for CR3BP libration
point orbit design and orbit determination.

Wave 10C: GMAT-equivalent libration point orbit design + Orbit Determination.

Tools registered
----------------
aerospace_compute_lagrange_points
    Compute all five Lagrange points for Earth-Moon or Sun-Earth system.

aerospace_design_halo_orbit
    Design a halo orbit (L1 or L2) using Richardson 3rd-order + Howell corrector.

aerospace_design_lyapunov_orbit
    Design a planar Lyapunov orbit around L1 or L2.

aerospace_design_lissajous_orbit
    Design a quasi-periodic Lissajous orbit (incommensurate xy and z frequencies).

aerospace_batch_od
    Batch least-squares orbit determination from range + range-rate observations.

aerospace_ekf_od
    Extended Kalman Filter sequential orbit determination.

DISCLAIMER: Simplified implementation for design exploration — not GMAT-validated.

References
----------
Szebehely, V. (1967). *Theory of Orbits*. Academic Press.
Richardson, D. L. (1980). Celestial Mechanics, 22, 241–253.
Howell, K. C. (1984). Celestial Mechanics, 32, 53–71.
Tapley, Schutz & Born (2004). *Statistical Orbit Determination*. Elsevier.
Vallado, D. A. (2013). *Fundamentals of Astrodynamics*, 4th ed.

Author: kerf aero depth (Wave 10C)
"""

from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_cad_core.aerospace.libration_orbits import (
    CR3BPSystem,
    EARTH_MOON_SYSTEM,
    SUN_EARTH_SYSTEM,
    compute_lagrange_points,
    design_halo_orbit,
    design_lyapunov_orbit,
    design_lissajous_orbit,
)
from kerf_cad_core.aerospace.orbit_determination import (
    InitialOrbitGuess,
    GroundStationObservation,
    batch_least_squares_od,
    extended_kalman_filter_od,
)

import numpy as np


# ---------------------------------------------------------------------------
# Helper: parse system name to CR3BPSystem
# ---------------------------------------------------------------------------

def _parse_system(system_name: str) -> CR3BPSystem:
    """Map user-supplied system name to CR3BPSystem.

    Accepts: 'earth-moon', 'em', 'sun-earth', 'se'.
    Custom systems can be specified as 'custom:mu:char_length_km:char_time_s'.
    """
    s = system_name.strip().lower()
    if s in ("earth-moon", "em", "earth_moon"):
        return EARTH_MOON_SYSTEM
    elif s in ("sun-earth", "se", "sun_earth"):
        return SUN_EARTH_SYSTEM
    elif s.startswith("custom:"):
        parts = s.split(":")
        if len(parts) < 4:
            raise ValueError(
                "Custom system format: 'custom:<mu>:<char_length_km>:<char_time_s>'"
            )
        return CR3BPSystem(
            mu=float(parts[1]),
            name="custom",
            char_length_km=float(parts[2]),
            char_time_s=float(parts[3]),
        )
    else:
        raise ValueError(
            f"Unknown system {system_name!r}. "
            "Use 'earth-moon', 'sun-earth', or 'custom:<mu>:<char_length_km>:<char_time_s>'."
        )


# ---------------------------------------------------------------------------
# Tool: aerospace_compute_lagrange_points
# ---------------------------------------------------------------------------

_lagrange_spec = ToolSpec(
    name="aerospace_compute_lagrange_points",
    description=(
        "Compute all five Lagrange (libration) equilibrium points for a CR3BP "
        "two-body system (e.g. Earth-Moon, Sun-Earth).\n\n"
        "Returns L1–L5 positions in the normalized synodic (rotating) frame, "
        "stability classification, and distances from the primary body [km].\n\n"
        "Algorithm: L1, L2, L3 from quintic polynomial roots (Szebehely 1967 §4.4); "
        "L4, L5 at ±60° from primary.\n\n"
        "DISCLAIMER: Simplified model — not GMAT-validated."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "system": {
                "type": "string",
                "description": (
                    "System name: 'earth-moon' (μ=0.01215), 'sun-earth' (μ=3e-6), "
                    "or 'custom:<mu>:<char_length_km>:<char_time_s>'."
                ),
            },
        },
        "required": ["system"],
    },
)


@register(_lagrange_spec, write=False)
async def run_aerospace_compute_lagrange_points(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    system_name = a.get("system")
    if not system_name:
        return err_payload("system is required", "BAD_ARGS")

    try:
        system = _parse_system(system_name)
        lpts = compute_lagrange_points(system)
    except Exception as exc:
        return err_payload(str(exc), "COMPUTATION_ERROR")

    result = {
        "system": system.name,
        "mu": system.mu,
        "char_length_km": system.char_length_km,
        "lagrange_points": [
            {
                "label": lp.label,
                "x_synodic": lp.x_synodic,
                "y_synodic": lp.y_synodic,
                "z_synodic": lp.z_synodic,
                "stability": lp.stability,
                "distance_from_primary_km": lp.distance_from_primary_km,
            }
            for lp in lpts
        ],
    }
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: aerospace_design_halo_orbit
# ---------------------------------------------------------------------------

_halo_spec = ToolSpec(
    name="aerospace_design_halo_orbit",
    description=(
        "Design a periodic halo orbit around an L1 or L2 Lagrange point using "
        "the Richardson (1980) 3rd-order approximation refined by the Howell (1984) "
        "differential corrector.\n\n"
        "Returns the initial state vector [x, y, z, vx, vy, vz] in the normalized "
        "synodic frame, orbital period [seconds], and convergence status.\n\n"
        "Halo orbits are 3D periodic orbits in the CR3BP, used by missions such as "
        "ISEE-3 (L1), WMAP (L2), and the James Webb Space Telescope (L2).\n\n"
        "DISCLAIMER: Simplified — not GMAT-validated. For preliminary design."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "system": {
                "type": "string",
                "description": "System: 'earth-moon' or 'sun-earth'.",
            },
            "libration_point": {
                "type": "string",
                "description": "'L1' or 'L2'.",
            },
            "target_z_amplitude_km": {
                "type": "number",
                "description": "Desired out-of-plane (z) amplitude [km]. E.g. 8000 for EM L1.",
            },
            "family": {
                "type": "string",
                "description": "'north' or 'south'. Default 'north'.",
            },
        },
        "required": ["system", "libration_point", "target_z_amplitude_km"],
    },
)


@register(_halo_spec, write=False)
async def run_aerospace_design_halo_orbit(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    system_name = a.get("system")
    lp = a.get("libration_point")
    z_amp = a.get("target_z_amplitude_km")
    family = a.get("family", "north")

    if not system_name:
        return err_payload("system is required", "BAD_ARGS")
    if not lp:
        return err_payload("libration_point is required", "BAD_ARGS")
    if z_amp is None:
        return err_payload("target_z_amplitude_km is required", "BAD_ARGS")

    try:
        system = _parse_system(system_name)
        orbit = design_halo_orbit(system, lp, float(z_amp), family=family)
    except Exception as exc:
        return err_payload(str(exc), "COMPUTATION_ERROR")

    result = {
        "family": orbit.family,
        "amplitude_z_km": orbit.amplitude_z_km,
        "period_seconds": orbit.period_seconds,
        "period_days": orbit.period_seconds / 86400.0,
        "initial_state_normalized": orbit.initial_state.tolist(),
        "initial_state_description": "[x, y, z, vx, vy, vz] in CR3BP normalized synodic frame",
        "converged": orbit.converged,
        "system": system.name,
        "disclaimer": "Simplified CR3BP model — not GMAT-validated. For design exploration.",
    }
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: aerospace_design_lyapunov_orbit
# ---------------------------------------------------------------------------

_lyapunov_spec = ToolSpec(
    name="aerospace_design_lyapunov_orbit",
    description=(
        "Design a planar Lyapunov orbit (z=0 throughout) around L1 or L2.\n\n"
        "Lyapunov orbits are the limiting case of halo orbits as the z-amplitude → 0. "
        "They lie entirely in the synodic equatorial plane and are periodic.\n\n"
        "Returns initial state, period, and x-amplitude from the Lagrange point.\n\n"
        "Reference: Szebehely (1967) §6.2.\n\n"
        "DISCLAIMER: Simplified model — not GMAT-validated."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "system": {
                "type": "string",
                "description": "System: 'earth-moon' or 'sun-earth'.",
            },
            "libration_point": {
                "type": "string",
                "description": "'L1' or 'L2'.",
            },
            "target_x_amplitude_km": {
                "type": "number",
                "description": "Approximate x amplitude from Lagrange point [km].",
            },
        },
        "required": ["system", "libration_point", "target_x_amplitude_km"],
    },
)


@register(_lyapunov_spec, write=False)
async def run_aerospace_design_lyapunov_orbit(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    system_name = a.get("system")
    lp = a.get("libration_point")
    x_amp = a.get("target_x_amplitude_km")

    if not system_name:
        return err_payload("system is required", "BAD_ARGS")
    if not lp:
        return err_payload("libration_point is required", "BAD_ARGS")
    if x_amp is None:
        return err_payload("target_x_amplitude_km is required", "BAD_ARGS")

    try:
        system = _parse_system(system_name)
        result = design_lyapunov_orbit(system, lp, float(x_amp))
    except Exception as exc:
        return err_payload(str(exc), "COMPUTATION_ERROR")

    result["system"] = system.name
    result["disclaimer"] = "Simplified CR3BP model — not GMAT-validated."
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: aerospace_design_lissajous_orbit
# ---------------------------------------------------------------------------

_lissajous_spec = ToolSpec(
    name="aerospace_design_lissajous_orbit",
    description=(
        "Design a quasi-periodic Lissajous orbit around a Lagrange point (L1, L2, L3).\n\n"
        "Lissajous orbits arise from incommensurate in-plane (λ) and out-of-plane (ν) "
        "frequencies in the linearized CR3BP dynamics (Farquhar 1968). When λ = ν, the "
        "orbit degenerates to a halo orbit (Richardson 1980).\n\n"
        "Returns the linearized initial state, both frequencies, and quasi-periods.\n\n"
        "DISCLAIMER: Linearized first-order approximation — not GMAT-validated."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "system": {
                "type": "string",
                "description": "System: 'earth-moon' or 'sun-earth'.",
            },
            "libration_point": {
                "type": "string",
                "description": "'L1', 'L2', or 'L3'.",
            },
            "target_xy_amp": {
                "type": "number",
                "description": "In-plane amplitude [normalized CR3BP units].",
            },
            "target_z_amp": {
                "type": "number",
                "description": "Out-of-plane amplitude [normalized CR3BP units].",
            },
        },
        "required": ["system", "libration_point", "target_xy_amp", "target_z_amp"],
    },
)


@register(_lissajous_spec, write=False)
async def run_aerospace_design_lissajous_orbit(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    system_name = a.get("system")
    lp = a.get("libration_point")
    xy_amp = a.get("target_xy_amp")
    z_amp = a.get("target_z_amp")

    if not system_name:
        return err_payload("system is required", "BAD_ARGS")
    if not lp:
        return err_payload("libration_point is required", "BAD_ARGS")
    if xy_amp is None:
        return err_payload("target_xy_amp is required", "BAD_ARGS")
    if z_amp is None:
        return err_payload("target_z_amp is required", "BAD_ARGS")

    try:
        system = _parse_system(system_name)
        result = design_lissajous_orbit(system, lp, float(xy_amp), float(z_amp))
    except Exception as exc:
        return err_payload(str(exc), "COMPUTATION_ERROR")

    result["system"] = system.name
    result["disclaimer"] = "Linearized approximation — not GMAT-validated."
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: aerospace_batch_od
# ---------------------------------------------------------------------------

_batch_od_spec = ToolSpec(
    name="aerospace_batch_od",
    description=(
        "Batch least-squares orbit determination from ground-station observations.\n\n"
        "Estimates a spacecraft orbit state (position + velocity at epoch) from "
        "range and range-rate observations by iterating differential corrections until "
        "convergence (Tapley, Schutz & Born 2004 §4.3; Vallado 2013 §7.6).\n\n"
        "Requires at least 6 observations (2 scalars each → 12 measurements for 6 state vars).\n\n"
        "Returns refined ECI state, covariance matrix, RMS residual, and convergence info.\n\n"
        "DISCLAIMER: Keplerian dynamics only — not GMAT-validated."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "initial_state_eci": {
                "type": "array",
                "description": "Initial guess state [x, y, z, vx, vy, vz] in ECI [km, km/s].",
                "items": {"type": "number"},
                "minItems": 6,
                "maxItems": 6,
            },
            "initial_epoch_iso": {
                "type": "string",
                "description": "ISO-8601 epoch for initial state, e.g. '2024-01-01T00:00:00Z'.",
            },
            "observations": {
                "type": "array",
                "description": "List of observation dicts.",
                "items": {
                    "type": "object",
                    "properties": {
                        "epoch_iso": {"type": "string"},
                        "range_km": {"type": "number"},
                        "range_rate_km_s": {"type": "number"},
                        "azimuth_deg": {"type": "number"},
                        "elevation_deg": {"type": "number"},
                        "station_eci": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "sigma_range_km": {"type": "number"},
                        "sigma_range_rate_km_s": {"type": "number"},
                    },
                    "required": ["epoch_iso", "range_km", "range_rate_km_s", "station_eci"],
                },
            },
            "max_iter": {
                "type": "integer",
                "description": "Maximum iterations. Default 10.",
            },
            "tol": {
                "type": "number",
                "description": "Position convergence tolerance [km]. Default 1e-6.",
            },
        },
        "required": ["initial_state_eci", "initial_epoch_iso", "observations"],
    },
)


@register(_batch_od_spec, write=False)
async def run_aerospace_batch_od(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    initial_state = a.get("initial_state_eci")
    initial_epoch = a.get("initial_epoch_iso")
    obs_raw = a.get("observations", [])
    max_iter = int(a.get("max_iter", 10))
    tol = float(a.get("tol", 1e-6))

    if not initial_state or len(initial_state) != 6:
        return err_payload("initial_state_eci must be a list of 6 floats", "BAD_ARGS")
    if not initial_epoch:
        return err_payload("initial_epoch_iso is required", "BAD_ARGS")
    if len(obs_raw) < 6:
        return err_payload(
            f"At least 6 observations required; got {len(obs_raw)}", "BAD_ARGS"
        )

    try:
        initial = InitialOrbitGuess(
            state_eci=np.array(initial_state, dtype=float),
            epoch_iso=initial_epoch,
        )
        observations = []
        for o in obs_raw:
            observations.append(GroundStationObservation(
                epoch_iso=o["epoch_iso"],
                range_km=float(o["range_km"]),
                range_rate_km_s=float(o["range_rate_km_s"]),
                azimuth_deg=float(o.get("azimuth_deg", 0.0)),
                elevation_deg=float(o.get("elevation_deg", 0.0)),
                station_eci=np.array(o["station_eci"], dtype=float),
                sigma_range_km=float(o.get("sigma_range_km", 0.001)),
                sigma_range_rate_km_s=float(o.get("sigma_range_rate_km_s", 1e-6)),
            ))

        report = batch_least_squares_od(initial, observations, max_iter=max_iter, tol=tol)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "COMPUTATION_ERROR")

    result = {
        "refined_state_eci": report.refined_state.tolist(),
        "covariance": report.covariance.tolist(),
        "rms_residual": report.rms_residual,
        "iterations": report.iterations,
        "converged": report.converged,
        "disclaimer": "Keplerian dynamics only — not GMAT-validated.",
    }
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: aerospace_ekf_od
# ---------------------------------------------------------------------------

_ekf_od_spec = ToolSpec(
    name="aerospace_ekf_od",
    description=(
        "Extended Kalman Filter (EKF) sequential orbit determination.\n\n"
        "Processes observations one-by-one with predict + update steps:\n"
        "  Predict: propagate state and covariance via RK4 + STM.\n"
        "  Update:  apply Kalman gain from range + range-rate residual.\n\n"
        "Returns a list of ODReport objects (one per observation), each with "
        "refined state, covariance, and normalized RMS residual after that update.\n\n"
        "References: Tapley et al. (2004) §5.3; Gelb (1974).\n\n"
        "DISCLAIMER: Keplerian dynamics only — not GMAT-validated."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "initial_state_eci": {
                "type": "array",
                "description": "Initial guess state [x, y, z, vx, vy, vz] in ECI [km, km/s].",
                "items": {"type": "number"},
                "minItems": 6,
                "maxItems": 6,
            },
            "initial_epoch_iso": {
                "type": "string",
                "description": "ISO-8601 epoch.",
            },
            "observations": {
                "type": "array",
                "description": "List of observation dicts (same schema as batch_od).",
                "items": {"type": "object"},
            },
            "process_noise_diagonal": {
                "type": "array",
                "description": (
                    "Optional diagonal of 6×6 process noise covariance Q. "
                    "Length 6: [qx, qy, qz, qvx, qvy, qvz]. "
                    "Null → Q = 0 (no process noise)."
                ),
                "items": {"type": "number"},
                "minItems": 6,
                "maxItems": 6,
            },
        },
        "required": ["initial_state_eci", "initial_epoch_iso", "observations"],
    },
)


@register(_ekf_od_spec, write=False)
async def run_aerospace_ekf_od(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    initial_state = a.get("initial_state_eci")
    initial_epoch = a.get("initial_epoch_iso")
    obs_raw = a.get("observations", [])
    q_diag = a.get("process_noise_diagonal")

    if not initial_state or len(initial_state) != 6:
        return err_payload("initial_state_eci must be a list of 6 floats", "BAD_ARGS")
    if not initial_epoch:
        return err_payload("initial_epoch_iso is required", "BAD_ARGS")

    try:
        initial = InitialOrbitGuess(
            state_eci=np.array(initial_state, dtype=float),
            epoch_iso=initial_epoch,
        )
        observations = []
        for o in obs_raw:
            observations.append(GroundStationObservation(
                epoch_iso=o["epoch_iso"],
                range_km=float(o["range_km"]),
                range_rate_km_s=float(o["range_rate_km_s"]),
                azimuth_deg=float(o.get("azimuth_deg", 0.0)),
                elevation_deg=float(o.get("elevation_deg", 0.0)),
                station_eci=np.array(o["station_eci"], dtype=float),
                sigma_range_km=float(o.get("sigma_range_km", 0.001)),
                sigma_range_rate_km_s=float(o.get("sigma_range_rate_km_s", 1e-6)),
            ))

        process_noise = None
        if q_diag is not None:
            process_noise = np.diag(np.array(q_diag, dtype=float))

        reports = extended_kalman_filter_od(initial, observations, process_noise)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "COMPUTATION_ERROR")

    result = {
        "reports": [
            {
                "step": i + 1,
                "refined_state_eci": r.refined_state.tolist(),
                "rms_residual": r.rms_residual,
                "iterations": r.iterations,
                "converged": r.converged,
            }
            for i, r in enumerate(reports)
        ],
        "total_steps": len(reports),
        "disclaimer": "Keplerian dynamics only — not GMAT-validated.",
    }
    return ok_payload(result)
