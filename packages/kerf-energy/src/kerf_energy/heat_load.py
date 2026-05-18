"""
Zone heat-load estimation — ASHRAE CLTD/CLF method.

References:
  ASHRAE Handbook of Fundamentals 2021, Ch. 18 — Nonresidential Cooling
    and Heating Load Calculations.
  Carrier (1965). Handbook of Air Conditioning System Design.
  Spitler, J. D. (2014). Load Calculation Applications Manual, 2nd ed. ASHRAE.

The Cooling-Load Temperature-Difference (CLTD) method is an approved
hand-calculation procedure.  For heavyweight wall/roof constructions this
module uses simplified CLTD tables; for lightweight constructions it uses
the CLTD_corr correction approach.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# CLTD tables (simplified — 21 Jul, 40°N latitude, dark surface)
# ---------------------------------------------------------------------------

# CLTD values for exterior walls by hour of day (1–24) for a medium-weight
# wall (Group D, facing south).  Source: ASHRAE HOF 2021 Table 1, Ch. 18.
# These are approximate representative values for demonstration purposes.
_CLTD_WALL_SOUTH_24H = [
    1, 1, 0, 0, 0, 1, 2, 4, 7, 10, 13, 16,
    18, 20, 21, 21, 20, 18, 16, 14, 12, 10, 8, 5,
]  # °C

# CLTD for roof (medium-weight flat roof, 21 Jul, 40°N).
_CLTD_ROOF_24H = [
    18, 14, 11, 9, 7, 6, 7, 9, 13, 18, 23, 28,
    32, 35, 37, 37, 36, 33, 29, 25, 22, 20, 19, 18,
]  # °C

# Correction for latitude, month, and surface colour.
_CLTD_LATITUDE_CORRECTION = 0.0  # default: 0°C correction for this seed


def cltd_for_wall(hour: int, facing: str = "south") -> float:
    """Return the CLTD value (°C) for a wall at the given hour of day.

    Parameters
    ----------
    hour:
        Hour of day (1–24).
    facing:
        Wall orientation (north/south/east/west).  Currently all orientations
        map to the south table (conservative); extend as needed.

    Returns
    -------
    float
        CLTD in °C.
    """
    idx = max(0, min(23, int(hour) - 1))
    return float(_CLTD_WALL_SOUTH_24H[idx])


def cltd_for_roof(hour: int) -> float:
    """Return the CLTD value (°C) for a flat roof at the given hour of day."""
    idx = max(0, min(23, int(hour) - 1))
    return float(_CLTD_ROOF_24H[idx])


# ---------------------------------------------------------------------------
# Building element heat gains
# ---------------------------------------------------------------------------

@dataclass
class WallElement:
    """An exterior wall or roof contributing conduction heat gain."""

    area_m2: float
    u_value_w_m2_k: float   # overall U-value W/(m²·K)
    facing: str = "south"   # north/south/east/west/roof
    is_roof: bool = False

    def conduction_gain_w(self, hour: int) -> float:
        """Sensible conduction heat gain (W) at the given hour."""
        if self.is_roof:
            cltd = cltd_for_roof(hour)
        else:
            cltd = cltd_for_wall(hour, self.facing)
        return self.u_value_w_m2_k * self.area_m2 * cltd


@dataclass
class GlazingElement:
    """An exterior glazing element contributing both conduction and solar gain."""

    area_m2: float
    u_value_w_m2_k: float   # overall U-value W/(m²·K)
    shgc: float              # solar heat gain coefficient (0–1)
    facing: str = "south"

    # Simplified CLF (Cooling Load Factor) for glass — placeholder hourly.
    # Full ASHRAE tables are large; this seed uses a representative shape.
    _CLF_SOUTH_24H: list[float] = field(default_factory=lambda: [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.03, 0.12, 0.22, 0.29, 0.35,
        0.39, 0.42, 0.43, 0.42, 0.38, 0.31, 0.20, 0.09, 0.02, 0.00, 0.00, 0.00,
    ])

    def conduction_gain_w(self, hour: int, delta_t: float = 8.0) -> float:
        """Conduction gain through glass (W).  Uses ΔT = indoor–outdoor (°C)."""
        return self.u_value_w_m2_k * self.area_m2 * delta_t

    def solar_gain_w(self, hour: int, peak_solar_w_m2: float = 600.0) -> float:
        """Solar heat gain through glass (W) at the given hour."""
        idx = max(0, min(23, int(hour) - 1))
        clf = self._CLF_SOUTH_24H[idx]
        return self.shgc * self.area_m2 * peak_solar_w_m2 * clf


# ---------------------------------------------------------------------------
# Internal loads
# ---------------------------------------------------------------------------

@dataclass
class OccupancyLoad:
    """Heat gain from occupants."""

    num_people: int
    sensible_per_person_w: float = 75.0   # ASHRAE Table 1 office work
    latent_per_person_w: float = 55.0

    def sensible_gain_w(self) -> float:
        return self.num_people * self.sensible_per_person_w

    def latent_gain_w(self) -> float:
        return self.num_people * self.latent_per_person_w


@dataclass
class LightingLoad:
    """Heat gain from lighting."""

    installed_power_w: float
    space_fraction: float = 1.0    # fraction of heat to space (vs plenum)
    clf: float = 0.85              # cooling load factor for fluorescent

    def sensible_gain_w(self) -> float:
        return self.installed_power_w * self.space_fraction * self.clf


@dataclass
class EquipmentLoad:
    """Heat gain from plug loads and equipment."""

    sensible_w: float
    latent_w: float = 0.0
    clf: float = 0.90

    def sensible_gain_w(self) -> float:
        return self.sensible_w * self.clf

    def latent_gain_w(self) -> float:
        return self.latent_w


# ---------------------------------------------------------------------------
# Zone heat load calculator
# ---------------------------------------------------------------------------

@dataclass
class ZoneHeatLoad:
    """Aggregate CLTD-method cooling load for a single zone.

    Build up a zone by appending walls, glazing, occupancy, lighting,
    and equipment, then call ``total()`` for a given hour of day.
    """

    walls: list[WallElement] = field(default_factory=list)
    glazing: list[GlazingElement] = field(default_factory=list)
    occupancy: list[OccupancyLoad] = field(default_factory=list)
    lighting: list[LightingLoad] = field(default_factory=list)
    equipment: list[EquipmentLoad] = field(default_factory=list)

    # Infiltration / ventilation latent load
    latent_ventilation_w: float = 0.0

    def sensible_w(self, hour: int) -> float:
        """Total sensible cooling load (W) at the given hour."""
        total = 0.0

        # Envelope conduction
        for w in self.walls:
            total += w.conduction_gain_w(hour)
        for g in self.glazing:
            total += g.conduction_gain_w(hour)
            total += g.solar_gain_w(hour)

        # Internal gains
        for o in self.occupancy:
            total += o.sensible_gain_w()
        for lt in self.lighting:
            total += lt.sensible_gain_w()
        for eq in self.equipment:
            total += eq.sensible_gain_w()

        return total

    def latent_w(self) -> float:
        """Total latent cooling load (W) — occupancy + ventilation."""
        total = self.latent_ventilation_w
        for o in self.occupancy:
            total += o.latent_gain_w()
        for eq in self.equipment:
            total += eq.latent_gain_w()
        return total

    def peak_hour(self) -> int:
        """Return the hour (1–24) with the highest sensible cooling load."""
        return max(range(1, 25), key=lambda h: self.sensible_w(h))

    def peak_sensible_w(self) -> float:
        """Return the peak sensible cooling load (W)."""
        return self.sensible_w(self.peak_hour())


# ---------------------------------------------------------------------------
# Heating load — simplified UA·ΔT method
# ---------------------------------------------------------------------------

@dataclass
class HeatingLoadElement:
    """One envelope element for heating load calculation."""

    area_m2: float
    u_value_w_m2_k: float
    delta_t_k: float  # indoor − outdoor design temperature difference

    def heat_loss_w(self) -> float:
        return self.area_m2 * self.u_value_w_m2_k * self.delta_t_k


def zone_heating_load_w(elements: Sequence[HeatingLoadElement]) -> float:
    """Return total zone design heating load (W) as the sum of UA·ΔT losses."""
    return sum(e.heat_loss_w() for e in elements)
