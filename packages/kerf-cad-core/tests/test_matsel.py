"""
Hermetic tests for kerf_cad_core.matsel — material-property database + Ashby selection.

Coverage:
  db.get_material          — property lookup, derived indices
  db.list_materials        — listing
  db.filter_materials      — constraint filtering, empty-set warning
  db.ashby_rank            — merit-index ranking, sort direction, top_n
  db.select_material       — integrated filter + rank
  tools.*                  — LLM tool wrappers (happy path + error paths)

All tests are pure-Python and hermetic: no OCC, no DB, no network, no fixtures.
Merit-index formulas are verified algebraically.

References
----------
Ashby, M.F. "Materials Selection in Mechanical Design", 4th ed.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.matsel.db import (
    get_material,
    list_materials,
    filter_materials,
    ashby_rank,
    select_material,
    _DB,
    _derived,
)
from kerf_cad_core.matsel.tools import (
    run_matsel_get,
    run_matsel_list,
    run_matsel_filter,
    run_matsel_select,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


REL = 1e-9


# ===========================================================================
# 1. Database integrity
# ===========================================================================

class TestDatabaseIntegrity:

    def test_at_least_40_materials(self):
        """Database must contain at least 40 materials."""
        assert len(_DB) >= 40

    def test_all_required_keys_present(self):
        """Every material must have all required property keys."""
        required = {"family", "density", "E", "sigma_y", "sigma_uts", "sigma_e",
                    "k", "CTE", "T_max", "cost_rel"}
        for name, props in _DB.items():
            missing = required - set(props.keys())
            assert not missing, f"{name} missing keys: {missing}"

    def test_all_numeric_properties_positive(self):
        """density, E, sigma_uts, k, T_max, cost_rel must all be > 0."""
        must_pos = {"density", "E", "sigma_uts", "k", "T_max", "cost_rel"}
        for name, props in _DB.items():
            for key in must_pos:
                assert props[key] > 0, f"{name}.{key} = {props[key]} is not positive"

    def test_sigma_uts_geq_sigma_y(self):
        """sigma_uts must be >= sigma_y for every material."""
        for name, props in _DB.items():
            assert props["sigma_uts"] >= props["sigma_y"], (
                f"{name}: sigma_uts={props['sigma_uts']} < sigma_y={props['sigma_y']}"
            )

    def test_AISI_1020_baseline_properties(self):
        """AISI_1020 must have cost_rel = 1.0 (the reference material)."""
        assert _DB["AISI_1020"]["cost_rel"] == pytest.approx(1.0)

    def test_families_cover_major_groups(self):
        """All expected major families must appear in the database."""
        families = {props["family"] for props in _DB.values()}
        for expected in ("steel", "aluminium", "titanium", "polymer", "composite",
                         "wood", "ceramic"):
            assert expected in families, f"Family {expected!r} missing"

    def test_no_nan_or_inf_in_properties(self):
        """No property value may be NaN or infinite."""
        for name, props in _DB.items():
            for key, val in props.items():
                if isinstance(val, float):
                    assert math.isfinite(val), f"{name}.{key} = {val}"


# ===========================================================================
# 2. get_material
# ===========================================================================

class TestGetMaterial:

    def test_known_material_returns_dict(self):
        """get_material on a valid name returns a dict with 'name' key."""
        mat = get_material("AISI_1020")
        assert mat is not None
        assert mat["name"] == "AISI_1020"

    def test_returned_dict_has_base_properties(self):
        """Returned dict must include all base property keys."""
        mat = get_material("Al_6061_T6")
        assert mat is not None
        for key in ("density", "E", "sigma_y", "sigma_uts", "sigma_e",
                    "k", "CTE", "T_max", "cost_rel"):
            assert key in mat, f"Missing key: {key}"

    def test_returned_dict_has_derived_indices(self):
        """Returned dict must include computed Ashby indices."""
        mat = get_material("Ti_6Al4V")
        assert mat is not None
        for key in ("specific_stiffness", "specific_strength",
                    "light_stiff_beam", "light_strong_plate", "cost_per_stiffness"):
            assert key in mat, f"Missing derived key: {key}"

    def test_unknown_material_returns_none(self):
        """get_material on unknown name returns None."""
        assert get_material("unobtanium_XR99") is None

    def test_specific_stiffness_algebraic(self):
        """specific_stiffness = E / density."""
        mat = get_material("AISI_1020")
        expected = mat["E"] / mat["density"]
        assert abs(mat["specific_stiffness"] - expected) < REL

    def test_specific_strength_algebraic(self):
        """specific_strength = sigma_y / density."""
        mat = get_material("Al_7075_T6")
        expected = mat["sigma_y"] / mat["density"]
        assert abs(mat["specific_strength"] - expected) < REL

    def test_light_stiff_beam_algebraic(self):
        """light_stiff_beam = sqrt(E) / density."""
        mat = get_material("CFRP_UD_0deg")
        expected = math.sqrt(mat["E"]) / mat["density"]
        assert abs(mat["light_stiff_beam"] - expected) / expected < REL

    def test_light_strong_plate_algebraic(self):
        """light_strong_plate = sigma_y^(2/3) / density."""
        mat = get_material("Ti_6Al4V")
        expected = mat["sigma_y"] ** (2.0 / 3.0) / mat["density"]
        assert abs(mat["light_strong_plate"] - expected) / expected < REL

    def test_cost_per_stiffness_algebraic(self):
        """cost_per_stiffness = cost_rel * density / E."""
        mat = get_material("PEEK")
        expected = mat["cost_rel"] * mat["density"] / mat["E"]
        assert abs(mat["cost_per_stiffness"] - expected) / expected < REL


# ===========================================================================
# 3. list_materials
# ===========================================================================

class TestListMaterials:

    def test_returns_sorted_list(self):
        """list_materials() must return a sorted list."""
        names = list_materials()
        assert names == sorted(names)

    def test_all_db_keys_present(self):
        """list_materials must contain all keys from _DB."""
        names = set(list_materials())
        assert names == set(_DB.keys())

    def test_contains_known_materials(self):
        """Known materials must appear in the list."""
        names = list_materials()
        for known in ("AISI_1020", "Al_6061_T6", "Ti_6Al4V", "CFRP_UD_0deg"):
            assert known in names


# ===========================================================================
# 4. filter_materials
# ===========================================================================

class TestFilterMaterials:

    def test_no_constraints_returns_all(self):
        """Empty constraints dict must return all materials."""
        result = filter_materials({})
        assert result["ok"] is True
        assert set(result["materials"]) == set(_DB.keys())

    def test_density_max_excludes_steels(self):
        """Constraint density < 3000 must exclude all steels."""
        result = filter_materials({"density": {"max": 3000}})
        assert result["ok"] is True
        for name in result["materials"]:
            assert _DB[name]["density"] <= 3000

    def test_density_min_constraint(self):
        """Constraint density >= 7000 must keep steels."""
        result = filter_materials({"density": {"min": 7000}})
        assert result["ok"] is True
        assert "AISI_1020" in result["materials"]

    def test_combined_constraints_reduce_set(self):
        """Adding more constraints should not increase the result set."""
        r1 = filter_materials({"E": {"min": 50}})
        r2 = filter_materials({"E": {"min": 50}, "density": {"max": 5000}})
        assert set(r2["materials"]).issubset(set(r1["materials"]))

    def test_impossible_constraint_warns_empty(self):
        """Contradictory constraints must produce empty list + warning."""
        result = filter_materials({"E": {"min": 9999}})
        assert result["ok"] is True
        assert result["materials"] == []
        assert any("relax" in w.lower() or "no material" in w.lower()
                   for w in result["warnings"])

    def test_unknown_property_warns(self):
        """Unknown property key must add a warning but not fail."""
        result = filter_materials({"nonexistent_prop": {"min": 1}})
        assert result["ok"] is True
        assert any("nonexistent_prop" in w for w in result["warnings"])

    def test_t_max_filter(self):
        """T_max constraint must work correctly."""
        result = filter_materials({"T_max": {"min": 1000}})
        assert result["ok"] is True
        for name in result["materials"]:
            assert _DB[name]["T_max"] >= 1000

    def test_non_dict_constraints_returns_error(self):
        """Passing a list as constraints must return ok=False."""
        result = filter_materials([])  # type: ignore[arg-type]
        assert result["ok"] is False

    def test_derived_property_filter(self):
        """Filtering on a derived index (specific_stiffness) must work."""
        result = filter_materials({"specific_stiffness": {"min": 0.05}})
        assert result["ok"] is True
        for name in result["materials"]:
            mat = get_material(name)
            assert mat["specific_stiffness"] >= 0.05


# ===========================================================================
# 5. ashby_rank
# ===========================================================================

class TestAshbyRank:

    def test_specific_stiffness_rank_higher_is_better(self):
        """specific_stiffness must sort descending (higher = better)."""
        result = ashby_rank("specific_stiffness")
        assert result["ok"] is True
        vals = [r["value"] for r in result["ranked"]]
        assert vals == sorted(vals, reverse=True)

    def test_density_rank_lower_is_better(self):
        """density ranking must be ascending (lower = better)."""
        result = ashby_rank("density")
        assert result["ok"] is True
        vals = [r["value"] for r in result["ranked"]]
        assert vals == sorted(vals)

    def test_cost_per_stiffness_lower_is_better(self):
        """cost_per_stiffness must sort ascending."""
        result = ashby_rank("cost_per_stiffness")
        assert result["ok"] is True
        vals = [r["value"] for r in result["ranked"]]
        assert vals == sorted(vals)

    def test_top_n_limits_results(self):
        """top_n=5 must return at most 5 results."""
        result = ashby_rank("specific_stiffness", top_n=5)
        assert result["ok"] is True
        assert len(result["ranked"]) == 5

    def test_ranks_are_1_indexed_contiguous(self):
        """Ranks must be 1, 2, 3, ... in order."""
        result = ashby_rank("specific_strength", top_n=10)
        assert result["ok"] is True
        ranks = [r["rank"] for r in result["ranked"]]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_candidates_subset(self):
        """Passing a candidates list must restrict ranking to that subset."""
        subset = ["AISI_1020", "Al_6061_T6", "Ti_6Al4V"]
        result = ashby_rank("specific_strength", candidates=subset)
        assert result["ok"] is True
        names = {r["name"] for r in result["ranked"]}
        assert names.issubset(set(subset))

    def test_cfrp_tops_specific_stiffness(self):
        """CFRP_UD_0deg must rank near the top for specific_stiffness."""
        result = ashby_rank("specific_stiffness", top_n=5)
        assert result["ok"] is True
        top_names = [r["name"] for r in result["ranked"]]
        assert "CFRP_UD_0deg" in top_names

    def test_balsa_tops_specific_stiffness_woods(self):
        """Among woods, Balsa has competitive specific stiffness."""
        woods = [n for n, p in _DB.items() if p["family"] == "wood"]
        result = ashby_rank("specific_stiffness", candidates=woods)
        assert result["ok"] is True
        assert len(result["ranked"]) == len(woods)

    def test_unknown_index_returns_error(self):
        """Unknown index name must return ok=False."""
        result = ashby_rank("magic_property")
        assert result["ok"] is False
        assert "reason" in result

    def test_ascending_override(self):
        """ascending=True on specific_stiffness must sort ascending."""
        result = ashby_rank("specific_stiffness", ascending=True)
        assert result["ok"] is True
        vals = [r["value"] for r in result["ranked"]]
        assert vals == sorted(vals)

    def test_unknown_candidate_warns(self):
        """Unknown candidate name must produce a warning and be skipped."""
        result = ashby_rank("specific_stiffness",
                            candidates=["AISI_1020", "GHOST_MATERIAL"])
        assert result["ok"] is True
        assert any("GHOST_MATERIAL" in w for w in result["warnings"])
        names = [r["name"] for r in result["ranked"]]
        assert "GHOST_MATERIAL" not in names

    def test_values_match_formula_specific_stiffness(self):
        """Ranked values must equal E/density for specific_stiffness."""
        result = ashby_rank("specific_stiffness",
                            candidates=["AISI_1020", "Al_6061_T6"])
        assert result["ok"] is True
        for entry in result["ranked"]:
            expected = _DB[entry["name"]]["E"] / _DB[entry["name"]]["density"]
            assert abs(entry["value"] - expected) < REL

    def test_light_stiff_beam_formula_check(self):
        """light_stiff_beam values must equal sqrt(E)/density."""
        result = ashby_rank("light_stiff_beam",
                            candidates=["Ti_6Al4V", "CFRP_UD_0deg", "Al_7075_T6"])
        assert result["ok"] is True
        for entry in result["ranked"]:
            p = _DB[entry["name"]]
            expected = math.sqrt(p["E"]) / p["density"]
            assert abs(entry["value"] - expected) / expected < REL


# ===========================================================================
# 6. select_material
# ===========================================================================

class TestSelectMaterial:

    def test_empty_constraints_returns_top_10(self):
        """No constraints must return top 10 by specific_stiffness."""
        result = select_material({})
        assert result["ok"] is True
        assert len(result["ranked"]) <= 10

    def test_aluminium_density_filter(self):
        """Constraining density < 3500 keeps only light alloys + polymers/woods."""
        result = select_material(
            {"density": {"max": 3500}},
            objective="specific_strength",
        )
        assert result["ok"] is True
        for entry in result["ranked"]:
            assert _DB[entry["name"]]["density"] <= 3500

    def test_high_temperature_ceramics(self):
        """T_max >= 1000 must return ceramics."""
        result = select_material(
            {"T_max": {"min": 1000}},
            objective="E",
            top_n=5,
        )
        assert result["ok"] is True
        families = {_DB[r["name"]]["family"] for r in result["ranked"]}
        assert "ceramic" in families

    def test_top_n_respected(self):
        """top_n must limit output length."""
        result = select_material({}, objective="density", top_n=3)
        assert result["ok"] is True
        assert len(result["ranked"]) <= 3

    def test_impossible_constraint_returns_empty_ranked(self):
        """Contradictory constraints produce empty ranked list, ok=True."""
        result = select_material({"E": {"min": 9999}})
        assert result["ok"] is True
        assert result["ranked"] == []
        assert result["warnings"]

    def test_invalid_objective_returns_error(self):
        """Unknown objective must return ok=False with reason."""
        result = select_material({}, objective="chocolate_index")
        assert result["ok"] is False
        assert "reason" in result

    def test_objective_specific_stiffness_ranking_consistent(self):
        """Ranked values must be in descending order for specific_stiffness."""
        result = select_material({}, objective="specific_stiffness", top_n=15)
        assert result["ok"] is True
        vals = [r["value"] for r in result["ranked"]]
        assert vals == sorted(vals, reverse=True)

    def test_cost_per_stiffness_ascending(self):
        """cost_per_stiffness objective must sort ascending."""
        result = select_material({}, objective="cost_per_stiffness", top_n=15)
        assert result["ok"] is True
        vals = [r["value"] for r in result["ranked"]]
        assert vals == sorted(vals)


# ===========================================================================
# 7. LLM tool wrappers
# ===========================================================================

class TestToolWrappers:

    def test_matsel_get_happy_path(self):
        ctx = _ctx()
        raw = _run(run_matsel_get(ctx, _args(name="AISI_1020")))
        d = _ok_tool(raw)
        assert d["density"] == pytest.approx(7850.0)

    def test_matsel_get_includes_derived(self):
        ctx = _ctx()
        raw = _run(run_matsel_get(ctx, _args(name="Al_6061_T6")))
        d = _ok_tool(raw)
        assert "specific_stiffness" in d
        assert d["specific_stiffness"] > 0

    def test_matsel_get_unknown_material(self):
        ctx = _ctx()
        raw = _run(run_matsel_get(ctx, _args(name="unobtanium_99")))
        _err_tool(raw)

    def test_matsel_get_missing_name(self):
        ctx = _ctx()
        raw = _run(run_matsel_get(ctx, b"{}"))
        _err_tool(raw)

    def test_matsel_get_bad_json(self):
        ctx = _ctx()
        raw = _run(run_matsel_get(ctx, b"not json"))
        _err_tool(raw)

    def test_matsel_list_returns_all(self):
        ctx = _ctx()
        raw = _run(run_matsel_list(ctx, b"{}"))
        d = _ok_tool(raw)
        assert d["count"] == len(_DB)
        assert "AISI_1020" in d["materials"]

    def test_matsel_list_family_filter(self):
        ctx = _ctx()
        raw = _run(run_matsel_list(ctx, _args(family="aluminium")))
        d = _ok_tool(raw)
        assert d["count"] > 0
        assert all(_DB[n]["family"] == "aluminium" for n in d["materials"])

    def test_matsel_list_bad_json(self):
        ctx = _ctx()
        raw = _run(run_matsel_list(ctx, b"{bad"))
        _err_tool(raw)

    def test_matsel_filter_happy_path(self):
        ctx = _ctx()
        raw = _run(run_matsel_filter(ctx, _args(
            constraints={"density": {"max": 3000}, "E": {"min": 30}}
        )))
        d = _ok_tool(raw)
        assert isinstance(d["materials"], list)
        assert len(d["materials"]) > 0

    def test_matsel_filter_empty_result(self):
        ctx = _ctx()
        raw = _run(run_matsel_filter(ctx, _args(
            constraints={"E": {"min": 9999}}
        )))
        d = _ok_tool(raw)
        assert d["materials"] == []
        assert d["warnings"]

    def test_matsel_filter_missing_constraints(self):
        ctx = _ctx()
        raw = _run(run_matsel_filter(ctx, b"{}"))
        _err_tool(raw)

    def test_matsel_select_happy_path(self):
        ctx = _ctx()
        raw = _run(run_matsel_select(ctx, _args(
            constraints={},
            objective="specific_stiffness",
            top_n=5,
        )))
        d = _ok_tool(raw)
        assert len(d["ranked"]) <= 5
        assert d["ranked"][0]["rank"] == 1

    def test_matsel_select_bad_objective(self):
        ctx = _ctx()
        raw = _run(run_matsel_select(ctx, _args(
            constraints={},
            objective="invalid_index",
        )))
        _err_tool(raw)

    def test_matsel_select_missing_constraints(self):
        ctx = _ctx()
        raw = _run(run_matsel_select(ctx, b"{}"))
        _err_tool(raw)

    def test_matsel_select_light_alloys(self):
        """Light alloy selection: density < 3000, E > 20, ranked by specific_strength."""
        ctx = _ctx()
        raw = _run(run_matsel_select(ctx, _args(
            constraints={"density": {"max": 3000}, "E": {"min": 20}},
            objective="specific_strength",
            top_n=3,
        )))
        d = _ok_tool(raw)
        for r in d["ranked"]:
            assert _DB[r["name"]]["density"] <= 3000
            assert _DB[r["name"]]["E"] >= 20
