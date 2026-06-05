"""
kerf_civil.dry_utilities — Dry-utility network model + corridor coordination.

Dry utilities (gas, electrical, telecom/fiber) routed underground in corridors
alongside wet utilities (drainage, water mains).  This module provides:

1.  Data model
    - DryUtilityKind enum: GAS, ELECTRICAL, TELECOM
    - GasPipe, ElecDuctBank, TelecomDuct, DryUtilityNode, DryUtilityNetwork
    - CorridorLink: a single trench section carrying one or more utilities

2.  Separation / clearance check
    Inter-utility and utility-to-structure minimum separation per industry
    standards:
      • Gas ↔ Electrical : ≥ 300 mm (NFPA 54 / IGEM PL2 / AS/NZS 4645-1)
      • Gas ↔ Telecom    : ≥ 300 mm (same)
      • Electrical ↔ Telecom : ≥ 300 mm (IEC 60364 / NEC Art 800)
      • Any utility ↔ water/sewer : ≥ 300 mm (AWWA M23 §7.5)
      • Gas min cover (NPS ≤ 100 mm): 600 mm (ASME B31.8 §841.1)
      • Electrical (HV ≥ 1 kV) min cover: 600 mm (NEC Table 300.5)
      • Electrical (LV < 1 kV) min cover: 450 mm (NEC Table 300.5)
      • Telecom min cover: 450 mm (Telcordia GR-771 §5)

3.  Gas pressure-drop (Weymouth equation for compressible flow)
    References: Weymouth (1912) Trans. ASME; Menon (2005) "Gas Pipeline
    Hydraulics", CRC Press, Chapter 3.

    For short distribution mains, the incompressible (Darcy-Weisbach + Fanning)
    form is also available.

4.  Electrical duct-fill check per NEC Table 1 (Chapter 9) and NEMA CA 100
    fill-ratio rules.

5.  3-D proximity check: given node XYZ + depth-of-cover, detect pairs of
    utility links whose 3-D centreline distance < a minimum threshold.

Public API
----------
DryUtilityKind           enum
GasPipe                  dataclass
ElecDuctBank             dataclass
TelecomDuct              dataclass
DryUtilityNode           dataclass
CorridorLink             dataclass
DryUtilityNetwork        dataclass + build_network()

gas_pressure_drop_weymouth(Q_m3s, D_m, L_m, P1_kPa, T_K, SG,
                            eff, Z) -> dict
gas_pressure_drop_darcy(Q_m3s, D_m, L_m, P_kPa, mu_Pa_s, rho_kg_m3,
                         roughness_m) -> dict
electrical_duct_fill_check(conduit_id_mm, cables) -> dict
check_corridor_clearances(network, wet_utilities=None) -> list[dict]
build_network(nodes, links) -> DryUtilityNetwork
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DryUtilityKind(str, Enum):
    GAS       = "gas"
    ELECTRICAL = "electrical"
    TELECOM   = "telecom"


# ---------------------------------------------------------------------------
# Minimum separation rules  (metres)
# ---------------------------------------------------------------------------

#: Gas ↔ Electrical (NFPA 54 §5.5.1 / IGEM PL2 / AS/NZS 4645-1 §7.3)
SEP_GAS_ELEC_M: float = 0.300

#: Gas ↔ Telecom (IGEM PL2 Appendix C)
SEP_GAS_TELECOM_M: float = 0.300

#: Electrical ↔ Telecom (NEC Art 800 / IEC 60364-4-44 §444)
SEP_ELEC_TELECOM_M: float = 0.300

#: Any dry utility ↔ water or sewer (AWWA M23 §7.5 / ASME B31.8 §841.1)
SEP_DRY_WET_M: float = 0.300

#: Minimum cover — gas NPS ≤ 100 mm (ASME B31.8 §841.1.1 Table)
MIN_COVER_GAS_M: float = 0.600

#: Minimum cover — electrical HV (≥ 1 kV): NEC Table 300.5
MIN_COVER_ELEC_HV_M: float = 0.600

#: Minimum cover — electrical LV (< 1 kV): NEC Table 300.5
MIN_COVER_ELEC_LV_M: float = 0.450

#: Minimum cover — telecom (Telcordia GR-771 §5)
MIN_COVER_TELECOM_M: float = 0.450

# Map (kindA, kindB) sorted → required separation [m]
_PAIR_SEP: dict[tuple[str, str], float] = {
    ("electrical", "gas"):     SEP_GAS_ELEC_M,
    ("gas",        "telecom"): SEP_GAS_TELECOM_M,
    ("electrical", "telecom"): SEP_ELEC_TELECOM_M,
}

# Cover requirements per kind
_MIN_COVER: dict[str, float] = {
    DryUtilityKind.GAS.value:      MIN_COVER_GAS_M,
    DryUtilityKind.ELECTRICAL.value: MIN_COVER_ELEC_LV_M,  # LV default; HV overridden below
    DryUtilityKind.TELECOM.value:  MIN_COVER_TELECOM_M,
}


def _pair_sep_required(kind_a: str, kind_b: str) -> float:
    """Return required horizontal separation (m) for a pair of utility kinds."""
    key = tuple(sorted([kind_a, kind_b]))  # type: ignore[call-overload]
    return _PAIR_SEP.get(key, SEP_GAS_ELEC_M)  # conservative fallback


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class GasPipe:
    """A gas distribution or transmission main segment."""
    id: str
    diameter_mm: float          # nominal inside diameter [mm]
    material: str               # e.g. 'PE', 'steel', 'CI'
    mop_kPa: float              # maximum operating pressure [kPa gauge]
    roughness_mm: float = 0.046  # pipe wall roughness [mm] (steel default)

    @property
    def kind(self) -> str:
        return DryUtilityKind.GAS.value


@dataclass
class ElecDuctBank:
    """An electrical duct bank (one or more conduits in a casing)."""
    id: str
    conduit_id_mm: float        # conduit inside diameter [mm]
    n_conduits: int = 1         # total conduit count
    voltage_class: str = "LV"   # 'LV' (< 1 kV) | 'MV' (1–35 kV) | 'HV' (> 35 kV)
    cables_per_conduit: int = 1

    @property
    def kind(self) -> str:
        return DryUtilityKind.ELECTRICAL.value

    @property
    def min_cover_m(self) -> float:
        return MIN_COVER_ELEC_HV_M if self.voltage_class in ("MV", "HV") else MIN_COVER_ELEC_LV_M


@dataclass
class TelecomDuct:
    """A telecom / fiber duct or conduit."""
    id: str
    conduit_id_mm: float        # conduit inside diameter [mm]
    n_conduits: int = 1
    fiber_count: int = 0        # informational: number of fiber cores

    @property
    def kind(self) -> str:
        return DryUtilityKind.TELECOM.value


# Union type alias
UtilityAsset = GasPipe | ElecDuctBank | TelecomDuct


@dataclass
class DryUtilityNode:
    """
    A network node — manhole, handhole, valve, regulator, or splice point.
    """
    id: str
    x: float                    # easting [m]
    y: float                    # northing [m]
    z_surface_m: float          # surface (finished-grade) elevation [m]
    node_type: str = "manhole"  # 'manhole' | 'handhole' | 'valve' | 'regulator' | 'splice'


@dataclass
class CorridorLink:
    """
    A utility run between two DryUtilityNodes.

    A single link carries ONE utility asset (gas pipe, duct bank, or telecom
    duct).  Multiple parallel links sharing the same node_a/node_b model
    co-located utilities in the same corridor.
    """
    id: str
    node_from: str              # DryUtilityNode.id
    node_to:   str              # DryUtilityNode.id
    asset: UtilityAsset
    length_m: float             # horizontal length along route [m]
    depth_of_cover_m: float     # cover from finished grade to crown [m]
    corridor_offset_m: float    # lateral offset from road CL or reference [m]
    wet_utility_offset_m: Optional[float] = None  # measured separation to nearest wet utility


@dataclass
class DryUtilityNetwork:
    """A dry-utility network graph (nodes + corridor links)."""
    nodes: list[DryUtilityNode] = field(default_factory=list)
    links: list[CorridorLink]   = field(default_factory=list)

    # Convenience look-ups built by build_network()
    _node_map: dict[str, DryUtilityNode] = field(default_factory=dict, repr=False)
    _link_map: dict[str, CorridorLink]   = field(default_factory=dict, repr=False)

    def node(self, nid: str) -> DryUtilityNode:
        return self._node_map[nid]

    def links_at_node(self, nid: str) -> list[CorridorLink]:
        return [lk for lk in self.links if lk.node_from == nid or lk.node_to == nid]

    def links_between(self, a: str, b: str) -> list[CorridorLink]:
        """All links whose (from,to) matches (a,b) or (b,a)."""
        return [
            lk for lk in self.links
            if {lk.node_from, lk.node_to} == {a, b}
        ]


def build_network(
    nodes: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> DryUtilityNetwork:
    """
    Construct a DryUtilityNetwork from plain-dict node and link records.

    Node dict keys:
        id, x, y, z_surface_m, node_type (optional)

    Link dict keys:
        id, node_from, node_to, length_m, depth_of_cover_m, corridor_offset_m
        asset: dict with kind + kind-specific fields:
            kind='gas':       diameter_mm, material, mop_kPa, roughness_mm (opt)
            kind='electrical':conduit_id_mm, n_conduits, voltage_class, cables_per_conduit
            kind='telecom':   conduit_id_mm, n_conduits, fiber_count (opt)
        wet_utility_offset_m: float (optional)

    Raises ValueError for unknown asset kinds or missing required fields.
    """
    net = DryUtilityNetwork()

    for nd in nodes:
        n = DryUtilityNode(
            id=nd["id"],
            x=float(nd["x"]),
            y=float(nd["y"]),
            z_surface_m=float(nd["z_surface_m"]),
            node_type=nd.get("node_type", "manhole"),
        )
        net.nodes.append(n)
        net._node_map[n.id] = n

    for lk in links:
        asset_d = lk["asset"]
        kind = asset_d["kind"]
        if kind == DryUtilityKind.GAS.value:
            asset: UtilityAsset = GasPipe(
                id=lk["id"] + ".gas",
                diameter_mm=float(asset_d["diameter_mm"]),
                material=asset_d.get("material", "PE"),
                mop_kPa=float(asset_d["mop_kPa"]),
                roughness_mm=float(asset_d.get("roughness_mm", 0.046)),
            )
        elif kind == DryUtilityKind.ELECTRICAL.value:
            asset = ElecDuctBank(
                id=lk["id"] + ".elec",
                conduit_id_mm=float(asset_d["conduit_id_mm"]),
                n_conduits=int(asset_d.get("n_conduits", 1)),
                voltage_class=asset_d.get("voltage_class", "LV"),
                cables_per_conduit=int(asset_d.get("cables_per_conduit", 1)),
            )
        elif kind == DryUtilityKind.TELECOM.value:
            asset = TelecomDuct(
                id=lk["id"] + ".tel",
                conduit_id_mm=float(asset_d["conduit_id_mm"]),
                n_conduits=int(asset_d.get("n_conduits", 1)),
                fiber_count=int(asset_d.get("fiber_count", 0)),
            )
        else:
            raise ValueError(f"Unknown asset kind {kind!r} for link {lk['id']!r}")

        corridor_link = CorridorLink(
            id=lk["id"],
            node_from=lk["node_from"],
            node_to=lk["node_to"],
            asset=asset,
            length_m=float(lk["length_m"]),
            depth_of_cover_m=float(lk["depth_of_cover_m"]),
            corridor_offset_m=float(lk["corridor_offset_m"]),
            wet_utility_offset_m=float(lk["wet_utility_offset_m"])
                if lk.get("wet_utility_offset_m") is not None else None,
        )
        net.links.append(corridor_link)
        net._link_map[corridor_link.id] = corridor_link

    return net


# ---------------------------------------------------------------------------
# Clearance / separation check
# ---------------------------------------------------------------------------

class ViolationType(str, Enum):
    INTER_UTILITY_SEP = "inter_utility_separation"
    COVER_DEPTH       = "cover_depth"
    WET_UTILITY_SEP   = "wet_utility_separation"


def check_corridor_clearances(
    network: DryUtilityNetwork,
    wet_utility_offset_m: Optional[float] = None,
) -> list[dict[str, Any]]:
    """
    Detect clearance / separation violations for all links in ``network``.

    Checks performed
    ----------------
    1.  Cover depth — compares link.depth_of_cover_m against the standard
        minimum for its asset kind.
    2.  Inter-dry-utility separation — for every pair of links sharing both
        end-nodes (same corridor segment), compares the absolute difference in
        corridor_offset_m against the required pair separation.
    3.  Wet-utility separation — if link.wet_utility_offset_m is set, checks
        it against SEP_DRY_WET_M = 300 mm.

    Parameters
    ----------
    network : DryUtilityNetwork
    wet_utility_offset_m : float, optional
        Global override for wet-utility offset (used when individual links do
        not carry the value).

    Returns
    -------
    list[dict]  — one dict per violation:
        violation_type, link_id, [link_id_b], required_m, actual_m,
        deficit_m, description
    """
    violations: list[dict[str, Any]] = []

    # --- 1. Cover depth per link -----------------------------------------------
    for lk in network.links:
        asset = lk.asset
        kind = asset.kind
        if kind == DryUtilityKind.ELECTRICAL.value and isinstance(asset, ElecDuctBank):
            min_cover = asset.min_cover_m
        else:
            min_cover = _MIN_COVER.get(kind, 0.450)

        if lk.depth_of_cover_m < min_cover - 1e-9:
            violations.append({
                "violation_type": ViolationType.COVER_DEPTH.value,
                "link_id": lk.id,
                "link_id_b": None,
                "required_m": min_cover,
                "actual_m": lk.depth_of_cover_m,
                "deficit_m": round(min_cover - lk.depth_of_cover_m, 4),
                "description": (
                    f"Link {lk.id!r} ({kind}) cover {lk.depth_of_cover_m*1000:.0f} mm "
                    f"< required {min_cover*1000:.0f} mm"
                ),
            })

    # --- 2. Inter-utility separation -------------------------------------------
    # Group links by (frozenset of endpoint IDs) to find co-routed segments
    from collections import defaultdict
    seg_groups: dict[frozenset, list[CorridorLink]] = defaultdict(list)
    for lk in network.links:
        key = frozenset({lk.node_from, lk.node_to})
        seg_groups[key].append(lk)

    for seg_key, seg_links in seg_groups.items():
        if len(seg_links) < 2:
            continue
        # Check every unique pair
        for i in range(len(seg_links)):
            for j in range(i + 1, len(seg_links)):
                lk_a = seg_links[i]
                lk_b = seg_links[j]
                kind_a = lk_a.asset.kind
                kind_b = lk_b.asset.kind
                if kind_a == kind_b:
                    continue  # same type — no separation rule (bundle allowed)
                required = _pair_sep_required(kind_a, kind_b)
                # Lateral offset difference as proxy for physical separation
                actual = abs(lk_a.corridor_offset_m - lk_b.corridor_offset_m)
                if actual < required - 1e-9:
                    violations.append({
                        "violation_type": ViolationType.INTER_UTILITY_SEP.value,
                        "link_id": lk_a.id,
                        "link_id_b": lk_b.id,
                        "required_m": required,
                        "actual_m": round(actual, 4),
                        "deficit_m": round(required - actual, 4),
                        "description": (
                            f"{kind_a}/{kind_b} separation {actual*1000:.0f} mm "
                            f"< required {required*1000:.0f} mm "
                            f"(links {lk_a.id!r} vs {lk_b.id!r})"
                        ),
                    })

    # --- 3. Wet-utility separation ---------------------------------------------
    for lk in network.links:
        wet_sep = lk.wet_utility_offset_m if lk.wet_utility_offset_m is not None else wet_utility_offset_m
        if wet_sep is not None and wet_sep < SEP_DRY_WET_M - 1e-9:
            violations.append({
                "violation_type": ViolationType.WET_UTILITY_SEP.value,
                "link_id": lk.id,
                "link_id_b": None,
                "required_m": SEP_DRY_WET_M,
                "actual_m": round(wet_sep, 4),
                "deficit_m": round(SEP_DRY_WET_M - wet_sep, 4),
                "description": (
                    f"Link {lk.id!r} ({lk.asset.kind}) wet-utility offset "
                    f"{wet_sep*1000:.0f} mm < required {SEP_DRY_WET_M*1000:.0f} mm"
                ),
            })

    return violations


# ---------------------------------------------------------------------------
# 3-D proximity check (centroid distance between link centrelines)
# ---------------------------------------------------------------------------

def _link_centroid_3d(
    network: DryUtilityNetwork,
    lk: CorridorLink,
) -> tuple[float, float, float]:
    """Return the 3-D midpoint of a link's centreline (at pipe crown depth)."""
    nm = network._node_map
    if lk.node_from not in nm or lk.node_to not in nm:
        return (0.0, 0.0, 0.0)
    na = nm[lk.node_from]
    nb = nm[lk.node_to]
    mx = (na.x + nb.x) / 2.0
    my = (na.y + nb.y) / 2.0
    # Z = surface elevation − cover (mid-point average surface)
    z_surf = (na.z_surface_m + nb.z_surface_m) / 2.0
    mz = z_surf - lk.depth_of_cover_m
    return (mx, my, mz)


def proximity_check_3d(
    network: DryUtilityNetwork,
    min_separation_m: float = SEP_GAS_ELEC_M,
) -> list[dict[str, Any]]:
    """
    Check 3-D centreline proximity between every pair of links.

    Uses the midpoint of each link's 3-D centreline as a representative
    point.  For long links the caller should subdivide them.

    Parameters
    ----------
    network : DryUtilityNetwork
    min_separation_m : float
        Global minimum 3-D separation threshold.

    Returns
    -------
    list[dict] — per-pair proximity violation:
        link_id_a, link_id_b, distance_m, required_m, deficit_m
    """
    results: list[dict[str, Any]] = []
    links = network.links
    for i in range(len(links)):
        for j in range(i + 1, len(links)):
            lk_a = links[i]
            lk_b = links[j]
            if lk_a.asset.kind == lk_b.asset.kind:
                continue  # same type, no clash rule
            required = _pair_sep_required(lk_a.asset.kind, lk_b.asset.kind)
            ca = _link_centroid_3d(network, lk_a)
            cb = _link_centroid_3d(network, lk_b)
            dist = math.sqrt(
                (ca[0] - cb[0]) ** 2 +
                (ca[1] - cb[1]) ** 2 +
                (ca[2] - cb[2]) ** 2
            )
            if dist < required - 1e-9:
                results.append({
                    "link_id_a": lk_a.id,
                    "link_id_b": lk_b.id,
                    "distance_m": round(dist, 4),
                    "required_m": required,
                    "deficit_m": round(required - dist, 4),
                })
    return results


# ---------------------------------------------------------------------------
# Gas pressure drop — Weymouth equation (compressible)
# ---------------------------------------------------------------------------

def gas_pressure_drop_weymouth(
    Q_m3s: float,
    D_m: float,
    L_m: float,
    P1_kPa: float,
    T_K: float = 288.15,
    SG: float = 0.6,
    efficiency: float = 1.0,
    Z: float = 1.0,
) -> dict[str, Any]:
    """
    Compute gas pressure drop using the Weymouth equation for compressible
    steady-state isothermal flow in a horizontal pipe.

    Weymouth (1912):
        Q_std = (π/4) · E · D^(8/3) · √( (P1² - P2²) / (SG · T · Z · L) ) · C_w

    Rearranged for P2:
        P2² = P1² - (Q_std / (E · C_w · D^(8/3)))² · SG · T · Z · L

    where:
        C_w = 433.49 (SI base form, Q in m³/s std, P in kPa, D in m, L in m)
        E   = pipeline efficiency factor (0–1)
        SG  = gas specific gravity relative to air (air = 1.0)
        T   = average gas temperature [K]
        Z   = compressibility factor

    Reference: Menon, E.S. (2005) "Gas Pipeline Hydraulics", CRC Press, §3.3.
               Weymouth, T.R. (1912). Trans. ASME 34, 185–234.

    Parameters
    ----------
    Q_m3s   : float — volumetric flow rate at standard conditions [m³/s]
    D_m     : float — pipe inside diameter [m]
    L_m     : float — pipe length [m]
    P1_kPa  : float — upstream absolute pressure [kPa]
    T_K     : float — average gas temperature [K]; default 288.15 K (15 °C)
    SG      : float — gas specific gravity (air = 1.0); default 0.6 (natural gas)
    efficiency : float — pipeline efficiency E (0–1); default 1.0
    Z       : float — average compressibility factor; default 1.0 (ideal)

    Returns
    -------
    dict:
        ok          : bool
        P2_kPa      : float — downstream absolute pressure [kPa]
        dP_kPa      : float — pressure drop [kPa]
        dP_bar      : float — pressure drop [bar]
        velocity_m_s: float — average gas velocity at mean pressure [m/s]
        reynolds    : float — Reynolds number (approx, using dynamic viscosity ~1.1e-5 Pa·s)
        regime      : str   — 'turbulent' | 'laminar'
        warnings    : list[str]

    Raises
    ------
    ValueError for invalid inputs.
    """
    if D_m <= 0:
        raise ValueError(f"D_m must be > 0, got {D_m!r}")
    if L_m <= 0:
        raise ValueError(f"L_m must be > 0, got {L_m!r}")
    if P1_kPa <= 0:
        raise ValueError(f"P1_kPa must be > 0, got {P1_kPa!r}")
    if Q_m3s < 0:
        raise ValueError(f"Q_m3s must be >= 0, got {Q_m3s!r}")
    if not (0 < efficiency <= 1.0):
        raise ValueError(f"efficiency must be in (0, 1], got {efficiency!r}")

    warnings_out: list[str] = []

    # Weymouth constant (SI, Q in m³/s, P in kPa, D in m, L in m, T in K)
    # Derived from: Q = E * 8.8538e-3 * D^(8/3) * sqrt((P1²-P2²)/(SG*T*Z*L))
    # → solve: (P1² - P2²) = (Q / (E * Cw * D^(8/3)))^2 * SG*T*Z*L
    # Cw = 8.8538e-3 in the common form below (Menon 2005 SI eq 3.33 rearranged)
    Cw = 8.8538e-3  # Weymouth constant (SI)

    D8_3 = D_m ** (8.0 / 3.0)
    denominator = efficiency * Cw * D8_3

    if denominator == 0 or Q_m3s == 0:
        return {
            "ok": True,
            "P2_kPa": P1_kPa,
            "dP_kPa": 0.0,
            "dP_bar": 0.0,
            "velocity_m_s": 0.0,
            "reynolds": 0.0,
            "regime": "laminar",
            "warnings": ["Zero flow — no pressure drop."],
        }

    # P2² = P1² - (Q / (E*Cw*D^(8/3)))^2 * SG * T * Z * L
    P1_sq = P1_kPa ** 2
    P2_sq = P1_sq - (Q_m3s / denominator) ** 2 * SG * T_K * Z * L_m

    if P2_sq < 0:
        warnings_out.append(
            "P2² < 0 — flow rate exceeds capacity for this pipe geometry. "
            "Pressure drop is physically limited; result clamped to P2=0."
        )
        P2_kPa = 0.0
    else:
        P2_kPa = math.sqrt(P2_sq)

    dP_kPa = P1_kPa - P2_kPa
    dP_bar = dP_kPa / 100.0

    # Average velocity at mean pressure (ideal gas approximation)
    P_mean_kPa = (P1_kPa + P2_kPa) / 2.0
    P_mean_Pa = P_mean_kPa * 1e3
    R_air = 8314.0 / 28.97  # J/(kg·K) for air
    R_gas = R_air / SG      # approximate R for the gas
    rho_gas = P_mean_Pa / (Z * R_gas * T_K)  # kg/m³ at mean conditions
    # Convert std volumetric flow to actual vol flow:
    # rho_std = P_std*M/(Z_std*R*T_std); P_std=101.325 kPa, T_std=288.15 K, Z_std≈1
    rho_std = 101325.0 / (R_gas * 288.15)
    Q_actual = Q_m3s * rho_std / rho_gas  # m³/s at mean pressure
    A = math.pi * (D_m / 2.0) ** 2
    velocity = Q_actual / A if A > 0 else 0.0

    # Reynolds number (dynamic viscosity of natural gas ~1.1e-5 Pa·s)
    mu_gas = 1.1e-5  # Pa·s
    Re = rho_gas * velocity * D_m / mu_gas if mu_gas > 0 else 0.0
    regime = "turbulent" if Re > 4000 else "laminar"

    if dP_kPa > 0.5 * P1_kPa:
        warnings_out.append(
            f"Pressure drop ({dP_kPa:.1f} kPa) exceeds 50 % of upstream pressure. "
            "Weymouth equation assumes moderate pressure change; consider HPC solver."
        )

    return {
        "ok": True,
        "P2_kPa": round(P2_kPa, 4),
        "dP_kPa": round(dP_kPa, 4),
        "dP_bar": round(dP_bar, 6),
        "velocity_m_s": round(velocity, 4),
        "reynolds": round(Re, 0),
        "regime": regime,
        "warnings": warnings_out,
    }


# ---------------------------------------------------------------------------
# Gas pressure drop — Darcy-Weisbach incompressible (low-pressure distribution)
# ---------------------------------------------------------------------------

def gas_pressure_drop_darcy(
    Q_m3s: float,
    D_m: float,
    L_m: float,
    P_kPa: float,
    mu_Pa_s: float = 1.1e-5,
    rho_kg_m3: float = 0.72,
    roughness_m: float = 0.046e-3,
) -> dict[str, Any]:
    """
    Darcy-Weisbach pressure drop for incompressible (low-pressure) gas flow.

    Formula:
        h_L = f * (L/D) * V² / (2g)    [m of head]
        ΔP  = ρ · g · h_L               [Pa]

    Friction factor: Swamee-Jain (1976) explicit approximation of Colebrook-White.

    Reference: Swamee & Jain (1976) J. Hydraulics Div. ASCE 102(5) 657–664.
    """
    if D_m <= 0:
        raise ValueError(f"D_m must be > 0, got {D_m!r}")
    if L_m <= 0:
        raise ValueError(f"L_m must be > 0, got {L_m!r}")
    if Q_m3s < 0:
        raise ValueError(f"Q_m3s must be >= 0, got {Q_m3s!r}")

    warnings_out: list[str] = []
    A = math.pi * (D_m / 2.0) ** 2
    if Q_m3s == 0:
        return {
            "ok": True,
            "dP_Pa": 0.0, "dP_kPa": 0.0,
            "velocity_m_s": 0.0, "reynolds": 0.0,
            "friction_factor": 0.0, "regime": "laminar",
            "warnings": ["Zero flow — no pressure drop."],
        }

    V = Q_m3s / A
    Re = rho_kg_m3 * V * D_m / mu_Pa_s

    # Swamee-Jain friction factor
    eps_D = roughness_m / D_m
    if Re < 2300:
        f = 64.0 / Re
        regime = "laminar"
    else:
        # Swamee-Jain explicit (valid for 10^-6 ≤ ε/D ≤ 0.01, 5000 ≤ Re ≤ 10^8)
        f = 0.25 / (math.log10(eps_D / 3.7 + 5.74 / Re ** 0.9)) ** 2
        regime = "turbulent"
        if Re < 4000:
            warnings_out.append(
                f"Re = {Re:.0f} — flow is in transition zone; "
                "Swamee-Jain may be less accurate."
            )

    dP_Pa = f * (L_m / D_m) * rho_kg_m3 * V ** 2 / 2.0
    dP_kPa = dP_Pa / 1000.0

    return {
        "ok": True,
        "dP_Pa": round(dP_Pa, 4),
        "dP_kPa": round(dP_kPa, 6),
        "velocity_m_s": round(V, 4),
        "reynolds": round(Re, 0),
        "friction_factor": round(f, 6),
        "regime": regime,
        "warnings": warnings_out,
    }


# ---------------------------------------------------------------------------
# Electrical duct-fill check  (NEC Chapter 9, Table 1)
# ---------------------------------------------------------------------------

# NEC Table 1 Chapter 9: maximum fill ratios by cable count in conduit
# 1 cable: 53 %, 2 cables: 31 %, ≥ 3 cables: 40 %
_NEC_FILL_LIMIT: dict[int, float] = {1: 0.53, 2: 0.31}
_NEC_FILL_LIMIT_GT2 = 0.40

# Typical cable OD (mm) for NEC conduit sizing
# If exact OD unknown, caller supplies cable_od_mm
_CABLE_OD_TABLE: dict[str, float] = {
    "12AWG": 5.3,
    "10AWG": 5.9,
    "8AWG":  7.7,
    "6AWG":  9.0,
    "4AWG":  10.5,
    "2AWG":  12.3,
    "1AWG":  14.0,
    "1/0AWG": 15.3,
}


@dataclass
class CableSpec:
    """Single cable type for duct-fill calculation."""
    count: int
    od_mm: float        # outside diameter [mm]


def electrical_duct_fill_check(
    conduit_id_mm: float,
    cables: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Check electrical conduit / duct fill per NEC Chapter 9, Table 1 (2020).

    Parameters
    ----------
    conduit_id_mm : float
        Conduit inside diameter [mm].
    cables : list[dict]
        Each dict: {'count': int, 'od_mm': float}
        'od_mm' is the cable outside diameter.  Alternatively pass
        'awg': str (e.g. '12AWG') for automatic OD lookup.

    Returns
    -------
    dict:
        ok           : bool
        fill_pct     : float — actual fill percentage
        fill_limit_pct: float — NEC Table 1 limit
        total_cable_area_mm2: float
        conduit_area_mm2    : float
        n_cables     : int
        pass_fail    : 'PASS' | 'FAIL'
        cables       : list — resolved cable specs
        warnings     : list[str]
    """
    if conduit_id_mm <= 0:
        raise ValueError(f"conduit_id_mm must be > 0, got {conduit_id_mm!r}")
    if not cables:
        return {
            "ok": True,
            "fill_pct": 0.0,
            "fill_limit_pct": 40.0,
            "total_cable_area_mm2": 0.0,
            "conduit_area_mm2": math.pi * (conduit_id_mm / 2.0) ** 2,
            "n_cables": 0,
            "pass_fail": "PASS",
            "cables": [],
            "warnings": [],
        }

    warnings_out: list[str] = []
    resolved: list[dict[str, Any]] = []
    total_cable_area = 0.0
    n_total = 0

    for spec in cables:
        if "od_mm" in spec and spec["od_mm"] is not None:
            od = float(spec["od_mm"])
        elif "awg" in spec:
            awg = spec["awg"]
            if awg not in _CABLE_OD_TABLE:
                warnings_out.append(
                    f"AWG size {awg!r} not in table; using 10 mm OD as fallback."
                )
                od = 10.0
            else:
                od = _CABLE_OD_TABLE[awg]
        else:
            raise ValueError("Each cable spec must have 'od_mm' or 'awg'.")

        count = int(spec.get("count", 1))
        area_each = math.pi * (od / 2.0) ** 2
        total_cable_area += count * area_each
        n_total += count
        resolved.append({"count": count, "od_mm": od, "area_mm2": round(area_each, 4)})

    conduit_area = math.pi * (conduit_id_mm / 2.0) ** 2
    fill_pct = 100.0 * total_cable_area / conduit_area

    # NEC Table 1 limit by cable count
    limit_ratio = _NEC_FILL_LIMIT.get(n_total, _NEC_FILL_LIMIT_GT2)
    limit_pct = limit_ratio * 100.0

    pass_fail = "PASS" if fill_pct <= limit_pct else "FAIL"

    if fill_pct > 85.0:
        warnings_out.append(
            f"Duct fill {fill_pct:.1f} % is critically high; consider a larger conduit."
        )

    return {
        "ok": True,
        "fill_pct": round(fill_pct, 2),
        "fill_limit_pct": round(limit_pct, 1),
        "total_cable_area_mm2": round(total_cable_area, 4),
        "conduit_area_mm2": round(conduit_area, 4),
        "n_cables": n_total,
        "pass_fail": pass_fail,
        "cables": resolved,
        "warnings": warnings_out,
    }
