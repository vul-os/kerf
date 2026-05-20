"""
kerf_textiles.materials
=======================
Curated catalogue of 50+ textile materials with physical and sustainability
properties, plus lookup helpers.

Each :class:`TextileMaterial` entry carries:

Physical
--------
- ``density_gsm``         — area density in g/m²  (typical finished-fabric value)
- ``tensile_strength_mpa`` — warp/fill tensile strength in MPa (single-yarn)
- ``elongation_pct``      — elongation-at-break in %

Sustainability (per kg of raw fibre, cradle-to-gate)
----------------------------------------------------
- ``water_consumption_l_per_kg`` — process water (L/kg)
- ``co2_footprint_kg_per_kg``    — GHG in kg CO₂e / kg fibre
- ``biodegradable``              — True if certified or well-established
- ``certifications``             — list of applicable labels

Lookup
------
- :func:`by_category`  — returns list of materials filtered by category string
- :func:`by_id`        — returns a single material by its ``material_id``
- ``CATALOGUE``        — flat dict keyed by ``material_id``

Usage::

    from kerf_textiles.materials import by_category, by_id, CATALOGUE

    naturals = by_category("natural_cellulosic")
    cotton = by_id("cotton_conventional")
    print(cotton.co2_footprint_kg_per_kg)   # 5.9
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TextileMaterial:
    """Immutable descriptor for one textile material variant."""

    material_id: str
    name: str
    category: str                           # see CATEGORIES constant
    subcategory: str                        # e.g. "organic", "recycled"

    # Physical properties (typical finished-fabric / yarn values)
    density_gsm: float                      # g/m² area weight
    tensile_strength_mpa: float             # MPa
    elongation_pct: float                   # %

    # Sustainability (cradle-to-gate, per kg raw fibre)
    water_consumption_l_per_kg: float       # litres per kg
    co2_footprint_kg_per_kg: float          # kg CO₂e per kg
    biodegradable: bool
    certifications: tuple[str, ...] = field(default_factory=tuple)

    # Optional notes / references
    notes: str = ""


# Valid category strings — informational, not enforced at runtime
CATEGORIES: tuple[str, ...] = (
    "natural_cellulosic",   # cotton, linen, hemp
    "natural_protein",      # wool, silk, cashmere, alpaca, mohair
    "man_made_cellulosic",  # viscose, lyocell, modal, cupro, bamboo viscose
    "synthetic",            # polyester, nylon, acrylic, spandex/elastane
    "semi_synthetic",       # acetate, triacetate
    "leather",              # full-grain, corrected-grain, PU/vegan
    "technical",            # aramid, UHMWPE, carbon-fibre, glass-fibre, PBO
)


# ---------------------------------------------------------------------------
# Catalogue — 50+ entries
# ---------------------------------------------------------------------------

def _m(
    material_id: str,
    name: str,
    category: str,
    subcategory: str,
    density_gsm: float,
    tensile_strength_mpa: float,
    elongation_pct: float,
    water_consumption_l_per_kg: float,
    co2_footprint_kg_per_kg: float,
    biodegradable: bool,
    certifications: tuple[str, ...] = (),
    notes: str = "",
) -> TextileMaterial:
    """Convenience builder — keeps catalogue definitions concise."""
    return TextileMaterial(
        material_id=material_id,
        name=name,
        category=category,
        subcategory=subcategory,
        density_gsm=density_gsm,
        tensile_strength_mpa=tensile_strength_mpa,
        elongation_pct=elongation_pct,
        water_consumption_l_per_kg=water_consumption_l_per_kg,
        co2_footprint_kg_per_kg=co2_footprint_kg_per_kg,
        biodegradable=biodegradable,
        certifications=certifications,
        notes=notes,
    )


_NC = "natural_cellulosic"
_NP = "natural_protein"
_MC = "man_made_cellulosic"
_SY = "synthetic"
_SS = "semi_synthetic"
_LE = "leather"
_TE = "technical"

_RAW_CATALOGUE: list[TextileMaterial] = [
    # ------------------------------------------------------------------
    # Natural cellulosic
    # ------------------------------------------------------------------
    _m("cotton_conventional",
       "Cotton (Conventional)", _NC, "conventional",
       density_gsm=150.0, tensile_strength_mpa=400.0, elongation_pct=8.0,
       water_consumption_l_per_kg=10000.0, co2_footprint_kg_per_kg=5.9,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="World-average conventional ring-spun; Higg index 2022."),

    _m("cotton_organic",
       "Cotton (Organic)", _NC, "organic",
       density_gsm=150.0, tensile_strength_mpa=395.0, elongation_pct=8.0,
       water_consumption_l_per_kg=6800.0, co2_footprint_kg_per_kg=3.8,
       biodegradable=True,
       certifications=("GOTS", "OEKO-TEX"),
       notes="GOTS-certified, no synthetic pesticides."),

    _m("cotton_recycled",
       "Cotton (Recycled / Mechanical)", _NC, "recycled",
       density_gsm=150.0, tensile_strength_mpa=310.0, elongation_pct=6.5,
       water_consumption_l_per_kg=320.0, co2_footprint_kg_per_kg=1.2,
       biodegradable=True,
       certifications=("GRS", "OEKO-TEX"),
       notes="Post-industrial or post-consumer shredded cotton; lower tensile."),

    _m("cotton_bci",
       "Cotton (Better Cotton Initiative)", _NC, "bci",
       density_gsm=150.0, tensile_strength_mpa=395.0, elongation_pct=8.0,
       water_consumption_l_per_kg=7500.0, co2_footprint_kg_per_kg=4.6,
       biodegradable=True,
       certifications=("BCI", "OEKO-TEX"),
       notes="BCI programme cotton; intermediate footprint."),

    _m("linen",
       "Linen (Flax)", _NC, "conventional",
       density_gsm=200.0, tensile_strength_mpa=950.0, elongation_pct=2.7,
       water_consumption_l_per_kg=650.0, co2_footprint_kg_per_kg=1.7,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="European wet-retting flax; very low irrigation."),

    _m("hemp",
       "Hemp", _NC, "conventional",
       density_gsm=240.0, tensile_strength_mpa=690.0, elongation_pct=1.6,
       water_consumption_l_per_kg=300.0, co2_footprint_kg_per_kg=1.1,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="Rainfed crop; sequesters CO₂ during growth."),

    _m("hemp_organic",
       "Hemp (Organic)", _NC, "organic",
       density_gsm=240.0, tensile_strength_mpa=690.0, elongation_pct=1.6,
       water_consumption_l_per_kg=280.0, co2_footprint_kg_per_kg=0.9,
       biodegradable=True,
       certifications=("GOTS", "OEKO-TEX"),
       notes="Certified organic, no chemical retting."),

    _m("jute",
       "Jute", _NC, "conventional",
       density_gsm=310.0, tensile_strength_mpa=400.0, elongation_pct=1.8,
       water_consumption_l_per_kg=250.0, co2_footprint_kg_per_kg=0.5,
       biodegradable=True,
       notes="Predominantly Bangladesh/India; very low footprint."),

    _m("nettle",
       "Stinging Nettle Fibre", _NC, "conventional",
       density_gsm=210.0, tensile_strength_mpa=570.0, elongation_pct=1.8,
       water_consumption_l_per_kg=200.0, co2_footprint_kg_per_kg=0.7,
       biodegradable=True,
       notes="Emerging fibre; low-input crop, degums without chemicals."),

    # ------------------------------------------------------------------
    # Natural protein
    # ------------------------------------------------------------------
    _m("wool_merino_virgin",
       "Wool — Merino (Virgin)", _NP, "virgin",
       density_gsm=180.0, tensile_strength_mpa=200.0, elongation_pct=35.0,
       water_consumption_l_per_kg=170.0, co2_footprint_kg_per_kg=27.0,
       biodegradable=True,
       certifications=("RWS", "OEKO-TEX"),
       notes="Includes methane from sheep; dyeing water not included."),

    _m("wool_recycled",
       "Wool (Recycled / Shoddy)", _NP, "recycled",
       density_gsm=180.0, tensile_strength_mpa=160.0, elongation_pct=28.0,
       water_consumption_l_per_kg=80.0, co2_footprint_kg_per_kg=4.0,
       biodegradable=True,
       certifications=("GRS",),
       notes="Mechanically recycled; shorter fibres, reduced tensile."),

    _m("cashmere_virgin",
       "Cashmere (Virgin)", _NP, "virgin",
       density_gsm=130.0, tensile_strength_mpa=175.0, elongation_pct=30.0,
       water_consumption_l_per_kg=220.0, co2_footprint_kg_per_kg=130.0,
       biodegradable=True,
       certifications=("GCS",),
       notes="Very high impact due to low yield per goat; land degradation risk."),

    _m("alpaca_virgin",
       "Alpaca (Virgin)", _NP, "virgin",
       density_gsm=160.0, tensile_strength_mpa=210.0, elongation_pct=28.0,
       water_consumption_l_per_kg=90.0, co2_footprint_kg_per_kg=14.5,
       biodegradable=True,
       notes="Lower methane than sheep per kg fleece; soft padded feet."),

    _m("mohair",
       "Mohair (Angora Goat)", _NP, "virgin",
       density_gsm=145.0, tensile_strength_mpa=185.0, elongation_pct=26.0,
       water_consumption_l_per_kg=160.0, co2_footprint_kg_per_kg=21.5,
       biodegradable=True,
       notes="South Africa / Turkey; high lustre protein fibre."),

    _m("silk_conventional",
       "Silk (Conventional Mulberry)", _NP, "conventional",
       density_gsm=80.0, tensile_strength_mpa=500.0, elongation_pct=20.0,
       water_consumption_l_per_kg=1900.0, co2_footprint_kg_per_kg=35.0,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="Reeling of Bombyx mori cocoons; silkworms are killed."),

    _m("silk_ahimsa",
       "Peace Silk (Ahimsa)", _NP, "ahimsa",
       density_gsm=80.0, tensile_strength_mpa=450.0, elongation_pct=18.0,
       water_consumption_l_per_kg=1900.0, co2_footprint_kg_per_kg=33.0,
       biodegradable=True,
       certifications=("GOTS", "OEKO-TEX"),
       notes="Moth allowed to emerge; slightly lower strength due to broken filament."),

    # ------------------------------------------------------------------
    # Man-made cellulosic
    # ------------------------------------------------------------------
    _m("viscose_conventional",
       "Viscose / Rayon (Conventional)", _MC, "conventional",
       density_gsm=130.0, tensile_strength_mpa=250.0, elongation_pct=20.0,
       water_consumption_l_per_kg=100.0, co2_footprint_kg_per_kg=4.2,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="CS₂ wet-spinning; chemical waste a concern."),

    _m("viscose_ecovero",
       "Viscose EcoVero (Lenzing)", _MC, "eco",
       density_gsm=130.0, tensile_strength_mpa=255.0, elongation_pct=20.0,
       water_consumption_l_per_kg=60.0, co2_footprint_kg_per_kg=2.1,
       biodegradable=True,
       certifications=("OEKO-TEX", "EU Ecolabel"),
       notes="Lenzing closed-loop process; certified sustainable wood source."),

    _m("lyocell_tencel",
       "Lyocell / TENCEL™", _MC, "lyocell",
       density_gsm=130.0, tensile_strength_mpa=350.0, elongation_pct=15.0,
       water_consumption_l_per_kg=20.0, co2_footprint_kg_per_kg=2.5,
       biodegradable=True,
       certifications=("OEKO-TEX", "FSC"),
       notes="Closed-loop NMMO solvent; Lenzing TENCEL is the benchmark."),

    _m("modal",
       "Modal (Lenzing)", _MC, "modal",
       density_gsm=140.0, tensile_strength_mpa=340.0, elongation_pct=13.0,
       water_consumption_l_per_kg=40.0, co2_footprint_kg_per_kg=3.4,
       biodegradable=True,
       certifications=("OEKO-TEX", "FSC"),
       notes="Beech-wood feedstock; softer drape than regular viscose."),

    _m("cupro",
       "Cupro (Bemberg)", _MC, "cupro",
       density_gsm=90.0, tensile_strength_mpa=270.0, elongation_pct=14.0,
       water_consumption_l_per_kg=500.0, co2_footprint_kg_per_kg=4.8,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="Made from cotton linter waste; copper-ammonium process."),

    _m("bamboo_viscose",
       "Bamboo Viscose", _MC, "bamboo",
       density_gsm=120.0, tensile_strength_mpa=240.0, elongation_pct=18.0,
       water_consumption_l_per_kg=80.0, co2_footprint_kg_per_kg=3.5,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="'Bamboo' label often viscose process; crop itself low-input."),

    _m("seacell",
       "SeaCell (Seaweed Lyocell)", _MC, "seacell",
       density_gsm=120.0, tensile_strength_mpa=300.0, elongation_pct=14.0,
       water_consumption_l_per_kg=25.0, co2_footprint_kg_per_kg=2.7,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="Lyocell with seaweed integrated into fibre matrix."),

    # ------------------------------------------------------------------
    # Synthetic
    # ------------------------------------------------------------------
    _m("polyester_virgin",
       "Polyester (Virgin PET)", _SY, "virgin",
       density_gsm=150.0, tensile_strength_mpa=900.0, elongation_pct=25.0,
       water_consumption_l_per_kg=17.0, co2_footprint_kg_per_kg=9.5,
       biodegradable=False,
       certifications=("OEKO-TEX",),
       notes="PET from virgin PTA+MEG; dominant global fibre by volume."),

    _m("polyester_recycled",
       "Polyester (Recycled rPET)", _SY, "recycled",
       density_gsm=150.0, tensile_strength_mpa=870.0, elongation_pct=24.0,
       water_consumption_l_per_kg=10.0, co2_footprint_kg_per_kg=3.8,
       biodegradable=False,
       certifications=("GRS", "OEKO-TEX", "Bluesign"),
       notes="Bottle-to-fibre or fibre-to-fibre; 50–60% lower GHG than virgin."),

    _m("polyester_biobased",
       "Bio-PET (Biobased Polyester)", _SY, "biobased",
       density_gsm=150.0, tensile_strength_mpa=895.0, elongation_pct=25.0,
       water_consumption_l_per_kg=25.0, co2_footprint_kg_per_kg=6.1,
       biodegradable=False,
       notes="MEG from bio-ethanol; TPA still petrochemical."),

    _m("nylon_6_virgin",
       "Nylon 6 (Virgin PA6)", _SY, "virgin",
       density_gsm=80.0, tensile_strength_mpa=950.0, elongation_pct=28.0,
       water_consumption_l_per_kg=20.0, co2_footprint_kg_per_kg=9.2,
       biodegradable=False,
       certifications=("OEKO-TEX",),
       notes="Caprolactam polymerisation; high N₂O precursor risk."),

    _m("nylon_6_recycled",
       "Nylon 6 (Recycled / ECONYL®)", _SY, "recycled",
       density_gsm=80.0, tensile_strength_mpa=930.0, elongation_pct=27.0,
       water_consumption_l_per_kg=12.0, co2_footprint_kg_per_kg=5.0,
       biodegradable=False,
       certifications=("GRS", "Bluesign"),
       notes="ECONYL regeneration from fishing nets / carpet waste."),

    _m("nylon_66_virgin",
       "Nylon 66 (Virgin PA66)", _SY, "virgin",
       density_gsm=80.0, tensile_strength_mpa=1050.0, elongation_pct=26.0,
       water_consumption_l_per_kg=22.0, co2_footprint_kg_per_kg=11.8,
       biodegradable=False,
       certifications=("OEKO-TEX",),
       notes="Adipic acid route; higher GWP than PA6 due to N₂O."),

    _m("acrylic",
       "Acrylic (Polyacrylonitrile)", _SY, "conventional",
       density_gsm=140.0, tensile_strength_mpa=250.0, elongation_pct=30.0,
       water_consumption_l_per_kg=14.0, co2_footprint_kg_per_kg=7.9,
       biodegradable=False,
       certifications=("OEKO-TEX",),
       notes="Wool-look fibre; solvent-spinning; microplastic concern."),

    _m("spandex_elastane",
       "Spandex / Elastane (Lycra®)", _SY, "conventional",
       density_gsm=35.0, tensile_strength_mpa=17.0, elongation_pct=600.0,
       water_consumption_l_per_kg=18.0, co2_footprint_kg_per_kg=12.5,
       biodegradable=False,
       notes="Polyurethane-urea; typically blended at 2–20% for stretch."),

    _m("polypropylene",
       "Polypropylene (PP) Fibre", _SY, "conventional",
       density_gsm=60.0, tensile_strength_mpa=360.0, elongation_pct=50.0,
       water_consumption_l_per_kg=5.0, co2_footprint_kg_per_kg=3.9,
       biodegradable=False,
       notes="Lightest common textile fibre; used in activewear linings."),

    _m("polyethylene_hdpe",
       "Polyethylene (HDPE) Fibre", _SY, "conventional",
       density_gsm=70.0, tensile_strength_mpa=300.0, elongation_pct=40.0,
       water_consumption_l_per_kg=5.0, co2_footprint_kg_per_kg=3.5,
       biodegradable=False,
       notes="Used in Dyneema blends and moisture-wicking liners."),

    _m("polylactic_acid",
       "PLA Fibre (Ingeo™)", _SY, "biobased",
       density_gsm=120.0, tensile_strength_mpa=450.0, elongation_pct=25.0,
       water_consumption_l_per_kg=60.0, co2_footprint_kg_per_kg=3.1,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="Corn-starch PLA; industrially compostable only (EN 13432)."),

    # ------------------------------------------------------------------
    # Semi-synthetic
    # ------------------------------------------------------------------
    _m("acetate",
       "Acetate (Cellulose Diacetate)", _SS, "acetate",
       density_gsm=100.0, tensile_strength_mpa=180.0, elongation_pct=25.0,
       water_consumption_l_per_kg=90.0, co2_footprint_kg_per_kg=5.0,
       biodegradable=True,
       certifications=("OEKO-TEX",),
       notes="Acetic acid acetylation of cotton linters; silk-like hand."),

    _m("triacetate",
       "Triacetate (Cellulose Triacetate)", _SS, "triacetate",
       density_gsm=105.0, tensile_strength_mpa=190.0, elongation_pct=26.0,
       water_consumption_l_per_kg=95.0, co2_footprint_kg_per_kg=5.3,
       biodegradable=True,
       notes="Higher acetic acid substitution; washable pleats."),

    # ------------------------------------------------------------------
    # Leather
    # ------------------------------------------------------------------
    _m("leather_full_grain",
       "Leather (Full-Grain Bovine)", _LE, "full_grain",
       density_gsm=800.0, tensile_strength_mpa=17.0, elongation_pct=40.0,
       water_consumption_l_per_kg=17000.0, co2_footprint_kg_per_kg=110.0,
       biodegradable=True,
       certifications=("LWG",),
       notes="Chrome-tanned; LWG Gold rated tanneries. High CO₂ incl. cattle."),

    _m("leather_corrected_grain",
       "Leather (Corrected-Grain)", _LE, "corrected_grain",
       density_gsm=850.0, tensile_strength_mpa=14.0, elongation_pct=38.0,
       water_consumption_l_per_kg=17000.0, co2_footprint_kg_per_kg=112.0,
       biodegradable=True,
       certifications=("LWG",),
       notes="Surface sanding + coating; lower surface quality than full-grain."),

    _m("leather_suede",
       "Suede (Split Leather)", _LE, "suede",
       density_gsm=500.0, tensile_strength_mpa=10.0, elongation_pct=50.0,
       water_consumption_l_per_kg=17500.0, co2_footprint_kg_per_kg=115.0,
       biodegradable=True,
       notes="From the inner split; napped finish."),

    _m("leather_vegetable_tanned",
       "Leather (Vegetable-Tanned)", _LE, "veg_tanned",
       density_gsm=820.0, tensile_strength_mpa=16.0, elongation_pct=42.0,
       water_consumption_l_per_kg=18000.0, co2_footprint_kg_per_kg=95.0,
       biodegradable=True,
       certifications=("LWG",),
       notes="Bark/tannin tannage; slower process, no heavy metals."),

    _m("leather_pu_synthetic",
       "PU Leather (Synthetic / Vegan)", _LE, "pu_synthetic",
       density_gsm=600.0, tensile_strength_mpa=12.0, elongation_pct=60.0,
       water_consumption_l_per_kg=30.0, co2_footprint_kg_per_kg=10.5,
       biodegradable=False,
       certifications=("OEKO-TEX",),
       notes="Polyurethane coated split or woven base; no animal; petrochemical."),

    _m("leather_pu_biobased",
       "PU Leather (Bio-Based / Cactus/Mushroom)", _LE, "pu_biobased",
       density_gsm=580.0, tensile_strength_mpa=11.0, elongation_pct=55.0,
       water_consumption_l_per_kg=15.0, co2_footprint_kg_per_kg=5.8,
       biodegradable=False,
       certifications=("OEKO-TEX",),
       notes="Nopal cactus (Desserto) or mycelium (Bolt Threads Mylo) base."),

    _m("pinatex",
       "Piñatex (Pineapple Leaf Fibre)", _LE, "plant_based",
       density_gsm=480.0, tensile_strength_mpa=9.5, elongation_pct=50.0,
       water_consumption_l_per_kg=50.0, co2_footprint_kg_per_kg=3.8,
       biodegradable=False,
       certifications=("OEKO-TEX",),
       notes="Ananas Anam; pineapple leaf waste + PLA/PU coating."),

    # ------------------------------------------------------------------
    # Technical / high-performance
    # ------------------------------------------------------------------
    _m("aramid_para",
       "Para-Aramid (Kevlar®/Twaron®)", _TE, "para_aramid",
       density_gsm=200.0, tensile_strength_mpa=3600.0, elongation_pct=2.4,
       water_consumption_l_per_kg=350.0, co2_footprint_kg_per_kg=28.0,
       biodegradable=False,
       certifications=("OEKO-TEX",),
       notes="DuPont Kevlar / Teijin Twaron; ballistic and cut resistance."),

    _m("aramid_meta",
       "Meta-Aramid (Nomex®)", _TE, "meta_aramid",
       density_gsm=180.0, tensile_strength_mpa=700.0, elongation_pct=22.0,
       water_consumption_l_per_kg=310.0, co2_footprint_kg_per_kg=26.0,
       biodegradable=False,
       notes="Thermal / flame resistance; firefighter PPE."),

    _m("uhmwpe",
       "UHMWPE (Dyneema® / Spectra®)", _TE, "uhmwpe",
       density_gsm=90.0, tensile_strength_mpa=3500.0, elongation_pct=3.5,
       water_consumption_l_per_kg=8.0, co2_footprint_kg_per_kg=6.0,
       biodegradable=False,
       notes="Ultra-high molecular weight polyethylene; strongest textile."),

    _m("carbon_fibre_prepreg",
       "Carbon Fibre (PAN-based Prepreg)", _TE, "carbon_fibre",
       density_gsm=200.0, tensile_strength_mpa=4900.0, elongation_pct=1.8,
       water_consumption_l_per_kg=40.0, co2_footprint_kg_per_kg=29.5,
       biodegradable=False,
       notes="PAN oxidation + carbonisation; aerospace / motorsport."),

    _m("glass_fibre_e",
       "Glass Fibre (E-glass)", _TE, "glass_fibre",
       density_gsm=300.0, tensile_strength_mpa=3500.0, elongation_pct=4.8,
       water_consumption_l_per_kg=20.0, co2_footprint_kg_per_kg=2.8,
       biodegradable=False,
       notes="E-glass woven roving; electrical-grade borosilicate."),

    _m("basalt_fibre",
       "Basalt Fibre", _TE, "basalt",
       density_gsm=280.0, tensile_strength_mpa=4840.0, elongation_pct=3.1,
       water_consumption_l_per_kg=12.0, co2_footprint_kg_per_kg=2.1,
       biodegradable=False,
       notes="Continuous basalt rock fibre; low chemical additives."),

    _m("pbo_zylon",
       "PBO Fibre (Zylon®)", _TE, "pbo",
       density_gsm=170.0, tensile_strength_mpa=5800.0, elongation_pct=2.5,
       water_consumption_l_per_kg=400.0, co2_footprint_kg_per_kg=55.0,
       biodegradable=False,
       notes="Poly(p-phenylene-2,6-benzobisoxazole); highest tensile of any textile."),

    _m("stainless_steel_fibre",
       "Stainless Steel Fibre (Bekinox)", _TE, "metal_fibre",
       density_gsm=250.0, tensile_strength_mpa=1200.0, elongation_pct=12.0,
       water_consumption_l_per_kg=25.0, co2_footprint_kg_per_kg=3.5,
       biodegradable=False,
       notes="Bekaert Bekinox; EMI shielding, cut resistance, antistatic."),

    _m("ptfe_fibre",
       "PTFE Fibre (Teflon®)", _TE, "ptfe",
       density_gsm=120.0, tensile_strength_mpa=420.0, elongation_pct=25.0,
       water_consumption_l_per_kg=15.0, co2_footprint_kg_per_kg=18.5,
       biodegradable=False,
       notes="Chemical resistance; filtration; non-stick composites."),
]

# ---------------------------------------------------------------------------
# Build lookup dict
# ---------------------------------------------------------------------------

CATALOGUE: dict[str, TextileMaterial] = {m.material_id: m for m in _RAW_CATALOGUE}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def by_id(material_id: str) -> TextileMaterial:
    """
    Return a single :class:`TextileMaterial` by its unique ``material_id``.

    Raises
    ------
    KeyError
        If *material_id* is not in the catalogue.
    """
    try:
        return CATALOGUE[material_id]
    except KeyError:
        raise KeyError(
            f"Unknown material_id {material_id!r}. "
            f"Valid IDs: {sorted(CATALOGUE)}"
        )


def by_category(category: str) -> list[TextileMaterial]:
    """
    Return all materials whose ``category`` matches *category* (case-insensitive).

    Parameters
    ----------
    category : str
        One of the values in :data:`CATEGORIES`, e.g. ``"natural_cellulosic"``.

    Returns
    -------
    list[TextileMaterial]
        Possibly empty list, ordered as inserted in the catalogue.
    """
    cat_lower = category.lower()
    return [m for m in _RAW_CATALOGUE if m.category.lower() == cat_lower]


def by_subcategory(subcategory: str) -> list[TextileMaterial]:
    """Return all materials matching *subcategory* (case-insensitive)."""
    sub_lower = subcategory.lower()
    return [m for m in _RAW_CATALOGUE if m.subcategory.lower() == sub_lower]


def with_certification(cert: str) -> list[TextileMaterial]:
    """Return all materials that carry the given certification label."""
    return [m for m in _RAW_CATALOGUE if cert in m.certifications]


def biodegradable_materials() -> list[TextileMaterial]:
    """Return all materials flagged as biodegradable."""
    return [m for m in _RAW_CATALOGUE if m.biodegradable]


__all__ = [
    "TextileMaterial",
    "CATALOGUE",
    "CATEGORIES",
    "by_id",
    "by_category",
    "by_subcategory",
    "with_certification",
    "biodegradable_materials",
]
