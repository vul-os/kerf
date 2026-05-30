"""
Verified-oracle tests for the native plant species catalog.

Analytic oracles
----------------
1. Red maple lookup
   Acer rubrum: USDA zones 3–9, mature height 22 m (Dirr, MWLP 6th ed. p. 63).

2. Filter by zone + conditions
   filter_plants(usda_zone=5, light='full_sun', water='low') must return ≥ 5 species.

3. Pollinator subset east
   plants_for_pollinators('east') must include Echinacea purpurea AND Asclepias tuberosa.

4. Deer-resistant filter
   filter_plants(usda_zone=5, deer_resistant=True) returns only deer_resistant=True entries.

All tests are hermetic — no external files, no skips, all must pass.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# 1.  Red maple lookup
#     Oracle: Acer rubrum — USDA zones 3–9, mature height 22 m (Dirr p. 63)
# ===========================================================================

def test_red_maple_lookup_by_common_name():
    """lookup_plant('red maple') returns Acer rubrum."""
    from kerf_landscape.plant_catalog import lookup_plant

    sp = lookup_plant("red maple")
    assert sp is not None, "Red maple must be in catalog"
    assert sp.scientific_name == "Acer rubrum"


def test_red_maple_lookup_case_insensitive():
    """lookup_plant is case-insensitive for common names."""
    from kerf_landscape.plant_catalog import lookup_plant

    sp = lookup_plant("Red Maple")
    assert sp is not None
    sp2 = lookup_plant("RED MAPLE")
    assert sp2 is not None
    assert sp.scientific_name == sp2.scientific_name


def test_red_maple_lookup_by_scientific_name():
    """lookup_plant('Acer rubrum') returns the same species."""
    from kerf_landscape.plant_catalog import lookup_plant

    sp = lookup_plant("Acer rubrum")
    assert sp is not None
    assert sp.common_name == "Red Maple"


def test_red_maple_usda_zones():
    """Acer rubrum: USDA zones 3–9 (Dirr p. 63)."""
    from kerf_landscape.plant_catalog import lookup_plant

    sp = lookup_plant("red maple")
    assert sp.usda_zones_min == 3, f"Expected min zone 3, got {sp.usda_zones_min}"
    assert sp.usda_zones_max == 9, f"Expected max zone 9, got {sp.usda_zones_max}"


def test_red_maple_mature_height():
    """Acer rubrum: mature height 18–27 m range; catalog value is 22 m (Dirr midpoint)."""
    from kerf_landscape.plant_catalog import lookup_plant

    sp = lookup_plant("red maple")
    assert 18.0 <= sp.mature_height_m <= 27.0, (
        f"Red maple mature height {sp.mature_height_m} m outside Dirr range 18–27 m"
    )


def test_red_maple_kind():
    """Acer rubrum is a deciduous_tree."""
    from kerf_landscape.plant_catalog import lookup_plant

    sp = lookup_plant("red maple")
    assert sp.kind == "deciduous_tree"


def test_lookup_nonexistent_returns_none():
    """Unknown plant names return None, not an exception."""
    from kerf_landscape.plant_catalog import lookup_plant

    assert lookup_plant("Xyzzy foobar") is None
    assert lookup_plant("") is None


# ===========================================================================
# 2.  Filter by zone / conditions
#     Oracle: zone=5, full_sun, low water → ≥ 5 species
# ===========================================================================

def test_filter_zone5_fullsun_low_water_min_count():
    """filter_plants(usda_zone=5, light='full_sun', water='low') returns ≥ 5 species."""
    from kerf_landscape.plant_catalog import filter_plants

    results = filter_plants(usda_zone=5, light="full_sun", water="low")
    assert len(results) >= 5, (
        f"Expected ≥ 5 plants for zone 5 / full_sun / low water, got {len(results)}"
    )


def test_filter_zone_range_respected():
    """All returned species include the requested zone in their min–max range."""
    from kerf_landscape.plant_catalog import filter_plants

    for zone in (3, 5, 7, 9):
        results = filter_plants(usda_zone=zone)
        for sp in results:
            assert sp.usda_zones_min <= zone <= sp.usda_zones_max, (
                f"{sp.scientific_name}: zone {zone} not in [{sp.usda_zones_min}–{sp.usda_zones_max}]"
            )


def test_filter_light_respected():
    """All returned species have the requested light value."""
    from kerf_landscape.plant_catalog import filter_plants

    for light in ("full_sun", "partial_shade", "shade"):
        results = filter_plants(light=light)
        for sp in results:
            assert sp.light == light, f"{sp.scientific_name}: light={sp.light!r} ≠ {light!r}"


def test_filter_water_respected():
    """All returned species have the requested water value."""
    from kerf_landscape.plant_catalog import filter_plants

    for water in ("low", "medium", "high"):
        results = filter_plants(water=water)
        assert len(results) > 0, f"No plants found for water={water!r}"
        for sp in results:
            assert sp.water == water, f"{sp.scientific_name}: water={sp.water!r} ≠ {water!r}"


def test_filter_kind_respected():
    """All returned species match the requested kind."""
    from kerf_landscape.plant_catalog import filter_plants

    for kind in ("deciduous_tree", "evergreen", "shrub", "perennial", "grass"):
        results = filter_plants(kind=kind)
        assert len(results) > 0, f"No plants found for kind={kind!r}"
        for sp in results:
            assert sp.kind == kind, f"{sp.scientific_name}: kind={sp.kind!r} ≠ {kind!r}"


def test_filter_no_args_returns_all():
    """filter_plants() with no arguments returns all catalog entries."""
    from kerf_landscape.plant_catalog import PLANT_CATALOG, filter_plants

    results = filter_plants()
    assert len(results) == len(PLANT_CATALOG)


def test_filter_impossible_zone_returns_empty():
    """Zone 0 is below all species min zones → empty result."""
    from kerf_landscape.plant_catalog import filter_plants

    results = filter_plants(usda_zone=0)
    assert results == []


# ===========================================================================
# 3.  Pollinator subset — east region
#     Oracle: Echinacea purpurea AND Asclepias tuberosa must be present
# ===========================================================================

def test_pollinators_east_contains_echinacea():
    """plants_for_pollinators('east') includes Echinacea purpurea."""
    from kerf_landscape.plant_catalog import plants_for_pollinators

    results = plants_for_pollinators("east")
    sci_names = {sp.scientific_name for sp in results}
    assert "Echinacea purpurea" in sci_names, (
        f"Echinacea purpurea not in east pollinator list: {sci_names}"
    )


def test_pollinators_east_contains_asclepias():
    """plants_for_pollinators('east') includes Asclepias tuberosa (monarch host)."""
    from kerf_landscape.plant_catalog import plants_for_pollinators

    results = plants_for_pollinators("east")
    sci_names = {sp.scientific_name for sp in results}
    assert "Asclepias tuberosa" in sci_names, (
        f"Asclepias tuberosa not in east pollinator list: {sci_names}"
    )


def test_pollinators_east_nonempty():
    """plants_for_pollinators('east') returns multiple species."""
    from kerf_landscape.plant_catalog import plants_for_pollinators

    results = plants_for_pollinators("east")
    assert len(results) >= 5


def test_pollinators_west_nonempty():
    """plants_for_pollinators('west') returns at least one species."""
    from kerf_landscape.plant_catalog import plants_for_pollinators

    results = plants_for_pollinators("west")
    assert len(results) >= 1


def test_pollinators_south_nonempty():
    """plants_for_pollinators('south') returns at least one species."""
    from kerf_landscape.plant_catalog import plants_for_pollinators

    results = plants_for_pollinators("south")
    assert len(results) >= 1


def test_pollinators_north_nonempty():
    """plants_for_pollinators('north') returns at least one species."""
    from kerf_landscape.plant_catalog import plants_for_pollinators

    results = plants_for_pollinators("north")
    assert len(results) >= 1


def test_pollinators_unknown_region_returns_empty():
    """Unknown region returns empty list."""
    from kerf_landscape.plant_catalog import plants_for_pollinators

    results = plants_for_pollinators("antarctica")  # type: ignore[arg-type]
    assert results == []


# ===========================================================================
# 4.  Deer-resistant filter
#     Oracle: all returned species have deer_resistant=True
# ===========================================================================

def test_filter_deer_resistant_all_true():
    """filter_plants(deer_resistant=True) returns only deer_resistant=True species."""
    from kerf_landscape.plant_catalog import filter_plants

    results = filter_plants(deer_resistant=True)
    assert len(results) > 0, "At least some catalog species should be deer-resistant"
    for sp in results:
        assert sp.deer_resistant is True, (
            f"{sp.scientific_name} has deer_resistant={sp.deer_resistant}, expected True"
        )


def test_filter_deer_resistant_zone5():
    """filter_plants(usda_zone=5, deer_resistant=True) returns deer-resistant zone-5 species."""
    from kerf_landscape.plant_catalog import filter_plants

    results = filter_plants(usda_zone=5, deer_resistant=True)
    assert len(results) >= 1, "Expected at least one deer-resistant plant in zone 5"
    for sp in results:
        assert sp.deer_resistant is True
        assert sp.usda_zones_min <= 5 <= sp.usda_zones_max


def test_filter_deer_not_resistant():
    """filter_plants(deer_resistant=False) returns only deer_resistant=False species."""
    from kerf_landscape.plant_catalog import filter_plants

    results = filter_plants(deer_resistant=False)
    assert len(results) > 0
    for sp in results:
        assert sp.deer_resistant is False


# ===========================================================================
# 5.  Catalog integrity
# ===========================================================================

def test_catalog_has_100_plus_species():
    """PLANT_CATALOG contains at least 100 entries (task DoD)."""
    from kerf_landscape.plant_catalog import PLANT_CATALOG

    assert len(PLANT_CATALOG) >= 100, (
        f"Catalog has {len(PLANT_CATALOG)} entries, expected ≥ 100"
    )


def test_catalog_all_required_fields():
    """Every PlantSpecies entry has required non-empty fields."""
    from kerf_landscape.plant_catalog import PLANT_CATALOG

    for sci, sp in PLANT_CATALOG.items():
        assert sp.scientific_name, f"{sci}: scientific_name is empty"
        assert sp.common_name, f"{sci}: common_name is empty"
        assert sp.kind in (
            "deciduous_tree", "evergreen", "shrub", "perennial", "grass", "groundcover"
        ), f"{sci}: invalid kind {sp.kind!r}"
        assert sp.mature_height_m > 0, f"{sci}: mature_height_m must be > 0"
        assert sp.mature_spread_m > 0, f"{sci}: mature_spread_m must be > 0"
        assert sp.growth_rate_cm_per_year >= 0, f"{sci}: growth_rate_cm_per_year must be ≥ 0"
        assert 1 <= sp.usda_zones_min <= 13, f"{sci}: usda_zones_min {sp.usda_zones_min} out of 1–13"
        assert 1 <= sp.usda_zones_max <= 13, f"{sci}: usda_zones_max {sp.usda_zones_max} out of 1–13"
        assert sp.usda_zones_min <= sp.usda_zones_max, f"{sci}: min zone > max zone"
        assert sp.light in ("full_sun", "partial_shade", "shade"), (
            f"{sci}: invalid light {sp.light!r}"
        )
        assert sp.water in ("low", "medium", "high"), f"{sci}: invalid water {sp.water!r}"
        assert isinstance(sp.deer_resistant, bool), f"{sci}: deer_resistant must be bool"
        assert sp.pollinator_value in ("high", "medium", "low", "none"), (
            f"{sci}: invalid pollinator_value {sp.pollinator_value!r}"
        )


def test_catalog_key_equals_lowercase_scientific_name():
    """Catalog dict keys are lowercase scientific names."""
    from kerf_landscape.plant_catalog import PLANT_CATALOG

    for key, sp in PLANT_CATALOG.items():
        assert key == sp.scientific_name.lower(), (
            f"Key {key!r} != lowercase({sp.scientific_name!r})"
        )


def test_catalog_covers_required_species():
    """Catalog includes the specifically required species from the task spec."""
    from kerf_landscape.plant_catalog import PLANT_CATALOG

    required = [
        "acer rubrum",          # red maple
        "quercus alba",         # white oak
        "cornus florida",       # dogwood
        "juniperus virginiana",  # eastern red cedar
        "hydrangea macrophylla",
        "hosta sieboldiana",
        "echinacea purpurea",
        "festuca arundinacea",  # tall fescue
        "asclepias tuberosa",   # butterfly weed (pollinator oracle)
    ]
    for sci in required:
        assert sci in PLANT_CATALOG, f"Required species {sci!r} missing from catalog"


# ===========================================================================
# 6.  LLM tool integration smoke tests
# ===========================================================================

def test_tool_lookup_plant_returns_ok():
    """landscape_lookup_plant tool returns ok payload for a known plant."""
    import json
    import asyncio
    from kerf_landscape.tools import run_landscape_lookup_plant
    from kerf_landscape._compat import ProjectCtx

    ctx = ProjectCtx()
    payload = asyncio.run(
        run_landscape_lookup_plant(ctx, json.dumps({"name": "red maple"}).encode())
    )
    result = json.loads(payload)
    assert result["ok"] is True
    assert result["scientific_name"] == "Acer rubrum"
    assert result["usda_zones_min"] == 3
    assert result["usda_zones_max"] == 9
    assert "disclaimer" in result
    assert "NOT USDA certified" in result["disclaimer"]


def test_tool_lookup_plant_not_found():
    """landscape_lookup_plant returns NOT_FOUND for unknown species."""
    import json
    import asyncio
    from kerf_landscape.tools import run_landscape_lookup_plant
    from kerf_landscape._compat import ProjectCtx

    ctx = ProjectCtx()
    payload = asyncio.run(
        run_landscape_lookup_plant(ctx, json.dumps({"name": "xyzzy bogusplant"}).encode())
    )
    result = json.loads(payload)
    assert result.get("code") == "NOT_FOUND"


def test_tool_filter_plants_returns_ok():
    """landscape_filter_plants tool returns ok payload and species list."""
    import json
    import asyncio
    from kerf_landscape.tools import run_landscape_filter_plants
    from kerf_landscape._compat import ProjectCtx

    ctx = ProjectCtx()
    payload = asyncio.run(
        run_landscape_filter_plants(
            ctx,
            json.dumps({"usda_zone": 5, "light": "full_sun", "water": "low"}).encode()
        )
    )
    result = json.loads(payload)
    assert result["ok"] is True
    assert result["count"] >= 5
    assert len(result["plants"]) == result["count"]
    assert "disclaimer" in result
    assert "NOT USDA certified" in result["disclaimer"]


def test_tool_filter_plants_deer_resistant():
    """landscape_filter_plants with deer_resistant=true returns only resistant species."""
    import json
    import asyncio
    from kerf_landscape.tools import run_landscape_filter_plants
    from kerf_landscape._compat import ProjectCtx

    ctx = ProjectCtx()
    payload = asyncio.run(
        run_landscape_filter_plants(
            ctx,
            json.dumps({"usda_zone": 5, "deer_resistant": True}).encode()
        )
    )
    result = json.loads(payload)
    assert result["ok"] is True
    assert result["count"] >= 1
    for plant in result["plants"]:
        assert plant["deer_resistant"] is True
