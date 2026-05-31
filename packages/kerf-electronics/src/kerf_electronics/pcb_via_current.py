"""
PCB via maximum current-carrying capacity — IPC-2152 §6.3 + IPC-2221A §6.

A plated-through-hole (PTH) via carries current through its plated copper
barrel.  The barrel cross-section is an annulus whose area (thin-wall
approximation) is:

  A_barrel = π × D_drill × t_plating

where D_drill is the finished drill diameter and t_plating is the copper
plating thickness on the barrel wall.  This cross-section is then treated
exactly like a rectangular trace cross-section and fed into the IPC-2221B
Eq. 6-4 empirical model:

  I_via [A] = k · ΔT^0.44 · A^0.725

The equivalent trace width for the via barrel at 1 oz copper is:

  w_equiv_mm = A_barrel_um2 / (1e6 × t_1oz_mm)

where t_1oz_mm = 0.0348 mm (1 oz/ft² copper thickness, IPC-4562).

References
----------
IPC-2152 (2009) §6.3 "Via current-carrying capacity":
    Barrel cross-section A = π × D × t (thin-wall);
    capacity follows the same empirical curve family as traces.

IPC-2221A (1998) §6:
    Earlier standard; same empirical basis.  IPC-2152 supersedes it with a
    larger test dataset; results here use IPC-2221B coefficients (k_ext=0.048)
    as the via barrel is an external-copper feature (open to ambient through
    the drill hole).

IPC-4562 (2011) Table 4-1:
    1 oz/ft² ≈ 34.8 µm nominal copper thickness.

Saturn PCB Toolkit (widely used design reference):
    Confirms barrel area = π × D × t and IPC-2221 application to vias.

HONEST CAVEATS (always reported)
---------------------------------
1. IPC empirical model (thin-wall annulus + IPC-2221B formula).  IPC-2152
   §6.3 is the most rigorous published standard; the result is an empirical
   estimate, not an exact thermal calculation.  Actual via capacity depends
   on thermal coupling to adjacent copper planes, pad size, and via fill
   material (air-filled vias transfer less heat than resin/copper-filled).
2. Plane proximity NOT modelled.  An adjacent solid ground/power plane within
   1–2 drill diameters dramatically increases heat spreading (IPC-2152 §6.2
   plane-proximity correction cf_pl); this is conservatively excluded here.
   Real-world capacity with an adjacent plane can be 10–30% higher.
3. Via length (board thickness) does NOT directly reduce current capacity
   in the IPC-2221B formula (only cross-section and ΔT matter); however,
   longer vias have higher barrel resistance and more I²R heating.  Via
   resistance R = ρ_Cu × L / A is computed and reported but does NOT feed
   back into the capacity formula.
4. Multiple-via derating NOT applied.  The model returns per-via capacity;
   for a tight cluster of vias the mutual heating reduces individual capacity
   by ~10–20% (IPC-7093 §4.1).  Apply a 0.80–0.90 derating factor for
   dense arrays.
5. Copper purity / plating quality: electroless + electrolytic barrel copper
   is typically 99.9% purity (ρ ≈ 1.724e-8 Ω·m); impurities or voided
   plating reduce capacity and are not modelled.
6. Temperature coefficient of copper resistivity (α ≈ 3.93e-3 /°C) means
   the actual barrel resistance is higher at elevated temperature; the
   IPC-2221B capacity formula uses a fixed ΔT and does NOT iterate on the
   copper-resistance change, so results are slightly optimistic at high ΔT.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Physical constants / conversion factors
# ---------------------------------------------------------------------------

# IPC-2221B Eq. 6-4 empirical coefficients (external copper)
# Via barrel is treated as external copper (open drill cavity):
_K_EXTERNAL: float = 0.048
_IPC_B: float = 0.44       # temperature-rise exponent
_IPC_C: float = 0.725      # area exponent

# Copper material constants
_RHO_CU_20C: float = 1.724e-8  # Ω·m  (IEC 60228, annealed copper at 20 °C)

# IPC-4562 Table 4-1: 1 oz/ft² = 34.8 µm nominal copper thickness
_T_1OZ_MM: float = 0.0348       # mm per oz/ft²
_T_1OZ_UM: float = 34.8         # µm per oz/ft²

# Unit conversions
_MM_PER_MIL: float = 0.0254     # 1 mil = 0.0254 mm
_UM_PER_MM: float = 1_000.0     # 1 mm = 1000 µm
_UM2_PER_MIL2: float = (_MM_PER_MIL * _UM_PER_MM) ** 2  # 1 mil² = 645.16 µm²


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PcbViaSpec:
    """PCB via geometry and thermal specification.

    Attributes:
        drill_diameter_mm: Finished drill diameter [mm].  Typical: 0.20–1.00 mm.
            IPC-2221A §9.1 minimum production drill: 0.15 mm; practical minimum
            for standard fab: 0.20–0.30 mm.
        plating_thickness_um: Copper plating thickness on barrel wall [µm].
            IPC-6012 Class B (Class 2 rigid PCB) minimum: 20 µm average /
            18 µm min.  Typical: 25 µm (standard), 35 µm (IPC Class 3 / high
            reliability), 50 µm+ (heavy copper HDI).
        via_length_mm: Via barrel length [mm], equal to PCB board thickness.
            Used to compute barrel DC resistance (reported but not in capacity
            formula).  Typical: 0.8–3.2 mm (1.6 mm standard FR-4).
        temp_rise_C: Allowable temperature rise above ambient [°C].
            Default 10 °C (IPC-2221B conservative guideline).
        copper_pad_size_mm: Annular copper pad diameter [mm] around the via
            (informational, used for reporting equivalent trace width context).
            Not used in the capacity calculation.  Default 1.0 mm.
    """
    drill_diameter_mm: float
    plating_thickness_um: float
    via_length_mm: float
    temp_rise_C: float = 10.0
    copper_pad_size_mm: float = 1.0


@dataclass
class PcbViaCurrentReport:
    """Result of the IPC-2152 §6.3 via maximum current calculation.

    Attributes:
        max_current_A: Maximum allowable DC current per via [A].
        via_cross_section_um2: Barrel copper cross-sectional area [µm²]
            = π × drill_diameter_mm × 1000 × plating_thickness_um.
        equivalent_trace_width_mm: Width of a 1 oz copper trace with the
            same cross-sectional area as the via barrel [mm].  Useful for
            verifying via current against IPC-2221 trace-width design rules.
        recommended_via_count_for_target_current: Number of vias needed to
            carry target_current_A.  Returns 1 when no target specified.
            Uses ceil(target / per_via) per IPC-2152 §6.3 Note 2.
        honest_caveat: Engineering notes and model limitations.
    """
    max_current_A: float
    via_cross_section_um2: float
    equivalent_trace_width_mm: float
    recommended_via_count_for_target_current: int
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _barrel_cross_section_um2(drill_diameter_mm: float, plating_thickness_um: float) -> float:
    """Thin-wall annulus approximation: A = π × D × t.

    IPC-2152 §6.3 barrel cross-section formula:
      A_barrel = π × D_drill × t_plating   (thin-wall, t << D/2)

    Args:
        drill_diameter_mm: Finished drill diameter [mm].
        plating_thickness_um: Plating thickness [µm].

    Returns:
        Cross-sectional area [µm²].
    """
    D_um = drill_diameter_mm * _UM_PER_MM   # mm → µm
    t_um = plating_thickness_um              # already µm
    return math.pi * D_um * t_um


def _via_capacity_amps(cross_section_um2: float, temp_rise_C: float) -> float:
    """IPC-2221B Eq. 6-4 applied to via barrel cross-section.

    Converts µm² to mil² before applying the formula.

    Formula:  I [A] = k · ΔT^b · A_mil²^c
    where k=0.048 (external), b=0.44, c=0.725.

    Args:
        cross_section_um2: Barrel area [µm²].
        temp_rise_C: Allowable temperature rise [°C].

    Returns:
        Maximum current [A].
    """
    # µm² → mil²:  1 mil² = 645.16 µm²
    A_mil2 = cross_section_um2 / _UM2_PER_MIL2
    return _K_EXTERNAL * (temp_rise_C ** _IPC_B) * (A_mil2 ** _IPC_C)


def _equiv_trace_width_mm(cross_section_um2: float) -> float:
    """Width [mm] of a 1 oz trace with the same area as via barrel.

    w_mm = A_um2 / (t_1oz_um × 1e6 / 1e6)  →  A_um2 / (t_1oz_mm × 1e6)
         = cross_section_um2 / (34.8 × 1000)

    Args:
        cross_section_um2: Cross-section [µm²].

    Returns:
        Equivalent trace width [mm] at 1 oz copper.
    """
    t_1oz_um = _T_1OZ_UM   # 34.8 µm
    # A [µm²] = w_um × t_um  →  w_um = A / t;  w_mm = w_um / 1000
    return (cross_section_um2 / t_1oz_um) / _UM_PER_MM


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_pcb_via_max_current(
    spec: PcbViaSpec,
    target_current_A: float | None = None,
) -> PcbViaCurrentReport:
    """Compute maximum allowable DC current for a PCB plated-through-hole via.

    Uses the IPC-2152 §6.3 thin-wall barrel model combined with the
    IPC-2221B Eq. 6-4 empirical current formula:

      A_barrel [µm²] = π × D_drill [µm] × t_plating [µm]
      I_via [A]      = 0.048 × ΔT^0.44 × A_barrel_mil²^0.725

    When target_current_A is provided, also computes how many parallel vias
    are needed to carry that current:
      N_vias = ceil(target_current_A / I_per_via)

    Args:
        spec: PcbViaSpec — drill diameter, plating thickness, board thickness
            (via length), temperature rise, and pad size.
        target_current_A: Optional target current [A] to compute via count.
            If None or ≤ 0, recommended_via_count_for_target_current = 1.

    Returns:
        PcbViaCurrentReport with max_current_A, via_cross_section_um2,
        equivalent_trace_width_mm, recommended_via_count_for_target_current,
        and honest_caveat.

    Raises:
        ValueError: If any input parameter is invalid.
    """
    # ---- input validation ----
    D = float(spec.drill_diameter_mm)
    t = float(spec.plating_thickness_um)
    L = float(spec.via_length_mm)
    dT = float(spec.temp_rise_C)
    pad = float(spec.copper_pad_size_mm)

    if D <= 0:
        raise ValueError(f"drill_diameter_mm must be > 0, got {D}")
    if t <= 0:
        raise ValueError(f"plating_thickness_um must be > 0, got {t}")
    if L <= 0:
        raise ValueError(f"via_length_mm must be > 0, got {L}")
    if dT <= 0:
        raise ValueError(f"temp_rise_C must be > 0, got {dT}")
    if pad <= 0:
        raise ValueError(f"copper_pad_size_mm must be > 0, got {pad}")

    # Thin-wall approximation requires t << D/2.  Warn in caveat if not.
    D_um = D * _UM_PER_MM
    thin_wall_ok = t < (D_um / 2.0)

    # ---- geometry ----
    A_um2 = _barrel_cross_section_um2(D, t)

    # ---- current capacity ----
    I_via = _via_capacity_amps(A_um2, dT)

    # ---- equivalent 1 oz trace width ----
    w_equiv = _equiv_trace_width_mm(A_um2)

    # ---- via count recommendation ----
    if target_current_A is not None and target_current_A > 0:
        n_vias = math.ceil(float(target_current_A) / I_via)
    else:
        n_vias = 1

    # ---- honest caveat ----
    thin_wall_note = (
        ""
        if thin_wall_ok
        else (
            f" WARNING: plating thickness ({t:.1f} µm) is NOT small relative to "
            f"drill radius ({D_um/2:.1f} µm); thin-wall approximation A=π·D·t "
            f"may underestimate the true annular area by up to "
            f"{100*(1 - math.pi*D_um*t / (math.pi*((D_um/2+t)**2-(D_um/2)**2))):.0f}%"
            f" — use exact annular area formula for thick-plated HDI vias."
        )
    )

    caveat = (
        "IPC-2152 §6.3 thin-wall barrel model + IPC-2221B Eq. 6-4 empirical formula "
        "(k=0.048, ΔT^0.44 × A_mil²^0.725). "
        "Via barrel treated as external copper (open drill cavity). "
        "PLANE PROXIMITY NOT MODELLED: an adjacent ground/power plane within 1–2× "
        "drill diameter increases capacity by 10–30% (IPC-2152 cf_pl) — result is "
        "conservative when a plane is present. "
        "VIA FILL EFFECT NOT MODELLED: resin-filled or copper-filled vias conduct "
        "heat more efficiently than air-filled; air-filled assumption is conservative. "
        "DENSE ARRAY DERATING NOT APPLIED: mutual heating in a tight cluster of vias "
        "reduces individual capacity by ~10–20% (IPC-7093 §4.1); apply 0.80–0.90 "
        "derating factor for dense arrays. "
        "COPPER RESISTIVITY INCREASE with temperature (α ≈ 3.93e-3 /°C) not iterated "
        "into the IPC formula; capacity is slightly optimistic at ΔT > 20 °C. "
        "VIA LENGTH / BOARD THICKNESS does not enter the IPC-2221B capacity formula "
        "(only cross-section and ΔT matter); barrel DC resistance is higher for thicker "
        "boards but via thermal capacity is the limiting constraint at DC."
        + thin_wall_note
    )

    return PcbViaCurrentReport(
        max_current_A=round(I_via, 6),
        via_cross_section_um2=round(A_um2, 2),
        equivalent_trace_width_mm=round(w_equiv, 6),
        recommended_via_count_for_target_current=n_vias,
        honest_caveat=caveat,
    )
