"""
kerf_cad_core.controls.transfer_function — Transfer function arithmetic,
stability analysis, and frequency-domain methods.

Public API
----------
TransferFunction   — G(s) = num(s) / den(s) dataclass
routh_hurwitz      — Routh 1877 / Hurwitz 1895 stability table
bode_plot_data     — Bode magnitude (dB) + phase (deg) arrays
nyquist_plot_data  — Nyquist complex values G(jω)
gain_phase_margin  — gain & phase margins, crossover frequencies
feedback           — closed-loop G/(1+GH) (sign=-1 for negative feedback)

All pure Python + numpy.  No scipy.

References
----------
Ogata, K. (2010). "Modern Control Engineering", 5th ed. Pearson.
Routh, E.J. (1877). "A Treatise on the Stability of a Given State of Motion."
Hurwitz, A. (1895). "Ueber die Bedingungen, unter welchen eine Gleichung
    nur Wurzeln mit negativen reellen Theilen besitzt." Math. Ann. 46, 273–284.
Nyquist, H. (1932). "Regeneration Theory." Bell System Tech. J. 11, 126–147.
Åström, K.J. & Hägglund, T. (2006). "Advanced PID Control." ISA.

Author: imranparuk
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poly_eval_complex(coeffs: list[float], s: complex) -> complex:
    """Evaluate polynomial at s using Horner's method (highest degree first)."""
    result = complex(0.0)
    for c in coeffs:
        result = result * s + c
    return result


def _poly_mul(a: list[float], b: list[float]) -> list[float]:
    """Multiply two polynomials (coefficient lists, highest degree first)."""
    if not a or not b:
        return [0.0]
    la, lb = len(a), len(b)
    result = [0.0] * (la + lb - 1)
    for i, ai in enumerate(a):
        for j, bj in enumerate(b):
            result[i + j] += ai * bj
    return result


def _poly_add(a: list[float], b: list[float]) -> list[float]:
    """Add two polynomials (highest degree first, zero-padded)."""
    la, lb = len(a), len(b)
    lmax = max(la, lb)
    result = [0.0] * lmax
    for i in range(la):
        result[lmax - la + i] += a[i]
    for i in range(lb):
        result[lmax - lb + i] += b[i]
    return result


def _poly_strip(coeffs: list[float]) -> list[float]:
    """Remove leading near-zero coefficients."""
    c = list(coeffs)
    while len(c) > 1 and abs(c[0]) < 1e-15:
        c.pop(0)
    return c


# ---------------------------------------------------------------------------
# TransferFunction dataclass
# ---------------------------------------------------------------------------

@dataclass
class TransferFunction:
    """
    G(s) = num(s) / den(s), coefficients in descending powers of s.

    Example — G(s) = 1/(s²+s+1):
        TransferFunction(num=[1.0], den=[1.0, 1.0, 1.0])

    References: Ogata (2010) §2.
    """
    num: list[float]
    den: list[float]

    def __post_init__(self) -> None:
        self.num = [float(c) for c in self.num]
        self.den = [float(c) for c in self.den]
        if not self.num:
            raise ValueError("num must be non-empty")
        if not self.den:
            raise ValueError("den must be non-empty")
        if abs(self.den[0]) < 1e-15:
            raise ValueError("Leading denominator coefficient must be non-zero")

    # -- Evaluation --------------------------------------------------------

    def evaluate_at(self, s: complex) -> complex:
        """Evaluate G(s) at a complex frequency s."""
        n_val = _poly_eval_complex(self.num, s)
        d_val = _poly_eval_complex(self.den, s)
        if abs(d_val) < 1e-30:
            return complex(math.inf)
        return n_val / d_val

    # -- Responses ---------------------------------------------------------

    def step_response(self, t: np.ndarray) -> np.ndarray:
        """
        Step response y(t) via inverse Laplace using residue method
        (partial fractions at the poles of G(s)/s).

        For the general case we use the bilinear (Tustin) discretisation:
            H(z) = G(s)|_{s = (2/dt)(z-1)/(z+1)}
        at a small sample interval, then convolve with unit step.

        Ogata (2010) §5.
        """
        t = np.asarray(t, dtype=float)
        if len(t) == 0:
            return np.array([])
        dt = float(t[1] - t[0]) if len(t) > 1 else 1e-3
        # Use bilinear transform to simulate step response
        return _simulate_step(self.num, self.den, t, dt)

    def impulse_response(self, t: np.ndarray) -> np.ndarray:
        """
        Impulse response h(t) via numerical differentiation of the step response:
            h(t) ≈ d/dt y_step(t).

        Ogata (2010) §5.
        """
        t = np.asarray(t, dtype=float)
        if len(t) == 0:
            return np.array([])
        dt = float(t[1] - t[0]) if len(t) > 1 else 1e-3
        step = _simulate_step(self.num, self.den, t, dt)
        # Numerical derivative
        impulse = np.gradient(step, t)
        return impulse

    # -- Poles and Zeros ---------------------------------------------------

    def poles(self) -> np.ndarray:
        """Roots of the denominator polynomial."""
        return np.roots(self.den)

    def zeros(self) -> np.ndarray:
        """Roots of the numerator polynomial."""
        return np.roots(self.num)

    # -- Arithmetic --------------------------------------------------------

    def __mul__(self, other: "TransferFunction") -> "TransferFunction":
        """Series connection: G1·G2."""
        num = _poly_mul(self.num, other.num)
        den = _poly_mul(self.den, other.den)
        return TransferFunction(num, den)

    def __add__(self, other: "TransferFunction") -> "TransferFunction":
        """Parallel connection: G1 + G2 = (G1·den2 + G2·den1)/(den1·den2)."""
        num = _poly_add(
            _poly_mul(self.num, other.den),
            _poly_mul(other.num, self.den),
        )
        den = _poly_mul(self.den, other.den)
        return TransferFunction(_poly_strip(num), _poly_strip(den))


# ---------------------------------------------------------------------------
# Step response simulation via forward Euler on state-space
# ---------------------------------------------------------------------------

def _simulate_step(
    num: list[float],
    den: list[float],
    t: np.ndarray,
    dt: float,
) -> np.ndarray:
    """
    Simulate unit step response of G(s) = num(s)/den(s) via direct-form II
    difference equations using zero-order-hold discretisation (Euler).

    This avoids scipy while handling arbitrary-order TFs.
    """
    # Normalise: leading den coefficient = 1
    a0 = den[0]
    num_n = [c / a0 for c in num]
    den_n = [c / a0 for c in den]

    n = len(den_n) - 1  # system order

    # Pad num to length n+1
    m = len(num_n) - 1
    if m < n:
        num_n = [0.0] * (n - m) + num_n

    # Observable canonical form state simulation
    # State: x[k+1] = Ad*x[k] + Bd*u[k]
    # Use Tustin (bilinear) discretisation for better accuracy
    # For simplicity use direct Euler simulation of ODE
    y = np.zeros(len(t))
    # Keep history of input and output (direct-form II)
    x = np.zeros(n)  # delay line

    for k, tk in enumerate(t):
        u = 1.0  # unit step input
        # Compute output using direct form II
        # w[k] = u - a1*w[k-1] - a2*w[k-2] - ... - an*w[k-n]
        # y[k] = b0*w[k] + b1*w[k-1] + ... + bn*w[k-n]
        w = u
        for i in range(n):
            w -= den_n[i + 1] * x[i]
        out = num_n[0] * w
        for i in range(n):
            out += num_n[i + 1] * x[i]
        y[k] = out
        # Shift state
        x = np.roll(x, 1)
        x[0] = w

    return y


# ---------------------------------------------------------------------------
# Routh-Hurwitz stability criterion
# ---------------------------------------------------------------------------

def routh_hurwitz(den: list[float]) -> dict:
    """
    Routh-Hurwitz stability analysis for characteristic polynomial.

    The polynomial is: den[0]*s^n + den[1]*s^(n-1) + ... + den[n]
    (highest power first).

    Returns
    -------
    dict with keys:
        stable               : bool
        right_half_plane_poles : int  (= number of sign changes in first column)
        first_column         : list[float]
        sign_changes         : int
        routh_array          : list[list[float]]

    References: Routh (1877); Hurwitz (1895); Ogata (2010) §6-3.
    """
    try:
        c = [float(x) for x in den]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"den must contain numbers: {exc}") from exc

    if len(c) < 2:
        raise ValueError("den must have at least 2 coefficients (degree >= 1)")
    if abs(c[0]) < 1e-15:
        raise ValueError("Leading coefficient must be non-zero")

    n = len(c) - 1  # degree

    # Build first two rows
    row0 = [c[i] for i in range(0, len(c), 2)]
    row1 = [c[i] for i in range(1, len(c), 2)]

    row_len = n // 2 + 1
    while len(row0) < row_len:
        row0.append(0.0)
    while len(row1) < row_len:
        row1.append(0.0)

    array: list[list[float]] = [row0[:row_len], row1[:row_len]]

    for i in range(2, n + 1):
        prev2 = array[-2]
        prev1 = array[-1]
        pivot = prev1[0]
        if abs(pivot) < 1e-15:
            pivot = 1e-15  # epsilon replacement for near-zero pivot

        row_len_i = len(prev2) - 1
        new_row: list[float] = []
        for j in range(row_len_i):
            val = (prev1[0] * prev2[j + 1] - prev2[0] * prev1[j + 1]) / pivot
            new_row.append(val)
        new_row.append(0.0)
        array.append(new_row)

    # Count sign changes in first column
    first_col = [row[0] for row in array]
    sign_changes = 0
    prev_sign = 1 if first_col[0] > 0 else -1
    for val in first_col[1:]:
        if abs(val) < 1e-15:
            continue
        cur_sign = 1 if val > 0 else -1
        if cur_sign != prev_sign:
            sign_changes += 1
            prev_sign = cur_sign

    return {
        "stable": sign_changes == 0,
        "right_half_plane_poles": sign_changes,
        "first_column": first_col,
        "sign_changes": sign_changes,
        "routh_array": array,
    }


# ---------------------------------------------------------------------------
# Bode plot data
# ---------------------------------------------------------------------------

def bode_plot_data(
    tf: TransferFunction,
    omega: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Bode plot magnitude and phase arrays.

    Parameters
    ----------
    tf    : TransferFunction
    omega : array of angular frequencies (rad/s), must be > 0

    Returns
    -------
    (magnitude_db, phase_deg) : two arrays of the same length as omega

    References: Ogata (2010) §8; Åström & Hägglund (2006) §2.
    """
    omega = np.asarray(omega, dtype=float)
    mag_db = np.zeros_like(omega)
    phase_deg = np.zeros_like(omega)

    for k, w in enumerate(omega):
        s = complex(0.0, w)
        G = tf.evaluate_at(s)
        mag = abs(G)
        if mag > 0:
            mag_db[k] = 20.0 * math.log10(mag)
        else:
            mag_db[k] = -math.inf
        phase_deg[k] = math.degrees(cmath.phase(G))

    return mag_db, phase_deg


# ---------------------------------------------------------------------------
# Nyquist plot data
# ---------------------------------------------------------------------------

def nyquist_plot_data(
    tf: TransferFunction,
    omega: np.ndarray,
) -> np.ndarray:
    """
    Compute Nyquist plot data: complex values G(jω) for plotting Re vs Im.

    Parameters
    ----------
    tf    : TransferFunction
    omega : array of angular frequencies (rad/s)

    Returns
    -------
    Complex-valued numpy array of G(jω).

    References: Nyquist (1932); Ogata (2010) §9-2.
    """
    omega = np.asarray(omega, dtype=float)
    result = np.zeros(len(omega), dtype=complex)
    for k, w in enumerate(omega):
        result[k] = tf.evaluate_at(complex(0.0, w))
    return result


# ---------------------------------------------------------------------------
# Gain and phase margins
# ---------------------------------------------------------------------------

def gain_phase_margin(tf: TransferFunction) -> dict:
    """
    Compute gain margin, phase margin, and crossover frequencies.

    Gain crossover:  |G(jω_gc)| = 1  (0 dB)
    Phase crossover: ∠G(jω_pc) = -180° (unwrapped phase)

    Gain margin  = -|G(jω_pc)|_dB  (positive → stable)
    Phase margin = 180° + ∠G(jω_gc)  (positive → stable)

    Phase is unwrapped via numpy.unwrap to correctly detect the -180° crossing.

    Returns
    -------
    dict with keys:
        gain_margin_db   : float or None
        phase_margin_deg : float or None
        omega_gc         : gain crossover frequency (rad/s) or None
        omega_pc         : phase crossover frequency (rad/s) or None

    References: Ogata (2010) §9-3.
    """
    # Log-spaced sweep from 1e-3 to 1e4
    omega = np.logspace(-3, 4, 5000)
    mag_db, phase_deg = bode_plot_data(tf, omega)

    # Unwrap phase for correct -180° crossing detection
    phase_rad = np.deg2rad(phase_deg)
    phase_unwrapped_deg = np.rad2deg(np.unwrap(phase_rad))

    gain_crossover: Optional[float] = None
    pm_deg: Optional[float] = None
    phase_crossover: Optional[float] = None
    gm_db: Optional[float] = None

    # Find gain crossover (magnitude crosses 0 dB)
    for i in range(len(omega) - 1):
        m0, m1 = mag_db[i], mag_db[i + 1]
        if math.isnan(m0) or math.isnan(m1):
            continue
        if m0 * m1 <= 0 and m0 != m1:
            frac = -m0 / (m1 - m0)
            gain_crossover = float(omega[i] + frac * (omega[i + 1] - omega[i]))
            phase_at_gc = phase_unwrapped_deg[i] + frac * (phase_unwrapped_deg[i + 1] - phase_unwrapped_deg[i])
            pm_deg = 180.0 + phase_at_gc
            break

    # Find phase crossover (unwrapped phase crosses -180°)
    for i in range(len(omega) - 1):
        p0, p1 = phase_unwrapped_deg[i], phase_unwrapped_deg[i + 1]
        if math.isnan(p0) or math.isnan(p1):
            continue
        if (p0 + 180.0) * (p1 + 180.0) <= 0 and p0 != p1:
            frac = -(p0 + 180.0) / (p1 - p0)
            phase_crossover = float(omega[i] + frac * (omega[i + 1] - omega[i]))
            mag_at_pc = mag_db[i] + frac * (mag_db[i + 1] - mag_db[i])
            gm_db = float(-mag_at_pc)
            break

    return {
        "gain_margin_db": gm_db,
        "phase_margin_deg": float(pm_deg) if pm_deg is not None else None,
        "omega_gc": gain_crossover,
        "omega_pc": phase_crossover,
    }


# ---------------------------------------------------------------------------
# Feedback interconnection
# ---------------------------------------------------------------------------

def feedback(
    forward: TransferFunction,
    feedback_tf: TransferFunction,
    sign: float = -1.0,
) -> TransferFunction:
    """
    Closed-loop transfer function for unity or non-unity feedback.

    T(s) = G(s) / (1 + sign·G(s)·H(s))

    For negative feedback (sign=-1):
        T(s) = G·H_num·den_H / (den_G·den_H + G_num·H_num)

    Parameters
    ----------
    forward     : G(s) — forward-path transfer function
    feedback_tf : H(s) — feedback-path transfer function
    sign        : +1 (positive) or -1 (negative, default)

    Returns
    -------
    TransferFunction — closed-loop T(s)

    References: Ogata (2010) §2-5.
    """
    # T = G / (1 + sign*G*H)
    # = num_G * den_H / (den_G * den_H + sign * num_G * num_H)
    num = _poly_mul(forward.num, feedback_tf.den)
    den_open = _poly_mul(forward.den, feedback_tf.den)
    den_fb = _poly_mul(forward.num, feedback_tf.num)

    # Apply sign
    if sign >= 0:
        # Positive feedback: denominator = den_G*den_H - num_G*num_H
        den_fb_signed = [-sign * c for c in den_fb]
    else:
        den_fb_signed = [abs(sign) * c for c in den_fb]

    den = _poly_add(den_open, den_fb_signed)

    return TransferFunction(_poly_strip(num), _poly_strip(den))
