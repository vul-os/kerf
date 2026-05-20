"""
kerf_textiles.sustainability
============================
Life-Cycle Assessment (LCA) sustainability scoring for garments.

A garment is described as a ``dict`` mapping ``material_id → mass_fraction``
(fractions must sum to 1.0 ± 1e-6).  The module computes an impact profile
weighted by mass fraction and then maps that profile onto a 0–100 score where
**higher is better** (more sustainable).

Methodology
-----------
Scoring uses a simple but transparent additive weighted model:

1.  **GHG sub-score** (0–100): maps ``co2_footprint_kg_per_kg`` onto a linear
    scale anchored at 0 kg CO₂e/kg → 100 and ``GHG_MAX_REFERENCE`` → 0.

2.  **Water sub-score** (0–100): same approach with ``WATER_MAX_REFERENCE``.

3.  **Biodegradability bonus** (+10 on the composite before clipping to 100).

4.  **Certification bonus** (+2 per unique positive-signal certification, up to
    ``CERT_BONUS_CAP``).

5.  **Composite score** = weighted average of GHG + water sub-scores with
    optional bonuses, clamped to [0, 100].

Reference maxima
----------------
``GHG_MAX_REFERENCE = 135.0`` kg CO₂e/kg  (≈ cashmere / bovine leather upper)
``WATER_MAX_REFERENCE = 20000.0`` L/kg     (≈ upper end of bovine leather tanning)

These are *normalisation anchors*, not hard caps; a material exceeding them
will simply receive a score of 0 on that dimension.

Usage::

    from kerf_textiles.sustainability import score_garment, GarmentImpact

    mix = {"cotton_organic": 0.6, "polyester_recycled": 0.35, "spandex_elastane": 0.05}
    impact = score_garment(mix, garment_mass_kg=0.25)
    print(impact.sustainability_score)   # 0–100 float
    print(impact.co2_total_kg)           # absolute CO₂ for this garment
    print(impact.water_total_l)          # absolute process water
    print(impact.breakdown)              # per-material contribution dict
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kerf_textiles.materials import CATALOGUE, TextileMaterial


# ---------------------------------------------------------------------------
# Reference anchors for normalisation
# ---------------------------------------------------------------------------

GHG_MAX_REFERENCE: float = 135.0      # kg CO₂e per kg fibre (cashmere / leather upper)
WATER_MAX_REFERENCE: float = 20_000.0  # L per kg fibre (bovine leather upper)

GHG_WEIGHT: float = 0.55              # fraction of composite score from GHG
WATER_WEIGHT: float = 0.45            # fraction of composite score from water
# GHG_WEIGHT + WATER_WEIGHT must equal 1.0

BIODEGRADABLE_BONUS: float = 8.0      # raw points added before clamping
CERT_BONUS_PER: float = 2.0           # per unique positive certification
CERT_BONUS_CAP: float = 10.0          # maximum certification bonus

# Certifications that signal positive environmental credentials
POSITIVE_CERTS: frozenset[str] = frozenset({
    "GOTS", "OEKO-TEX", "Bluesign", "GRS", "FSC", "RWS", "EU Ecolabel",
    "LWG", "BCI", "GCS",
})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MaterialContribution:
    """Per-material breakdown inside a :class:`GarmentImpact`."""
    material_id: str
    name: str
    mass_fraction: float             # 0–1
    mass_kg: float                   # kg
    co2_contribution_kg: float       # kg CO₂e attributed to this material
    water_contribution_l: float      # litres attributed to this material
    ghg_sub_score: float             # 0–100 (normalised, this material alone)
    water_sub_score: float           # 0–100 (normalised, this material alone)


@dataclass
class GarmentImpact:
    """Full LCA impact profile and sustainability score for a garment."""

    # Inputs
    material_mix: dict[str, float]   # material_id → mass_fraction
    garment_mass_kg: float

    # Weighted averages (per kg of garment)
    weighted_co2_kg_per_kg: float    # kg CO₂e per kg garment
    weighted_water_l_per_kg: float   # L per kg garment

    # Absolute totals for this garment instance
    co2_total_kg: float              # kg CO₂e
    water_total_l: float             # litres

    # Sub-scores (0–100, higher = better)
    ghg_sub_score: float
    water_sub_score: float
    biodegradable_bonus: float
    cert_bonus: float

    # Final composite score (0–100)
    sustainability_score: float

    # Per-material detail
    breakdown: list[MaterialContribution] = field(default_factory=list)

    # Biodegradability flag (True only when ALL materials are biodegradable)
    fully_biodegradable: bool = False


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _ghg_sub_score(co2_kg_per_kg: float) -> float:
    """Map kg CO₂e/kg fibre onto [0, 100] (lower emissions → higher score)."""
    return max(0.0, 100.0 * (1.0 - co2_kg_per_kg / GHG_MAX_REFERENCE))


def _water_sub_score(water_l_per_kg: float) -> float:
    """Map L/kg water onto [0, 100] (lower water → higher score)."""
    return max(0.0, 100.0 * (1.0 - water_l_per_kg / WATER_MAX_REFERENCE))


def _cert_bonus(materials: list[TextileMaterial]) -> float:
    """
    Sum up unique positive-signal certifications across all materials,
    award ``CERT_BONUS_PER`` each, cap at ``CERT_BONUS_CAP``.
    """
    seen: set[str] = set()
    for mat in materials:
        for cert in mat.certifications:
            if cert in POSITIVE_CERTS:
                seen.add(cert)
    bonus = len(seen) * CERT_BONUS_PER
    return min(bonus, CERT_BONUS_CAP)


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def score_garment(
    material_mix: dict[str, float],
    garment_mass_kg: float = 0.3,
) -> GarmentImpact:
    """
    Compute the LCA sustainability score for a garment.

    Parameters
    ----------
    material_mix : dict[str, float]
        Mapping of ``material_id`` to mass fraction (0–1).
        Fractions must sum to 1.0 ± 1e-6.
    garment_mass_kg : float
        Total dry mass of the finished garment in kg (default 300 g).

    Returns
    -------
    GarmentImpact
        Full impact profile including composite score.

    Raises
    ------
    ValueError
        If fractions do not sum to 1, any fraction is out of [0, 1], or an
        unknown ``material_id`` is provided.
    """
    if not material_mix:
        raise ValueError("material_mix must not be empty")
    if garment_mass_kg <= 0.0:
        raise ValueError(f"garment_mass_kg must be positive, got {garment_mass_kg}")

    # Validate fractions
    total_frac = sum(material_mix.values())
    if abs(total_frac - 1.0) > 1e-6:
        raise ValueError(
            f"material_mix fractions must sum to 1.0 ± 1e-6, got {total_frac:.8f}"
        )
    for mid, frac in material_mix.items():
        if not (0.0 <= frac <= 1.0):
            raise ValueError(f"Fraction for {mid!r} must be in [0, 1], got {frac}")

    # Resolve materials
    resolved: list[tuple[str, float, TextileMaterial]] = []
    for mid, frac in material_mix.items():
        if mid not in CATALOGUE:
            raise ValueError(
                f"Unknown material_id {mid!r}. "
                f"Use kerf_textiles.materials.CATALOGUE to see valid IDs."
            )
        resolved.append((mid, frac, CATALOGUE[mid]))

    # Compute weighted averages
    weighted_co2 = sum(frac * mat.co2_footprint_kg_per_kg for _, frac, mat in resolved)
    weighted_water = sum(frac * mat.water_consumption_l_per_kg for _, frac, mat in resolved)

    # Absolute totals
    co2_total = weighted_co2 * garment_mass_kg
    water_total = weighted_water * garment_mass_kg

    # Sub-scores from weighted averages
    ghg_sub = _ghg_sub_score(weighted_co2)
    water_sub = _water_sub_score(weighted_water)

    # Biodegradability bonus
    fully_bio = all(mat.biodegradable for _, _, mat in resolved)
    bio_bonus = BIODEGRADABLE_BONUS if fully_bio else 0.0

    # Certification bonus
    all_mats = [mat for _, _, mat in resolved]
    c_bonus = _cert_bonus(all_mats)

    # Composite score (weighted sum + bonuses, clamped)
    composite_raw = (
        GHG_WEIGHT * ghg_sub
        + WATER_WEIGHT * water_sub
        + bio_bonus
        + c_bonus
    )
    sustainability_score = min(100.0, max(0.0, composite_raw))

    # Build per-material breakdown
    breakdown: list[MaterialContribution] = []
    for mid, frac, mat in resolved:
        mass_kg = frac * garment_mass_kg
        breakdown.append(MaterialContribution(
            material_id=mid,
            name=mat.name,
            mass_fraction=frac,
            mass_kg=mass_kg,
            co2_contribution_kg=mat.co2_footprint_kg_per_kg * mass_kg,
            water_contribution_l=mat.water_consumption_l_per_kg * mass_kg,
            ghg_sub_score=_ghg_sub_score(mat.co2_footprint_kg_per_kg),
            water_sub_score=_water_sub_score(mat.water_consumption_l_per_kg),
        ))

    return GarmentImpact(
        material_mix=material_mix,
        garment_mass_kg=garment_mass_kg,
        weighted_co2_kg_per_kg=weighted_co2,
        weighted_water_l_per_kg=weighted_water,
        co2_total_kg=co2_total,
        water_total_l=water_total,
        ghg_sub_score=ghg_sub,
        water_sub_score=water_sub,
        biodegradable_bonus=bio_bonus,
        cert_bonus=c_bonus,
        sustainability_score=sustainability_score,
        breakdown=breakdown,
        fully_biodegradable=fully_bio,
    )


def compare_garments(
    garments: dict[str, dict[str, float]],
    garment_mass_kg: float = 0.3,
) -> dict[str, GarmentImpact]:
    """
    Score multiple garment material mixes and return a dict keyed by label.

    Parameters
    ----------
    garments : dict[str, dict[str, float]]
        ``{ label: material_mix }``.
    garment_mass_kg : float
        Uniform garment mass used for all garments.

    Returns
    -------
    dict[str, GarmentImpact]
        Results in the same key order as *garments*.
    """
    return {label: score_garment(mix, garment_mass_kg) for label, mix in garments.items()}


__all__ = [
    "GHG_MAX_REFERENCE",
    "WATER_MAX_REFERENCE",
    "GHG_WEIGHT",
    "WATER_WEIGHT",
    "BIODEGRADABLE_BONUS",
    "CERT_BONUS_PER",
    "CERT_BONUS_CAP",
    "POSITIVE_CERTS",
    "MaterialContribution",
    "GarmentImpact",
    "score_garment",
    "compare_garments",
]
