"""
kerf_cad_core.piping.component_catalogue — AVEVA E3D parity: piping component catalogue.

Implements an ASME B16.5 / B16.9 / API 6D / AWWA C153 pipe component catalogue
with built-in component tables and BOM assembly.

Public API
----------
PipeComponent         — dataclass representing a single catalogue entry
PipeCatalogue         — collection with filter/query helpers
asme_b16_5_flange_catalog()         — flanges (sizes 0.5"–24", classes 150–2500)
asme_b16_9_buttweld_fitting_catalog() — elbows, tees, reducers
api_6d_valve_catalog()               — gate, ball, check, plug valves
compute_pipe_run_bom()               — assemble BOM for a pipe run

References
----------
ASME B16.5-2020 — Pipe Flanges and Flanged Fittings (NPS ½ Through NPS 24)
ASME B16.9-2018 — Factory-Made Wrought Buttwelding Fittings
API Spec 6D-2014 — Specification for Pipeline and Piping Valves
AWWA C153/A21.53 — Ductile-Iron Compact Fittings

Wave 12B: AVEVA E3D parity (piping catalog + multi-discipline + concurrent)

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PipeComponent:
    """Single catalogue entry for a pipe component.

    catalog_standard: 'ASME B16.5' | 'ASME B16.9' | 'API 6D' | 'AWWA C153'
    component_type:   'flange' | 'elbow' | 'tee' | 'reducer' | 'valve' | 'cap' | 'cross'
    nominal_size_in:  NPS (Nominal Pipe Size) in inches
    schedule:         'SCH40' | 'SCH80' | 'SCH160' | 'XXS' | '' (for flanges/valves)
    material:         'A105' | '316L' | 'F316' | 'WPB' | 'PVC'
    pressure_class_psi: 150 | 300 | 600 | 900 | 1500 | 2500
    weight_kg:        component mass per ASME tables
    cost_usd:         midstream indicative price (2024 USD); HONEST — production needs vendor quotes
    """
    component_id: str
    catalog_standard: str
    component_type: str
    nominal_size_in: float
    schedule: str
    material: str
    pressure_class_psi: int
    weight_kg: float
    cost_usd: float
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "catalog_standard": self.catalog_standard,
            "component_type": self.component_type,
            "nominal_size_in": self.nominal_size_in,
            "schedule": self.schedule,
            "material": self.material,
            "pressure_class_psi": self.pressure_class_psi,
            "weight_kg": self.weight_kg,
            "cost_usd": self.cost_usd,
            "description": self.description,
        }


@dataclass
class PipeCatalogue:
    """Collection of PipeComponent entries with query helpers."""

    components: list[PipeComponent] = field(default_factory=list)

    def by_type(self, ct: str) -> list[PipeComponent]:
        """Return all components matching *component_type* (case-insensitive)."""
        ct_lower = ct.lower()
        return [c for c in self.components if c.component_type.lower() == ct_lower]

    def by_size(self, size_in: float, tol: float = 1e-6) -> list[PipeComponent]:
        """Return all components with *nominal_size_in* == *size_in*."""
        return [c for c in self.components if abs(c.nominal_size_in - size_in) < tol]

    def filter(self, **kwargs) -> list[PipeComponent]:
        """Filter catalogue by any combination of PipeComponent fields.

        Numeric fields use approximate equality (tol=1e-6).
        String fields are compared case-insensitively.

        Example::

            cat.filter(component_type='elbow', nominal_size_in=4.0)
        """
        results = self.components
        for attr, val in kwargs.items():
            if not hasattr(PipeComponent, attr) and attr not in vars(self.components[0] if self.components else PipeComponent):
                # Try it anyway — will filter to empty on unknown attr
                pass
            if isinstance(val, float):
                results = [c for c in results if abs((getattr(c, attr, None) or -1e9) - val) < 1e-6]
            elif isinstance(val, str):
                v_lower = val.lower()
                results = [c for c in results if (getattr(c, attr, "") or "").lower() == v_lower]
            elif isinstance(val, int):
                results = [c for c in results if getattr(c, attr, None) == val]
            else:
                results = [c for c in results if getattr(c, attr, None) == val]
        return results

    def __len__(self) -> int:
        return len(self.components)

    def __iter__(self):
        return iter(self.components)


# ---------------------------------------------------------------------------
# ASME B16.5 flange weight / cost tables
# ---------------------------------------------------------------------------
# Weight data per ASME B16.5-2020 Table 1 (raised-face forged steel flanges).
# Cost data: indicative 2024 midstream pricing for A105 carbon steel.
# HONEST: representative pricing — production deployments must obtain vendor quotes.
#
# Columns: (NPS, class, weight_kg, cost_usd)
# NPS in inches; class = pressure class in psi

_B16_5_FLANGE_DATA: list[tuple[float, int, float, float]] = [
    # 0.5" (DN15)
    (0.5, 150,  0.36,  12.0),
    (0.5, 300,  0.52,  16.0),
    (0.5, 600,  0.68,  22.0),
    (0.5, 900,  0.91,  30.0),
    (0.5, 1500, 1.18,  42.0),
    (0.5, 2500, 1.82,  68.0),
    # 0.75" (DN20)
    (0.75, 150,  0.45,  14.0),
    (0.75, 300,  0.63,  18.0),
    (0.75, 600,  0.82,  25.0),
    (0.75, 900,  1.09,  36.0),
    (0.75, 1500, 1.41,  50.0),
    (0.75, 2500, 2.18,  82.0),
    # 1" (DN25)
    (1.0, 150,  0.59,  18.0),
    (1.0, 300,  0.82,  23.0),
    (1.0, 600,  1.09,  32.0),
    (1.0, 900,  1.45,  46.0),
    (1.0, 1500, 1.91,  64.0),
    (1.0, 2500, 2.95,  99.0),
    # 1.25" (DN32)
    (1.25, 150,  0.73,  22.0),
    (1.25, 300,  1.00,  28.0),
    (1.25, 600,  1.36,  38.0),
    (1.25, 900,  1.82,  56.0),
    (1.25, 1500, 2.36,  78.0),
    (1.25, 2500, 3.63, 121.0),
    # 1.5" (DN40)
    (1.5, 150,  0.91,  26.0),
    (1.5, 300,  1.27,  34.0),
    (1.5, 600,  1.72,  47.0),
    (1.5, 900,  2.27,  70.0),
    (1.5, 1500, 2.95,  96.0),
    (1.5, 2500, 4.54, 150.0),
    # 2" (DN50)
    (2.0, 150,  1.45,  38.0),
    (2.0, 300,  2.00,  52.0),
    (2.0, 600,  2.72,  72.0),
    (2.0, 900,  3.63,  98.0),
    (2.0, 1500, 4.72, 130.0),
    (2.0, 2500, 7.26, 200.0),
    # 2.5" (DN65)
    (2.5, 150,  1.91,  49.0),
    (2.5, 300,  2.72,  68.0),
    (2.5, 600,  3.63,  92.0),
    (2.5, 900,  4.90, 128.0),
    (2.5, 1500, 6.35, 168.0),
    (2.5, 2500, 9.98, 264.0),
    # 3" (DN80)
    (3.0, 150,  2.72,  64.0),
    (3.0, 300,  3.86,  90.0),
    (3.0, 600,  5.22, 122.0),
    (3.0, 900,  6.80, 162.0),
    (3.0, 1500, 9.07, 220.0),
    (3.0, 2500, 14.06, 340.0),
    # 4" (DN100)
    (4.0, 150,  4.54,  98.0),
    (4.0, 300,  6.35, 136.0),
    (4.0, 600,  8.62, 186.0),
    (4.0, 900,  11.79, 254.0),
    (4.0, 1500, 15.42, 334.0),
    (4.0, 2500, 24.04, 520.0),
    # 6" (DN150)
    (6.0, 150,  8.62, 162.0),
    (6.0, 300, 12.25, 228.0),
    (6.0, 600, 16.78, 310.0),
    (6.0, 900, 22.68, 420.0),
    (6.0, 1500, 29.94, 556.0),
    (6.0, 2500, 46.27, 860.0),
    # 8" (DN200)
    (8.0, 150,  14.06, 248.0),
    (8.0, 300,  19.96, 348.0),
    (8.0, 600,  27.22, 476.0),
    (8.0, 900,  36.29, 636.0),
    (8.0, 1500, 47.63, 840.0),
    (8.0, 2500, 72.58, 1280.0),
    # 10" (DN250)
    (10.0, 150,  21.32,  360.0),
    (10.0, 300,  29.94,  506.0),
    (10.0, 600,  41.28,  696.0),
    (10.0, 900,  54.43,  920.0),
    (10.0, 1500, 72.58, 1220.0),
    (10.0, 2500, 110.22, 1860.0),
    # 12" (DN300)
    (12.0, 150,  29.94,  490.0),
    (12.0, 300,  42.18,  690.0),
    (12.0, 600,  57.15,  940.0),
    (12.0, 900,  75.75, 1240.0),
    (12.0, 1500, 100.70, 1660.0),
    (12.0, 2500, 154.22, 2540.0),
    # 16" (DN400)
    (16.0, 150,  51.26,  780.0),
    (16.0, 300,  71.67, 1100.0),
    (16.0, 600,  98.88, 1520.0),
    (16.0, 900, 130.63, 2010.0),
    (16.0, 1500, 172.37, 2660.0),
    (16.0, 2500, 263.09, 4060.0),
    # 20" (DN500)
    (20.0, 150,   84.37, 1180.0),
    (20.0, 300,  118.39, 1660.0),
    (20.0, 600,  162.39, 2280.0),
    (20.0, 900,  213.19, 3000.0),
    (20.0, 1500, 281.24, 3960.0),
    (20.0, 2500, 430.91, 6060.0),
    # 24" (DN600)
    (24.0, 150,  128.82, 1660.0),
    (24.0, 300,  180.53, 2340.0),
    (24.0, 600,  247.21, 3200.0),
    (24.0, 900,  325.30, 4220.0),
    (24.0, 1500, 427.92, 5560.0),
    (24.0, 2500, 653.17, 8500.0),
]


def asme_b16_5_flange_catalog() -> PipeCatalogue:
    """Built-in catalog of ASME B16.5 raised-face weld-neck flanges.

    Sizes: NPS 0.5" through 24" (½ DN15 to DN600).
    Pressure classes: 150 / 300 / 600 / 900 / 1500 / 2500.
    Material: A105 carbon steel (standard stock material).

    Weight per ASME B16.5-2020 Table 1 (approximate; RTJ flanges ~5% heavier).
    Cost: indicative 2024 midstream pricing in USD.
    HONEST: representative midstream pricing — production needs vendor quotes.

    Reference: ASME B16.5-2020, Pipe Flanges and Flanged Fittings NPS ½ Through NPS 24.
    """
    components = []
    for nps, cls, wt_kg, cost_usd in _B16_5_FLANGE_DATA:
        cid = f"B165-FL-{str(nps).replace('.', '_')}-{cls}"
        nps_str = str(nps).rstrip("0").rstrip(".")
        desc = f"ASME B16.5 WN Flange {nps_str}\" Class {cls} A105 RF"
        components.append(PipeComponent(
            component_id=cid,
            catalog_standard="ASME B16.5",
            component_type="flange",
            nominal_size_in=float(nps),
            schedule="",
            material="A105",
            pressure_class_psi=cls,
            weight_kg=wt_kg,
            cost_usd=cost_usd,
            description=desc,
        ))
    return PipeCatalogue(components=components)


# ---------------------------------------------------------------------------
# ASME B16.9 butt-weld fitting tables
# ---------------------------------------------------------------------------
# Ref: ASME B16.9-2018 Factory-Made Wrought Buttwelding Fittings
# Weight data approximated from published tables; material WPB (ASTM A234).
# Cost: indicative 2024 midstream USD. HONEST: production needs vendor quotes.

# (NPS, type, schedule, weight_kg, cost_usd, description)
_B16_9_DATA: list[tuple[float, str, str, float, float, str]] = [
    # 90° long-radius elbow
    (0.5,  "elbow", "SCH40", 0.10,  5.0, "90° LR Elbow 0.5\" SCH40 WPB"),
    (0.75, "elbow", "SCH40", 0.14,  6.0, "90° LR Elbow 0.75\" SCH40 WPB"),
    (1.0,  "elbow", "SCH40", 0.20,  8.0, "90° LR Elbow 1\" SCH40 WPB"),
    (1.5,  "elbow", "SCH40", 0.36, 11.0, "90° LR Elbow 1.5\" SCH40 WPB"),
    (2.0,  "elbow", "SCH40", 0.59, 15.0, "90° LR Elbow 2\" SCH40 WPB"),
    (3.0,  "elbow", "SCH40", 1.50, 29.0, "90° LR Elbow 3\" SCH40 WPB"),
    (4.0,  "elbow", "SCH40", 3.00, 52.0, "90° LR Elbow 4\" SCH40 WPB"),
    (6.0,  "elbow", "SCH40", 7.71, 106.0, "90° LR Elbow 6\" SCH40 WPB"),
    (8.0,  "elbow", "SCH40", 16.33, 196.0, "90° LR Elbow 8\" SCH40 WPB"),
    (10.0, "elbow", "SCH40", 30.39, 340.0, "90° LR Elbow 10\" SCH40 WPB"),
    (12.0, "elbow", "SCH40", 49.44, 520.0, "90° LR Elbow 12\" SCH40 WPB"),
    # SCH80 elbows
    (1.0,  "elbow", "SCH80", 0.23,  9.5, "90° LR Elbow 1\" SCH80 WPB"),
    (2.0,  "elbow", "SCH80", 0.68, 17.0, "90° LR Elbow 2\" SCH80 WPB"),
    (4.0,  "elbow", "SCH80", 3.50, 58.0, "90° LR Elbow 4\" SCH80 WPB"),
    (6.0,  "elbow", "SCH80", 9.07, 120.0, "90° LR Elbow 6\" SCH80 WPB"),
    # 45° elbows
    (2.0,  "elbow", "SCH40", 0.36, 12.0, "45° LR Elbow 2\" SCH40 WPB"),
    (4.0,  "elbow", "SCH40", 1.81, 42.0, "45° LR Elbow 4\" SCH40 WPB"),
    # Equal tees
    (0.5,  "tee", "SCH40", 0.14,  7.0, "Equal Tee 0.5\" SCH40 WPB"),
    (1.0,  "tee", "SCH40", 0.27, 11.0, "Equal Tee 1\" SCH40 WPB"),
    (2.0,  "tee", "SCH40", 0.77, 20.0, "Equal Tee 2\" SCH40 WPB"),
    (3.0,  "tee", "SCH40", 1.95, 39.0, "Equal Tee 3\" SCH40 WPB"),
    (4.0,  "tee", "SCH40", 3.97, 70.0, "Equal Tee 4\" SCH40 WPB"),
    (6.0,  "tee", "SCH40", 9.98, 142.0, "Equal Tee 6\" SCH40 WPB"),
    (8.0,  "tee", "SCH40", 21.32, 262.0, "Equal Tee 8\" SCH40 WPB"),
    (10.0, "tee", "SCH40", 39.92, 455.0, "Equal Tee 10\" SCH40 WPB"),
    (12.0, "tee", "SCH40", 64.86, 700.0, "Equal Tee 12\" SCH40 WPB"),
    # Concentric reducers
    (3.0,  "reducer", "SCH40", 0.91, 28.0, "Con Reducer 3x2\" SCH40 WPB"),
    (4.0,  "reducer", "SCH40", 1.36, 38.0, "Con Reducer 4x3\" SCH40 WPB"),
    (6.0,  "reducer", "SCH40", 3.18, 72.0, "Con Reducer 6x4\" SCH40 WPB"),
    (8.0,  "reducer", "SCH40", 6.35, 130.0, "Con Reducer 8x6\" SCH40 WPB"),
    (10.0, "reducer", "SCH40", 11.34, 230.0, "Con Reducer 10x8\" SCH40 WPB"),
    (12.0, "reducer", "SCH40", 17.69, 358.0, "Con Reducer 12x10\" SCH40 WPB"),
    # Caps
    (2.0,  "cap", "SCH40", 0.23, 10.0, "Cap 2\" SCH40 WPB"),
    (4.0,  "cap", "SCH40", 0.68, 22.0, "Cap 4\" SCH40 WPB"),
    (6.0,  "cap", "SCH40", 1.59, 46.0, "Cap 6\" SCH40 WPB"),
    (8.0,  "cap", "SCH40", 3.18, 84.0, "Cap 8\" SCH40 WPB"),
    # Cross
    (2.0,  "cross", "SCH40", 1.04, 28.0, "Equal Cross 2\" SCH40 WPB"),
    (4.0,  "cross", "SCH40", 5.31, 90.0, "Equal Cross 4\" SCH40 WPB"),
    (6.0,  "cross", "SCH40", 13.61, 190.0, "Equal Cross 6\" SCH40 WPB"),
]


def asme_b16_9_buttweld_fitting_catalog() -> PipeCatalogue:
    """ASME B16.9 factory-made wrought buttwelding fittings.

    Includes:
    - 90° long-radius (LR) elbows and 45° LR elbows (SCH40 and SCH80)
    - Equal tees
    - Concentric reducers
    - Caps and equal crosses

    Material: WPB (ASTM A234 Grade WPB).
    HONEST: representative 2024 midstream pricing — production needs vendor quotes.

    Reference: ASME B16.9-2018, Factory-Made Wrought Buttwelding Fittings.
    """
    components = []
    seen: dict[str, int] = {}
    for nps, ctype, sched, wt, cost, desc in _B16_9_DATA:
        base_id = f"B169-{ctype.upper()}-{str(nps).replace('.','_')}-{sched}"
        idx = seen.get(base_id, 0)
        cid = f"{base_id}-{idx:02d}" if idx else base_id
        seen[base_id] = idx + 1
        components.append(PipeComponent(
            component_id=cid,
            catalog_standard="ASME B16.9",
            component_type=ctype,
            nominal_size_in=float(nps),
            schedule=sched,
            material="WPB",
            pressure_class_psi=0,         # B16.9 rated by schedule/wall, not class
            weight_kg=wt,
            cost_usd=cost,
            description=desc,
        ))
    return PipeCatalogue(components=components)


# ---------------------------------------------------------------------------
# API 6D valve tables
# ---------------------------------------------------------------------------
# Ref: API Spec 6D-2014, Specification for Pipeline and Piping Valves
# (gate, ball, check, plug; pipeline service; ANSI pressure classes)
# Weight / cost: indicative 2024 A105 body API 6D carbon steel.
# HONEST: representative pricing only.

# (NPS, valve_type, class, weight_kg, cost_usd)
_API_6D_DATA: list[tuple[float, str, int, float, float]] = [
    # Gate valves
    (2.0,  "valve", 150, 11.3,   240.0),
    (2.0,  "valve", 300, 15.4,   320.0),
    (3.0,  "valve", 150, 22.7,   380.0),
    (3.0,  "valve", 300, 29.5,   500.0),
    (4.0,  "valve", 150, 38.6,   560.0),
    (4.0,  "valve", 300, 52.2,   760.0),
    (6.0,  "valve", 150, 82.6,  1100.0),
    (6.0,  "valve", 300, 113.4, 1500.0),
    (8.0,  "valve", 150, 154.2, 1820.0),
    (8.0,  "valve", 300, 213.2, 2480.0),
    (10.0, "valve", 150, 245.0, 2900.0),
    (10.0, "valve", 300, 340.0, 4000.0),
    (12.0, "valve", 150, 381.0, 4400.0),
    (12.0, "valve", 300, 522.0, 6000.0),
    # Ball valves
    (1.0,  "valve", 150,  5.4,   140.0),
    (2.0,  "valve", 150, 13.6,   280.0),
    (3.0,  "valve", 150, 27.2,   440.0),
    (4.0,  "valve", 150, 49.9,   680.0),
    (6.0,  "valve", 150, 108.9, 1300.0),
    (8.0,  "valve", 150, 181.4, 2200.0),
    # Check valves (swing type)
    (2.0,  "valve", 150,  8.2,   190.0),
    (4.0,  "valve", 150, 28.6,   480.0),
    (6.0,  "valve", 150, 63.5,   940.0),
    (8.0,  "valve", 150, 113.4, 1560.0),
    # Plug valves
    (2.0,  "valve", 150, 10.0,   220.0),
    (4.0,  "valve", 150, 36.3,   560.0),
    (6.0,  "valve", 150, 79.4, 1050.0),
]


def api_6d_valve_catalog() -> PipeCatalogue:
    """API 6D pipeline valves.

    Includes: gate, ball, check, and plug valves.
    Material: A105 body (carbon steel), trim per API 6D Table 1.
    Classes: ANSI 150 and 300 (most common pipeline service).

    HONEST: representative 2024 industry pricing — production needs vendor quotes.

    Reference: API Spec 6D-2014, Specification for Pipeline and Piping Valves (25th ed.).
    """
    components = []
    seen: dict[str, int] = {}
    valve_subtypes = ["gate", "gate", "gate", "gate", "gate", "gate",
                      "gate", "gate", "gate", "gate", "gate", "gate",
                      "gate", "gate",
                      "ball", "ball", "ball", "ball", "ball", "ball",
                      "check", "check", "check", "check",
                      "plug", "plug", "plug"]
    for (nps, ctype, cls, wt, cost), subtype in zip(_API_6D_DATA, valve_subtypes):
        base_id = f"API6D-{subtype.upper()}-{str(nps).replace('.','_')}-CL{cls}"
        idx = seen.get(base_id, 0)
        cid = f"{base_id}-{idx:02d}" if idx else base_id
        seen[base_id] = idx + 1
        desc = f"API 6D {subtype.capitalize()} Valve {nps}\" Class {cls} A105"
        components.append(PipeComponent(
            component_id=cid,
            catalog_standard="API 6D",
            component_type=ctype,
            nominal_size_in=float(nps),
            schedule="",
            material="A105",
            pressure_class_psi=cls,
            weight_kg=wt,
            cost_usd=cost,
            description=desc,
        ))
    return PipeCatalogue(components=components)


# ---------------------------------------------------------------------------
# Pipe BOM calculation
# ---------------------------------------------------------------------------

# ASME B36.10M pipe wall thickness table: (NPS, schedule) → (OD_mm, t_mm)
# OD per ASME B36.10M Table 1; wall per schedule columns.
_PIPE_DIM: dict[tuple[float, str], tuple[float, float]] = {
    (0.5, "SCH40"): (21.34, 2.77), (0.5, "SCH80"): (21.34, 3.73),
    (0.75, "SCH40"): (26.67, 2.87), (0.75, "SCH80"): (26.67, 3.91),
    (1.0, "SCH40"): (33.40, 3.38), (1.0, "SCH80"): (33.40, 4.55),
    (1.5, "SCH40"): (48.26, 3.68), (1.5, "SCH80"): (48.26, 5.08),
    (2.0, "SCH40"): (60.33, 3.91), (2.0, "SCH80"): (60.33, 5.54),
    (3.0, "SCH40"): (88.90, 5.49), (3.0, "SCH80"): (88.90, 7.62),
    (4.0, "SCH40"): (114.30, 6.02), (4.0, "SCH80"): (114.30, 8.56),
    (6.0, "SCH40"): (168.28, 7.11), (6.0, "SCH80"): (168.28, 10.97),
    (8.0, "SCH40"): (219.08, 8.18), (8.0, "SCH80"): (219.08, 12.70),
    (10.0, "SCH40"): (273.05, 9.27), (10.0, "SCH80"): (273.05, 15.09),
    (12.0, "SCH40"): (323.85, 9.53), (12.0, "SCH80"): (323.85, 17.48),
    (16.0, "SCH40"): (406.40, 9.53), (16.0, "SCH80"): (406.40, 21.44),
    (20.0, "SCH40"): (508.00, 9.53), (20.0, "SCH80"): (508.00, 23.01),
    (24.0, "SCH40"): (609.60, 9.53), (24.0, "SCH80"): (609.60, 24.61),
    # SCH160
    (1.0, "SCH160"): (33.40, 6.35), (2.0, "SCH160"): (60.33, 8.74),
    (4.0, "SCH160"): (114.30, 13.49), (6.0, "SCH160"): (168.28, 18.26),
    (8.0, "SCH160"): (219.08, 23.01), (10.0, "SCH160"): (273.05, 28.58),
    (12.0, "SCH160"): (323.85, 33.32),
    # XXS
    (1.0, "XXS"): (33.40, 9.09), (2.0, "XXS"): (60.33, 11.07),
    (4.0, "XXS"): (114.30, 17.12), (6.0, "XXS"): (168.28, 21.95),
    (8.0, "XXS"): (219.08, 22.23), (10.0, "XXS"): (273.05, 25.40),
    (12.0, "XXS"): (323.85, 25.40),
}

# Carbon steel density (kg/m³)
_STEEL_DENSITY_KG_M3 = 7850.0

# Approximate pipe cost per metre (2024 USD/m); keyed (NPS, schedule).
# HONEST: representative 2024 distributor list pricing; production needs vendor quotes.
_PIPE_COST_USD_PER_M: dict[tuple[float, str], float] = {
    (1.0, "SCH40"): 6.0,  (1.0, "SCH80"): 9.0,
    (2.0, "SCH40"): 11.0, (2.0, "SCH80"): 16.0,
    (3.0, "SCH40"): 19.0, (3.0, "SCH80"): 27.0,
    (4.0, "SCH40"): 28.0, (4.0, "SCH80"): 40.0,  (4.0, "SCH160"): 58.0,
    (6.0, "SCH40"): 52.0, (6.0, "SCH80"): 76.0,
    (8.0, "SCH40"): 82.0, (8.0, "SCH80"): 124.0,
    (10.0, "SCH40"): 130.0, (10.0, "SCH80"): 198.0,
    (12.0, "SCH40"): 190.0, (12.0, "SCH80"): 286.0,
}


def compute_pipe_run_bom(
    pipe_segments: list[dict],
    catalogue: PipeCatalogue,
) -> dict:
    """Assemble BOM for a piping run, matching fittings from the given catalogue.

    Each segment dict should contain:
      - from (str): start tag
      - to (str): end tag
      - size_in (float): NPS in inches
      - schedule (str): 'SCH40' | 'SCH80' | ...
      - length_m (float): pipe spool length in metres
      - material (str): pipe material designation
      - n_elbows (int, optional): number of elbows on this segment (default 0)
      - n_flanges (int, optional): number of flange pairs (default 2 = per segment end)

    Returns:
      {
        ok: True,
        total_weight_kg: float,
        total_cost_usd: float,
        line_items: list[{description, qty, unit_weight_kg, unit_cost_usd, ...}]
      }

    HONEST: fitting counts are user-supplied; BOM is a budgetary estimate only.
    Production BOM needs isometric extraction and vendor quotes.

    Reference: ASME B16.5-2020 § for flange weight; ASME B36.10M-2018 for pipe wall.
    """
    line_items: list[dict] = []
    total_weight = 0.0
    total_cost = 0.0

    for seg in pipe_segments:
        size_in = float(seg.get("size_in", 0))
        schedule = str(seg.get("schedule", "SCH40")).upper()
        length_m = float(seg.get("length_m", 0.0))
        n_elbows = int(seg.get("n_elbows", 0))
        n_flanges = int(seg.get("n_flanges", 2))
        material = str(seg.get("material", "CS"))

        # -- Pipe spool weight -----------------------------------------------
        dim_key = (size_in, schedule)
        if dim_key in _PIPE_DIM:
            od_mm, t_mm = _PIPE_DIM[dim_key]
            od_m = od_mm / 1000.0
            t_m = t_mm / 1000.0
            r_out = od_m / 2.0
            r_in = r_out - t_m
            area_m2 = math.pi * (r_out**2 - r_in**2)
            pipe_wt = area_m2 * length_m * _STEEL_DENSITY_KG_M3
        else:
            pipe_wt = 0.0  # unknown schedule — skip weight

        pipe_cost_key = (size_in, schedule)
        pipe_cost = _PIPE_COST_USD_PER_M.get(pipe_cost_key, 0.0) * length_m

        item_pipe: dict = {
            "description": f"Pipe NPS {size_in}\" {schedule} {material} L={length_m:.1f}m",
            "qty": 1,
            "unit_weight_kg": round(pipe_wt, 3),
            "unit_cost_usd": round(pipe_cost, 2),
        }
        total_weight += pipe_wt
        total_cost += pipe_cost
        line_items.append(item_pipe)

        # -- Elbows from catalogue -------------------------------------------
        if n_elbows > 0:
            elbows = catalogue.filter(component_type="elbow", nominal_size_in=size_in, schedule=schedule)
            if elbows:
                el = elbows[0]
                elbow_wt = el.weight_kg * n_elbows
                elbow_cost = el.cost_usd * n_elbows
                item_elbow: dict = {
                    "description": f"{n_elbows}x {el.description}",
                    "qty": n_elbows,
                    "unit_weight_kg": el.weight_kg,
                    "unit_cost_usd": el.cost_usd,
                }
                total_weight += elbow_wt
                total_cost += elbow_cost
                line_items.append(item_elbow)
            else:
                # Approximate fallback: 0.5 kg/elbow for small bore, linear scale
                est_wt_ea = max(0.2, size_in * 0.4)
                est_cost_ea = max(8.0, size_in * 12.0)
                item_elbow_est: dict = {
                    "description": f"{n_elbows}x Elbow NPS {size_in}\" {schedule} (estimated)",
                    "qty": n_elbows,
                    "unit_weight_kg": round(est_wt_ea, 3),
                    "unit_cost_usd": round(est_cost_ea, 2),
                }
                total_weight += est_wt_ea * n_elbows
                total_cost += est_cost_ea * n_elbows
                line_items.append(item_elbow_est)

        # -- Flanges from catalogue ------------------------------------------
        if n_flanges > 0:
            flanges = catalogue.filter(component_type="flange", nominal_size_in=size_in)
            if flanges:
                fl = flanges[0]
                fl_wt = fl.weight_kg * n_flanges
                fl_cost = fl.cost_usd * n_flanges
                item_fl: dict = {
                    "description": f"{n_flanges}x {fl.description}",
                    "qty": n_flanges,
                    "unit_weight_kg": fl.weight_kg,
                    "unit_cost_usd": fl.cost_usd,
                }
                total_weight += fl_wt
                total_cost += fl_cost
                line_items.append(item_fl)

    return {
        "ok": True,
        "total_weight_kg": round(total_weight, 3),
        "total_cost_usd": round(total_cost, 2),
        "line_items": line_items,
    }
