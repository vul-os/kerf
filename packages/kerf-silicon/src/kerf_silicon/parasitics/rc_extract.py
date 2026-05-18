"""
RC parasitic extraction for post-layout net analysis.

Models:
  - Resistance per wire segment:  R = ρ·L/W   (sheet resistance × aspect ratio)
  - Plate capacitance to substrate: C_plate = ε₀·εr·A / d
  - Lateral coupling (first-order analytical): fringe + parallel-plate to neighbour

References:
  - Weste & Harris, "CMOS VLSI Design", 4th ed.
  - Baker, "CMOS: Circuit Design, Layout, and Simulation", 3rd ed.
  - IEEE 1481-1999 (SPEF)

Physical constants
------------------
ε₀ = 8.854 187 817 × 10⁻¹² F/m

Coordinates
-----------
All layout coordinates are in **micrometres (μm)**.
Layer parameters use SI units (Ω/□ and F/μm²).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

_EPSILON_0 = 8.854187817e-12   # F/m

# ---------------------------------------------------------------------------
# PDK technology defaults
# ---------------------------------------------------------------------------

# Default per-layer technology parameters bundled with the extractor.
# Keys: layer name.
# Values:
#   rho_sq    : sheet resistance in Ω/□
#   cap_aF_um2: area capacitance to substrate in aF/μm²   (aF = 1e-18 F)
#   thickness_nm: conductor thickness (nm) — used for fringe
#   height_nm : height above substrate ground plane (nm)
#   epsilon_r : inter-layer dielectric relative permittivity

_DEFAULT_TECH: dict[str, dict[str, float]] = {
    "met1": {
        "rho_sq":       0.125,    # Ω/□
        "cap_aF_um2":   80.0,     # aF/μm²  (plate cap to substrate)
        "thickness_nm": 300.0,    # nm
        "height_nm":    230.0,    # nm above substrate (oxide thickness)
        "epsilon_r":    3.9,      # SiO₂
    },
    "met2": {
        "rho_sq":       0.080,
        "cap_aF_um2":   40.0,
        "thickness_nm": 400.0,
        "height_nm":    700.0,
        "epsilon_r":    3.9,
    },
    "met3": {
        "rho_sq":       0.060,
        "cap_aF_um2":   25.0,
        "thickness_nm": 600.0,
        "height_nm":    1400.0,
        "epsilon_r":    3.9,
    },
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RSegment:
    """Resistance of one wire segment."""
    layer: str
    length_um: float
    width_um: float
    R_ohm: float


@dataclass
class CSegment:
    """Capacitance of one wire segment (plate + fringe)."""
    layer: str
    length_um: float
    width_um: float
    C_plate_F: float          # plate capacitance to substrate
    C_lateral_F: float        # first-order lateral coupling to neighbours
    C_total_F: float          # sum


@dataclass
class NetParasitics:
    """Aggregated parasitics for one net."""
    name: str
    R_total_ohm: float = 0.0
    C_total_F: float = 0.0
    R_segments: list[RSegment] = field(default_factory=list)
    C_segments: list[CSegment] = field(default_factory=list)


@dataclass
class ParasiticReport:
    """Top-level extraction result."""
    nets: dict[str, NetParasitics] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Layout geometry helpers
# ---------------------------------------------------------------------------

@dataclass
class Wire:
    """
    A single rectangular wire segment on a routing layer.

    Attributes
    ----------
    net   : net name this wire belongs to
    layer : metal layer name (e.g. 'met1')
    x0, y0, x1, y1 : bounding-box corners in μm (x0 ≤ x1, y0 ≤ y1)
    """
    net: str
    layer: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def length_um(self) -> float:
        """Length of the longer dimension (routing direction)."""
        dx = abs(self.x1 - self.x0)
        dy = abs(self.y1 - self.y0)
        return max(dx, dy)

    @property
    def width_um(self) -> float:
        """Width of the shorter dimension."""
        dx = abs(self.x1 - self.x0)
        dy = abs(self.y1 - self.y0)
        return min(dx, dy)

    @property
    def area_um2(self) -> float:
        return self.length_um * self.width_um


@dataclass
class Layout:
    """
    Minimal routed layout representation.

    Parameters
    ----------
    wires : list of Wire objects describing the post-route geometry.
    """
    wires: list[Wire] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core extraction functions
# ---------------------------------------------------------------------------

def _resistance(wire: Wire, tech_layer: dict[str, float]) -> RSegment:
    """
    Compute resistance of one wire segment.

    R = ρ × (L / W)   where ρ is sheet resistance (Ω/□).

    Zero-width wires return R = 0 (degenerate; caller should warn).
    """
    rho = tech_layer["rho_sq"]
    L = wire.length_um
    W = wire.width_um
    R = 0.0
    if W > 0.0:
        R = rho * (L / W)
    return RSegment(
        layer=wire.layer,
        length_um=L,
        width_um=W,
        R_ohm=R,
    )


def _capacitance(
    wire: Wire,
    tech_layer: dict[str, float],
    same_layer_wires: list[Wire],
) -> CSegment:
    """
    Compute capacitance of one wire segment.

    Plate capacitance (parallel-plate to substrate)
    ------------------------------------------------
    C_plate = cap_aF_um2 × Area   [converted to Farads]

    Lateral coupling (first-order analytical)
    -----------------------------------------
    For each same-net-different or different-net wire on the same layer
    that runs parallel and within a coupling distance, we compute:

        C_lateral ≈ ε₀·εr · t · L_overlap / gap

    where t is conductor thickness, L_overlap is parallel overlap length,
    and gap is the edge-to-edge spacing.  We add this to C_total.
    """
    cap_aF_um2 = tech_layer["cap_aF_um2"]
    area_um2 = wire.area_um2
    C_plate_F = cap_aF_um2 * 1e-18 * area_um2   # aF/μm² × μm² → F

    eps_r = tech_layer["epsilon_r"]
    t_um = tech_layer["thickness_nm"] * 1e-3   # nm → μm
    # height above substrate in μm (used for fringe — not dominant here)

    C_lateral_F = _lateral_coupling(wire, same_layer_wires, eps_r, t_um)
    C_total_F = C_plate_F + C_lateral_F

    return CSegment(
        layer=wire.layer,
        length_um=wire.length_um,
        width_um=wire.width_um,
        C_plate_F=C_plate_F,
        C_lateral_F=C_lateral_F,
        C_total_F=C_total_F,
    )


def _lateral_coupling(
    wire: Wire,
    neighbours: list[Wire],
    eps_r: float,
    t_um: float,
    max_coupling_um: float = 2.0,
) -> float:
    """
    First-order lateral capacitance between *wire* and its neighbours.

    Only parallel wire pairs on the same layer within *max_coupling_um*
    edge-to-edge distance are considered.

    Returns total lateral capacitance in Farads.
    """
    # ε₀·εr in SI  → but our geometry is in μm, so we need consistent units.
    # C = ε₀·εr · t[m] · L_overlap[m] / gap[m]
    # Convert μm → m : multiply by 1e-6.
    eps = _EPSILON_0 * eps_r   # F/m

    C_lat = 0.0

    # Determine if *wire* is horizontal or vertical
    dx = abs(wire.x1 - wire.x0)
    dy = abs(wire.y1 - wire.y0)
    wire_horizontal = dx >= dy

    for nb in neighbours:
        if nb is wire:
            continue
        if nb.layer != wire.layer:
            continue

        nb_dx = abs(nb.x1 - nb.x0)
        nb_dy = abs(nb.y1 - nb.y0)
        nb_horizontal = nb_dx >= nb_dy

        # Only couple parallel wires
        if wire_horizontal != nb_horizontal:
            continue

        if wire_horizontal:
            # Both horizontal — coupling is in Y direction
            # gap = edge-to-edge in Y
            wire_y_lo = min(wire.y0, wire.y1)
            wire_y_hi = max(wire.y0, wire.y1)
            nb_y_lo = min(nb.y0, nb.y1)
            nb_y_hi = max(nb.y0, nb.y1)

            # Signed gap between nearest edges
            if nb_y_lo > wire_y_hi:
                gap_um = nb_y_lo - wire_y_hi
            elif wire_y_lo > nb_y_hi:
                gap_um = wire_y_lo - nb_y_hi
            else:
                # Overlapping in Y — skip (physical short or same wire)
                continue

            if gap_um <= 0.0 or gap_um > max_coupling_um:
                continue

            # Overlap in X
            wire_x_lo = min(wire.x0, wire.x1)
            wire_x_hi = max(wire.x0, wire.x1)
            nb_x_lo = min(nb.x0, nb.x1)
            nb_x_hi = max(nb.x0, nb.x1)
            overlap_um = max(0.0, min(wire_x_hi, nb_x_hi) - max(wire_x_lo, nb_x_lo))

        else:
            # Both vertical — coupling is in X direction
            wire_x_lo = min(wire.x0, wire.x1)
            wire_x_hi = max(wire.x0, wire.x1)
            nb_x_lo = min(nb.x0, nb.x1)
            nb_x_hi = max(nb.x0, nb.x1)

            if nb_x_lo > wire_x_hi:
                gap_um = nb_x_lo - wire_x_hi
            elif wire_x_lo > nb_x_hi:
                gap_um = wire_x_lo - nb_x_hi
            else:
                continue

            if gap_um <= 0.0 or gap_um > max_coupling_um:
                continue

            wire_y_lo = min(wire.y0, wire.y1)
            wire_y_hi = max(wire.y0, wire.y1)
            nb_y_lo = min(nb.y0, nb.y1)
            nb_y_hi = max(nb.y0, nb.y1)
            overlap_um = max(0.0, min(wire_y_hi, nb_y_hi) - max(wire_y_lo, nb_y_lo))

        if overlap_um <= 0.0:
            continue

        # Convert μm → m
        t_m = t_um * 1e-6
        L_m = overlap_um * 1e-6
        g_m = gap_um * 1e-6

        C_seg = eps * t_m * L_m / g_m
        C_lat += C_seg

    return C_lat


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_rc(
    layout: Layout,
    tech: dict[str, dict[str, float]] | None = None,
    layers_to_extract: list[str] | None = None,
) -> ParasiticReport:
    """
    Extract RC parasitics from a routed layout.

    Parameters
    ----------
    layout           : Layout object containing wire segments.
    tech             : Per-layer technology parameters dict.
                       Defaults to _DEFAULT_TECH if None.
                       Keys are layer names; values are dicts with:
                         rho_sq        (Ω/□)
                         cap_aF_um2    (aF/μm²)
                         thickness_nm  (nm)
                         height_nm     (nm)
                         epsilon_r     (dimensionless)
    layers_to_extract: List of layer names to process.
                       Defaults to ['met1', 'met2', 'met3'].

    Returns
    -------
    ParasiticReport
        .nets : {net_name → NetParasitics}
        Each NetParasitics has:
            R_total_ohm, C_total_F, R_segments, C_segments
    """
    if tech is None:
        tech = _DEFAULT_TECH
    if layers_to_extract is None:
        layers_to_extract = ["met1", "met2", "met3"]

    report = ParasiticReport()

    # Filter wires to relevant layers only
    active_wires = [
        w for w in layout.wires
        if w.layer in layers_to_extract and w.layer in tech
    ]

    if not active_wires:
        return report

    # Group by layer for lateral coupling lookups
    wires_by_layer: dict[str, list[Wire]] = {}
    for w in active_wires:
        wires_by_layer.setdefault(w.layer, []).append(w)

    for wire in active_wires:
        net_name = wire.net
        tech_layer = tech[wire.layer]
        same_layer = wires_by_layer.get(wire.layer, [])

        r_seg = _resistance(wire, tech_layer)
        c_seg = _capacitance(wire, tech_layer, same_layer)

        net = report.nets.setdefault(
            net_name,
            NetParasitics(name=net_name),
        )
        net.R_total_ohm += r_seg.R_ohm
        net.C_total_F += c_seg.C_total_F
        net.R_segments.append(r_seg)
        net.C_segments.append(c_seg)

    return report
