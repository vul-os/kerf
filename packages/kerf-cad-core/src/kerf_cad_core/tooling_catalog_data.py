"""
kerf_cad_core.tooling_catalog_data — Embedded manufacturing tooling catalog (~50 tools).

Covers: end mills, drills, taps, reamers, turning inserts from Sandvik Coromant,
Iscar, Kennametal, OSG, and Tungaloy.

HONEST FLAG
-----------
This is a curated static sample (~50 tools) for illustration and first-approximation
tooling match. It is NOT a live manufacturer product database and does NOT replace
Sandvik CoroPlus, Iscar ITA, Kennametal NOVO, or OSG e-Catalog. Speeds/feeds are
representative mid-range starting points derived from:

  - Sandvik Coromant "Cutting Data Recommendations" (2024 ed.)
  - Drozda, T.J. & Wick, C. "Tool and Manufacturing Engineers Handbook" §3 (SME, 4th ed.)

Real application data depends on machine rigidity, coolant, workholding, and run-in
conditions. Apply a ±20% tolerance to all speed/feed values.

Author: imranparuk
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FeedSpeedEntry:
    """Speed/feed recommendation for a (tool, workpiece_material) pair.

    References
    ----------
    Sandvik Coromant "Cutting Data Recommendations" (2024); Drozda-Wick §3.
    """
    workpiece_material: str           # e.g. "aluminium_6061", "steel_mild", "stainless_304"
    speed_sfm: float                  # Surface feet per minute
    speed_m_min: float                # m/min (informational)
    feed_ipt: float                   # Inches per tooth (or per rev for drills/reamers/taps)
    feed_mm_rev: float                # mm/tooth (or mm/rev)
    depth_of_cut_mm: float            # Recommended axial depth (mm)
    radial_doc_mm: Optional[float]    # Radial depth (mm); None for turning/drilling
    notes: str = ""


@dataclass
class CatalogTool:
    """One tool entry in the embedded catalog.

    References
    ----------
    Sandvik Coromant product catalog (2024); Drozda-Wick §3-1..§3-7.
    """
    tool_id: str                      # Manufacturer part number / catalog ID
    manufacturer: str                 # e.g. "Sandvik", "Iscar", "Kennametal", "OSG", "Tungaloy"
    tool_type: str                    # "end_mill", "drill", "tap", "reamer", "insert"
    diameter_mm: float                # Nominal diameter (mm); for inserts: nose radius mm
    material: str                     # "carbide", "hss", "coated_carbide", "ceramic", "cermet"
    coating: Optional[str]            # "AlTiN", "TiN", "TiAlN", "TiSiN", "uncoated", None
    flutes: Optional[int]             # Number of flutes/teeth; None for inserts
    description: str                  # Short human-readable label
    workpiece_materials: List[str]    # Supported workpiece materials (normalised keys)
    feed_speeds: List[FeedSpeedEntry] # Speed/feed per workpiece material
    tags: List[str] = field(default_factory=list)   # e.g. ["slot", "finishing", "roughing"]


# ---------------------------------------------------------------------------
# Normalised workpiece-material keys
# ---------------------------------------------------------------------------
# Keys used in workpiece_materials and FeedSpeedEntry.workpiece_material.
# These map user-supplied strings via MATERIAL_ALIASES below.

MATERIAL_ALIASES: Dict[str, str] = {
    # Aluminium variants
    "aluminium": "aluminium_6061",
    "aluminum": "aluminium_6061",
    "al": "aluminium_6061",
    "al6061": "aluminium_6061",
    "aluminium 6061": "aluminium_6061",
    "aluminum 6061": "aluminium_6061",
    "al7075": "aluminium_7075",
    "aluminium 7075": "aluminium_7075",
    "aluminum 7075": "aluminium_7075",
    # Steel variants
    "mild steel": "steel_mild",
    "low carbon steel": "steel_mild",
    "steel": "steel_mild",
    "1018": "steel_mild",
    "4140": "steel_alloy",
    "alloy steel": "steel_alloy",
    "steel alloy": "steel_alloy",
    "tool steel": "steel_tool",
    "d2": "steel_tool",
    "h13": "steel_tool",
    # Stainless
    "stainless": "stainless_304",
    "ss": "stainless_304",
    "304": "stainless_304",
    "316": "stainless_316",
    # Titanium
    "titanium": "titanium_ti6al4v",
    "ti": "titanium_ti6al4v",
    "ti6al4v": "titanium_ti6al4v",
    "ti-6al-4v": "titanium_ti6al4v",
    # Inconel
    "inconel": "inconel_718",
    "inconel 718": "inconel_718",
    # Copper / brass
    "copper": "copper_c110",
    "brass": "brass_360",
    # Plastics
    "plastic": "plastic_general",
    "abs": "plastic_general",
    "nylon": "plastic_general",
    "delrin": "plastic_general",
    # Cast iron
    "cast iron": "cast_iron_grey",
    "grey cast iron": "cast_iron_grey",
    "gray cast iron": "cast_iron_grey",
}


def normalise_material(raw: str) -> str:
    """Return canonical material key from user-supplied string."""
    key = raw.strip().lower()
    return MATERIAL_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Catalog — End Mills
# ---------------------------------------------------------------------------

_END_MILLS: List[CatalogTool] = [
    # ── Sandvik CoroMill Plura ø0.5 mm (micro end mill, 2-flute)
    CatalogTool(
        tool_id="R216.32-00502-AC10G",
        manufacturer="Sandvik",
        tool_type="end_mill",
        diameter_mm=0.5,
        material="coated_carbide",
        coating="AlTiN",
        flutes=2,
        description="Sandvik CoroMill Plura ø0.5 mm 2-fl solid carbide end mill (AlTiN)",
        workpiece_materials=["aluminium_6061", "aluminium_7075", "steel_mild", "steel_alloy"],
        feed_speeds=[
            FeedSpeedEntry("aluminium_6061", speed_sfm=400, speed_m_min=122, feed_ipt=0.0001,
                           feed_mm_rev=0.0025, depth_of_cut_mm=0.5, radial_doc_mm=0.1,
                           notes="Sandvik Cutting Data Rec. 2024 micro-milling Al; SFM=400"),
            FeedSpeedEntry("steel_mild",    speed_sfm=120, speed_m_min=37,  feed_ipt=0.00005,
                           feed_mm_rev=0.0013, depth_of_cut_mm=0.3, radial_doc_mm=0.05,
                           notes="Drozda-Wick §3-4 micro end mill mild steel"),
        ],
        tags=["slot", "micro", "finishing"],
    ),
    # ── Sandvik CoroMill Plura ø1.0 mm
    CatalogTool(
        tool_id="R216.32-01030-AC22G",
        manufacturer="Sandvik",
        tool_type="end_mill",
        diameter_mm=1.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=2,
        description="Sandvik CoroMill Plura ø1.0 mm 2-fl solid carbide end mill",
        workpiece_materials=["aluminium_6061", "aluminium_7075", "steel_mild", "steel_alloy", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("aluminium_6061", speed_sfm=600, speed_m_min=183, feed_ipt=0.0002,
                           feed_mm_rev=0.005, depth_of_cut_mm=1.0, radial_doc_mm=0.2,
                           notes="Sandvik Cutting Data Rec. 2024 CoroMill Plura ø1 Al"),
            FeedSpeedEntry("steel_mild",    speed_sfm=200, speed_m_min=61,  feed_ipt=0.0001,
                           feed_mm_rev=0.0025, depth_of_cut_mm=0.5, radial_doc_mm=0.1,
                           notes="Drozda-Wick §3-4"),
            FeedSpeedEntry("stainless_304", speed_sfm=130, speed_m_min=40,  feed_ipt=0.00008,
                           feed_mm_rev=0.002, depth_of_cut_mm=0.5, radial_doc_mm=0.1),
        ],
        tags=["slot", "finishing"],
    ),
    # ── Sandvik CoroMill Plura ø3.0 mm
    CatalogTool(
        tool_id="R216.32-03030-AC26P",
        manufacturer="Sandvik",
        tool_type="end_mill",
        diameter_mm=3.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=3,
        description="Sandvik CoroMill Plura ø3 mm 3-fl solid carbide end mill",
        workpiece_materials=["aluminium_6061", "steel_mild", "stainless_304", "steel_alloy"],
        feed_speeds=[
            FeedSpeedEntry("aluminium_6061", speed_sfm=800, speed_m_min=244, feed_ipt=0.0008,
                           feed_mm_rev=0.020, depth_of_cut_mm=3.0, radial_doc_mm=1.5),
            FeedSpeedEntry("steel_mild",    speed_sfm=250, speed_m_min=76,  feed_ipt=0.0004,
                           feed_mm_rev=0.010, depth_of_cut_mm=1.5, radial_doc_mm=0.75),
            FeedSpeedEntry("stainless_304", speed_sfm=160, speed_m_min=49,  feed_ipt=0.0003,
                           feed_mm_rev=0.008, depth_of_cut_mm=1.5, radial_doc_mm=0.5),
        ],
        tags=["slot", "roughing"],
    ),
    # ── Sandvik CoroMill Plura ø6 mm 4-fl
    CatalogTool(
        tool_id="R216.32-06030-AC32P",
        manufacturer="Sandvik",
        tool_type="end_mill",
        diameter_mm=6.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=4,
        description="Sandvik CoroMill Plura ø6 mm 4-fl solid carbide end mill",
        workpiece_materials=["aluminium_6061", "steel_mild", "stainless_304", "steel_alloy", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("aluminium_6061", speed_sfm=1200, speed_m_min=366, feed_ipt=0.0025,
                           feed_mm_rev=0.064, depth_of_cut_mm=6.0, radial_doc_mm=3.0),
            FeedSpeedEntry("steel_mild",    speed_sfm=300,  speed_m_min=91,  feed_ipt=0.001,
                           feed_mm_rev=0.025, depth_of_cut_mm=3.0, radial_doc_mm=1.5),
            FeedSpeedEntry("stainless_304", speed_sfm=200,  speed_m_min=61,  feed_ipt=0.0008,
                           feed_mm_rev=0.020, depth_of_cut_mm=3.0, radial_doc_mm=1.0),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=350,  speed_m_min=107, feed_ipt=0.0015,
                           feed_mm_rev=0.038, depth_of_cut_mm=3.0, radial_doc_mm=1.5),
        ],
        tags=["slot", "roughing", "finishing"],
    ),
    # ── Sandvik CoroMill Plura ø10 mm 4-fl
    CatalogTool(
        tool_id="R216.32-10030-AC38P",
        manufacturer="Sandvik",
        tool_type="end_mill",
        diameter_mm=10.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=4,
        description="Sandvik CoroMill Plura ø10 mm 4-fl solid carbide end mill",
        workpiece_materials=["aluminium_6061", "steel_mild", "stainless_304", "steel_alloy", "titanium_ti6al4v"],
        feed_speeds=[
            FeedSpeedEntry("aluminium_6061",    speed_sfm=1500, speed_m_min=457, feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=10.0, radial_doc_mm=5.0),
            FeedSpeedEntry("steel_mild",        speed_sfm=350,  speed_m_min=107, feed_ipt=0.0015,
                           feed_mm_rev=0.038, depth_of_cut_mm=5.0, radial_doc_mm=2.5),
            FeedSpeedEntry("stainless_304",     speed_sfm=250,  speed_m_min=76,  feed_ipt=0.001,
                           feed_mm_rev=0.025, depth_of_cut_mm=5.0, radial_doc_mm=1.5),
            FeedSpeedEntry("titanium_ti6al4v",  speed_sfm=100,  speed_m_min=30,  feed_ipt=0.0008,
                           feed_mm_rev=0.020, depth_of_cut_mm=5.0, radial_doc_mm=1.0,
                           notes="Ti: use flood coolant; Drozda-Wick §3-5 Ti"),
        ],
        tags=["slot", "roughing"],
    ),
    # ── Iscar EA 90 MULTI-MASTER ø12 mm
    CatalogTool(
        tool_id="ISCAR-ECK90-12-2CF-IC908",
        manufacturer="Iscar",
        tool_type="end_mill",
        diameter_mm=12.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=4,
        description="Iscar MULTI-MASTER ECK90-12 ø12 mm 4-fl end mill IC908",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",     speed_sfm=400, speed_m_min=122, feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=6.0, radial_doc_mm=3.0),
            FeedSpeedEntry("steel_alloy",    speed_sfm=320, speed_m_min=98,  feed_ipt=0.0015,
                           feed_mm_rev=0.038, depth_of_cut_mm=6.0, radial_doc_mm=2.5),
            FeedSpeedEntry("stainless_304",  speed_sfm=220, speed_m_min=67,  feed_ipt=0.0012,
                           feed_mm_rev=0.030, depth_of_cut_mm=5.0, radial_doc_mm=2.0),
            FeedSpeedEntry("cast_iron_grey", speed_sfm=450, speed_m_min=137, feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=6.0, radial_doc_mm=3.0),
        ],
        tags=["slot", "roughing"],
    ),
    # ── OSG EX-HL-EMS ø16 mm high-helix Al
    CatalogTool(
        tool_id="OSG-EX-HL-EMS16",
        manufacturer="OSG",
        tool_type="end_mill",
        diameter_mm=16.0,
        material="coated_carbide",
        coating="TiN",
        flutes=3,
        description="OSG EX-HL-EMS ø16 mm 3-fl high-helix aluminium end mill",
        workpiece_materials=["aluminium_6061", "aluminium_7075", "plastic_general"],
        feed_speeds=[
            FeedSpeedEntry("aluminium_6061",  speed_sfm=1800, speed_m_min=549, feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=16.0, radial_doc_mm=4.0,
                           notes="OSG Al high-helix; high-speed strategy"),
            FeedSpeedEntry("aluminium_7075",  speed_sfm=2000, speed_m_min=610, feed_ipt=0.007,
                           feed_mm_rev=0.178, depth_of_cut_mm=16.0, radial_doc_mm=4.0),
            FeedSpeedEntry("plastic_general", speed_sfm=1000, speed_m_min=305, feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=16.0, radial_doc_mm=4.0),
        ],
        tags=["slot", "roughing", "aluminium"],
    ),
    # ── Kennametal HARVI I ø20 mm
    CatalogTool(
        tool_id="KMT-B218A200Z4CF-KC643M",
        manufacturer="Kennametal",
        tool_type="end_mill",
        diameter_mm=20.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=4,
        description="Kennametal HARVI I ø20 mm 4-fl solid carbide end mill KC643M",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",     speed_sfm=450, speed_m_min=137, feed_ipt=0.003,
                           feed_mm_rev=0.076, depth_of_cut_mm=10.0, radial_doc_mm=5.0),
            FeedSpeedEntry("steel_alloy",    speed_sfm=350, speed_m_min=107, feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=10.0, radial_doc_mm=4.0),
            FeedSpeedEntry("stainless_304",  speed_sfm=250, speed_m_min=76,  feed_ipt=0.0015,
                           feed_mm_rev=0.038, depth_of_cut_mm=8.0,  radial_doc_mm=3.0),
            FeedSpeedEntry("cast_iron_grey", speed_sfm=500, speed_m_min=152, feed_ipt=0.003,
                           feed_mm_rev=0.076, depth_of_cut_mm=10.0, radial_doc_mm=5.0),
        ],
        tags=["roughing", "finishing"],
    ),
    # ── Tungaloy TungMill ø25 mm
    CatalogTool(
        tool_id="TUNG-TEM25L25.0A-02",
        manufacturer="Tungaloy",
        tool_type="end_mill",
        diameter_mm=25.0,
        material="coated_carbide",
        coating="TiSiN",
        flutes=4,
        description="Tungaloy TungMill ø25 mm 4-fl solid carbide end mill",
        workpiece_materials=["steel_mild", "steel_alloy", "cast_iron_grey", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",     speed_sfm=500, speed_m_min=152, feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=12.0, radial_doc_mm=6.0),
            FeedSpeedEntry("cast_iron_grey", speed_sfm=600, speed_m_min=183, feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=12.0, radial_doc_mm=6.0),
            FeedSpeedEntry("stainless_304",  speed_sfm=280, speed_m_min=85,  feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=10.0, radial_doc_mm=4.0),
        ],
        tags=["roughing"],
    ),
]


# ---------------------------------------------------------------------------
# Catalog — Drills
# ---------------------------------------------------------------------------

_DRILLS: List[CatalogTool] = [
    # ── Sandvik CoroDrill ø3.3 mm (M4 tap drill)
    CatalogTool(
        tool_id="870-0330-3T-MM",
        manufacturer="Sandvik",
        tool_type="drill",
        diameter_mm=3.3,
        material="coated_carbide",
        coating="TiN",
        flutes=2,
        description="Sandvik CoroDrill 870 ø3.3 mm (M4 tap drill) solid carbide",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=250, speed_m_min=76,  feed_ipt=0.003,
                           feed_mm_rev=0.076, depth_of_cut_mm=3.3, radial_doc_mm=None,
                           notes="Sandvik CoroDrill 870 steel baseline"),
            FeedSpeedEntry("aluminium_6061",speed_sfm=600, speed_m_min=183, feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=3.3, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=150, speed_m_min=46,  feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=3.3, radial_doc_mm=None),
        ],
        tags=["drill", "tap_prep", "m4"],
    ),
    # ── Sandvik CoroDrill ø5.0 mm (M6 tap drill)
    CatalogTool(
        tool_id="870-0500-5T-MM",
        manufacturer="Sandvik",
        tool_type="drill",
        diameter_mm=5.0,
        material="coated_carbide",
        coating="TiN",
        flutes=2,
        description="Sandvik CoroDrill 870 ø5.0 mm (M6 tap drill) solid carbide",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304", "aluminium_6061", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=250, speed_m_min=76,  feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=5.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=700, speed_m_min=213, feed_ipt=0.007,
                           feed_mm_rev=0.178, depth_of_cut_mm=5.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=160, speed_m_min=49,  feed_ipt=0.003,
                           feed_mm_rev=0.076, depth_of_cut_mm=5.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=350, speed_m_min=107, feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=5.0, radial_doc_mm=None),
        ],
        tags=["drill", "tap_prep", "m6"],
    ),
    # ── Sandvik CoroDrill 870 ø6.8 mm (M8 tap drill) — depth-bar reference
    CatalogTool(
        tool_id="870-0680-6T-MM",
        manufacturer="Sandvik",
        tool_type="drill",
        diameter_mm=6.8,
        material="coated_carbide",
        coating="TiN",
        flutes=2,
        description="Sandvik CoroDrill 870 ø6.8 mm (M8 tap drill) solid carbide",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304", "aluminium_6061", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=180, speed_m_min=55,  feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=6.8, radial_doc_mm=None,
                           notes="Sandvik CoroDrill 870 data sheet M8 tap drill; Drozda-Wick §3-3"),
            FeedSpeedEntry("steel_alloy",   speed_sfm=150, speed_m_min=46,  feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=6.8, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=700, speed_m_min=213, feed_ipt=0.009,
                           feed_mm_rev=0.229, depth_of_cut_mm=6.8, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=130, speed_m_min=40,  feed_ipt=0.003,
                           feed_mm_rev=0.076, depth_of_cut_mm=6.8, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=300, speed_m_min=91,  feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=6.8, radial_doc_mm=None),
        ],
        tags=["drill", "tap_prep", "m8"],
    ),
    # ── Sandvik CoroDrill ø8.5 mm (M10 tap drill)
    CatalogTool(
        tool_id="870-0850-6T-MM",
        manufacturer="Sandvik",
        tool_type="drill",
        diameter_mm=8.5,
        material="coated_carbide",
        coating="TiN",
        flutes=2,
        description="Sandvik CoroDrill 870 ø8.5 mm (M10 tap drill) solid carbide",
        workpiece_materials=["steel_mild", "stainless_304", "aluminium_6061", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=200, speed_m_min=61,  feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=8.5, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=800, speed_m_min=244, feed_ipt=0.011,
                           feed_mm_rev=0.279, depth_of_cut_mm=8.5, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=140, speed_m_min=43,  feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=8.5, radial_doc_mm=None),
        ],
        tags=["drill", "tap_prep", "m10"],
    ),
    # ── Iscar SUMOCHAM ø12 mm
    CatalogTool(
        tool_id="ISCAR-ICP120-IC908",
        manufacturer="Iscar",
        tool_type="drill",
        diameter_mm=12.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=2,
        description="Iscar SUMOCHAM ø12 mm replaceable-tip drill IC908",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=350, speed_m_min=107, feed_ipt=0.007,
                           feed_mm_rev=0.178, depth_of_cut_mm=12.0, radial_doc_mm=None),
            FeedSpeedEntry("steel_alloy",   speed_sfm=280, speed_m_min=85,  feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=12.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=200, speed_m_min=61,  feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=12.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=450, speed_m_min=137, feed_ipt=0.008,
                           feed_mm_rev=0.203, depth_of_cut_mm=12.0, radial_doc_mm=None),
        ],
        tags=["drill", "roughing"],
    ),
    # ── OSG WX-DS ø4.2 mm (M5 tap drill)
    CatalogTool(
        tool_id="OSG-WX-DS-4.2",
        manufacturer="OSG",
        tool_type="drill",
        diameter_mm=4.2,
        material="coated_carbide",
        coating="TiN",
        flutes=2,
        description="OSG WX-DS ø4.2 mm (M5 tap drill) solid carbide",
        workpiece_materials=["steel_mild", "aluminium_6061", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=230, speed_m_min=70,  feed_ipt=0.003,
                           feed_mm_rev=0.076, depth_of_cut_mm=4.2, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=650, speed_m_min=198, feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=4.2, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=140, speed_m_min=43,  feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=4.2, radial_doc_mm=None),
        ],
        tags=["drill", "tap_prep", "m5"],
    ),
    # ── Kennametal B2CL HSS ø6.0 mm
    CatalogTool(
        tool_id="KMT-B2CL-6.0",
        manufacturer="Kennametal",
        tool_type="drill",
        diameter_mm=6.0,
        material="hss",
        coating="TiN",
        flutes=2,
        description="Kennametal B2CL ø6.0 mm HSS-E TiN coated drill",
        workpiece_materials=["steel_mild", "aluminium_6061", "plastic_general"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=80,  speed_m_min=24,  feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=6.0, radial_doc_mm=None,
                           notes="HSS drill; Drozda-Wick §3-2 HSS starting data"),
            FeedSpeedEntry("aluminium_6061",speed_sfm=300, speed_m_min=91,  feed_ipt=0.008,
                           feed_mm_rev=0.203, depth_of_cut_mm=6.0, radial_doc_mm=None),
            FeedSpeedEntry("plastic_general",speed_sfm=400, speed_m_min=122, feed_ipt=0.008,
                           feed_mm_rev=0.203, depth_of_cut_mm=6.0, radial_doc_mm=None),
        ],
        tags=["drill", "hss"],
    ),
    # ── Tungaloy TungDrill ø10 mm
    CatalogTool(
        tool_id="TUNG-SCD100Q10-02",
        manufacturer="Tungaloy",
        tool_type="drill",
        diameter_mm=10.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=2,
        description="Tungaloy TungDrill ø10 mm solid carbide drill",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=300, speed_m_min=91,  feed_ipt=0.007,
                           feed_mm_rev=0.178, depth_of_cut_mm=10.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=900, speed_m_min=274, feed_ipt=0.012,
                           feed_mm_rev=0.305, depth_of_cut_mm=10.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=180, speed_m_min=55,  feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=10.0, radial_doc_mm=None),
        ],
        tags=["drill"],
    ),
]


# ---------------------------------------------------------------------------
# Catalog — Taps
# ---------------------------------------------------------------------------

_TAPS: List[CatalogTool] = [
    # ── Sandvik CoroTap ø6 M6x1.0 forming tap
    CatalogTool(
        tool_id="E533GX-M6x1.0",
        manufacturer="Sandvik",
        tool_type="tap",
        diameter_mm=6.0,
        material="hss",
        coating="TiN",
        flutes=0,
        description="Sandvik CoroTap 300 M6x1.0 forming tap (flute-less)",
        workpiece_materials=["steel_mild", "aluminium_6061", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=60,  speed_m_min=18,  feed_ipt=0.03937,
                           feed_mm_rev=1.0, depth_of_cut_mm=6.0, radial_doc_mm=None,
                           notes="Feed = pitch = 1.0 mm; Sandvik CoroTap forming data 2024"),
            FeedSpeedEntry("aluminium_6061",speed_sfm=120, speed_m_min=37,  feed_ipt=0.03937,
                           feed_mm_rev=1.0, depth_of_cut_mm=6.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=30,  speed_m_min=9,   feed_ipt=0.03937,
                           feed_mm_rev=1.0, depth_of_cut_mm=6.0, radial_doc_mm=None),
        ],
        tags=["tap", "forming", "m6"],
    ),
    # ── Sandvik CoroTap ø8 M8x1.25 cutting tap
    CatalogTool(
        tool_id="E530GX-M8x1.25",
        manufacturer="Sandvik",
        tool_type="tap",
        diameter_mm=8.0,
        material="hss",
        coating="TiN",
        flutes=3,
        description="Sandvik CoroTap 100 M8x1.25 3-flute cutting tap",
        workpiece_materials=["steel_mild", "aluminium_6061", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=50,  speed_m_min=15,  feed_ipt=0.04921,
                           feed_mm_rev=1.25, depth_of_cut_mm=8.0, radial_doc_mm=None,
                           notes="Feed = pitch = 1.25 mm; Sandvik CoroTap 100 data 2024"),
            FeedSpeedEntry("aluminium_6061",speed_sfm=100, speed_m_min=30,  feed_ipt=0.04921,
                           feed_mm_rev=1.25, depth_of_cut_mm=8.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=60,  speed_m_min=18,  feed_ipt=0.04921,
                           feed_mm_rev=1.25, depth_of_cut_mm=8.0, radial_doc_mm=None),
        ],
        tags=["tap", "cutting", "m8"],
    ),
    # ── OSG UH-TAP M5x0.8 HSSE
    CatalogTool(
        tool_id="OSG-UH-TAP-M5x0.8",
        manufacturer="OSG",
        tool_type="tap",
        diameter_mm=5.0,
        material="hss",
        coating="TiN",
        flutes=3,
        description="OSG HSSE UH-TAP M5x0.8 universal cutting tap",
        workpiece_materials=["steel_mild", "aluminium_6061", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=40,  speed_m_min=12,  feed_ipt=0.03150,
                           feed_mm_rev=0.8, depth_of_cut_mm=5.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=100, speed_m_min=30,  feed_ipt=0.03150,
                           feed_mm_rev=0.8, depth_of_cut_mm=5.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=20,  speed_m_min=6,   feed_ipt=0.03150,
                           feed_mm_rev=0.8, depth_of_cut_mm=5.0, radial_doc_mm=None,
                           notes="Stainless tapping: use quality tapping fluid"),
        ],
        tags=["tap", "cutting", "m5"],
    ),
    # ── Kennametal KMT-TAP M10x1.5 spiral-point
    CatalogTool(
        tool_id="KMT-TAP-M10x1.5-SP",
        manufacturer="Kennametal",
        tool_type="tap",
        diameter_mm=10.0,
        material="hss",
        coating="TiN",
        flutes=3,
        description="Kennametal spiral-point M10x1.5 tap (gun tap, through holes)",
        workpiece_materials=["steel_mild", "steel_alloy", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=55,  speed_m_min=17,  feed_ipt=0.05906,
                           feed_mm_rev=1.5, depth_of_cut_mm=10.0, radial_doc_mm=None),
            FeedSpeedEntry("steel_alloy",   speed_sfm=40,  speed_m_min=12,  feed_ipt=0.05906,
                           feed_mm_rev=1.5, depth_of_cut_mm=10.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=120, speed_m_min=37,  feed_ipt=0.05906,
                           feed_mm_rev=1.5, depth_of_cut_mm=10.0, radial_doc_mm=None),
        ],
        tags=["tap", "m10", "through_hole"],
    ),
    # ── Iscar IQ-110 M12x1.75
    CatalogTool(
        tool_id="ISCAR-TAP-M12x1.75-HSSE",
        manufacturer="Iscar",
        tool_type="tap",
        diameter_mm=12.0,
        material="hss",
        coating="TiAlN",
        flutes=4,
        description="Iscar HSSE M12x1.75 spiral-flute tap",
        workpiece_materials=["steel_mild", "stainless_304", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=55,  speed_m_min=17,  feed_ipt=0.06890,
                           feed_mm_rev=1.75, depth_of_cut_mm=12.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=25,  speed_m_min=8,   feed_ipt=0.06890,
                           feed_mm_rev=1.75, depth_of_cut_mm=12.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=120, speed_m_min=37,  feed_ipt=0.06890,
                           feed_mm_rev=1.75, depth_of_cut_mm=12.0, radial_doc_mm=None),
        ],
        tags=["tap", "m12"],
    ),
]


# ---------------------------------------------------------------------------
# Catalog — Reamers
# ---------------------------------------------------------------------------

_REAMERS: List[CatalogTool] = [
    # ── Sandvik CoroBore ø6 mm reamer
    CatalogTool(
        tool_id="SAND-REAMER-6.0-H7",
        manufacturer="Sandvik",
        tool_type="reamer",
        diameter_mm=6.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=6,
        description="Sandvik solid carbide reamer ø6 mm H7 tolerance",
        workpiece_materials=["steel_mild", "aluminium_6061", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=80,  speed_m_min=24,  feed_ipt=0.008,
                           feed_mm_rev=0.203, depth_of_cut_mm=6.0, radial_doc_mm=None,
                           notes="Sandvik reamer; Drozda-Wick §3-6 reaming data; ≤0.2 mm stock"),
            FeedSpeedEntry("aluminium_6061",speed_sfm=200, speed_m_min=61,  feed_ipt=0.015,
                           feed_mm_rev=0.381, depth_of_cut_mm=6.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=100, speed_m_min=30,  feed_ipt=0.010,
                           feed_mm_rev=0.254, depth_of_cut_mm=6.0, radial_doc_mm=None),
        ],
        tags=["reamer", "finishing", "h7"],
    ),
    # ── Sandvik solid carbide reamer ø10 mm — depth-bar reference
    CatalogTool(
        tool_id="SAND-REAMER-10.0-H7",
        manufacturer="Sandvik",
        tool_type="reamer",
        diameter_mm=10.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=6,
        description="Sandvik solid carbide reamer ø10 mm H7 tolerance",
        workpiece_materials=["steel_mild", "steel_alloy", "aluminium_6061", "stainless_304", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=90,  speed_m_min=27,  feed_ipt=0.010,
                           feed_mm_rev=0.254, depth_of_cut_mm=10.0, radial_doc_mm=None,
                           notes="Sandvik reamer 2024 / Drozda-Wick §3-6"),
            FeedSpeedEntry("steel_alloy",   speed_sfm=75,  speed_m_min=23,  feed_ipt=0.009,
                           feed_mm_rev=0.229, depth_of_cut_mm=10.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=250, speed_m_min=76,  feed_ipt=0.018,
                           feed_mm_rev=0.457, depth_of_cut_mm=10.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=60,  speed_m_min=18,  feed_ipt=0.007,
                           feed_mm_rev=0.178, depth_of_cut_mm=10.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=120, speed_m_min=37,  feed_ipt=0.012,
                           feed_mm_rev=0.305, depth_of_cut_mm=10.0, radial_doc_mm=None),
        ],
        tags=["reamer", "finishing", "h7"],
    ),
    # ── Kennametal KMT adjustable reamer ø12 mm
    CatalogTool(
        tool_id="KMT-ADJ-REAMER-12.0",
        manufacturer="Kennametal",
        tool_type="reamer",
        diameter_mm=12.0,
        material="coated_carbide",
        coating="TiN",
        flutes=8,
        description="Kennametal adjustable carbide reamer ø12 mm",
        workpiece_materials=["steel_mild", "aluminium_6061", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=100, speed_m_min=30,  feed_ipt=0.012,
                           feed_mm_rev=0.305, depth_of_cut_mm=12.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=300, speed_m_min=91,  feed_ipt=0.020,
                           feed_mm_rev=0.508, depth_of_cut_mm=12.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=140, speed_m_min=43,  feed_ipt=0.014,
                           feed_mm_rev=0.356, depth_of_cut_mm=12.0, radial_doc_mm=None),
        ],
        tags=["reamer", "finishing"],
    ),
    # ── OSG carbide reamer ø8 mm
    CatalogTool(
        tool_id="OSG-VPH-REAMER-8.0",
        manufacturer="OSG",
        tool_type="reamer",
        diameter_mm=8.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=6,
        description="OSG VPH carbide reamer ø8 mm",
        workpiece_materials=["steel_mild", "aluminium_6061", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=90,  speed_m_min=27,  feed_ipt=0.009,
                           feed_mm_rev=0.229, depth_of_cut_mm=8.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=220, speed_m_min=67,  feed_ipt=0.016,
                           feed_mm_rev=0.406, depth_of_cut_mm=8.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=55,  speed_m_min=17,  feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=8.0, radial_doc_mm=None),
        ],
        tags=["reamer", "finishing"],
    ),
]


# ---------------------------------------------------------------------------
# Catalog — Turning Inserts
# ---------------------------------------------------------------------------

_INSERTS: List[CatalogTool] = [
    # ── Sandvik CNMG 120408 general turning insert
    CatalogTool(
        tool_id="CNMG120408-MR2-4225",
        manufacturer="Sandvik",
        tool_type="insert",
        diameter_mm=0.8,  # nose radius
        material="coated_carbide",
        coating="TiCN/Al2O3/TiN",
        flutes=None,
        description="Sandvik CNMG 120408-MR2 general turning insert grade 4225 (steel)",
        workpiece_materials=["steel_mild", "steel_alloy"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",  speed_sfm=700, speed_m_min=213, feed_ipt=0.012,
                           feed_mm_rev=0.305, depth_of_cut_mm=2.0, radial_doc_mm=None,
                           notes="Sandvik T-Max P CNMG 4225; Drozda-Wick §3-7 insert turning"),
            FeedSpeedEntry("steel_alloy", speed_sfm=550, speed_m_min=168, feed_ipt=0.010,
                           feed_mm_rev=0.254, depth_of_cut_mm=2.0, radial_doc_mm=None),
        ],
        tags=["insert", "turning", "external", "roughing"],
    ),
    # ── Sandvik WNMG 080408 for stainless
    CatalogTool(
        tool_id="WNMG080408-MF2-2040",
        manufacturer="Sandvik",
        tool_type="insert",
        diameter_mm=0.8,
        material="coated_carbide",
        coating="PVD-TiAlN",
        flutes=None,
        description="Sandvik WNMG 080408-MF2 insert grade 2040 (stainless/austenitic)",
        workpiece_materials=["stainless_304", "stainless_316"],
        feed_speeds=[
            FeedSpeedEntry("stainless_304", speed_sfm=400, speed_m_min=122, feed_ipt=0.008,
                           feed_mm_rev=0.203, depth_of_cut_mm=1.5, radial_doc_mm=None),
            FeedSpeedEntry("stainless_316", speed_sfm=350, speed_m_min=107, feed_ipt=0.007,
                           feed_mm_rev=0.178, depth_of_cut_mm=1.5, radial_doc_mm=None),
        ],
        tags=["insert", "turning", "stainless"],
    ),
    # ── Iscar CNMG 120408 IC8250 (cast iron)
    CatalogTool(
        tool_id="ISCAR-CNMG120408-IC8250",
        manufacturer="Iscar",
        tool_type="insert",
        diameter_mm=0.8,
        material="coated_carbide",
        coating="TiCN/Al2O3",
        flutes=None,
        description="Iscar CNMG 120408 IC8250 turning insert (cast iron / steel)",
        workpiece_materials=["cast_iron_grey", "steel_mild"],
        feed_speeds=[
            FeedSpeedEntry("cast_iron_grey",speed_sfm=1000, speed_m_min=305, feed_ipt=0.014,
                           feed_mm_rev=0.356, depth_of_cut_mm=2.5, radial_doc_mm=None),
            FeedSpeedEntry("steel_mild",    speed_sfm=700,  speed_m_min=213, feed_ipt=0.012,
                           feed_mm_rev=0.305, depth_of_cut_mm=2.0, radial_doc_mm=None),
        ],
        tags=["insert", "turning", "cast_iron"],
    ),
    # ── Kennametal TNMG 160404 KC5010 (titanium)
    CatalogTool(
        tool_id="KMT-TNMG160404-KC5010",
        manufacturer="Kennametal",
        tool_type="insert",
        diameter_mm=0.4,
        material="coated_carbide",
        coating="PVD-AlTiN",
        flutes=None,
        description="Kennametal TNMG 160404 KC5010 insert for titanium/HRSAs",
        workpiece_materials=["titanium_ti6al4v", "inconel_718"],
        feed_speeds=[
            FeedSpeedEntry("titanium_ti6al4v",speed_sfm=250, speed_m_min=76,  feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=1.5, radial_doc_mm=None,
                           notes="Ti: flood coolant mandatory; Drozda-Wick §3-5"),
            FeedSpeedEntry("inconel_718",     speed_sfm=100, speed_m_min=30,  feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=1.0, radial_doc_mm=None,
                           notes="Inconel: high-pressure coolant recommended"),
        ],
        tags=["insert", "turning", "titanium", "hrsa"],
    ),
    # ── Tungaloy TNGG 160404 for aluminium
    CatalogTool(
        tool_id="TUNG-TNGG160404-PD-PCD10",
        manufacturer="Tungaloy",
        tool_type="insert",
        diameter_mm=0.4,
        material="ceramic",
        coating=None,
        flutes=None,
        description="Tungaloy TNGG 160404 PCD10 diamond insert for aluminium finishing",
        workpiece_materials=["aluminium_6061", "aluminium_7075"],
        feed_speeds=[
            FeedSpeedEntry("aluminium_6061",speed_sfm=2500, speed_m_min=762, feed_ipt=0.008,
                           feed_mm_rev=0.203, depth_of_cut_mm=0.5, radial_doc_mm=None,
                           notes="PCD insert for mirror-finish Al turning"),
            FeedSpeedEntry("aluminium_7075",speed_sfm=3000, speed_m_min=914, feed_ipt=0.009,
                           feed_mm_rev=0.229, depth_of_cut_mm=0.5, radial_doc_mm=None),
        ],
        tags=["insert", "turning", "finishing", "pcd", "aluminium"],
    ),
    # ── Sandvik RCMT 1204 ball-nose insert (screw-on milling)
    CatalogTool(
        tool_id="R390-12T308M-PM-4240",
        manufacturer="Sandvik",
        tool_type="insert",
        diameter_mm=12.0,
        material="coated_carbide",
        coating="TiCN/Al2O3",
        flutes=None,
        description="Sandvik R390 12T308 milling insert grade 4240 (90° shoulder milling)",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",  speed_sfm=650, speed_m_min=198, feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=3.0, radial_doc_mm=None),
            FeedSpeedEntry("steel_alloy", speed_sfm=500, speed_m_min=152, feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=3.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304",speed_sfm=350, speed_m_min=107, feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=2.5, radial_doc_mm=None),
        ],
        tags=["insert", "milling", "shoulder"],
    ),
]


# ---------------------------------------------------------------------------
# Catalog — Additional End Mills (extended coverage to reach ≥50 tools)
# ---------------------------------------------------------------------------

_END_MILLS_EXT: List[CatalogTool] = [
    # ── Sandvik CoroMill Plura ø2.0 mm 2-fl
    CatalogTool(
        tool_id="R216.32-02030-AC25G",
        manufacturer="Sandvik",
        tool_type="end_mill",
        diameter_mm=2.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=2,
        description="Sandvik CoroMill Plura ø2 mm 2-fl solid carbide end mill",
        workpiece_materials=["aluminium_6061", "steel_mild", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("aluminium_6061", speed_sfm=700, speed_m_min=213, feed_ipt=0.0004,
                           feed_mm_rev=0.010, depth_of_cut_mm=2.0, radial_doc_mm=0.5),
            FeedSpeedEntry("steel_mild",     speed_sfm=180, speed_m_min=55,  feed_ipt=0.0002,
                           feed_mm_rev=0.005, depth_of_cut_mm=1.0, radial_doc_mm=0.2),
            FeedSpeedEntry("stainless_304",  speed_sfm=120, speed_m_min=37,  feed_ipt=0.00015,
                           feed_mm_rev=0.004, depth_of_cut_mm=1.0, radial_doc_mm=0.2),
        ],
        tags=["slot", "finishing"],
    ),
    # ── Iscar SOLIDMILL ø4 mm 4-fl
    CatalogTool(
        tool_id="ISCAR-ECF4-04-2T10-IC908",
        manufacturer="Iscar",
        tool_type="end_mill",
        diameter_mm=4.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=4,
        description="Iscar SolidMill ø4 mm 4-fl solid carbide end mill IC908",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=280, speed_m_min=85,  feed_ipt=0.0006,
                           feed_mm_rev=0.015, depth_of_cut_mm=2.0, radial_doc_mm=1.0),
            FeedSpeedEntry("steel_alloy",   speed_sfm=220, speed_m_min=67,  feed_ipt=0.0005,
                           feed_mm_rev=0.013, depth_of_cut_mm=2.0, radial_doc_mm=0.8),
            FeedSpeedEntry("stainless_304", speed_sfm=160, speed_m_min=49,  feed_ipt=0.0004,
                           feed_mm_rev=0.010, depth_of_cut_mm=2.0, radial_doc_mm=0.6),
        ],
        tags=["slot", "roughing"],
    ),
    # ── OSG EX-EMS ø8 mm 4-fl
    CatalogTool(
        tool_id="OSG-EX-EMS8",
        manufacturer="OSG",
        tool_type="end_mill",
        diameter_mm=8.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=4,
        description="OSG EX-EMS ø8 mm 4-fl solid carbide end mill",
        workpiece_materials=["steel_mild", "steel_alloy", "stainless_304", "titanium_ti6al4v"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",       speed_sfm=320, speed_m_min=98,  feed_ipt=0.0012,
                           feed_mm_rev=0.030, depth_of_cut_mm=4.0, radial_doc_mm=2.0),
            FeedSpeedEntry("stainless_304",    speed_sfm=200, speed_m_min=61,  feed_ipt=0.0008,
                           feed_mm_rev=0.020, depth_of_cut_mm=4.0, radial_doc_mm=1.5),
            FeedSpeedEntry("titanium_ti6al4v", speed_sfm=90,  speed_m_min=27,  feed_ipt=0.0007,
                           feed_mm_rev=0.018, depth_of_cut_mm=4.0, radial_doc_mm=1.0,
                           notes="OSG Ti end mill; flood coolant; Drozda-Wick §3-5"),
        ],
        tags=["slot", "roughing"],
    ),
    # ── Tungaloy TungMill ø5 mm ball-nose
    CatalogTool(
        tool_id="TUNG-BALL-5R2.5",
        manufacturer="Tungaloy",
        tool_type="end_mill",
        diameter_mm=5.0,
        material="coated_carbide",
        coating="TiSiN",
        flutes=2,
        description="Tungaloy TungMill ø5 mm R2.5 2-fl ball-nose end mill",
        workpiece_materials=["steel_mild", "steel_alloy", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=300, speed_m_min=91,  feed_ipt=0.001,
                           feed_mm_rev=0.025, depth_of_cut_mm=2.5, radial_doc_mm=1.0),
            FeedSpeedEntry("aluminium_6061",speed_sfm=900, speed_m_min=274, feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=2.5, radial_doc_mm=1.0),
        ],
        tags=["ball_nose", "finishing", "3d_contour"],
    ),
    # ── Kennametal HARVI ø14 mm
    CatalogTool(
        tool_id="KMT-B218A140Z4CF-KC643M",
        manufacturer="Kennametal",
        tool_type="end_mill",
        diameter_mm=14.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=4,
        description="Kennametal HARVI I ø14 mm 4-fl solid carbide end mill KC643M",
        workpiece_materials=["steel_mild", "stainless_304", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",     speed_sfm=420, speed_m_min=128, feed_ipt=0.0025,
                           feed_mm_rev=0.064, depth_of_cut_mm=7.0, radial_doc_mm=3.5),
            FeedSpeedEntry("stainless_304",  speed_sfm=250, speed_m_min=76,  feed_ipt=0.0015,
                           feed_mm_rev=0.038, depth_of_cut_mm=6.0, radial_doc_mm=2.5),
            FeedSpeedEntry("cast_iron_grey", speed_sfm=480, speed_m_min=146, feed_ipt=0.0025,
                           feed_mm_rev=0.064, depth_of_cut_mm=7.0, radial_doc_mm=3.5),
        ],
        tags=["slot", "roughing"],
    ),
    # ── Sandvik CoroMill Plura ø32 mm 6-fl (heavy rougher)
    CatalogTool(
        tool_id="R216.32-32060-AC45H",
        manufacturer="Sandvik",
        tool_type="end_mill",
        diameter_mm=32.0,
        material="coated_carbide",
        coating="AlTiN",
        flutes=6,
        description="Sandvik CoroMill Plura ø32 mm 6-fl solid carbide end mill (heavy rougher)",
        workpiece_materials=["steel_mild", "steel_alloy", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",     speed_sfm=550, speed_m_min=168, feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=16.0, radial_doc_mm=8.0),
            FeedSpeedEntry("steel_alloy",    speed_sfm=420, speed_m_min=128, feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=16.0, radial_doc_mm=6.0),
            FeedSpeedEntry("cast_iron_grey", speed_sfm=650, speed_m_min=198, feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=16.0, radial_doc_mm=8.0),
        ],
        tags=["roughing"],
    ),
]


# ---------------------------------------------------------------------------
# Catalog — Additional Drills (extended coverage)
# ---------------------------------------------------------------------------

_DRILLS_EXT: List[CatalogTool] = [
    # ── Sandvik CoroDrill ø2.5 mm
    CatalogTool(
        tool_id="870-0250-3T-MM",
        manufacturer="Sandvik",
        tool_type="drill",
        diameter_mm=2.5,
        material="coated_carbide",
        coating="TiN",
        flutes=2,
        description="Sandvik CoroDrill 870 ø2.5 mm solid carbide drill",
        workpiece_materials=["steel_mild", "aluminium_6061", "stainless_304"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=220, speed_m_min=67,  feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=2.5, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=550, speed_m_min=168, feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=2.5, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=130, speed_m_min=40,  feed_ipt=0.0015,
                           feed_mm_rev=0.038, depth_of_cut_mm=2.5, radial_doc_mm=None),
        ],
        tags=["drill"],
    ),
    # ── Tungaloy TungDrill ø16 mm
    CatalogTool(
        tool_id="TUNG-SCD160Q16-02",
        manufacturer="Tungaloy",
        tool_type="drill",
        diameter_mm=16.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=2,
        description="Tungaloy TungDrill ø16 mm solid carbide drill",
        workpiece_materials=["steel_mild", "stainless_304", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=350, speed_m_min=107, feed_ipt=0.010,
                           feed_mm_rev=0.254, depth_of_cut_mm=16.0, radial_doc_mm=None),
            FeedSpeedEntry("stainless_304", speed_sfm=200, speed_m_min=61,  feed_ipt=0.007,
                           feed_mm_rev=0.178, depth_of_cut_mm=16.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=500, speed_m_min=152, feed_ipt=0.011,
                           feed_mm_rev=0.279, depth_of_cut_mm=16.0, radial_doc_mm=None),
        ],
        tags=["drill"],
    ),
    # ── Kennametal KEO HSS ø5.0 mm
    CatalogTool(
        tool_id="KMT-KEO-HSS-5.0",
        manufacturer="Kennametal",
        tool_type="drill",
        diameter_mm=5.0,
        material="hss",
        coating="uncoated",
        flutes=2,
        description="Kennametal KEO ø5.0 mm HSS twist drill (uncoated)",
        workpiece_materials=["steel_mild", "aluminium_6061", "brass_360"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=70,  speed_m_min=21,  feed_ipt=0.003,
                           feed_mm_rev=0.076, depth_of_cut_mm=5.0, radial_doc_mm=None,
                           notes="HSS uncoated; Drozda-Wick §3-2"),
            FeedSpeedEntry("aluminium_6061",speed_sfm=250, speed_m_min=76,  feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=5.0, radial_doc_mm=None),
            FeedSpeedEntry("brass_360",     speed_sfm=200, speed_m_min=61,  feed_ipt=0.005,
                           feed_mm_rev=0.127, depth_of_cut_mm=5.0, radial_doc_mm=None),
        ],
        tags=["drill", "hss"],
    ),
    # ── OSG WX-DS ø3.0 mm
    CatalogTool(
        tool_id="OSG-WX-DS-3.0",
        manufacturer="OSG",
        tool_type="drill",
        diameter_mm=3.0,
        material="coated_carbide",
        coating="TiN",
        flutes=2,
        description="OSG WX-DS ø3.0 mm solid carbide drill",
        workpiece_materials=["steel_mild", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=200, speed_m_min=61,  feed_ipt=0.002,
                           feed_mm_rev=0.051, depth_of_cut_mm=3.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=500, speed_m_min=152, feed_ipt=0.004,
                           feed_mm_rev=0.102, depth_of_cut_mm=3.0, radial_doc_mm=None),
        ],
        tags=["drill"],
    ),
    # ── Iscar SUMOCHAM ø20 mm
    CatalogTool(
        tool_id="ISCAR-ICP200-IC908",
        manufacturer="Iscar",
        tool_type="drill",
        diameter_mm=20.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=2,
        description="Iscar SUMOCHAM ø20 mm replaceable-tip drill IC908",
        workpiece_materials=["steel_mild", "steel_alloy", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=400, speed_m_min=122, feed_ipt=0.012,
                           feed_mm_rev=0.305, depth_of_cut_mm=20.0, radial_doc_mm=None),
            FeedSpeedEntry("steel_alloy",   speed_sfm=320, speed_m_min=98,  feed_ipt=0.010,
                           feed_mm_rev=0.254, depth_of_cut_mm=20.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=500, speed_m_min=152, feed_ipt=0.014,
                           feed_mm_rev=0.356, depth_of_cut_mm=20.0, radial_doc_mm=None),
        ],
        tags=["drill"],
    ),
]


# ---------------------------------------------------------------------------
# Catalog — Additional Taps
# ---------------------------------------------------------------------------

_TAPS_EXT: List[CatalogTool] = [
    # ── Sandvik CoroTap M4x0.7 forming
    CatalogTool(
        tool_id="E533GX-M4x0.7",
        manufacturer="Sandvik",
        tool_type="tap",
        diameter_mm=4.0,
        material="hss",
        coating="TiN",
        flutes=0,
        description="Sandvik CoroTap 300 M4x0.7 forming tap",
        workpiece_materials=["steel_mild", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=55,  speed_m_min=17,  feed_ipt=0.02756,
                           feed_mm_rev=0.7, depth_of_cut_mm=4.0, radial_doc_mm=None,
                           notes="Feed = pitch = 0.7 mm; Sandvik CoroTap forming data 2024"),
            FeedSpeedEntry("aluminium_6061",speed_sfm=110, speed_m_min=34,  feed_ipt=0.02756,
                           feed_mm_rev=0.7, depth_of_cut_mm=4.0, radial_doc_mm=None),
        ],
        tags=["tap", "forming", "m4"],
    ),
    # ── OSG UH-TAP M3x0.5
    CatalogTool(
        tool_id="OSG-UH-TAP-M3x0.5",
        manufacturer="OSG",
        tool_type="tap",
        diameter_mm=3.0,
        material="hss",
        coating="TiN",
        flutes=3,
        description="OSG HSSE UH-TAP M3x0.5 cutting tap",
        workpiece_materials=["steel_mild", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=35,  speed_m_min=11,  feed_ipt=0.01969,
                           feed_mm_rev=0.5, depth_of_cut_mm=3.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=80,  speed_m_min=24,  feed_ipt=0.01969,
                           feed_mm_rev=0.5, depth_of_cut_mm=3.0, radial_doc_mm=None),
        ],
        tags=["tap", "m3"],
    ),
    # ── Iscar M16x2.0 spiral-flute
    CatalogTool(
        tool_id="ISCAR-TAP-M16x2.0-HSSE",
        manufacturer="Iscar",
        tool_type="tap",
        diameter_mm=16.0,
        material="hss",
        coating="TiAlN",
        flutes=4,
        description="Iscar HSSE M16x2.0 spiral-flute tap",
        workpiece_materials=["steel_mild", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=60,  speed_m_min=18,  feed_ipt=0.07874,
                           feed_mm_rev=2.0, depth_of_cut_mm=16.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=130, speed_m_min=40,  feed_ipt=0.07874,
                           feed_mm_rev=2.0, depth_of_cut_mm=16.0, radial_doc_mm=None),
        ],
        tags=["tap", "m16"],
    ),
]


# ---------------------------------------------------------------------------
# Catalog — Additional Reamers
# ---------------------------------------------------------------------------

_REAMERS_EXT: List[CatalogTool] = [
    # ── Tungaloy reamer ø5 mm
    CatalogTool(
        tool_id="TUNG-REAMER-5.0-H7",
        manufacturer="Tungaloy",
        tool_type="reamer",
        diameter_mm=5.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=6,
        description="Tungaloy solid carbide reamer ø5 mm H7",
        workpiece_materials=["steel_mild", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=75,  speed_m_min=23,  feed_ipt=0.007,
                           feed_mm_rev=0.178, depth_of_cut_mm=5.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=180, speed_m_min=55,  feed_ipt=0.013,
                           feed_mm_rev=0.330, depth_of_cut_mm=5.0, radial_doc_mm=None),
        ],
        tags=["reamer", "finishing"],
    ),
    # ── Iscar adjustable reamer ø16 mm
    CatalogTool(
        tool_id="ISCAR-ADJ-REAMER-16",
        manufacturer="Iscar",
        tool_type="reamer",
        diameter_mm=16.0,
        material="coated_carbide",
        coating="TiN",
        flutes=8,
        description="Iscar adjustable carbide reamer ø16 mm",
        workpiece_materials=["steel_mild", "cast_iron_grey", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=110, speed_m_min=34,  feed_ipt=0.014,
                           feed_mm_rev=0.356, depth_of_cut_mm=16.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=160, speed_m_min=49,  feed_ipt=0.016,
                           feed_mm_rev=0.406, depth_of_cut_mm=16.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=350, speed_m_min=107, feed_ipt=0.022,
                           feed_mm_rev=0.559, depth_of_cut_mm=16.0, radial_doc_mm=None),
        ],
        tags=["reamer", "finishing"],
    ),
    # ── OSG VPH reamer ø20 mm
    CatalogTool(
        tool_id="OSG-VPH-REAMER-20.0",
        manufacturer="OSG",
        tool_type="reamer",
        diameter_mm=20.0,
        material="coated_carbide",
        coating="TiAlN",
        flutes=8,
        description="OSG VPH carbide reamer ø20 mm",
        workpiece_materials=["steel_mild", "aluminium_6061", "cast_iron_grey"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=120, speed_m_min=37,  feed_ipt=0.016,
                           feed_mm_rev=0.406, depth_of_cut_mm=20.0, radial_doc_mm=None,
                           notes="OSG VPH reamer; Drozda-Wick §3-6"),
            FeedSpeedEntry("aluminium_6061",speed_sfm=360, speed_m_min=110, feed_ipt=0.025,
                           feed_mm_rev=0.635, depth_of_cut_mm=20.0, radial_doc_mm=None),
            FeedSpeedEntry("cast_iron_grey",speed_sfm=180, speed_m_min=55,  feed_ipt=0.018,
                           feed_mm_rev=0.457, depth_of_cut_mm=20.0, radial_doc_mm=None),
        ],
        tags=["reamer", "finishing"],
    ),
    # ── Kennametal KMT solid reamer ø4 mm
    CatalogTool(
        tool_id="KMT-SOLID-REAMER-4.0",
        manufacturer="Kennametal",
        tool_type="reamer",
        diameter_mm=4.0,
        material="coated_carbide",
        coating="TiN",
        flutes=6,
        description="Kennametal solid carbide reamer ø4 mm H7",
        workpiece_materials=["steel_mild", "aluminium_6061"],
        feed_speeds=[
            FeedSpeedEntry("steel_mild",    speed_sfm=70,  speed_m_min=21,  feed_ipt=0.006,
                           feed_mm_rev=0.152, depth_of_cut_mm=4.0, radial_doc_mm=None),
            FeedSpeedEntry("aluminium_6061",speed_sfm=170, speed_m_min=52,  feed_ipt=0.010,
                           feed_mm_rev=0.254, depth_of_cut_mm=4.0, radial_doc_mm=None),
        ],
        tags=["reamer", "finishing"],
    ),
]


# ---------------------------------------------------------------------------
# Master catalog
# ---------------------------------------------------------------------------

CATALOG: List[CatalogTool] = (
    _END_MILLS + _END_MILLS_EXT +
    _DRILLS + _DRILLS_EXT +
    _TAPS + _TAPS_EXT +
    _REAMERS + _REAMERS_EXT +
    _INSERTS
)
