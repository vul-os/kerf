"""
kerf_cad_core.jewelry.metal_cost
================================

Metal weight, casting-cost estimator, and full jeweller's quote for jewelry CAD.

This module is intentionally pure-Python with no external dependencies
so it can be imported, tested, and used on any machine without OCCT.

## Density table

Alloy densities in g/cm³, sourced from industry references:

  - Gold alloys: World Gold Council "Handbook on Gold Alloys" + Legor Group
    technical data sheets (2023). Karat values use standard UK/US compositions.
  - Platinum 950: Platinum Guild International standard composition (95% Pt
    5% Ru/Co/Cu typical). Density 21.4–21.5 g/cm³.
  - Platinum 900: PGI, 90% Pt 10% Ir/Ru. Density ~21.3 g/cm³.
  - Palladium 950: Platinum Guild International, ~11.0 g/cm³.
  - Palladium 500: 50% Pd alloy for lower-cost applications, ~10.6 g/cm³.
  - Sterling silver 925: Handy & Harman, 10.36 g/cm³.
  - Fine silver: 10.49 g/cm³ (NIST).
  - Argentium 935: 93.5% Ag + germanium alloy, 10.40 g/cm³ (Argentium Int'l).
  - Titanium: grade 2 (commercially pure), ASTM B265, 4.51 g/cm³.
  - Brass (70/30 CuZn): Copper Development Association, 8.53 g/cm³.
  - Bronze (90/10 CuSn): Copper Development Association, 8.78 g/cm³.

## Hallmark / fineness table

`METAL_HALLMARK` maps each alloy key to its fineness stamp:
  - Gold: parts per thousand of fine gold (e.g. 18k = 750)
  - Platinum/Palladium: percentage purity × 10 (e.g. Pt950 = 950)
  - Silver: sterling 925, fine 999, Argentium 935

## Unit conversions

  - 1 troy ounce (ozt) = 31.1034768 g  (NIST)
  - 1 pennyweight (dwt) = 1/20 ozt = 1.55517384 g  (traditional jewelry unit)
  - 1 mm³ = 1e-3 cm³ (used for volume input which is in mm³ = CAD units)

## Casting allowance

Lost-wax casting always produces more metal waste than the net part weight:
  - Sprue / button: the column of metal that fills the sprue tube
    (~8–12% for typical hollow shanks, higher for thick bands)
  - Button: retained casting-button metal (~3–5%)
  - Flashing / overflow seams (~1–3%)

The combined "gross/net" ratio is typically 1.10–1.20 for well-optimised
spruing. The default used here is 15% (gross = net × 1.15), which is a
conservative industry midpoint. Casters who optimise sprue placement and
use a vacuum–pressure machine can reach 10%; high-complexity multi-gate
moulds may need 20–25%. The value is fully configurable via
`casting_allowance_pct`.

## Gemstone cost

`stone_cost_line_items` accepts a list of stone specs. Each spec is a dict:

    {
        "cut":             str,    # e.g. "round_brilliant", "princess" — display only
        "carat":           float,  # stone weight in carats (ct)
        "price_per_carat": float,  # per-carat cost in your currency
        "count":           int,    # number of identical stones (default 1)
        "note":            str,    # optional descriptor e.g. "VS1 G colour"
    }

Carat and price_per_carat come from the caller — the gemstones tool (or the
user) supplies these values; this module does not import gemstones.py to
avoid cross-module coupling.

Alternatively, supply `mm` instead of `carat` for round brilliant stones;
the estimator uses a standard mm→carat formula (varies by cut). Note that
the mm→carat formula is an approximation; use explicit `carat` for accuracy.

## Labour / setting / finishing

`labour_cost` computes:
  - Bench hours × hourly rate
  - Per-stone setting fee by setting type (prong, bezel, pave, channel, flush)
  - Finishing fee (polish, plating, rhodium) chosen from named presets or explicit

## Full quote

`jewelry_quote` combines metal (via `casting_cost`), stones, and labour/
setting/finishing into a complete breakdown, with optional markup/margin.

## Regional metal-price presets

`METAL_PRICE_PRESETS` provides named reference price sets (caller-overrideable).
These are approximate spot-derived values (USD/g) for orientation only —
they are NOT live prices. The caller must verify and may supply explicit prices.

## Integration with Kerf material files

If a project has a `.material` file with `physical.rho_kg_m3` populated
(as all seed materials do), you can pass that density directly:

    density_g_cm3 = mat["physical"]["rho_kg_m3"] / 1000.0
    grams = metal_weight(volume_mm3, density_g_cm3=density_g_cm3)

The `metal_weight` function accepts either:
  - `metal` — a string key resolved from `METAL_DENSITY_G_CM3`, or
  - `density_g_cm3` — an explicit float override.

Pass `density_g_cm3` when you have already resolved the density from a
material file; pass `metal` when the user picks from the built-in menu.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Density table  (g/cm³)
# ---------------------------------------------------------------------------

METAL_DENSITY_G_CM3: dict[str, float] = {
    # Yellow gold alloys
    "10k_yellow": 11.57,   # 41.7% Au, 52% Ag+Cu, 6.3% Zn  — WGC Handbook
    "14k_yellow": 13.07,   # 58.3% Au, 30% Ag, 11.7% Cu   — WGC Handbook
    "18k_yellow": 15.58,   # 75% Au, 12.5% Ag, 12.5% Cu   — WGC / Legor DS-18Y
    "22k_yellow": 17.80,   # 91.7% Au, 5% Ag, 3.3% Cu     — WGC Handbook
    "24k_yellow": 19.32,   # 99.9% Au                       — NIST pure gold
    # White gold alloys  (Pd-white; Ni-white ≈ same density range)
    "10k_white":  11.61,   # 41.7% Au, Pd/Ag/Cu balance    — Legor DS-10W
    "14k_white":  13.25,   # 58.3% Au, Pd/Cu balance        — Legor DS-14W
    "18k_white":  15.60,   # 75% Au, Pd/Cu balance          — Legor DS-18W-PD
    "22k_white":  17.60,   # 91.7% Au, Pd balance           — WGC Handbook est.
    # Rose gold alloys
    "10k_rose":   11.59,   # 41.7% Au, high Cu              — Legor DS-10R
    "14k_rose":   13.20,   # 58.3% Au, high Cu              — Legor DS-14R
    "18k_rose":   15.45,   # 75% Au, ~22% Cu, 3% Ag         — Legor DS-18R
    "22k_rose":   17.75,   # 91.7% Au, Cu balance           — WGC Handbook est.
    # Platinum & palladium
    "platinum_950": 21.40, # 95% Pt 5% Ru/Co   — PGI standard; range 21.4–21.5
    "platinum_900": 21.30, # 90% Pt 10% Ir/Ru  — PGI; range 21.2–21.4
    "palladium_950": 11.00, # 95% Pd 5% Ru     — PGI; range 10.9–11.1
    "palladium_500": 10.60, # 50% Pd alloy     — lower-cost applications
    # Silver
    "sterling_925":   10.36, # 92.5% Ag 7.5% Cu  — Handy & Harman
    "fine_silver":    10.49, # 99.9% Ag           — NIST
    "argentium_935":  10.40, # 93.5% Ag + Ge      — Argentium International
    # Other jewelry metals
    "titanium":    4.51,   # Grade 2 commercially pure      — ASTM B265
    "brass":       8.53,   # 70/30 CuZn                     — CDA C26000
    "bronze":      8.78,   # 90/10 CuSn (phosphor bronze)   — CDA C52100
}

# Human-readable labels for the UI (maps key → display name)
METAL_LABELS: dict[str, str] = {
    "10k_yellow":    "10k Yellow Gold",
    "14k_yellow":    "14k Yellow Gold",
    "18k_yellow":    "18k Yellow Gold",
    "22k_yellow":    "22k Yellow Gold",
    "24k_yellow":    "24k Yellow Gold (Fine)",
    "10k_white":     "10k White Gold",
    "14k_white":     "14k White Gold",
    "18k_white":     "18k White Gold",
    "22k_white":     "22k White Gold",
    "10k_rose":      "10k Rose Gold",
    "14k_rose":      "14k Rose Gold",
    "18k_rose":      "18k Rose Gold",
    "22k_rose":      "22k Rose Gold",
    "platinum_950":  "Platinum 950",
    "platinum_900":  "Platinum 900",
    "palladium_950": "Palladium 950",
    "palladium_500": "Palladium 500",
    "sterling_925":  "Sterling Silver 925",
    "fine_silver":   "Fine Silver",
    "argentium_935": "Argentium Silver 935",
    "titanium":      "Titanium (Grade 2)",
    "brass":         "Brass (70/30)",
    "bronze":        "Bronze (90/10)",
}

# Fineness / hallmark stamps (parts per thousand of the primary precious metal).
# Gold:      417 = 10k, 583 = 14k, 750 = 18k, 917 = 22k, 999 = 24k (fine)
# Platinum:  950 = Pt950, 900 = Pt900
# Palladium: 950 = Pd950, 500 = Pd500
# Silver:    925 = sterling, 999 = fine, 935 = Argentium
# Non-precious metals: None (not hallmarked as precious)
METAL_HALLMARK: dict[str, Optional[int]] = {
    "10k_yellow":    417,
    "14k_yellow":    583,
    "18k_yellow":    750,
    "22k_yellow":    917,
    "24k_yellow":    999,
    "10k_white":     417,
    "14k_white":     583,
    "18k_white":     750,
    "22k_white":     917,
    "10k_rose":      417,
    "14k_rose":      583,
    "18k_rose":      750,
    "22k_rose":      917,
    "platinum_950":  950,
    "platinum_900":  900,
    "palladium_950": 950,
    "palladium_500": 500,
    "sterling_925":  925,
    "fine_silver":   999,
    "argentium_935": 935,
    "titanium":      None,
    "brass":         None,
    "bronze":        None,
}

# Fineness label used on UK/EU hallmarks (e.g. "750" for 18k yellow)
METAL_FINENESS_LABEL: dict[str, str] = {
    k: str(v) if v is not None else "—"
    for k, v in METAL_HALLMARK.items()
}


# ---------------------------------------------------------------------------
# Regional metal-price presets  (USD/g, approximate spot-derived — NOT live)
# ---------------------------------------------------------------------------
# These are orientation defaults only.  Caller must verify current prices
# and may supply any explicit price; these presets are merely labelled defaults.
# Prices update with market; treat these as rough 2024 midpoints.

METAL_PRICE_PRESETS: dict[str, dict[str, float]] = {
    # Approximate USD/g at ~$2 000/ozt fine gold, ~$25/ozt silver, ~$1 000/ozt Pt
    "usd_2024_approx": {
        "10k_yellow":    27.0,
        "14k_yellow":    37.5,
        "18k_yellow":    48.0,
        "22k_yellow":    58.5,
        "24k_yellow":    64.0,
        "10k_white":     27.5,
        "14k_white":     38.0,
        "18k_white":     49.0,
        "22k_white":     59.5,
        "10k_rose":      27.0,
        "14k_rose":      37.5,
        "18k_rose":      48.0,
        "22k_rose":      58.5,
        "platinum_950":  32.0,
        "platinum_900":  30.5,
        "palladium_950": 42.0,
        "palladium_500": 22.0,
        "sterling_925":   0.80,
        "fine_silver":    0.86,
        "argentium_935":  0.84,
        "titanium":       0.05,
        "brass":          0.008,
        "bronze":         0.01,
    },
}


# ---------------------------------------------------------------------------
# Setting types and per-stone fees (USD defaults — caller overrides)
# ---------------------------------------------------------------------------

# Named setting types, with short descriptions for UI.
SETTING_TYPES: dict[str, str] = {
    "prong":    "Prong / claw setting (most common, best light)",
    "bezel":    "Bezel / rub-over setting (fully enclosed girdle)",
    "pave":     "Pavé / micro-pavé (small stones, drilled pockets)",
    "channel":  "Channel setting (stones set between two rails)",
    "flush":    "Flush / gypsy setting (stone sunk into metal)",
    "invisible":"Invisible setting (stones set without visible metal)",
    "tension":  "Tension setting (stone held by spring pressure)",
    "bar":      "Bar setting (each stone separated by metal bars)",
}

# Default setting fee per stone (USD) by setting type.
# These are bench-time estimates; actual shop rates vary widely.
DEFAULT_SETTING_FEE_PER_STONE: dict[str, float] = {
    "prong":    12.0,
    "bezel":    18.0,
    "pave":      5.0,
    "channel":   8.0,
    "flush":    10.0,
    "invisible": 22.0,
    "tension":  25.0,
    "bar":      10.0,
}

# Finishing options and their default cost (USD).
FINISHING_TYPES: dict[str, str] = {
    "polish":          "High-polish finishing",
    "satin":           "Satin / brushed finish",
    "hammer":          "Hammered texture finish",
    "rhodium":         "Rhodium plating (typical for white gold)",
    "black_rhodium":   "Black rhodium plating",
    "gold_plate":      "Gold vermeil / gold plating over silver",
    "antique":         "Antiquing / oxidation treatment",
    "sandblast":       "Sandblasted matte finish",
}

DEFAULT_FINISHING_COST: dict[str, float] = {
    "polish":        0.0,   # included in base labour
    "satin":        15.0,
    "hammer":       20.0,
    "rhodium":      35.0,
    "black_rhodium": 45.0,
    "gold_plate":   25.0,
    "antique":      20.0,
    "sandblast":    18.0,
}


# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------

GRAMS_PER_DWT: float = 1.55517384   # 1 pennyweight = 1.55517384 g  (NIST)
GRAMS_PER_OZT: float = 31.1034768   # 1 troy ounce  = 31.1034768 g  (NIST)
MM3_PER_CM3:   float = 1000.0       # 1 cm³ = 1000 mm³
CARATS_PER_GRAM: float = 5.0        # 1 gram = 5 carats  (gemological carat)


# ---------------------------------------------------------------------------
# Core calculations
# ---------------------------------------------------------------------------

def grams_to_dwt(grams: float) -> float:
    """Convert grams to pennyweight (dwt)."""
    return grams / GRAMS_PER_DWT


def grams_to_ozt(grams: float) -> float:
    """Convert grams to troy ounces (ozt)."""
    return grams / GRAMS_PER_OZT


def dwt_to_grams(dwt: float) -> float:
    """Convert pennyweight to grams."""
    return dwt * GRAMS_PER_DWT


def ozt_to_grams(ozt: float) -> float:
    """Convert troy ounces to grams."""
    return ozt * GRAMS_PER_OZT


def resolve_density(
    metal: Optional[str] = None,
    density_g_cm3: Optional[float] = None,
) -> float:
    """
    Resolve density in g/cm³.

    Priority: explicit `density_g_cm3` > `metal` key lookup.
    Raises ValueError for unknown metal keys or invalid density values.
    """
    if density_g_cm3 is not None:
        if density_g_cm3 <= 0:
            raise ValueError(f"density_g_cm3 must be positive, got {density_g_cm3}")
        return float(density_g_cm3)
    if metal is None:
        raise ValueError("Either metal or density_g_cm3 must be provided")
    key = metal.strip().lower()
    if key not in METAL_DENSITY_G_CM3:
        raise ValueError(
            f"Unknown metal '{metal}'. Valid keys: {sorted(METAL_DENSITY_G_CM3)}"
        )
    return METAL_DENSITY_G_CM3[key]


def metal_weight(
    volume_mm3: float,
    metal: Optional[str] = None,
    density_g_cm3: Optional[float] = None,
) -> dict:
    """
    Calculate the net weight of a metal body.

    Parameters
    ----------
    volume_mm3 : float
        Volume of the part in cubic millimetres (standard CAD unit in Kerf).
        You can pass the volume from a OCCT GProp_GProps result directly:
            props = GProp_GProps()
            brepgprop.VolumeProperties(shape, props)
            vol = props.Mass()  # mm³ when model units are mm
    metal : str, optional
        Key from METAL_DENSITY_G_CM3.  Mutually exclusive with density_g_cm3.
    density_g_cm3 : float, optional
        Explicit density override (from a .material file or lab measurement).
        When provided, `metal` is ignored.

    Returns
    -------
    dict with keys:
        grams     — net weight in grams
        dwt       — net weight in pennyweight
        ozt       — net weight in troy ounces
        metal     — the resolved metal key (or None if density override used)
        density_g_cm3 — density used
        volume_mm3    — volume used
    """
    if volume_mm3 <= 0:
        raise ValueError(f"volume_mm3 must be positive, got {volume_mm3}")
    density = resolve_density(metal, density_g_cm3)
    volume_cm3 = volume_mm3 / MM3_PER_CM3
    grams = density * volume_cm3
    return {
        "grams": grams,
        "dwt": grams_to_dwt(grams),
        "ozt": grams_to_ozt(grams),
        "metal": metal,
        "density_g_cm3": density,
        "volume_mm3": volume_mm3,
    }


def casting_weight(
    net_grams: float,
    casting_allowance_pct: float = 15.0,
) -> dict:
    """
    Estimate gross casting weight including sprue/button/flashing allowance.

    Parameters
    ----------
    net_grams : float
        Net part weight in grams (from metal_weight).
    casting_allowance_pct : float
        Percentage overhead for sprue, button, and flashing.
        Default 15% (gross = net × 1.15).
        Typical range: 10% (optimised gate) to 25% (complex multi-gate).

    Returns
    -------
    dict with keys:
        net_grams           — the input net weight
        allowance_pct       — the configured allowance percentage
        allowance_grams     — overhead grams (sprue + button + flashing)
        gross_grams         — total casting weight (net + allowance)
        gross_dwt           — gross weight in pennyweight
        gross_ozt           — gross weight in troy ounces
    """
    if net_grams <= 0:
        raise ValueError(f"net_grams must be positive, got {net_grams}")
    if casting_allowance_pct < 0:
        raise ValueError(f"casting_allowance_pct must be >= 0, got {casting_allowance_pct}")
    factor = 1.0 + casting_allowance_pct / 100.0
    gross = net_grams * factor
    allowance = gross - net_grams
    return {
        "net_grams": net_grams,
        "allowance_pct": casting_allowance_pct,
        "allowance_grams": allowance,
        "gross_grams": gross,
        "gross_dwt": grams_to_dwt(gross),
        "gross_ozt": grams_to_ozt(gross),
    }


def casting_cost(
    volume_mm3: float,
    metal: Optional[str] = None,
    density_g_cm3: Optional[float] = None,
    metal_price_per_gram: float = 0.0,
    labor: float = 0.0,
    finishing: float = 0.0,
    casting_allowance_pct: float = 15.0,
) -> dict:
    """
    Produce an itemised casting cost estimate.

    Metal price is supplied by the user (no live market feed — prices vary
    by supplier, purity, form, and currency). Use spot gold/silver prices
    as a baseline and add your supplier's premium.

    Parameters
    ----------
    volume_mm3 : float
        Part volume in mm³.
    metal : str, optional
        Metal key (see METAL_DENSITY_G_CM3). Mutually exclusive with
        density_g_cm3.
    density_g_cm3 : float, optional
        Explicit density override.
    metal_price_per_gram : float
        Metal spot price in your currency per gram.
        Example: 18k yellow gold ≈ $38 USD/g at ~$1950/ozt spot.
    labor : float
        Bench labor cost (casting, cleanup, polishing) in your currency.
    finishing : float
        Finishing / plating / rhodium cost in your currency.
    casting_allowance_pct : float
        Sprue/button/flashing overhead, default 15%.

    Returns
    -------
    dict with full itemised breakdown:
        metal            — metal key
        density_g_cm3    — density used
        volume_mm3       — input volume
        net_grams        — net part weight
        net_dwt          — net weight in dwt
        net_ozt          — net weight in ozt
        allowance_pct    — casting allowance used
        gross_grams      — total metal to purchase
        gross_dwt        — gross weight in dwt
        gross_ozt        — gross weight in ozt
        metal_price_per_gram  — input price
        metal_cost       — gross_grams × metal_price_per_gram
        labor            — input labor cost
        finishing        — input finishing cost
        total_cost       — metal_cost + labor + finishing
    """
    if volume_mm3 <= 0:
        raise ValueError(f"volume_mm3 must be positive, got {volume_mm3}")
    if metal_price_per_gram < 0:
        raise ValueError(f"metal_price_per_gram must be >= 0, got {metal_price_per_gram}")
    if labor < 0:
        raise ValueError(f"labor must be >= 0, got {labor}")
    if finishing < 0:
        raise ValueError(f"finishing must be >= 0, got {finishing}")

    weight = metal_weight(volume_mm3, metal=metal, density_g_cm3=density_g_cm3)
    cast = casting_weight(weight["grams"], casting_allowance_pct=casting_allowance_pct)
    metal_cost_value = cast["gross_grams"] * metal_price_per_gram
    total = metal_cost_value + labor + finishing

    return {
        "metal": weight["metal"],
        "density_g_cm3": weight["density_g_cm3"],
        "volume_mm3": volume_mm3,
        "net_grams": weight["grams"],
        "net_dwt": weight["dwt"],
        "net_ozt": weight["ozt"],
        "allowance_pct": casting_allowance_pct,
        "gross_grams": cast["gross_grams"],
        "gross_dwt": cast["gross_dwt"],
        "gross_ozt": cast["gross_ozt"],
        "metal_price_per_gram": metal_price_per_gram,
        "metal_cost": metal_cost_value,
        "labor": labor,
        "finishing": finishing,
        "total_cost": total,
    }


def multi_metal_compare(
    volume_mm3: float,
    metals: Optional[list[str]] = None,
    metal_prices: Optional[dict[str, float]] = None,
    labor: float = 0.0,
    finishing: float = 0.0,
    casting_allowance_pct: float = 15.0,
) -> list[dict]:
    """
    Compare casting cost across multiple metals for the same volume.

    Useful for helping a jeweler decide on metal choice before committing
    to a casting order.

    Parameters
    ----------
    volume_mm3 : float
        Part volume in mm³.
    metals : list[str], optional
        List of metal keys to compare.  Defaults to the common jewelry
        metals: 14k_yellow, 14k_white, 18k_yellow, sterling_925,
        platinum_950, palladium_950.
    metal_prices : dict[str, float], optional
        Per-metal price overrides {metal_key: price_per_gram}.
        Metals not present in the dict use price 0.0 (weight-only output).
    labor : float
        Common labor cost applied to all metals.
    finishing : float
        Common finishing cost applied to all metals.
    casting_allowance_pct : float
        Common casting allowance applied to all metals.

    Returns
    -------
    List of casting_cost dicts sorted by total_cost ascending.
    """
    DEFAULT_METALS = [
        "14k_yellow", "14k_white", "14k_rose",
        "18k_yellow", "18k_white",
        "sterling_925", "platinum_950", "palladium_950",
    ]
    if metals is None:
        metals = DEFAULT_METALS
    if metal_prices is None:
        metal_prices = {}

    results = []
    for m in metals:
        price = metal_prices.get(m, 0.0)
        row = casting_cost(
            volume_mm3,
            metal=m,
            metal_price_per_gram=price,
            labor=labor,
            finishing=finishing,
            casting_allowance_pct=casting_allowance_pct,
        )
        row["label"] = METAL_LABELS.get(m, m)
        results.append(row)

    results.sort(key=lambda r: r["total_cost"])
    return results


# ---------------------------------------------------------------------------
# mm → carat estimate helpers
# ---------------------------------------------------------------------------

# Standard mm→carat conversion formulae (approximate, varies by cut quality).
# Formula: carat = (diameter_mm ^ 3) × factor
# Source: GIA Technical Guide + trade tables (3rd-party approximations).
_MM_TO_CARAT_FACTOR: dict[str, float] = {
    "round_brilliant": 0.00370,    # Most accurate; GIA formula
    "princess":        0.00390,    # Slightly different aspect ratio
    "oval":            0.00280,    # Oval is shallower than round
    "cushion":         0.00350,
    "pear":            0.00240,
    "marquise":        0.00200,
    "emerald":         0.00240,
    "asscher":         0.00350,
    "radiant":         0.00360,
    "heart":           0.00230,
}
_DEFAULT_MM_TO_CARAT_FACTOR = 0.00370  # fallback to round brilliant


def mm_to_carat(diameter_mm: float, cut: str = "round_brilliant") -> float:
    """
    Estimate carat weight of a stone from its diameter (mm).

    This is an approximation — actual weight depends on depth, proportions,
    and cutting quality. For accurate costing, supply explicit carat weight.

    Parameters
    ----------
    diameter_mm : float
        Stone diameter (for round) or longest dimension (for fancy cuts).
    cut : str
        Cut style key (see _MM_TO_CARAT_FACTOR). Defaults to round_brilliant.

    Returns
    -------
    Estimated carat weight (float).
    """
    if diameter_mm <= 0:
        raise ValueError(f"diameter_mm must be positive, got {diameter_mm}")
    key = cut.strip().lower()
    factor = _MM_TO_CARAT_FACTOR.get(key, _DEFAULT_MM_TO_CARAT_FACTOR)
    return diameter_mm ** 3 * factor


# ---------------------------------------------------------------------------
# Gemstone cost line items
# ---------------------------------------------------------------------------

def stone_cost_line_items(stones: list[dict]) -> dict:
    """
    Compute itemised stone cost from a list of stone specs.

    Each stone spec is a dict with:
        cut             : str    — display label e.g. "round_brilliant"
        carat           : float  — stone weight in carats (preferred)
        mm              : float  — stone diameter mm (used if carat absent)
        price_per_carat : float  — cost per carat in your currency
        count           : int    — number of identical stones (default 1)
        note            : str    — optional label / quality descriptor

    Carat and price_per_carat are caller-supplied. The gemstones tool (or the
    user) supplies these; this module does NOT import gemstones.py to avoid
    cross-module coupling. Carat can come from the gemstone tool output.

    Parameters
    ----------
    stones : list[dict]
        List of stone spec dicts as described above.

    Returns
    -------
    dict with keys:
        line_items      — list of per-spec dicts:
                          cut, carat_each, count, price_per_carat,
                          line_total, note
        total_carats    — total carat weight of all stones
        total_stones    — total stone count
        total_cost      — sum of all line item costs
    """
    if not isinstance(stones, list):
        raise ValueError("stones must be a list of stone spec dicts")

    line_items = []
    total_carats = 0.0
    total_cost = 0.0
    total_stones = 0

    for i, spec in enumerate(stones):
        if not isinstance(spec, dict):
            raise ValueError(f"stones[{i}] must be a dict, got {type(spec).__name__}")

        cut = str(spec.get("cut", "round_brilliant")).strip().lower()
        price_per_carat = spec.get("price_per_carat")
        if price_per_carat is None:
            raise ValueError(f"stones[{i}] missing required field 'price_per_carat'")
        try:
            price_per_carat = float(price_per_carat)
        except (TypeError, ValueError):
            raise ValueError(f"stones[{i}].price_per_carat must be numeric")
        if price_per_carat < 0:
            raise ValueError(f"stones[{i}].price_per_carat must be >= 0")

        # Resolve carat weight
        if "carat" in spec and spec["carat"] is not None:
            try:
                carat_each = float(spec["carat"])
            except (TypeError, ValueError):
                raise ValueError(f"stones[{i}].carat must be numeric")
            if carat_each <= 0:
                raise ValueError(f"stones[{i}].carat must be positive")
        elif "mm" in spec and spec["mm"] is not None:
            try:
                mm_val = float(spec["mm"])
            except (TypeError, ValueError):
                raise ValueError(f"stones[{i}].mm must be numeric")
            if mm_val <= 0:
                raise ValueError(f"stones[{i}].mm must be positive")
            carat_each = mm_to_carat(mm_val, cut)
        else:
            raise ValueError(f"stones[{i}] must have 'carat' or 'mm'")

        count_raw = spec.get("count", 1)
        try:
            count = int(count_raw)
        except (TypeError, ValueError):
            raise ValueError(f"stones[{i}].count must be an integer")
        if count <= 0:
            raise ValueError(f"stones[{i}].count must be >= 1")

        note = str(spec.get("note", "")).strip()
        line_total = carat_each * price_per_carat * count

        line_items.append({
            "cut": cut,
            "carat_each": round(carat_each, 4),
            "count": count,
            "price_per_carat": price_per_carat,
            "line_total": round(line_total, 4),
            "note": note,
        })
        total_carats += carat_each * count
        total_cost += line_total
        total_stones += count

    return {
        "line_items": line_items,
        "total_carats": round(total_carats, 4),
        "total_stones": total_stones,
        "total_cost": round(total_cost, 4),
    }


# ---------------------------------------------------------------------------
# Labour / setting / finishing model
# ---------------------------------------------------------------------------

def labour_cost(
    bench_hours: float = 0.0,
    hourly_rate: float = 0.0,
    stones: Optional[list[dict]] = None,
    setting_type: str = "prong",
    setting_fee_per_stone: Optional[float] = None,
    finishing_type: Optional[str] = None,
    finishing_cost: Optional[float] = None,
) -> dict:
    """
    Compute parametric labour, setting, and finishing costs.

    Parameters
    ----------
    bench_hours : float
        Hours of bench labour (casting, cleanup, polishing). Default 0.
    hourly_rate : float
        Bench hourly rate in your currency. Default 0.
    stones : list[dict], optional
        Same stone specs as `stone_cost_line_items`. Used to count total
        stones for setting fee; carat/price NOT re-calculated here.
        Alternatively pass an integer via the stone count directly using
        the simpler `_stone_count` approach (see `jewelry_quote`).
    setting_type : str
        Setting style: prong, bezel, pave, channel, flush, invisible,
        tension, bar. Default "prong".
    setting_fee_per_stone : float, optional
        Override per-stone setting fee. If None, uses DEFAULT_SETTING_FEE_PER_STONE.
    finishing_type : str, optional
        Named finishing type (see FINISHING_TYPES). Default None (no finish
        charge; polish assumed included in bench hours).
    finishing_cost : float, optional
        Explicit finishing cost override. Overrides finishing_type default.

    Returns
    -------
    dict with keys:
        bench_hours          — input bench hours
        hourly_rate          — input hourly rate
        bench_labour_cost    — bench_hours × hourly_rate
        setting_type         — name of setting type used
        setting_fee_per_stone — fee applied per stone
        stone_count          — total stones set
        setting_cost         — setting_fee_per_stone × stone_count
        finishing_type       — finishing type label
        finishing_cost       — finishing cost applied
        total_labour         — bench_labour_cost + setting_cost + finishing_cost
    """
    if bench_hours < 0:
        raise ValueError(f"bench_hours must be >= 0, got {bench_hours}")
    if hourly_rate < 0:
        raise ValueError(f"hourly_rate must be >= 0, got {hourly_rate}")

    bench_labour = bench_hours * hourly_rate

    # Setting cost
    stype = setting_type.strip().lower() if setting_type else "prong"
    if stype not in DEFAULT_SETTING_FEE_PER_STONE and setting_fee_per_stone is None:
        raise ValueError(
            f"Unknown setting_type '{setting_type}'. "
            f"Valid: {sorted(DEFAULT_SETTING_FEE_PER_STONE)}"
        )
    if setting_fee_per_stone is None:
        setting_fee_per_stone = DEFAULT_SETTING_FEE_PER_STONE.get(stype, 0.0)
    else:
        setting_fee_per_stone = float(setting_fee_per_stone)
    if setting_fee_per_stone < 0:
        raise ValueError(f"setting_fee_per_stone must be >= 0, got {setting_fee_per_stone}")

    stone_count = 0
    if stones:
        for spec in stones:
            if isinstance(spec, dict):
                try:
                    stone_count += int(spec.get("count", 1))
                except (TypeError, ValueError):
                    stone_count += 1

    setting_cost = setting_fee_per_stone * stone_count

    # Finishing cost
    ftype_label = finishing_type or "none"
    if finishing_cost is not None:
        finishing_cost = float(finishing_cost)
        if finishing_cost < 0:
            raise ValueError(f"finishing_cost must be >= 0, got {finishing_cost}")
    elif finishing_type is not None:
        fkey = finishing_type.strip().lower()
        if fkey not in DEFAULT_FINISHING_COST:
            raise ValueError(
                f"Unknown finishing_type '{finishing_type}'. "
                f"Valid: {sorted(DEFAULT_FINISHING_COST)}"
            )
        finishing_cost = DEFAULT_FINISHING_COST[fkey]
    else:
        finishing_cost = 0.0

    total = bench_labour + setting_cost + finishing_cost
    return {
        "bench_hours": bench_hours,
        "hourly_rate": hourly_rate,
        "bench_labour_cost": round(bench_labour, 4),
        "setting_type": stype,
        "setting_fee_per_stone": setting_fee_per_stone,
        "stone_count": stone_count,
        "setting_cost": round(setting_cost, 4),
        "finishing_type": ftype_label,
        "finishing_cost": round(finishing_cost, 4),
        "total_labour": round(total, 4),
    }


# ---------------------------------------------------------------------------
# Full jeweller's quote
# ---------------------------------------------------------------------------

def jewelry_quote(
    volume_mm3: float,
    metal: Optional[str] = None,
    density_g_cm3: Optional[float] = None,
    metal_price_per_gram: float = 0.0,
    casting_allowance_pct: float = 15.0,
    # Stones
    stones: Optional[list[dict]] = None,
    # Labour & setting
    bench_hours: float = 0.0,
    hourly_rate: float = 0.0,
    setting_type: str = "prong",
    setting_fee_per_stone: Optional[float] = None,
    # Finishing
    finishing_type: Optional[str] = None,
    finishing_cost: Optional[float] = None,
    # Markup
    markup_pct: float = 0.0,
    # Optional price preset name (lookup only; explicit metal_price overrides)
    price_preset: Optional[str] = None,
) -> dict:
    """
    Produce a full jeweller's quote for a finished piece.

    Combines:
      - metal weight + casting cost (gross weight with sprue allowance)
      - stone cost line items
      - bench labour
      - stone setting fees
      - finishing / plating / rhodium
      - configurable markup/margin percentage

    All monetary values are in the caller's currency (no currency conversion).
    No live price feed — supply `metal_price_per_gram` or a `price_preset`.

    Parameters
    ----------
    volume_mm3 : float
        Part volume in cubic millimetres (from CAD volume query).
    metal : str, optional
        Metal key from METAL_DENSITY_G_CM3. Mutually exclusive with
        density_g_cm3. Required unless density_g_cm3 is given.
    density_g_cm3 : float, optional
        Explicit density override (from a .material file).
    metal_price_per_gram : float
        Metal price per gram. If 0 and price_preset is given, the preset
        value for the metal is used. Explicit non-zero value always wins.
    casting_allowance_pct : float
        Sprue/button/flashing overhead, default 15%.
    stones : list[dict], optional
        List of stone specs (see `stone_cost_line_items` for spec format).
        Leave empty/None for no stones.
    bench_hours : float
        Bench hours. Default 0 (bench_labour = 0).
    hourly_rate : float
        Bench hourly rate. Default 0.
    setting_type : str
        Setting style for per-stone fee. Default "prong".
    setting_fee_per_stone : float, optional
        Override per-stone setting fee. None uses default for setting_type.
    finishing_type : str, optional
        Named finishing (polish, satin, rhodium, etc.). None = no finish charge.
    finishing_cost : float, optional
        Explicit finishing cost (overrides finishing_type default).
    markup_pct : float
        Markup applied to subtotal as a percentage (e.g. 20 = +20%).
        Must be >= 0. Default 0 (no markup).
    price_preset : str, optional
        Named preset key from METAL_PRICE_PRESETS (e.g. "usd_2024_approx").
        Used as fallback if metal_price_per_gram == 0 and metal is known.
        Explicit metal_price_per_gram > 0 always takes precedence.

    Returns
    -------
    dict with keys:
        metal           — metal key used
        label           — human-readable metal label
        hallmark        — fineness stamp (e.g. 750 for 18k)
        density_g_cm3   — density used
        volume_mm3      — input volume
        net_grams       — net part weight (g)
        net_dwt         — net weight in dwt
        net_ozt         — net weight in ozt
        allowance_pct   — casting allowance %
        gross_grams     — total metal to purchase (g)
        metal_price_per_gram — price used
        metal_cost      — gross metal cost
        casting_cost    — alias for metal_cost (gross_grams × price)
        stones          — stone cost breakdown (from stone_cost_line_items)
        stone_cost      — total stone cost
        labour          — labour breakdown (from labour_cost)
        labour_total    — total labour+setting+finishing
        subtotal        — metal_cost + stone_cost + labour_total
        markup_pct      — markup percentage used
        markup_amount   — subtotal × markup_pct / 100
        total           — subtotal + markup_amount
    """
    # Validate markup
    if markup_pct < 0:
        raise ValueError(f"markup_pct must be >= 0, got {markup_pct}")

    # Resolve price via preset if needed
    resolved_price = float(metal_price_per_gram)
    if resolved_price == 0.0 and price_preset is not None and metal is not None:
        preset_data = METAL_PRICE_PRESETS.get(price_preset)
        if preset_data is None:
            raise ValueError(
                f"Unknown price_preset '{price_preset}'. "
                f"Valid: {sorted(METAL_PRICE_PRESETS)}"
            )
        mkey = metal.strip().lower() if metal else ""
        resolved_price = preset_data.get(mkey, 0.0)

    # Metal cost (validates volume, metal/density, price)
    cast = casting_cost(
        volume_mm3=volume_mm3,
        metal=metal,
        density_g_cm3=density_g_cm3,
        metal_price_per_gram=resolved_price,
        labor=0.0,
        finishing=0.0,
        casting_allowance_pct=casting_allowance_pct,
    )

    # Stone cost
    stones_result: dict = {"line_items": [], "total_carats": 0.0,
                           "total_stones": 0, "total_cost": 0.0}
    if stones:
        stones_result = stone_cost_line_items(stones)
    stone_cost_total = stones_result["total_cost"]

    # Labour, setting, finishing
    labour_result = labour_cost(
        bench_hours=bench_hours,
        hourly_rate=hourly_rate,
        stones=stones or [],
        setting_type=setting_type,
        setting_fee_per_stone=setting_fee_per_stone,
        finishing_type=finishing_type,
        finishing_cost=finishing_cost,
    )
    labour_total = labour_result["total_labour"]

    # Subtotal and markup
    subtotal = cast["metal_cost"] + stone_cost_total + labour_total
    markup_amount = subtotal * markup_pct / 100.0
    total = subtotal + markup_amount

    mkey = (metal.strip().lower() if metal else None)
    return {
        "metal": cast["metal"],
        "label": METAL_LABELS.get(mkey or "", mkey or "custom density"),
        "hallmark": METAL_HALLMARK.get(mkey or "", None),
        "density_g_cm3": cast["density_g_cm3"],
        "volume_mm3": volume_mm3,
        "net_grams": cast["net_grams"],
        "net_dwt": cast["net_dwt"],
        "net_ozt": cast["net_ozt"],
        "allowance_pct": casting_allowance_pct,
        "gross_grams": cast["gross_grams"],
        "metal_price_per_gram": resolved_price,
        "metal_cost": cast["metal_cost"],
        "casting_cost": cast["metal_cost"],   # alias for clarity
        "stones": stones_result,
        "stone_cost": stone_cost_total,
        "labour": labour_result,
        "labour_total": labour_total,
        "subtotal": round(subtotal, 4),
        "markup_pct": markup_pct,
        "markup_amount": round(markup_amount, 4),
        "total": round(total, 4),
    }
