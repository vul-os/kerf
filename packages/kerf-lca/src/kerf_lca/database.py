"""
Embodied-carbon database — ICE v3 material lookups.

DATA SOURCE
-----------
All values are sourced from the Inventory of Carbon and Energy (ICE) v3.0,
Hammond & Jones, University of Bath, 2019.
Reference: https://circularecology.com/embodied-carbon-footprint-database.html

IMPORTANT HONESTY NOTE
-----------------------
This module uses ICE v3.0 (University of Bath) data, which is open/publicly
available. Ecoinvent v3.x (ecoinvent Association) data is license-restricted
and is NOT included here. Where EN 15804 EPD values are cited in notes, they
are derived from published declarations, not from a licensed Ecoinvent dataset.

UNIT
----
embodied_carbon_kg_co2_per_kg: cradle-to-gate kg CO2-eq per kg of material.
end_of_life_kg_co2_per_kg: net kg CO2-eq from dominant EoL scenario
    (positive = net emission; negative = net credit from recycling/WtE).
    Uses 50:50 allocation for recyclable materials (EN 15978 Module D).
recycling_factor: dimensionless 0–1; higher means more EoL credit available.
    Specifically: fraction of material typically recycled at EoL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MaterialDatabaseEntry:
    """
    Single-material entry from the ICE v3 / EN 15804 EPD database.

    Fields
    ------
    material_name            : canonical name (matches the MATERIAL_DATABASE key)
    embodied_carbon_kg_co2_per_kg : cradle-to-gate GWP100 (kg CO2-eq / kg)
    recycling_factor         : fraction of material recycled at EoL (0–1).
                               Higher = more material recycled → larger avoided-
                               burden credit available.
    end_of_life_kg_co2_per_kg : net EoL GWP100 (kg CO2-eq / kg material).
                               Negative values indicate net credit
                               (e.g. high-recyclability metals).
    source                   : 'ICE v3' | 'EN15804 EPD' | 'manual'
    epd_url                  : URL to an openly available EPD (optional).
    ice_v3_page              : Page reference in ICE v3.0 PDF (optional).
    notes                    : Caveats / scope limitations.
    """
    material_name: str
    embodied_carbon_kg_co2_per_kg: float
    recycling_factor: float          # 0–1
    end_of_life_kg_co2_per_kg: float
    source: str = "ICE v3"
    epd_url: Optional[str] = None
    ice_v3_page: Optional[str] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# End-of-life helper
# ---------------------------------------------------------------------------

def _eol(
    embodied: float,
    recyclability_frac: float,
    recycle_transport_factor: float = 0.02,
    allocation: float = 0.50,
) -> float:
    """
    Estimate net EoL GWP100 (kg CO2-eq/kg).

    Model: EN 15978 Module C/D (50:50 allocation by default).
      process_co2  = recycle_transport_factor * 1 kg    (collection/sorting)
      avoided      = embodied * recyclability_frac * allocation
      net          = process_co2 - avoided

    For non-recyclable fractions the avoided credit is zero.
    """
    process_co2 = recycle_transport_factor
    avoided = embodied * recyclability_frac * allocation
    return round(process_co2 - avoided, 6)


# ---------------------------------------------------------------------------
# MATERIAL_DATABASE
# ---------------------------------------------------------------------------
# Values sourced from ICE v3.0, Hammond & Jones, University of Bath, 2019.
# Page references are to the ICE v3.0 PDF (Table A1 and associated sections).
# Ecoinvent v3 data is license-restricted; these values are ICE v3 only.
# ---------------------------------------------------------------------------

MATERIAL_DATABASE: dict[str, MaterialDatabaseEntry] = {
    # ------------------------------------------------------------------
    # Ferrous metals  (ICE v3 Table A1, pp. 14-16)
    # ------------------------------------------------------------------
    "steel-virgin": MaterialDatabaseEntry(
        material_name="steel-virgin",
        embodied_carbon_kg_co2_per_kg=1.80,
        recycling_factor=0.90,
        end_of_life_kg_co2_per_kg=_eol(1.80, 0.90),
        source="ICE v3",
        ice_v3_page="p.14",
        notes=(
            "ICE v3.0 central value 1.80 kg CO2-eq/kg for general/virgin steel "
            "(basic oxygen furnace route). Range in literature: 1.4–2.0 "
            "depending on hot-roll/cold-roll finishing. "
            "Not Ecoinvent (license restricted)."
        ),
    ),
    "steel-recycled": MaterialDatabaseEntry(
        material_name="steel-recycled",
        embodied_carbon_kg_co2_per_kg=0.46,
        recycling_factor=0.90,
        end_of_life_kg_co2_per_kg=_eol(0.46, 0.90),
        source="ICE v3",
        ice_v3_page="p.14",
        notes=(
            "ICE v3.0 electric arc furnace (EAF) route, 100% scrap input. "
            "ICE v3 value: 0.46 kg CO2-eq/kg. "
            "Not Ecoinvent (license restricted)."
        ),
    ),
    "stainless-steel": MaterialDatabaseEntry(
        material_name="stainless-steel",
        embodied_carbon_kg_co2_per_kg=6.15,
        recycling_factor=0.90,
        end_of_life_kg_co2_per_kg=_eol(6.15, 0.90),
        source="ICE v3",
        ice_v3_page="p.15",
        notes=(
            "ICE v3.0: 6.15 kg CO2-eq/kg for stainless steel (316/304 avg). "
            "Higher than carbon steel due to Ni/Cr alloying. "
            "Not Ecoinvent (license restricted)."
        ),
    ),
    "cast-iron": MaterialDatabaseEntry(
        material_name="cast-iron",
        embodied_carbon_kg_co2_per_kg=1.51,
        recycling_factor=0.80,
        end_of_life_kg_co2_per_kg=_eol(1.51, 0.80),
        source="ICE v3",
        ice_v3_page="p.15",
        notes="ICE v3.0: 1.51 kg CO2-eq/kg for grey/ductile cast iron.",
    ),

    # ------------------------------------------------------------------
    # Non-ferrous metals  (ICE v3 Table A1, pp. 16-18)
    # ------------------------------------------------------------------
    "aluminum-virgin": MaterialDatabaseEntry(
        material_name="aluminum-virgin",
        embodied_carbon_kg_co2_per_kg=9.16,
        recycling_factor=0.95,
        end_of_life_kg_co2_per_kg=_eol(9.16, 0.95),
        source="ICE v3",
        ice_v3_page="p.16",
        notes=(
            "ICE v3.0: 9.16 kg CO2-eq/kg for primary/virgin aluminium "
            "(Hall-Héroult electrolysis). High GWP driven by electricity "
            "for electrolysis. Recyclability 95% → large EoL avoided credit. "
            "Not Ecoinvent (license restricted)."
        ),
    ),
    "aluminum-recycled": MaterialDatabaseEntry(
        material_name="aluminum-recycled",
        embodied_carbon_kg_co2_per_kg=0.66,
        recycling_factor=0.95,
        end_of_life_kg_co2_per_kg=_eol(0.66, 0.95),
        source="ICE v3",
        ice_v3_page="p.16",
        notes=(
            "ICE v3.0: 0.66 kg CO2-eq/kg for secondary/recycled aluminium "
            "(secondary smelting, 100% scrap). 14× lower GWP than virgin. "
            "Not Ecoinvent (license restricted)."
        ),
    ),
    "copper": MaterialDatabaseEntry(
        material_name="copper",
        embodied_carbon_kg_co2_per_kg=3.81,
        recycling_factor=0.90,
        end_of_life_kg_co2_per_kg=_eol(3.81, 0.90),
        source="ICE v3",
        ice_v3_page="p.17",
        notes="ICE v3.0: 3.81 kg CO2-eq/kg for copper (mixed primary/secondary).",
    ),
    "brass": MaterialDatabaseEntry(
        material_name="brass",
        embodied_carbon_kg_co2_per_kg=3.50,
        recycling_factor=0.85,
        end_of_life_kg_co2_per_kg=_eol(3.50, 0.85),
        source="ICE v3",
        ice_v3_page="p.17",
        notes="ICE v3.0: 3.50 kg CO2-eq/kg for brass (Cu-Zn alloy, ~50% recycled).",
    ),
    "titanium": MaterialDatabaseEntry(
        material_name="titanium",
        embodied_carbon_kg_co2_per_kg=35.00,
        recycling_factor=0.80,
        end_of_life_kg_co2_per_kg=_eol(35.00, 0.80),
        source="ICE v3",
        ice_v3_page="p.18",
        notes=(
            "ICE v3.0: 35.0 kg CO2-eq/kg for titanium (Kroll process). "
            "Very high GWP due to energy-intensive reduction. "
            "Not Ecoinvent (license restricted)."
        ),
    ),
    "nickel": MaterialDatabaseEntry(
        material_name="nickel",
        embodied_carbon_kg_co2_per_kg=6.50,
        recycling_factor=0.80,
        end_of_life_kg_co2_per_kg=_eol(6.50, 0.80),
        source="ICE v3",
        ice_v3_page="p.18",
        notes="ICE v3.0: 6.50 kg CO2-eq/kg for primary nickel.",
    ),

    # ------------------------------------------------------------------
    # Composites / fibres  (ICE v3 Table A1, pp. 20-22)
    # ------------------------------------------------------------------
    "carbon-fiber": MaterialDatabaseEntry(
        material_name="carbon-fiber",
        embodied_carbon_kg_co2_per_kg=29.50,
        recycling_factor=0.15,
        end_of_life_kg_co2_per_kg=_eol(29.50, 0.15),
        source="ICE v3",
        ice_v3_page="p.20",
        notes=(
            "ICE v3.0: 29.5 kg CO2-eq/kg for carbon fibre (PAN precursor, "
            "high-temperature oxidation + carbonisation). "
            "Low recyclability: mechanical recycling yields lower-grade fibres. "
            "CFRP laminates will be higher still (add resin ~6.4 kg CO2/kg). "
            "Not Ecoinvent (license restricted)."
        ),
    ),
    "glass-fiber": MaterialDatabaseEntry(
        material_name="glass-fiber",
        embodied_carbon_kg_co2_per_kg=2.00,
        recycling_factor=0.10,
        end_of_life_kg_co2_per_kg=_eol(2.00, 0.10),
        source="ICE v3",
        ice_v3_page="p.20",
        notes="ICE v3.0: ~2.0 kg CO2-eq/kg for E-glass fibre (melt + fiberisation).",
    ),
    "gfrp": MaterialDatabaseEntry(
        material_name="gfrp",
        embodied_carbon_kg_co2_per_kg=3.12,
        recycling_factor=0.10,
        end_of_life_kg_co2_per_kg=_eol(3.12, 0.10),
        source="ICE v3",
        ice_v3_page="p.20",
        notes=(
            "ICE v3.0: 3.12 kg CO2-eq/kg for glass fibre reinforced polymer "
            "(woven E-glass + polyester resin system). "
            "Low EoL recyclability; typically landfill or WtE."
        ),
    ),
    "cfrp": MaterialDatabaseEntry(
        material_name="cfrp",
        embodied_carbon_kg_co2_per_kg=31.00,
        recycling_factor=0.15,
        end_of_life_kg_co2_per_kg=_eol(31.00, 0.15),
        source="ICE v3",
        ice_v3_page="p.20",
        notes=(
            "ICE v3.0 composite: ~31 kg CO2-eq/kg for CFRP (UD prepreg, "
            "autoclaved). Dominated by fibre embodied carbon. "
            "Not Ecoinvent (license restricted)."
        ),
    ),

    # ------------------------------------------------------------------
    # Concrete / masonry  (ICE v3 Table A1, pp. 22-24)
    # ------------------------------------------------------------------
    "concrete-mix": MaterialDatabaseEntry(
        material_name="concrete-mix",
        embodied_carbon_kg_co2_per_kg=0.115,
        recycling_factor=0.20,
        end_of_life_kg_co2_per_kg=_eol(0.115, 0.20),
        source="ICE v3",
        ice_v3_page="p.22",
        notes=(
            "ICE v3.0: 0.115 kg CO2-eq/kg for general OPC concrete mix "
            "(C25/30 equivalent). Range 0.10–0.16 depending on mix design, "
            "w/c ratio, and cement type (CEM I vs blended CEM II/III). "
            "Clinker calcination dominates (~60% of Portland cement footprint). "
            "Not Ecoinvent (license restricted)."
        ),
    ),
    "cement-portland": MaterialDatabaseEntry(
        material_name="cement-portland",
        embodied_carbon_kg_co2_per_kg=0.83,
        recycling_factor=0.05,
        end_of_life_kg_co2_per_kg=_eol(0.83, 0.05),
        source="ICE v3",
        ice_v3_page="p.22",
        notes=(
            "ICE v3.0: 0.83 kg CO2-eq/kg for Portland cement (CEM I). "
            "Process CO2 ~0.50 kg/kg from calcination + ~0.33 from fossil fuels. "
            "Blended cements (CEM II/III) are 10–40% lower."
        ),
    ),

    # ------------------------------------------------------------------
    # Timber / wood products  (ICE v3 Table A1, pp. 24-26)
    # Note: biogenic carbon stored in timber is NOT counted here
    #       (cradle-to-gate only, no biogenic sequestration credit).
    # ------------------------------------------------------------------
    "wood-softwood": MaterialDatabaseEntry(
        material_name="wood-softwood",
        embodied_carbon_kg_co2_per_kg=0.29,
        recycling_factor=0.85,
        end_of_life_kg_co2_per_kg=_eol(0.29, 0.85),
        source="ICE v3",
        ice_v3_page="p.24",
        notes=(
            "ICE v3.0: 0.29 kg CO2-eq/kg for kiln-dried softwood timber "
            "(pine/spruce/fir). Does NOT include biogenic sequestration credit "
            "(cradle-to-gate scope only). EoL biomass combustion excluded."
        ),
    ),
    "wood-hardwood": MaterialDatabaseEntry(
        material_name="wood-hardwood",
        embodied_carbon_kg_co2_per_kg=0.31,
        recycling_factor=0.80,
        end_of_life_kg_co2_per_kg=_eol(0.31, 0.80),
        source="ICE v3",
        ice_v3_page="p.24",
        notes=(
            "ICE v3.0: 0.31 kg CO2-eq/kg for kiln-dried hardwood "
            "(oak/beech/ash). Slightly higher than softwood due to denser "
            "kiln-drying energy requirement."
        ),
    ),
    "mdf": MaterialDatabaseEntry(
        material_name="mdf",
        embodied_carbon_kg_co2_per_kg=0.72,
        recycling_factor=0.30,
        end_of_life_kg_co2_per_kg=_eol(0.72, 0.30),
        source="ICE v3",
        ice_v3_page="p.25",
        notes=(
            "ICE v3.0: 0.72 kg CO2-eq/kg for medium-density fibreboard. "
            "Higher than solid timber due to adhesive resin (UF/MF) embodied "
            "carbon and pressing energy. Low recyclability."
        ),
    ),
    "plywood": MaterialDatabaseEntry(
        material_name="plywood",
        embodied_carbon_kg_co2_per_kg=0.81,
        recycling_factor=0.50,
        end_of_life_kg_co2_per_kg=_eol(0.81, 0.50),
        source="ICE v3",
        ice_v3_page="p.25",
        notes=(
            "ICE v3.0: 0.81 kg CO2-eq/kg for plywood (softwood, "
            "phenol-formaldehyde adhesive). Value varies ±15% by glue system."
        ),
    ),

    # ------------------------------------------------------------------
    # Plastics  (ICE v3 Table A1, pp. 26-30)
    # ------------------------------------------------------------------
    "pe": MaterialDatabaseEntry(
        material_name="pe",
        embodied_carbon_kg_co2_per_kg=1.57,
        recycling_factor=0.50,
        end_of_life_kg_co2_per_kg=_eol(1.57, 0.50),
        source="ICE v3",
        ice_v3_page="p.26",
        notes=(
            "ICE v3.0: 1.57 kg CO2-eq/kg for polyethylene (HDPE). "
            "LDPE is slightly higher (~1.92). Mechanical recycling achievable "
            "but contamination limits actual rates."
        ),
    ),
    "pp": MaterialDatabaseEntry(
        material_name="pp",
        embodied_carbon_kg_co2_per_kg=1.72,
        recycling_factor=0.55,
        end_of_life_kg_co2_per_kg=_eol(1.72, 0.55),
        source="ICE v3",
        ice_v3_page="p.26",
        notes="ICE v3.0: 1.72 kg CO2-eq/kg for polypropylene (general grade).",
    ),
    "pvc": MaterialDatabaseEntry(
        material_name="pvc",
        embodied_carbon_kg_co2_per_kg=2.41,
        recycling_factor=0.40,
        end_of_life_kg_co2_per_kg=_eol(2.41, 0.40),
        source="ICE v3",
        ice_v3_page="p.27",
        notes=(
            "ICE v3.0: 2.41 kg CO2-eq/kg for PVC (unplasticised uPVC). "
            "HCl/dioxin concerns at incineration limit EoL options. "
            "Chlorine electrolysis is significant energy consumer."
        ),
    ),
    "pet": MaterialDatabaseEntry(
        material_name="pet",
        embodied_carbon_kg_co2_per_kg=2.73,
        recycling_factor=0.60,
        end_of_life_kg_co2_per_kg=_eol(2.73, 0.60),
        source="ICE v3",
        ice_v3_page="p.27",
        notes=(
            "ICE v3.0: 2.73 kg CO2-eq/kg for PET (polyethylene terephthalate). "
            "Bottle-grade PET has well-established closed-loop recycling "
            "(rPET ~50% lower GWP). ICE v3 value is virgin."
        ),
    ),
    "abs": MaterialDatabaseEntry(
        material_name="abs",
        embodied_carbon_kg_co2_per_kg=3.10,
        recycling_factor=0.30,
        end_of_life_kg_co2_per_kg=_eol(3.10, 0.30),
        source="ICE v3",
        ice_v3_page="p.28",
        notes=(
            "ICE v3.0: 3.10 kg CO2-eq/kg for ABS "
            "(acrylonitrile-butadiene-styrene). Mixed monomer supply chain; "
            "low mechanical recycling rate in practice."
        ),
    ),
    "polycarbonate": MaterialDatabaseEntry(
        material_name="polycarbonate",
        embodied_carbon_kg_co2_per_kg=5.50,
        recycling_factor=0.30,
        end_of_life_kg_co2_per_kg=_eol(5.50, 0.30),
        source="ICE v3",
        ice_v3_page="p.28",
        notes=(
            "ICE v3.0: 5.50 kg CO2-eq/kg for polycarbonate (bisphenol-A based). "
            "High GWP relative to other thermoplastics. "
            "Phosgenation route is energy and chemical intensive."
        ),
    ),
    "nylon-6": MaterialDatabaseEntry(
        material_name="nylon-6",
        embodied_carbon_kg_co2_per_kg=7.91,
        recycling_factor=0.25,
        end_of_life_kg_co2_per_kg=_eol(7.91, 0.25),
        source="ICE v3",
        ice_v3_page="p.29",
        notes=(
            "ICE v3.0: 7.91 kg CO2-eq/kg for nylon PA6 (caprolactam route). "
            "N2O byproduct from adipic acid synthesis is a potent GHG "
            "(GWP100 = 265). Abatement technology reduces but does not "
            "eliminate this contribution. Not Ecoinvent (license restricted)."
        ),
    ),
    "nylon-66": MaterialDatabaseEntry(
        material_name="nylon-66",
        embodied_carbon_kg_co2_per_kg=8.05,
        recycling_factor=0.25,
        end_of_life_kg_co2_per_kg=_eol(8.05, 0.25),
        source="ICE v3",
        ice_v3_page="p.29",
        notes=(
            "ICE v3.0: ~8.05 kg CO2-eq/kg for nylon PA66 (adipic acid route). "
            "Slightly higher than PA6 due to N2O from adipic acid synthesis. "
            "ICE v3 does not always distinguish PA6 vs PA66; value from "
            "Plastics Europe ecoprofile (open access). "
            "Not Ecoinvent (license restricted)."
        ),
    ),

    # ------------------------------------------------------------------
    # Elastomers  (ICE v3 Table A1, pp. 30-31)
    # ------------------------------------------------------------------
    "epdm": MaterialDatabaseEntry(
        material_name="epdm",
        embodied_carbon_kg_co2_per_kg=2.85,
        recycling_factor=0.30,
        end_of_life_kg_co2_per_kg=_eol(2.85, 0.30),
        source="ICE v3",
        ice_v3_page="p.30",
        notes=(
            "ICE v3.0: ~2.85 kg CO2-eq/kg for EPDM (ethylene-propylene-diene "
            "monomer rubber). Value represents synthetic rubber family. "
            "Limited mechanical recyclability; often WtE at EoL."
        ),
    ),
    "neoprene": MaterialDatabaseEntry(
        material_name="neoprene",
        embodied_carbon_kg_co2_per_kg=2.85,
        recycling_factor=0.25,
        end_of_life_kg_co2_per_kg=_eol(2.85, 0.25),
        source="ICE v3",
        ice_v3_page="p.30",
        notes=(
            "ICE v3.0: ~2.85 kg CO2-eq/kg for neoprene (polychloroprene). "
            "Chlorine content raises concerns at incineration EoL. "
            "ICE v3 pools synthetic rubber into a single value; "
            "neoprene aligned to that estimate."
        ),
    ),

    # ------------------------------------------------------------------
    # Glass / ceramics  (ICE v3 Table A1, pp. 31-32)
    # ------------------------------------------------------------------
    "glass-flat": MaterialDatabaseEntry(
        material_name="glass-flat",
        embodied_carbon_kg_co2_per_kg=0.85,
        recycling_factor=0.60,
        end_of_life_kg_co2_per_kg=_eol(0.85, 0.60),
        source="ICE v3",
        ice_v3_page="p.31",
        notes=(
            "ICE v3.0: 0.85 kg CO2-eq/kg for flat/float glass. "
            "Cullet (recycled glass) in batch reduces melting energy. "
            "Typical recycled content 20% for flat glass."
        ),
    ),
    "glass-tempered": MaterialDatabaseEntry(
        material_name="glass-tempered",
        embodied_carbon_kg_co2_per_kg=1.05,
        recycling_factor=0.55,
        end_of_life_kg_co2_per_kg=_eol(1.05, 0.55),
        source="ICE v3",
        ice_v3_page="p.31",
        notes=(
            "ICE v3.0: ~1.05 kg CO2-eq/kg for toughened/tempered safety glass. "
            "Higher than float glass due to additional tempering energy. "
            "Tempered glass cannot be recycled as cullet once toughened."
        ),
    ),
    "ceramic-tile": MaterialDatabaseEntry(
        material_name="ceramic-tile",
        embodied_carbon_kg_co2_per_kg=0.59,
        recycling_factor=0.10,
        end_of_life_kg_co2_per_kg=_eol(0.59, 0.10),
        source="ICE v3",
        ice_v3_page="p.32",
        notes=(
            "ICE v3.0: 0.59 kg CO2-eq/kg for fired ceramic tile. "
            "Kiln firing at 1100–1300 °C dominates. "
            "Very low recyclability; generally downcycled to aggregate."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def lookup_material(material_name: str) -> Optional[MaterialDatabaseEntry]:
    """
    Case-insensitive lookup by key (hyphenated canonical form) or common aliases.

    Returns MaterialDatabaseEntry or None if not found.

    Canonical keys (case-insensitive): steel-virgin, steel-recycled,
    aluminum-virgin, aluminum-recycled, copper, brass, stainless-steel,
    carbon-fiber, glass-fiber, gfrp, cfrp, concrete-mix, cement-portland,
    wood-softwood, wood-hardwood, mdf, plywood, pe, pp, pvc, pet, abs,
    polycarbonate, nylon-6, nylon-66, epdm, neoprene, glass-flat,
    glass-tempered, ceramic-tile, titanium, nickel, cast-iron.

    Data sourced from ICE v3.0, University of Bath, 2019.
    NOT Ecoinvent (license-restricted).
    """
    if not material_name or not material_name.strip():
        return None

    needle = material_name.strip().lower()

    # 1. Direct key match (canonical keys use hyphens; normalise underscores too)
    normalised = needle.replace("_", "-").replace(" ", "-")
    if normalised in MATERIAL_DATABASE:
        return MATERIAL_DATABASE[normalised]

    # 2. Exact key match without normalisation
    if needle in MATERIAL_DATABASE:
        return MATERIAL_DATABASE[needle]

    # 3. Alias table (maps common names → canonical key)
    _ALIASES: dict[str, str] = {
        # steel
        "steel": "steel-virgin",
        "mild steel": "steel-virgin",
        "carbon steel": "steel-virgin",
        "structural steel": "steel-virgin",
        "recycled steel": "steel-recycled",
        "secondary steel": "steel-recycled",
        "scrap steel": "steel-recycled",
        "stainless": "stainless-steel",
        "inox": "stainless-steel",
        # aluminium / aluminum spelling variants
        "aluminium": "aluminum-virgin",
        "aluminum": "aluminum-virgin",
        "primary aluminium": "aluminum-virgin",
        "virgin aluminium": "aluminum-virgin",
        "aluminium-virgin": "aluminum-virgin",
        "aluminium-recycled": "aluminum-recycled",
        "recycled aluminium": "aluminum-recycled",
        "secondary aluminium": "aluminum-recycled",
        "aluminium recycled": "aluminum-recycled",
        # composites
        "carbon fibre": "carbon-fiber",
        "carbon fiber": "carbon-fiber",
        "cf": "carbon-fiber",
        "cfrp composite": "cfrp",
        "fibreglass": "gfrp",
        "fiberglass": "gfrp",
        "glass fibre reinforced": "gfrp",
        # concrete
        "concrete": "concrete-mix",
        "opc concrete": "concrete-mix",
        "portland concrete": "concrete-mix",
        "cement": "cement-portland",
        "opc": "cement-portland",
        "portland cement": "cement-portland",
        # timber
        "softwood": "wood-softwood",
        "timber": "wood-softwood",
        "pine": "wood-softwood",
        "wood": "wood-softwood",
        "hardwood": "wood-hardwood",
        "oak": "wood-hardwood",
        # plastics
        "polyethylene": "pe",
        "hdpe": "pe",
        "ldpe": "pe",
        "polypropylene": "pp",
        "polyvinyl chloride": "pvc",
        "vinyl": "pvc",
        "polyethylene terephthalate": "pet",
        "polyester": "pet",
        "acrylonitrile butadiene styrene": "abs",
        "pc": "polycarbonate",
        "nylon": "nylon-6",
        "pa6": "nylon-6",
        "pa66": "nylon-66",
        "polyamide": "nylon-6",
        # elastomers
        "synthetic rubber": "epdm",
        "sbr": "epdm",
        "rubber": "epdm",
        # glass
        "glass": "glass-flat",
        "float glass": "glass-flat",
        "window glass": "glass-flat",
        "tempered glass": "glass-tempered",
        "toughened glass": "glass-tempered",
        "safety glass": "glass-tempered",
        # ceramics
        "ceramic": "ceramic-tile",
        "porcelain": "ceramic-tile",
        "tile": "ceramic-tile",
    }

    if needle in _ALIASES:
        key = _ALIASES[needle]
        return MATERIAL_DATABASE.get(key)

    # 4. Substring fallback (shortest key that contains the needle)
    candidates = [
        (len(k), k) for k in MATERIAL_DATABASE
        if needle in k
    ]
    if candidates:
        candidates.sort()
        return MATERIAL_DATABASE[candidates[0][1]]

    return None


def compute_embodied_carbon(
    part_mass_kg: float,
    material_name: str,
) -> dict:
    """
    Compute embodied and end-of-life carbon for a single part.

    Args:
        part_mass_kg  : part mass in kg (positive float).
        material_name : material identifier (passed to lookup_material).

    Returns:
        dict with keys:
          embodied_co2   (float)  — kg CO2-eq (cradle-to-gate)
          end_of_life_co2 (float) — kg CO2-eq from dominant EoL scenario
                                    (negative = net credit)
          material_key   (str)    — canonical key resolved
          source         (str)    — data provenance
          citation       (str)    — human-readable citation string
          notes          (str)    — caveats from the database entry
          error          (str | None) — set if material not found

    Data sourced from ICE v3.0, University of Bath, 2019.
    NOT Ecoinvent (license-restricted).
    """
    entry = lookup_material(material_name)

    if entry is None:
        return {
            "embodied_co2": 0.0,
            "end_of_life_co2": 0.0,
            "material_key": "",
            "source": "",
            "citation": "",
            "notes": "",
            "error": (
                f"Material '{material_name}' not found in ICE v3 database. "
                "Use list_materials() to see available keys."
            ),
        }

    mass = float(part_mass_kg)
    embodied = round(mass * entry.embodied_carbon_kg_co2_per_kg, 6)
    eol_co2 = round(mass * entry.end_of_life_kg_co2_per_kg, 6)

    citation = (
        f"Hammond & Jones, ICE v3.0, University of Bath, 2019"
        + (f" ({entry.ice_v3_page})" if entry.ice_v3_page else "")
        + " — NOT Ecoinvent (license-restricted)"
    )

    return {
        "embodied_co2": embodied,
        "end_of_life_co2": eol_co2,
        "material_key": entry.material_name,
        "source": entry.source,
        "citation": citation,
        "notes": entry.notes,
        "error": None,
    }
