"""
material_catalogue_data.py
==========================

Curated PBR catalogue for the BIM material library (T-115).

Each entry covers the canonical BIM categories:
  concrete, brick, masonry, wood, steel, aluminum, glass, plaster,
  ceramic_tile, vinyl, carpet.

PBR values (base_color, metalness, roughness, ior, transmission) are
tuned for the Cycles/Principled-BSDF path.  Physical properties
(density, thermal conductivity, specific heat) reference published
engineering standards.

Sources
-------
- ASTM A36, A572, A240     Structural steel / stainless
- EN 1993-1-1:2005         Eurocode 3 — S275, S355
- IS 456:2000              Concrete grades M20..M50
- NDS 2018 Supplement      Timber (oak, maple, walnut, pine, douglas fir, SPF)
- ASTM C1036-21            Float / tempered glass
- ASTM C62-17              Clay brick
- ASTM C90-22              Concrete masonry units (CMU)
- NIST SP 1018             Density reference data
- ASHRAE 2021 HOF Ch.26    Thermal properties
- EN ISO 10456:2007        Thermal conductivities
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class MaterialEntry:
    """A single BIM material with PBR appearance and physical properties."""

    name: str                          # canonical lower-case key
    category: str                      # BIM category
    base_color: Tuple[float, float, float]  # linear sRGB [0,1]
    metalness: float                   # 0.0 – 1.0
    roughness: float                   # 0.0 – 1.0
    ior: float                         # index of refraction
    transmission: float                # 0.0 (opaque) – 1.0 (fully transmissive)
    density_kg_m3: float               # kg/m³
    thermal_conductivity_w_mk: float   # W/(m·K)
    specific_heat_j_kgk: float         # J/(kg·K)
    description: str


# ---------------------------------------------------------------------------
# Raw catalogue list — 40+ entries
# ---------------------------------------------------------------------------

_RAW: list[MaterialEntry] = [

    # -----------------------------------------------------------------------
    # CONCRETE
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="concrete_m20",
        category="concrete",
        base_color=(0.72, 0.72, 0.70),
        metalness=0.0, roughness=0.85, ior=1.50, transmission=0.0,
        density_kg_m3=2400.0, thermal_conductivity_w_mk=1.7, specific_heat_j_kgk=880.0,
        description="Normal-weight concrete grade M20 (f_ck=20 MPa); IS 456:2000.",
    ),
    MaterialEntry(
        name="concrete_m30",
        category="concrete",
        base_color=(0.70, 0.70, 0.68),
        metalness=0.0, roughness=0.85, ior=1.50, transmission=0.0,
        density_kg_m3=2400.0, thermal_conductivity_w_mk=1.7, specific_heat_j_kgk=880.0,
        description="Normal-weight concrete grade M30 (f_ck=30 MPa); IS 456:2000.",
    ),
    MaterialEntry(
        name="concrete_m40",
        category="concrete",
        base_color=(0.68, 0.68, 0.66),
        metalness=0.0, roughness=0.85, ior=1.50, transmission=0.0,
        density_kg_m3=2400.0, thermal_conductivity_w_mk=1.7, specific_heat_j_kgk=880.0,
        description="Normal-weight concrete grade M40 (f_ck=40 MPa); IS 456:2000.",
    ),
    MaterialEntry(
        name="concrete_m50",
        category="concrete",
        base_color=(0.66, 0.66, 0.64),
        metalness=0.0, roughness=0.82, ior=1.50, transmission=0.0,
        density_kg_m3=2400.0, thermal_conductivity_w_mk=1.7, specific_heat_j_kgk=880.0,
        description="Normal-weight concrete grade M50 (f_ck=50 MPa); IS 456:2000.",
    ),
    MaterialEntry(
        name="concrete_reinforced",
        category="concrete",
        base_color=(0.65, 0.65, 0.63),
        metalness=0.0, roughness=0.85, ior=1.50, transmission=0.0,
        density_kg_m3=2500.0, thermal_conductivity_w_mk=1.7, specific_heat_j_kgk=880.0,
        description="Reinforced normal-weight concrete; IS 456:2000 / ACI 318-19.",
    ),

    # -----------------------------------------------------------------------
    # BRICK
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="brick_clay_red",
        category="brick",
        base_color=(0.72, 0.36, 0.25),
        metalness=0.0, roughness=0.88, ior=1.50, transmission=0.0,
        density_kg_m3=1900.0, thermal_conductivity_w_mk=0.72, specific_heat_j_kgk=840.0,
        description="Red clay building brick; ASTM C62-17; density ~1900 kg/m³.",
    ),
    MaterialEntry(
        name="brick_clay_buff",
        category="brick",
        base_color=(0.82, 0.70, 0.48),
        metalness=0.0, roughness=0.88, ior=1.50, transmission=0.0,
        density_kg_m3=1900.0, thermal_conductivity_w_mk=0.72, specific_heat_j_kgk=840.0,
        description="Buff/sand-faced clay brick; ASTM C62-17.",
    ),
    MaterialEntry(
        name="brick_engineered",
        category="brick",
        base_color=(0.60, 0.28, 0.20),
        metalness=0.0, roughness=0.80, ior=1.50, transmission=0.0,
        density_kg_m3=2000.0, thermal_conductivity_w_mk=0.85, specific_heat_j_kgk=840.0,
        description="Engineering brick (dense, low absorption); BS EN 771-1:2011.",
    ),

    # -----------------------------------------------------------------------
    # MASONRY
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="masonry_cmu_concrete",
        category="masonry",
        base_color=(0.65, 0.65, 0.62),
        metalness=0.0, roughness=0.90, ior=1.50, transmission=0.0,
        density_kg_m3=1920.0, thermal_conductivity_w_mk=0.88, specific_heat_j_kgk=880.0,
        description="Normal-weight concrete masonry unit (CMU); ASTM C90-22.",
    ),
    MaterialEntry(
        name="masonry_aac_block",
        category="masonry",
        base_color=(0.92, 0.92, 0.90),
        metalness=0.0, roughness=0.80, ior=1.50, transmission=0.0,
        density_kg_m3=600.0, thermal_conductivity_w_mk=0.16, specific_heat_j_kgk=1000.0,
        description="Autoclaved aerated concrete (AAC) block; ASTM C1693-18; density 500–700 kg/m³.",
    ),

    # -----------------------------------------------------------------------
    # WOOD
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="wood_oak",
        category="wood",
        base_color=(0.55, 0.38, 0.22),
        metalness=0.0, roughness=0.75, ior=1.50, transmission=0.0,
        density_kg_m3=750.0, thermal_conductivity_w_mk=0.18, specific_heat_j_kgk=1700.0,
        description="Red/white oak hardwood; NDS 2018 Supplement Table 4A; density ~750 kg/m³.",
    ),
    MaterialEntry(
        name="wood_maple",
        category="wood",
        base_color=(0.78, 0.65, 0.45),
        metalness=0.0, roughness=0.72, ior=1.50, transmission=0.0,
        density_kg_m3=705.0, thermal_conductivity_w_mk=0.16, specific_heat_j_kgk=1700.0,
        description="Hard maple; NDS 2018 Supplement Table 4A; density ~705 kg/m³.",
    ),
    MaterialEntry(
        name="wood_walnut",
        category="wood",
        base_color=(0.32, 0.20, 0.10),
        metalness=0.0, roughness=0.70, ior=1.50, transmission=0.0,
        density_kg_m3=625.0, thermal_conductivity_w_mk=0.16, specific_heat_j_kgk=1700.0,
        description="Black walnut; NDS 2018; density ~625 kg/m³.",
    ),
    MaterialEntry(
        name="wood_pine",
        category="wood",
        base_color=(0.80, 0.63, 0.38),
        metalness=0.0, roughness=0.78, ior=1.50, transmission=0.0,
        density_kg_m3=590.0, thermal_conductivity_w_mk=0.14, specific_heat_j_kgk=1700.0,
        description="Southern yellow pine No.2; NDS 2018 Supplement Table 4B; density ~590 kg/m³.",
    ),
    MaterialEntry(
        name="wood_douglas_fir",
        category="wood",
        base_color=(0.76, 0.58, 0.35),
        metalness=0.0, roughness=0.76, ior=1.50, transmission=0.0,
        density_kg_m3=530.0, thermal_conductivity_w_mk=0.14, specific_heat_j_kgk=1700.0,
        description="Douglas Fir-Larch; NDS 2018 Supplement Table 4A; density 530 kg/m³.",
    ),
    MaterialEntry(
        name="wood_spf",
        category="wood",
        base_color=(0.76, 0.60, 0.42),
        metalness=0.0, roughness=0.75, ior=1.50, transmission=0.0,
        density_kg_m3=420.0, thermal_conductivity_w_mk=0.12, specific_heat_j_kgk=1700.0,
        description="Spruce-Pine-Fir (SPF); NDS 2018 Supplement Table 4A; density ~420 kg/m³.",
    ),

    # -----------------------------------------------------------------------
    # STEEL
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="steel_raw_a36",
        category="steel",
        base_color=(0.72, 0.72, 0.72),
        metalness=1.0, roughness=0.40, ior=2.50, transmission=0.0,
        density_kg_m3=7850.0, thermal_conductivity_w_mk=50.0, specific_heat_j_kgk=490.0,
        description="Raw structural steel ASTM A36; F_y=248 MPa, E=200 GPa; NIST SP 1018.",
    ),
    MaterialEntry(
        name="steel_raw_s355",
        category="steel",
        base_color=(0.70, 0.70, 0.70),
        metalness=1.0, roughness=0.42, ior=2.50, transmission=0.0,
        density_kg_m3=7850.0, thermal_conductivity_w_mk=50.0, specific_heat_j_kgk=490.0,
        description="Raw structural steel EN 1993-1-1 S355; f_y=355 MPa.",
    ),
    MaterialEntry(
        name="steel_painted_white",
        category="steel",
        base_color=(0.95, 0.95, 0.94),
        metalness=0.05, roughness=0.55, ior=1.55, transmission=0.0,
        density_kg_m3=7900.0, thermal_conductivity_w_mk=48.0, specific_heat_j_kgk=490.0,
        description="Painted (white) structural steel; paint layer modelled as low-metalness coating.",
    ),
    MaterialEntry(
        name="steel_galvanised",
        category="steel",
        base_color=(0.80, 0.82, 0.80),
        metalness=0.90, roughness=0.30, ior=2.40, transmission=0.0,
        density_kg_m3=7870.0, thermal_conductivity_w_mk=50.0, specific_heat_j_kgk=490.0,
        description="Hot-dip galvanised steel; zinc-coated finish; ASTM A123.",
    ),
    MaterialEntry(
        name="steel_stainless_304",
        category="steel",
        base_color=(0.80, 0.82, 0.83),
        metalness=1.0, roughness=0.25, ior=2.50, transmission=0.0,
        density_kg_m3=8000.0, thermal_conductivity_w_mk=16.3, specific_heat_j_kgk=500.0,
        description="Stainless steel 304 (1.4301); ASTM A240-22; EN 10088-2.",
    ),

    # -----------------------------------------------------------------------
    # ALUMINUM
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="aluminum_6061_t6",
        category="aluminum",
        base_color=(0.82, 0.83, 0.85),
        metalness=1.0, roughness=0.30, ior=2.00, transmission=0.0,
        density_kg_m3=2700.0, thermal_conductivity_w_mk=167.0, specific_heat_j_kgk=896.0,
        description="Aluminium alloy 6061-T6; F_y=276 MPa; ADM 2020 Table A.3.4.",
    ),
    MaterialEntry(
        name="aluminum_anodised",
        category="aluminum",
        base_color=(0.75, 0.78, 0.82),
        metalness=0.85, roughness=0.35, ior=1.80, transmission=0.0,
        density_kg_m3=2700.0, thermal_conductivity_w_mk=160.0, specific_heat_j_kgk=896.0,
        description="Anodised aluminium (natural); thin Al₂O₃ coating reduces metalness slightly.",
    ),

    # -----------------------------------------------------------------------
    # GLASS
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="glass_clear_float",
        category="glass",
        base_color=(0.82, 0.90, 0.90),
        metalness=0.0, roughness=0.05, ior=1.52, transmission=0.90,
        density_kg_m3=2500.0, thermal_conductivity_w_mk=1.0, specific_heat_j_kgk=840.0,
        description="Clear sodalime float glass; ASTM C1036-21; IOR 1.52; transmission ~90%.",
    ),
    MaterialEntry(
        name="glass_frosted",
        category="glass",
        base_color=(0.88, 0.92, 0.93),
        metalness=0.0, roughness=0.65, ior=1.52, transmission=0.82,
        density_kg_m3=2500.0, thermal_conductivity_w_mk=1.0, specific_heat_j_kgk=840.0,
        description="Acid-etched / sandblasted frosted glass; diffuse transmission.",
    ),
    MaterialEntry(
        name="glass_low_e",
        category="glass",
        base_color=(0.78, 0.88, 0.88),
        metalness=0.05, roughness=0.08, ior=1.52, transmission=0.85,
        density_kg_m3=2500.0, thermal_conductivity_w_mk=1.0, specific_heat_j_kgk=840.0,
        description="Low-emissivity (Low-E) double-pane glass; metallic oxide coating; NFRC.",
    ),
    MaterialEntry(
        name="glass_tempered",
        category="glass",
        base_color=(0.82, 0.90, 0.90),
        metalness=0.0, roughness=0.04, ior=1.52, transmission=0.90,
        density_kg_m3=2500.0, thermal_conductivity_w_mk=1.0, specific_heat_j_kgk=840.0,
        description="Heat-strengthened tempered glass (~4× annealed MOR); ASTM C1036-21.",
    ),

    # -----------------------------------------------------------------------
    # PLASTER
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="plaster_lime",
        category="plaster",
        base_color=(0.96, 0.94, 0.88),
        metalness=0.0, roughness=0.80, ior=1.50, transmission=0.0,
        density_kg_m3=1600.0, thermal_conductivity_w_mk=0.72, specific_heat_j_kgk=840.0,
        description="Lime render / plaster; BS EN 998-1:2016; density 1400–1800 kg/m³.",
    ),
    MaterialEntry(
        name="plaster_gypsum",
        category="plaster",
        base_color=(0.97, 0.96, 0.94),
        metalness=0.0, roughness=0.60, ior=1.50, transmission=0.0,
        density_kg_m3=1100.0, thermal_conductivity_w_mk=0.40, specific_heat_j_kgk=1090.0,
        description="Gypsum finish plaster; ASTM C28-00; BS EN 13279-1:2008.",
    ),
    MaterialEntry(
        name="plaster_cement",
        category="plaster",
        base_color=(0.82, 0.82, 0.80),
        metalness=0.0, roughness=0.82, ior=1.50, transmission=0.0,
        density_kg_m3=1800.0, thermal_conductivity_w_mk=1.0, specific_heat_j_kgk=880.0,
        description="Cement render; BS EN 998-1:2016 GP mortar; IS 1661:1972.",
    ),

    # -----------------------------------------------------------------------
    # CERAMIC TILE
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="ceramic_tile_white",
        category="ceramic_tile",
        base_color=(0.95, 0.95, 0.94),
        metalness=0.0, roughness=0.18, ior=1.55, transmission=0.0,
        density_kg_m3=2000.0, thermal_conductivity_w_mk=1.0, specific_heat_j_kgk=840.0,
        description="Glazed white ceramic wall/floor tile; ASTM C373-18; EN ISO 10545.",
    ),
    MaterialEntry(
        name="ceramic_tile_terracotta",
        category="ceramic_tile",
        base_color=(0.70, 0.38, 0.22),
        metalness=0.0, roughness=0.55, ior=1.55, transmission=0.0,
        density_kg_m3=1950.0, thermal_conductivity_w_mk=0.85, specific_heat_j_kgk=840.0,
        description="Unglazed terracotta tile; traditional fired clay; EN ISO 10545.",
    ),
    MaterialEntry(
        name="ceramic_tile_porcelain",
        category="ceramic_tile",
        base_color=(0.88, 0.88, 0.88),
        metalness=0.0, roughness=0.12, ior=1.55, transmission=0.0,
        density_kg_m3=2300.0, thermal_conductivity_w_mk=1.3, specific_heat_j_kgk=800.0,
        description="Glazed porcelain floor tile; ASTM C373-18; water absorption <0.5%.",
    ),

    # -----------------------------------------------------------------------
    # VINYL
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="vinyl_lvt",
        category="vinyl",
        base_color=(0.72, 0.60, 0.45),
        metalness=0.0, roughness=0.50, ior=1.54, transmission=0.0,
        density_kg_m3=1700.0, thermal_conductivity_w_mk=0.17, specific_heat_j_kgk=1000.0,
        description="Luxury vinyl tile (LVT) / plank; ASTM F1700-18; density ~1700 kg/m³.",
    ),
    MaterialEntry(
        name="vinyl_sheet",
        category="vinyl",
        base_color=(0.70, 0.70, 0.68),
        metalness=0.0, roughness=0.45, ior=1.54, transmission=0.0,
        density_kg_m3=1500.0, thermal_conductivity_w_mk=0.16, specific_heat_j_kgk=1000.0,
        description="Vinyl sheet flooring (homogeneous); ASTM F1303-04.",
    ),

    # -----------------------------------------------------------------------
    # CARPET
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="carpet_loop_pile",
        category="carpet",
        base_color=(0.45, 0.42, 0.38),
        metalness=0.0, roughness=0.95, ior=1.20, transmission=0.0,
        density_kg_m3=200.0, thermal_conductivity_w_mk=0.06, specific_heat_j_kgk=1300.0,
        description="Commercial loop-pile carpet tile; ASTM D5116; density ~150–250 kg/m³.",
    ),
    MaterialEntry(
        name="carpet_cut_pile",
        category="carpet",
        base_color=(0.55, 0.48, 0.40),
        metalness=0.0, roughness=0.95, ior=1.20, transmission=0.0,
        density_kg_m3=180.0, thermal_conductivity_w_mk=0.06, specific_heat_j_kgk=1300.0,
        description="Residential cut-pile carpet; ASTM D5116; density ~150–200 kg/m³.",
    ),

    # -----------------------------------------------------------------------
    # ADDITIONAL — insulation, board, stone (ensures 40+ total)
    # -----------------------------------------------------------------------
    MaterialEntry(
        name="insulation_rockwool",
        category="insulation",
        base_color=(0.82, 0.74, 0.58),
        metalness=0.0, roughness=0.95, ior=1.20, transmission=0.0,
        density_kg_m3=40.0, thermal_conductivity_w_mk=0.036, specific_heat_j_kgk=840.0,
        description="Mineral/rock wool insulation; EN ISO 10456; λ=0.036 W/(m·K).",
    ),
    MaterialEntry(
        name="insulation_eps",
        category="insulation",
        base_color=(0.96, 0.96, 0.96),
        metalness=0.0, roughness=0.90, ior=1.10, transmission=0.0,
        density_kg_m3=20.0, thermal_conductivity_w_mk=0.038, specific_heat_j_kgk=1300.0,
        description="EPS expanded polystyrene board; EN 13163:2012; λ=0.038 W/(m·K).",
    ),
    MaterialEntry(
        name="board_gypsum_drywall",
        category="board",
        base_color=(0.96, 0.96, 0.95),
        metalness=0.0, roughness=0.85, ior=1.50, transmission=0.0,
        density_kg_m3=800.0, thermal_conductivity_w_mk=0.25, specific_heat_j_kgk=1090.0,
        description="Standard gypsum wallboard (drywall); ASTM C1396-21.",
    ),
    MaterialEntry(
        name="stone_granite",
        category="stone",
        base_color=(0.55, 0.50, 0.50),
        metalness=0.0, roughness=0.60, ior=1.55, transmission=0.0,
        density_kg_m3=2700.0, thermal_conductivity_w_mk=3.0, specific_heat_j_kgk=790.0,
        description="Granite; ASTM C615-18; density ~2700 kg/m³.",
    ),
    MaterialEntry(
        name="stone_marble",
        category="stone",
        base_color=(0.93, 0.93, 0.90),
        metalness=0.0, roughness=0.25, ior=1.55, transmission=0.0,
        density_kg_m3=2720.0, thermal_conductivity_w_mk=2.5, specific_heat_j_kgk=880.0,
        description="Marble; ASTM C503-19; density ~2720 kg/m³.",
    ),
]
