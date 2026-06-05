"""
mep_families.py — Parametric MEP family definitions for kerf-bim.

Provides parametric family definitions for MEP terminal and distribution
equipment, with IFC4 connector port mapping and formula-driven geometry.

Family categories and IFC4 mapping:
------------------------------------
  air_diffuser       → IfcAirTerminal (PredefinedType=DIFFUSER)
  air_grille         → IfcAirTerminal (PredefinedType=GRILLE)
  duct_fitting_tee   → IfcDuctFitting (PredefinedType=TEE)
  duct_fitting_elbow → IfcDuctFitting (PredefinedType=BEND)
  duct_fitting_reducer → IfcDuctFitting (PredefinedType=TRANSITION)
  pipe_valve         → IfcValve (PredefinedType=GATE)
  pipe_pump          → IfcPump (PredefinedType=CIRCULATOR)
  luminaire          → IfcLightFixture (PredefinedType=POINTSOURCE)
  socket_outlet      → IfcElectricDistributionBoard (PredefinedType=NOTDEFINED)
  junction_box       → IfcJunctionBox (PredefinedType=POWER)

All families follow the three-layer pyramid:
  FamilyDefinition → FamilyType → FamilyInstance

Formula-driven parameters are evaluated using the ``kerf_bim.family.evaluator``.

References
----------
ISO 16739-1:2018 — IfcAirTerminal, IfcDuctFitting, IfcValve, IfcPump,
  IfcLightFixture, IfcDistributionPort, IfcRelConnectsPortToElement.
ASHRAE Standard 62.1-2022 — Ventilation for Acceptable Indoor Air Quality
  (minimum airflow requirements by terminal type).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from kerf_bim.family_editor import (
    FamilyDef,
    FamilyFormula,
    FamilyParameter,
    FamilyEditorError,
    instantiate_family,
    validate_family,
)

__all__ = [
    # Family definitions
    "AIR_DIFFUSER_FAMILY",
    "AIR_GRILLE_FAMILY",
    "DUCT_TEE_FAMILY",
    "DUCT_ELBOW_FAMILY",
    "DUCT_REDUCER_FAMILY",
    "PIPE_VALVE_FAMILY",
    "PIPE_PUMP_FAMILY",
    "LUMINAIRE_FAMILY",
    "SOCKET_OUTLET_FAMILY",
    "JUNCTION_BOX_FAMILY",
    "ALL_MEP_FAMILIES",
    # IFC mapping helpers
    "MEPFamilyIFCMap",
    "ifc_type_for_family",
    "ifc_predefined_type_for_family",
    "connector_ports_for_family",
    # Connector port descriptor
    "MEPPortDescriptor",
    "ConnectorPortKind",
    # Errors
    "MEPFamilyError",
]


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class MEPFamilyError(FamilyEditorError):
    """Raised for MEP-family-specific errors."""


# ---------------------------------------------------------------------------
# Connector port kind (aligns with mep_engine.ConnectorKind)
# ---------------------------------------------------------------------------

class ConnectorPortKind:
    """IFC4 IfcDistributionPort PredefinedType values for MEP terminals."""
    SOURCEANDSINK = "SOURCEANDSINK"  # bidirectional (e.g. VAV box)
    SOURCE        = "SOURCE"         # output only (e.g. supply diffuser)
    SINK          = "SINK"           # input only (e.g. exhaust grille)
    NOTDEFINED    = "NOTDEFINED"


@dataclass
class MEPPortDescriptor:
    """Descriptor for one connector port on an MEP family instance.

    Maps to IFC4 ``IfcDistributionPort`` + ``IfcRelConnectsPortToElement``.

    Parameters
    ----------
    name : str
        Port name (e.g. "Supply In", "Return Out").
    kind : ConnectorPortKind
        IFC4 port direction.
    medium : str
        Medium flowing through: "air" | "water" | "electrical" | "signal".
    offset_xyz : list[float]
        Position offset from family origin in mm [x, y, z].
    size_mm : float
        Nominal duct/pipe size at this port (mm).
    """
    name: str
    kind: str = ConnectorPortKind.SOURCEANDSINK
    medium: str = "air"
    offset_xyz: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    size_mm: float = 200.0


# ---------------------------------------------------------------------------
# IFC mapping table
# ---------------------------------------------------------------------------

@dataclass
class MEPFamilyIFCMap:
    """IFC4 entity type + predefined type for an MEP family.

    IFC4 §IfcAirTerminal: DIFFUSER | GRILLE | LOUVRE | REGISTER | SIDEWALLDIFFUSER | SUPPLYGRILLE
    IFC4 §IfcDuctFitting: BEND | CONNECTOR | ENTRY | EXIT | JUNCTION | OBSTRUCTION | TRANSITION
    IFC4 §IfcValve: AIRRELEASE | ANTIVACUUM | CHANGEOVER | CHECK | COMMISSIONING | DIVERTING |
                    DRAWOFFCOCK | DOUBLECHECK | DOUBLEREGULATINGLECKOFFCOCK | FLUSHING |
                    FLOWREGULATING | GASCOCK | GASTAP | GLOBE | ISOLATING | MIXING | PRESSUREREDUCING |
                    PRESSURERELIEF | REGULATINGCOCK | SAFETYCUTOFF | STEAMTRAP | STOPCOCK
    IFC4 §IfcPump: CIRCULATOR | ENDSUCTION | SPLITCASE | SUBMERSIBLEPUMP | SUMPPUMP | VERTICALINLINE | VERTICALTURBINE
    IFC4 §IfcLightFixture: POINTSOURCE | DIRECTIONSOURCE
    """
    ifc_entity: str        # e.g. "IfcAirTerminal"
    predefined_type: str   # e.g. "DIFFUSER"
    ports: List[MEPPortDescriptor] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parametric MEP family definitions
# ---------------------------------------------------------------------------

AIR_DIFFUSER_FAMILY = FamilyDef(
    name="Supply Air Diffuser",
    category="fixture",
    description=(
        "Ceiling supply air diffuser. Formula-driven neck size and throw radius. "
        "IFC4 IfcAirTerminal DIFFUSER. "
        "ASHRAE 62.1-2022 §6.2 — minimum supply rate 0.15 l/s/m²."
    ),
    parameters=[
        FamilyParameter("face_size_mm",  "number", default=600.0, min=150.0, max=1200.0, units="mm",
                        description="Face plate nominal dimension (square, mm)"),
        FamilyParameter("neck_size_mm",  "number", default=200.0, min=100.0, max=500.0,  units="mm",
                        description="Supply neck duct connection diameter (mm)"),
        FamilyParameter("design_flow_ls","number", default=20.0,  min=1.0,   max=500.0,  units="l/s",
                        description="Design supply airflow in l/s"),
        FamilyParameter("throw_m",       "number", default=2.5,   min=0.5,   max=8.0,    units="m",
                        description="Nominal throw distance at terminal velocity 0.25 m/s"),
        FamilyParameter("pressure_drop_pa","number", default=12.0, min=1.0,  max=100.0,  units="Pa",
                        description="Pressure drop at design flow (Pa)"),
    ],
    formulas=[
        FamilyFormula("neck_radius_mm", "neck_size_mm / 2.0"),
        FamilyFormula("face_area_m2",   "face_size_mm**2 / 1e6"),
        FamilyFormula("supply_velocity_ms", "design_flow_ls / 1000.0 / max(face_area_m2, 0.001)"),
    ],
    geometry_script="""
# Supply air diffuser geometry summary (no CAD kernel required)
result = {
    "family": "Supply Air Diffuser",
    "category": "fixture",
    "ifc_type": "IfcAirTerminal",
    "ifc_predefined_type": "DIFFUSER",
    "face_size_mm": face_size_mm,
    "neck_size_mm": neck_size_mm,
    "design_flow_ls": design_flow_ls,
    "neck_radius_mm": neck_radius_mm,
    "face_area_m2": face_area_m2,
    "supply_velocity_ms": round(supply_velocity_ms, 3),
    "throw_m": throw_m,
    "pressure_drop_pa": pressure_drop_pa,
    "ports": [
        {"name": "Supply In", "kind": "SINK", "medium": "air",
         "size_mm": neck_size_mm, "offset_xyz": [0.0, 0.0, 0.0]},
    ],
}
""",
)

AIR_GRILLE_FAMILY = FamilyDef(
    name="Return Air Grille",
    category="fixture",
    description=(
        "Ceiling return air grille with opposed blade damper. "
        "IFC4 IfcAirTerminal GRILLE."
    ),
    parameters=[
        FamilyParameter("face_width_mm",  "number", default=600.0, min=150.0, max=1200.0, units="mm"),
        FamilyParameter("face_height_mm", "number", default=300.0, min=100.0, max=600.0,  units="mm"),
        FamilyParameter("neck_size_mm",   "number", default=200.0, min=100.0, max=500.0,  units="mm"),
        FamilyParameter("design_flow_ls", "number", default=15.0,  min=1.0,   max=300.0,  units="l/s"),
        FamilyParameter("has_damper",     "boolean", default=True,
                        description="True if opposed blade damper installed"),
    ],
    formulas=[
        FamilyFormula("face_area_m2",   "face_width_mm * face_height_mm / 1e6"),
        FamilyFormula("face_velocity_ms", "design_flow_ls / 1000.0 / max(face_area_m2, 0.001)"),
    ],
    geometry_script="""
result = {
    "family": "Return Air Grille",
    "category": "fixture",
    "ifc_type": "IfcAirTerminal",
    "ifc_predefined_type": "GRILLE",
    "face_width_mm": face_width_mm,
    "face_height_mm": face_height_mm,
    "design_flow_ls": design_flow_ls,
    "face_area_m2": face_area_m2,
    "face_velocity_ms": round(face_velocity_ms, 3),
    "has_damper": has_damper,
    "ports": [
        {"name": "Return Out", "kind": "SOURCE", "medium": "air",
         "size_mm": neck_size_mm, "offset_xyz": [0.0, 0.0, 0.0]},
    ],
}
""",
)

DUCT_TEE_FAMILY = FamilyDef(
    name="Duct Tee",
    category="fixture",
    description=(
        "Equal or reducing duct tee fitting. "
        "IFC4 IfcDuctFitting JUNCTION. "
        "Flow balance: Q_trunk = Q_branch1 + Q_branch2."
    ),
    parameters=[
        FamilyParameter("trunk_size_mm",   "number", default=400.0, min=50.0, max=2000.0, units="mm"),
        FamilyParameter("branch1_size_mm", "number", default=300.0, min=50.0, max=2000.0, units="mm"),
        FamilyParameter("branch2_size_mm", "number", default=300.0, min=50.0, max=2000.0, units="mm"),
        FamilyParameter("trunk_flow_ls",   "number", default=100.0, min=0.0,  max=10000.0, units="l/s"),
        FamilyParameter("branch_split",    "number", default=0.5,   min=0.01, max=0.99,
                        description="Fraction of flow to branch1 (remainder to branch2)"),
    ],
    formulas=[
        FamilyFormula("branch1_flow_ls", "trunk_flow_ls * branch_split"),
        FamilyFormula("branch2_flow_ls", "trunk_flow_ls * (1.0 - branch_split)"),
    ],
    geometry_script="""
result = {
    "family": "Duct Tee",
    "category": "fixture",
    "ifc_type": "IfcDuctFitting",
    "ifc_predefined_type": "JUNCTION",
    "trunk_size_mm": trunk_size_mm,
    "branch1_size_mm": branch1_size_mm,
    "branch2_size_mm": branch2_size_mm,
    "trunk_flow_ls": trunk_flow_ls,
    "branch1_flow_ls": branch1_flow_ls,
    "branch2_flow_ls": branch2_flow_ls,
    "ports": [
        {"name": "Trunk", "kind": "SINK", "medium": "air",
         "size_mm": trunk_size_mm, "offset_xyz": [0.0, 0.0, 0.0]},
        {"name": "Branch 1", "kind": "SOURCE", "medium": "air",
         "size_mm": branch1_size_mm, "offset_xyz": [0.0, 200.0, 0.0]},
        {"name": "Branch 2", "kind": "SOURCE", "medium": "air",
         "size_mm": branch2_size_mm, "offset_xyz": [0.0, -200.0, 0.0]},
    ],
}
""",
)

DUCT_ELBOW_FAMILY = FamilyDef(
    name="Duct Elbow",
    category="fixture",
    description=(
        "Circular or rectangular duct elbow. "
        "IFC4 IfcDuctFitting BEND. "
        "SMACNA loss coefficient at 90°: C = 0.11 (smooth) – 0.27 (mitre)."
    ),
    parameters=[
        FamilyParameter("size_mm",       "number", default=400.0, min=50.0, max=2000.0, units="mm"),
        FamilyParameter("angle_deg",     "number", default=90.0,  min=15.0, max=180.0,  units="deg"),
        FamilyParameter("radius_mm",     "number", default=600.0, min=50.0, max=3000.0, units="mm",
                        description="Centreline bend radius (SMACNA r/D ≥ 1.5 recommended)"),
        FamilyParameter("smacna_r_over_d", "number", default=1.5, min=0.5, max=5.0,
                        description="Centreline radius-to-diameter ratio"),
    ],
    formulas=[
        FamilyFormula("r_over_d", "radius_mm / size_mm"),
        # SMACNA local loss coefficient (simplified Idelchik, Fig. 6-14):
        # C = 0.0447 × θ^0.5 / (r/D)^1.22  for θ in degrees
        FamilyFormula("loss_coeff_c",
                      "0.0447 * angle_deg**0.5 / max(r_over_d**1.22, 0.001)"),
    ],
    geometry_script="""
result = {
    "family": "Duct Elbow",
    "category": "fixture",
    "ifc_type": "IfcDuctFitting",
    "ifc_predefined_type": "BEND",
    "size_mm": size_mm,
    "angle_deg": angle_deg,
    "radius_mm": radius_mm,
    "r_over_d": round(r_over_d, 3),
    "smacna_loss_coefficient": round(loss_coeff_c, 4),
    "ports": [
        {"name": "Inlet", "kind": "SINK", "medium": "air",
         "size_mm": size_mm, "offset_xyz": [0.0, 0.0, 0.0]},
        {"name": "Outlet", "kind": "SOURCE", "medium": "air",
         "size_mm": size_mm, "offset_xyz": [radius_mm, radius_mm, 0.0]},
    ],
}
""",
)

DUCT_REDUCER_FAMILY = FamilyDef(
    name="Duct Reducer",
    category="fixture",
    description=(
        "Concentric duct reducer / increaser. "
        "IFC4 IfcDuctFitting TRANSITION. "
        "SMACNA expansion loss: C = k(1 - (A1/A2))² where k≈1 for sudden."
    ),
    parameters=[
        FamilyParameter("inlet_size_mm",   "number", default=400.0, min=50.0, max=2000.0, units="mm"),
        FamilyParameter("outlet_size_mm",  "number", default=250.0, min=50.0, max=2000.0, units="mm"),
        FamilyParameter("taper_length_mm", "number", default=300.0, min=50.0, max=3000.0, units="mm",
                        description="Length of the tapered section (mm)"),
    ],
    formulas=[
        FamilyFormula("inlet_area_m2",  "3.14159 * (inlet_size_mm/2000.0)**2"),
        FamilyFormula("outlet_area_m2", "3.14159 * (outlet_size_mm/2000.0)**2"),
        FamilyFormula("area_ratio",     "outlet_area_m2 / max(inlet_area_m2, 0.001)"),
        # Borda-Carnot coefficient for sudden contraction (SMACNA)
        FamilyFormula("loss_coeff",     "0.5 * (1 - area_ratio)**2"),
    ],
    geometry_script="""
result = {
    "family": "Duct Reducer",
    "category": "fixture",
    "ifc_type": "IfcDuctFitting",
    "ifc_predefined_type": "TRANSITION",
    "inlet_size_mm": inlet_size_mm,
    "outlet_size_mm": outlet_size_mm,
    "taper_length_mm": taper_length_mm,
    "area_ratio": round(area_ratio, 4),
    "loss_coefficient": round(loss_coeff, 4),
    "ports": [
        {"name": "Inlet", "kind": "SINK", "medium": "air",
         "size_mm": inlet_size_mm, "offset_xyz": [0.0, 0.0, 0.0]},
        {"name": "Outlet", "kind": "SOURCE", "medium": "air",
         "size_mm": outlet_size_mm, "offset_xyz": [taper_length_mm, 0.0, 0.0]},
    ],
}
""",
)

PIPE_VALVE_FAMILY = FamilyDef(
    name="Gate Valve",
    category="fixture",
    description=(
        "Full-bore gate valve for isolating water distribution. "
        "IFC4 IfcValve ISOLATING. "
        "Fully open Kv: ≈ 0.2 (DIN EN 1074-1, BS EN 1074-1)."
    ),
    parameters=[
        FamilyParameter("dn_mm",        "number", default=50.0,  min=15.0, max=600.0, units="mm",
                        description="Nominal pipe diameter DN (mm)"),
        FamilyParameter("face_to_face_mm", "number", default=178.0, min=50.0, max=1000.0, units="mm",
                        description="Face-to-face dimension per EN 558 series 14"),
        FamilyParameter("kv_open",      "number", default=0.2,   min=0.01, max=2.0,
                        description="Pressure loss coefficient Kv at fully open"),
        FamilyParameter("is_open",      "boolean", default=True,
                        description="True = fully open position"),
    ],
    formulas=[
        FamilyFormula("area_m2",       "3.14159 * (dn_mm/2000.0)**2"),
        # Pressure drop at 1 m/s: ΔP = Kv × ρv²/2 with ρ=1000 kg/m³
        FamilyFormula("dp_at_1ms_pa",  "kv_open * 1000.0 * 1.0**2 / 2.0"),
    ],
    geometry_script="""
result = {
    "family": "Gate Valve",
    "category": "fixture",
    "ifc_type": "IfcValve",
    "ifc_predefined_type": "ISOLATING",
    "dn_mm": dn_mm,
    "face_to_face_mm": face_to_face_mm,
    "kv_open": kv_open,
    "is_open": is_open,
    "dp_at_1ms_pa": round(dp_at_1ms_pa, 2),
    "ports": [
        {"name": "Inlet", "kind": "SINK", "medium": "water",
         "size_mm": dn_mm, "offset_xyz": [0.0, 0.0, 0.0]},
        {"name": "Outlet", "kind": "SOURCE", "medium": "water",
         "size_mm": dn_mm, "offset_xyz": [face_to_face_mm, 0.0, 0.0]},
    ],
}
""",
)

PIPE_PUMP_FAMILY = FamilyDef(
    name="Circulator Pump",
    category="fixture",
    description=(
        "In-line circulator pump for HVAC / domestic hot water circuits. "
        "IFC4 IfcPump CIRCULATOR. "
        "Efficiency per EU ErP Directive 2009/125/EC."
    ),
    parameters=[
        FamilyParameter("dn_mm",          "number", default=50.0,  min=15.0, max=300.0,  units="mm"),
        FamilyParameter("design_flow_ls",  "number", default=2.0,   min=0.01, max=1000.0, units="l/s"),
        FamilyParameter("design_head_pa",  "number", default=30000.0, min=1000.0, max=1e6, units="Pa",
                        description="Design differential pressure (Pa)"),
        FamilyParameter("motor_power_w",   "number", default=250.0, min=10.0, max=50000.0, units="W"),
        FamilyParameter("face_to_face_mm", "number", default=180.0, min=80.0, max=1000.0, units="mm"),
    ],
    formulas=[
        FamilyFormula("flow_m3_s",     "design_flow_ls / 1000.0"),
        FamilyFormula("hydraulic_pw",  "design_head_pa * flow_m3_s"),
        # η_hydraulic = P_hydraulic / P_motor
        FamilyFormula("efficiency",    "min(hydraulic_pw / max(motor_power_w, 1.0), 1.0)"),
    ],
    geometry_script="""
result = {
    "family": "Circulator Pump",
    "category": "fixture",
    "ifc_type": "IfcPump",
    "ifc_predefined_type": "CIRCULATOR",
    "dn_mm": dn_mm,
    "design_flow_ls": design_flow_ls,
    "design_head_pa": design_head_pa,
    "motor_power_w": motor_power_w,
    "hydraulic_power_w": round(hydraulic_pw, 1),
    "efficiency_pct": round(efficiency * 100, 1),
    "ports": [
        {"name": "Suction", "kind": "SINK", "medium": "water",
         "size_mm": dn_mm, "offset_xyz": [0.0, 0.0, 0.0]},
        {"name": "Discharge", "kind": "SOURCE", "medium": "water",
         "size_mm": dn_mm, "offset_xyz": [face_to_face_mm, 0.0, 0.0]},
    ],
}
""",
)

LUMINAIRE_FAMILY = FamilyDef(
    name="Recessed LED Luminaire",
    category="fixture",
    description=(
        "Recessed ceiling LED luminaire with fixed or adjustable flux. "
        "IFC4 IfcLightFixture POINTSOURCE. "
        "CIE 69:1987 / IES LM-79-19."
    ),
    parameters=[
        FamilyParameter("length_mm",  "number", default=600.0,  min=100.0, max=2400.0, units="mm"),
        FamilyParameter("width_mm",   "number", default=600.0,  min=100.0, max=1200.0, units="mm"),
        FamilyParameter("wattage_w",  "number", default=36.0,   min=5.0,   max=500.0,  units="W"),
        FamilyParameter("lumens",     "number", default=4000.0, min=100.0, max=100000.0, units="lm"),
        FamilyParameter("cct_k",      "number", default=4000.0, min=2700.0, max=6500.0, units="K",
                        description="Correlated colour temperature (K)"),
        FamilyParameter("cri",        "number", default=80.0,   min=70.0,  max=100.0,
                        description="Colour rendering index (CIE Ra)"),
    ],
    formulas=[
        FamilyFormula("efficacy_lm_w", "lumens / max(wattage_w, 0.001)"),
        FamilyFormula("face_area_m2",  "length_mm * width_mm / 1e6"),
    ],
    geometry_script="""
result = {
    "family": "Recessed LED Luminaire",
    "category": "fixture",
    "ifc_type": "IfcLightFixture",
    "ifc_predefined_type": "POINTSOURCE",
    "length_mm": length_mm,
    "width_mm": width_mm,
    "wattage_w": wattage_w,
    "lumens": lumens,
    "cct_k": cct_k,
    "cri": cri,
    "efficacy_lm_w": round(efficacy_lm_w, 1),
    "face_area_m2": face_area_m2,
    "ports": [
        {"name": "Power In", "kind": "SINK", "medium": "electrical",
         "size_mm": 0, "offset_xyz": [0.0, 0.0, 0.0]},
    ],
}
""",
)

SOCKET_OUTLET_FAMILY = FamilyDef(
    name="Single Socket Outlet",
    category="fixture",
    description=(
        "13A single switched socket outlet (BS 1363 / IEC 60884). "
        "IFC4 IfcElectricDistributionBoard NOTDEFINED."
    ),
    parameters=[
        FamilyParameter("voltage_v",      "number", default=230.0, min=100.0, max=415.0, units="V"),
        FamilyParameter("current_a",      "number", default=13.0,  min=1.0,   max=63.0,  units="A"),
        FamilyParameter("is_switched",    "boolean", default=True),
        FamilyParameter("flush_depth_mm", "number", default=45.0,  min=30.0,  max=80.0,  units="mm"),
    ],
    formulas=[
        FamilyFormula("max_power_w", "voltage_v * current_a"),
    ],
    geometry_script="""
result = {
    "family": "Single Socket Outlet",
    "category": "fixture",
    "ifc_type": "IfcElectricDistributionBoard",
    "ifc_predefined_type": "NOTDEFINED",
    "voltage_v": voltage_v,
    "current_a": current_a,
    "max_power_w": max_power_w,
    "is_switched": is_switched,
    "ports": [
        {"name": "Power In", "kind": "SINK", "medium": "electrical",
         "size_mm": 0, "offset_xyz": [0.0, 0.0, 0.0]},
    ],
}
""",
)

JUNCTION_BOX_FAMILY = FamilyDef(
    name="Junction Box",
    category="fixture",
    description=(
        "Electrical junction box for conduit termination. "
        "IFC4 IfcJunctionBox POWER. "
        "BS EN 60670-22 / IEC 60670-22."
    ),
    parameters=[
        FamilyParameter("width_mm",  "number", default=150.0, min=50.0, max=500.0, units="mm"),
        FamilyParameter("height_mm", "number", default=150.0, min=50.0, max=500.0, units="mm"),
        FamilyParameter("depth_mm",  "number", default=70.0,  min=30.0, max=200.0, units="mm"),
        FamilyParameter("ip_rating", "number", default=55.0,  min=0.0,  max=69.0,
                        description="IP rating (e.g. 55 = IP55)"),
        FamilyParameter("n_knockouts","number", default=4.0,  min=1.0,  max=20.0,
                        description="Number of conduit entry knockouts"),
    ],
    formulas=[
        FamilyFormula("volume_cm3", "width_mm * height_mm * depth_mm / 1000.0"),
    ],
    geometry_script="""
result = {
    "family": "Junction Box",
    "category": "fixture",
    "ifc_type": "IfcJunctionBox",
    "ifc_predefined_type": "POWER",
    "width_mm": width_mm,
    "height_mm": height_mm,
    "depth_mm": depth_mm,
    "ip_rating_str": f"IP{int(ip_rating)}",
    "n_knockouts": int(n_knockouts),
    "volume_cm3": round(volume_cm3, 1),
    "ports": [
        {"name": f"Conduit {i+1}", "kind": "SOURCEANDSINK",
         "medium": "electrical", "size_mm": 25,
         "offset_xyz": [i*30.0, 0.0, 0.0]}
        for i in range(int(n_knockouts))
    ],
}
""",
)


# ---------------------------------------------------------------------------
# All families registry
# ---------------------------------------------------------------------------

ALL_MEP_FAMILIES: list[FamilyDef] = [
    AIR_DIFFUSER_FAMILY,
    AIR_GRILLE_FAMILY,
    DUCT_TEE_FAMILY,
    DUCT_ELBOW_FAMILY,
    DUCT_REDUCER_FAMILY,
    PIPE_VALVE_FAMILY,
    PIPE_PUMP_FAMILY,
    LUMINAIRE_FAMILY,
    SOCKET_OUTLET_FAMILY,
    JUNCTION_BOX_FAMILY,
]

# Name → family lookup
_FAMILY_REGISTRY: dict[str, FamilyDef] = {f.name: f for f in ALL_MEP_FAMILIES}

# IFC4 type mapping per family name
_IFC_MAP: dict[str, MEPFamilyIFCMap] = {}  # populated lazily by ifc_type_for_family


def ifc_type_for_family(family_name: str) -> Optional[str]:
    """Return the IFC4 entity type string for *family_name*, or None."""
    fdef = _FAMILY_REGISTRY.get(family_name)
    if fdef is None:
        return None
    try:
        result = instantiate_family(fdef)
        if isinstance(result, dict):
            return result.get("ifc_type")
    except Exception:
        pass
    return None


def ifc_predefined_type_for_family(family_name: str) -> Optional[str]:
    """Return the IFC4 PredefinedType for *family_name*, or None."""
    fdef = _FAMILY_REGISTRY.get(family_name)
    if fdef is None:
        return None
    try:
        result = instantiate_family(fdef)
        if isinstance(result, dict):
            return result.get("ifc_predefined_type")
    except Exception:
        pass
    return None


def connector_ports_for_family(
    family_name: str,
    param_overrides: Optional[Dict[str, Any]] = None,
) -> List[MEPPortDescriptor]:
    """Return connector port descriptors for *family_name*.

    Evaluates the family with *param_overrides* and converts the ``ports``
    list in the result to :class:`MEPPortDescriptor` instances.

    Parameters
    ----------
    family_name : str
        One of the family names in :data:`ALL_MEP_FAMILIES`.
    param_overrides : dict | None
        Optional parameter overrides for the instantiation.

    Returns
    -------
    list[MEPPortDescriptor]
        Empty list if the family is not found or has no ports.
    """
    fdef = _FAMILY_REGISTRY.get(family_name)
    if fdef is None:
        return []
    try:
        result = instantiate_family(fdef, param_overrides)
        if not isinstance(result, dict):
            return []
        raw_ports = result.get("ports", [])
        ports = []
        for rp in raw_ports:
            if isinstance(rp, dict):
                ports.append(MEPPortDescriptor(
                    name=str(rp.get("name", "")),
                    kind=str(rp.get("kind", ConnectorPortKind.NOTDEFINED)),
                    medium=str(rp.get("medium", "air")),
                    offset_xyz=list(rp.get("offset_xyz", [0.0, 0.0, 0.0])),
                    size_mm=float(rp.get("size_mm", 0.0)),
                ))
        return ports
    except Exception:
        return []
