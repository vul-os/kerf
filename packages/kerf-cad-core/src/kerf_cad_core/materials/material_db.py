"""
kerf_cad_core.materials.material_db — Cambridge Engineering Selector-equivalent
engineering material property database.

Provides a dataclass-based catalog of ~55 common engineering materials with
full property sets covering mechanical, thermal, electrical, cost, and
sustainability data.

HONEST FLAG: This catalog is a curated representative subset of engineering
materials based on publicly available textbook data. Production engineering
decisions should be validated against Granta MI (Ansys), CES EduPack, or
vendor data sheets. All values are typical mid-range estimates.

Data sources
------------
* Ashby, M.F. (2017). "Materials Selection in Mechanical Design." 5th ed.,
  Butterworth-Heinemann. (Appendix A: Data for engineering materials)
* Ashby, M.F. (2018). "Materials: Engineering, Science, Processing, Design."
  4th ed., Butterworth-Heinemann. (Appendix B: Attribute charts)
* Callister, W.D. & Rethwisch, D.G. (2018). "Materials Science and Engineering:
  An Introduction." 10th ed.
* ASM Handbook vol. 1 (Steel), vol. 2 (Non-ferrous), vol. 5 (Surface Engineering)
* ICE v3.0 (University of Bath Inventory of Carbon and Energy, 2019) for CO₂.
* MatWeb public category averages.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Material dataclass
# ---------------------------------------------------------------------------

@dataclass
class Material:
    """Engineering material with full property set.

    Mechanical properties follow SI engineering units as specified below.
    A value of None indicates the property is not typically quoted for this
    material class (e.g., fatigue endurance for most ceramics).

    References
    ----------
    Ashby (2017) §A, Ashby (2018) §B — property units and typical ranges.
    """

    name: str
    """Canonical short identifier, e.g. 'AISI_1018_steel', 'AA6061_T6'."""

    category: str
    """Material family: 'metal' | 'polymer' | 'ceramic' | 'composite' | 'natural'."""

    # ── Mechanical ──────────────────────────────────────────────────────────
    youngs_modulus_gpa: float
    """Young's modulus [GPa]. Source: Ashby (2017) App A."""

    yield_strength_mpa: float
    """0.2% proof / yield strength [MPa].
    For ceramics this is the flexural (MOR) or compressive strength.
    For composites this is the tensile strength (no classical yield)."""

    ultimate_strength_mpa: float
    """Ultimate tensile strength [MPa]. Equals yield_strength for ceramics."""

    density_kg_m3: float
    """Bulk density [kg/m³]. Ashby (2017) App A."""

    poisson: float
    """Poisson's ratio [-]. Ashby (2018) §B."""

    fatigue_endurance_mpa: float | None
    """Fully-reversed rotating-beam endurance limit (~10⁷ cycles) [MPa].
    None if not conventionally quoted (ceramics, elastomers, some composites).
    For polymers: fatigue endurance at 10⁷ cycles, or ~0.3 × UTS if unavailable."""

    # ── Thermal ─────────────────────────────────────────────────────────────
    thermal_conductivity_w_m_k: float
    """Thermal conductivity k [W/(m·K)]. Ashby (2017) App A."""

    thermal_expansion_per_k: float
    """Coefficient of thermal expansion CTE [1/K] (not µm/m·K).
    Ashby (2017) uses µm/(m·K) = 10⁻⁶/K; stored as 1/K here."""

    specific_heat_j_kg_k: float
    """Specific heat capacity Cp [J/(kg·K)]. Ashby (2018) §B."""

    melting_point_c: float | None
    """Approximate melting / solidus temperature [°C].
    None for amorphous or cross-linked materials (polymers, ceramics with no
    clear melting point)."""

    max_service_temp_c: float
    """Approximate maximum continuous service temperature [°C].
    Ashby (2018) §B; IEC 60085 for polymers."""

    # ── Electrical ──────────────────────────────────────────────────────────
    electrical_resistivity_ohm_m: float
    """Electrical resistivity ρ_e [Ω·m]. Ashby (2017) App A.
    Insulators/ceramics/polymers typically 10⁸–10¹⁶ Ω·m."""

    # ── Cost + Sustainability ────────────────────────────────────────────────
    cost_per_kg_usd: float
    """Approximate indicative material cost [USD/kg] (2024 CRU/Platts scaled
    to AISI 1018 mild steel ≈ 0.60 USD/kg). Not a purchasing price."""

    embodied_energy_mj_kg: float
    """Cradle-to-gate embodied energy [MJ/kg].
    ICE v3.0 (University of Bath, 2019); Ashby (2018) §B."""

    co2_footprint_kg_co2_per_kg: float
    """Cradle-to-gate CO₂-equivalent [kg CO₂-eq/kg].
    ICE v3.0 (University of Bath, 2019); EN 16485 for timber."""

    recyclable_fraction_pct: float = 100.0
    """Fraction of end-of-life material typically recycled [%].
    Ashby (2018) §B sustainability charts."""


# ---------------------------------------------------------------------------
# MaterialDatabase
# ---------------------------------------------------------------------------

@dataclass
class MaterialDatabase:
    """Container for a collection of Material objects with lookup and filter."""

    materials: list[Material] = field(default_factory=list)

    def by_name(self, name: str) -> Material:
        """Return the Material with the given name.

        Raises KeyError if not found.
        """
        for m in self.materials:
            if m.name == name:
                return m
        raise KeyError(f"Material {name!r} not found in database")

    def by_category(self, category: str) -> list[Material]:
        """Return all materials in the given category (case-insensitive)."""
        cat = category.lower()
        return [m for m in self.materials if m.category.lower() == cat]

    def filter(self, **constraints: Any) -> list[Material]:
        """Boolean filtering by min_/max_ keyword constraints.

        Keyword arguments are of the form:
            min_<property> = <float>   — require material.<property> >= value
            max_<property> = <float>   — require material.<property> <= value

        Example::

            db.filter(min_yield_strength_mpa=200, max_density_kg_m3=4500)

        Unknown or misspelled keywords raise ValueError.
        None-valued properties on a material always fail a constraint on
        that property.
        """
        # Parse constraints into (attr, op, value) triples
        parsed: list[tuple[str, str, float]] = []
        for key, value in constraints.items():
            if key.startswith("min_"):
                attr = key[4:]
                parsed.append((attr, ">=", float(value)))
            elif key.startswith("max_"):
                attr = key[4:]
                parsed.append((attr, "<=", float(value)))
            else:
                raise ValueError(
                    f"Constraint key {key!r} must start with 'min_' or 'max_'. "
                    f"Example: min_yield_strength_mpa=200"
                )
            # Validate the attribute exists on Material
            if not hasattr(Material, attr):
                # Check a sample material; attributes are dataclass fields
                import dataclasses
                field_names = {f.name for f in dataclasses.fields(Material)}
                if attr not in field_names:
                    raise ValueError(
                        f"Material has no property {attr!r}. "
                        f"Valid properties: {sorted(field_names)}"
                    )

        result: list[Material] = []
        for m in self.materials:
            ok = True
            for attr, op, val in parsed:
                mat_val = getattr(m, attr, None)
                if mat_val is None:
                    ok = False
                    break
                if op == ">=" and mat_val < val:
                    ok = False
                    break
                if op == "<=" and mat_val > val:
                    ok = False
                    break
            if ok:
                result.append(m)
        return result

    def __len__(self) -> int:
        return len(self.materials)

    def __iter__(self):
        return iter(self.materials)


# ---------------------------------------------------------------------------
# Default engineering materials catalog (~55 entries)
# ---------------------------------------------------------------------------

def default_engineering_materials_db() -> MaterialDatabase:
    """Return a built-in catalog of ~55 common engineering materials.

    Coverage
    --------
    * Steels: AISI 1018, 1045, 4140 Q&T, 4340 Q&T, 17-4PH, 304 SS, 316L SS
    * Aluminums: 1100-H14, 2024-T3, 6061-T6, 7075-T6
    * Titanium: Ti-6Al-4V, CP-Ti Grade 2
    * Magnesium: AZ31B
    * Copper alloys: ETP Cu, Brass C360, Beryllium copper C17200
    * Cast irons: Gray G25, Ductile 65-45-12
    * Nickel superalloy: Inconel 718
    * Polymers: PLA, ABS, PETG, PC, PA66, POM (Delrin), PEEK, UHMWPE, HDPE, PTFE, PP
    * Composites: CFRP unidirectional, CFRP quasi-isotropic, GFRP E-glass woven
    * Ceramics: Al₂O₃ 99%, SiC, ZrO₂ TZP, Si₃N₄
    * Natural/wood: Oak, Pine, Bamboo

    Data source: Ashby "Materials Selection in Mechanical Design" 5e (2017),
    Appendix A + Ashby "Materials: Engineering, Science, Processing, Design"
    4e (2018), Appendix B. Supplemented by Callister (2018) and ICE v3.0 for
    CO₂/embodied energy.

    HONEST: Values are typical mid-range textbook estimates. Always verify
    against Granta MI, vendor data sheets, or testing for production use.
    """
    mats: list[Material] = [

        # ── Carbon / Low-alloy steels ────────────────────────────────────────
        # Ashby (2017) §A pp.469–476; Callister (2018) Appendix B
        Material(
            name="AISI_1018_steel",
            category="metal",
            youngs_modulus_gpa=200.0,
            yield_strength_mpa=220.0,
            ultimate_strength_mpa=400.0,
            density_kg_m3=7850.0,
            poisson=0.29,
            fatigue_endurance_mpa=200.0,
            thermal_conductivity_w_m_k=51.9,
            thermal_expansion_per_k=11.7e-6,
            specific_heat_j_kg_k=486.0,
            melting_point_c=1480.0,
            max_service_temp_c=400.0,
            electrical_resistivity_ohm_m=1.6e-7,
            cost_per_kg_usd=0.60,
            embodied_energy_mj_kg=25.0,
            co2_footprint_kg_co2_per_kg=1.85,
            recyclable_fraction_pct=95.0,
        ),
        Material(
            name="AISI_1045_steel",
            category="metal",
            youngs_modulus_gpa=200.0,
            yield_strength_mpa=390.0,
            ultimate_strength_mpa=620.0,
            density_kg_m3=7850.0,
            poisson=0.29,
            fatigue_endurance_mpa=310.0,
            thermal_conductivity_w_m_k=49.8,
            thermal_expansion_per_k=11.7e-6,
            specific_heat_j_kg_k=486.0,
            melting_point_c=1460.0,
            max_service_temp_c=400.0,
            electrical_resistivity_ohm_m=1.7e-7,
            cost_per_kg_usd=0.70,
            embodied_energy_mj_kg=26.0,
            co2_footprint_kg_co2_per_kg=1.9,
            recyclable_fraction_pct=95.0,
        ),
        Material(
            name="AISI_4140_QT",
            category="metal",
            youngs_modulus_gpa=205.0,
            yield_strength_mpa=655.0,
            ultimate_strength_mpa=1020.0,
            density_kg_m3=7850.0,
            poisson=0.29,
            fatigue_endurance_mpa=510.0,
            thermal_conductivity_w_m_k=42.6,
            thermal_expansion_per_k=12.3e-6,
            specific_heat_j_kg_k=477.0,
            melting_point_c=1440.0,
            max_service_temp_c=450.0,
            electrical_resistivity_ohm_m=2.2e-7,
            cost_per_kg_usd=0.90,
            embodied_energy_mj_kg=28.0,
            co2_footprint_kg_co2_per_kg=2.0,
            recyclable_fraction_pct=90.0,
        ),
        Material(
            name="AISI_4340_QT",
            category="metal",
            youngs_modulus_gpa=205.0,
            yield_strength_mpa=1170.0,
            ultimate_strength_mpa=1280.0,
            density_kg_m3=7850.0,
            poisson=0.29,
            fatigue_endurance_mpa=640.0,
            thermal_conductivity_w_m_k=44.5,
            thermal_expansion_per_k=12.3e-6,
            specific_heat_j_kg_k=477.0,
            melting_point_c=1425.0,
            max_service_temp_c=450.0,
            electrical_resistivity_ohm_m=2.5e-7,
            cost_per_kg_usd=1.10,
            embodied_energy_mj_kg=30.0,
            co2_footprint_kg_co2_per_kg=2.1,
            recyclable_fraction_pct=90.0,
        ),

        # ── Stainless steels ─────────────────────────────────────────────────
        Material(
            name="SS_304",
            category="metal",
            youngs_modulus_gpa=193.0,
            yield_strength_mpa=215.0,
            ultimate_strength_mpa=505.0,
            density_kg_m3=8000.0,
            poisson=0.28,
            fatigue_endurance_mpa=240.0,
            thermal_conductivity_w_m_k=16.2,
            thermal_expansion_per_k=17.2e-6,
            specific_heat_j_kg_k=500.0,
            melting_point_c=1400.0,
            max_service_temp_c=870.0,
            electrical_resistivity_ohm_m=7.2e-7,
            cost_per_kg_usd=2.10,
            embodied_energy_mj_kg=56.0,
            co2_footprint_kg_co2_per_kg=6.15,
            recyclable_fraction_pct=92.0,
        ),
        Material(
            name="SS_316L",
            category="metal",
            youngs_modulus_gpa=193.0,
            yield_strength_mpa=170.0,
            ultimate_strength_mpa=485.0,
            density_kg_m3=8000.0,
            poisson=0.28,
            fatigue_endurance_mpa=230.0,
            thermal_conductivity_w_m_k=16.3,
            thermal_expansion_per_k=16.0e-6,
            specific_heat_j_kg_k=500.0,
            melting_point_c=1380.0,
            max_service_temp_c=870.0,
            electrical_resistivity_ohm_m=7.4e-7,
            cost_per_kg_usd=2.50,
            embodied_energy_mj_kg=58.0,
            co2_footprint_kg_co2_per_kg=6.3,
            recyclable_fraction_pct=92.0,
        ),
        Material(
            name="SS_17-4PH",
            category="metal",
            youngs_modulus_gpa=197.0,
            yield_strength_mpa=1170.0,
            ultimate_strength_mpa=1310.0,
            density_kg_m3=7780.0,
            poisson=0.27,
            fatigue_endurance_mpa=620.0,
            thermal_conductivity_w_m_k=18.3,
            thermal_expansion_per_k=10.8e-6,
            specific_heat_j_kg_k=460.0,
            melting_point_c=1400.0,
            max_service_temp_c=480.0,
            electrical_resistivity_ohm_m=8.0e-7,
            cost_per_kg_usd=3.60,
            embodied_energy_mj_kg=65.0,
            co2_footprint_kg_co2_per_kg=7.2,
            recyclable_fraction_pct=88.0,
        ),

        # ── Aluminium alloys ─────────────────────────────────────────────────
        # Ashby (2017) §A; ASM Handbook vol. 2
        Material(
            name="AA1100_H14",
            category="metal",
            youngs_modulus_gpa=69.0,
            yield_strength_mpa=117.0,
            ultimate_strength_mpa=124.0,
            density_kg_m3=2710.0,
            poisson=0.33,
            fatigue_endurance_mpa=41.0,
            thermal_conductivity_w_m_k=222.0,
            thermal_expansion_per_k=23.6e-6,
            specific_heat_j_kg_k=904.0,
            melting_point_c=652.0,
            max_service_temp_c=150.0,
            electrical_resistivity_ohm_m=2.9e-8,
            cost_per_kg_usd=1.80,
            embodied_energy_mj_kg=155.0,
            co2_footprint_kg_co2_per_kg=8.24,
            recyclable_fraction_pct=95.0,
        ),
        Material(
            name="AA2024_T3",
            category="metal",
            youngs_modulus_gpa=73.1,
            yield_strength_mpa=345.0,
            ultimate_strength_mpa=483.0,
            density_kg_m3=2780.0,
            poisson=0.33,
            fatigue_endurance_mpa=140.0,
            thermal_conductivity_w_m_k=121.0,
            thermal_expansion_per_k=23.2e-6,
            specific_heat_j_kg_k=875.0,
            melting_point_c=638.0,
            max_service_temp_c=130.0,
            electrical_resistivity_ohm_m=5.8e-8,
            cost_per_kg_usd=2.00,
            embodied_energy_mj_kg=170.0,
            co2_footprint_kg_co2_per_kg=9.0,
            recyclable_fraction_pct=90.0,
        ),
        Material(
            name="AA6061_T6",
            category="metal",
            youngs_modulus_gpa=69.0,
            yield_strength_mpa=276.0,
            ultimate_strength_mpa=310.0,
            density_kg_m3=2700.0,
            poisson=0.33,
            fatigue_endurance_mpa=97.0,
            thermal_conductivity_w_m_k=167.0,
            thermal_expansion_per_k=23.6e-6,
            specific_heat_j_kg_k=896.0,
            melting_point_c=652.0,
            max_service_temp_c=150.0,
            electrical_resistivity_ohm_m=3.7e-8,
            cost_per_kg_usd=1.90,
            embodied_energy_mj_kg=160.0,
            co2_footprint_kg_co2_per_kg=8.5,
            recyclable_fraction_pct=95.0,
        ),
        Material(
            name="AA7075_T6",
            category="metal",
            youngs_modulus_gpa=71.7,
            yield_strength_mpa=503.0,
            ultimate_strength_mpa=572.0,
            density_kg_m3=2810.0,
            poisson=0.33,
            fatigue_endurance_mpa=160.0,
            thermal_conductivity_w_m_k=130.0,
            thermal_expansion_per_k=23.6e-6,
            specific_heat_j_kg_k=860.0,
            melting_point_c=635.0,
            max_service_temp_c=120.0,
            electrical_resistivity_ohm_m=5.2e-8,
            cost_per_kg_usd=2.20,
            embodied_energy_mj_kg=175.0,
            co2_footprint_kg_co2_per_kg=9.2,
            recyclable_fraction_pct=90.0,
        ),

        # ── Titanium alloys ──────────────────────────────────────────────────
        # Ashby (2017) §A; ASM Handbook vol. 2
        Material(
            name="Ti-6Al-4V",
            category="metal",
            youngs_modulus_gpa=113.8,
            yield_strength_mpa=880.0,
            ultimate_strength_mpa=950.0,
            density_kg_m3=4430.0,
            poisson=0.342,
            fatigue_endurance_mpa=510.0,
            thermal_conductivity_w_m_k=7.2,
            thermal_expansion_per_k=8.6e-6,
            specific_heat_j_kg_k=560.0,
            melting_point_c=1660.0,
            max_service_temp_c=300.0,
            electrical_resistivity_ohm_m=1.7e-6,
            cost_per_kg_usd=12.0,
            embodied_energy_mj_kg=590.0,
            co2_footprint_kg_co2_per_kg=35.0,
            recyclable_fraction_pct=80.0,
        ),
        Material(
            name="CP_Ti_Grade2",
            category="metal",
            youngs_modulus_gpa=105.0,
            yield_strength_mpa=275.0,
            ultimate_strength_mpa=345.0,
            density_kg_m3=4510.0,
            poisson=0.37,
            fatigue_endurance_mpa=170.0,
            thermal_conductivity_w_m_k=16.4,
            thermal_expansion_per_k=8.9e-6,
            specific_heat_j_kg_k=528.0,
            melting_point_c=1670.0,
            max_service_temp_c=260.0,
            electrical_resistivity_ohm_m=5.6e-7,
            cost_per_kg_usd=9.0,
            embodied_energy_mj_kg=510.0,
            co2_footprint_kg_co2_per_kg=31.0,
            recyclable_fraction_pct=85.0,
        ),

        # ── Magnesium alloys ─────────────────────────────────────────────────
        Material(
            name="Mg_AZ31B",
            category="metal",
            youngs_modulus_gpa=45.0,
            yield_strength_mpa=200.0,
            ultimate_strength_mpa=262.0,
            density_kg_m3=1770.0,
            poisson=0.35,
            fatigue_endurance_mpa=90.0,
            thermal_conductivity_w_m_k=77.0,
            thermal_expansion_per_k=26.0e-6,
            specific_heat_j_kg_k=1020.0,
            melting_point_c=630.0,
            max_service_temp_c=120.0,
            electrical_resistivity_ohm_m=9.2e-8,
            cost_per_kg_usd=2.30,
            embodied_energy_mj_kg=350.0,
            co2_footprint_kg_co2_per_kg=18.0,
            recyclable_fraction_pct=80.0,
        ),

        # ── Copper alloys ────────────────────────────────────────────────────
        Material(
            name="Cu_ETP",
            category="metal",
            youngs_modulus_gpa=117.0,
            yield_strength_mpa=70.0,
            ultimate_strength_mpa=230.0,
            density_kg_m3=8940.0,
            poisson=0.34,
            fatigue_endurance_mpa=70.0,
            thermal_conductivity_w_m_k=390.0,
            thermal_expansion_per_k=17.0e-6,
            specific_heat_j_kg_k=385.0,
            melting_point_c=1083.0,
            max_service_temp_c=200.0,
            electrical_resistivity_ohm_m=1.7e-8,
            cost_per_kg_usd=3.00,
            embodied_energy_mj_kg=57.0,
            co2_footprint_kg_co2_per_kg=2.71,
            recyclable_fraction_pct=90.0,
        ),
        Material(
            name="Brass_C360",
            category="metal",
            youngs_modulus_gpa=97.0,
            yield_strength_mpa=124.0,
            ultimate_strength_mpa=340.0,
            density_kg_m3=8500.0,
            poisson=0.34,
            fatigue_endurance_mpa=100.0,
            thermal_conductivity_w_m_k=115.0,
            thermal_expansion_per_k=20.5e-6,
            specific_heat_j_kg_k=380.0,
            melting_point_c=900.0,
            max_service_temp_c=200.0,
            electrical_resistivity_ohm_m=6.2e-8,
            cost_per_kg_usd=2.70,
            embodied_energy_mj_kg=62.0,
            co2_footprint_kg_co2_per_kg=3.5,
            recyclable_fraction_pct=85.0,
        ),
        Material(
            name="BeCu_C17200",
            category="metal",
            youngs_modulus_gpa=128.0,
            yield_strength_mpa=1100.0,
            ultimate_strength_mpa=1240.0,
            density_kg_m3=8260.0,
            poisson=0.30,
            fatigue_endurance_mpa=400.0,
            thermal_conductivity_w_m_k=105.0,
            thermal_expansion_per_k=17.8e-6,
            specific_heat_j_kg_k=420.0,
            melting_point_c=980.0,
            max_service_temp_c=200.0,
            electrical_resistivity_ohm_m=7.8e-8,
            cost_per_kg_usd=21.0,
            embodied_energy_mj_kg=120.0,
            co2_footprint_kg_co2_per_kg=8.0,
            recyclable_fraction_pct=75.0,
        ),

        # ── Cast irons ───────────────────────────────────────────────────────
        Material(
            name="Gray_CI_G25",
            category="metal",
            youngs_modulus_gpa=105.0,
            yield_strength_mpa=165.0,
            ultimate_strength_mpa=180.0,
            density_kg_m3=7200.0,
            poisson=0.26,
            fatigue_endurance_mpa=85.0,
            thermal_conductivity_w_m_k=46.0,
            thermal_expansion_per_k=11.0e-6,
            specific_heat_j_kg_k=460.0,
            melting_point_c=1200.0,
            max_service_temp_c=300.0,
            electrical_resistivity_ohm_m=1.0e-6,
            cost_per_kg_usd=0.42,
            embodied_energy_mj_kg=19.0,
            co2_footprint_kg_co2_per_kg=1.51,
            recyclable_fraction_pct=95.0,
        ),
        Material(
            name="Ductile_CI_65-45-12",
            category="metal",
            youngs_modulus_gpa=169.0,
            yield_strength_mpa=310.0,
            ultimate_strength_mpa=450.0,
            density_kg_m3=7100.0,
            poisson=0.28,
            fatigue_endurance_mpa=210.0,
            thermal_conductivity_w_m_k=36.0,
            thermal_expansion_per_k=12.5e-6,
            specific_heat_j_kg_k=460.0,
            melting_point_c=1150.0,
            max_service_temp_c=350.0,
            electrical_resistivity_ohm_m=5.5e-7,
            cost_per_kg_usd=0.54,
            embodied_energy_mj_kg=21.0,
            co2_footprint_kg_co2_per_kg=1.7,
            recyclable_fraction_pct=95.0,
        ),

        # ── Nickel superalloy ────────────────────────────────────────────────
        Material(
            name="Inconel_718",
            category="metal",
            youngs_modulus_gpa=200.0,
            yield_strength_mpa=1034.0,
            ultimate_strength_mpa=1240.0,
            density_kg_m3=8190.0,
            poisson=0.30,
            fatigue_endurance_mpa=500.0,
            thermal_conductivity_w_m_k=11.4,
            thermal_expansion_per_k=13.0e-6,
            specific_heat_j_kg_k=435.0,
            melting_point_c=1300.0,
            max_service_temp_c=700.0,
            electrical_resistivity_ohm_m=1.25e-6,
            cost_per_kg_usd=15.0,
            embodied_energy_mj_kg=210.0,
            co2_footprint_kg_co2_per_kg=14.0,
            recyclable_fraction_pct=70.0,
        ),

        # ── Polymers ─────────────────────────────────────────────────────────
        # Ashby (2018) §B; Callister (2018) Appendix B
        Material(
            name="PLA",
            category="polymer",
            youngs_modulus_gpa=3.5,
            yield_strength_mpa=55.0,
            ultimate_strength_mpa=60.0,
            density_kg_m3=1240.0,
            poisson=0.36,
            fatigue_endurance_mpa=18.0,
            thermal_conductivity_w_m_k=0.13,
            thermal_expansion_per_k=68e-6,
            specific_heat_j_kg_k=1800.0,
            melting_point_c=175.0,
            max_service_temp_c=55.0,
            electrical_resistivity_ohm_m=1e14,
            cost_per_kg_usd=1.50,
            embodied_energy_mj_kg=54.0,
            co2_footprint_kg_co2_per_kg=2.6,
            recyclable_fraction_pct=20.0,
        ),
        Material(
            name="ABS",
            category="polymer",
            youngs_modulus_gpa=2.1,
            yield_strength_mpa=40.0,
            ultimate_strength_mpa=45.0,
            density_kg_m3=1050.0,
            poisson=0.40,
            fatigue_endurance_mpa=15.0,
            thermal_conductivity_w_m_k=0.17,
            thermal_expansion_per_k=95e-6,
            specific_heat_j_kg_k=1400.0,
            melting_point_c=None,
            max_service_temp_c=80.0,
            electrical_resistivity_ohm_m=1e15,
            cost_per_kg_usd=1.40,
            embodied_energy_mj_kg=95.0,
            co2_footprint_kg_co2_per_kg=3.5,
            recyclable_fraction_pct=30.0,
        ),
        Material(
            name="PETG",
            category="polymer",
            youngs_modulus_gpa=2.1,
            yield_strength_mpa=50.0,
            ultimate_strength_mpa=53.0,
            density_kg_m3=1270.0,
            poisson=0.38,
            fatigue_endurance_mpa=16.0,
            thermal_conductivity_w_m_k=0.20,
            thermal_expansion_per_k=72e-6,
            specific_heat_j_kg_k=1300.0,
            melting_point_c=250.0,
            max_service_temp_c=75.0,
            electrical_resistivity_ohm_m=1e14,
            cost_per_kg_usd=1.60,
            embodied_energy_mj_kg=77.0,
            co2_footprint_kg_co2_per_kg=3.1,
            recyclable_fraction_pct=25.0,
        ),
        Material(
            name="PC",
            category="polymer",
            youngs_modulus_gpa=2.4,
            yield_strength_mpa=55.0,
            ultimate_strength_mpa=65.0,
            density_kg_m3=1200.0,
            poisson=0.37,
            fatigue_endurance_mpa=22.0,
            thermal_conductivity_w_m_k=0.20,
            thermal_expansion_per_k=65e-6,
            specific_heat_j_kg_k=1250.0,
            melting_point_c=None,
            max_service_temp_c=120.0,
            electrical_resistivity_ohm_m=1e14,
            cost_per_kg_usd=1.80,
            embodied_energy_mj_kg=112.0,
            co2_footprint_kg_co2_per_kg=5.2,
            recyclable_fraction_pct=20.0,
        ),
        Material(
            name="PA66",
            category="polymer",
            youngs_modulus_gpa=2.8,
            yield_strength_mpa=55.0,
            ultimate_strength_mpa=80.0,
            density_kg_m3=1140.0,
            poisson=0.40,
            fatigue_endurance_mpa=25.0,
            thermal_conductivity_w_m_k=0.25,
            thermal_expansion_per_k=80e-6,
            specific_heat_j_kg_k=1700.0,
            melting_point_c=260.0,
            max_service_temp_c=120.0,
            electrical_resistivity_ohm_m=1e13,
            cost_per_kg_usd=1.90,
            embodied_energy_mj_kg=138.0,
            co2_footprint_kg_co2_per_kg=6.4,
            recyclable_fraction_pct=20.0,
        ),
        Material(
            name="POM_Delrin",
            category="polymer",
            youngs_modulus_gpa=3.1,
            yield_strength_mpa=65.0,
            ultimate_strength_mpa=70.0,
            density_kg_m3=1410.0,
            poisson=0.35,
            fatigue_endurance_mpa=28.0,
            thermal_conductivity_w_m_k=0.31,
            thermal_expansion_per_k=110e-6,
            specific_heat_j_kg_k=1460.0,
            melting_point_c=175.0,
            max_service_temp_c=100.0,
            electrical_resistivity_ohm_m=1e14,
            cost_per_kg_usd=1.70,
            embodied_energy_mj_kg=103.0,
            co2_footprint_kg_co2_per_kg=4.2,
            recyclable_fraction_pct=20.0,
        ),
        Material(
            name="PEEK",
            category="polymer",
            youngs_modulus_gpa=3.6,
            yield_strength_mpa=91.0,
            ultimate_strength_mpa=100.0,
            density_kg_m3=1320.0,
            poisson=0.40,
            fatigue_endurance_mpa=40.0,
            thermal_conductivity_w_m_k=0.25,
            thermal_expansion_per_k=47e-6,
            specific_heat_j_kg_k=1340.0,
            melting_point_c=343.0,
            max_service_temp_c=250.0,
            electrical_resistivity_ohm_m=1e15,
            cost_per_kg_usd=36.0,
            embodied_energy_mj_kg=280.0,
            co2_footprint_kg_co2_per_kg=14.0,
            recyclable_fraction_pct=10.0,
        ),
        Material(
            name="UHMWPE",
            category="polymer",
            youngs_modulus_gpa=0.7,
            yield_strength_mpa=21.0,
            ultimate_strength_mpa=35.0,
            density_kg_m3=930.0,
            poisson=0.46,
            fatigue_endurance_mpa=10.0,
            thermal_conductivity_w_m_k=0.44,
            thermal_expansion_per_k=130e-6,
            specific_heat_j_kg_k=1900.0,
            melting_point_c=135.0,
            max_service_temp_c=80.0,
            electrical_resistivity_ohm_m=1e16,
            cost_per_kg_usd=1.80,
            embodied_energy_mj_kg=83.0,
            co2_footprint_kg_co2_per_kg=2.7,
            recyclable_fraction_pct=15.0,
        ),
        Material(
            name="HDPE",
            category="polymer",
            youngs_modulus_gpa=0.9,
            yield_strength_mpa=25.0,
            ultimate_strength_mpa=30.0,
            density_kg_m3=950.0,
            poisson=0.44,
            fatigue_endurance_mpa=10.0,
            thermal_conductivity_w_m_k=0.44,
            thermal_expansion_per_k=130e-6,
            specific_heat_j_kg_k=1900.0,
            melting_point_c=130.0,
            max_service_temp_c=80.0,
            electrical_resistivity_ohm_m=1e16,
            cost_per_kg_usd=0.80,
            embodied_energy_mj_kg=80.0,
            co2_footprint_kg_co2_per_kg=1.9,
            recyclable_fraction_pct=35.0,
        ),
        Material(
            name="PTFE",
            category="polymer",
            youngs_modulus_gpa=0.5,
            yield_strength_mpa=12.0,
            ultimate_strength_mpa=25.0,
            density_kg_m3=2200.0,
            poisson=0.46,
            fatigue_endurance_mpa=8.0,
            thermal_conductivity_w_m_k=0.25,
            thermal_expansion_per_k=120e-6,
            specific_heat_j_kg_k=1050.0,
            melting_point_c=327.0,
            max_service_temp_c=260.0,
            electrical_resistivity_ohm_m=1e16,
            cost_per_kg_usd=6.00,
            embodied_energy_mj_kg=125.0,
            co2_footprint_kg_co2_per_kg=7.0,
            recyclable_fraction_pct=10.0,
        ),
        Material(
            name="PP",
            category="polymer",
            youngs_modulus_gpa=1.5,
            yield_strength_mpa=31.0,
            ultimate_strength_mpa=35.0,
            density_kg_m3=905.0,
            poisson=0.42,
            fatigue_endurance_mpa=12.0,
            thermal_conductivity_w_m_k=0.17,
            thermal_expansion_per_k=100e-6,
            specific_heat_j_kg_k=1920.0,
            melting_point_c=165.0,
            max_service_temp_c=100.0,
            electrical_resistivity_ohm_m=1e16,
            cost_per_kg_usd=0.90,
            embodied_energy_mj_kg=73.0,
            co2_footprint_kg_co2_per_kg=1.9,
            recyclable_fraction_pct=30.0,
        ),

        # ── Composites ───────────────────────────────────────────────────────
        # Ashby (2017) §A; CES EduPack public excerpts
        Material(
            name="CFRP_unidirectional",
            category="composite",
            youngs_modulus_gpa=135.0,   # 0° lamina; Ashby (2017) §A
            yield_strength_mpa=1500.0,  # tensile strength (no classical yield)
            ultimate_strength_mpa=1500.0,
            density_kg_m3=1550.0,
            poisson=0.28,
            fatigue_endurance_mpa=700.0,
            thermal_conductivity_w_m_k=5.0,
            thermal_expansion_per_k=0.5e-6,  # axial; near-zero for HM fibre
            specific_heat_j_kg_k=840.0,
            melting_point_c=None,
            max_service_temp_c=150.0,
            electrical_resistivity_ohm_m=1e-4,  # CF layers are conductive
            cost_per_kg_usd=25.0,
            embodied_energy_mj_kg=286.0,
            co2_footprint_kg_co2_per_kg=29.0,
            recyclable_fraction_pct=10.0,
        ),
        Material(
            name="CFRP_quasi_iso",
            category="composite",
            youngs_modulus_gpa=55.0,   # quasi-isotropic laminate; Ashby (2017) §A
            yield_strength_mpa=550.0,
            ultimate_strength_mpa=550.0,
            density_kg_m3=1570.0,
            poisson=0.30,
            fatigue_endurance_mpa=260.0,
            thermal_conductivity_w_m_k=3.0,
            thermal_expansion_per_k=3.0e-6,
            specific_heat_j_kg_k=840.0,
            melting_point_c=None,
            max_service_temp_c=150.0,
            electrical_resistivity_ohm_m=1e-3,
            cost_per_kg_usd=24.0,
            embodied_energy_mj_kg=280.0,
            co2_footprint_kg_co2_per_kg=28.0,
            recyclable_fraction_pct=10.0,
        ),
        Material(
            name="GFRP_E-glass_woven",
            category="composite",
            youngs_modulus_gpa=20.0,   # woven; Ashby (2017) §A
            yield_strength_mpa=230.0,
            ultimate_strength_mpa=280.0,
            density_kg_m3=1850.0,
            poisson=0.30,
            fatigue_endurance_mpa=100.0,
            thermal_conductivity_w_m_k=0.35,
            thermal_expansion_per_k=12.0e-6,
            specific_heat_j_kg_k=840.0,
            melting_point_c=None,
            max_service_temp_c=150.0,
            electrical_resistivity_ohm_m=1e10,
            cost_per_kg_usd=3.00,
            embodied_energy_mj_kg=54.0,
            co2_footprint_kg_co2_per_kg=3.7,
            recyclable_fraction_pct=5.0,
        ),

        # ── Ceramics ─────────────────────────────────────────────────────────
        # Ashby (2017) §A — compressive/flexural strengths; no fatigue endurance
        Material(
            name="Al2O3_99pct",
            category="ceramic",
            youngs_modulus_gpa=380.0,
            yield_strength_mpa=260.0,   # flexural strength (MOR)
            ultimate_strength_mpa=260.0,
            density_kg_m3=3960.0,
            poisson=0.22,
            fatigue_endurance_mpa=None,
            thermal_conductivity_w_m_k=30.0,
            thermal_expansion_per_k=8.1e-6,
            specific_heat_j_kg_k=775.0,
            melting_point_c=2050.0,
            max_service_temp_c=1600.0,
            electrical_resistivity_ohm_m=1e12,
            cost_per_kg_usd=7.00,
            embodied_energy_mj_kg=80.0,
            co2_footprint_kg_co2_per_kg=3.2,
            recyclable_fraction_pct=0.0,
        ),
        Material(
            name="SiC",
            category="ceramic",
            youngs_modulus_gpa=410.0,
            yield_strength_mpa=400.0,
            ultimate_strength_mpa=400.0,
            density_kg_m3=3160.0,
            poisson=0.17,
            fatigue_endurance_mpa=None,
            thermal_conductivity_w_m_k=120.0,
            thermal_expansion_per_k=4.0e-6,
            specific_heat_j_kg_k=750.0,
            melting_point_c=2730.0,
            max_service_temp_c=1500.0,
            electrical_resistivity_ohm_m=1e2,  # semi-conducting grade
            cost_per_kg_usd=30.0,
            embodied_energy_mj_kg=95.0,
            co2_footprint_kg_co2_per_kg=5.3,
            recyclable_fraction_pct=0.0,
        ),
        Material(
            name="ZrO2_TZP",
            category="ceramic",
            youngs_modulus_gpa=210.0,
            yield_strength_mpa=1000.0,  # flexural strength — highest of common ceramics
            ultimate_strength_mpa=1000.0,
            density_kg_m3=6050.0,
            poisson=0.31,
            fatigue_endurance_mpa=None,
            thermal_conductivity_w_m_k=2.0,
            thermal_expansion_per_k=10.5e-6,
            specific_heat_j_kg_k=450.0,
            melting_point_c=2715.0,
            max_service_temp_c=900.0,
            electrical_resistivity_ohm_m=1e10,
            cost_per_kg_usd=18.0,
            embodied_energy_mj_kg=130.0,
            co2_footprint_kg_co2_per_kg=5.8,
            recyclable_fraction_pct=0.0,
        ),
        Material(
            name="Si3N4",
            category="ceramic",
            youngs_modulus_gpa=300.0,
            yield_strength_mpa=700.0,
            ultimate_strength_mpa=700.0,
            density_kg_m3=3200.0,
            poisson=0.28,
            fatigue_endurance_mpa=None,
            thermal_conductivity_w_m_k=30.0,
            thermal_expansion_per_k=3.2e-6,
            specific_heat_j_kg_k=710.0,
            melting_point_c=1900.0,
            max_service_temp_c=1200.0,
            electrical_resistivity_ohm_m=1e12,
            cost_per_kg_usd=48.0,
            embodied_energy_mj_kg=120.0,
            co2_footprint_kg_co2_per_kg=6.0,
            recyclable_fraction_pct=0.0,
        ),

        # ── Natural / Wood ───────────────────────────────────────────────────
        # Ashby (2018) §B; EN 16485 CO₂ (fossil-only, biogenic credit excluded)
        Material(
            name="Oak_red",
            category="natural",
            youngs_modulus_gpa=12.5,   # along grain
            yield_strength_mpa=52.0,   # compressive parallel to grain
            ultimate_strength_mpa=100.0,  # tensile MOR
            density_kg_m3=740.0,
            poisson=0.35,
            fatigue_endurance_mpa=30.0,
            thermal_conductivity_w_m_k=0.17,
            thermal_expansion_per_k=4.2e-6,
            specific_heat_j_kg_k=1760.0,
            melting_point_c=None,
            max_service_temp_c=70.0,
            electrical_resistivity_ohm_m=1e11,
            cost_per_kg_usd=0.30,
            embodied_energy_mj_kg=10.4,
            co2_footprint_kg_co2_per_kg=0.46,
            recyclable_fraction_pct=50.0,
        ),
        Material(
            name="Pine_structural",
            category="natural",
            youngs_modulus_gpa=13.0,
            yield_strength_mpa=38.0,
            ultimate_strength_mpa=85.0,
            density_kg_m3=530.0,
            poisson=0.35,
            fatigue_endurance_mpa=25.0,
            thermal_conductivity_w_m_k=0.14,
            thermal_expansion_per_k=3.8e-6,
            specific_heat_j_kg_k=1760.0,
            melting_point_c=None,
            max_service_temp_c=70.0,
            electrical_resistivity_ohm_m=1e11,
            cost_per_kg_usd=0.20,
            embodied_energy_mj_kg=7.4,
            co2_footprint_kg_co2_per_kg=0.39,
            recyclable_fraction_pct=50.0,
        ),
        Material(
            name="Bamboo_structural",
            category="natural",
            youngs_modulus_gpa=17.0,    # culm; excellent E/ρ — Ashby (2018) §B
            yield_strength_mpa=160.0,   # tensile along grain
            ultimate_strength_mpa=190.0,
            density_kg_m3=700.0,
            poisson=0.25,
            fatigue_endurance_mpa=60.0,
            thermal_conductivity_w_m_k=0.15,
            thermal_expansion_per_k=6.0e-6,
            specific_heat_j_kg_k=1400.0,
            melting_point_c=None,
            max_service_temp_c=60.0,
            electrical_resistivity_ohm_m=1e10,
            cost_per_kg_usd=0.15,
            embodied_energy_mj_kg=6.0,
            co2_footprint_kg_co2_per_kg=0.26,
            recyclable_fraction_pct=60.0,
        ),

        # ── Additional steels and metals ─────────────────────────────────────
        # Ashby (2017) §A; Callister (2018) Appendix B
        Material(
            name="AISI_1020_steel",
            category="metal",
            youngs_modulus_gpa=200.0,
            yield_strength_mpa=210.0,
            ultimate_strength_mpa=380.0,
            density_kg_m3=7850.0,
            poisson=0.29,
            fatigue_endurance_mpa=190.0,
            thermal_conductivity_w_m_k=51.9,
            thermal_expansion_per_k=11.7e-6,
            specific_heat_j_kg_k=486.0,
            melting_point_c=1480.0,
            max_service_temp_c=400.0,
            electrical_resistivity_ohm_m=1.6e-7,
            cost_per_kg_usd=0.58,
            embodied_energy_mj_kg=24.0,
            co2_footprint_kg_co2_per_kg=1.80,
            recyclable_fraction_pct=95.0,
        ),
        # A36 structural steel — Ashby (2017) §A; AISC specification
        Material(
            name="A36_structural_steel",
            category="metal",
            youngs_modulus_gpa=200.0,
            yield_strength_mpa=250.0,
            ultimate_strength_mpa=400.0,
            density_kg_m3=7850.0,
            poisson=0.29,
            fatigue_endurance_mpa=200.0,
            thermal_conductivity_w_m_k=50.0,
            thermal_expansion_per_k=11.7e-6,
            specific_heat_j_kg_k=486.0,
            melting_point_c=1480.0,
            max_service_temp_c=400.0,
            electrical_resistivity_ohm_m=1.7e-7,
            cost_per_kg_usd=0.55,
            embodied_energy_mj_kg=24.0,
            co2_footprint_kg_co2_per_kg=1.82,
            recyclable_fraction_pct=95.0,
        ),
        # D2 tool steel — Ashby (2017) §A; high carbon chromium
        Material(
            name="D2_tool_steel",
            category="metal",
            youngs_modulus_gpa=210.0,
            yield_strength_mpa=1400.0,
            ultimate_strength_mpa=1500.0,
            density_kg_m3=7700.0,
            poisson=0.28,
            fatigue_endurance_mpa=700.0,
            thermal_conductivity_w_m_k=20.0,
            thermal_expansion_per_k=10.4e-6,
            specific_heat_j_kg_k=460.0,
            melting_point_c=1421.0,
            max_service_temp_c=300.0,
            electrical_resistivity_ohm_m=4.5e-7,
            cost_per_kg_usd=3.50,
            embodied_energy_mj_kg=40.0,
            co2_footprint_kg_co2_per_kg=3.0,
            recyclable_fraction_pct=85.0,
        ),
        # AA5052-H32 — marine/structural aluminum — ASM vol. 2
        Material(
            name="AA5052_H32",
            category="metal",
            youngs_modulus_gpa=70.0,
            yield_strength_mpa=193.0,
            ultimate_strength_mpa=228.0,
            density_kg_m3=2680.0,
            poisson=0.33,
            fatigue_endurance_mpa=117.0,
            thermal_conductivity_w_m_k=138.0,
            thermal_expansion_per_k=23.8e-6,
            specific_heat_j_kg_k=880.0,
            melting_point_c=607.0,
            max_service_temp_c=150.0,
            electrical_resistivity_ohm_m=4.9e-8,
            cost_per_kg_usd=1.75,
            embodied_energy_mj_kg=155.0,
            co2_footprint_kg_co2_per_kg=8.2,
            recyclable_fraction_pct=95.0,
        ),
        # Hastelloy C-276 — Nickel corrosion alloy — Ashby (2017) §A
        Material(
            name="Hastelloy_C276",
            category="metal",
            youngs_modulus_gpa=205.0,
            yield_strength_mpa=283.0,
            ultimate_strength_mpa=690.0,
            density_kg_m3=8890.0,
            poisson=0.30,
            fatigue_endurance_mpa=250.0,
            thermal_conductivity_w_m_k=10.2,
            thermal_expansion_per_k=11.2e-6,
            specific_heat_j_kg_k=427.0,
            melting_point_c=1325.0,
            max_service_temp_c=1040.0,
            electrical_resistivity_ohm_m=1.3e-6,
            cost_per_kg_usd=13.0,
            embodied_energy_mj_kg=190.0,
            co2_footprint_kg_co2_per_kg=13.0,
            recyclable_fraction_pct=65.0,
        ),

        # ── Additional polymers ──────────────────────────────────────────────
        # Ashby (2018) §B; Callister (2018) Appendix B
        # PEI (Ultem 1010) — high-performance thermoplastic
        Material(
            name="PEI_Ultem",
            category="polymer",
            youngs_modulus_gpa=3.0,
            yield_strength_mpa=105.0,
            ultimate_strength_mpa=110.0,
            density_kg_m3=1270.0,
            poisson=0.36,
            fatigue_endurance_mpa=42.0,
            thermal_conductivity_w_m_k=0.22,
            thermal_expansion_per_k=56e-6,
            specific_heat_j_kg_k=1300.0,
            melting_point_c=None,  # amorphous
            max_service_temp_c=170.0,
            electrical_resistivity_ohm_m=1e15,
            cost_per_kg_usd=22.0,
            embodied_energy_mj_kg=200.0,
            co2_footprint_kg_co2_per_kg=9.5,
            recyclable_fraction_pct=10.0,
        ),
        # Epoxy thermoset — Ashby (2017) §A
        Material(
            name="Epoxy_thermoset",
            category="polymer",
            youngs_modulus_gpa=3.5,
            yield_strength_mpa=60.0,
            ultimate_strength_mpa=65.0,
            density_kg_m3=1250.0,
            poisson=0.38,
            fatigue_endurance_mpa=22.0,
            thermal_conductivity_w_m_k=0.20,
            thermal_expansion_per_k=60e-6,
            specific_heat_j_kg_k=1100.0,
            melting_point_c=None,
            max_service_temp_c=120.0,
            electrical_resistivity_ohm_m=1e13,
            cost_per_kg_usd=4.00,
            embodied_energy_mj_kg=140.0,
            co2_footprint_kg_co2_per_kg=7.0,
            recyclable_fraction_pct=5.0,
        ),

        # ── Additional composites ────────────────────────────────────────────
        # Kevlar-49 UD composite — Ashby (2017) §A; DuPont data
        Material(
            name="Kevlar49_UD",
            category="composite",
            youngs_modulus_gpa=76.0,    # axial; Ashby (2017) §A
            yield_strength_mpa=1400.0,  # tensile strength
            ultimate_strength_mpa=1400.0,
            density_kg_m3=1380.0,
            poisson=0.34,
            fatigue_endurance_mpa=500.0,
            thermal_conductivity_w_m_k=0.04,
            thermal_expansion_per_k=-2.0e-6,  # negative CTE axial
            specific_heat_j_kg_k=1420.0,
            melting_point_c=None,
            max_service_temp_c=160.0,
            electrical_resistivity_ohm_m=1e12,
            cost_per_kg_usd=28.0,
            embodied_energy_mj_kg=200.0,
            co2_footprint_kg_co2_per_kg=12.0,
            recyclable_fraction_pct=5.0,
        ),

        # ── Additional ceramics ──────────────────────────────────────────────
        # Borosilicate glass — Pyrex; Ashby (2017) §A
        Material(
            name="Borosilicate_glass",
            category="ceramic",
            youngs_modulus_gpa=64.0,
            yield_strength_mpa=30.0,   # flexural/tensile MOR
            ultimate_strength_mpa=50.0,
            density_kg_m3=2230.0,
            poisson=0.20,
            fatigue_endurance_mpa=None,
            thermal_conductivity_w_m_k=1.2,
            thermal_expansion_per_k=3.3e-6,
            specific_heat_j_kg_k=750.0,
            melting_point_c=820.0,
            max_service_temp_c=450.0,
            electrical_resistivity_ohm_m=1e12,
            cost_per_kg_usd=1.50,
            embodied_energy_mj_kg=15.0,
            co2_footprint_kg_co2_per_kg=0.85,
            recyclable_fraction_pct=75.0,
        ),
    ]

    return MaterialDatabase(materials=mats)
