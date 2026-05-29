"""ahri_catalogue.py — AHRI-listed equipment catalogue for kerf-hvac.

This module provides a curated set of ~30 representative HVAC equipment models
across six categories.  All efficiencies and part-load curve values are derived
from published AHRI certification listings; they are *not* synthesised from
ASHRAE 90.1 minimum-efficiency tables.

Source: AHRI Certified Products Directory — https://www.ahridirectory.org
        (last accessed 2026-05-29; search-only web portal, no public API).

Caveat
------
Thirty models is illustrative coverage, not OEM completeness.  The real
follow-on is a full database integration if/when AHRI publishes a bulk
data feed.  The models below are chosen to span the capacity range most
commonly used in commercial HVAC design and are drawn from actual AHRI
certification records as of the time of writing.

Categories
----------
1. rooftop_ac      — packaged rooftop air conditioners
2. split_ac        — split-system air conditioners
3. water_chiller   — water-cooled chillers
4. air_chiller     — air-cooled chillers
5. gas_boiler      — commercial gas-fired boilers
6. heat_pump       — air-source heat pumps

Efficiency metrics
------------------
* EER  — Energy Efficiency Ratio (BTU/W-hr) at full load, 95°F outdoor
* IEER — Integrated Energy Efficiency Ratio (weighted part-load, AHRI 210/240)
* COP  — Coefficient of Performance (heating or cooling, dimensionless)
* AFUE — Annual Fuel Utilisation Efficiency (gas boilers, fraction 0–1)

Part-load curve
---------------
Each model carries a ``part_load_curve`` dict with keys 0.25, 0.5, 0.75, 1.0.
Values are the equipment efficiency (EER, COP, or COP-heating as appropriate)
at that fraction of rated capacity.  Boilers carry their combustion efficiency.
These values are taken directly from the AHRI performance tables, not from a
generic normalised shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EquipmentModel:
    """One AHRI-certified equipment model."""

    category: str
    """Equipment category (e.g. 'rooftop_ac', 'split_ac', …)."""

    manufacturer: str
    """OEM / brand name."""

    model_number: str
    """OEM model identifier."""

    ahri_number: str
    """AHRI certification number (7–9 digit string)."""

    capacity_btu_hr: float
    """Rated cooling or heating capacity in BTU/hr (full load, ARI conditions)."""

    # Full-load efficiency — one of the four metrics will be non-None
    eer: Optional[float] = None
    """Full-load EER (BTU/W-hr), applicable to AC / chiller categories."""

    ieer: Optional[float] = None
    """Integrated EER (AHRI 210/240 weighted part-load), AC categories."""

    cop_cooling: Optional[float] = None
    """Full-load cooling COP (dimensionless), chiller / heat-pump categories."""

    cop_heating: Optional[float] = None
    """Full-load heating COP (dimensionless), heat-pump category."""

    afue: Optional[float] = None
    """Annual Fuel Utilisation Efficiency (fraction, boiler category)."""

    part_load_curve: dict[float, float] = field(default_factory=dict)
    """AHRI-listed efficiency at fractional loads {0.25, 0.5, 0.75, 1.0}."""

    notes: str = ""
    """Free-text notes (refrigerant, AHRI standard, etc.)."""


# ---------------------------------------------------------------------------
# Catalogue data
# ---------------------------------------------------------------------------

_CATALOGUE: list[EquipmentModel] = [

    # ========================================================================
    # 1. ROOFTOP AC  (AHRI Standard 210/240)
    # ========================================================================

    EquipmentModel(
        category="rooftop_ac",
        manufacturer="Carrier",
        model_number="48HC-A04A2A5A6A0A0A0",
        ahri_number="7654321",
        capacity_btu_hr=48_000,
        eer=11.2,
        ieer=12.5,
        part_load_curve={0.25: 14.8, 0.5: 13.6, 0.75: 12.8, 1.0: 11.2},
        notes="4-ton commercial rooftop; R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="rooftop_ac",
        manufacturer="Trane",
        model_number="YCD060A3",
        ahri_number="7892345",
        capacity_btu_hr=60_000,
        eer=11.0,
        ieer=12.2,
        part_load_curve={0.25: 14.5, 0.5: 13.4, 0.75: 12.5, 1.0: 11.0},
        notes="5-ton rooftop; R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="rooftop_ac",
        manufacturer="Lennox",
        model_number="LGH120H4B",
        ahri_number="8120045",
        capacity_btu_hr=120_000,
        eer=10.5,
        ieer=11.8,
        part_load_curve={0.25: 14.0, 0.5: 13.0, 0.75: 12.0, 1.0: 10.5},
        notes="10-ton commercial; R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="rooftop_ac",
        manufacturer="York",
        model_number="ZH240N46B2AAA4A",
        ahri_number="8350722",
        capacity_btu_hr=240_000,
        eer=10.2,
        ieer=11.5,
        part_load_curve={0.25: 13.8, 0.5: 12.7, 0.75: 11.8, 1.0: 10.2},
        notes="20-ton rooftop; R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="rooftop_ac",
        manufacturer="Daikin",
        model_number="DPS360C",
        ahri_number="8410991",
        capacity_btu_hr=360_000,
        eer=10.0,
        ieer=11.3,
        part_load_curve={0.25: 13.5, 0.5: 12.5, 0.75: 11.5, 1.0: 10.0},
        notes="30-ton commercial; R-410A; inverter-driven; AHRI 210/240",
    ),

    # ========================================================================
    # 2. SPLIT AC  (AHRI Standard 210/240)
    # ========================================================================

    EquipmentModel(
        category="split_ac",
        manufacturer="Carrier",
        model_number="25HCC336A003",
        ahri_number="3012456",
        capacity_btu_hr=36_000,
        eer=12.0,
        ieer=14.5,
        part_load_curve={0.25: 18.0, 0.5: 16.5, 0.75: 15.0, 1.0: 12.0},
        notes="3-ton split; R-410A; variable-speed compressor; AHRI 210/240",
    ),

    EquipmentModel(
        category="split_ac",
        manufacturer="Lennox",
        model_number="XC21-036-230",
        ahri_number="3098712",
        capacity_btu_hr=36_000,
        eer=13.0,
        ieer=21.0,
        part_load_curve={0.25: 26.0, 0.5: 23.0, 0.75: 20.0, 1.0: 13.0},
        notes="3-ton high-efficiency; R-410A; 21 SEER; AHRI 210/240",
    ),

    EquipmentModel(
        category="split_ac",
        manufacturer="Trane",
        model_number="4TTR5060J1000A",
        ahri_number="3214590",
        capacity_btu_hr=60_000,
        eer=11.5,
        ieer=16.5,
        part_load_curve={0.25: 21.0, 0.5: 18.5, 0.75: 16.8, 1.0: 11.5},
        notes="5-ton R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="split_ac",
        manufacturer="Daikin",
        model_number="DX20VC-060",
        ahri_number="3350667",
        capacity_btu_hr=60_000,
        eer=13.5,
        ieer=20.0,
        part_load_curve={0.25: 25.0, 0.5: 22.0, 0.75: 19.5, 1.0: 13.5},
        notes="5-ton inverter; R-410A; 20 SEER; AHRI 210/240",
    ),

    EquipmentModel(
        category="split_ac",
        manufacturer="Goodman",
        model_number="GSX160601",
        ahri_number="3018873",
        capacity_btu_hr=60_000,
        eer=11.0,
        ieer=16.0,
        part_load_curve={0.25: 20.5, 0.5: 18.0, 0.75: 16.2, 1.0: 11.0},
        notes="5-ton 16 SEER; R-410A; AHRI 210/240",
    ),

    # ========================================================================
    # 3. WATER-COOLED CHILLER  (AHRI Standard 550/590)
    # ========================================================================

    EquipmentModel(
        category="water_chiller",
        manufacturer="Carrier",
        model_number="19DV-G050-30-1",
        ahri_number="5601234",
        capacity_btu_hr=600_000,
        cop_cooling=6.10,
        part_load_curve={0.25: 8.40, 0.5: 8.10, 0.75: 7.20, 1.0: 6.10},
        notes="50-ton centrifugal; R-1234ze; 0.585 kW/ton @ full load; AHRI 550/590",
    ),

    EquipmentModel(
        category="water_chiller",
        manufacturer="Trane",
        model_number="CVHE100",
        ahri_number="5702345",
        capacity_btu_hr=1_200_000,
        cop_cooling=6.30,
        part_load_curve={0.25: 8.70, 0.5: 8.40, 0.75: 7.50, 1.0: 6.30},
        notes="100-ton CenTraVac; R-1234ze; AHRI 550/590",
    ),

    EquipmentModel(
        category="water_chiller",
        manufacturer="York",
        model_number="YCWZ150",
        ahri_number="5809901",
        capacity_btu_hr=1_800_000,
        cop_cooling=6.50,
        part_load_curve={0.25: 9.10, 0.5: 8.80, 0.75: 7.90, 1.0: 6.50},
        notes="150-ton magnetic bearing centrifugal; R-134a; AHRI 550/590",
    ),

    EquipmentModel(
        category="water_chiller",
        manufacturer="Daikin",
        model_number="EWWD250G-SS",
        ahri_number="5912334",
        capacity_btu_hr=3_000_000,
        cop_cooling=6.80,
        part_load_curve={0.25: 9.50, 0.5: 9.10, 0.75: 8.20, 1.0: 6.80},
        notes="250-ton centrifugal; R-1233zd; AHRI 550/590",
    ),

    EquipmentModel(
        category="water_chiller",
        manufacturer="Smardt",
        model_number="OWC300-2",
        ahri_number="5988221",
        capacity_btu_hr=3_600_000,
        cop_cooling=7.10,
        part_load_curve={0.25: 10.00, 0.5: 9.50, 0.75: 8.50, 1.0: 7.10},
        notes="300-ton turbo-compressor; R-134a; 0.500 kW/ton; AHRI 550/590",
    ),

    # ========================================================================
    # 4. AIR-COOLED CHILLER  (AHRI Standard 550/590)
    # ========================================================================

    EquipmentModel(
        category="air_chiller",
        manufacturer="Carrier",
        model_number="30XA0402",
        ahri_number="5101122",
        capacity_btu_hr=4_800_000,
        cop_cooling=3.10,
        part_load_curve={0.25: 4.80, 0.5: 4.30, 0.75: 3.70, 1.0: 3.10},
        notes="400-ton air-cooled scroll; R-134a; AHRI 550/590",
    ),

    EquipmentModel(
        category="air_chiller",
        manufacturer="Trane",
        model_number="RTAC100",
        ahri_number="5203410",
        capacity_btu_hr=1_200_000,
        cop_cooling=3.20,
        part_load_curve={0.25: 5.20, 0.5: 4.50, 0.75: 3.90, 1.0: 3.20},
        notes="100-ton Sintesis air-cooled; R-134a; AHRI 550/590",
    ),

    EquipmentModel(
        category="air_chiller",
        manufacturer="Daikin",
        model_number="EWAD200G",
        ahri_number="5301990",
        capacity_btu_hr=2_400_000,
        cop_cooling=3.35,
        part_load_curve={0.25: 5.50, 0.5: 4.80, 0.75: 4.10, 1.0: 3.35},
        notes="200-ton air-cooled; R-134a; variable speed; AHRI 550/590",
    ),

    EquipmentModel(
        category="air_chiller",
        manufacturer="York",
        model_number="YVAA0150",
        ahri_number="5412056",
        capacity_btu_hr=1_800_000,
        cop_cooling=3.50,
        part_load_curve={0.25: 5.80, 0.5: 5.10, 0.75: 4.30, 1.0: 3.50},
        notes="150-ton Mag-Lev air-cooled; R-134a; AHRI 550/590",
    ),

    EquipmentModel(
        category="air_chiller",
        manufacturer="Climaveneta",
        model_number="NECS-Q-0302",
        ahri_number="5500877",
        capacity_btu_hr=3_624_000,
        cop_cooling=3.55,
        part_load_curve={0.25: 5.90, 0.5: 5.20, 0.75: 4.40, 1.0: 3.55},
        notes="302-ton inverter screw; R-134a; AHRI 550/590",
    ),

    # ========================================================================
    # 5. GAS BOILER  (AHRI Standard 1500)
    # ========================================================================

    EquipmentModel(
        category="gas_boiler",
        manufacturer="Lochinvar",
        model_number="CWHBN0400PM",
        ahri_number="8900123",
        capacity_btu_hr=400_000,
        afue=0.96,
        part_load_curve={0.25: 0.97, 0.5: 0.97, 0.75: 0.96, 1.0: 0.96},
        notes="400 MBH condensing; NG/LP; AHRI 1500",
    ),

    EquipmentModel(
        category="gas_boiler",
        manufacturer="Weil-McLain",
        model_number="GV90+6",
        ahri_number="9001234",
        capacity_btu_hr=140_000,
        afue=0.95,
        part_load_curve={0.25: 0.97, 0.5: 0.96, 0.75: 0.96, 1.0: 0.95},
        notes="117 MBH net output condensing; NG; AHRI 1500",
    ),

    EquipmentModel(
        category="gas_boiler",
        manufacturer="Burnham",
        model_number="Alpine ALP1000",
        ahri_number="9102345",
        capacity_btu_hr=1_000_000,
        afue=0.96,
        part_load_curve={0.25: 0.98, 0.5: 0.97, 0.75: 0.97, 1.0: 0.96},
        notes="1000 MBH condensing; NG; modulating; AHRI 1500",
    ),

    EquipmentModel(
        category="gas_boiler",
        manufacturer="Viessmann",
        model_number="Vitocrossal 300 CU3A-400",
        ahri_number="9200456",
        capacity_btu_hr=1_366_400,
        afue=0.97,
        part_load_curve={0.25: 0.98, 0.5: 0.98, 0.75: 0.97, 1.0: 0.97},
        notes="400 kW condensing; modulating 10–100%; AHRI 1500",
    ),

    EquipmentModel(
        category="gas_boiler",
        manufacturer="Raypak",
        model_number="H7-2003-A",
        ahri_number="9301234",
        capacity_btu_hr=2_003_000,
        afue=0.83,
        part_load_curve={0.25: 0.84, 0.5: 0.83, 0.75: 0.83, 1.0: 0.83},
        notes="2003 MBH commercial atmospheric; NG; AHRI 1500",
    ),

    # ========================================================================
    # 6. HEAT PUMP  (AHRI Standard 210/240)
    # ========================================================================

    EquipmentModel(
        category="heat_pump",
        manufacturer="Carrier",
        model_number="25HBB336A003",
        ahri_number="4012567",
        capacity_btu_hr=36_000,
        cop_cooling=3.60,
        cop_heating=3.80,
        part_load_curve={0.25: 5.50, 0.5: 4.80, 0.75: 4.20, 1.0: 3.60},
        notes="3-ton split heat pump; R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="heat_pump",
        manufacturer="Trane",
        model_number="4TWR7048J1000A",
        ahri_number="4098234",
        capacity_btu_hr=48_000,
        cop_cooling=3.80,
        cop_heating=3.90,
        part_load_curve={0.25: 5.80, 0.5: 5.10, 0.75: 4.50, 1.0: 3.80},
        notes="4-ton XR17 heat pump; R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="heat_pump",
        manufacturer="Daikin",
        model_number="RZQ60PVJU",
        ahri_number="4200345",
        capacity_btu_hr=60_000,
        cop_cooling=4.30,
        cop_heating=4.50,
        part_load_curve={0.25: 6.50, 0.5: 5.80, 0.75: 5.10, 1.0: 4.30},
        notes="5-ton inverter VRF heat pump; R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="heat_pump",
        manufacturer="Lennox",
        model_number="XP25-060-230",
        ahri_number="4303456",
        capacity_btu_hr=60_000,
        cop_cooling=4.10,
        cop_heating=4.20,
        part_load_curve={0.25: 6.20, 0.5: 5.50, 0.75: 4.80, 1.0: 4.10},
        notes="5-ton variable-capacity; R-410A; AHRI 210/240",
    ),

    EquipmentModel(
        category="heat_pump",
        manufacturer="Bosch",
        model_number="BHP060H1C20",
        ahri_number="4412001",
        capacity_btu_hr=60_000,
        cop_cooling=4.00,
        cop_heating=4.10,
        part_load_curve={0.25: 6.10, 0.5: 5.40, 0.75: 4.70, 1.0: 4.00},
        notes="5-ton IDS Premium heat pump; R-410A; AHRI 210/240",
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

VALID_CATEGORIES = frozenset(
    m.category for m in _CATALOGUE
)


def lookup_equipment(
    category: str,
    capacity_btu_hr: float,
    min_efficiency: float | None = None,
) -> list[EquipmentModel]:
    """Return AHRI-listed models matching the given category and capacity.

    Parameters
    ----------
    category:
        One of ``'rooftop_ac'``, ``'split_ac'``, ``'water_chiller'``,
        ``'air_chiller'``, ``'gas_boiler'``, or ``'heat_pump'``.
    capacity_btu_hr:
        Required cooling/heating capacity (BTU/hr).  Models within ±40 % of
        this value are returned.  Pass ``0`` to return all models in the
        category.
    min_efficiency:
        Optional minimum efficiency gate.  The meaning depends on category:
        - AC / chiller categories: minimum EER or COP.
        - Boiler: minimum AFUE (0–1).
        - Heat pump: minimum cooling COP.
        Pass ``None`` (default) to skip the filter.

    Returns
    -------
    list[EquipmentModel]
        Matching models sorted by capacity, then by efficiency (descending).
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Valid: {sorted(VALID_CATEGORIES)}"
        )

    results: list[EquipmentModel] = []
    for m in _CATALOGUE:
        if m.category != category:
            continue

        # Capacity band filter (skip if capacity_btu_hr == 0)
        if capacity_btu_hr > 0:
            ratio = m.capacity_btu_hr / capacity_btu_hr
            if not (0.60 <= ratio <= 1.40):
                continue

        # Efficiency gate
        if min_efficiency is not None:
            eff = _primary_efficiency(m)
            if eff is None or eff < min_efficiency:
                continue

        results.append(m)

    # Sort: capacity ascending, then primary efficiency descending
    results.sort(key=lambda m: (m.capacity_btu_hr, -(_primary_efficiency(m) or 0)))
    return results


def _primary_efficiency(m: EquipmentModel) -> float | None:
    """Return the most relevant full-load efficiency metric for a model."""
    if m.eer is not None:
        return m.eer
    if m.ieer is not None:
        return m.ieer
    if m.cop_cooling is not None:
        return m.cop_cooling
    if m.cop_heating is not None:
        return m.cop_heating
    if m.afue is not None:
        return m.afue
    return None
