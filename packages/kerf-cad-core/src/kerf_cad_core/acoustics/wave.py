"""
kerf_cad_core.acoustics.wave — wave-domain room acoustics + SEA (pure Python).

New capability layer (does NOT modify sound.py).

Public API
----------
image_source_impulse_response(room_LWH, source_xyz, receiver_xyz,
                              alpha_walls, max_order=3, c=343,
                              dt=1e-4, t_max=2.0)
    Computes the room impulse response (RIR) for a shoebox room using the
    image-source method.  Returns (t_array, h_array).

rt60_from_ir(t, h)
    Schroeder backward-integration → energy decay curve → linear dB fit → T60.

room_modes(L, W, H, f_max=500, c=343)
    Returns list of (nx, ny, nz, f_mode) for all room modes below f_max.

sea_two_rooms_tl(loss_factor_1, loss_factor_2, coupling,
                 modal_density, freq_bands)
    Two-room SEA energy-balance: solves 2×2 system per band →
    transmission loss in dB.

LLM tools (registered with the Kerf tool registry):
    wave_image_source_ir
    wave_rt60_from_ir
    wave_room_modes
    wave_sea_two_rooms_tl

References
----------
Allen & Berkley (1979) "Image method for efficiently simulating small-room
acoustics."  JASA 65(4):943-950.
Schroeder (1965) "New method of measuring reverberation time."  JASA 37:409.
Beranek & Ver "Noise and Vibration Control Engineering" (1992).
Lyon & DeJong "Theory and Application of SEA" (1995).

Author: imranparuk
"""
from __future__ import annotations

import json
import math
import warnings
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# 1. Image-Source Method (ISM) — shoebox RIR
# ---------------------------------------------------------------------------

def image_source_impulse_response(
    room_LWH: Tuple[float, float, float],
    source_xyz: Tuple[float, float, float],
    receiver_xyz: Tuple[float, float, float],
    alpha_walls: float | List[float],
    max_order: int = 3,
    c: float = 343.0,
    dt: float = 1e-4,
    t_max: float = 2.0,
) -> dict:
    """
    Room impulse response via the image-source method for a shoebox room.

    Parameters
    ----------
    room_LWH    : (L, W, H) room dimensions in metres.
    source_xyz  : (x, y, z) source position (metres).
    receiver_xyz: (x, y, z) receiver position (metres).
    alpha_walls : uniform absorption coefficient OR list of 6 per-surface
                  values [x_low, x_high, y_low, y_high, z_low, z_high].
    max_order   : maximum reflection order (default 3).
    c           : speed of sound (m/s, default 343).
    dt          : time resolution (s, default 1e-4).
    t_max       : impulse response length (s, default 2.0).

    Returns
    -------
    dict with keys:
        ok       : True
        t        : list[float] — time axis (seconds)
        h        : list[float] — impulse response amplitudes
        n_images : int — number of image sources summed
    """
    try:
        L, W, H = float(room_LWH[0]), float(room_LWH[1]), float(room_LWH[2])
        xs, ys, zs = float(source_xyz[0]), float(source_xyz[1]), float(source_xyz[2])
        xr, yr, zr = float(receiver_xyz[0]), float(receiver_xyz[1]), float(receiver_xyz[2])
    except Exception as exc:
        warnings.warn(str(exc))
        return {"ok": False, "reason": f"bad geometry args: {exc}"}

    if L <= 0 or W <= 0 or H <= 0:
        warnings.warn("Room dimensions must be positive.")
        return {"ok": False, "reason": "Room dimensions must be positive."}

    # Normalise alpha_walls to 6-element list
    if isinstance(alpha_walls, (int, float)):
        a6 = [float(alpha_walls)] * 6
    else:
        try:
            a6 = [float(v) for v in alpha_walls]
        except Exception as exc:
            return {"ok": False, "reason": f"bad alpha_walls: {exc}"}
        if len(a6) != 6:
            return {"ok": False, "reason": "alpha_walls must be scalar or list of 6 values."}

    # Reflection coefficients (amplitude) per surface
    # r_i = sqrt(1 - alpha_i)  (pressure reflection coefficient)
    try:
        rc = [math.sqrt(_clamp(1.0 - a, 0.0, 1.0)) for a in a6]
    except Exception as exc:
        return {"ok": False, "reason": f"alpha_walls out of range: {exc}"}

    # Unpack: x_low(0), x_high(1), y_low(2), y_high(3), z_low(4), z_high(5)
    rx_lo, rx_hi, ry_lo, ry_hi, rz_lo, rz_hi = rc

    if max_order < 0 or max_order > 30:
        return {"ok": False, "reason": "max_order must be in [0, 30]."}

    n_samples = int(math.ceil(t_max / dt)) + 1
    h = [0.0] * n_samples
    n_images = 0

    # Allen & Berkley (1979) image-source method.
    # Image position for integer lattice index (nx, ny, nz) and parity (px, py, pz):
    #   xi = 2*nx*L + (-1)^px * xs   (px=0: even mirror, px=1: odd mirror)
    #   yi = 2*ny*W + (-1)^py * ys
    #   zi = 2*nz*H + (-1)^pz * zs
    #
    # Reflection count per wall (Allen & Berkley Eq. A2):
    #   n_x_lo (bounces off x=0): max(0, -nx) + px
    #   n_x_hi (bounces off x=L): max(0,  nx)
    # (and analogously for y, z)
    #
    # Total reflection order = n_x_lo + n_x_hi + n_y_lo + n_y_hi + n_z_lo + n_z_hi

    for nx in range(-max_order, max_order + 1):
        for ny in range(-max_order, max_order + 1):
            for nz in range(-max_order, max_order + 1):
                for px in range(2):
                    for py in range(2):
                        for pz in range(2):
                            # Image source coordinates (Allen-Berkley 1979)
                            xi = 2 * nx * L + (xs if px == 0 else -xs)
                            yi = 2 * ny * W + (ys if py == 0 else -ys)
                            zi = 2 * nz * H + (zs if pz == 0 else -zs)

                            dx = xi - xr
                            dy = yi - yr
                            dz = zi - zr
                            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                            if dist < 1e-9:
                                continue

                            t_arrive = dist / c
                            if t_arrive > t_max:
                                continue

                            # Reflection counts per wall
                            n_x_lo = max(0, -nx) + px   # bounces off x=0
                            n_x_hi = max(0, nx)          # bounces off x=L
                            n_y_lo = max(0, -ny) + py
                            n_y_hi = max(0, ny)
                            n_z_lo = max(0, -nz) + pz
                            n_z_hi = max(0, nz)

                            # Skip if total order exceeds max_order
                            total_bounces = (n_x_lo + n_x_hi +
                                             n_y_lo + n_y_hi +
                                             n_z_lo + n_z_hi)
                            if total_bounces > max_order:
                                continue

                            amplitude = (
                                (rx_lo ** n_x_lo) *
                                (rx_hi ** n_x_hi) *
                                (ry_lo ** n_y_lo) *
                                (ry_hi ** n_y_hi) *
                                (rz_lo ** n_z_lo) *
                                (rz_hi ** n_z_hi)
                            ) / dist

                            sample_idx = int(round(t_arrive / dt))
                            if 0 <= sample_idx < n_samples:
                                h[sample_idx] += amplitude
                                n_images += 1

    t_arr = [i * dt for i in range(n_samples)]

    return {
        "ok": True,
        "t": t_arr,
        "h": h,
        "n_images": n_images,
    }


# ---------------------------------------------------------------------------
# 2. RT60 from Impulse Response (Schroeder)
# ---------------------------------------------------------------------------

def rt60_from_ir(t: List[float], h: List[float]) -> dict:
    """
    Estimate RT60 from a room impulse response using Schroeder
    backward-integration.

    Parameters
    ----------
    t : list[float] — time axis (seconds).
    h : list[float] — impulse response amplitudes.

    Returns
    -------
    dict with keys:
        ok          : True
        rt60_s      : float — estimated T60 in seconds
        edc_db      : list[float] — energy decay curve (dB, Schroeder integral)
        fit_slope   : float — dB/s slope of linear fit
        fit_intercept: float — intercept of linear fit
    """
    try:
        t_arr = [float(v) for v in t]
        h_arr = [float(v) for v in h]
    except Exception as exc:
        return {"ok": False, "reason": f"bad t/h: {exc}"}

    n = len(t_arr)
    if n < 2 or len(h_arr) != n:
        return {"ok": False, "reason": "t and h must be equal-length lists of length >= 2."}

    # Squared impulse response energy
    h2 = [x * x for x in h_arr]

    # Schroeder backward cumulative sum
    total = sum(h2)
    if total <= 0:
        return {"ok": False, "reason": "Impulse response has zero energy."}

    # Build energy decay curve
    running = 0.0
    backward = []
    for i in range(n - 1, -1, -1):
        running += h2[i]
        backward.append(running)
    backward.reverse()  # now forward in time

    # Convert to dB (normalised)
    edc_db = []
    for v in backward:
        if v > 0:
            edc_db.append(10.0 * math.log10(v / total))
        else:
            edc_db.append(-120.0)

    # Linear fit over the -5 dB to -35 dB region (ISO 3382 T30 method)
    fit_t = []
    fit_e = []
    for i in range(n):
        e = edc_db[i]
        if -35.0 <= e <= -5.0:
            fit_t.append(t_arr[i])
            fit_e.append(e)

    if len(fit_t) < 2:
        # Fall back to full range
        fit_t = t_arr
        fit_e = edc_db

    # Least-squares linear fit: e = slope * t + intercept
    k = len(fit_t)
    sum_t = sum(fit_t)
    sum_e = sum(fit_e)
    sum_tt = sum(x * x for x in fit_t)
    sum_te = sum(fit_t[i] * fit_e[i] for i in range(k))
    denom = k * sum_tt - sum_t * sum_t
    if abs(denom) < 1e-12:
        return {"ok": False, "reason": "Degenerate fit: t range too small."}

    slope = (k * sum_te - sum_t * sum_e) / denom
    intercept = (sum_e - slope * sum_t) / k

    if slope >= 0:
        return {"ok": False, "reason": "Energy decay slope is non-negative; bad IR."}

    # RT60: time for 60 dB decay from 0 dB
    rt60 = -60.0 / slope

    return {
        "ok": True,
        "rt60_s": round(rt60, 4),
        "edc_db": [round(v, 3) for v in edc_db],
        "fit_slope": round(slope, 4),
        "fit_intercept": round(intercept, 4),
    }


# ---------------------------------------------------------------------------
# 3. Room Modes (shoebox)
# ---------------------------------------------------------------------------

def room_modes(
    L: float,
    W: float,
    H: float,
    f_max: float = 500.0,
    c: float = 343.0,
) -> dict:
    """
    Compute axial, tangential, and oblique room modes for a shoebox room.

    f_mode = (c/2) * sqrt((nx/L)^2 + (ny/W)^2 + (nz/H)^2)

    Parameters
    ----------
    L, W, H  : room dimensions (metres).
    f_max    : upper frequency limit (Hz, default 500).
    c        : speed of sound (m/s, default 343).

    Returns
    -------
    dict with keys:
        ok    : True
        modes : list of {"nx", "ny", "nz", "type", "f_hz"}
                sorted by frequency.
    """
    try:
        L, W, H = float(L), float(W), float(H)
        f_max = float(f_max)
        c = float(c)
    except Exception as exc:
        return {"ok": False, "reason": f"bad args: {exc}"}

    if L <= 0 or W <= 0 or H <= 0:
        return {"ok": False, "reason": "Room dimensions must be positive."}
    if f_max <= 0:
        return {"ok": False, "reason": "f_max must be positive."}

    # Max mode index per dimension
    n_max_x = int(math.floor(2 * f_max * L / c)) + 1
    n_max_y = int(math.floor(2 * f_max * W / c)) + 1
    n_max_z = int(math.floor(2 * f_max * H / c)) + 1

    modes = []
    for nx in range(0, n_max_x + 1):
        for ny in range(0, n_max_y + 1):
            for nz in range(0, n_max_z + 1):
                if nx == 0 and ny == 0 and nz == 0:
                    continue
                f = 0.5 * c * math.sqrt(
                    (nx / L) ** 2 + (ny / W) ** 2 + (nz / H) ** 2
                )
                if f > f_max:
                    continue
                nonzero = (nx != 0) + (ny != 0) + (nz != 0)
                if nonzero == 1:
                    mode_type = "axial"
                elif nonzero == 2:
                    mode_type = "tangential"
                else:
                    mode_type = "oblique"
                modes.append({
                    "nx": nx, "ny": ny, "nz": nz,
                    "type": mode_type,
                    "f_hz": round(f, 3),
                })

    modes.sort(key=lambda m: m["f_hz"])
    return {"ok": True, "modes": modes}


# ---------------------------------------------------------------------------
# 4. Two-Room SEA Transmission Loss
# ---------------------------------------------------------------------------

def sea_two_rooms_tl(
    loss_factor_1: float,
    loss_factor_2: float,
    coupling: float,
    modal_density: float,
    freq_bands: List[float],
) -> dict:
    """
    Statistical Energy Analysis for two coupled rooms.

    Energy balance per band:
        [ (eta_1 + eta_c),   -eta_c      ] [E1]   [P_in]
        [ -eta_c,    (eta_2 + eta_c)      ] [E2] = [0   ]

    where eta_c = coupling loss factor (eta_c = coupling / (modal_density * omega)).
    Transmission Loss = 10 * log10(E1 / E2).

    Parameters
    ----------
    loss_factor_1   : internal loss factor of room 1 (dimensionless, e.g. 0.05).
    loss_factor_2   : internal loss factor of room 2 (dimensionless, e.g. 0.05).
    coupling        : coupling coefficient between rooms (dimensionless, e.g. 0.01).
    modal_density   : modal density n(f) in modes/Hz (positive float).
    freq_bands      : list of centre frequencies (Hz).

    Returns
    -------
    dict with keys:
        ok       : True
        results  : list of {"freq_hz", "E1", "E2", "tl_db"}
    """
    try:
        eta1 = float(loss_factor_1)
        eta2 = float(loss_factor_2)
        eta_c_raw = float(coupling)
        nd = float(modal_density)
        bands = [float(f) for f in freq_bands]
    except Exception as exc:
        return {"ok": False, "reason": f"bad args: {exc}"}

    if eta1 <= 0 or eta2 <= 0:
        return {"ok": False, "reason": "loss factors must be positive."}
    if eta_c_raw < 0:
        return {"ok": False, "reason": "coupling must be non-negative."}
    if nd <= 0:
        return {"ok": False, "reason": "modal_density must be positive."}
    if not bands:
        return {"ok": False, "reason": "freq_bands must be non-empty."}

    results = []
    for f in bands:
        if f <= 0:
            results.append({"freq_hz": f, "E1": None, "E2": None,
                             "tl_db": None, "reason": "freq must be positive"})
            continue

        omega = 2.0 * math.pi * f
        # Coupling loss factor (frequency-dependent)
        eta_c = eta_c_raw / (nd * omega) if nd * omega > 0 else 0.0

        # 2×2 system: (A) * [E1, E2]^T = [P_in, 0]^T
        # A = [[eta1+eta_c, -eta_c], [-eta_c, eta2+eta_c]]
        # Solve with unit power input (P_in = 1)
        a11 = eta1 + eta_c
        a12 = -eta_c
        a21 = -eta_c
        a22 = eta2 + eta_c

        det = a11 * a22 - a12 * a21
        if abs(det) < 1e-30:
            results.append({"freq_hz": f, "E1": None, "E2": None,
                             "tl_db": None, "reason": "singular matrix"})
            continue

        # Cramer's rule: [P=1, 0] on RHS
        E1 = (1.0 * a22 - 0.0 * a12) / det
        E2 = (a11 * 0.0 - a21 * 1.0) / det

        if E1 <= 0 or E2 <= 0:
            tl_db = None
        else:
            tl_db = round(10.0 * math.log10(E1 / E2), 3)

        results.append({
            "freq_hz": round(f, 2),
            "E1": round(E1, 6),
            "E2": round(E2, 6),
            "tl_db": tl_db,
        })

    return {"ok": True, "results": results}


# ---------------------------------------------------------------------------
# LLM Tool wrappers
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    # --- wave_image_source_ir ---

    _ism_spec = ToolSpec(
        name="wave_image_source_ir",
        description=(
            "Compute the room impulse response (RIR) of a shoebox room using the "
            "image-source method (Allen & Berkley 1979).\n\n"
            "The RIR captures how a brief sound propagates and reflects inside "
            "the room. Use it as input to wave_rt60_from_ir to extract T60, or "
            "convolve with a dry signal for auralization.\n\n"
            "Returns: t (time axis, s), h (amplitude array), n_images (count)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "room_LWH": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[L, W, H] — room length, width, height (metres).",
                },
                "source_xyz": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[x, y, z] source position (metres).",
                },
                "receiver_xyz": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[x, y, z] receiver position (metres).",
                },
                "alpha_walls": {
                    "description": (
                        "Absorption coefficient(s) for the walls.  "
                        "Scalar for uniform surfaces, or list of 6 values "
                        "[x_low, x_high, y_low, y_high, z_low, z_high]."
                    ),
                },
                "max_order": {
                    "type": "integer",
                    "description": "Maximum reflection order (default 3).",
                },
                "c": {
                    "type": "number",
                    "description": "Speed of sound m/s (default 343).",
                },
                "dt": {
                    "type": "number",
                    "description": "Time step seconds (default 1e-4).",
                },
                "t_max": {
                    "type": "number",
                    "description": "IR duration seconds (default 2.0).",
                },
            },
            "required": ["room_LWH", "source_xyz", "receiver_xyz", "alpha_walls"],
        },
    )

    @register(_ism_spec, write=False)
    async def run_wave_image_source_ir(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        result = image_source_impulse_response(
            room_LWH=a.get("room_LWH", [5, 4, 3]),
            source_xyz=a.get("source_xyz", [1, 1, 1]),
            receiver_xyz=a.get("receiver_xyz", [4, 3, 2]),
            alpha_walls=a.get("alpha_walls", 0.1),
            max_order=int(a.get("max_order", 3)),
            c=float(a.get("c", 343.0)),
            dt=float(a.get("dt", 1e-4)),
            t_max=float(a.get("t_max", 2.0)),
        )
        return ok_payload(result) if result["ok"] else json.dumps(result)

    # --- wave_rt60_from_ir ---

    _rt60_ir_spec = ToolSpec(
        name="wave_rt60_from_ir",
        description=(
            "Estimate RT60 reverberation time from a room impulse response using "
            "Schroeder backward-integration (ISO 3382 T30 method extrapolated to T60).\n\n"
            "Input: t (time axis, s) and h (IR amplitudes) as returned by "
            "wave_image_source_ir.\n\n"
            "Returns: rt60_s, energy decay curve (edc_db), fit slope (dB/s)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "t": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Time axis (seconds).",
                },
                "h": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Impulse response amplitudes.",
                },
            },
            "required": ["t", "h"],
        },
    )

    @register(_rt60_ir_spec, write=False)
    async def run_wave_rt60_from_ir(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        result = rt60_from_ir(t=a.get("t", []), h=a.get("h", []))
        return ok_payload(result) if result["ok"] else json.dumps(result)

    # --- wave_room_modes ---

    _modes_spec = ToolSpec(
        name="wave_room_modes",
        description=(
            "Compute axial, tangential, and oblique room modes for a rectangular "
            "(shoebox) room up to a specified frequency.\n\n"
            "f_mode = (c/2) · sqrt((nx/L)² + (ny/W)² + (nz/H)²)\n\n"
            "Returns a list of modes sorted by frequency with type classification."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "L": {"type": "number", "description": "Room length (m)."},
                "W": {"type": "number", "description": "Room width (m)."},
                "H": {"type": "number", "description": "Room height (m)."},
                "f_max": {
                    "type": "number",
                    "description": "Upper frequency limit Hz (default 500).",
                },
                "c": {
                    "type": "number",
                    "description": "Speed of sound m/s (default 343).",
                },
            },
            "required": ["L", "W", "H"],
        },
    )

    @register(_modes_spec, write=False)
    async def run_wave_room_modes(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        result = room_modes(
            L=float(a.get("L", 5)),
            W=float(a.get("W", 4)),
            H=float(a.get("H", 3)),
            f_max=float(a.get("f_max", 500)),
            c=float(a.get("c", 343)),
        )
        return ok_payload(result) if result["ok"] else json.dumps(result)

    # --- wave_sea_two_rooms_tl ---

    _sea_spec = ToolSpec(
        name="wave_sea_two_rooms_tl",
        description=(
            "Statistical Energy Analysis (SEA) for two coupled rooms.\n\n"
            "Solves the 2×2 energy balance per frequency band:\n"
            "  (η₁ + η_c)·E₁ − η_c·E₂ = P_in\n"
            "  −η_c·E₁ + (η₂ + η_c)·E₂ = 0\n\n"
            "Returns transmission loss TL = 10·log₁₀(E₁/E₂) per band.\n\n"
            "Use to estimate partition performance when detailed geometry is unavailable."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "loss_factor_1": {
                    "type": "number",
                    "description": "Internal loss factor η₁ of room 1 (e.g. 0.05).",
                },
                "loss_factor_2": {
                    "type": "number",
                    "description": "Internal loss factor η₂ of room 2 (e.g. 0.05).",
                },
                "coupling": {
                    "type": "number",
                    "description": "Coupling coefficient between rooms (e.g. 0.01).",
                },
                "modal_density": {
                    "type": "number",
                    "description": "Modal density n(f) in modes/Hz.",
                },
                "freq_bands": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Centre frequencies (Hz), e.g. [125, 250, 500, 1000].",
                },
            },
            "required": [
                "loss_factor_1", "loss_factor_2",
                "coupling", "modal_density", "freq_bands",
            ],
        },
    )

    @register(_sea_spec, write=False)
    async def run_wave_sea_two_rooms_tl(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        result = sea_two_rooms_tl(
            loss_factor_1=float(a.get("loss_factor_1", 0.05)),
            loss_factor_2=float(a.get("loss_factor_2", 0.05)),
            coupling=float(a.get("coupling", 0.01)),
            modal_density=float(a.get("modal_density", 1.0)),
            freq_bands=a.get("freq_bands", [125, 250, 500, 1000]),
        )
        return ok_payload(result) if result["ok"] else json.dumps(result)
