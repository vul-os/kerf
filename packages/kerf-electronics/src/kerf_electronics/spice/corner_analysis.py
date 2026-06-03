"""corner_analysis.py — Statistical Monte-Carlo / PVT corner sweep.

Implements:
  * Standard 5-corner process model (TT / SS / FF / SF / FS)
  * PVT sweep: voltage (±10%), temperature (−40, 27, 125 °C)
  * Monte-Carlo with Pelgrom (1989) local matching variation
  * Yield estimation against user-supplied Id specification

HONEST DISCLAIMER
-----------------
Process corners and Monte-Carlo variances are representative estimates based
on published BSIM4.8 parameter sensitivities and Pelgrom matching coefficients.
They are NOT calibrated to any real foundry PDK.  Commercial sign-off requires
foundry-supplied corner decks.  This implementation is suitable for design
exploration, architecture trade-off analysis, and educational use only.

References:
  BSIM4.8 Technical Manual, UC Berkeley, 2013 (process parameter sensitivity).
  Pelgrom, M.J.M., Duinmaijer, A.C.J., Welbers, A.P.G. (1989).
    "Matching properties of MOS transistors."
    IEEE Journal of Solid-State Circuits, 24(5), 1433–1439.
  Hastings, R.A. (2006). The Art of Analog Layout, 2e. Prentice Hall.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from kerf_electronics.spice.bsim4_model import (
    Bsim4Geometry,
    Bsim4Parameters,
    id_bsim4,
)


# ---------------------------------------------------------------------------
# Box-Muller Gaussian RNG (pure Python, no numpy/scipy)
# ---------------------------------------------------------------------------

class _BoxMullerRng:
    """Deterministic Gaussian RNG using the Box-Muller transform.

    Seeded with a simple LCG so results are reproducible.
    """

    # Knuth / POSIX LCG constants
    _A = 1664525
    _C = 1013904223
    _M = 2 ** 32

    def __init__(self, seed: int = 0) -> None:
        self._state = (seed ^ 0xDEADBEEF) % self._M
        self._spare: Optional[float] = None

    def _lcg(self) -> float:
        """Advance LCG and return uniform in (0, 1)."""
        self._state = (self._A * self._state + self._C) % self._M
        return (self._state + 0.5) / self._M  # (0, 1) exclusive

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        """Return a Gaussian-distributed variate N(mu, sigma²)."""
        if self._spare is not None:
            z = self._spare
            self._spare = None
            return mu + sigma * z
        # Box-Muller
        u1 = self._lcg()
        u2 = self._lcg()
        mag = math.sqrt(-2.0 * math.log(u1))
        z0  = mag * math.cos(2.0 * math.pi * u2)
        z1  = mag * math.sin(2.0 * math.pi * u2)
        self._spare = z1
        return mu + sigma * z0


# ---------------------------------------------------------------------------
# Process corner definitions
# ---------------------------------------------------------------------------

@dataclass
class ProcessCorner:
    """One process corner — deltas applied multiplicatively to BSIM4 params.

    Convention (Pelgrom 1989 + BSIM4 §8 sensitivity):
      vth_delta_pct  > 0 → Vth higher (SLOW NMOS) or lower (FAST NMOS)
      mobility_delta_pct > 0 → μ higher (FAST)

    Signs follow standard foundry convention:
      SS: Vth↑, μ↓  (slow-slow, both slow)
      FF: Vth↓, μ↑  (fast-fast, both fast)
      SF: Vth↑, μ↑  (slow Vth, fast β — unusual corner)
      FS: Vth↓, μ↓  (fast Vth, slow β — unusual corner)
    """

    name: str
    vth_delta_pct: float          # % shift applied to vth0; positive = higher Vth
    mobility_delta_pct: float     # % shift applied to u0; positive = higher mobility
    tox_delta_pct: float = 0.0    # % shift applied to tox (thicker → slower)

    @staticmethod
    def apply(corner: "ProcessCorner", base: Bsim4Parameters) -> Bsim4Parameters:
        """Return a new Bsim4Parameters with corner deltas applied."""
        import dataclasses
        p = dataclasses.replace(base)
        p.vth0 = base.vth0 * (1.0 + corner.vth_delta_pct / 100.0)
        p.u0   = base.u0   * (1.0 + corner.mobility_delta_pct / 100.0)
        p.tox  = base.tox  * (1.0 + corner.tox_delta_pct / 100.0)
        p.toxe = base.toxe * (1.0 + corner.tox_delta_pct / 100.0)
        return p


DEFAULT_CORNERS: List[ProcessCorner] = [
    ProcessCorner("TT",  0.0,   0.0,   0.0),   # Typical-typical (nominal)
    ProcessCorner("SS",  5.0,  -5.0,   3.0),   # Slow-slow: high Vth, low μ, thick tox
    ProcessCorner("FF", -5.0,   5.0,  -3.0),   # Fast-fast: low Vth, high μ, thin tox
    ProcessCorner("SF",  5.0,   5.0,   0.0),   # Slow Vth / Fast β
    ProcessCorner("FS", -5.0,  -5.0,   0.0),   # Fast Vth / Slow β
]


# ---------------------------------------------------------------------------
# PVT sweep specification
# ---------------------------------------------------------------------------

@dataclass
class PvtSweepSpec:
    """Full PVT sweep specification.

    Defaults cover:
      * All 5 standard process corners
      * ±10% VDD variation (0.9 V, 1.0 V, 1.1 V) — typical 1 V core
      * Military/automotive temperature range: −40, 27, 125 °C
      * 100 Monte-Carlo iterations per (corner, V, T) point
    """

    process_corners: List[ProcessCorner] = field(
        default_factory=lambda: list(DEFAULT_CORNERS)
    )
    voltages_vdd: List[float] = field(
        default_factory=lambda: [0.9, 1.0, 1.1]
    )
    temperatures_c: List[float] = field(
        default_factory=lambda: [-40.0, 27.0, 125.0]
    )
    monte_carlo_iterations: int = 100


# ---------------------------------------------------------------------------
# Sweep result
# ---------------------------------------------------------------------------

@dataclass
class CornerSweepReport:
    """Result of a full PVT / Monte-Carlo corner sweep.

    Fields:
      sweeps          — one row dict per (corner, vdd, T_c, mc_iter) sample
      worst_id_pct    — max |% deviation from TT/nominal Id| across all sweeps
      worst_pvt       — (corner_name, vdd, T_c) at worst_id_pct
      yield_estimate  — fraction of MC samples that meet spec_min_id (0..1);
                        1.0 if no spec supplied
      nominal_id      — Id at TT / nominal vdd / nominal T (reference point)

    HONEST NOTE: yield_estimate is a statistical estimate from a limited
    Monte-Carlo sample.  Not foundry-PDK sign-off accuracy.
    """

    sweeps: List[dict]
    worst_id_pct: float
    worst_pvt: Tuple[str, float, float]
    yield_estimate: float
    nominal_id: float


# ---------------------------------------------------------------------------
# Core sweep runner
# ---------------------------------------------------------------------------

def run_pvt_corner_sweep(
    params: Bsim4Parameters,
    geom: Bsim4Geometry,
    vgs: float,
    vds: float,
    vbs: float,
    spec: Optional[PvtSweepSpec] = None,
    spec_min_id: Optional[float] = None,
    rng_seed: int = 0,
) -> CornerSweepReport:
    """Run a full PVT + Monte-Carlo corner sweep via BSIM4 Id.

    For each (process_corner, vdd, T, mc_iteration):
      1. Apply corner delta to params → perturbed_params
      2. Scale vgs/vds/vbs by vdd/nominal_vdd (supply-referred biasing)
      3. Add Pelgrom (1989) local mismatch to Vth and β via Gaussian draws
      4. Call id_bsim4 → record in sweeps list

    Yield = fraction of rows with Id ≥ spec_min_id (if provided).

    HONEST NOTE: This is an analytical perturbation model, not a SPICE
    Monte-Carlo simulation with a foundry PDK.  Not suitable for tape-out
    sign-off.  For design exploration and statistical insight only.

    References:
      Pelgrom 1989 IEEE JSSC 24(5) — matching model, eqs. 4, 6.
      BSIM4.8 Technical Manual, UC Berkeley, 2013.
    """
    if spec is None:
        spec = PvtSweepSpec()

    rng = _BoxMullerRng(seed=rng_seed)

    # Nominal operating conditions — TT / mid-voltage / 27°C
    nominal_vdd   = spec.voltages_vdd[len(spec.voltages_vdd) // 2]
    nominal_T_c   = 27.0
    nominal_T_K   = nominal_T_c + 273.15

    # Reference Id at TT / nominal V / nominal T (no mismatch)
    nominal_id = id_bsim4(vgs, vds, vbs, nominal_T_K, params, geom)

    # Pelgrom matching sigma (Pelgrom 1989, eqs. 4 & 6)
    # σ(ΔVth) = AVT0 / sqrt(W·L)
    # σ(Δβ/β) = ABETA / sqrt(W·L)
    WL = geom.W * geom.L * max(geom.nf, 1)
    sigma_vth   = params.avt0  / math.sqrt(max(WL, 1e-20))   # V
    sigma_beta  = params.abeta / math.sqrt(max(WL, 1e-20))   # fractional

    sweeps: List[dict] = []
    pass_count = 0
    total_mc   = 0

    for corner in spec.process_corners:
        corner_params = ProcessCorner.apply(corner, params)

        for vdd in spec.voltages_vdd:
            # Scale bias voltages proportionally to supply
            vdd_ratio = vdd / max(nominal_vdd, 1e-9)
            vgs_s = vgs * vdd_ratio
            vds_s = vds * vdd_ratio
            vbs_s = vbs  # body bias typically fixed

            for T_c in spec.temperatures_c:
                T_K = T_c + 273.15

                for mc_iter in range(spec.monte_carlo_iterations):
                    total_mc += 1

                    # Pelgrom mismatch perturbations (Pelgrom 1989 eqs. 4, 6)
                    dvth  = rng.gauss(0.0, sigma_vth)
                    dbeta = rng.gauss(0.0, sigma_beta)

                    # Build perturbed params
                    import dataclasses
                    p_mc = dataclasses.replace(corner_params)
                    p_mc.vth0 = corner_params.vth0 + dvth
                    p_mc.u0   = corner_params.u0   * (1.0 + dbeta)

                    Id = id_bsim4(vgs_s, vds_s, vbs_s, T_K, p_mc, geom)

                    row = {
                        "corner": corner.name,
                        "vdd":    vdd,
                        "T_c":    T_c,
                        "mc_iter": mc_iter,
                        "Id_A":   Id,
                        "dvth_V": dvth,
                        "dbeta":  dbeta,
                    }
                    sweeps.append(row)

                    if spec_min_id is None or Id >= spec_min_id:
                        pass_count += 1

    # Worst-case Id variation relative to nominal
    worst_id_pct = 0.0
    worst_pvt: Tuple[str, float, float] = (spec.process_corners[0].name, nominal_vdd, nominal_T_c)

    if nominal_id > 0:
        for row in sweeps:
            pct = abs(row["Id_A"] - nominal_id) / nominal_id * 100.0
            if pct > worst_id_pct:
                worst_id_pct = pct
                worst_pvt    = (row["corner"], row["vdd"], row["T_c"])

    yield_est = pass_count / max(total_mc, 1)

    return CornerSweepReport(
        sweeps        = sweeps,
        worst_id_pct  = worst_id_pct,
        worst_pvt     = worst_pvt,
        yield_estimate = yield_est,
        nominal_id    = nominal_id,
    )


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def corner_summary(report: CornerSweepReport) -> dict:
    """Return a compact summary dict from a CornerSweepReport.

    Includes per-corner min/max/mean Id statistics.

    HONEST NOTE: summary statistics derived from analytical model only.
    Not foundry-PDK accurate; for design exploration only.
    """
    from collections import defaultdict

    per_corner: dict = defaultdict(list)
    for row in report.sweeps:
        per_corner[row["corner"]].append(row["Id_A"])

    stats = {}
    for cname, ids in per_corner.items():
        stats[cname] = {
            "min_Id_A":  min(ids),
            "max_Id_A":  max(ids),
            "mean_Id_A": sum(ids) / len(ids),
            "n_samples": len(ids),
        }

    return {
        "nominal_id_A": report.nominal_id,
        "worst_id_pct": report.worst_id_pct,
        "worst_pvt":    list(report.worst_pvt),
        "yield_estimate": report.yield_estimate,
        "per_corner_stats": stats,
        "honest_disclaimer": (
            "Not foundry-PDK accurate. Uses BSIM4.8 first-order model + "
            "Pelgrom (1989) matching. For design exploration only."
        ),
    }
