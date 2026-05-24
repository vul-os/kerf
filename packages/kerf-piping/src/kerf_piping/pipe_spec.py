"""
kerf_piping.pipe_spec — Pipe specification class enforcement.

Implements spec-driven pipe selection per:
  - ASME B36.10M: Welded and Seamless Wrought Steel Pipe (wall thicknesses, schedules)
  - ASME B31.3: Process Piping (pressure-temperature ratings, material selection)
  - ASME B16.9: Factory-Made Wrought Butt-Welding Fittings
  - API 5L: Line pipe for oil/gas transport

A ``PipeSpec`` defines the engineering rules for a pipe class:
  - permitted nominal diameters (DN)
  - schedule(s) for each diameter
  - material grade and design temperature/pressure limits
  - corrosion allowance
  - end preparation (BW/SW/flanged)

Key functions
-------------
PipeSpec                      — Pipe class definition.
select_schedule(dn, spec)     — Return schedule for a given DN per spec rules.
wall_thickness_mm(dn, sched)  — ASME B36.10M actual wall thickness.
min_wall_required(dn, P_barg, material) — Barlow's formula: minimum required wall.
check_spec_compliance(pipe, spec)       — Validate a Pipe against a PipeSpec.

References
----------
ASME B36.10M-2018, Tables 1-9 — Nominal pipe sizes, schedules, wall thicknesses.
ASME B31.3-2022, §302.1 — Design pressure / allowable stress.
ASME B16.9-2018 — Long-radius elbow dimensions.
API 5L-2018 — Line pipe grades and min wall.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from kerf_piping.pid import PipeSchedule


# ---------------------------------------------------------------------------
# ASME B36.10M wall thickness table (mm)
# Key: (nominal_dn_mm, schedule_code)
# Schedule codes: "10", "20", "30", "40", "60", "80", "100", "120", "140", "160",
#                 "STD", "XS", "XXS"
# Source: ASME B36.10M-2018 Table 1
# ---------------------------------------------------------------------------

WALL_THICKNESS_MM: Dict[Tuple[int, str], float] = {
    # DN 15 (NPS 1/2")
    (15, "40"): 2.77,  (15, "STD"): 2.77,
    (15, "80"): 3.73,  (15, "XS"): 3.73,
    (15, "160"): 4.78, (15, "XXS"): 7.47,
    # DN 20 (NPS 3/4")
    (20, "40"): 2.87,  (20, "STD"): 2.87,
    (20, "80"): 3.91,  (20, "XS"): 3.91,
    (20, "160"): 5.56, (20, "XXS"): 7.82,
    # DN 25 (NPS 1")
    (25, "40"): 3.38,  (25, "STD"): 3.38,
    (25, "80"): 4.55,  (25, "XS"): 4.55,
    (25, "160"): 6.35, (25, "XXS"): 9.09,
    # DN 32 (NPS 1-1/4")
    (32, "40"): 3.56,  (32, "STD"): 3.56,
    (32, "80"): 4.85,  (32, "XS"): 4.85,
    (32, "160"): 8.08, (32, "XXS"): 9.70,
    # DN 40 (NPS 1-1/2")
    (40, "40"): 3.68,  (40, "STD"): 3.68,
    (40, "80"): 5.08,  (40, "XS"): 5.08,
    (40, "160"): 9.09, (40, "XXS"): 10.16,
    # DN 50 (NPS 2")
    (50, "40"): 3.91,  (50, "STD"): 3.91,
    (50, "80"): 5.54,  (50, "XS"): 5.54,
    (50, "160"): 8.74, (50, "XXS"): 11.07,
    # DN 65 (NPS 2-1/2")
    (65, "40"): 5.16,  (65, "STD"): 5.16,
    (65, "80"): 7.01,  (65, "XS"): 7.01,
    (65, "160"): 9.53, (65, "XXS"): 14.02,
    # DN 80 (NPS 3")
    (80, "40"): 5.49,  (80, "STD"): 5.49,
    (80, "80"): 7.62,  (80, "XS"): 7.62,
    (80, "160"): 11.13, (80, "XXS"): 15.24,
    # DN 100 (NPS 4")
    (100, "40"): 6.02,  (100, "STD"): 6.02,
    (100, "80"): 8.56,  (100, "XS"): 8.56,
    (100, "120"): 11.13,
    (100, "160"): 13.49, (100, "XXS"): 17.12,
    # DN 150 (NPS 6")
    (150, "40"): 7.11,  (150, "STD"): 7.11,
    (150, "80"): 10.97, (150, "XS"): 10.97,
    (150, "120"): 14.27,
    (150, "160"): 18.26, (150, "XXS"): 21.95,
    # DN 200 (NPS 8")
    (200, "20"): 6.35,
    (200, "30"): 7.04,
    (200, "40"): 8.18,  (200, "STD"): 9.53,
    (200, "60"): 10.31,
    (200, "80"): 12.70, (200, "XS"): 12.70,
    (200, "100"): 15.09,
    (200, "120"): 18.26,
    (200, "140"): 20.62,
    (200, "160"): 23.01, (200, "XXS"): 22.23,
    # DN 250 (NPS 10")
    (250, "20"): 6.35,
    (250, "30"): 7.80,
    (250, "40"): 9.27,  (250, "STD"): 9.27,
    (250, "60"): 12.70,
    (250, "80"): 15.09, (250, "XS"): 12.70,
    (250, "100"): 18.26,
    (250, "120"): 21.44,
    (250, "140"): 25.40,
    (250, "160"): 28.58, (250, "XXS"): 25.40,
    # DN 300 (NPS 12")
    (300, "20"): 6.35,
    (300, "30"): 8.38,
    (300, "40"): 10.31,
    (300, "STD"): 9.53,
    (300, "60"): 14.27,
    (300, "80"): 17.48, (300, "XS"): 12.70,
    (300, "100"): 21.44,
    (300, "120"): 25.40,
    (300, "140"): 28.58,
    (300, "160"): 33.32, (300, "XXS"): 25.40,
}

# Nominal OD table (mm) per ASME B36.10M
NOMINAL_OD_MM: Dict[int, float] = {
    6:  10.287,
    8:  13.716,
    10: 17.145,
    15: 21.336,
    20: 26.670,
    25: 33.401,
    32: 42.164,
    40: 48.260,
    50: 60.325,
    65: 73.025,
    80: 88.900,
    100: 114.300,
    125: 141.300,
    150: 168.275,
    200: 219.075,
    250: 273.050,
    300: 323.850,
    350: 355.600,
    400: 406.400,
    450: 457.200,
    500: 508.000,
    600: 609.600,
}

# ASME B31.3 Table A-1 basic allowable stress (MPa) — common materials at 20°C
# Key: (material_spec, grade)
ALLOWABLE_STRESS_MPA: Dict[Tuple[str, str], float] = {
    ("A106", "B"): 117.2,    # Carbon steel seamless
    ("A53",  "B"): 103.4,    # Black / galv steel
    ("A312", "316L"): 115.1, # SS 316L
    ("A312", "304L"): 115.1, # SS 304L
    ("A333", "6"):  138.0,   # Low-temp alloy (−50°C)
    ("API5L", "X42"): 144.8, # Line pipe X42
    ("API5L", "X52"): 179.3, # Line pipe X52
    ("API5L", "X65"): 224.1, # Line pipe X65
}

# Maximum allowable service temperature (°C) — simplified; real B31.3 curves needed
MAX_TEMP_C: Dict[str, float] = {
    "A106": 427.0,
    "A53":  370.0,
    "A312": 482.0,
    "A333": 343.0,
    "API5L": 121.0,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MaterialSpec:
    """Pipe material specification.

    Parameters
    ----------
    spec       ASME / API material designation (e.g. 'A106', 'A312', 'API5L').
    grade      Material grade (e.g. 'B', '316L', 'X52').
    allowable_stress_mpa   Basic allowable stress per ASME B31.3 at design temp.
    max_temp_c             Maximum service temperature.
    corrosion_allowance_mm Corrosion allowance to add to minimum required wall.
    """
    spec: str = "A106"
    grade: str = "B"
    allowable_stress_mpa: float = 117.2
    max_temp_c: float = 427.0
    corrosion_allowance_mm: float = 1.5

    @classmethod
    def from_designation(
        cls,
        spec: str,
        grade: str,
        corrosion_allowance_mm: float = 1.5,
    ) -> "MaterialSpec":
        """Build a MaterialSpec from the ASME/API designation look-up tables."""
        key = (spec.upper(), grade.upper())
        stress = ALLOWABLE_STRESS_MPA.get(key)
        if stress is None:
            raise ValueError(
                f"Material ({spec}, {grade}) not in allowable-stress table. "
                f"Available: {sorted(ALLOWABLE_STRESS_MPA.keys())}"
            )
        max_t = MAX_TEMP_C.get(spec.upper(), 427.0)
        return cls(
            spec=spec.upper(),
            grade=grade.upper(),
            allowable_stress_mpa=stress,
            max_temp_c=max_t,
            corrosion_allowance_mm=corrosion_allowance_mm,
        )


@dataclass
class PipeSpec:
    """
    Pipe class specification — rules for a piping class.

    A pipe class is a set of engineering rules that governs which pipe
    size/schedule combinations are permitted in a given fluid service
    and pressure/temperature envelope.  Analogous to an AVEVA E3D pipe
    class or a Caeser II material group.

    Parameters
    ----------
    name             Class identifier (e.g. 'CS-A', 'SS-HT', 'API-X52').
    material         MaterialSpec instance.
    design_pressure_barg  Class design pressure (barg).
    design_temp_c    Class design temperature (°C).
    permitted_dn     Allowed nominal diameters (mm).  Empty = any DN.
    default_schedule Default schedule code (e.g. '40', 'STD', 'XS').
    schedule_by_dn   Override schedule for specific DN sizes.
    end_prep         End preparation: 'BW' (butt-weld), 'SW' (socket-weld),
                     'FL' (flanged), 'THD' (threaded).
    """
    name: str = "CS-A"
    material: MaterialSpec = field(default_factory=MaterialSpec)
    design_pressure_barg: float = 10.0
    design_temp_c: float = 120.0
    permitted_dn: List[int] = field(default_factory=list)
    default_schedule: str = "40"
    schedule_by_dn: Dict[int, str] = field(default_factory=dict)
    end_prep: str = "BW"  # BW | SW | FL | THD


# ---------------------------------------------------------------------------
# Core engineering functions
# ---------------------------------------------------------------------------

def wall_thickness_mm(dn: int, schedule: str) -> float:
    """
    Return the ASME B36.10M nominal wall thickness for a given DN and schedule.

    Parameters
    ----------
    dn        Nominal pipe diameter (mm), e.g. 50, 100, 150.
    schedule  Schedule code string: '40', '80', 'STD', 'XS', 'XXS', etc.

    Raises
    ------
    KeyError if the (dn, schedule) combination is not in the B36.10M table.
    """
    key = (int(dn), schedule.upper())
    if key not in WALL_THICKNESS_MM:
        raise KeyError(
            f"Wall thickness not found for DN{dn} schedule {schedule!r}. "
            f"Check ASME B36.10M or add to WALL_THICKNESS_MM table."
        )
    return WALL_THICKNESS_MM[key]


def nominal_od_mm(dn: int) -> float:
    """
    Return the ASME B36.10M nominal outside diameter for a given DN size.

    Raises KeyError if DN not in table.
    """
    if dn not in NOMINAL_OD_MM:
        raise KeyError(
            f"Nominal OD not found for DN{dn}. "
            f"Check ASME B36.10M or add to NOMINAL_OD_MM table."
        )
    return NOMINAL_OD_MM[dn]


def min_wall_barlow(
    dn: int,
    design_pressure_barg: float,
    material: MaterialSpec,
    *,
    joint_factor: float = 1.0,
    mechanical_allowance_mm: float = 0.0,
) -> float:
    """
    Minimum required wall thickness via the Barlow / ASME B31.3 formula:

        t_min = P · D / (2 · S · E + 2 · Y · P) + c_a + m_a

    where:
      P   = design pressure (MPa)  [barg × 0.1 ≈ MPa for gauge P < 100 bar]
      D   = nominal outside diameter (mm)
      S   = basic allowable stress at design temperature (MPa)
      E   = joint quality factor (default 1.0 for seamless)
      Y   = temperature coefficient (0.4 for most carbon steel; simplified 0 here)
      c_a = corrosion allowance (mm)
      m_a = mechanical (thread/groove) allowance (mm)

    Reference: ASME B31.3-2022 §304.1.2 Equation (3a).

    Parameters
    ----------
    dn                    Nominal pipe diameter (mm).
    design_pressure_barg  Design gauge pressure (barg).
    material              MaterialSpec with allowable stress and corrosion allowance.
    joint_factor          E factor: 1.0 seamless, 0.85 ERW, 0.80 furnace-butt-weld.
    mechanical_allowance_mm  Thread or groove mechanical strength allowance (mm).

    Returns
    -------
    Minimum required wall thickness (mm).
    """
    P_mpa = design_pressure_barg * 0.1   # bar → MPa (exact: 1 bar = 0.1 MPa)
    D_mm = nominal_od_mm(dn)
    S = material.allowable_stress_mpa
    E = joint_factor
    Y = 0.4  # simplified temperature coefficient (ASME B31.3 Table 304.1.1 for T ≤ 482°C)
    c_a = material.corrosion_allowance_mm
    m_a = mechanical_allowance_mm

    denominator = 2.0 * S * E + 2.0 * Y * P_mpa
    if denominator <= 0.0:
        return float("inf")

    t_structural = (P_mpa * D_mm) / denominator
    return t_structural + c_a + m_a


def select_schedule(
    dn: int,
    spec: PipeSpec,
) -> str:
    """
    Select the appropriate schedule for a given DN per the pipe spec rules.

    Rules applied in order:
    1.  If the spec has a DN-specific override in ``schedule_by_dn``, use it.
    2.  Otherwise, use the spec's ``default_schedule``.
    3.  Check that the resulting wall thickness meets the Barlow minimum.

    Returns the schedule code string.

    Raises
    ------
    ValueError if the selected schedule produces insufficient wall thickness.
    """
    # DN must be permitted if the spec restricts sizes
    if spec.permitted_dn and dn not in spec.permitted_dn:
        raise ValueError(
            f"DN{dn} is not permitted by spec '{spec.name}'. "
            f"Permitted sizes: {spec.permitted_dn}"
        )

    # Pick schedule
    sched = spec.schedule_by_dn.get(dn, spec.default_schedule)

    # Verify wall thickness is adequate
    try:
        actual = wall_thickness_mm(dn, sched)
    except KeyError as exc:
        raise ValueError(f"Schedule look-up failed: {exc}") from exc

    required = min_wall_barlow(dn, spec.design_pressure_barg, spec.material)

    if actual < required:
        raise ValueError(
            f"DN{dn} schedule {sched!r}: actual wall {actual:.2f} mm < "
            f"required minimum {required:.2f} mm (Barlow/B31.3, P={spec.design_pressure_barg} barg, "
            f"material {spec.material.spec}/{spec.material.grade})."
        )

    return sched


# ---------------------------------------------------------------------------
# Compliance check
# ---------------------------------------------------------------------------

@dataclass
class SpecViolation:
    """A single spec compliance violation."""
    field: str
    actual: object
    expected: object
    reason: str


@dataclass
class SpecComplianceResult:
    """Result of check_spec_compliance."""
    compliant: bool
    violations: List[SpecViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    actual_wall_mm: float = 0.0
    min_required_wall_mm: float = 0.0
    schedule_used: str = ""

    def as_dict(self) -> dict:
        return {
            "compliant": self.compliant,
            "actual_wall_mm": round(self.actual_wall_mm, 3),
            "min_required_wall_mm": round(self.min_required_wall_mm, 3),
            "schedule_used": self.schedule_used,
            "violations": [
                {
                    "field": v.field,
                    "actual": v.actual,
                    "expected": v.expected,
                    "reason": v.reason,
                }
                for v in self.violations
            ],
            "warnings": self.warnings,
        }


def check_spec_compliance(
    dn: int,
    schedule: str,
    design_pressure_barg: float,
    design_temp_c: float,
    spec: PipeSpec,
) -> SpecComplianceResult:
    """
    Check whether a pipe (DN + schedule) complies with a PipeSpec.

    Checks performed:
    1. DN is in the permitted list (if restricted).
    2. Schedule matches the spec-driven selection rule.
    3. Actual wall thickness ≥ Barlow minimum.
    4. Design pressure ≤ spec class limit.
    5. Design temperature ≤ material maximum.

    Parameters
    ----------
    dn                    Nominal pipe diameter (mm).
    schedule              Proposed schedule code.
    design_pressure_barg  Proposed design pressure (barg).
    design_temp_c         Proposed design temperature (°C).
    spec                  PipeSpec defining the class rules.

    Returns
    -------
    SpecComplianceResult — never raises.
    """
    violations: list[SpecViolation] = []
    warnings: list[str] = []

    # 1. DN permitted
    if spec.permitted_dn and dn not in spec.permitted_dn:
        violations.append(SpecViolation(
            field="dn",
            actual=dn,
            expected=spec.permitted_dn,
            reason=f"DN{dn} not in permitted sizes {spec.permitted_dn}",
        ))

    # 2. Schedule vs spec rule
    spec_sched = spec.schedule_by_dn.get(dn, spec.default_schedule)
    if schedule.upper() != spec_sched.upper():
        warnings.append(
            f"Schedule {schedule!r} differs from spec-driven selection {spec_sched!r} "
            f"for DN{dn} in class '{spec.name}'"
        )

    # 3. Wall thickness
    actual_wall = 0.0
    min_req = 0.0
    try:
        actual_wall = wall_thickness_mm(dn, schedule)
        min_req = min_wall_barlow(dn, design_pressure_barg, spec.material)
        if actual_wall < min_req:
            violations.append(SpecViolation(
                field="wall_thickness",
                actual=actual_wall,
                expected=f">= {round(min_req, 3)} mm",
                reason=(
                    f"Wall {actual_wall:.3f} mm < Barlow minimum {min_req:.3f} mm "
                    f"(P={design_pressure_barg} barg, "
                    f"{spec.material.spec}/{spec.material.grade})"
                ),
            ))
    except KeyError as exc:
        violations.append(SpecViolation(
            field="schedule",
            actual=schedule,
            expected="valid ASME B36.10M entry",
            reason=str(exc),
        ))

    # 4. Design pressure vs class limit
    if design_pressure_barg > spec.design_pressure_barg:
        violations.append(SpecViolation(
            field="design_pressure_barg",
            actual=design_pressure_barg,
            expected=f"<= {spec.design_pressure_barg} barg",
            reason=(
                f"Design pressure {design_pressure_barg} barg exceeds "
                f"class '{spec.name}' limit {spec.design_pressure_barg} barg"
            ),
        ))

    # 5. Design temperature vs material limit
    if design_temp_c > spec.material.max_temp_c:
        violations.append(SpecViolation(
            field="design_temp_c",
            actual=design_temp_c,
            expected=f"<= {spec.material.max_temp_c} °C",
            reason=(
                f"Design temperature {design_temp_c} °C exceeds "
                f"{spec.material.spec} limit {spec.material.max_temp_c} °C"
            ),
        ))

    return SpecComplianceResult(
        compliant=len(violations) == 0,
        violations=violations,
        warnings=warnings,
        actual_wall_mm=actual_wall,
        min_required_wall_mm=min_req,
        schedule_used=schedule,
    )


# ---------------------------------------------------------------------------
# Standard pipe class library
# ---------------------------------------------------------------------------

def standard_class_cs_a(
    design_pressure_barg: float = 10.0,
    design_temp_c: float = 120.0,
    corrosion_allowance_mm: float = 1.5,
) -> PipeSpec:
    """
    Standard carbon steel Class A — general process service.

    Material: A106 Gr. B seamless, ASME B31.3.
    Typical use: water, steam, oil service up to 427°C.
    Schedules: Sch 40 for DN ≤ 150; Sch 20 for DN ≥ 200.
    """
    mat = MaterialSpec.from_designation("A106", "B", corrosion_allowance_mm)
    sched_by_dn = {200: "20", 250: "20", 300: "20"}
    return PipeSpec(
        name="CS-A",
        material=mat,
        design_pressure_barg=design_pressure_barg,
        design_temp_c=design_temp_c,
        permitted_dn=[15, 20, 25, 32, 40, 50, 65, 80, 100, 150, 200, 250, 300],
        default_schedule="40",
        schedule_by_dn=sched_by_dn,
        end_prep="BW",
    )


def standard_class_cs_hh(
    design_pressure_barg: float = 40.0,
    design_temp_c: float = 300.0,
    corrosion_allowance_mm: float = 3.0,
) -> PipeSpec:
    """
    High-heat, high-pressure carbon steel class.

    Material: A106 Gr. B, heavy-wall schedules.
    Typical use: high-pressure steam, boiler feed water, HP process.
    Schedules: Sch 80 for DN ≤ 100; Sch 60 for DN ≥ 150.
    """
    mat = MaterialSpec.from_designation("A106", "B", corrosion_allowance_mm)
    sched_by_dn = {150: "60", 200: "60", 250: "60", 300: "60"}
    return PipeSpec(
        name="CS-HH",
        material=mat,
        design_pressure_barg=design_pressure_barg,
        design_temp_c=design_temp_c,
        permitted_dn=[25, 40, 50, 80, 100, 150, 200, 250, 300],
        default_schedule="80",
        schedule_by_dn=sched_by_dn,
        end_prep="BW",
    )


def standard_class_ss_316l(
    design_pressure_barg: float = 10.0,
    design_temp_c: float = 200.0,
    corrosion_allowance_mm: float = 0.0,
) -> PipeSpec:
    """
    Stainless steel 316L class — corrosive / hygienic service.

    Material: A312 TP316L seamless, zero corrosion allowance.
    Typical use: acids, chloride services, pharmaceutical, food.
    Schedules: Sch 40 throughout.
    """
    mat = MaterialSpec.from_designation("A312", "316L", corrosion_allowance_mm)
    return PipeSpec(
        name="SS-316L",
        material=mat,
        design_pressure_barg=design_pressure_barg,
        design_temp_c=design_temp_c,
        permitted_dn=[15, 20, 25, 40, 50, 80, 100, 150, 200],
        default_schedule="40",
        end_prep="BW",
    )


def standard_class_api_x52(
    design_pressure_barg: float = 70.0,
    design_temp_c: float = 65.0,
    corrosion_allowance_mm: float = 3.0,
) -> PipeSpec:
    """
    API 5L X52 line pipe class — transmission pipelines.

    Material: API 5L X52, high-yield for oil/gas trunk lines.
    Schedules: STD for all sizes.
    """
    mat = MaterialSpec(
        spec="API5L",
        grade="X52",
        allowable_stress_mpa=ALLOWABLE_STRESS_MPA[("API5L", "X52")],
        max_temp_c=MAX_TEMP_C["API5L"],
        corrosion_allowance_mm=corrosion_allowance_mm,
    )
    return PipeSpec(
        name="API-X52",
        material=mat,
        design_pressure_barg=design_pressure_barg,
        design_temp_c=design_temp_c,
        permitted_dn=[150, 200, 250, 300],
        default_schedule="STD",
        end_prep="BW",
    )
