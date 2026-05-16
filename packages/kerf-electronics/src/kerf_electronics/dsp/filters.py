"""
DSP & digital filter design — pure-Python (math/cmath only, no numpy).

Functions
---------
FFT / IFFT
  fft(x)                  Radix-2 Cooley-Tukey FFT; x must be power-of-2 length.
  ifft(X)                 Radix-2 IFFT.

Spectral analysis
  dft_spectrum(x, fs)     Magnitude [linear], phase [rad], and frequencies for a
                          real signal using the FFT.
  bin_frequency(k, N, fs) Frequency of DFT bin k.

FIR design (windowed-sinc)
  windowed_sinc_lp(N, fc_norm, window)   Lowpass FIR coefficients.
  windowed_sinc_hp(N, fc_norm, window)   Highpass FIR.
  windowed_sinc_bp(N, fl_norm, fh_norm, window) Bandpass FIR.
  fir_order_estimate(transition_bw_norm, window) Minimum tap count (Kaiser/harris rule).

IIR design (bilinear transform, Butterworth)
  bilinear_butterworth_lp(order, fc_hz, fs_hz)  b, a coefficients (LP).
  bilinear_butterworth_hp(order, fc_hz, fs_hz)  b, a coefficients (HP).

Biquad (RBJ cookbook)
  biquad_lp(fc_hz, fs_hz, Q)      LP biquad b0,b1,b2,a0,a1,a2.
  biquad_hp(fc_hz, fs_hz, Q)      HP biquad.
  biquad_bp(fc_hz, fs_hz, Q)      BP biquad (0 dB at fc).
  biquad_notch(fc_hz, fs_hz, Q)   Notch biquad.
  biquad_peaking(fc_hz, fs_hz, Q, gain_db) Peaking EQ biquad.

Frequency-domain analysis
  freq_response(b, a, freq_hz, fs_hz)  H(e^jω) magnitude [linear], phase [rad].
  group_delay(b, a, freq_hz, fs_hz)    Group delay [samples] at freq_hz.

Sampling & ADC
  nyquist_check(signal_bw_hz, fs_hz)   Aliasing / Nyquist compliance check.
  adc_snr(bits, osr)                   Theoretical SNR [dBFS], ENOB, process gain.

All functions return plain dicts:  {"ok": True, ...}  or  {"ok": False, "reason": ...}.
Warnings (aliasing, unstable poles, non-power-of-2) are issued via the warnings module;
exceptions are never raised to the caller.
"""
from __future__ import annotations

import cmath
import math
import warnings
from typing import List, Sequence, Tuple

# ── helpers ───────────────────────────────────────────────────────────────────

def _is_power_of_2(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def _next_power_of_2(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


def _validate_positive(name: str, value) -> str | None:
    """Return an error string if value is not a positive real number."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if v <= 0:
        return f"{name} must be positive, got {v}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# FFT / IFFT  (radix-2 Cooley-Tukey, power-of-2 only)
# ═══════════════════════════════════════════════════════════════════════════════

def _fft_inplace(x: List[complex], invert: bool) -> None:
    """In-place radix-2 DIT FFT (bit-reversal permutation + butterfly)."""
    n = len(x)
    # Bit-reversal permutation
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            x[i], x[j] = x[j], x[i]
    # Butterfly passes
    length = 2
    while length <= n:
        half = length >> 1
        angle = 2.0 * math.pi / length
        if invert:
            angle = -angle
        w_start = complex(math.cos(angle), math.sin(angle))
        for i in range(0, n, length):
            w = complex(1.0, 0.0)
            for k in range(half):
                u = x[i + k]
                v = x[i + k + half] * w
                x[i + k] = u + v
                x[i + k + half] = u - v
                w *= w_start
        length <<= 1
    if invert:
        inv_n = 1.0 / n
        for i in range(n):
            x[i] *= inv_n


def fft(x: Sequence) -> dict:
    """
    Radix-2 Cooley-Tukey FFT of a real or complex sequence.

    Parameters
    ----------
    x : sequence of real or complex
        Input samples.  Length must be a power of 2.

    Returns
    -------
    {"ok": True, "X": [{"re": ..., "im": ...}, ...], "N": int}
    or
    {"ok": False, "reason": ...}
    """
    try:
        n = len(x)
    except TypeError:
        return {"ok": False, "reason": "x must be a sequence"}
    if n == 0:
        return {"ok": False, "reason": "x must not be empty"}
    if not _is_power_of_2(n):
        warnings.warn(
            f"dsp.fft: input length {n} is not a power of 2; "
            f"zero-pad to {_next_power_of_2(n)} for efficiency.",
            UserWarning,
            stacklevel=2,
        )
        return {"ok": False, "reason": f"length {n} is not a power of 2"}
    try:
        buf = [complex(v) for v in x]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid input: {exc}"}
    _fft_inplace(buf, invert=False)
    return {
        "ok": True,
        "N": n,
        "X": [{"re": c.real, "im": c.imag} for c in buf],
    }


def ifft(X: Sequence) -> dict:
    """
    Radix-2 IFFT.

    Parameters
    ----------
    X : sequence of {"re", "im"} dicts or complex numbers
        Frequency-domain samples.  Length must be a power of 2.

    Returns
    -------
    {"ok": True, "x": [{"re": ..., "im": ...}, ...], "N": int}
    """
    try:
        n = len(X)
    except TypeError:
        return {"ok": False, "reason": "X must be a sequence"}
    if n == 0:
        return {"ok": False, "reason": "X must not be empty"}
    if not _is_power_of_2(n):
        return {"ok": False, "reason": f"length {n} is not a power of 2"}
    try:
        buf = []
        for v in X:
            if isinstance(v, dict):
                buf.append(complex(v["re"], v["im"]))
            else:
                buf.append(complex(v))
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid input element: {exc}"}
    _fft_inplace(buf, invert=True)
    return {
        "ok": True,
        "N": n,
        "x": [{"re": c.real, "im": c.imag} for c in buf],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DFT spectrum
# ═══════════════════════════════════════════════════════════════════════════════

def dft_spectrum(x: Sequence, fs: float) -> dict:
    """
    Compute one-sided magnitude and phase spectrum of a real signal via FFT.

    Parameters
    ----------
    x  : real-valued samples (length must be power of 2)
    fs : sample rate [Hz]

    Returns
    -------
    {"ok": True,
     "N": int,
     "fs_hz": float,
     "freq_hz": [f0, f1, ...],       # N/2+1 positive frequencies
     "magnitude": [...],             # linear amplitude
     "phase_rad": [...],
     "magnitude_db": [...]}
    """
    err = _validate_positive("fs", fs)
    if err:
        return {"ok": False, "reason": err}
    res = fft(x)
    if not res["ok"]:
        return res
    n = res["N"]
    X = res["X"]
    half = n // 2 + 1
    freqs, mags, phases, mags_db = [], [], [], []
    for k in range(half):
        c = complex(X[k]["re"], X[k]["im"])
        # One-sided: scale by 2/N for k>0, 1/N for DC and Nyquist
        scale = 2.0 / n if 0 < k < n // 2 else 1.0 / n
        mag = abs(c) * scale
        freqs.append(k * float(fs) / n)
        mags.append(mag)
        phases.append(cmath.phase(c) if mag > 0 else 0.0)
        mags_db.append(20.0 * math.log10(mag) if mag > 0 else -float("inf"))
    return {
        "ok": True,
        "N": n,
        "fs_hz": float(fs),
        "freq_hz": freqs,
        "magnitude": mags,
        "phase_rad": phases,
        "magnitude_db": mags_db,
    }


def bin_frequency(k: int, N: int, fs: float) -> dict:
    """
    Frequency of DFT bin k.

    Returns
    -------
    {"ok": True, "freq_hz": float, "bin": int, "N": int, "fs_hz": float}
    """
    try:
        k = int(k)
        N = int(N)
        fs = float(fs)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if N <= 0:
        return {"ok": False, "reason": "N must be positive"}
    if fs <= 0:
        return {"ok": False, "reason": "fs must be positive"}
    if k < 0 or k >= N:
        return {"ok": False, "reason": f"bin k={k} out of range [0, {N-1}]"}
    return {"ok": True, "freq_hz": k * fs / N, "bin": k, "N": N, "fs_hz": fs}


# ═══════════════════════════════════════════════════════════════════════════════
# Window functions
# ═══════════════════════════════════════════════════════════════════════════════

_WINDOWS = frozenset({"rect", "hann", "hamming", "blackman"})


def _window_coeff(n: int, N: int, window: str) -> float:
    """Window coefficient w[n] for a length-N window."""
    if window == "rect":
        return 1.0
    elif window == "hann":
        return 0.5 * (1.0 - math.cos(2.0 * math.pi * n / (N - 1)))
    elif window == "hamming":
        return 0.54 - 0.46 * math.cos(2.0 * math.pi * n / (N - 1))
    elif window == "blackman":
        return (
            0.42
            - 0.5 * math.cos(2.0 * math.pi * n / (N - 1))
            + 0.08 * math.cos(4.0 * math.pi * n / (N - 1))
        )
    else:
        raise ValueError(f"unknown window: {window!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# FIR design — windowed-sinc
# ═══════════════════════════════════════════════════════════════════════════════

def windowed_sinc_lp(N: int, fc_norm: float, window: str = "hamming") -> dict:
    """
    Design a lowpass FIR filter using the windowed-sinc method.

    Parameters
    ----------
    N        : Number of taps (should be odd for Type-I FIR; even accepted with warning).
    fc_norm  : Normalised cutoff frequency in (0, 0.5)  [fc / fs].
    window   : One of "rect", "hann", "hamming", "blackman".

    Returns
    -------
    {"ok": True, "N": int, "fc_norm": float, "window": str, "h": [float, ...]}
    """
    try:
        N = int(N)
        fc_norm = float(fc_norm)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if N < 1:
        return {"ok": False, "reason": "N must be >= 1"}
    if not (0.0 < fc_norm < 0.5):
        return {"ok": False, "reason": "fc_norm must be in (0, 0.5)"}
    if window not in _WINDOWS:
        return {"ok": False, "reason": f"window must be one of {sorted(_WINDOWS)}"}
    if N % 2 == 0:
        warnings.warn(
            "windowed_sinc_lp: even tap count; consider using odd N for symmetric FIR.",
            UserWarning,
            stacklevel=2,
        )
    M = N - 1
    h = []
    for n in range(N):
        m = n - M / 2.0
        if m == 0.0:
            ideal = 2.0 * fc_norm
        else:
            ideal = math.sin(2.0 * math.pi * fc_norm * m) / (math.pi * m)
        w = _window_coeff(n, N, window)
        h.append(ideal * w)
    return {"ok": True, "N": N, "fc_norm": fc_norm, "window": window, "h": h}


def windowed_sinc_hp(N: int, fc_norm: float, window: str = "hamming") -> dict:
    """
    Design a highpass FIR filter (spectral inversion of LP prototype).

    Parameters
    ----------
    N, fc_norm, window : same as windowed_sinc_lp.

    Returns
    -------
    {"ok": True, "N": int, "fc_norm": float, "window": str, "h": [float, ...]}
    """
    lp = windowed_sinc_lp(N, fc_norm, window)
    if not lp["ok"]:
        return lp
    if N % 2 == 0:
        return {"ok": False, "reason": "highpass FIR requires odd N (Type-I)"}
    h = lp["h"]
    M = N - 1
    center = M // 2
    hp = [-v for v in h]
    hp[center] += 1.0
    return {"ok": True, "N": N, "fc_norm": fc_norm, "window": window, "h": hp}


def windowed_sinc_bp(
    N: int, fl_norm: float, fh_norm: float, window: str = "hamming"
) -> dict:
    """
    Design a bandpass FIR (difference of two LP filters).

    Parameters
    ----------
    N        : Number of taps (must be odd).
    fl_norm  : Lower normalised cutoff in (0, 0.5).
    fh_norm  : Upper normalised cutoff in (0, 0.5), must be > fl_norm.
    window   : One of "rect", "hann", "hamming", "blackman".

    Returns
    -------
    {"ok": True, "N": int, "fl_norm": float, "fh_norm": float,
     "window": str, "h": [float, ...]}
    """
    try:
        N = int(N)
        fl_norm = float(fl_norm)
        fh_norm = float(fh_norm)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if fl_norm >= fh_norm:
        return {"ok": False, "reason": "fl_norm must be less than fh_norm"}
    lp_hi = windowed_sinc_lp(N, fh_norm, window)
    if not lp_hi["ok"]:
        return lp_hi
    lp_lo = windowed_sinc_lp(N, fl_norm, window)
    if not lp_lo["ok"]:
        return lp_lo
    h = [lp_hi["h"][i] - lp_lo["h"][i] for i in range(N)]
    return {
        "ok": True,
        "N": N,
        "fl_norm": fl_norm,
        "fh_norm": fh_norm,
        "window": window,
        "h": h,
    }


def fir_order_estimate(
    transition_bw_norm: float, window: str = "hamming"
) -> dict:
    """
    Estimate minimum FIR tap count using the Kaiser / fred-harris rule-of-thumb.

    Rules (N = ceil(A / (Δf))):
      rect:      A = 0.9
      hann:      A = 3.1
      hamming:   A = 3.3
      blackman:  A = 5.5

    Parameters
    ----------
    transition_bw_norm : Normalised transition bandwidth  [Δf / fs].
    window             : Window type.

    Returns
    -------
    {"ok": True, "N_estimate": int, "window": str, "transition_bw_norm": float}
    """
    _HARRIS_A = {
        "rect": 0.9,
        "hann": 3.1,
        "hamming": 3.3,
        "blackman": 5.5,
    }
    try:
        transition_bw_norm = float(transition_bw_norm)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid transition_bw_norm: {exc}"}
    if window not in _WINDOWS:
        return {"ok": False, "reason": f"window must be one of {sorted(_WINDOWS)}"}
    if transition_bw_norm <= 0:
        return {"ok": False, "reason": "transition_bw_norm must be positive"}
    if transition_bw_norm >= 0.5:
        return {"ok": False, "reason": "transition_bw_norm must be < 0.5"}
    A = _HARRIS_A[window]
    N_exact = A / transition_bw_norm
    N = int(math.ceil(N_exact))
    if N % 2 == 0:
        N += 1  # ensure odd for symmetric FIR
    return {
        "ok": True,
        "N_estimate": N,
        "window": window,
        "transition_bw_norm": transition_bw_norm,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# IIR design — bilinear-transform Butterworth (LP / HP)
# ═══════════════════════════════════════════════════════════════════════════════

def _butterworth_analog_poles(n: int) -> List[complex]:
    """Normalised analog Butterworth LP poles (unit cutoff, LHP)."""
    poles = []
    for k in range(1, n + 1):
        angle = math.pi * (2 * k + n - 1) / (2 * n)
        poles.append(complex(math.cos(angle), math.sin(angle)))
    return poles


def _poly_from_roots(roots: List[complex]) -> List[complex]:
    """Expand monic polynomial from roots: prod(z - r_k)."""
    poly = [complex(1.0)]
    for r in roots:
        new_poly = [complex(0.0)] * (len(poly) + 1)
        for i, coef in enumerate(poly):
            new_poly[i] += coef
            new_poly[i + 1] -= coef * r
    poly = [complex(1.0)]
    for r in roots:
        new_poly = [complex(0.0)] * (len(poly) + 1)
        for i, coef in enumerate(poly):
            new_poly[i] += coef
            new_poly[i + 1] -= coef * r
        poly = new_poly
    return poly


def _bilinear_lp(n: int, wc_prewarp: float) -> Tuple[List[float], List[float]]:
    """
    Bilinear-transform LP Butterworth.  Returns (b, a) where len(b)=len(a)=n+1.
    wc_prewarp : prewarped analog cutoff [rad/s].
    """
    # Analog prototype poles at unit cutoff, scaled to wc
    s_poles = [wc_prewarp * p for p in _butterworth_analog_poles(n)]
    # Map s → z via bilinear: s = 2*(z-1)/(z+1)  (T=1 normalised, fs=2 rad/s)
    # In terms of normalised: s_d = 2*fs*(z-1)/(z+1), so use wc_prewarp directly.
    # Digital poles: z_k = (1 + s_k/2) / (1 - s_k/2)
    z_poles = [(1.0 + p / 2.0) / (1.0 - p / 2.0) for p in s_poles]
    # Check stability
    for zp in z_poles:
        if abs(zp) >= 1.0:
            warnings.warn(
                f"dsp.bilinear: pole |z|={abs(zp):.4f} ≥ 1 — unstable filter.",
                UserWarning,
                stacklevel=4,
            )
    # All-pole LP denominator
    denom = _poly_from_roots(z_poles)
    # Numerator: (1 + z^{-1})^n  → coefficients [1, n, C(n,2), ...]
    numer_coeffs = [1.0]
    for k in range(1, n + 1):
        numer_coeffs.append(numer_coeffs[-1] * (n - k + 1) / k)
    # Normalise gain at DC (z=1): H(1)=1
    b_raw = [complex(c) for c in numer_coeffs]
    a_raw = denom
    h_dc_b = sum(b_raw)
    h_dc_a = sum(a_raw)
    gain = (h_dc_a / h_dc_b).real
    b = [c.real * gain for c in b_raw]
    a = [c.real for c in a_raw]
    return b, a


def bilinear_butterworth_lp(order: int, fc_hz: float, fs_hz: float) -> dict:
    """
    Design a digital Butterworth lowpass IIR filter via bilinear transform.

    Parameters
    ----------
    order  : Filter order (1–10).
    fc_hz  : −3 dB cutoff frequency [Hz].
    fs_hz  : Sample rate [Hz].

    Returns
    -------
    {"ok": True, "order": int, "fc_hz": float, "fs_hz": float,
     "b": [...], "a": [...],
     "fc_norm": float, "fc_prewarped_hz": float}
    """
    try:
        order = int(order)
        fc_hz = float(fc_hz)
        fs_hz = float(fs_hz)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if order < 1 or order > 10:
        return {"ok": False, "reason": "order must be in [1, 10]"}
    err = _validate_positive("fc_hz", fc_hz)
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive("fs_hz", fs_hz)
    if err:
        return {"ok": False, "reason": err}
    if fc_hz >= fs_hz / 2.0:
        warnings.warn(
            f"dsp.bilinear_butterworth_lp: fc_hz={fc_hz} >= Nyquist={fs_hz/2}.",
            UserWarning,
            stacklevel=2,
        )
        return {"ok": False, "reason": f"fc_hz must be < Nyquist ({fs_hz/2} Hz)"}
    # Frequency prewarping: wc_a = 2*fs * tan(pi * fc / fs)
    wc_prewarp = 2.0 * fs_hz * math.tan(math.pi * fc_hz / fs_hz)
    b, a = _bilinear_lp(order, wc_prewarp / (2.0 * fs_hz) * 2.0)
    # Recompute with correct normalisation (use unit fs=1, then scale)
    # Reuse: bilinear maps s → z with T=1/fs; prewarp at digital freq wd=2pi*fc/fs
    wd = 2.0 * math.pi * fc_hz / fs_hz
    wc_a = 2.0 * math.tan(wd / 2.0)  # analog cutoff in units where T=1
    b, a = _bilinear_lp(order, wc_a)
    return {
        "ok": True,
        "order": order,
        "fc_hz": fc_hz,
        "fs_hz": fs_hz,
        "fc_norm": fc_hz / fs_hz,
        "fc_prewarped_hz": (wc_prewarp / (2.0 * math.pi)),
        "b": b,
        "a": a,
    }


def bilinear_butterworth_hp(order: int, fc_hz: float, fs_hz: float) -> dict:
    """
    Design a digital Butterworth highpass IIR filter via bilinear transform.

    Maps analog LP prototype poles to HP digital poles via LP->HP transformation:
      s_hp = wc_a^2 / s_lp  (unit cutoff LP prototype scaled to wc_a).
    Then bilinear: z = (1 + s/2) / (1 - s/2).

    Returns
    -------
    {"ok": True, "order": int, "fc_hz": float, "fs_hz": float,
     "b": [...], "a": [...],
     "fc_norm": float, "fc_prewarped_hz": float}
    """
    try:
        order = int(order)
        fc_hz = float(fc_hz)
        fs_hz = float(fs_hz)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if order < 1 or order > 10:
        return {"ok": False, "reason": "order must be in [1, 10]"}
    err = _validate_positive("fc_hz", fc_hz)
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive("fs_hz", fs_hz)
    if err:
        return {"ok": False, "reason": err}
    if fc_hz >= fs_hz / 2.0:
        warnings.warn(
            f"dsp.bilinear_butterworth_hp: fc_hz={fc_hz} >= Nyquist={fs_hz/2}.",
            UserWarning,
            stacklevel=2,
        )
        return {"ok": False, "reason": f"fc_hz must be < Nyquist ({fs_hz/2} Hz)"}
    # Frequency prewarping
    wd = 2.0 * math.pi * fc_hz / fs_hz
    wc_a = 2.0 * math.tan(wd / 2.0)  # analog cutoff (T=1 normalised)
    # LP prototype poles at unit cutoff
    lp_poles = _butterworth_analog_poles(order)
    # LP-to-HP transformation: each LP pole p -> HP analog pole wc_a / p
    hp_analog_poles = [wc_a / p for p in lp_poles]
    # Bilinear: z = (1 + s/2) / (1 - s/2)
    z_poles = [(1.0 + p / 2.0) / (1.0 - p / 2.0) for p in hp_analog_poles]
    for zp in z_poles:
        if abs(zp) >= 1.0:
            warnings.warn(
                f"dsp.bilinear_butterworth_hp: pole |z|={abs(zp):.4f} >= 1.",
                UserWarning,
                stacklevel=2,
            )
    # Build denominator polynomial from digital poles
    denom = _poly_from_roots(z_poles)
    # HP numerator: (1 - z^{-1})^n evaluated as polynomial in z^{-1}
    # Coefficients: binom(n, k) * (-1)^k
    numer_coeffs = []
    for k in range(order + 1):
        # binomial(n, k) * (-1)^k
        bk = 1
        for i in range(k):
            bk = bk * (order - i) // (i + 1)
        numer_coeffs.append(float(bk) * ((-1.0) ** k))
    b_raw = [complex(c) for c in numer_coeffs]
    a_raw = denom
    # Evaluate at z = -1 (Nyquist) to normalise gain to unity
    def eval_at_zm1(coeffs):
        """Evaluate polynomial in z^{-1} at z=-1: sum c[k] * (-1)^k."""
        return sum(c * ((-1.0) ** k) for k, c in enumerate(coeffs))
    h_ny_b = eval_at_zm1(b_raw)
    h_ny_a = eval_at_zm1(a_raw)
    if abs(h_ny_b) < 1e-30:
        gain = 1.0
    else:
        gain = (h_ny_a / h_ny_b).real
    b = [c.real * gain for c in b_raw]
    a = [c.real for c in a_raw]
    return {
        "ok": True,
        "order": order,
        "fc_hz": fc_hz,
        "fs_hz": fs_hz,
        "fc_norm": fc_hz / fs_hz,
        "fc_prewarped_hz": wc_a / (2.0 * math.pi),
        "b": b,
        "a": a,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Biquad sections — RBJ Audio EQ Cookbook
# (Robert Bristow-Johnson, rev. 2.0)
# ═══════════════════════════════════════════════════════════════════════════════

def _biquad_common(fc_hz: float, fs_hz: float, Q: float):
    """Validate & compute shared intermediate values for RBJ biquads."""
    try:
        fc_hz = float(fc_hz)
        fs_hz = float(fs_hz)
        Q = float(Q)
    except (TypeError, ValueError) as exc:
        return None, None, None, None, f"invalid argument: {exc}"
    if fc_hz <= 0:
        return None, None, None, None, "fc_hz must be positive"
    if fs_hz <= 0:
        return None, None, None, None, "fs_hz must be positive"
    if Q <= 0:
        return None, None, None, None, "Q must be positive"
    if fc_hz >= fs_hz / 2.0:
        warnings.warn(
            f"dsp.biquad: fc_hz={fc_hz} >= Nyquist={fs_hz/2}.",
            UserWarning,
            stacklevel=3,
        )
        return None, None, None, None, f"fc_hz must be < Nyquist ({fs_hz/2} Hz)"
    w0 = 2.0 * math.pi * fc_hz / fs_hz
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * Q)
    return w0, cos_w0, sin_w0, alpha, None


def _normalise_biquad(b0, b1, b2, a0, a1, a2) -> dict:
    """Normalise RBJ biquad so that a[0]=1."""
    return {
        "ok": True,
        "b": [b0 / a0, b1 / a0, b2 / a0],
        "a": [1.0, a1 / a0, a2 / a0],
    }


def biquad_lp(fc_hz: float, fs_hz: float, Q: float = 0.7071) -> dict:
    """
    RBJ lowpass biquad.

    H(z) = (1 - cos(w0))/2 * (1 + 2z^-1 + z^-2) / (...)

    Returns
    -------
    {"ok": True, "b": [b0,b1,b2], "a": [1,a1,a2], "fc_hz": float, "Q": float}
    """
    w0, cos_w0, sin_w0, alpha, err = _biquad_common(fc_hz, fs_hz, Q)
    if err:
        return {"ok": False, "reason": err}
    b0 = (1.0 - cos_w0) / 2.0
    b1 = 1.0 - cos_w0
    b2 = (1.0 - cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    res = _normalise_biquad(b0, b1, b2, a0, a1, a2)
    res.update({"fc_hz": fc_hz, "fs_hz": fs_hz, "Q": Q})
    return res


def biquad_hp(fc_hz: float, fs_hz: float, Q: float = 0.7071) -> dict:
    """RBJ highpass biquad."""
    w0, cos_w0, sin_w0, alpha, err = _biquad_common(fc_hz, fs_hz, Q)
    if err:
        return {"ok": False, "reason": err}
    b0 = (1.0 + cos_w0) / 2.0
    b1 = -(1.0 + cos_w0)
    b2 = (1.0 + cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    res = _normalise_biquad(b0, b1, b2, a0, a1, a2)
    res.update({"fc_hz": fc_hz, "fs_hz": fs_hz, "Q": Q})
    return res


def biquad_bp(fc_hz: float, fs_hz: float, Q: float = 1.0) -> dict:
    """RBJ bandpass biquad (peak gain = 0 dB at fc)."""
    w0, cos_w0, sin_w0, alpha, err = _biquad_common(fc_hz, fs_hz, Q)
    if err:
        return {"ok": False, "reason": err}
    b0 = sin_w0 / 2.0
    b1 = 0.0
    b2 = -sin_w0 / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    res = _normalise_biquad(b0, b1, b2, a0, a1, a2)
    res.update({"fc_hz": fc_hz, "fs_hz": fs_hz, "Q": Q})
    return res


def biquad_notch(fc_hz: float, fs_hz: float, Q: float = 1.0) -> dict:
    """RBJ notch biquad."""
    w0, cos_w0, sin_w0, alpha, err = _biquad_common(fc_hz, fs_hz, Q)
    if err:
        return {"ok": False, "reason": err}
    b0 = 1.0
    b1 = -2.0 * cos_w0
    b2 = 1.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    res = _normalise_biquad(b0, b1, b2, a0, a1, a2)
    res.update({"fc_hz": fc_hz, "fs_hz": fs_hz, "Q": Q})
    return res


def biquad_peaking(
    fc_hz: float, fs_hz: float, Q: float = 1.0, gain_db: float = 6.0
) -> dict:
    """
    RBJ peaking EQ biquad.

    Parameters
    ----------
    gain_db : Boost (+) or cut (−) at fc in dB.
    """
    w0, cos_w0, sin_w0, alpha_raw, err = _biquad_common(fc_hz, fs_hz, Q)
    if err:
        return {"ok": False, "reason": err}
    try:
        gain_db = float(gain_db)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid gain_db: {exc}"}
    A = 10.0 ** (gain_db / 40.0)
    alpha = sin_w0 / (2.0 * Q)
    b0 = 1.0 + alpha * A
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / A
    res = _normalise_biquad(b0, b1, b2, a0, a1, a2)
    res.update({"fc_hz": fc_hz, "fs_hz": fs_hz, "Q": Q, "gain_db": gain_db})
    return res


# ═══════════════════════════════════════════════════════════════════════════════
# Frequency response H(e^jω) from b/a coefficients
# ═══════════════════════════════════════════════════════════════════════════════

def freq_response(
    b: Sequence[float],
    a: Sequence[float],
    freq_hz: float,
    fs_hz: float,
) -> dict:
    """
    Evaluate H(e^{jω}) at a single frequency.

    Parameters
    ----------
    b, a     : Filter coefficients (numerator / denominator).
    freq_hz  : Frequency to evaluate [Hz].
    fs_hz    : Sample rate [Hz].

    Returns
    -------
    {"ok": True,
     "freq_hz": float,
     "magnitude": float,     # linear
     "magnitude_db": float,
     "phase_rad": float,
     "H_re": float,
     "H_im": float}
    """
    try:
        b = [float(v) for v in b]
        a = [float(v) for v in a]
        freq_hz = float(freq_hz)
        fs_hz = float(fs_hz)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if fs_hz <= 0:
        return {"ok": False, "reason": "fs_hz must be positive"}
    if freq_hz < 0 or freq_hz > fs_hz / 2.0:
        return {"ok": False, "reason": f"freq_hz must be in [0, {fs_hz/2}]"}
    w = 2.0 * math.pi * freq_hz / fs_hz
    z = cmath.exp(1j * w)
    # Evaluate numerator and denominator as polynomials in z^{-1}
    def poly_z(coeffs: List[float]) -> complex:
        acc = complex(0.0)
        zk = complex(1.0)
        for c in coeffs:
            acc += c * zk
            zk /= z  # z^{-k}
        return acc
    H_num = poly_z(b)
    H_den = poly_z(a)
    if abs(H_den) < 1e-300:
        return {"ok": False, "reason": "denominator is zero at this frequency (pole)"}
    H = H_num / H_den
    mag = abs(H)
    mag_db = 20.0 * math.log10(mag) if mag > 0 else -float("inf")
    return {
        "ok": True,
        "freq_hz": freq_hz,
        "fs_hz": fs_hz,
        "magnitude": mag,
        "magnitude_db": mag_db,
        "phase_rad": cmath.phase(H),
        "H_re": H.real,
        "H_im": H.imag,
    }


def group_delay(
    b: Sequence[float],
    a: Sequence[float],
    freq_hz: float,
    fs_hz: float,
    delta_hz: float = 1.0,
) -> dict:
    """
    Approximate group delay at freq_hz by central difference of phase.

    τ_g(ω) ≈ −dφ/dω ≈ −(φ(ω+Δ) − φ(ω−Δ)) / (2Δω)   [samples]

    Returns
    -------
    {"ok": True, "group_delay_samples": float, "group_delay_s": float,
     "freq_hz": float, "fs_hz": float}
    """
    try:
        freq_hz = float(freq_hz)
        fs_hz = float(fs_hz)
        delta_hz = float(delta_hz)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if delta_hz <= 0:
        return {"ok": False, "reason": "delta_hz must be positive"}
    # Upper point
    f_hi = min(freq_hz + delta_hz, fs_hz / 2.0 - 1e-9)
    f_lo = max(freq_hz - delta_hz, 0.0 + 1e-9)
    r_hi = freq_response(b, a, f_hi, fs_hz)
    r_lo = freq_response(b, a, f_lo, fs_hz)
    if not r_hi.get("ok") or not r_lo.get("ok"):
        return {"ok": False, "reason": "freq_response failed at delta points"}
    dphi = r_hi["phase_rad"] - r_lo["phase_rad"]
    # Unwrap large jumps
    while dphi > math.pi:
        dphi -= 2.0 * math.pi
    while dphi < -math.pi:
        dphi += 2.0 * math.pi
    dw = 2.0 * math.pi * (f_hi - f_lo) / fs_hz
    if abs(dw) < 1e-30:
        return {"ok": False, "reason": "delta_hz too small"}
    gd_samples = -dphi / dw
    return {
        "ok": True,
        "freq_hz": freq_hz,
        "fs_hz": fs_hz,
        "group_delay_samples": gd_samples,
        "group_delay_s": gd_samples / fs_hz,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Sampling & Nyquist check
# ═══════════════════════════════════════════════════════════════════════════════

def nyquist_check(signal_bw_hz: float, fs_hz: float) -> dict:
    """
    Check whether the sample rate satisfies the Nyquist criterion.

    Parameters
    ----------
    signal_bw_hz : Highest frequency component in the signal [Hz].
    fs_hz        : Sample rate [Hz].

    Returns
    -------
    {"ok": True,
     "nyquist_hz": float,
     "oversampling_ratio": float,
     "alias_free": bool,
     "recommended_fs_hz": float,
     "warnings": list[str]}
    """
    try:
        signal_bw_hz = float(signal_bw_hz)
        fs_hz = float(fs_hz)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if signal_bw_hz <= 0:
        return {"ok": False, "reason": "signal_bw_hz must be positive"}
    if fs_hz <= 0:
        return {"ok": False, "reason": "fs_hz must be positive"}
    nyquist = fs_hz / 2.0
    osr = fs_hz / (2.0 * signal_bw_hz)
    alias_free = fs_hz > 2.0 * signal_bw_hz
    warns = []
    if not alias_free:
        msg = (
            f"Aliasing: fs={fs_hz} Hz ≤ 2×{signal_bw_hz} Hz (Nyquist rate). "
            "Increase fs or apply anti-alias filter."
        )
        warnings.warn(msg, UserWarning, stacklevel=2)
        warns.append(msg)
    elif osr < 2.0:
        msg = f"Marginally oversampled (OSR={osr:.2f}). Consider ≥2× oversampling."
        warnings.warn(msg, UserWarning, stacklevel=2)
        warns.append(msg)
    return {
        "ok": True,
        "signal_bw_hz": signal_bw_hz,
        "fs_hz": fs_hz,
        "nyquist_hz": nyquist,
        "oversampling_ratio": osr,
        "alias_free": alias_free,
        "recommended_fs_hz": 2.0 * signal_bw_hz * 1.1,  # 10% guard band
        "warnings": warns,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ADC quantisation SNR / ENOB / process gain
# ═══════════════════════════════════════════════════════════════════════════════

def adc_snr(bits: int, osr: float = 1.0) -> dict:
    """
    Theoretical ADC performance metrics.

    Parameters
    ----------
    bits : ADC resolution (number of bits, 1–32).
    osr  : Oversampling ratio (≥ 1).  For a sigma-delta or decimated ADC.
           Process gain = 10×log10(osr) / 2  [dB].

    Returns
    -------
    {"ok": True,
     "bits": int,
     "osr": float,
     "snr_ideal_db": float,        # 6.02×N + 1.76 dB (full-scale sine)
     "process_gain_db": float,     # 10×log10(osr)/2
     "snr_with_osr_db": float,
     "enob": float,                # (SNR_with_osr − 1.76) / 6.02
     "dynamic_range_db": float}
    """
    try:
        bits = int(bits)
        osr = float(osr)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"invalid argument: {exc}"}
    if bits < 1 or bits > 32:
        return {"ok": False, "reason": "bits must be in [1, 32]"}
    if osr < 1.0:
        return {"ok": False, "reason": "osr must be >= 1.0"}
    snr_ideal = 6.0206 * bits + 1.7609  # exact coefficients
    process_gain = 10.0 * math.log10(osr) / 2.0  # 3 dB per octave of OSR
    snr_total = snr_ideal + process_gain
    enob = (snr_total - 1.7609) / 6.0206
    dynamic_range = 20.0 * math.log10(2.0 ** bits)
    return {
        "ok": True,
        "bits": bits,
        "osr": osr,
        "snr_ideal_db": snr_ideal,
        "process_gain_db": process_gain,
        "snr_with_osr_db": snr_total,
        "enob": enob,
        "dynamic_range_db": dynamic_range,
    }
