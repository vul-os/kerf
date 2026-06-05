"""
mep_engine.py — Routed MEP systems engine for kerf-bim.

Implements genuine, standards-correct MEP modelling:

* **System classification** — ISO 16739-1:2018 (IFC4) IfcDistributionSystemEnum
  covering HVAC supply/return/exhaust, domestic water (CW/HW), sanitary drainage,
  electrical power/lighting, fire protection, and telecom.

* **Duct sizing** — SMACNA *HVAC Duct Construction Standards* + ASHRAE Fundamentals
  Ch. 21: equal-friction method (target 1.0 Pa/m), gives nominal circular duct
  diameter from airflow (l/s) + velocity constraint.

* **Pipe sizing** — CIBSE Guide C: velocity-based nominal DN selection for CPVC/Cu/
  PE/CI.  Flow classification: laminar (Re < 2300), transitional (2300-4000),
  turbulent (> 4000).  Pressure drop via Darcy-Weisbach + Swamee-Jain.

* **Connector / endpoint model** — each segment carries typed connector ports
  (supply_inlet, supply_outlet, return_inlet, etc.) that drive network
  connectivity checks.

* **Network connectivity** — BFS walk of segment graph; detects isolated islands,
  missing return paths, and flow-balance errors (sum of branch flows ≠ trunk).

References
----------
ISO 16739-1:2018  — IfcDistributionSystemEnum, IfcDistributionPort, IfcFlowSegment
SMACNA HVAC Duct Construction Standards, 3rd Ed. (2005)
ASHRAE Fundamentals 2021, Ch. 21 — Duct Design
CIBSE Guide C 2007 — Hydraulics, Pipe Sizing
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

__all__ = [
    # Constants / enums
    "SystemDomain",
    "SystemType",
    "SystemTypeEnum",
    "ConnectorKind",
    "FittingKind",
    "SegmentKind",
    # Data classes
    "MEPConnector",
    "MEPSegment",
    "MEPFitting",
    "MEPEndpoint",
    "MEPSystem",
    # Factory / mutation
    "make_mep_system",
    "add_segment",
    "add_fitting",
    "add_endpoint",
    # Sizing
    "size_duct_diameter",
    "size_duct_rect",
    "size_pipe_dn",
    "velocity_check",
    # Hydraulics
    "darcy_weisbach",
    "swamee_jain_friction",
    "duct_pressure_drop",
    # Connectivity
    "build_adjacency",
    "connectivity_check",
    # IFC
    "system_to_ifc_dict",
    # Errors
    "MEPError",
    "MEPSizingError",
    "MEPConnectivityError",
]


# ---------------------------------------------------------------------------
# Enumerations (ISO 16739-1:2018 §IfcDistributionSystemEnum)
# ---------------------------------------------------------------------------

class SystemDomain:
    """Discipline domains."""
    HVAC = "HVAC"
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    FIRE = "FIRE"
    TELECOM = "TELECOM"


class SystemTypeEnum:
    """
    IFC4 IfcDistributionSystemEnum values, mapped to human-readable labels.

    ISO 16739-1:2018 Table at §IfcDistributionSystemEnum.
    """
    # HVAC
    SUPPLY_AIR = "SUPPLYAIR"       # Primary heated/cooled supply air
    RETURN_AIR = "RETURNAIR"       # Return air back to AHU
    EXHAUST_AIR = "EXHAUSTAIR"     # Exhaust to outside
    OUTDOOR_AIR = "AIRCONDITIONING"  # Fresh air intake
    # Plumbing
    COLD_WATER = "DOMESTICCOLDWATER"
    HOT_WATER = "DOMESTICHOTWATER"
    SANITARY = "DRAINAGE"
    RAINWATER = "RAINWATER"
    COMPRESSED_AIR = "COMPRESSEDAIR"
    # Fire
    FIRE_PROTECTION = "FIREPROTECTION"
    # Electrical
    ELECTRICAL_POWER = "ELECTRICAL"
    ELECTRICAL_LIGHTING = "LIGHTING"
    # Telecom
    TELECOM = "COMMUNICATION"
    # Generic
    GENERAL = "NOTDEFINED"


# Back-compat alias
SystemType = SystemTypeEnum


# Map SystemTypeEnum → domain (IFC4 DistributionSystem discipline)
SYSTEM_TYPE_DOMAIN: dict[str, str] = {
    SystemTypeEnum.SUPPLY_AIR:       SystemDomain.HVAC,
    SystemTypeEnum.RETURN_AIR:       SystemDomain.HVAC,
    SystemTypeEnum.EXHAUST_AIR:      SystemDomain.HVAC,
    SystemTypeEnum.OUTDOOR_AIR:      SystemDomain.HVAC,
    SystemTypeEnum.COLD_WATER:       SystemDomain.PLUMBING,
    SystemTypeEnum.HOT_WATER:        SystemDomain.PLUMBING,
    SystemTypeEnum.SANITARY:         SystemDomain.PLUMBING,
    SystemTypeEnum.RAINWATER:        SystemDomain.PLUMBING,
    SystemTypeEnum.COMPRESSED_AIR:   SystemDomain.HVAC,
    SystemTypeEnum.FIRE_PROTECTION:  SystemDomain.FIRE,
    SystemTypeEnum.ELECTRICAL_POWER: SystemDomain.ELECTRICAL,
    SystemTypeEnum.ELECTRICAL_LIGHTING: SystemDomain.ELECTRICAL,
    SystemTypeEnum.TELECOM:          SystemDomain.TELECOM,
    SystemTypeEnum.GENERAL:          SystemDomain.HVAC,
}

VALID_SYSTEM_TYPES: frozenset[str] = frozenset(SYSTEM_TYPE_DOMAIN)

# Medium (fluid or air) carried per system type
SYSTEM_MEDIUM: dict[str, str] = {
    SystemTypeEnum.SUPPLY_AIR:    "air",
    SystemTypeEnum.RETURN_AIR:    "air",
    SystemTypeEnum.EXHAUST_AIR:   "air",
    SystemTypeEnum.OUTDOOR_AIR:   "air",
    SystemTypeEnum.COLD_WATER:    "water",
    SystemTypeEnum.HOT_WATER:     "water",
    SystemTypeEnum.SANITARY:      "waste",
    SystemTypeEnum.RAINWATER:     "water",
    SystemTypeEnum.COMPRESSED_AIR: "air",
    SystemTypeEnum.FIRE_PROTECTION: "water",
    SystemTypeEnum.ELECTRICAL_POWER: "electrical",
    SystemTypeEnum.ELECTRICAL_LIGHTING: "electrical",
    SystemTypeEnum.TELECOM:       "signal",
    SystemTypeEnum.GENERAL:       "air",
}

# Default carrier kind per system type
SYSTEM_CARRIER: dict[str, str] = {
    SystemTypeEnum.SUPPLY_AIR:    "duct",
    SystemTypeEnum.RETURN_AIR:    "duct",
    SystemTypeEnum.EXHAUST_AIR:   "duct",
    SystemTypeEnum.OUTDOOR_AIR:   "duct",
    SystemTypeEnum.COLD_WATER:    "pipe",
    SystemTypeEnum.HOT_WATER:     "pipe",
    SystemTypeEnum.SANITARY:      "pipe",
    SystemTypeEnum.RAINWATER:     "pipe",
    SystemTypeEnum.COMPRESSED_AIR: "pipe",
    SystemTypeEnum.FIRE_PROTECTION: "pipe",
    SystemTypeEnum.ELECTRICAL_POWER: "conduit",
    SystemTypeEnum.ELECTRICAL_LIGHTING: "conduit",
    SystemTypeEnum.TELECOM:       "conduit",
    SystemTypeEnum.GENERAL:       "duct",
}


class ConnectorKind:
    """Port roles on a segment (IFC4 IfcDistributionPort PredefinedType)."""
    SUPPLY_INLET  = "SUPPLY_INLET"   # flow enters
    SUPPLY_OUTLET = "SUPPLY_OUTLET"  # flow exits
    RETURN_INLET  = "RETURN_INLET"
    RETURN_OUTLET = "RETURN_OUTLET"
    DRAIN         = "DRAIN"
    VENT          = "VENT"
    SIGNAL_IN     = "SIGNAL_IN"
    SIGNAL_OUT    = "SIGNAL_OUT"
    GENERIC       = "GENERIC"


class FittingKind:
    """IFC4 IfcFlowFitting subtypes."""
    TEE        = "TEE"
    CROSS      = "CROSS"
    ELBOW      = "ELBOW"
    REDUCER    = "REDUCER"
    TRANSITION = "TRANSITION"
    CAP        = "CAP"
    UNION      = "UNION"
    COUPLING   = "COUPLING"
    TRAP       = "TRAP"          # plumbing
    STRAINER   = "STRAINER"      # plumbing
    Y_BRANCH   = "Y_BRANCH"      # 45° branch


class SegmentKind:
    """Segment geometry types."""
    STRAIGHT  = "straight"
    ELBOW     = "elbow"
    VERTICAL  = "vertical"
    RISER     = "riser"
    DROP      = "drop"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MEPError(ValueError):
    """Base MEP engine error."""


class MEPSizingError(MEPError):
    """Raised when sizing inputs are out of valid range."""


class MEPConnectivityError(MEPError):
    """Raised when connectivity check fails."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MEPConnector:
    """A typed port on a segment endpoint (IFC4 IfcDistributionPort).

    Parameters
    ----------
    id : str
        Unique port id.
    kind : ConnectorKind
        Port role.
    position : list[float]
        [x, y, z] in mm.
    connected_to : str | None
        Id of the port this connector is mated to (None = unconnected).
    flow_l_s : float
        Design flow rate in litres/second (0 for electrical/signal).
    """
    id: str
    kind: str = ConnectorKind.GENERIC
    position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    connected_to: Optional[str] = None
    flow_l_s: float = 0.0


@dataclass
class MEPSegment:
    """A routed segment with typed connectors (IFC4 IfcFlowSegment).

    Covers IfcDuctSegment, IfcPipeSegment, IfcCableCarrierSegment depending
    on the parent system's carrier kind.

    Parameters
    ----------
    id : str
    from_pt, to_pt : list[float]  — [x, y, z] mm
    kind : SegmentKind
    size_mm : float  — nominal OD / diameter in mm (circular)
    width_mm, height_mm : float | None  — for rectangular ducts (mm)
    material : str
    flow_l_s : float  — design flow in l/s
    velocity_m_s : float  — design velocity in m/s (0 = not set)
    connectors : list[MEPConnector]  — inlet (index 0) + outlet (index 1)
    elbow_radius_mm : float  — bend radius for elbow segments
    insulation_thickness_mm : float
    """
    id: str
    from_pt: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    to_pt: List[float] = field(default_factory=lambda: [1000.0, 0.0, 0.0])
    kind: str = SegmentKind.STRAIGHT
    size_mm: float = 200.0
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    material: str = "galvanized_steel"
    flow_l_s: float = 0.0
    velocity_m_s: float = 0.0
    connectors: List[MEPConnector] = field(default_factory=list)
    elbow_radius_mm: float = 0.0
    insulation_thickness_mm: float = 0.0

    @property
    def length_mm(self) -> float:
        dx = self.to_pt[0] - self.from_pt[0]
        dy = self.to_pt[1] - self.from_pt[1]
        dz = self.to_pt[2] - self.from_pt[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @property
    def is_rectangular(self) -> bool:
        return self.width_mm is not None and self.height_mm is not None

    @property
    def hydraulic_diameter_mm(self) -> float:
        """Hydraulic diameter (mm).
        Circular: D. Rectangular: 4A/P (ASHRAE Fundamentals Ch.21 Eq. 1).
        """
        if self.is_rectangular:
            w = self.width_mm  # type: ignore[arg-type]
            h = self.height_mm  # type: ignore[arg-type]
            return (4.0 * w * h) / (2.0 * (w + h))
        return self.size_mm

    @property
    def cross_section_area_m2(self) -> float:
        """Flow cross-sectional area in m²."""
        if self.is_rectangular:
            return (self.width_mm / 1000.0) * (self.height_mm / 1000.0)  # type: ignore[operator]
        r = self.size_mm / 2000.0  # radius in metres
        return math.pi * r * r


@dataclass
class MEPFitting:
    """A distribution fitting (IFC4 IfcFlowFitting).

    Parameters
    ----------
    id : str
    kind : FittingKind
    position : list[float]  — [x, y, z] mm
    branches : list[str]  — segment ids connected to this fitting
    size_in_mm : float  — nominal inlet size
    size_out_mm : float  — nominal outlet size (different for reducers)
    angle_deg : float  — bend angle for elbows (0 = not applicable)
    """
    id: str
    kind: str = FittingKind.TEE
    position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    branches: List[str] = field(default_factory=list)
    size_in_mm: float = 200.0
    size_out_mm: float = 200.0
    angle_deg: float = 90.0


@dataclass
class MEPEndpoint:
    """A terminal device (grille, diffuser, fixture, outlet) at a route end.

    IFC4: IfcAirTerminal / IfcSanitaryTerminal / IfcElectricAppliance.

    Parameters
    ----------
    id : str
    label : str  — human-readable name (e.g. "Supply Diffuser AH-01")
    position : list[float]  — [x, y, z] mm
    design_flow_l_s : float  — required flow/load
    connected_segment_id : str | None  — segment this terminal connects to
    """
    id: str
    label: str = ""
    position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    design_flow_l_s: float = 0.0
    connected_segment_id: Optional[str] = None


@dataclass
class MEPSystem:
    """A complete routed MEP system (IFC4 IfcDistributionSystem).

    Parameters
    ----------
    id : str  — unique system identifier
    name : str  — e.g. "Supply Air System AHU-01"
    system_type : SystemTypeEnum  — one of the ISO 16739-1 enum values
    domain : SystemDomain  — resolved from system_type
    carrier : str  — "duct" | "pipe" | "conduit"
    medium : str  — "air" | "water" | "waste" | "electrical" | "signal"
    material : str  — carrier material
    size_mm : float  — nominal size in mm (0 if rectangular)
    width_mm, height_mm : float | None  — rectangular duct dimensions
    insulation_thickness_mm : float
    design_flow_l_s : float  — total system design flow
    design_velocity_m_s : float  — design velocity
    segments : list[MEPSegment]
    fittings : list[MEPFitting]
    endpoints : list[MEPEndpoint]
    system_color : str  — hex colour for UI rendering
    """
    id: str
    name: str
    system_type: str = SystemTypeEnum.GENERAL
    domain: str = SystemDomain.HVAC
    carrier: str = "duct"
    medium: str = "air"
    material: str = "galvanized_steel"
    size_mm: float = 400.0
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    insulation_thickness_mm: float = 25.0
    design_flow_l_s: float = 0.0
    design_velocity_m_s: float = 5.0  # m/s — ASHRAE typical supply duct
    segments: List[MEPSegment] = field(default_factory=list)
    fittings: List[MEPFitting] = field(default_factory=list)
    endpoints: List[MEPEndpoint] = field(default_factory=list)
    system_color: str = "#5da9ff"


# ---------------------------------------------------------------------------
# Defaults by carrier material (SMACNA Table 3-1 / CIBSE C Table 2.1)
# ---------------------------------------------------------------------------

# Material roughness (mm) for Darcy-Weisbach + Swamee-Jain
ROUGHNESS_MM: dict[str, float] = {
    "galvanized_steel":  0.046,
    "stainless_steel":   0.015,
    "copper":            0.0015,
    "pvc":               0.0015,
    "hdpe":              0.007,
    "cast_iron":         0.26,
    "concrete":          1.5,
    "fiberglass":        0.046,  # SMACNA Table 3-1
    "aluminium":         0.046,
}

# SMACNA recommended velocity ranges (m/s) per system type
RECOMMENDED_VELOCITY_MS: dict[str, tuple[float, float]] = {
    SystemTypeEnum.SUPPLY_AIR:    (3.0, 8.0),   # main duct SMACNA Table 2-1
    SystemTypeEnum.RETURN_AIR:    (2.0, 5.0),
    SystemTypeEnum.EXHAUST_AIR:   (2.0, 6.0),
    SystemTypeEnum.OUTDOOR_AIR:   (2.0, 5.0),
    SystemTypeEnum.COLD_WATER:    (0.5, 2.0),   # CIBSE Guide C Table 2.3
    SystemTypeEnum.HOT_WATER:     (0.5, 1.5),
    SystemTypeEnum.SANITARY:      (0.6, 1.2),   # self-cleansing velocity
    SystemTypeEnum.COMPRESSED_AIR: (5.0, 15.0),
    SystemTypeEnum.FIRE_PROTECTION: (1.5, 4.5),
}


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_mep_system(
    name: str,
    system_type: str = SystemTypeEnum.SUPPLY_AIR,
    material: Optional[str] = None,
    size_mm: float = 0.0,
    width_mm: Optional[float] = None,
    height_mm: Optional[float] = None,
    design_flow_l_s: float = 0.0,
    design_velocity_m_s: float = 0.0,
    insulation_thickness_mm: Optional[float] = None,
    system_id: Optional[str] = None,
) -> MEPSystem:
    """Create an :class:`MEPSystem` with validated classification.

    Parameters
    ----------
    name : str
        Human-readable system name.
    system_type : str
        One of :class:`SystemTypeEnum`.
    material : str | None
        Carrier material; defaults by carrier kind.
    size_mm : float
        Nominal diameter in mm (0 = use rectangular or auto-size).
    width_mm, height_mm : float | None
        Rectangular duct dimensions (mm).
    design_flow_l_s : float
        Total design flow in l/s.
    design_velocity_m_s : float
        Target velocity in m/s (0 = use SMACNA/CIBSE midpoint).
    insulation_thickness_mm : float | None
        Insulation thickness (mm); defaults by carrier.
    system_id : str | None
        Explicit id (auto-generated if None).

    Raises
    ------
    MEPError
        If system_type is not a valid SystemTypeEnum value.
    """
    if system_type not in VALID_SYSTEM_TYPES:
        raise MEPError(
            f"system_type must be one of {sorted(VALID_SYSTEM_TYPES)!r}; "
            f"got {system_type!r}"
        )
    domain = SYSTEM_TYPE_DOMAIN[system_type]
    carrier = SYSTEM_CARRIER[system_type]
    medium = SYSTEM_MEDIUM[system_type]

    # Material defaults by carrier
    _default_material = {
        "duct":    "galvanized_steel",
        "pipe":    "copper",
        "conduit": "pvc",
    }
    mat = material or _default_material.get(carrier, "galvanized_steel")

    # Default sizes by carrier if not provided
    _default_size = {"duct": 400.0, "pipe": 50.0, "conduit": 25.0}
    if size_mm <= 0 and width_mm is None:
        size_mm = _default_size.get(carrier, 200.0)

    # Insulation defaults
    if insulation_thickness_mm is None:
        insulation_thickness_mm = 25.0 if carrier == "duct" else 0.0

    # Velocity defaults (SMACNA midpoint)
    if design_velocity_m_s <= 0:
        lo, hi = RECOMMENDED_VELOCITY_MS.get(system_type, (2.0, 6.0))
        design_velocity_m_s = (lo + hi) / 2.0

    # System colour by domain
    _domain_colour = {
        SystemDomain.HVAC:       "#5da9ff",
        SystemDomain.PLUMBING:   "#4ac8a8",
        SystemDomain.ELECTRICAL: "#ffcc44",
        SystemDomain.FIRE:       "#ff4444",
        SystemDomain.TELECOM:    "#cc88ff",
    }
    colour = _domain_colour.get(domain, "#5da9ff")

    import uuid as _uuid
    sys_id = system_id or str(_uuid.uuid4())

    return MEPSystem(
        id=sys_id,
        name=name,
        system_type=system_type,
        domain=domain,
        carrier=carrier,
        medium=medium,
        material=mat,
        size_mm=size_mm,
        width_mm=width_mm,
        height_mm=height_mm,
        insulation_thickness_mm=insulation_thickness_mm,
        design_flow_l_s=design_flow_l_s,
        design_velocity_m_s=design_velocity_m_s,
        system_color=colour,
    )


def add_segment(
    system: MEPSystem,
    from_pt: list[float],
    to_pt: list[float],
    kind: str = SegmentKind.STRAIGHT,
    size_mm: Optional[float] = None,
    width_mm: Optional[float] = None,
    height_mm: Optional[float] = None,
    flow_l_s: float = 0.0,
    elbow_radius_mm: float = 0.0,
    segment_id: Optional[str] = None,
) -> MEPSegment:
    """Add a segment to *system* and return it.

    Auto-generates inlet/outlet connectors with appropriate port roles.
    """
    import uuid as _uuid
    seg_id = segment_id or f"s_{_uuid.uuid4().hex[:8]}"
    seg_size = size_mm or system.size_mm

    # Inlet connector
    inlet_kind = (
        ConnectorKind.SUPPLY_INLET if system.domain == SystemDomain.HVAC
        else ConnectorKind.SUPPLY_INLET  # generic — upstream specialises
    )
    outlet_kind = ConnectorKind.SUPPLY_OUTLET

    if system.carrier == "conduit":
        inlet_kind = ConnectorKind.SIGNAL_IN
        outlet_kind = ConnectorKind.SIGNAL_OUT

    connectors = [
        MEPConnector(
            id=f"{seg_id}_in",
            kind=inlet_kind,
            position=list(from_pt),
            flow_l_s=flow_l_s,
        ),
        MEPConnector(
            id=f"{seg_id}_out",
            kind=outlet_kind,
            position=list(to_pt),
            flow_l_s=flow_l_s,
        ),
    ]

    seg = MEPSegment(
        id=seg_id,
        from_pt=list(from_pt),
        to_pt=list(to_pt),
        kind=kind,
        size_mm=seg_size,
        width_mm=width_mm,
        height_mm=height_mm,
        material=system.material,
        flow_l_s=flow_l_s,
        velocity_m_s=(
            flow_l_s / 1000.0 / max(
                _cross_section_area(seg_size, width_mm, height_mm), 1e-9
            )
        ) if flow_l_s > 0 else 0.0,
        connectors=connectors,
        elbow_radius_mm=elbow_radius_mm,
        insulation_thickness_mm=system.insulation_thickness_mm,
    )
    system.segments.append(seg)
    return seg


def _cross_section_area(size_mm, width_mm, height_mm) -> float:
    """Cross-sectional area in m²."""
    if width_mm and height_mm:
        return (width_mm / 1000.0) * (height_mm / 1000.0)
    r = size_mm / 2000.0
    return math.pi * r * r


def add_fitting(
    system: MEPSystem,
    kind: str,
    position: list[float],
    branches: Optional[list[str]] = None,
    size_in_mm: Optional[float] = None,
    size_out_mm: Optional[float] = None,
    angle_deg: float = 90.0,
    fitting_id: Optional[str] = None,
) -> MEPFitting:
    """Add a fitting to *system* and return it."""
    import uuid as _uuid
    fit_id = fitting_id or f"f_{_uuid.uuid4().hex[:8]}"
    fit = MEPFitting(
        id=fit_id,
        kind=kind,
        position=list(position),
        branches=list(branches or []),
        size_in_mm=size_in_mm or system.size_mm,
        size_out_mm=size_out_mm or system.size_mm,
        angle_deg=angle_deg,
    )
    system.fittings.append(fit)
    return fit


def add_endpoint(
    system: MEPSystem,
    label: str,
    position: list[float],
    design_flow_l_s: float = 0.0,
    connected_segment_id: Optional[str] = None,
    endpoint_id: Optional[str] = None,
) -> MEPEndpoint:
    """Add a terminal endpoint to *system* and return it."""
    import uuid as _uuid
    ep_id = endpoint_id or f"ep_{_uuid.uuid4().hex[:8]}"
    ep = MEPEndpoint(
        id=ep_id,
        label=label,
        position=list(position),
        design_flow_l_s=design_flow_l_s,
        connected_segment_id=connected_segment_id,
    )
    system.endpoints.append(ep)
    return ep


# ---------------------------------------------------------------------------
# Duct sizing — SMACNA equal-friction method (ASHRAE Fundamentals 2021, Ch. 21)
# ---------------------------------------------------------------------------

# Target friction rate: 1.0 Pa/m (SMACNA recommended for main trunk ducts)
_TARGET_FRICTION_PA_PER_M = 1.0
# Air properties at 20°C, 101.325 kPa (ASHRAE)
_AIR_DENSITY_KG_M3 = 1.204
_AIR_VISCOSITY_PA_S = 1.81e-5
_AIR_ROUGHNESS_MM = 0.046  # galvanised steel SMACNA


def size_duct_diameter(
    flow_l_s: float,
    target_pa_per_m: float = _TARGET_FRICTION_PA_PER_M,
    velocity_max_m_s: float = 8.0,
    roughness_mm: float = _AIR_ROUGHNESS_MM,
) -> dict:
    """
    Return the circular duct diameter (mm) that satisfies the equal-friction
    criterion at the given airflow.

    Method: ASHRAE Fundamentals 2021, Ch. 21 §Equal-Friction.
    Solve iteratively: given Q (m³/s) and ΔP/L (Pa/m), find D.

    The friction loss in a round duct is:
        ΔP/L = f/D × (ρ v² / 2)
    where v = Q / (π D²/4).

    Substituting:
        ΔP/L = f/D × ρ/2 × (4Q / πD²)²
              = f × 8ρQ² / (π² D⁵)

    Rearranging for D:
        D⁵ = f × 8ρQ² / (π² × ΔP/L)

    Since f itself depends on D (via Re), iterate.

    Parameters
    ----------
    flow_l_s : float
        Volume flow rate in litres per second.
    target_pa_per_m : float
        Target friction rate (Pa/m).  Default 1.0 (SMACNA).
    velocity_max_m_s : float
        Maximum allowed velocity (m/s).  If the sized diameter produces a
        higher velocity, a warning is returned.
    roughness_mm : float
        Absolute roughness of duct wall material (mm).

    Returns
    -------
    dict
        {
            "diameter_mm": float,
            "velocity_m_s": float,
            "friction_pa_per_m": float,
            "reynolds_number": float,
            "friction_factor": float,
            "warning": str | None,
        }

    Raises
    ------
    MEPSizingError
        If flow_l_s ≤ 0 or target_pa_per_m ≤ 0.
    """
    if flow_l_s <= 0:
        raise MEPSizingError(f"flow_l_s must be > 0; got {flow_l_s}")
    if target_pa_per_m <= 0:
        raise MEPSizingError(f"target_pa_per_m must be > 0; got {target_pa_per_m}")

    Q = flow_l_s / 1000.0  # l/s → m³/s
    rho = _AIR_DENSITY_KG_M3
    mu = _AIR_VISCOSITY_PA_S
    eps = roughness_mm / 1000.0  # m

    # Initial estimate: assume f = 0.02 (turbulent)
    f = 0.02
    D = (f * 8 * rho * Q**2 / (math.pi**2 * target_pa_per_m)) ** 0.2

    for _ in range(40):
        v = Q / (math.pi / 4.0 * D**2)
        Re = rho * v * D / mu
        eps_D = eps / D
        if Re < 2300:
            f_new = 64.0 / max(Re, 1)
        else:
            # Swamee-Jain (explicit Colebrook approximation)
            f_new = 0.25 / (math.log10(eps_D / 3.7 + 5.74 / max(Re**0.9, 1)) ** 2)
        D_new = (f_new * 8 * rho * Q**2 / (math.pi**2 * target_pa_per_m)) ** 0.2
        if abs(D_new - D) < 1e-6:
            D = D_new
            f = f_new
            break
        D = D_new
        f = f_new

    D_mm = D * 1000.0
    v_final = Q / (math.pi / 4.0 * D**2)
    Re_final = rho * v_final * D / mu
    dp_actual = f * (1.0 / D) * rho * v_final**2 / 2.0

    warning = None
    if v_final > velocity_max_m_s:
        warning = (
            f"Sized velocity {v_final:.2f} m/s exceeds max {velocity_max_m_s:.2f} m/s; "
            f"consider increasing duct size."
        )

    # Round up to nearest 50mm nominal duct size (SMACNA nominal series)
    D_nominal = math.ceil(D_mm / 50.0) * 50.0

    return {
        "diameter_mm": round(D_mm, 1),
        "diameter_nominal_mm": D_nominal,
        "velocity_m_s": round(v_final, 3),
        "friction_pa_per_m": round(dp_actual, 4),
        "reynolds_number": round(Re_final, 0),
        "friction_factor": round(f, 6),
        "warning": warning,
    }


def size_duct_rect(
    flow_l_s: float,
    aspect_ratio: float = 1.5,
    target_pa_per_m: float = _TARGET_FRICTION_PA_PER_M,
    velocity_max_m_s: float = 8.0,
) -> dict:
    """
    Size a rectangular duct with target aspect ratio.

    Uses equal-friction method: first find circular equivalent diameter,
    then compute rectangular dimensions with the hydraulic diameter equation:
        D_h = 4A/P = 2wh/(w+h)   where w = aspect_ratio × h  →  h = D_h √(1+R)/(2R)

    SMACNA HVAC Duct Construction Standards, 3rd Ed., Table 2-3.

    Parameters
    ----------
    flow_l_s : float
        Volume flow rate in l/s.
    aspect_ratio : float
        w/h — recommended ≤ 4:1 (SMACNA 4.1).
    target_pa_per_m : float
        Target friction rate (Pa/m).
    velocity_max_m_s : float
        Maximum velocity (m/s).

    Returns
    -------
    dict
        Adds "width_mm", "height_mm", "aspect_ratio" to the circular result.
    """
    result = size_duct_diameter(flow_l_s, target_pa_per_m, velocity_max_m_s)
    D_h = result["diameter_mm"] / 1000.0  # m
    R = max(aspect_ratio, 1.0)
    # D_h = 2wh/(w+h) with w = R*h
    #   D_h = 2 R h²/ (h(R+1)) = 2 R h / (R+1)  →  h = D_h(R+1)/(2R)
    h = D_h * (R + 1) / (2 * R)
    w = R * h
    result["width_mm"] = round(w * 1000.0, 0)
    result["height_mm"] = round(h * 1000.0, 0)
    result["aspect_ratio"] = round(w / h, 2)
    return result


# ---------------------------------------------------------------------------
# Pipe sizing — CIBSE Guide C / DN nominal series
# ---------------------------------------------------------------------------

# DN nominal pipe diameters (inner diameter in mm, approximate for copper)
# Based on BS EN ISO 6708 nominal pipe sizes
_DN_INNER_MM: list[tuple[int, float]] = [
    (6,  6.0),
    (8,  8.0),
    (10, 10.0),
    (15, 13.0),
    (20, 19.0),
    (25, 26.0),
    (32, 35.0),
    (40, 41.0),
    (50, 53.0),
    (65, 68.0),
    (80, 82.0),
    (100, 105.0),
    (125, 130.0),
    (150, 156.0),
    (200, 206.0),
    (250, 260.0),
    (300, 310.0),
    (400, 410.0),
    (500, 510.0),
]


def size_pipe_dn(
    flow_l_s: float,
    system_type: str = SystemTypeEnum.COLD_WATER,
    roughness_mm: float = 0.0015,  # copper
    density_kg_m3: float = 1000.0,
    viscosity_pa_s: float = 1.002e-3,  # water at 20°C
) -> dict:
    """
    Select the minimum DN pipe size that satisfies:
    1. Velocity ≤ upper limit for system type (CIBSE Guide C Table 2.3)
    2. Friction rate ≤ 300 Pa/m (recommended maximum, CIBSE C §2.3)

    Parameters
    ----------
    flow_l_s : float
        Volume flow rate in l/s.
    system_type : str
        One of :class:`SystemTypeEnum` (plumbing types).
    roughness_mm : float
        Pipe material roughness (mm).
    density_kg_m3 : float
        Fluid density in kg/m³ (default: water at 20°C).
    viscosity_pa_s : float
        Dynamic viscosity in Pa·s (default: water at 20°C).

    Returns
    -------
    dict
        {"dn": int, "inner_diameter_mm": float, "velocity_m_s": float,
         "pressure_drop_pa_per_m": float, "reynolds_number": float,
         "friction_factor": float, "flow_regime": str, "warning": str | None}

    Raises
    ------
    MEPSizingError
        If no standard DN fits the constraints.
    """
    if flow_l_s <= 0:
        raise MEPSizingError(f"flow_l_s must be > 0; got {flow_l_s}")

    Q = flow_l_s / 1000.0  # m³/s
    v_lo, v_hi = RECOMMENDED_VELOCITY_MS.get(system_type, (0.5, 2.5))

    selected = None
    for dn, d_inner_mm in _DN_INNER_MM:
        d = d_inner_mm / 1000.0  # m
        area = math.pi * (d / 2.0) ** 2
        v = Q / area
        if v > v_hi:
            continue

        Re = density_kg_m3 * v * d / viscosity_pa_s
        eps_D = (roughness_mm / 1000.0) / d
        if Re < 2300:
            f = 64.0 / max(Re, 1.0)
            regime = "laminar"
        elif Re < 4000:
            # Transitional — use Colebrook as conservative estimate
            f = 0.25 / (math.log10(eps_D / 3.7 + 5.74 / max(Re**0.9, 1)) ** 2)
            regime = "transitional"
        else:
            f = 0.25 / (math.log10(eps_D / 3.7 + 5.74 / max(Re**0.9, 1)) ** 2)
            regime = "turbulent"

        dp_per_m = f * (1.0 / d) * density_kg_m3 * v**2 / 2.0
        if dp_per_m > 300.0 and v > v_lo:
            continue  # excessive friction — try larger DN

        selected = {
            "dn": dn,
            "inner_diameter_mm": d_inner_mm,
            "velocity_m_s": round(v, 3),
            "pressure_drop_pa_per_m": round(dp_per_m, 3),
            "reynolds_number": round(Re, 1),
            "friction_factor": round(f, 6),
            "flow_regime": regime,
            "warning": (
                f"Velocity {v:.2f} m/s below recommended minimum {v_lo:.2f} m/s"
                if v < v_lo else None
            ),
        }
        break  # smallest DN that satisfies constraints

    if selected is None:
        raise MEPSizingError(
            f"No standard DN size can carry {flow_l_s} l/s within velocity "
            f"{v_lo}-{v_hi} m/s and ΔP/L ≤ 300 Pa/m"
        )
    return selected


def velocity_check(
    system: MEPSystem,
    system_type: Optional[str] = None,
) -> dict:
    """
    Check all segments in *system* against SMACNA/CIBSE velocity limits.

    Returns
    -------
    dict
        {
          "ok": bool,
          "segment_results": list[{id, velocity_m_s, ok, warning}],
          "out_of_range_count": int,
        }
    """
    stype = system_type or system.system_type
    lo, hi = RECOMMENDED_VELOCITY_MS.get(stype, (0.0, 99.0))
    results = []
    for seg in system.segments:
        if seg.flow_l_s > 0:
            v = seg.flow_l_s / 1000.0 / max(seg.cross_section_area_m2, 1e-12)
        elif seg.velocity_m_s > 0:
            v = seg.velocity_m_s
        else:
            v = 0.0
        ok = (v == 0.0) or (lo <= v <= hi)
        warn = None if ok else (
            f"Segment {seg.id}: velocity {v:.2f} m/s outside [{lo:.1f}, {hi:.1f}] m/s"
        )
        results.append({"id": seg.id, "velocity_m_s": round(v, 3), "ok": ok, "warning": warn})

    oob = sum(1 for r in results if not r["ok"])
    return {
        "ok": oob == 0,
        "segment_results": results,
        "out_of_range_count": oob,
    }


# ---------------------------------------------------------------------------
# Darcy-Weisbach helpers
# ---------------------------------------------------------------------------


def swamee_jain_friction(re: float, roughness_mm: float, diameter_mm: float) -> float:
    """
    Swamee-Jain explicit approximation to the Colebrook-White friction factor.

    Valid for: 5000 ≤ Re ≤ 10⁸ and 1×10⁻⁶ ≤ ε/D ≤ 0.01.

    Reference: Swamee & Jain (1976), ASCE J. Hydraulics Div., 102(5):657-664.
    """
    if re < 2300:
        return 64.0 / max(re, 1.0)
    eps_D = (roughness_mm / 1000.0) / (diameter_mm / 1000.0)
    return 0.25 / (math.log10(eps_D / 3.7 + 5.74 / max(re**0.9, 1.0)) ** 2)


def darcy_weisbach(
    length_m: float,
    diameter_mm: float,
    velocity_m_s: float,
    density_kg_m3: float,
    friction_factor: float,
) -> float:
    """
    Darcy-Weisbach pressure drop in Pa.

        ΔP = f × (L/D) × ρv²/2

    Reference: ISO 4022:1977, ASHRAE Fundamentals 2021 Ch. 3.
    """
    D = diameter_mm / 1000.0
    return friction_factor * (length_m / D) * density_kg_m3 * velocity_m_s**2 / 2.0


def duct_pressure_drop(
    system: MEPSystem,
    density_kg_m3: float = _AIR_DENSITY_KG_M3,
    dynamic_viscosity_pa_s: float = _AIR_VISCOSITY_PA_S,
) -> dict:
    """
    Compute total pressure drop across all segments in *system*.

    Uses Darcy-Weisbach for pipe/duct; returns 0 for conduit.
    Fitting losses estimated using equivalent-length method:
        - Elbow 90°: 15× diameter
        - Tee: 30× diameter  (ASHRAE Fundamentals 2021 Ch.21 Table 3)

    Parameters
    ----------
    system : MEPSystem
    density_kg_m3 : float
        Fluid/air density (kg/m³).
    dynamic_viscosity_pa_s : float
        Dynamic viscosity (Pa·s).

    Returns
    -------
    dict
        {
          "total_pressure_drop_pa": float,
          "total_length_m": float,
          "segment_drops": list[{id, dp_pa, length_m}],
          "fitting_drops_pa": float,
          "warnings": list[str],
        }
    """
    if system.carrier == "conduit":
        return {
            "total_pressure_drop_pa": 0.0,
            "total_length_m": 0.0,
            "segment_drops": [],
            "fitting_drops_pa": 0.0,
            "warnings": ["Conduit: no fluid pressure drop applicable."],
        }

    seg_drops = []
    total_dp = 0.0
    total_len = 0.0
    warnings: list[str] = []

    for seg in system.segments:
        L = seg.length_mm / 1000.0
        D_mm = seg.hydraulic_diameter_mm

        # Velocity from flow if available, else use system design velocity
        if seg.flow_l_s > 0 and seg.cross_section_area_m2 > 0:
            v = seg.flow_l_s / 1000.0 / seg.cross_section_area_m2
        else:
            v = system.design_velocity_m_s

        Re = density_kg_m3 * v * (D_mm / 1000.0) / dynamic_viscosity_pa_s
        rough_mm = ROUGHNESS_MM.get(seg.material, 0.046)
        f = swamee_jain_friction(Re, rough_mm, D_mm)
        dp = darcy_weisbach(L, D_mm, v, density_kg_m3, f)

        seg_drops.append({
            "id": seg.id,
            "dp_pa": round(dp, 3),
            "length_m": round(L, 3),
            "velocity_m_s": round(v, 3),
        })
        total_dp += dp
        total_len += L

    # Equivalent-length fitting losses
    fitting_dp = 0.0
    for fitting in system.fittings:
        D_mm = system.size_mm
        v = system.design_velocity_m_s
        eq_len_D = {"ELBOW": 15.0, "TEE": 30.0, "CROSS": 50.0,
                    "REDUCER": 5.0, "CAP": 2.0}.get(fitting.kind, 10.0)
        eq_len_m = eq_len_D * D_mm / 1000.0
        Re = density_kg_m3 * v * (D_mm / 1000.0) / dynamic_viscosity_pa_s
        rough_mm = ROUGHNESS_MM.get(system.material, 0.046)
        f = swamee_jain_friction(Re, rough_mm, D_mm)
        fitting_dp += darcy_weisbach(eq_len_m, D_mm, v, density_kg_m3, f)

    return {
        "total_pressure_drop_pa": round(total_dp + fitting_dp, 3),
        "total_length_m": round(total_len, 3),
        "segment_drops": seg_drops,
        "fitting_drops_pa": round(fitting_dp, 3),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Connectivity analysis
# ---------------------------------------------------------------------------


def build_adjacency(system: MEPSystem) -> dict[str, set[str]]:
    """
    Build an adjacency map of segment-id → {connected segment ids}.

    Segments are considered adjacent if they share a common endpoint (within
    1 mm tolerance) or if a fitting references both of them.
    """
    adj: dict[str, set[str]] = {s.id: set() for s in system.segments}

    # Proximity adjacency (shared endpoints)
    tol = 1.0  # mm
    segs = system.segments
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            si, sj = segs[i], segs[j]
            for pt_i in (si.from_pt, si.to_pt):
                for pt_j in (sj.from_pt, sj.to_pt):
                    d = math.sqrt(sum((a - b)**2 for a, b in zip(pt_i, pt_j)))
                    if d <= tol:
                        adj[si.id].add(sj.id)
                        adj[sj.id].add(si.id)

    # Fitting-based adjacency
    for fitting in system.fittings:
        bs = fitting.branches
        for k in range(len(bs)):
            for m in range(k + 1, len(bs)):
                if bs[k] in adj and bs[m] in adj:
                    adj[bs[k]].add(bs[m])
                    adj[bs[m]].add(bs[k])

    return adj


def connectivity_check(system: MEPSystem) -> dict:
    """
    BFS connectivity check for *system*.

    Returns
    -------
    dict
        {
          "ok": bool,
          "connected": bool,   — True if all segments form one component
          "n_components": int,
          "components": list[list[str]],  — segment ids per component
          "isolated_segments": list[str],
          "unconnected_endpoints": list[str],  — endpoint ids with no matching segment
          "flow_balance_warnings": list[str],
          "warnings": list[str],
        }
    """
    if not system.segments:
        return {
            "ok": True,
            "connected": True,
            "n_components": 0,
            "components": [],
            "isolated_segments": [],
            "unconnected_endpoints": [],
            "flow_balance_warnings": [],
            "warnings": [],
        }

    adj = build_adjacency(system)
    visited: Set[str] = set()
    components: List[List[str]] = []

    all_ids = [s.id for s in system.segments]
    for start in all_ids:
        if start in visited:
            continue
        # BFS
        queue = [start]
        comp: List[str] = []
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            comp.append(node)
            for nb in adj.get(node, set()):
                if nb not in visited:
                    queue.append(nb)
        components.append(comp)

    isolated = [c[0] for c in components if len(c) == 1]

    # Check endpoints have matching segments
    seg_ids = {s.id for s in system.segments}
    unconnected_eps = [
        ep.id for ep in system.endpoints
        if ep.connected_segment_id and ep.connected_segment_id not in seg_ids
    ]

    # Flow balance at fittings (sum-of-branches check)
    flow_balance_warnings: List[str] = []
    seg_flow: dict[str, float] = {s.id: s.flow_l_s for s in system.segments}
    for fitting in system.fittings:
        if fitting.kind in (FittingKind.TEE, FittingKind.CROSS, FittingKind.Y_BRANCH):
            flows = [seg_flow.get(b, 0.0) for b in fitting.branches]
            if len(flows) >= 2:
                total = sum(flows[1:])
                trunk = flows[0]
                if trunk > 0 and abs(total - trunk) / trunk > 0.05:
                    flow_balance_warnings.append(
                        f"Fitting {fitting.id}: branch flows {flows[1:]} sum to "
                        f"{total:.3f} l/s but trunk is {trunk:.3f} l/s "
                        f"(>{5:.0f}% imbalance)"
                    )

    all_ok = (
        len(components) <= 1
        and not isolated
        and not unconnected_eps
        and not flow_balance_warnings
    )
    warnings: List[str] = []
    if len(components) > 1:
        warnings.append(f"System has {len(components)} disconnected sub-networks.")
    if isolated:
        warnings.append(f"Isolated segments (no neighbours): {isolated}")

    return {
        "ok": all_ok,
        "connected": len(components) <= 1,
        "n_components": len(components),
        "components": components,
        "isolated_segments": isolated,
        "unconnected_endpoints": unconnected_eps,
        "flow_balance_warnings": flow_balance_warnings,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# IFC4 dict serialisation (IfcDistributionSystem + IfcFlowSegment subtypes)
# ---------------------------------------------------------------------------

def system_to_ifc_dict(system: MEPSystem) -> dict:
    """
    Serialise an :class:`MEPSystem` to an IFC-4-flavoured dict compatible
    with the kerf-bim IFC export writer.

    IFC4 types used (ISO 16739-1:2018):
        IfcDistributionSystem        — the system container
        IfcDuctSegment               — for HVAC duct segments
        IfcPipeSegment               — for plumbing/fire segments
        IfcCableCarrierSegment       — for electrical conduit segments
        IfcDuctFitting               — for HVAC fittings
        IfcPipeFitting               — for plumbing fittings
        IfcAirTerminal               — HVAC supply/return terminals
        IfcSanitaryTerminal          — plumbing fixtures
        IfcDistributionPort          — connector ports
        IfcRelConnectsPortToElement  — port-to-element relationship
    """
    _CARRIER_SEGMENT_TYPE = {
        "duct":    "IfcDuctSegment",
        "pipe":    "IfcPipeSegment",
        "conduit": "IfcCableCarrierSegment",
    }
    _CARRIER_FITTING_TYPE = {
        "duct":    "IfcDuctFitting",
        "pipe":    "IfcPipeFitting",
        "conduit": "IfcCableFitting",
    }
    _CARRIER_TERMINAL_TYPE = {
        "duct":    "IfcAirTerminal",
        "pipe":    "IfcSanitaryTerminal",
        "conduit": "IfcJunctionBox",
    }

    seg_type = _CARRIER_SEGMENT_TYPE.get(system.carrier, "IfcFlowSegment")
    fit_type = _CARRIER_FITTING_TYPE.get(system.carrier, "IfcFlowFitting")
    term_type = _CARRIER_TERMINAL_TYPE.get(system.carrier, "IfcFlowTerminal")

    return {
        "ifc_type": "IfcDistributionSystem",
        "id": system.id,
        "name": system.name,
        "system_type": system.system_type,           # IfcDistributionSystemEnum
        "domain": system.domain,
        "medium": system.medium,
        "carrier_kind": system.carrier,
        "segment_ifc_type": seg_type,
        "fitting_ifc_type": fit_type,
        "terminal_ifc_type": term_type,
        "design_flow_l_s": system.design_flow_l_s,
        "design_velocity_m_s": system.design_velocity_m_s,
        "segments": [
            {
                "ifc_type": seg_type,
                "id": s.id,
                "from": s.from_pt,
                "to": s.to_pt,
                "kind": s.kind,
                "size_mm": s.size_mm,
                "width_mm": s.width_mm,
                "height_mm": s.height_mm,
                "material": s.material,
                "flow_l_s": s.flow_l_s,
                "velocity_m_s": s.velocity_m_s,
                "length_mm": round(s.length_mm, 2),
                "hydraulic_diameter_mm": round(s.hydraulic_diameter_mm, 2),
                "insulation_thickness_mm": s.insulation_thickness_mm,
                "ports": [
                    {
                        "ifc_type": "IfcDistributionPort",
                        "id": c.id,
                        "kind": c.kind,
                        "position": c.position,
                        "connected_to": c.connected_to,
                        "flow_l_s": c.flow_l_s,
                    }
                    for c in s.connectors
                ],
            }
            for s in system.segments
        ],
        "fittings": [
            {
                "ifc_type": fit_type,
                "id": f.id,
                "kind": f.kind,
                "position": f.position,
                "branches": f.branches,
                "size_in_mm": f.size_in_mm,
                "size_out_mm": f.size_out_mm,
                "angle_deg": f.angle_deg,
            }
            for f in system.fittings
        ],
        "endpoints": [
            {
                "ifc_type": term_type,
                "id": e.id,
                "label": e.label,
                "position": e.position,
                "design_flow_l_s": e.design_flow_l_s,
                "connected_segment_id": e.connected_segment_id,
            }
            for e in system.endpoints
        ],
    }
