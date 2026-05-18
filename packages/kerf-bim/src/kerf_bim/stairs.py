"""
kerf_bim.stairs — Full parametric stair / ramp model (T-112).

Provides multi-flight stair authoring with:
- Code-compliant rise/run validation (2R+T rule)
- Winder turn geometry
- Monolithic + assembled construction types
- Ramps with landings and handrails
- IFC export

Building code references
------------------------
- ICC IBC 2021 § 1011 — Stairways
- BS 5395-1:2010 — Stairs, ladders and walkways
- SANS 10400-M:2011 — Stairs

IFC mapping
-----------
Stair flights map to ``IfcStairFlight``; landings map to ``IfcSlab``
(type LANDING); ramps map to ``IfcRamp`` + ``IfcRampFlight``.  This
module generates the geometry-dict representation used by the existing
IFC writer and extends it with additional stair/ramp entity dicts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

__all__ = [
    # Stairs
    "StairConstruction",
    "StairFlight",
    "StairLanding",
    "WinderGroup",
    "Stair",
    "StairValidationError",
    "make_stair",
    "make_u_stair",
    "stair_to_ifc_dict",
    # Ramps
    "Ramp",
    "RampFlight",
    "RampLanding",
    "make_ramp",
    "ramp_to_ifc_dict",
    # Code check
    "check_stair_code",
    "HANDRAIL_DEFAULTS",
]


class StairValidationError(ValueError):
    """Raised when stair geometry violates constraints."""


StairConstruction = Literal["monolithic", "assembled", "precast"]
VALID_CONSTRUCTIONS = frozenset({"monolithic", "assembled", "precast"})


# ---------------------------------------------------------------------------
# Code-compliance check
# ---------------------------------------------------------------------------

HANDRAIL_DEFAULTS = {
    "height_mm": 900.0,         # IBC 2021: 34–38 in = 864–965 mm
    "diameter_mm": 38.0,
    "extension_mm": 300.0,      # Extension beyond top/bottom riser
    "material": "steel_stainless_304",
}

#: Allowed riser + tread ranges per IBC 2021 § 1011.5.2
CODE_LIMITS = {
    "riser_min_mm": 100.0,    # BS 5395: 150 mm practical min; IBC: 4 in = 101 mm
    "riser_max_mm": 178.0,    # IBC 2021: 7 in = 178 mm
    "tread_min_mm": 279.0,    # IBC 2021: 11 in = 279 mm
    "tread_max_mm": 400.0,
    "2R_plus_T_min": 550.0,   # Comfort formula — BS 5395 / practice
    "2R_plus_T_max": 700.0,
    "width_min_mm":  914.4,   # IBC 2021: 36 in = 914 mm (occupant load < 50)
}


def check_stair_code(
    riser_mm: float,
    tread_mm: float,
    width_mm: float,
) -> List[str]:
    """Return a list of code-violation strings (empty = compliant).

    Checks IBC 2021 § 1011.5 riser/tread limits and the 2R+T comfort
    formula.
    """
    errors: List[str] = []
    lim = CODE_LIMITS
    if riser_mm < lim["riser_min_mm"] or riser_mm > lim["riser_max_mm"]:
        errors.append(
            f"Riser height {riser_mm:.1f} mm outside [{lim['riser_min_mm']}, "
            f"{lim['riser_max_mm']}] mm (IBC 2021 § 1011.5.2)"
        )
    if tread_mm < lim["tread_min_mm"] or tread_mm > lim["tread_max_mm"]:
        errors.append(
            f"Tread depth {tread_mm:.1f} mm outside [{lim['tread_min_mm']}, "
            f"{lim['tread_max_mm']}] mm (IBC 2021 § 1011.5.2)"
        )
    two_r_t = 2 * riser_mm + tread_mm
    if two_r_t < lim["2R_plus_T_min"] or two_r_t > lim["2R_plus_T_max"]:
        errors.append(
            f"2R+T = {two_r_t:.1f} mm outside [{lim['2R_plus_T_min']}, "
            f"{lim['2R_plus_T_max']}] mm comfort range"
        )
    if width_mm < lim["width_min_mm"]:
        errors.append(
            f"Stair width {width_mm:.1f} mm < {lim['width_min_mm']} mm "
            f"(IBC 2021 § 1005.1)"
        )
    return errors


# ---------------------------------------------------------------------------
# Stair geometry primitives
# ---------------------------------------------------------------------------

@dataclass
class StairFlight:
    """A single straight flight of stairs.

    Parameters
    ----------
    id:
        Unique flight identifier within the stair.
    start:
        ``[x, y, z]`` bottom-front corner of first riser (mm).
    direction:
        Unit ``[dx, dy]`` run direction in plan.
    step_count:
        Number of risers in this flight.
    riser_mm:
        Riser height in mm.
    tread_mm:
        Tread depth in mm (nosing excluded).
    width_mm:
        Stair clear width in mm.
    nosing_mm:
        Nosing overhang beyond riser face (mm).
    """
    id: str
    start: List[float]          # [x, y, z] mm
    direction: List[float]      # [dx, dy]  (unit vector or will be normalised)
    step_count: int
    riser_mm: float
    tread_mm: float
    width_mm: float = 1200.0
    nosing_mm: float = 25.0

    def __post_init__(self) -> None:
        if self.step_count < 1:
            raise StairValidationError("step_count must be ≥ 1")
        if self.riser_mm <= 0 or self.tread_mm <= 0:
            raise StairValidationError("riser_mm and tread_mm must be > 0")
        if len(self.start) < 3:
            self.start = list(self.start) + [0.0] * (3 - len(self.start))
        # Normalise direction
        dx, dy = self.direction[0], self.direction[1]
        mag = math.sqrt(dx * dx + dy * dy)
        if mag < 1e-12:
            raise StairValidationError("direction vector must be non-zero")
        self.direction = [dx / mag, dy / mag]

    @property
    def total_rise(self) -> float:
        """Total rise of this flight (mm)."""
        return self.step_count * self.riser_mm

    @property
    def total_run(self) -> float:
        """Total horizontal run of this flight (mm)."""
        return self.step_count * self.tread_mm

    @property
    def end_point(self) -> List[float]:
        """Bottom-front corner of the riser *above* the last step (top of flight)."""
        dx, dy = self.direction[0], self.direction[1]
        run = self.total_run
        return [
            self.start[0] + dx * run,
            self.start[1] + dy * run,
            self.start[2] + self.total_rise,
        ]

    def code_violations(self) -> List[str]:
        return check_stair_code(self.riser_mm, self.tread_mm, self.width_mm)


@dataclass
class StairLanding:
    """An intermediate or top landing platform.

    Parameters
    ----------
    id:
        Unique landing identifier.
    position:
        ``[x, y, z]`` top-surface corner of the landing slab (mm).
    size_mm:
        ``[width, depth]`` — width = dimension perpendicular to travel,
        depth = dimension parallel to travel (mm).
    """
    id: str
    position: List[float]
    size_mm: List[float]   # [width, depth]

    def __post_init__(self) -> None:
        if len(self.position) < 3:
            self.position = list(self.position) + [0.0] * (3 - len(self.position))
        if len(self.size_mm) < 2:
            raise StairValidationError("size_mm must have at least [width, depth]")

    @property
    def area(self) -> float:
        """Landing plan area (mm²)."""
        return self.size_mm[0] * self.size_mm[1]


@dataclass
class WinderGroup:
    """A set of winder treads filling a turn between two flights.

    Parameters
    ----------
    id:
        Unique winder-group identifier.
    centre:
        ``[x, y, z]`` turning-centre point (mm).
    angle_deg:
        Total turn angle in degrees (e.g. 90 for L-stair, 180 for U-stair).
    winder_count:
        Number of winder treads in the group.
    riser_mm:
        Riser height for winder steps (same as adjacent flight).
    min_tread_mm:
        Minimum tread depth at the narrow (inner) end.
    width_mm:
        Flight width at the winder.
    """
    id: str
    centre: List[float]
    angle_deg: float
    winder_count: int
    riser_mm: float
    min_tread_mm: float = 150.0
    width_mm: float = 1200.0

    def __post_init__(self) -> None:
        if self.winder_count < 2:
            raise StairValidationError("WinderGroup must have at least 2 winder treads")
        if self.angle_deg <= 0 or self.angle_deg > 360:
            raise StairValidationError("angle_deg must be in (0°, 360°]")


# ---------------------------------------------------------------------------
# Stair (full multi-flight)
# ---------------------------------------------------------------------------

@dataclass
class Stair:
    """A complete multi-flight stair assembly.

    Parameters
    ----------
    name:
        Stair name.
    construction:
        Construction type: ``"monolithic"``, ``"assembled"``, or ``"precast"``.
    flights:
        Ordered list of :class:`StairFlight` objects.
    landings:
        Intermediate and top landing :class:`StairLanding` objects.
    winders:
        Optional :class:`WinderGroup` objects for turns without landings.
    material:
        Primary structural material id.
    has_handrail:
        Whether handrail is modelled.
    handrail_side:
        ``"left"``, ``"right"``, or ``"both"``.
    """
    name: str
    construction: StairConstruction = "monolithic"
    flights: List[StairFlight] = field(default_factory=list)
    landings: List[StairLanding] = field(default_factory=list)
    winders: List[WinderGroup] = field(default_factory=list)
    material: str = "concrete_reinforced"
    has_handrail: bool = True
    handrail_side: Literal["left", "right", "both"] = "both"

    def __post_init__(self) -> None:
        if not self.name:
            raise StairValidationError("Stair name must be non-empty")
        if self.construction not in VALID_CONSTRUCTIONS:
            raise StairValidationError(
                f"Unknown construction '{self.construction}'; "
                f"allowed: {sorted(VALID_CONSTRUCTIONS)}"
            )
        if not self.flights:
            raise StairValidationError("Stair must have at least one flight")

    @property
    def total_rise(self) -> float:
        """Total vertical rise across all flights (mm)."""
        return sum(f.total_rise for f in self.flights)

    @property
    def total_run(self) -> float:
        """Total horizontal run across all flights (mm)."""
        return sum(f.total_run for f in self.flights)

    @property
    def flight_count(self) -> int:
        return len(self.flights)

    def all_code_violations(self) -> List[str]:
        """Return all code violations across all flights."""
        violations: List[str] = []
        for flt in self.flights:
            for v in flt.code_violations():
                violations.append(f"[{flt.id}] {v}")
        return violations


# ---------------------------------------------------------------------------
# Factory: U-stair (180° multi-flight) — T-112 DoD
# ---------------------------------------------------------------------------

def make_u_stair(
    name: str = "U-Stair",
    total_rise_mm: float = 3000.0,
    riser_mm: float = 175.0,
    tread_mm: float = 280.0,
    width_mm: float = 1200.0,
    start: Optional[List[float]] = None,
    construction: StairConstruction = "monolithic",
    material: str = "concrete_reinforced",
) -> Stair:
    """Create a U-shaped (180°) two-flight stair with a mid-landing.

    The first flight goes in the +X direction; the intermediate landing
    sits at the mid-rise level; the second flight returns in the -X
    direction.

    Parameters
    ----------
    name:
        Stair name.
    total_rise_mm:
        Total vertical rise (mm).
    riser_mm:
        Target riser height (mm).
    tread_mm:
        Tread depth in mm.
    width_mm:
        Stair clear width (mm).
    start:
        ``[x, y, z]`` start point.  Defaults to ``[0, 0, 0]``.
    construction:
        Construction type.
    material:
        Structural material id.

    Returns
    -------
    :class:`Stair` — a complete U-stair with two flights and one landing.

    Raises
    ------
    StairValidationError
        On invalid geometry.
    """
    if start is None:
        start = [0.0, 0.0, 0.0]

    steps_per_flight = max(1, round(total_rise_mm / riser_mm / 2))
    actual_riser = total_rise_mm / (steps_per_flight * 2)

    sx, sy, sz = float(start[0]), float(start[1]), float(start[2])
    mid_rise = steps_per_flight * actual_riser

    # Flight 1: goes in +X
    f1_run = steps_per_flight * tread_mm
    flight1 = StairFlight(
        id="flight-1",
        start=[sx, sy, sz],
        direction=[1.0, 0.0],
        step_count=steps_per_flight,
        riser_mm=actual_riser,
        tread_mm=tread_mm,
        width_mm=width_mm,
    )

    # Landing at mid-rise level — positioned at the end of flight 1
    landing_depth = width_mm  # landing depth = stair width
    landing_x = sx + f1_run
    landing_y = sy
    landing_z = sz + mid_rise
    landing = StairLanding(
        id="landing-1",
        position=[landing_x, landing_y, landing_z],
        size_mm=[width_mm, landing_depth],
    )

    # Flight 2: returns in -X direction, offset in Y by width
    flight2 = StairFlight(
        id="flight-2",
        start=[landing_x, landing_y + landing_depth, landing_z],
        direction=[-1.0, 0.0],
        step_count=steps_per_flight,
        riser_mm=actual_riser,
        tread_mm=tread_mm,
        width_mm=width_mm,
    )

    return Stair(
        name=name,
        construction=construction,
        flights=[flight1, flight2],
        landings=[landing],
        material=material,
    )


def make_stair(
    name: str,
    flights: List[StairFlight],
    landings: Optional[List[StairLanding]] = None,
    winders: Optional[List[WinderGroup]] = None,
    construction: StairConstruction = "monolithic",
    material: str = "concrete_reinforced",
) -> Stair:
    """Create a :class:`Stair` from pre-built flight / landing objects."""
    return Stair(
        name=name,
        construction=construction,
        flights=flights,
        landings=landings or [],
        winders=winders or [],
        material=material,
    )


# ---------------------------------------------------------------------------
# IFC dict serialisation — stairs
# ---------------------------------------------------------------------------

def stair_to_ifc_dict(stair: Stair) -> dict:
    """Convert a :class:`Stair` to the IFC-exporter dict representation.

    The model dict is compatible with the ``stairs`` key in the BIM model
    dict.  The IFC writer maps each flight to an ``IfcStairFlight`` and
    each landing to an ``IfcSlab(LANDING)``.

    Returns::

        {
          "kind":        "stair",
          "name":        str,
          "construction": str,
          "material":    str,
          "total_rise_mm": float,
          "total_run_mm":  float,
          "flights": [
            {
              "id": str,
              "start": [x, y, z],
              "direction": [dx, dy],
              "step_count": int,
              "riser_mm": float,
              "tread_mm": float,
              "width_mm": float,
              "nosing_mm": float,
              "total_rise_mm": float,
              "total_run_mm": float,
              "end_point": [x, y, z],
            },
            ...
          ],
          "landings": [
            {
              "id": str,
              "position": [x, y, z],
              "size_mm": [w, d],
              "area_mm2": float,
            },
            ...
          ],
          "winders": [
            {
              "id": str,
              "centre": [x, y, z],
              "angle_deg": float,
              "winder_count": int,
              "riser_mm": float,
              "min_tread_mm": float,
              "width_mm": float,
            },
            ...
          ],
          "code_violations": [str, ...],
          "has_handrail": bool,
          "handrail_side": str,
        }
    """
    return {
        "kind": "stair",
        "name": stair.name,
        "construction": stair.construction,
        "material": stair.material,
        "total_rise_mm": stair.total_rise,
        "total_run_mm": stair.total_run,
        "flights": [
            {
                "id": f.id,
                "start": list(f.start),
                "direction": list(f.direction),
                "step_count": f.step_count,
                "riser_mm": f.riser_mm,
                "tread_mm": f.tread_mm,
                "width_mm": f.width_mm,
                "nosing_mm": f.nosing_mm,
                "total_rise_mm": f.total_rise,
                "total_run_mm": f.total_run,
                "end_point": f.end_point,
            }
            for f in stair.flights
        ],
        "landings": [
            {
                "id": la.id,
                "position": list(la.position),
                "size_mm": list(la.size_mm),
                "area_mm2": la.area,
            }
            for la in stair.landings
        ],
        "winders": [
            {
                "id": w.id,
                "centre": list(w.centre),
                "angle_deg": w.angle_deg,
                "winder_count": w.winder_count,
                "riser_mm": w.riser_mm,
                "min_tread_mm": w.min_tread_mm,
                "width_mm": w.width_mm,
            }
            for w in stair.winders
        ],
        "code_violations": stair.all_code_violations(),
        "has_handrail": stair.has_handrail,
        "handrail_side": stair.handrail_side,
    }


# ---------------------------------------------------------------------------
# Ramp
# ---------------------------------------------------------------------------

@dataclass
class RampFlight:
    """A single inclined ramp flight.

    Parameters
    ----------
    id:
        Unique flight identifier.
    start:
        ``[x, y, z]`` bottom corner (mm).
    direction:
        Unit plan direction vector ``[dx, dy]``.
    length_mm:
        Horizontal run length of the ramp (mm).
    width_mm:
        Clear ramp width (mm).
    slope_percent:
        Grade in percent (rise/run × 100).  ADA max = 8.33 % (1:12).
    """
    id: str
    start: List[float]
    direction: List[float]
    length_mm: float
    width_mm: float = 1500.0
    slope_percent: float = 8.33   # ADA max 1:12

    def __post_init__(self) -> None:
        if self.length_mm <= 0:
            raise StairValidationError("RampFlight length_mm must be > 0")
        if self.slope_percent < 0 or self.slope_percent > 33.3:
            raise StairValidationError(
                f"slope_percent {self.slope_percent} outside [0, 33.3] (max ~18°)"
            )
        dx, dy = self.direction[0], self.direction[1]
        mag = math.sqrt(dx * dx + dy * dy)
        if mag < 1e-12:
            raise StairValidationError("RampFlight direction must be non-zero")
        self.direction = [dx / mag, dy / mag]
        if len(self.start) < 3:
            self.start = list(self.start) + [0.0] * (3 - len(self.start))

    @property
    def rise_mm(self) -> float:
        """Total vertical rise of this ramp flight (mm)."""
        return self.length_mm * self.slope_percent / 100.0

    @property
    def end_point(self) -> List[float]:
        dx, dy = self.direction[0], self.direction[1]
        return [
            self.start[0] + dx * self.length_mm,
            self.start[1] + dy * self.length_mm,
            self.start[2] + self.rise_mm,
        ]


@dataclass
class RampLanding:
    """A flat landing between ramp flights (required every 9000 mm of run per ADA)."""
    id: str
    position: List[float]
    size_mm: List[float]   # [width, depth]

    def __post_init__(self) -> None:
        if len(self.position) < 3:
            self.position = list(self.position) + [0.0] * (3 - len(self.position))


@dataclass
class Ramp:
    """A complete ramp assembly with flights and landings.

    Parameters
    ----------
    name:
        Ramp name.
    flights:
        Ordered :class:`RampFlight` objects.
    landings:
        Intermediate :class:`RampLanding` objects.
    material:
        Primary structural material id.
    has_handrail:
        Whether the ramp has a handrail.
    handrail_side:
        ``"left"``, ``"right"``, or ``"both"``.
    """
    name: str
    flights: List[RampFlight] = field(default_factory=list)
    landings: List[RampLanding] = field(default_factory=list)
    material: str = "concrete_reinforced"
    has_handrail: bool = True
    handrail_side: Literal["left", "right", "both"] = "both"

    def __post_init__(self) -> None:
        if not self.name:
            raise StairValidationError("Ramp name must be non-empty")
        if not self.flights:
            raise StairValidationError("Ramp must have at least one flight")

    @property
    def total_rise(self) -> float:
        return sum(f.rise_mm for f in self.flights)

    @property
    def total_run(self) -> float:
        return sum(f.length_mm for f in self.flights)


def make_ramp(
    name: str = "Ramp",
    total_rise_mm: float = 600.0,
    slope_percent: float = 8.33,
    width_mm: float = 1500.0,
    start: Optional[List[float]] = None,
    num_flights: int = 2,
    material: str = "concrete_reinforced",
) -> Ramp:
    """Create a ramp with ``num_flights`` equal flights and intermediate landings.

    Landings are 1500 mm deep (ADA minimum = 1525 mm / 60 in).

    Parameters
    ----------
    name:
        Ramp name.
    total_rise_mm:
        Total vertical rise across all flights (mm).
    slope_percent:
        Grade in percent; must be ≤ 8.33 % for ADA compliance.
    width_mm:
        Clear ramp width (mm).
    start:
        ``[x, y, z]`` start point.
    num_flights:
        Number of ramp flights.  Must be ≥ 1.
    material:
        Structural material id.

    Returns
    -------
    :class:`Ramp`
    """
    if start is None:
        start = [0.0, 0.0, 0.0]
    if num_flights < 1:
        raise StairValidationError("num_flights must be ≥ 1")

    rise_per_flight = total_rise_mm / num_flights
    run_per_flight = rise_per_flight / (slope_percent / 100.0) if slope_percent > 0 else 3000.0
    landing_depth = max(1500.0, width_mm)

    flights: List[RampFlight] = []
    landings: List[RampLanding] = []
    cur_x, cur_y, cur_z = float(start[0]), float(start[1]), float(start[2])

    for i in range(num_flights):
        flt = RampFlight(
            id=f"flight-{i + 1}",
            start=[cur_x, cur_y, cur_z],
            direction=[1.0, 0.0],
            length_mm=run_per_flight,
            width_mm=width_mm,
            slope_percent=slope_percent,
        )
        flights.append(flt)
        cur_x += run_per_flight
        cur_z += flt.rise_mm

        # Add landing between flights (not after last flight)
        if i < num_flights - 1:
            lan = RampLanding(
                id=f"landing-{i + 1}",
                position=[cur_x, cur_y, cur_z],
                size_mm=[width_mm, landing_depth],
            )
            landings.append(lan)
            cur_x += landing_depth   # advance past landing

    return Ramp(
        name=name,
        flights=flights,
        landings=landings,
        material=material,
    )


def ramp_to_ifc_dict(ramp: Ramp) -> dict:
    """Convert a :class:`Ramp` to the IFC-exporter dict representation.

    Returns::

        {
          "kind": "ramp",
          "name": str,
          "material": str,
          "total_rise_mm": float,
          "total_run_mm": float,
          "flights": [...],
          "landings": [...],
          "has_handrail": bool,
          "handrail_side": str,
        }
    """
    return {
        "kind": "ramp",
        "name": ramp.name,
        "material": ramp.material,
        "total_rise_mm": ramp.total_rise,
        "total_run_mm": ramp.total_run,
        "flights": [
            {
                "id": f.id,
                "start": list(f.start),
                "direction": list(f.direction),
                "length_mm": f.length_mm,
                "width_mm": f.width_mm,
                "slope_percent": f.slope_percent,
                "rise_mm": f.rise_mm,
                "end_point": f.end_point,
            }
            for f in ramp.flights
        ],
        "landings": [
            {
                "id": la.id,
                "position": list(la.position),
                "size_mm": list(la.size_mm),
            }
            for la in ramp.landings
        ],
        "has_handrail": ramp.has_handrail,
        "handrail_side": ramp.handrail_side,
    }
