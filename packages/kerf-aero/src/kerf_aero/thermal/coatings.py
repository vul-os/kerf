"""
Spacecraft surface-coating catalogue: absorptivity (α) and emissivity (ε) pairs.

All values are representative room-temperature / BOL (beginning of life) figures
from standard spacecraft thermal-control references:
  - Gilmore, D. G. (ed.), "Spacecraft Thermal Control Handbook", 2nd ed., 2002.
  - Wertz & Larson, "Space Mission Engineering", 3rd ed.
  - Henninger, J.H., "Solar Absorptance and Thermal Emittance of Some Common
    Spacecraft Thermal-Control Coatings", NASA RP-1121, 1984.

Fields per coating entry:
  name        : human-readable label
  alpha       : solar absorptivity  (fraction, 0–1)
  epsilon     : total hemispherical emissivity at 300 K (fraction, 0–1)
  description : brief note on application / EOL degradation trend

Units: dimensionless (both α and ε are ratios).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Coating:
    """Optical-thermal properties for one spacecraft surface finish."""

    name: str
    alpha: float          # solar absorptivity  (0–1)
    epsilon: float        # hemispherical emissivity at ~300 K (0–1)
    description: str = ""

    def __post_init__(self) -> None:
        if not (0.0 <= self.alpha <= 1.0):
            raise ValueError(f"alpha must be in [0, 1]; got {self.alpha}")
        if not (0.0 <= self.epsilon <= 1.0):
            raise ValueError(f"epsilon must be in [0, 1]; got {self.epsilon}")

    @property
    def alpha_over_epsilon(self) -> float:
        """α/ε ratio — drives equilibrium temperature in sunlight."""
        if self.epsilon == 0.0:
            return float("inf")
        return self.alpha / self.epsilon


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

COATINGS: dict[str, Coating] = {c.name: c for c in [
    Coating(
        name="white_paint_s13g",
        alpha=0.20,
        epsilon=0.85,
        description=(
            "S13G white silicone paint; low α/ε ≈ 0.24; good for radiators; "
            "α degrades to ~0.28 at EOL (5-yr LEO)."
        ),
    ),
    Coating(
        name="white_paint_a276",
        alpha=0.22,
        epsilon=0.88,
        description="A-276 white polyurethane; similar to S13G with slightly higher ε.",
    ),
    Coating(
        name="black_paint_chemglaze_z306",
        alpha=0.95,
        epsilon=0.90,
        description=(
            "Chemglaze Z-306 black polyurethane; high α and ε; "
            "used for internal structure heating uniformity."
        ),
    ),
    Coating(
        name="black_paint_aeroglaze_l300",
        alpha=0.97,
        epsilon=0.91,
        description="Aeroglaze L-300 flat black; near-blackbody; internal surfaces.",
    ),
    Coating(
        name="gold_electroplated",
        alpha=0.25,
        epsilon=0.03,
        description=(
            "Electroplated gold; very low ε → high equilibrium temperature in sun; "
            "used on warm surfaces (propellant lines, battery enclosures)."
        ),
    ),
    Coating(
        name="aluminized_kapton_25um",
        alpha=0.34,
        epsilon=0.55,
        description=(
            "25-μm Kapton with 100-nm Al on outer surface (MLI outer layer); "
            "ε is for the Kapton side; Al side ε ≈ 0.04."
        ),
    ),
    Coating(
        name="aluminized_kapton_al_side",
        alpha=0.15,
        epsilon=0.04,
        description=(
            "Aluminized Kapton, aluminium-side out; very low ε; MLI inner layers."
        ),
    ),
    Coating(
        name="ito_coated_quartz_mirror_osr",
        alpha=0.08,
        epsilon=0.80,
        description=(
            "ITO-coated quartz mirror (Optical Solar Reflector); extremely low α/ε ≈ 0.10; "
            "radiator tiles on GEO spacecraft; radiation-stable (α rises only ~0.01 per year)."
        ),
    ),
    Coating(
        name="alodine_aluminum",
        alpha=0.08,
        epsilon=0.03,
        description=(
            "Alodine 1200 conversion coating on aluminium; very low ε and α; "
            "structural panels where thermal isolation is needed."
        ),
    ),
    Coating(
        name="bare_aluminum_6061",
        alpha=0.37,
        epsilon=0.09,
        description=(
            "Uncoated 6061-T6 aluminium (polished); low ε → high equilibrium T; "
            "ε rises sharply if oxidised."
        ),
    ),
    Coating(
        name="anodized_aluminum_black",
        alpha=0.88,
        epsilon=0.84,
        description=(
            "Black-anodized aluminium; high α and ε; used for heatsink fins "
            "and internal structure where thermal coupling is desired."
        ),
    ),
    Coating(
        name="silver_teflon_tape_fep",
        alpha=0.08,
        epsilon=0.78,
        description=(
            "Ag-backed FEP Teflon second-surface mirror tape (SSM); α/ε ≈ 0.10; "
            "very radiation-stable radiator; GEO/deep-space favourite."
        ),
    ),
    Coating(
        name="vapor_deposited_aluminum_vda",
        alpha=0.09,
        epsilon=0.02,
        description=(
            "Vacuum-deposited aluminium; mirror finish; very low ε; "
            "MLI inner-layer crinkled foil."
        ),
    ),
]}


def get(name: str) -> Optional[Coating]:
    """Return the coating with *name*, or None if not found."""
    return COATINGS.get(name)


def all_coatings() -> list[Coating]:
    """Return all catalogue entries as a sorted list."""
    return sorted(COATINGS.values(), key=lambda c: c.name)


def find_by_alpha_epsilon(
    alpha: float,
    epsilon: float,
    *,
    tol: float = 0.05,
) -> list[Coating]:
    """Return coatings whose α and ε are within *tol* of the requested values."""
    return [
        c for c in COATINGS.values()
        if abs(c.alpha - alpha) <= tol and abs(c.epsilon - epsilon) <= tol
    ]
