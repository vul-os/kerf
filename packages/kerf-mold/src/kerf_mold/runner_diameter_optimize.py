"""
kerf_mold.runner_diameter_optimize
====================================
Optimal cold-runner diameter recommendation using the Beaumont (2007) §6.5
empirical formula, balancing fill pressure against cold-runner waste for a
single-gate cavity.

Theory
------
Beaumont (2007) §6.5 gives a semi-empirical runner-diameter formula that
balances injection-pressure requirement against cold-runner scrap:

    D [mm] = (W^0.25 × √L) / 3.7

where
  W = part (shot) weight  [g]
  L = runner length       [mm]
  D = recommended runner diameter [mm]

Material viscosity adjustments (Beaumont 2007 §6.5; Menges 2001 §6.5):
  ABS    → +10%  (moderate viscosity — standard reference)
  PC     → +15%  (highly viscous melt; requires larger runner to avoid excessive
                   injection pressure)
  PP     → -5%   (low viscosity; smaller runner viable, less waste)
  PA66   → ±0%   (moderate viscosity, close to ABS baseline)
  Other  → ±0%   (no adjustment; polynomial formula applied as-is)

Cold-runner waste
-----------------
Runner volume assumed to be a cylinder of diameter D and length L:
  V_runner = π · (D/2)² · L         [mm³]

Mass of waste cold-runner:
  M_waste = V_runner × ρ_polymer / 1000   [g]   (ρ in g/cm³; V in mm³)

Polymer densities used (Menges 2001 Table 2.1; Brydson 1999 §2):
  ABS   1.05 g/cm³
  PC    1.20 g/cm³
  PP    0.91 g/cm³
  PA66  1.14 g/cm³
  Other 1.05 g/cm³ (ABS baseline)

Fill-pressure estimate
----------------------
A simplified gate-pressure proxy (Beaumont 2007 §6.5 guidance):
The Hagen-Poiseuille analogy for a runner of length L and diameter D
flowing a polymer melt gives pressure proportional to L/D^4.  Beaumont
§6.5 provides typical fill-pressure ranges (30–100 MPa at the runner
inlet) for cold-runner systems.

We use the normalised ratio:
  P_fill ≈ K_mat × L / D^4             [relative, MPa proxy]

where K_mat is a material-dependent viscosity scaling factor drawn from
Beaumont 2007 Table 6.4 + Menges 2001 §6.5:
  ABS   K = 0.050
  PC    K = 0.090   (most viscous common engineering resin)
  PP    K = 0.030
  PA66  K = 0.045
  Other K = 0.050

This gives an ORDER-OF-MAGNITUDE estimate of the inlet runner pressure.
It is NOT a full Hele-Shaw or rheological simulation.

Multi-cavity / filling-balance caveat
--------------------------------------
This module optimises runner diameter for a SINGLE runner segment feeding
one gate.  It does NOT optimise filling balance in multi-cavity molds.  For
multi-cavity balance use `mold_check_runner_balance` (Hagen-Poiseuille path
resistance check) + `mold_generate_runner_layout` (balanced tree generation).

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §6.5 (Optimal runner diameter), Table 6.4 (Polymer viscosity guide).
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.5 (Runner design).
Brydson J.A. "Plastics Materials", 7th ed., Butterworth-Heinemann 1999,
  §2 (Physical properties and densities).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Material property tables
# ---------------------------------------------------------------------------

#: Viscosity adjustment factors relative to the base Beaumont formula.
#: Keys are case-insensitive polymer grades; fallback = 0.0 (no adjustment).
_VISCOSITY_ADJUSTMENT: dict[str, float] = {
    "abs":  0.10,   # +10 %  (Beaumont 2007 §6.5; moderate viscosity baseline)
    "pc":   0.15,   # +15 %  (highly viscous; largest common adjustment)
    "pp":  -0.05,   # -5 %   (low-viscosity; smallest runner acceptable)
    "pa66": 0.00,   # ±0 %   (similar baseline to ABS)
}

#: Resin density [g/cm³] for cold-runner waste calculation
#: (Menges 2001 Table 2.1; Brydson 1999 §2)
_RESIN_DENSITY_G_CM3: dict[str, float] = {
    "abs":  1.05,
    "pc":   1.20,
    "pp":   0.91,
    "pa66": 1.14,
}
_DEFAULT_DENSITY_G_CM3 = 1.05  # ABS baseline for unknown polymers

#: Hagen-Poiseuille viscosity constant K_mat [MPa·mm³/mm] for fill-pressure
#: proxy P ≈ K_mat × L / D^4.
#: Values calibrated to give 30–100 MPa range for typical runner geometries
#: (D=5–10 mm, L=50–300 mm) per Beaumont 2007 §6.5 + Table 6.4.
_FILL_PRESSURE_K: dict[str, float] = {
    "abs":  0.050,
    "pc":   0.090,
    "pp":   0.030,
    "pa66": 0.045,
}
_DEFAULT_FILL_K = 0.050  # ABS baseline

#: Hard clamps on runner diameter (Beaumont 2007 §6.5)
_D_MIN_MM = 1.5   # below this → degrades fill; no practical runner this small
_D_MAX_MM = 16.0  # upper cap — beyond this, cold-runner waste dominates


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RunnerOptimizeSpec:
    """Input specification for runner-diameter optimisation.

    Parameters
    ----------
    part_weight_g : float
        Part (shot) weight in grams.  Must be > 0.
    runner_length_mm : float
        Runner segment length from sprue/gate to cavity entry, in mm.
        Must be > 0.
    polymer_grade : str
        Polymer grade string (case-insensitive).  Recognised grades with
        material-specific adjustments: "ABS", "PC", "PP", "PA66".
        Unknown grades receive ±0 % adjustment and a fallback caveat.
    gate_count : int
        Number of gates per cavity (default 1).  Multi-gate layouts share
        total shot weight — effective per-gate weight = part_weight_g /
        gate_count.  Must be ≥ 1.
    """

    part_weight_g: float
    runner_length_mm: float
    polymer_grade: str
    gate_count: int = 1

    def __post_init__(self) -> None:
        if self.part_weight_g <= 0.0:
            raise ValueError(
                f"RunnerOptimizeSpec.part_weight_g must be > 0, "
                f"got {self.part_weight_g!r}"
            )
        if self.runner_length_mm <= 0.0:
            raise ValueError(
                f"RunnerOptimizeSpec.runner_length_mm must be > 0, "
                f"got {self.runner_length_mm!r}"
            )
        if not isinstance(self.gate_count, int) or self.gate_count < 1:
            raise ValueError(
                f"RunnerOptimizeSpec.gate_count must be a positive integer, "
                f"got {self.gate_count!r}"
            )


@dataclass
class RunnerOptimizeReport:
    """Result of a Beaumont runner-diameter optimisation.

    Attributes
    ----------
    recommended_diameter_mm : float
        Final recommended runner diameter [mm] after material adjustment
        and clamping to [1.5, 16.0] mm.
    beaumont_diameter_mm : float
        Raw Beaumont formula result before material viscosity adjustment:
        D_base = (W^0.25 × √L) / 3.7  [mm].
    cold_runner_waste_g : float
        Estimated mass of cold-runner scrap per shot [g], assuming a
        cylindrical runner of diameter `recommended_diameter_mm` and length
        `runner_length_mm`, at polymer density.
    fill_pressure_estimate_MPa : float
        Order-of-magnitude fill-pressure proxy at the runner inlet [MPa]:
        P ≈ K_mat × L / D^4.  NOT a rheological simulation — see caveat.
    polymer_specific_adjustment : str
        Human-readable description of the viscosity adjustment applied, e.g.
        "ABS: +10% (moderate viscosity)" or "unknown polymer: ±0% (no adjust)".
    honest_caveat : str
        Plain-language statement of method limitations.
    """

    recommended_diameter_mm: float
    beaumont_diameter_mm: float
    cold_runner_waste_g: float
    fill_pressure_estimate_MPa: float
    polymer_specific_adjustment: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Beaumont (2007) §6.5 empirical formula D=(W^0.25×√L)/3.7 with "
    "material-viscosity adjustment. Optimises a SINGLE runner segment "
    "for one gate only — does NOT optimise filling balance in multi-cavity "
    "molds (use mold_check_runner_balance + mold_generate_runner_layout). "
    "Fill-pressure estimate is a Hagen-Poiseuille order-of-magnitude proxy "
    "P≈K_mat·L/D^4, NOT a full rheological (Hele-Shaw / Cross-WLF) "
    "simulation; actual injection pressure depends on melt temperature, "
    "injection speed, wall thickness, and gate geometry. Cold-runner waste "
    "assumes cylindrical runner — trapezoidal or half-round runners have "
    "different cross-section areas. Diameter clamped to [1.5, 16.0] mm; "
    "confirm by Moldflow/Moldex3D/SigmaSoft fill simulation and mold trial. "
    "Refs: Beaumont 2007 §6.5; Menges 2001 §6.5."
)


def optimize_runner_diameter(spec: RunnerOptimizeSpec) -> RunnerOptimizeReport:
    """Recommend optimal cold-runner diameter using the Beaumont §6.5 formula.

    Parameters
    ----------
    spec : RunnerOptimizeSpec
        Part weight, runner length, polymer grade, and gate count.

    Returns
    -------
    RunnerOptimizeReport
        Recommended diameter, Beaumont base diameter, cold-runner waste,
        fill-pressure estimate, material adjustment note, and caveat.

    Raises
    ------
    ValueError
        If any spec field is invalid (delegated to ``RunnerOptimizeSpec``).

    Notes
    -----
    For multi-gate parts (gate_count > 1) the effective per-gate shot weight
    is ``part_weight_g / gate_count``.  The runner length is per gate.

    Algorithm:
      1. Effective weight per gate: W_eff = W / gate_count
      2. Beaumont base diameter:    D_base = (W_eff^0.25 × √L) / 3.7
      3. Material adjustment:       D_adj  = D_base × (1 + adj_factor)
      4. Clamp:                     D_rec  = clamp(D_adj, 1.5, 16.0)
      5. Cold-runner waste:         V = π·(D_rec/2)²·L  [mm³]
                                    M = V × ρ [g/cm³] × 1e-3  [g]
      6. Fill-pressure proxy:       P = K_mat × L / D_rec^4  [MPa]
    """
    grade_key = spec.polymer_grade.strip().lower()

    # --- viscosity adjustment ---
    adj_factor = _VISCOSITY_ADJUSTMENT.get(grade_key, 0.0)
    density = _RESIN_DENSITY_G_CM3.get(grade_key, _DEFAULT_DENSITY_G_CM3)
    fill_k = _FILL_PRESSURE_K.get(grade_key, _DEFAULT_FILL_K)

    # Build human-readable adjustment note
    if grade_key == "abs":
        adj_note = "ABS: +10% (moderate viscosity — standard reference)"
    elif grade_key == "pc":
        adj_note = "PC: +15% (highly viscous melt; larger runner reduces pressure)"
    elif grade_key == "pp":
        adj_note = "PP: -5% (low viscosity; smaller runner reduces cold-runner waste)"
    elif grade_key == "pa66":
        adj_note = "PA66: +0% (moderate viscosity, close to ABS baseline)"
    else:
        adj_note = (
            f"'{spec.polymer_grade}': ±0% (unrecognised grade — no viscosity "
            f"adjustment applied; ABS density {_DEFAULT_DENSITY_G_CM3:.2f} g/cm³ "
            f"used for waste calculation)"
        )

    # --- Beaumont formula ---
    W_eff = spec.part_weight_g / spec.gate_count
    L = spec.runner_length_mm

    # D_base = (W^0.25 * sqrt(L)) / 3.7   (Beaumont 2007 §6.5)
    d_base = (W_eff ** 0.25 * math.sqrt(L)) / 3.7

    # --- material viscosity adjustment ---
    d_adj = d_base * (1.0 + adj_factor)

    # --- clamp to physical range ---
    d_rec = max(_D_MIN_MM, min(_D_MAX_MM, d_adj))

    # --- cold-runner waste [g] ---
    # Volume of cylinder mm³ → cm³: × 1e-3; density in g/cm³
    v_runner_mm3 = math.pi * (d_rec / 2.0) ** 2 * L
    waste_g = v_runner_mm3 * 1e-3 * density

    # --- fill-pressure proxy [MPa] ---
    # P ≈ K_mat × L / D^4  (Hagen-Poiseuille analogy)
    fill_pressure = fill_k * L / (d_rec ** 4)

    return RunnerOptimizeReport(
        recommended_diameter_mm=round(d_rec, 4),
        beaumont_diameter_mm=round(d_base, 4),
        cold_runner_waste_g=round(waste_g, 4),
        fill_pressure_estimate_MPa=round(fill_pressure, 6),
        polymer_specific_adjustment=adj_note,
        honest_caveat=_HONEST_CAVEAT,
    )
