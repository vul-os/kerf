"""
Tests for kerf_cad_core.materials.ashby_selection — Ashby material selection
indices, multi-objective scoring, Pareto front, and chart data.

Coverage
--------
* Material index formula strings
* SelectionConstraint evaluation
* select_materials() multi-constraint + multi-objective
* AshbyChart structure and consistency
* pareto_front() non-dominated set
* Physical plausibility of selections
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.materials.material_db import (
    Material,
    MaterialDatabase,
    default_engineering_materials_db,
)
from kerf_cad_core.materials.ashby_selection import (
    AshbyChart,
    SelectionConstraint,
    SelectionObjective,
    SelectionResult,
    build_ashby_chart,
    material_index_minimum_cost_stiff_beam,
    material_index_minimum_mass_stiff_beam_bending,
    material_index_minimum_mass_strong_beam_bending,
    material_index_minimum_mass_strong_tie,
    pareto_front,
    select_materials,
    _eval_formula,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db() -> MaterialDatabase:
    return default_engineering_materials_db()


# ---------------------------------------------------------------------------
# Ashby index formula strings
# ---------------------------------------------------------------------------

def test_index_stiff_beam_formula():
    """E^(1/2)/ρ formula string — Ashby (2017) Table 5.1."""
    formula = material_index_minimum_mass_stiff_beam_bending()
    assert "youngs_modulus_gpa**0.5" in formula
    assert "density_kg_m3" in formula


def test_index_strong_tie_formula():
    """σy/ρ formula string — Ashby (2017) Table 5.1."""
    formula = material_index_minimum_mass_strong_tie()
    assert "yield_strength_mpa" in formula
    assert "density_kg_m3" in formula


def test_index_strong_beam_formula():
    """σy^(2/3)/ρ formula string — Ashby (2017) Table 5.1."""
    formula = material_index_minimum_mass_strong_beam_bending()
    assert "0.667" in formula or "2/3" in formula or "2.0/3" in formula
    assert "density_kg_m3" in formula


def test_index_cost_stiff_beam_formula():
    """E^(1/2)/(ρ·cost) formula string — Ashby (2017) §5.7."""
    formula = material_index_minimum_cost_stiff_beam()
    assert "youngs_modulus_gpa**0.5" in formula
    assert "cost_per_kg_usd" in formula


# ---------------------------------------------------------------------------
# _eval_formula
# ---------------------------------------------------------------------------

def test_eval_formula_simple(db: MaterialDatabase):
    steel = db.by_name("AISI_1018_steel")
    val = _eval_formula("youngs_modulus_gpa", steel)
    assert val == pytest.approx(200.0, abs=1.0)


def test_eval_formula_index(db: MaterialDatabase):
    al = db.by_name("AA6061_T6")
    # E^(1/2)/ρ — should be about sqrt(69)/2700
    expected = math.sqrt(69.0) / 2700.0
    val = _eval_formula("youngs_modulus_gpa**0.5/density_kg_m3", al)
    assert val == pytest.approx(expected, rel=1e-3)


def test_eval_formula_none_property_returns_nan(db: MaterialDatabase):
    """Ceramic with None fatigue endurance → NaN in formula using that field."""
    al2o3 = db.by_name("Al2O3_99pct")
    val = _eval_formula("fatigue_endurance_mpa/density_kg_m3", al2o3)
    assert math.isnan(val)


# ---------------------------------------------------------------------------
# SelectionConstraint
# ---------------------------------------------------------------------------

def test_constraint_gte_satisfied(db: MaterialDatabase):
    steel = db.by_name("AISI_4340_QT")
    c = SelectionConstraint("yield_strength_mpa", ">=", 1000.0)
    assert c.satisfied_by(steel)


def test_constraint_gte_failed(db: MaterialDatabase):
    al = db.by_name("AA6061_T6")
    c = SelectionConstraint("yield_strength_mpa", ">=", 1000.0)
    assert not c.satisfied_by(al)


def test_constraint_lte(db: MaterialDatabase):
    cfrp = db.by_name("CFRP_unidirectional")
    c = SelectionConstraint("density_kg_m3", "<=", 2000.0)
    assert c.satisfied_by(cfrp)


def test_constraint_none_property_fails(db: MaterialDatabase):
    """A None-valued property should fail any constraint."""
    al2o3 = db.by_name("Al2O3_99pct")
    c = SelectionConstraint("fatigue_endurance_mpa", ">=", 0.0)
    assert not c.satisfied_by(al2o3)


def test_constraint_bad_operator():
    from kerf_cad_core.materials.material_db import Material
    mat = Material(
        name="test", category="metal",
        youngs_modulus_gpa=200, yield_strength_mpa=300, ultimate_strength_mpa=400,
        density_kg_m3=8000, poisson=0.3, fatigue_endurance_mpa=150,
        thermal_conductivity_w_m_k=50, thermal_expansion_per_k=12e-6,
        specific_heat_j_kg_k=480, melting_point_c=1500, max_service_temp_c=400,
        electrical_resistivity_ohm_m=1e-7,
        cost_per_kg_usd=1.0, embodied_energy_mj_kg=25, co2_footprint_kg_co2_per_kg=2.0,
    )
    c = SelectionConstraint("youngs_modulus_gpa", "??", 100.0)
    with pytest.raises(ValueError, match="Unknown operator"):
        c.satisfied_by(mat)


# ---------------------------------------------------------------------------
# select_materials — basic
# ---------------------------------------------------------------------------

def test_select_materials_requires_objectives(db: MaterialDatabase):
    with pytest.raises(ValueError, match="[Oo]bjective"):
        select_materials(db, [], [])


def test_select_materials_top_k_respected(db: MaterialDatabase):
    objectives = [SelectionObjective(
        formula="yield_strength_mpa/density_kg_m3",
        direction="maximize",
    )]
    results = select_materials(db, [], objectives, top_k=5)
    assert len(results) <= 5


def test_select_materials_constraint_density_and_high_stiffness(db: MaterialDatabase):
    """Light materials + maximize E^(1/2)/rho — composites and ceramics should dominate."""
    constraints = [
        SelectionConstraint("density_kg_m3", "<=", 3000.0),
    ]
    objectives = [SelectionObjective(
        formula=material_index_minimum_mass_stiff_beam_bending(),
        direction="maximize",
    )]
    results = select_materials(db, constraints, objectives, top_k=10)
    # Must have results
    assert len(results) >= 1
    # Top results should satisfy constraint
    passing = [r for r in results if r.constraints_satisfied]
    assert len(passing) >= 1
    # Top constrained result should be composites or ceramics (high E/ρ)
    top = passing[0]
    assert top.material.category in ("composite", "ceramic", "natural")


def test_select_materials_lightest_strong_tie_favors_cfrp(db: MaterialDatabase):
    """Maximize σy/ρ for min-mass strong tie — CFRP should rank near top."""
    objectives = [SelectionObjective(
        formula="yield_strength_mpa/density_kg_m3",
        direction="maximize",
    )]
    results = select_materials(db, [], objectives, top_k=5)
    top_names = [r.material.name for r in results]
    # CFRP unidirectional has σy=1500/ρ=1550 → very high σy/ρ
    assert any("CFRP" in n for n in top_names), (
        f"Expected CFRP in top 5 for specific strength, got: {top_names}"
    )


def test_select_materials_density_constraint_lt_3000_excludes_ceramics(db: MaterialDatabase):
    """density < 3000 should exclude Al2O3 (3960 kg/m3) and ZrO2 (6050)."""
    constraints = [
        SelectionConstraint("density_kg_m3", "<", 3000.0),
    ]
    objectives = [SelectionObjective(
        formula="youngs_modulus_gpa**0.5/density_kg_m3",
        direction="maximize",
    )]
    results = select_materials(db, constraints, objectives, top_k=15)
    passing = [r for r in results if r.constraints_satisfied]
    heavy_ceramics = [r.material.name for r in passing
                      if r.material.name in ("Al2O3_99pct", "ZrO2_TZP")]
    assert len(heavy_ceramics) == 0, f"Heavy ceramics leaked through constraint: {heavy_ceramics}"


def test_select_materials_multi_objective_weighted(db: MaterialDatabase):
    """Multi-objective: high strength AND low density with equal weights."""
    constraints: list[SelectionConstraint] = []
    objectives = [
        SelectionObjective("yield_strength_mpa", "maximize", weight=1.0),
        SelectionObjective("density_kg_m3", "minimize", weight=1.0),
    ]
    results = select_materials(db, constraints, objectives, top_k=10)
    assert len(results) >= 5
    # Scores should be descending
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_select_materials_lightest_stiff_beam_favors_composites_ceramics(db: MaterialDatabase):
    """
    'Selecting for lightest stiff beam' should rank composites + ceramics
    over polymers (task assertion: composites + ceramics over polymers).

    Ashby (2017) §5.4 Table 5.1: E^(1/2)/ρ for CFRP ≈ sqrt(135)/1550 ≈ 0.0075
    vs PA66 ≈ sqrt(2.8)/1140 ≈ 0.00147.
    """
    constraints: list[SelectionConstraint] = []
    objectives = [SelectionObjective(
        formula="youngs_modulus_gpa**0.5/density_kg_m3",
        direction="maximize",
    )]
    results = select_materials(db, constraints, objectives, top_k=10)
    passing = results  # no constraints, all pass
    top5_categories = [r.material.category for r in passing[:5]]
    # At least 2 composites or ceramics in top 5
    high_perf = sum(1 for c in top5_categories if c in ("composite", "ceramic"))
    polymers_in_top5 = sum(1 for c in top5_categories if c == "polymer")
    assert high_perf >= 2, (
        f"Expected composites/ceramics to dominate top 5, got: "
        f"{[(r.material.name, r.material.category) for r in passing[:5]]}"
    )
    # Composites/ceramics beat polymers
    assert high_perf > polymers_in_top5


def test_select_materials_ranks_assigned(db: MaterialDatabase):
    """Ranks must be sequential starting from 1."""
    objectives = [SelectionObjective("youngs_modulus_gpa", "maximize")]
    results = select_materials(db, [], objectives, top_k=5)
    ranks = [r.rank for r in results]
    assert ranks == list(range(1, len(results) + 1))


def test_select_materials_constraint_fails_reflected(db: MaterialDatabase):
    """Materials failing constraints must have constraints_satisfied=False."""
    constraints = [SelectionConstraint("density_kg_m3", "<=", 500.0)]
    objectives = [SelectionObjective("youngs_modulus_gpa", "maximize")]
    results = select_materials(db, constraints, objectives, top_k=20)
    for r in results:
        if r.material.density_kg_m3 > 500.0:
            assert not r.constraints_satisfied
            assert len(r.failed_constraints) > 0


# ---------------------------------------------------------------------------
# AshbyChart
# ---------------------------------------------------------------------------

def test_build_ashby_chart_lengths_match(db: MaterialDatabase):
    """x_values, y_values, materials must all have same length."""
    chart = build_ashby_chart(db, "density_kg_m3", "youngs_modulus_gpa")
    assert len(chart.x_values) == len(chart.y_values) == len(chart.materials)


def test_build_ashby_chart_positive_values(db: MaterialDatabase):
    """All chart values must be positive (needed for log scale)."""
    chart = build_ashby_chart(db, "density_kg_m3", "yield_strength_mpa")
    for x, y in zip(chart.x_values, chart.y_values):
        assert x > 0, f"Non-positive x value: {x}"
        assert y > 0, f"Non-positive y value: {y}"


def test_build_ashby_chart_log_scale_defaults(db: MaterialDatabase):
    chart = build_ashby_chart(db, "density_kg_m3", "youngs_modulus_gpa")
    assert chart.log_x is True
    assert chart.log_y is True


def test_build_ashby_chart_property_names_stored(db: MaterialDatabase):
    chart = build_ashby_chart(db, "density_kg_m3", "youngs_modulus_gpa")
    assert chart.x_property == "density_kg_m3"
    assert chart.y_property == "youngs_modulus_gpa"


def test_build_ashby_chart_excludes_none_values(db: MaterialDatabase):
    """Materials with None for a property must be excluded (fatigue for ceramics)."""
    chart_fatigue = build_ashby_chart(db, "density_kg_m3", "fatigue_endurance_mpa")
    # Al2O3 and SiC have fatigue_endurance_mpa=None; must not appear
    ceramic_names = {m.name for m in chart_fatigue.materials if m.category == "ceramic"}
    for name in ("Al2O3_99pct", "SiC", "ZrO2_TZP", "Si3N4"):
        assert name not in ceramic_names, (
            f"Ceramic {name} with None fatigue should be excluded from fatigue chart"
        )


def test_build_ashby_chart_covers_most_materials(db: MaterialDatabase):
    """Density vs strength chart (no None values) should include almost all materials."""
    chart = build_ashby_chart(db, "density_kg_m3", "yield_strength_mpa")
    assert len(chart.materials) >= 40


# ---------------------------------------------------------------------------
# Pareto front
# ---------------------------------------------------------------------------

def test_pareto_front_returns_materials(db: MaterialDatabase):
    front = pareto_front(db, "youngs_modulus_gpa", "density_kg_m3",
                         direction_x="maximize", direction_y="minimize")
    assert len(front) >= 2


def test_pareto_front_max_e_min_density_contains_multiple(db: MaterialDatabase):
    """Maximize E vs minimize density — expect CFRP, ceramics, maybe natural."""
    front = pareto_front(db, "youngs_modulus_gpa", "density_kg_m3",
                         direction_x="maximize", direction_y="minimize")
    assert len(front) >= 3, f"Expected ≥ 3 Pareto-optimal, got {len(front)}"


def test_pareto_front_non_dominated(db: MaterialDatabase):
    """Verify returned materials are truly non-dominated."""
    x_prop = "youngs_modulus_gpa"
    y_prop = "density_kg_m3"
    front = pareto_front(db, x_prop, y_prop, direction_x="maximize", direction_y="minimize")
    front_set = {m.name for m in front}

    for m_i in front:
        xi = m_i.youngs_modulus_gpa
        yi = m_i.density_kg_m3
        # No other material in DB should dominate m_i (higher E AND lower density)
        for m_j in db.materials:
            if m_j.name == m_i.name:
                continue
            xj = m_j.youngs_modulus_gpa
            yj = m_j.density_kg_m3
            if xj is None or yj is None:
                continue
            # j strictly dominates i: E_j >= E_i and density_j <= density_i with at least one strict
            # (remember minimize density means lower is better; so "better y" = lower density)
            if xj >= xi and yj <= yi and (xj > xi or yj < yi):
                pytest.fail(
                    f"Material {m_j.name} (E={xj}, ρ={yj}) dominates Pareto member "
                    f"{m_i.name} (E={xi}, ρ={yi})"
                )


def test_pareto_front_bad_direction_raises(db: MaterialDatabase):
    with pytest.raises(ValueError):
        pareto_front(db, "youngs_modulus_gpa", "density_kg_m3", direction_x="wrong")


def test_pareto_front_maximize_both(db: MaterialDatabase):
    """Maximize both strength and modulus — should return a non-empty front."""
    front = pareto_front(db, "youngs_modulus_gpa", "yield_strength_mpa",
                         direction_x="maximize", direction_y="maximize")
    assert len(front) >= 2
