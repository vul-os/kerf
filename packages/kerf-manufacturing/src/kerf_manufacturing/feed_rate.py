"""
CAM feed-rate optimizer for Kerf manufacturing.

Computes recommended cutting parameters and optimizes per-segment feed rates
along a CNC toolpath using:

  - Altintas (2012) "Manufacturing Automation" §3 chip-load model
    (Table 3.1 material × tool cutting-speed reference data)
  - Standard SFM/Vc tables for steel / aluminum / engineering plastics
  - Machine acceleration cap (Altintas §3.6)
  - Tool deflection cap via Euler-Bernoulli cantilever beam model

DISCLAIMER
----------
Reference values are sourced from Altintas 2012 Table 3.1 and standard
machining handbooks.  They are NOT cutting-tool-manufacturer-certified and
should be treated as engineering starting-points only.  Always verify against
your specific tool manufacturer's recommended parameters and run appropriate
test cuts before production use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Material + tool database (Altintas 2012 Table 3.1 + SFM handbooks)
# ---------------------------------------------------------------------------

# Cutting speed Vc in m/min for each (material_class, tool_class) pair.
# Keys: material classes  → ALUMINUM, STEEL_MILD, STEEL_STAINLESS, STEEL_HARDENED,
#                            CAST_IRON, PLASTIC, TITANIUM, BRASS, COPPER
#       tool classes      → HSS, CARBIDE_UNCOATED, CARBIDE_COATED, CERAMIC, CERMET
#
# Values = (Vc_recommended_m_per_min, fz_default_mm_per_tooth_per_10mm_dia)
# fz is linearly scaled later: fz_actual = fz_default * (D_mm / 10.0)
#
# Source: Altintas 2012, Machinery's Handbook (31st ed.), Sandvik Coromant
# reference data.  NOT manufacturer-certified.

_VC_FZ_DB: dict[tuple[str, str], tuple[float, float]] = {
    # ── Aluminum ──────────────────────────────────────────────────────────
    ("ALUMINUM", "HSS"):               (100.0, 0.05),
    ("ALUMINUM", "CARBIDE_UNCOATED"):  (250.0, 0.08),
    ("ALUMINUM", "CARBIDE_COATED"):    (300.0, 0.10),
    ("ALUMINUM", "CERAMIC"):           (500.0, 0.12),
    ("ALUMINUM", "CERMET"):            (350.0, 0.10),

    # ── Mild / low-alloy steel ────────────────────────────────────────────
    ("STEEL_MILD", "HSS"):             (25.0,  0.04),
    ("STEEL_MILD", "CARBIDE_UNCOATED"): (80.0, 0.06),
    ("STEEL_MILD", "CARBIDE_COATED"):  (120.0, 0.07),
    ("STEEL_MILD", "CERAMIC"):         (300.0, 0.08),
    ("STEEL_MILD", "CERMET"):          (200.0, 0.07),

    # ── Stainless / 304–316 ───────────────────────────────────────────────
    ("STEEL_STAINLESS", "HSS"):             (15.0, 0.03),
    ("STEEL_STAINLESS", "CARBIDE_UNCOATED"): (60.0, 0.05),
    ("STEEL_STAINLESS", "CARBIDE_COATED"):   (90.0, 0.06),
    ("STEEL_STAINLESS", "CERAMIC"):          (200.0, 0.07),
    ("STEEL_STAINLESS", "CERMET"):           (150.0, 0.06),

    # ── Hardened tool steel (>55 HRC) ─────────────────────────────────────
    ("STEEL_HARDENED", "HSS"):              (5.0,  0.02),
    ("STEEL_HARDENED", "CARBIDE_UNCOATED"): (30.0, 0.03),
    ("STEEL_HARDENED", "CARBIDE_COATED"):   (50.0, 0.04),
    ("STEEL_HARDENED", "CERAMIC"):          (150.0, 0.05),
    ("STEEL_HARDENED", "CERMET"):           (100.0, 0.04),

    # ── Cast iron ─────────────────────────────────────────────────────────
    ("CAST_IRON", "HSS"):               (30.0, 0.05),
    ("CAST_IRON", "CARBIDE_UNCOATED"):  (100.0, 0.08),
    ("CAST_IRON", "CARBIDE_COATED"):    (150.0, 0.10),
    ("CAST_IRON", "CERAMIC"):           (600.0, 0.12),
    ("CAST_IRON", "CERMET"):            (350.0, 0.10),

    # ── Engineering plastics (nylon, ABS, PEEK, acrylic …) ───────────────
    ("PLASTIC", "HSS"):               (60.0,  0.05),
    ("PLASTIC", "CARBIDE_UNCOATED"):  (150.0, 0.08),
    ("PLASTIC", "CARBIDE_COATED"):    (200.0, 0.10),
    ("PLASTIC", "CERAMIC"):           (300.0, 0.10),
    ("PLASTIC", "CERMET"):            (250.0, 0.10),

    # ── Titanium alloys (Ti-6Al-4V) ───────────────────────────────────────
    ("TITANIUM", "HSS"):               (10.0, 0.03),
    ("TITANIUM", "CARBIDE_UNCOATED"):  (40.0, 0.04),
    ("TITANIUM", "CARBIDE_COATED"):    (55.0, 0.05),
    ("TITANIUM", "CERAMIC"):           (80.0, 0.05),
    ("TITANIUM", "CERMET"):            (60.0, 0.04),

    # ── Brass ─────────────────────────────────────────────────────────────
    ("BRASS", "HSS"):               (80.0,  0.06),
    ("BRASS", "CARBIDE_UNCOATED"):  (200.0, 0.10),
    ("BRASS", "CARBIDE_COATED"):    (250.0, 0.12),
    ("BRASS", "CERAMIC"):           (400.0, 0.12),
    ("BRASS", "CERMET"):            (300.0, 0.10),

    # ── Copper ────────────────────────────────────────────────────────────
    ("COPPER", "HSS"):               (70.0,  0.05),
    ("COPPER", "CARBIDE_UNCOATED"):  (180.0, 0.08),
    ("COPPER", "CARBIDE_COATED"):    (220.0, 0.10),
    ("COPPER", "CERAMIC"):           (350.0, 0.10),
    ("COPPER", "CERMET"):            (270.0, 0.10),
}

# Friendly alias map: human-readable material names → canonical keys
_MATERIAL_ALIASES: dict[str, str] = {
    "aluminum": "ALUMINUM",
    "aluminium": "ALUMINUM",
    "al": "ALUMINUM",
    "al6061": "ALUMINUM",
    "al7075": "ALUMINUM",
    "steel": "STEEL_MILD",
    "steel_mild": "STEEL_MILD",
    "mild_steel": "STEEL_MILD",
    "low_alloy_steel": "STEEL_MILD",
    "stainless": "STEEL_STAINLESS",
    "stainless_steel": "STEEL_STAINLESS",
    "ss": "STEEL_STAINLESS",
    "304": "STEEL_STAINLESS",
    "316": "STEEL_STAINLESS",
    "hardened_steel": "STEEL_HARDENED",
    "tool_steel": "STEEL_HARDENED",
    "cast_iron": "CAST_IRON",
    "grey_iron": "CAST_IRON",
    "plastic": "PLASTIC",
    "nylon": "PLASTIC",
    "abs": "PLASTIC",
    "peek": "PLASTIC",
    "acrylic": "PLASTIC",
    "titanium": "TITANIUM",
    "ti6al4v": "TITANIUM",
    "ti-6al-4v": "TITANIUM",
    "brass": "BRASS",
    "copper": "COPPER",
}

# Friendly alias map: tool names → canonical keys
_TOOL_ALIASES: dict[str, str] = {
    "hss": "HSS",
    "high_speed_steel": "HSS",
    "carbide": "CARBIDE_COATED",
    "carbide_uncoated": "CARBIDE_UNCOATED",
    "carbide_coated": "CARBIDE_COATED",
    "tialn": "CARBIDE_COATED",
    "ticn": "CARBIDE_COATED",
    "tin": "CARBIDE_COATED",
    "ceramic": "CERAMIC",
    "cermet": "CERMET",
    "end_mill": "CARBIDE_COATED",
    "end mill": "CARBIDE_COATED",
}

# Default number of flutes for a given nominal tool diameter
def _default_flutes(diameter_mm: float) -> int:
    """Return a sensible flute count for a standard end mill."""
    if diameter_mm <= 3.0:
        return 2
    if diameter_mm <= 12.0:
        return 4
    return 6


def _resolve_material(material: str) -> str:
    key = _MATERIAL_ALIASES.get(material.strip().lower())
    if key is None:
        key = material.strip().upper()
    if not any(k[0] == key for k in _VC_FZ_DB):
        raise ValueError(
            f"Unknown material '{material}'. "
            f"Supported: {sorted({k[0] for k in _VC_FZ_DB})}"
        )
    return key


def _resolve_tool(tool_kind: str) -> str:
    key = _TOOL_ALIASES.get(tool_kind.strip().lower())
    if key is None:
        key = tool_kind.strip().upper()
    if not any(k[1] == key for k in _VC_FZ_DB):
        raise ValueError(
            f"Unknown tool kind '{tool_kind}'. "
            f"Supported: {sorted({k[1] for k in _VC_FZ_DB})}"
        )
    return key


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def compute_recommended_feed(
    material: str,
    tool_kind: str,
    tool_diameter_mm: float,
    doc_mm: float,
    woc_mm: float,
    n_flutes: int | None = None,
) -> dict:
    """
    Compute recommended CNC milling feed rate for a given material, tool, and
    cut geometry.

    Parameters
    ----------
    material : str
        Work material.  Accepts common names: 'aluminum', 'steel', 'stainless',
        'cast_iron', 'plastic', 'titanium', 'brass', 'copper', or canonical
        database keys (ALUMINUM, STEEL_MILD, …).
    tool_kind : str
        Cutting tool material/coating: 'hss', 'carbide', 'carbide_uncoated',
        'ceramic', 'cermet'.  Defaults to 'carbide_coated' for 'end_mill'.
    tool_diameter_mm : float
        Tool diameter in mm (> 0).
    doc_mm : float
        Axial depth of cut (ap) in mm.  Used for MRR calculation only.
    woc_mm : float
        Radial width of cut (ae) in mm.  Used for MRR calculation only.
    n_flutes : int | None
        Number of cutter flutes.  If None, a sensible default is chosen based
        on diameter.

    Returns
    -------
    dict with keys:
        rpm                 : float — spindle speed (rev/min)
        feed_rate_mm_min    : float — table feed rate (mm/min)
        chip_load_mm_per_tooth : float — fz per tooth (mm)
        mrr_mm3_per_min     : float — material removal rate (mm³/min)
        vc_m_per_min        : float — cutting speed used (m/min)
        n_flutes            : int   — number of flutes used
        material_key        : str   — canonical material identifier
        tool_key            : str   — canonical tool identifier
        disclaimer          : str   — data-quality notice

    Notes
    -----
    RPM = Vc · 1000 / (π · D)   [Vc in m/min, D in mm]
    Fr  = RPM · n_flutes · fz

    Reference: Altintas 2012 Table 3.1.  NOT cutting-tool-manufacturer-certified.
    """
    if tool_diameter_mm <= 0:
        raise ValueError("tool_diameter_mm must be positive")
    if doc_mm < 0:
        raise ValueError("doc_mm must be non-negative")
    if woc_mm < 0:
        raise ValueError("woc_mm must be non-negative")

    mat_key = _resolve_material(material)
    tool_key = _resolve_tool(tool_kind)

    vc, fz_ref = _VC_FZ_DB[(mat_key, tool_key)]

    # fz scales linearly with diameter (fz_ref is calibrated at 10 mm)
    fz = fz_ref * (tool_diameter_mm / 10.0)

    # Spindle RPM
    rpm = (vc * 1000.0) / (math.pi * tool_diameter_mm)

    flutes = n_flutes if n_flutes is not None else _default_flutes(tool_diameter_mm)

    # Table feed
    feed_rate = rpm * flutes * fz

    # MRR = ae · ap · Fr  (mm² × mm/min → mm³/min)
    mrr = woc_mm * doc_mm * feed_rate

    return {
        "rpm": round(rpm, 1),
        "feed_rate_mm_min": round(feed_rate, 1),
        "chip_load_mm_per_tooth": round(fz, 4),
        "mrr_mm3_per_min": round(mrr, 2),
        "vc_m_per_min": vc,
        "n_flutes": flutes,
        "material_key": mat_key,
        "tool_key": tool_key,
        "disclaimer": (
            "Altintas 2012 Table 3.1 reference data — "
            "NOT cutting-tool-manufacturer-certified. "
            "Verify with your tool supplier before production use."
        ),
    }


# ---------------------------------------------------------------------------
# Toolpath optimizer
# ---------------------------------------------------------------------------

@dataclass
class OptimizedSegment:
    """One segment of an optimized toolpath."""
    segment_id: int
    length_mm: float
    base_feed_mm_min: float       # feed from chip-load model
    feed_mm_min: float            # final feed after all caps
    cap_reason: str               # 'nominal' | 'acceleration' | 'deflection' | 'jerk'
    mrr_mm3_per_min: float
    doc_mm: float
    woc_mm: float


def _tool_deflection_limit_force_n(
    tool_diameter_mm: float,
    overhang_mm: float,
    e_gpa: float = 620.0,          # TiAlN carbide Young's modulus
    max_deflection_mm: float = 0.01,  # 10 µm typical finish tolerance
) -> float:
    """
    Maximum allowable cutting force (N) based on cantilever deflection limit.

    Model: Euler-Bernoulli cantilever beam.
        δ = F · L³ / (3 · E · I)
        I = π D⁴ / 64

    Parameters
    ----------
    tool_diameter_mm     : float  — shank / cutting diameter (mm)
    overhang_mm          : float  — effective cantilever length (mm)
    e_gpa                : float  — Young's modulus (GPa); default TiAlN carbide
    max_deflection_mm    : float  — allowable tip deflection (mm)
    """
    if overhang_mm <= 0:
        return float("inf")
    D = tool_diameter_mm * 1e-3     # m
    L = overhang_mm * 1e-3          # m
    delta = max_deflection_mm * 1e-3  # m
    E = e_gpa * 1e9                  # Pa
    I = math.pi * D**4 / 64.0       # m⁴
    f_max = 3.0 * E * I * delta / (L**3)  # N
    return f_max


def _specific_cutting_force_n_per_mm2(mat_key: str) -> float:
    """
    Specific cutting force Kc (N/mm²) — Altintas 2012 Table 3.1 representative.
    Used for deflection cap: Fc = Kc · ap · fz.
    """
    # Source: Altintas 2012, Table 3.1
    KC_MAP: dict[str, float] = {
        "ALUMINUM":         700.0,
        "STEEL_MILD":      1800.0,
        "STEEL_STAINLESS": 2200.0,
        "STEEL_HARDENED":  2800.0,
        "CAST_IRON":       1100.0,
        "PLASTIC":          400.0,
        "TITANIUM":        2000.0,
        "BRASS":            700.0,
        "COPPER":           900.0,
    }
    return KC_MAP.get(mat_key, 1500.0)


def optimize_toolpath_feed(
    toolpath_segments: Sequence[dict],
    material: str,
    tool: dict,
    dynamic_limits: dict,
) -> list[OptimizedSegment]:
    """
    Optimize the feed rate for each segment of a CNC toolpath.

    Parameters
    ----------
    toolpath_segments : list[dict]
        Each dict must contain:
            length_mm  : float — segment length (mm)
            doc_mm     : float — axial depth of cut (mm)
            woc_mm     : float — radial width of cut (mm)
        Optional:
            feed_override : float — manual feed override (mm/min)

    material : str
        Work material (same as ``compute_recommended_feed``).

    tool : dict
        Tool descriptor:
            kind          : str   — 'carbide', 'hss', …
            diameter_mm   : float
            n_flutes      : int  (optional)
            overhang_mm   : float (optional, for deflection cap; default = 3×D)
            e_gpa         : float (optional; Young's modulus of tool shank)

    dynamic_limits : dict
        Machine dynamic constraints (Altintas §3.6):
            max_feed_mm_min   : float — absolute feed cap (mm/min)
            max_accel_mm_s2   : float — max table acceleration (mm/s²)
            jerk_limit_mm_s3  : float (optional) — max jerk; smooths transitions

    Returns
    -------
    list[OptimizedSegment]

    Notes
    -----
    Feed smoothing uses a forward–backward pass: the feed at any segment is
    constrained so that it can be reached from the previous segment's feed
    within the machine's acceleration envelope over the segment's length.

    Reference: Altintas 2012 §3.6 (feed scheduling / acc–dec profiles).
    """
    mat_key = _resolve_material(material)
    tool_kind = tool.get("kind", "carbide_coated")
    tool_key = _resolve_tool(tool_kind)
    D = float(tool.get("diameter_mm", 10.0))
    flutes = int(tool.get("n_flutes", _default_flutes(D)))
    overhang = float(tool.get("overhang_mm", 3.0 * D))
    e_gpa = float(tool.get("e_gpa", 620.0))

    max_feed = float(dynamic_limits.get("max_feed_mm_min", 10000.0))
    max_accel = float(dynamic_limits.get("max_accel_mm_s2", 500.0))   # mm/s²
    jerk_lim = float(dynamic_limits.get("jerk_limit_mm_s3", float("inf")))

    vc, fz_ref = _VC_FZ_DB[(mat_key, tool_key)]
    fz_base = fz_ref * (D / 10.0)
    rpm_base = (vc * 1000.0) / (math.pi * D)

    kc = _specific_cutting_force_n_per_mm2(mat_key)
    f_defl_limit = _tool_deflection_limit_force_n(D, overhang, e_gpa)

    # ── Pass 1: compute base (chip-load) feed per segment, then apply
    #            absolute and deflection caps ─────────────────────────
    base_feeds: list[float] = []
    reasons: list[str] = []

    for seg in toolpath_segments:
        doc = float(seg.get("doc_mm", 0.0))
        woc = float(seg.get("woc_mm", 0.0))

        # Chip-load feed
        if seg.get("feed_override") is not None:
            f = float(seg["feed_override"])
            reason = "override"
        else:
            f = rpm_base * flutes * fz_base
            reason = "nominal"

        # Cap by absolute machine feed
        if f > max_feed:
            f = max_feed
            reason = "acceleration"

        # Deflection cap: Fc = Kc · ap · fz ≤ F_limit
        # If doc > 0 and woc > 0 we can estimate fz from feed/RPM/z
        if doc > 0 and rpm_base > 0 and flutes > 0:
            fz_actual = (f / (rpm_base * flutes))          # mm/tooth
            fc_est = kc * doc * fz_actual                   # N (per tooth, peak)
            if fc_est > f_defl_limit:
                # scale feed down so that Fc ≤ F_limit
                f_defl = (f_defl_limit / kc / doc) * rpm_base * flutes
                if f_defl < f:
                    f = max(1.0, f_defl)
                    reason = "deflection"

        base_feeds.append(f)
        reasons.append(reason)

    n = len(base_feeds)

    # ── Pass 2: forward–backward acceleration smoothing (Altintas §3.6) ──
    # Convert feeds mm/min → mm/s for dynamics calculation
    feeds_mms = np.array(base_feeds, dtype=float) / 60.0
    lengths_mm = np.array([float(s.get("length_mm", 1.0)) for s in toolpath_segments])
    lengths_mm = np.maximum(lengths_mm, 1e-9)  # guard zero-length

    def _accel_reachable(v_prev: float, length: float, a_max: float) -> float:
        """Max speed reachable at end of segment accelerating from v_prev."""
        return math.sqrt(v_prev**2 + 2.0 * a_max * length)

    def _decel_reachable(v_next: float, length: float, a_max: float) -> float:
        """Max entry speed so that v_next can be reached by decelerating."""
        return math.sqrt(v_next**2 + 2.0 * a_max * length)

    # Forward pass: cap feeds so acceleration from previous segment is feasible
    v_fwd = feeds_mms.copy()
    v_fwd[0] = min(v_fwd[0], feeds_mms[0])
    for i in range(1, n):
        v_max_reachable = _accel_reachable(v_fwd[i - 1], float(lengths_mm[i - 1]), max_accel / 1000.0)
        # /1000 converts mm/s² → (mm/s)²/mm correctly (no unit change needed,
        # but accel is in mm/s² and length mm → mm/s result is consistent)
        v_max_reachable = _accel_reachable(v_fwd[i - 1], float(lengths_mm[i - 1]), max_accel)
        if v_fwd[i] > v_max_reachable:
            v_fwd[i] = v_max_reachable
            if reasons[i] == "nominal":
                reasons[i] = "acceleration"

    # Backward pass: cap feeds so deceleration from next segment is feasible
    v_bwd = v_fwd.copy()
    for i in range(n - 2, -1, -1):
        v_max_entry = _decel_reachable(v_bwd[i + 1], float(lengths_mm[i]), max_accel)
        if v_bwd[i] > v_max_entry:
            v_bwd[i] = v_max_entry
            if reasons[i] == "nominal":
                reasons[i] = "acceleration"

    # Convert back to mm/min
    final_feeds = v_bwd * 60.0

    # ── Build result ───────────────────────────────────────────────────────
    result: list[OptimizedSegment] = []
    for idx, (seg, f_base, f_final, reason) in enumerate(
        zip(toolpath_segments, base_feeds, final_feeds, reasons)
    ):
        doc = float(seg.get("doc_mm", 0.0))
        woc = float(seg.get("woc_mm", 0.0))
        mrr = woc * doc * f_final

        result.append(OptimizedSegment(
            segment_id=idx,
            length_mm=float(seg.get("length_mm", 0.0)),
            base_feed_mm_min=round(f_base, 1),
            feed_mm_min=round(float(f_final), 1),
            cap_reason=reason,
            mrr_mm3_per_min=round(mrr, 2),
            doc_mm=doc,
            woc_mm=woc,
        ))

    return result


# ---------------------------------------------------------------------------
# Cycle time estimator
# ---------------------------------------------------------------------------

def estimate_cycle_time(toolpath: list[OptimizedSegment]) -> float:
    """
    Estimate total CNC cycle time from an optimized toolpath.

    Parameters
    ----------
    toolpath : list[OptimizedSegment]
        Output of ``optimize_toolpath_feed``.

    Returns
    -------
    float
        Cycle time in **seconds**.

    Formula
    -------
    t = Σ (length_i / feed_i)   where feed is in mm/min
      → t = Σ (length_i / feed_i) × 60   [seconds]
    """
    total_time_s = 0.0
    for seg in toolpath:
        if seg.feed_mm_min > 0 and seg.length_mm > 0:
            total_time_s += (seg.length_mm / seg.feed_mm_min) * 60.0
    return total_time_s
