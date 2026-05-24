"""
Simple SI channel simulator — IBIS-driver + transmission-line model.

Given a parsed IBIS driver (pulldown/pullup IV + C_comp + ramp) and a
channel description (Z0, length, loss), computes the time-domain receiver
voltage waveform for a single bit and an optional eye-diagram envelope.

Model summary
-------------
1.  Driver output impedance (R_drv) is estimated from the Thevenin slope of
    the pulldown/pullup IV table (dV/dI near V_oh / V_ol).
2.  The ramp dV/dt (typ corner) sets the rise time at the driver output.
3.  The transmission line is modelled as:
      - One-way delay  TD = length * sqrt(er) / c
      - Attenuation    A  = exp(-alpha * length)      (alpha in Np/m)
      - Reflection at source end  Γ_src = (R_drv - Z0) / (R_drv + Z0)
      - Reflection at load end    Γ_ld  = (Z_term - Z0) / (Z_term + Z0)
    The waveform is built by the Bergeron / bounce-diagram method limited
    to the first three bounces (sufficient for single-bit analysis).
4.  The receiver load is a parallel combination of R_term and C_term; the
    C_term effect is approximated as a single-pole low-pass with
    τ = Z0 * C_term / 2 (source termination limit).

Output
------
``channel_response`` returns a list of ``(t_s, V)`` tuples covering at least
one bit period.

``eye_diagram_envelope`` runs a PRBS-7 through the channel and returns
(V_eye_high, V_eye_low) worst-case envelope at the sampling instant.

Author: imranparuk
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from kerf_electronics.si.ibis_parser import IBISModel, TypMinMax

# Speed of light [m/s]
_C = 2.997924580e8


# ── IV-table helpers ────────────────────────────────────────────────────────────

def _interp_iv(table: list, v: float) -> Optional[float]:
    """Linear interpolation on an (V, I_typ, …) IV table.  Returns I_typ or None."""
    if not table:
        return None
    # table rows: (V, I_typ, I_min, I_max) — use typ (index 1)
    if len(table) == 1:
        return table[0][1]
    # Sort by V
    srt = sorted(table, key=lambda r: r[0])
    if v <= srt[0][0]:
        return srt[0][1]
    if v >= srt[-1][0]:
        return srt[-1][1]
    for i in range(len(srt) - 1):
        v0, i0 = srt[i][0], srt[i][1]
        v1, i1 = srt[i + 1][0], srt[i + 1][1]
        if v0 <= v <= v1:
            if v1 == v0:
                return i0
            frac = (v - v0) / (v1 - v0)
            if i0 is None or i1 is None:
                return None
            return i0 + frac * (i1 - i0)
    return None


def _driver_thevenin(model: IBISModel, v_supply: float = 3.3) -> Tuple[float, float, float]:
    """
    Estimate Thevenin equivalent of the driver: (V_th, R_drv, V_ol, V_oh).

    Uses the pulldown table slope near V_ol and pullup slope near V_oh.
    Returns (R_drv, V_ol, V_oh).

    R_drv is the average of pulldown and pullup slope magnitudes.
    If tables are absent falls back to a default 50 Ω / 0 V / V_supply.
    """
    def _slope(table, v_ref, dv=0.1):
        """dI/dV at v_ref from the IV table; returns dV/dI (resistance)."""
        i_lo = _interp_iv(table, v_ref - dv / 2)
        i_hi = _interp_iv(table, v_ref + dv / 2)
        if i_lo is None or i_hi is None:
            return None
        di = i_hi - i_lo
        if abs(di) < 1e-12:
            return None
        return abs(dv / di)

    v_ol = 0.2
    v_oh = v_supply - 0.2
    r_pd = _slope(model.pulldown, v_ol) if model.pulldown else None
    r_pu = _slope(model.pullup, v_oh) if model.pullup else None
    if r_pd is not None and r_pu is not None:
        r_drv = (r_pd + r_pu) / 2.0
    elif r_pd is not None:
        r_drv = r_pd
    elif r_pu is not None:
        r_drv = r_pu
    else:
        r_drv = 50.0
    return r_drv, v_ol, v_oh


# ── Waveform builder ────────────────────────────────────────────────────────────

def _ramp_wave(
    v_start: float,
    v_end: float,
    dv_dt: float,
    t_start: float,
    n_pts: int = 400,
    t_total: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """
    Build a piecewise-linear ramp from v_start to v_end starting at t_start.

    dv_dt   — slew rate [V/s]
    t_total — total time window [s] (default: 4 × rise time)
    """
    if abs(v_end - v_start) < 1e-12 or dv_dt <= 0:
        t_rise = 1e-9
    else:
        t_rise = abs(v_end - v_start) / dv_dt

    t_end_ramp = t_start + t_rise
    if t_total is None:
        t_total = t_rise * 4.0
    t_final = t_start + t_total

    pts: List[Tuple[float, float]] = []
    for i in range(n_pts):
        t = t_start + t_total * i / (n_pts - 1)
        if t < t_start:
            v = v_start
        elif t < t_end_ramp:
            v = v_start + (v_end - v_start) * (t - t_start) / t_rise
        else:
            v = v_end
        pts.append((t, v))
    return pts


def _apply_lp_filter(
    waveform: List[Tuple[float, float]],
    tau: float,
) -> List[Tuple[float, float]]:
    """Simple first-order RC IIR low-pass filter on a waveform."""
    if tau <= 0:
        return waveform
    out = []
    v_prev = waveform[0][1] if waveform else 0.0
    for i, (t, v_in) in enumerate(waveform):
        if i == 0:
            dt = 0.0
        else:
            dt = t - waveform[i - 1][0]
        alpha = dt / (tau + dt) if (tau + dt) > 0 else 1.0
        v_out = v_prev + alpha * (v_in - v_prev)
        v_prev = v_out
        out.append((t, v_out))
    return out


def _add_waveforms(
    base: List[Tuple[float, float]],
    delta: List[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    """Element-wise sum — both lists must be the same length."""
    return [(base[i][0], base[i][1] + delta[i][1]) for i in range(len(base))]


def _scale_waveform(
    waveform: List[Tuple[float, float]],
    scale: float,
) -> List[Tuple[float, float]]:
    return [(t, v * scale) for t, v in waveform]


def _shift_waveform(
    waveform: List[Tuple[float, float]],
    dt_shift: float,
) -> List[Tuple[float, float]]:
    """Shift time axis by dt_shift; clip values that fall before t=0."""
    return [(t + dt_shift, v) for t, v in waveform]


def _sample_waveform(
    waveform: List[Tuple[float, float]],
    t_grid: List[float],
) -> List[Tuple[float, float]]:
    """Resample *waveform* onto *t_grid* by linear interpolation."""
    srt = sorted(waveform, key=lambda r: r[0])
    result = []
    for t in t_grid:
        if t <= srt[0][0]:
            result.append((t, srt[0][1]))
            continue
        if t >= srt[-1][0]:
            result.append((t, srt[-1][1]))
            continue
        for i in range(len(srt) - 1):
            t0, v0 = srt[i]
            t1, v1 = srt[i + 1]
            if t0 <= t <= t1:
                frac = (t - t0) / (t1 - t0) if t1 != t0 else 0.0
                result.append((t, v0 + frac * (v1 - v0)))
                break
    return result


# ── Public: channel_response ────────────────────────────────────────────────────

def channel_response(
    model: IBISModel,
    z0: float = 50.0,
    length_m: float = 0.1,
    alpha_db_per_m: float = 0.0,
    er: float = 4.2,
    r_term: float = 50.0,
    c_term_f: float = 0.0,
    v_supply: float = 3.3,
    n_pts: int = 500,
    corner: str = "typ",
) -> List[Tuple[float, float]]:
    """
    Compute the time-domain receiver voltage for a low→high bit transition.

    Parameters
    ----------
    model        : IBISModel — parsed IBIS model (needs ramp + IV tables)
    z0           : float     — transmission-line characteristic impedance [Ω]
    length_m     : float     — physical line length [m]
    alpha_db_per_m : float   — conductor + dielectric loss [dB/m] (0 = lossless)
    er           : float     — effective relative permittivity (e.g. 4.2 for FR-4)
    r_term       : float     — receiver termination resistance [Ω] (∞ = open)
    c_term_f     : float     — receiver capacitance [F] (0 = none)
    v_supply     : float     — supply voltage [V] (default 3.3 V)
    n_pts        : int       — number of time samples in output
    corner       : str       — 'typ' | 'min' | 'max' (IV/ramp corner to use)

    Returns
    -------
    List[Tuple[float, float]]
        [(t_s, V_receiver), …] covering ~4 × bit period
    """
    # ── 1. Driver Thevenin ───────────────────────────────────────────────────
    r_drv, v_ol, v_oh = _driver_thevenin(model, v_supply)

    # Voltage swing at driver output into matched load = V_supply / 2 divider
    v_drv_lo = v_ol
    v_drv_hi = v_oh

    # ── 2. Ramp / slew ───────────────────────────────────────────────────────
    dv_dt: Optional[float] = None
    if model.ramp:
        tmm = model.ramp.dv_dt_rise
        if corner == "min":
            dv_dt = tmm.min
        elif corner == "max":
            dv_dt = tmm.max
        else:
            dv_dt = tmm.typ
    if not dv_dt:
        # Fallback: assume 1 V/ns
        dv_dt = 1e9

    # ── 3. Transmission line parameters ─────────────────────────────────────
    td = length_m * math.sqrt(er) / _C          # one-way delay [s]
    attenuation = math.exp(-alpha_db_per_m * length_m / 8.686)  # dB → Np

    # Reflection coefficients
    gamma_src = (r_drv - z0) / (r_drv + z0)    # source end
    gamma_ld = (r_term - z0) / (r_term + z0)   # load end

    # ── 4. Driver waveform on a 4×bit_period grid ────────────────────────────
    t_rise = abs(v_drv_hi - v_drv_lo) / dv_dt
    t_bit = max(t_rise * 4.0, td * 8.0)        # bit period ≥ 4 × rise or 8 × TD
    t_total = t_bit * 1.5

    t_grid = [t_total * i / (n_pts - 1) for i in range(n_pts)]

    # Driver waveform (at source)
    drv_wave = _sample_waveform(
        _ramp_wave(v_drv_lo, v_drv_hi, dv_dt, t_start=0.0, n_pts=n_pts * 2,
                   t_total=t_total * 2),
        t_grid,
    )

    # ── 5. Bounce diagram — first 3 passes ──────────────────────────────────
    # Incident wave at load = driver × attenuated × delayed
    # We superpose up to 3 reflections.  Each bounce adds 2×TD delay.
    # This is the simplified Bergeron model (lossless bounces after first
    # attenuation; adequate for single-bit SI audit).

    def _delay_and_atten(wave, passes: int) -> List[Tuple[float, float]]:
        """Shift by passes × TD and scale by attenuation^passes."""
        shifted = _shift_waveform(wave, passes * td)
        return _sample_waveform(
            _scale_waveform(shifted, attenuation ** passes),
            t_grid,
        )

    # Incident (first forward pass, 1 × TD)
    v_incident = _delay_and_atten(drv_wave, 1)

    # First reflection from load end → travels back → arrives at source after 2 TD
    v_refl_1 = _sample_waveform(
        _scale_waveform(_shift_waveform(drv_wave, 2 * td), gamma_ld * attenuation ** 2),
        t_grid,
    )

    # Second reflection: from source → load (3 × TD)
    v_refl_2 = _sample_waveform(
        _scale_waveform(_shift_waveform(drv_wave, 3 * td),
                        gamma_ld * gamma_src * attenuation ** 3),
        t_grid,
    )

    # Third reflection: from load (4 × TD)
    v_refl_3 = _sample_waveform(
        _scale_waveform(_shift_waveform(drv_wave, 4 * td),
                        gamma_ld ** 2 * gamma_src * attenuation ** 4),
        t_grid,
    )

    # Receiver voltage = superposition at load end
    rcv = [(t_grid[i],
            v_incident[i][1] + v_refl_1[i][1] + v_refl_2[i][1] + v_refl_3[i][1])
           for i in range(n_pts)]

    # ── 6. Optional receiver C_term low-pass ─────────────────────────────────
    if c_term_f and c_term_f > 0:
        tau = z0 * c_term_f / 2.0
        rcv = _apply_lp_filter(rcv, tau)

    return rcv


# ── Public: eye_diagram_envelope ────────────────────────────────────────────────

def _prbs7() -> List[int]:
    """Generate one period of PRBS-7 (127 bits)."""
    bits = []
    state = 0b1111111  # non-zero seed
    for _ in range(127):
        bit = ((state >> 6) ^ (state >> 5)) & 1
        bits.append(bit)
        state = ((state << 1) | bit) & 0x7F
    return bits


def _channel_response_generic(
    model: IBISModel,
    v_start: float,
    v_end: float,
    dv_dt: float,
    z0: float,
    length_m: float,
    alpha_db_per_m: float,
    er: float,
    r_term: float,
    c_term_f: float,
    n_pts: int,
) -> List[Tuple[float, float]]:
    """
    Generic version of channel_response for arbitrary v_start → v_end transitions.
    Internal helper used by eye_diagram_envelope.
    """
    r_drv, _v_ol, _v_oh = _driver_thevenin(model, 3.3)
    t_rise = abs(v_end - v_start) / dv_dt if dv_dt > 0 else 1e-9
    td = length_m * math.sqrt(er) / _C
    attenuation = math.exp(-alpha_db_per_m * length_m / 8.686)
    gamma_src = (r_drv - z0) / (r_drv + z0)
    gamma_ld = (r_term - z0) / (r_term + z0)

    t_bit = max(t_rise * 4.0, td * 8.0)
    t_total = t_bit * 1.5
    t_grid = [t_total * i / (n_pts - 1) for i in range(n_pts)]

    drv_wave = _sample_waveform(
        _ramp_wave(v_start, v_end, dv_dt, t_start=0.0, n_pts=n_pts * 2, t_total=t_total * 2),
        t_grid,
    )

    def _delay_and_atten(wave, passes):
        shifted = _shift_waveform(wave, passes * td)
        return _sample_waveform(_scale_waveform(shifted, attenuation ** passes), t_grid)

    v_incident = _delay_and_atten(drv_wave, 1)
    v_refl_1 = _sample_waveform(
        _scale_waveform(_shift_waveform(drv_wave, 2 * td), gamma_ld * attenuation ** 2),
        t_grid)
    v_refl_2 = _sample_waveform(
        _scale_waveform(_shift_waveform(drv_wave, 3 * td),
                        gamma_ld * gamma_src * attenuation ** 3), t_grid)
    v_refl_3 = _sample_waveform(
        _scale_waveform(_shift_waveform(drv_wave, 4 * td),
                        gamma_ld ** 2 * gamma_src * attenuation ** 4), t_grid)

    rcv = [(t_grid[i],
            v_incident[i][1] + v_refl_1[i][1] + v_refl_2[i][1] + v_refl_3[i][1])
           for i in range(n_pts)]

    if c_term_f and c_term_f > 0:
        tau = z0 * c_term_f / 2.0
        rcv = _apply_lp_filter(rcv, tau)

    return rcv


def eye_diagram_envelope(
    model: IBISModel,
    z0: float = 50.0,
    length_m: float = 0.1,
    alpha_db_per_m: float = 0.0,
    er: float = 4.2,
    r_term: float = 50.0,
    c_term_f: float = 0.0,
    v_supply: float = 3.3,
    n_pts: int = 200,
) -> Tuple[float, float]:
    """
    Compute worst-case eye height at the receiver sampling instant using PRBS-7.

    Returns (V_eye_high, V_eye_low) — the minimum high-level and maximum
    low-level voltages at the ideal sampling point (centre of the eye).
    """
    bits = _prbs7()

    r_drv, v_ol, v_oh = _driver_thevenin(model, v_supply)
    dv_dt_rise = (model.ramp.dv_dt_rise.typ if model.ramp and model.ramp.dv_dt_rise.typ
                  else 1e9)
    dv_dt_fall = (model.ramp.dv_dt_fall.typ if model.ramp and model.ramp.dv_dt_fall.typ
                  else dv_dt_rise)

    td = length_m * math.sqrt(er) / _C
    t_rise = abs(v_oh - v_ol) / dv_dt_rise if dv_dt_rise > 0 else 1e-9
    t_bit = max(t_rise * 4.0, td * 8.0)

    # Sample at the midpoint of each bit (centre of eye)
    t_sample_offset = t_bit / 2.0

    # Cache waveforms for rising and falling transitions
    _wave_cache: dict = {}

    def _get_wave(rising: bool) -> List[Tuple[float, float]]:
        key = "rise" if rising else "fall"
        if key not in _wave_cache:
            vs = v_ol if rising else v_oh
            ve = v_oh if rising else v_ol
            dv = dv_dt_rise if rising else dv_dt_fall
            _wave_cache[key] = _channel_response_generic(
                model, vs, ve, dv, z0, length_m, alpha_db_per_m,
                er, r_term, c_term_f, n_pts,
            )
        return _wave_cache[key]

    v_eye_high = math.inf
    v_eye_low = -math.inf

    for bit_idx in range(len(bits)):
        cur_bit = bits[bit_idx]
        prev_bit = bits[bit_idx - 1] if bit_idx > 0 else 0

        rising = (cur_bit == 1 and prev_bit == 0)
        falling = (cur_bit == 0 and prev_bit == 1)

        if rising:
            wave = _get_wave(True)
            v_rcv = _sample_waveform(wave, [t_sample_offset])[0][1]
        elif falling:
            wave = _get_wave(False)
            v_rcv = _sample_waveform(wave, [t_sample_offset])[0][1]
        else:
            # Steady state: no transition
            v_rcv = v_oh if cur_bit else v_ol

        if cur_bit:
            v_eye_high = min(v_eye_high, v_rcv)
        else:
            v_eye_low = max(v_eye_low, v_rcv)

    if v_eye_high == math.inf:
        v_eye_high = v_oh
    if v_eye_low == -math.inf:
        v_eye_low = v_ol

    return v_eye_high, v_eye_low
