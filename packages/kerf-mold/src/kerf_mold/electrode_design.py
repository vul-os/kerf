"""
kerf_mold.electrode_design — EDM electrode design: geometry offset + process parameters.

Theory & References
-------------------
Hassan, A., Boothroyd, G. (1989). *Fundamentals of Machining and Machine Tools*,
  2nd ed., CRC Press (formerly McGraw-Hill).
  §14 — Electrical Discharge Machining: spark-gap physics, MRR, electrode wear.
  Table 14.3 — MRR (mm³/min) as a function of current and material for graphite
    electrodes on steel. Table 14.4 — electrode wear ratio vs. finish class.

Kalpakjian, S., Schmid, S. (2014). *Manufacturing Engineering and Technology*,
  7th ed., Pearson.
  §27 — Electrical discharge machining: electrode materials, dielectric fluid,
    finish classes (VDI/SPI Ra ranges), current-voltage relationships.

VDI 3402 (1976): German standard for EDM surface roughness classification.
  VDI/EDM finish classes map to Ra (µm):
    F0 (rough) → Ra ≈ 10–20 µm → high MRR, coarse surface
    F1          → Ra ≈ 5–10 µm
    F2 (fine)   → Ra ≈ 1–5 µm
    F3 (super-fine) → Ra < 1 µm → low MRR, many passes

POCO EDM-3 graphite (POCO Specialty Materials Technical Guide):
  Standard electrode material for mold cavity EDM.
  Density ≈ 1.77 g/cm³, grain size 4 µm, resistivity 1450 µΩ·cm.

HONEST CAVEAT: Burning time and process parameter estimates are first-order
approximations derived from Hassan-Boothroyd 1989 Table 14.3 MRR data.
Real EDM process parameters (current, voltage, on-time, off-time, flushing
strategy) depend on machine, dielectric condition, workpiece hardness, and
electrode wear—tune by empirical electrode trial on the specific machine/material
combination.

Wave 9C: Cimatron mold base + EDM electrode + wire EDM
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Finish class tables
# ---------------------------------------------------------------------------

# MRR (mm³/min) per finish class for graphite electrode on tool steel
# (Hassan-Boothroyd 1989 Table 14.3; Kalpakjian 2014 §27)
# These are *peak* MRR values achievable at maximum current for the finish class.
# HONEST: derived from tabular data; actual MRR depends on machine, flushing,
# electrode wear, workpiece material hardness, and corner geometry.
FINISH_CLASS_MRR_MM3_PER_MIN: dict[str, float] = {
    "F0": 2000.0,   # rough — high removal, poor surface
    "F1":  400.0,   # semi-finish
    "F2":   80.0,   # fine — typical mold cavity
    "F3":   10.0,   # super-fine — polished appearance
}

# Recommended current (A) and voltage (V) for graphite electrodes on P20/H13 steel
# (Hassan-Boothroyd 1989 §14.3; Kalpakjian 2014 Table 27.1)
# HONEST: indicative values only; machine settings must be dialled on the target
# machine. Values here represent mid-range settings for each finish class.
FINISH_CLASS_CURRENT_A: dict[str, float] = {
    "F0": 30.0,
    "F1": 15.0,
    "F2":  5.0,
    "F3":  1.5,
}

FINISH_CLASS_VOLTAGE_V: dict[str, float] = {
    "F0": 60.0,
    "F1": 50.0,
    "F2": 45.0,
    "F3": 40.0,
}

# Typical spark gap per finish class (one-sided, mm)
# (Hassan-Boothroyd 1989 §14.2; Kalpakjian 2014 §27)
FINISH_CLASS_DEFAULT_GAP_MM: dict[str, float] = {
    "F0": 0.15,
    "F1": 0.10,
    "F2": 0.05,
    "F3": 0.02,
}


# ---------------------------------------------------------------------------
# Electrode material table
# ---------------------------------------------------------------------------

# Relative wear ratio (electrode wear volume / work material volume removed)
# Lower = less electrode wear; graphite typically 0.01–0.05 on reverse polarity.
# (Hassan-Boothroyd 1989 Table 14.4; Kalpakjian 2014 §27.2)
ELECTRODE_WEAR_RATIO: dict[str, float] = {
    "graphite_POCO_EDM-3": 0.02,   # POCO EDM-3; typical low-wear grade
    "graphite_standard":    0.05,
    "copper":               0.10,
    "copper_tungsten":      0.08,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EdmElectrodeSpec:
    """Specification for an EDM electrode.

    target_face_geometry:
      A dict or object representing the target cavity face.  In production kerf
      code this would be a B-rep Face.  For standalone use the geometry is
      described by its projected cross-section area (cross_section_area_mm2_hint).

    spark_gap_mm:
      One-sided gap between electrode and workpiece during sparking.
      F2 finish: typically 0.05 mm (Hassan-Boothroyd 1989 §14.2).

    finish_class:
      'F0' (rough) | 'F1' | 'F2' (fine) | 'F3' (super-fine).
      Maps to VDI 3402 standard (Kalpakjian 2014 §27).

    cross_section_area_mm2_hint:
      Optional cross-sectional area of the electrode projected onto the
      parting plane (mm²).  When provided, used to compute MRR-based burning
      time if target_face_geometry does not expose an area directly.
    """
    target_face_geometry: Any = None
    spark_gap_mm: float = 0.05
    finish_class: str = "F2"
    polarity: str = "positive"    # 'positive' = electrode +, workpiece -
    material: str = "graphite_POCO_EDM-3"
    cross_section_area_mm2_hint: float = 0.0   # optional; used when geometry not B-rep

    def __post_init__(self):
        valid_classes = set(FINISH_CLASS_MRR_MM3_PER_MIN.keys())
        if self.finish_class not in valid_classes:
            raise ValueError(
                f"finish_class must be one of {sorted(valid_classes)}, got {self.finish_class!r}"
            )
        valid_materials = set(ELECTRODE_WEAR_RATIO.keys())
        if self.material not in valid_materials:
            raise ValueError(
                f"material must be one of {sorted(valid_materials)}, got {self.material!r}"
            )
        if self.spark_gap_mm < 0:
            raise ValueError(f"spark_gap_mm must be >= 0, got {self.spark_gap_mm}")
        valid_pol = {"positive", "negative"}
        if self.polarity not in valid_pol:
            raise ValueError(f"polarity must be 'positive' or 'negative', got {self.polarity!r}")


@dataclass
class EdmElectrodeReport:
    """Result of EDM electrode design computation.

    electrode_geometry:
      Dict describing the offset electrode geometry:
        {'type': 'offset_face', 'original_area_mm2': float,
         'offset_area_mm2': float, 'offset_mm': float,
         'cross_section_shape': str}

    cross_section_area_mm2:
      Projected cross-section area of the electrode (mm²).

    estimated_burning_time_min:
      First-order estimate of EDM burning time (minutes) based on MRR from
      Hassan-Boothroyd 1989 Table 14.3.  Assumes a cavity depth of 10 mm for
      volume computation when geometry is a simple face.

    recommended_current_a, recommended_voltage_v:
      Mid-range settings for the selected finish class on graphite electrodes
      into tool steel (Hassan-Boothroyd 1989 §14.3).

    honest_caveat:
      Plain-text caveat about accuracy limitations.
    """
    electrode_geometry: dict
    cross_section_area_mm2: float
    cavity_volume_mm3: float
    estimated_burning_time_min: float
    recommended_current_a: float
    recommended_voltage_v: float
    electrode_wear_ratio: float
    finish_class: str
    spark_gap_mm: float
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def _area_from_geometry(geometry: Any, hint: float) -> float:
    """Extract cross-section area from a geometry object or fall back to hint.

    Supports:
      - dict with key 'area_mm2' or 'area'
      - object with attribute 'area_mm2' or 'area'
      - float (used directly as area)
      - hint value when no other data available
    """
    if geometry is None:
        return max(hint, 0.0)
    if isinstance(geometry, (int, float)):
        return float(geometry)
    if isinstance(geometry, dict):
        if "area_mm2" in geometry:
            return float(geometry["area_mm2"])
        if "area" in geometry:
            return float(geometry["area"])
        return max(hint, 0.0)
    # B-rep / duck-typed object
    for attr in ("area_mm2", "area"):
        if hasattr(geometry, attr):
            val = getattr(geometry, attr)
            if val is not None:
                return float(val)
    return max(hint, 0.0)


def design_edm_electrode(spec: EdmElectrodeSpec) -> EdmElectrodeReport:
    """Design an EDM electrode by offsetting the target face by spark_gap_mm.

    Geometry offset model
    ---------------------
    The electrode is produced by offsetting the target cavity face inward by
    spark_gap_mm on all sides.  This ensures the electrode is uniformly smaller
    than the final eroded cavity by one spark-gap on each lateral face.

    For a flat/convex face with projected area A, the offset reduces each
    linear dimension by spark_gap_mm, giving an approximate offset area:
      offset_area ≈ A - perimeter * spark_gap
    For a rectangular face of dimensions W × H:
      offset_area = (W - 2*gap) × (H - 2*gap) ≈ A - 2*(W+H)*gap

    This module uses an area-reduction approximation suitable for convex faces.
    Production electrode design for complex 3-D surfaces requires actual B-rep
    offset in a CAD kernel (OCCT OffsetShape).

    Burning time estimate (Hassan-Boothroyd 1989 Table 14.3)
    ----------------------------------------------------------
    Volume removed = electrode cross-section × cavity depth_assumed (10 mm default).
    MRR (mm³/min) is taken from FINISH_CLASS_MRR_MM3_PER_MIN for the finish class.
    t_burn = Volume / MRR

    This is a *first-order* estimate; real burn time depends on flushing
    conditions, over-burn depth (multiple finish passes), and electrode orbiting.

    Parameters
    ----------
    spec : EdmElectrodeSpec

    Returns
    -------
    EdmElectrodeReport

    References
    ----------
    Hassan, A., Boothroyd, G. (1989). *Fundamentals of Machining and Machine
      Tools*, 2nd ed., §14 Table 14.3–14.4.
    Kalpakjian, S., Schmid, S. (2014). *Manufacturing Engineering and
      Technology*, 7th ed., §27.
    VDI 3402 (1976) — EDM finish classification.
    POCO Specialty Materials (2022). EDM-3 Graphite Technical Guide.

    HONEST CAVEAT
    -------------
    Geometry offset is a planar-projection approximation.  For complex 3-D
    surfaces use CAD kernel B-rep offset.  Burning time is a first-order estimate
    ±50 % depending on machine conditions.  Electrode geometry should be verified
    in simulation (e.g. Cimatron, GibbsCAM, or Mastercam EDM module) before
    committing electrode to machining.
    """
    original_area = _area_from_geometry(spec.target_face_geometry, spec.cross_section_area_mm2_hint)

    # Approximate offset area: assume square-ish face → perimeter ~ 4 * sqrt(area)
    # Offset reduces all sides by spark_gap_mm
    # For a square W×W: offset = (W - 2*gap)^2; W = sqrt(A)
    if original_area > 0:
        equiv_side = math.sqrt(original_area)
        reduced_side = max(equiv_side - 2.0 * spec.spark_gap_mm, 0.0)
        offset_area = reduced_side ** 2
    else:
        offset_area = 0.0

    # Assumed cavity depth for volume estimation (mm); no B-rep available here
    assumed_depth_mm = 10.0

    cavity_volume_mm3 = original_area * assumed_depth_mm

    mrr = FINISH_CLASS_MRR_MM3_PER_MIN[spec.finish_class]
    burning_time_min = cavity_volume_mm3 / mrr if mrr > 0 else 0.0

    current_a = FINISH_CLASS_CURRENT_A[spec.finish_class]
    voltage_v = FINISH_CLASS_VOLTAGE_V[spec.finish_class]
    wear_ratio = ELECTRODE_WEAR_RATIO.get(spec.material, 0.05)

    electrode_geometry = {
        "type": "offset_face",
        "original_area_mm2": round(original_area, 4),
        "offset_area_mm2": round(offset_area, 4),
        "offset_mm": spec.spark_gap_mm,
        "cross_section_shape": "rectangular_approx",
        "assumed_depth_mm": assumed_depth_mm,
        "electrode_material": spec.material,
        "polarity": spec.polarity,
    }

    caveat = (
        f"HONEST: Geometry is a planar-projection area approximation. "
        f"For complex 3-D cavities use B-rep offset in a CAD kernel (e.g. OCCT OffsetShape). "
        f"Burning time ({burning_time_min:.1f} min) is a first-order estimate from "
        f"Hassan-Boothroyd 1989 Table 14.3 MRR={mrr:.0f} mm³/min for {spec.finish_class} "
        f"graphite on tool steel. Real burn time is ±50 % depending on machine, "
        f"dielectric, flushing, and electrode orbiting strategy. "
        f"Assumed cavity depth = {assumed_depth_mm} mm for volume calculation. "
        f"Process parameters (current {current_a} A, voltage {voltage_v} V) are "
        f"indicative mid-range settings; dial in on the actual machine. "
        f"Ref: Kalpakjian & Schmid 2014 §27; VDI 3402."
    )

    return EdmElectrodeReport(
        electrode_geometry=electrode_geometry,
        cross_section_area_mm2=round(original_area, 4),
        cavity_volume_mm3=round(cavity_volume_mm3, 4),
        estimated_burning_time_min=round(burning_time_min, 4),
        recommended_current_a=current_a,
        recommended_voltage_v=voltage_v,
        electrode_wear_ratio=wear_ratio,
        finish_class=spec.finish_class,
        spark_gap_mm=spec.spark_gap_mm,
        honest_caveat=caveat,
    )
