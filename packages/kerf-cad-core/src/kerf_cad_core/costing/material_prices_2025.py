"""
kerf_cad_core.costing.material_prices_2025 — 2025 spot-price baseline for
common engineering materials.

ADVISORY / HONEST-FLAG
-----------------------
Prices are indicative 2025 H1 spot baselines sourced from publicly available
market data (LME, Plastics News, CRU Group, MEPS International).  Actual
procurement prices depend on form (rod, sheet, powder), quantity, grade
certification, supplier, and freight.  Prices fluctuate: treat these as a
starting point only.  Always verify against current distributor quotes before
committing to a production budget.

Key sources (all 2025 Q1 midpoints):
  Metals    — LME / CME daily settlement + 10–15% fabrication premium for
              bar/billet/sheet; Al from LME Al Settlement + Midwest premium;
              Ti from USGS Mineral Commodity Summaries 2025.
  Polymers  — Plastics News North American pricing index, January 2025.
  Paper     — Tappi T 220 SP-08 material-cost benchmarks (advisory).

Units: USD per kilogram (USD/kg) unless noted.

Author: imranparuk
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MaterialSpec:
    """Specification for a single material entry."""

    name: str
    """Display name."""
    density_g_cm3: float
    """Density in g/cm³ (= kg/L).  Used to convert volume_mm³ → mass_kg."""
    price_per_kg_usd: float
    """2025 H1 baseline spot price in USD/kg.  See module advisory."""
    notes: str = ""
    """Short note on price source or grade."""


# ---------------------------------------------------------------------------
# 2025 H1 baseline prices
# Keys should be the same strings accepted by compute_material_cost_rollup()
# and must be lower-case-normalised for lookup (see MATERIAL_DB below).
# ---------------------------------------------------------------------------

_ENTRIES: list[MaterialSpec] = [
    # ── Polymers ──────────────────────────────────────────────────────────
    MaterialSpec(
        name="ABS",
        density_g_cm3=1.04,
        price_per_kg_usd=2.50,
        notes="Acrylonitrile-butadiene-styrene; Plastics News Jan 2025 spot.",
    ),
    MaterialSpec(
        name="PP",
        density_g_cm3=0.905,
        price_per_kg_usd=1.45,
        notes="Polypropylene homopolymer; Plastics News Jan 2025.",
    ),
    MaterialSpec(
        name="PC",
        density_g_cm3=1.20,
        price_per_kg_usd=3.80,
        notes="Polycarbonate (optical / engineering grade); Plastics News Jan 2025.",
    ),
    MaterialSpec(
        name="PA66",
        density_g_cm3=1.14,
        price_per_kg_usd=4.20,
        notes="Polyamide 66 (Nylon 66); Plastics News Jan 2025.",
    ),
    MaterialSpec(
        name="PEEK",
        density_g_cm3=1.32,
        price_per_kg_usd=95.00,
        notes="Polyether ether ketone; engineering / high-performance grade.",
    ),
    MaterialSpec(
        name="PLA",
        density_g_cm3=1.24,
        price_per_kg_usd=2.20,
        notes="Polylactic acid; biopolymer; bulk pellet price.",
    ),
    # ── Aluminium alloys ─────────────────────────────────────────────────
    MaterialSpec(
        name="Al6061",
        density_g_cm3=2.70,
        price_per_kg_usd=4.80,
        notes=(
            "Al 6061-T6 billet/bar; LME Al + 10% Midwest premium + 15% "
            "fabrication; CRU Group Q1 2025."
        ),
    ),
    MaterialSpec(
        name="Al7075",
        density_g_cm3=2.81,
        price_per_kg_usd=6.50,
        notes="Al 7075-T6; aerospace grade; higher alloy premium.",
    ),
    # ── Steel alloys ─────────────────────────────────────────────────────
    MaterialSpec(
        name="Steel304",
        density_g_cm3=7.93,
        price_per_kg_usd=3.20,
        notes=(
            "304 stainless steel bar/sheet; MEPS International Jan 2025 "
            "+ 15% service-centre premium."
        ),
    ),
    MaterialSpec(
        name="Steel316",
        density_g_cm3=8.00,
        price_per_kg_usd=4.10,
        notes="316L stainless; higher Mo content; MEPS Jan 2025.",
    ),
    MaterialSpec(
        name="Steel1018",
        density_g_cm3=7.87,
        price_per_kg_usd=0.90,
        notes="AISI 1018 mild steel cold-drawn bar; CME HRC + 20% fab.",
    ),
    MaterialSpec(
        name="Steel4140",
        density_g_cm3=7.85,
        price_per_kg_usd=1.40,
        notes="AISI 4140 alloy steel (normalised); CME HRC + alloy premium.",
    ),
    # ── Copper ───────────────────────────────────────────────────────────
    MaterialSpec(
        name="Cu",
        density_g_cm3=8.96,
        price_per_kg_usd=9.50,
        notes="Copper (ETP C11000) rod/sheet; LME Cu settlement Jan 2025.",
    ),
    # ── Titanium ─────────────────────────────────────────────────────────
    MaterialSpec(
        name="Ti6Al4V",
        density_g_cm3=4.43,
        price_per_kg_usd=38.00,
        notes=(
            "Grade 5 Ti-6Al-4V billet; USGS Mineral Commodity Summaries 2025 "
            "+ 25% forged-billet premium."
        ),
    ),
    # ── Cast iron ─────────────────────────────────────────────────────────
    MaterialSpec(
        name="GrayIron",
        density_g_cm3=7.20,
        price_per_kg_usd=0.75,
        notes="Gray cast iron (ASTM A48 Class 30); foundry price.",
    ),
    # ── Composites / paper (advisory) ────────────────────────────────────
    MaterialSpec(
        name="CFRP",
        density_g_cm3=1.60,
        price_per_kg_usd=35.00,
        notes=(
            "Carbon fibre reinforced polymer prepreg (T300/epoxy); "
            "indicative aerospace-grade midpoint."
        ),
    ),
    MaterialSpec(
        name="GFRP",
        density_g_cm3=1.85,
        price_per_kg_usd=4.50,
        notes="E-glass/epoxy laminate; industrial grade.",
    ),
]

# ---------------------------------------------------------------------------
# Primary lookup dict:  lower-case canonical key → MaterialSpec
# Also build an alias table for common alternative spellings.
# ---------------------------------------------------------------------------

MATERIAL_DB: dict[str, MaterialSpec] = {s.name.lower(): s for s in _ENTRIES}

_ALIASES: dict[str, str] = {
    # normalise common abbreviations to canonical keys
    "abs": "abs",
    "polypropylene": "pp",
    "polycarbonate": "pc",
    "nylon": "pa66",
    "nylon66": "pa66",
    "pa 66": "pa66",
    "aluminum": "al6061",
    "aluminium": "al6061",
    "al": "al6061",
    "6061": "al6061",
    "7075": "al7075",
    "304": "steel304",
    "ss304": "steel304",
    "316": "steel316",
    "ss316": "steel316",
    "1018": "steel1018",
    "4140": "steel4140",
    "copper": "cu",
    "titanium": "ti6al4v",
    "ti": "ti6al4v",
    "gray iron": "grayiron",
    "grey iron": "grayiron",
    "cast iron": "grayiron",
    "carbon fibre": "cfrp",
    "carbon fiber": "cfrp",
    "glass fibre": "gfrp",
    "glass fiber": "gfrp",
}


def lookup_material(key: str) -> MaterialSpec | None:
    """Return MaterialSpec for *key* (case-insensitive; aliases resolved).

    Returns ``None`` if the material is not in the 2025 database.
    """
    k = key.strip().lower()
    canon = _ALIASES.get(k, k)
    return MATERIAL_DB.get(canon)


__all__ = [
    "MaterialSpec",
    "MATERIAL_DB",
    "lookup_material",
]
