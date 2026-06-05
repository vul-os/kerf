"""
test_mold_parity_registration.py — Verify plugin registers all Moldflow/Cimatron
parity tools (injection fill, parting line, cooling, runner balance, warpage).

Covers:
  1. Plugin registers mold_injection_fill_simulate
  2. Plugin registers mold_cross_wlf_viscosity
  3. Plugin registers mold_detect_parting_line
  4. Plugin registers mold_split_cavity_core
  5. Plugin registers mold_estimate_mold_complexity
  6. Plugin registers mold_cooling_analysis (via cooling_tool)
  7. Plugin registers mold_check_runner_balance
  8. Plugin registers mold_compute_warpage_index
  9. mold_injection_fill_simulate tool runs end-to-end (square cavity, ABS)
  10. mold_injection_fill_simulate returns weld lines with 2 gates
  11. mold_cross_wlf_viscosity tool round-trip
  12. mold_detect_parting_line tool round-trip (cube B-rep)
  13. mold_split_cavity_core tool round-trip
  14. mold_compute_warpage_index tool round-trip
  15. mold_check_runner_balance tool round-trip

References:
  Hieber, C.A., Shen, S.F. (1980). J. Non-Newtonian Fluid Mech. 7, 1–32.
  Cross, M.M. (1965). J. Colloid Sci. 20, 417–437.
  Hayrettin, A. et al. (2003). Computer-Aided Design 35(12), 1109–1122.
  Chen, L.L., Rosen, D.W. (1999). J. Manufacturing Science & Engineering 121(1).
  Beaumont J.P. (2007). Runner and Gating Design Handbook, 2nd ed., §6.6, §10.
  Menges G. et al. (2001). How to Make Injection Molds, 3rd ed., §7.3.3, §8.
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()


def _mock_registration():
    """Return (app, ctx) with a mock tool registry."""
    from fastapi import FastAPI

    class _MockReg:
        def __init__(self):
            self.registered = {}
        def register(self, name, spec, handler):
            self.registered[name] = (spec, handler)

    class _MockCtx:
        def __init__(self):
            self.tools = _MockReg()

    return FastAPI(), _MockCtx()


def _registered_names():
    """Call plugin.register and return the set of registered tool names."""
    from kerf_mold.plugin import register
    app, ctx = _mock_registration()
    _run(register(app, ctx))
    return set(ctx.tools.registered.keys())


# ---------------------------------------------------------------------------
# 1–8: Registration checks
# ---------------------------------------------------------------------------

class TestPluginRegistrationParity:
    @classmethod
    def setup_class(cls):
        cls.names = _registered_names()

    def test_injection_fill_simulate_registered(self):
        """mold_injection_fill_simulate must be registered."""
        assert "mold_injection_fill_simulate" in self.names

    def test_cross_wlf_viscosity_registered(self):
        """mold_cross_wlf_viscosity must be registered."""
        assert "mold_cross_wlf_viscosity" in self.names

    def test_detect_parting_line_registered(self):
        """mold_detect_parting_line must be registered."""
        assert "mold_detect_parting_line" in self.names

    def test_split_cavity_core_registered(self):
        """mold_split_cavity_core must be registered."""
        assert "mold_split_cavity_core" in self.names

    def test_estimate_mold_complexity_registered(self):
        """mold_estimate_mold_complexity must be registered."""
        assert "mold_estimate_mold_complexity" in self.names

    def test_cooling_analysis_registered(self):
        """mold_cooling_analysis must be registered."""
        assert "mold_cooling_analysis" in self.names

    def test_runner_balance_registered(self):
        """mold_check_runner_balance must be registered."""
        assert "mold_check_runner_balance" in self.names

    def test_warpage_index_registered(self):
        """mold_compute_warpage_index must be registered."""
        assert "mold_compute_warpage_index" in self.names


# ---------------------------------------------------------------------------
# 9: mold_injection_fill_simulate end-to-end (square cavity, ABS, 1 gate)
# ---------------------------------------------------------------------------

class TestInjectionFillSimulateTool:
    def _square_outline(self):
        return [[0, 0], [100, 0], [100, 100], [0, 100]]

    def test_single_gate_fill_ok(self):
        """Single gate in square cavity: tool returns fill results with valid fields."""
        from kerf_mold.injection_fill_tools import run_mold_injection_fill_simulate
        params = {
            "part_thickness_mm": 3.0,
            "gate_locations": [[50, 50]],
            "cavity_outline_polygon": self._square_outline(),
            "polymer_name": "ABS_Cycolac_T",
            "mold_temp_c": 60.0,
            "injection_pressure_mpa": 100.0,
            "fill_time_target_s": 1.5,
            "grid_resolution": 32,
        }
        result = json.loads(_run(run_mold_injection_fill_simulate(params, CTX)))
        # ok_payload returns result dict directly (no 'ok' key); error has 'error' key
        assert "error" not in result, f"Tool returned error: {result}"
        assert "fill_time_s" in result
        assert "max_pressure_drop_mpa" in result
        assert "short_shot_risk_pct" in result
        assert math.isfinite(result["fill_time_s"])
        assert result["fill_time_s"] > 0.0
        assert result["short_shot_risk_pct"] < 20.0

    # ---------------------------------------------------------------------------
    # 10: Weld lines with 2 opposing gates
    # ---------------------------------------------------------------------------

    def test_two_gates_weld_lines(self):
        """Two opposing gates should produce weld lines."""
        from kerf_mold.injection_fill_tools import run_mold_injection_fill_simulate
        params = {
            "part_thickness_mm": 2.5,
            "gate_locations": [[5, 50], [95, 50]],
            "cavity_outline_polygon": self._square_outline(),
            "polymer_name": "ABS_Cycolac_T",
            "grid_resolution": 32,
        }
        result = json.loads(_run(run_mold_injection_fill_simulate(params, CTX)))
        assert "error" not in result, f"Tool returned error: {result}"
        assert result["weld_line_count"] > 0
        total_pts = sum(len(wl) for wl in result.get("weld_lines", []))
        assert total_pts > 0

    def test_single_gate_no_weld_lines(self):
        """Single gate should produce no weld lines."""
        from kerf_mold.injection_fill_tools import run_mold_injection_fill_simulate
        params = {
            "part_thickness_mm": 3.0,
            "gate_locations": [[50, 50]],
            "cavity_outline_polygon": self._square_outline(),
            "polymer_name": "PC_Makrolon_2407",
            "grid_resolution": 32,
        }
        result = json.loads(_run(run_mold_injection_fill_simulate(params, CTX)))
        assert "error" not in result, f"Tool returned error: {result}"
        assert result["weld_line_count"] == 0

    def test_unknown_polymer_returns_error(self):
        """Unknown polymer name must return an error payload (has 'error' key)."""
        from kerf_mold.injection_fill_tools import run_mold_injection_fill_simulate
        params = {
            "part_thickness_mm": 3.0,
            "gate_locations": [[50, 50]],
            "cavity_outline_polygon": self._square_outline(),
            "polymer_name": "NONEXISTENT_RESIN",
        }
        result = json.loads(_run(run_mold_injection_fill_simulate(params, CTX)))
        assert "error" in result

    def test_honest_caveat_in_response(self):
        """Response must include an honest caveat mentioning Hele-Shaw or 1.5D."""
        from kerf_mold.injection_fill_tools import run_mold_injection_fill_simulate
        params = {
            "part_thickness_mm": 2.0,
            "gate_locations": [[50, 50]],
            "cavity_outline_polygon": self._square_outline(),
            "polymer_name": "PA66_Zytel",
            "grid_resolution": 24,
        }
        result = json.loads(_run(run_mold_injection_fill_simulate(params, CTX)))
        assert "error" not in result, f"Tool returned error: {result}"
        caveat = result.get("honest_caveat", "").lower()
        assert "simplified" in caveat or "1.5d" in caveat or "hele-shaw" in caveat.replace("-", "")

    def test_all_polymer_presets_work(self):
        """All three polymer presets should return a fill_time_s field."""
        from kerf_mold.injection_fill_tools import run_mold_injection_fill_simulate
        for polymer in ["ABS_Cycolac_T", "PC_Makrolon_2407", "PA66_Zytel"]:
            params = {
                "part_thickness_mm": 3.0,
                "gate_locations": [[50, 50]],
                "cavity_outline_polygon": self._square_outline(),
                "polymer_name": polymer,
                "grid_resolution": 24,
            }
            result = json.loads(_run(run_mold_injection_fill_simulate(params, CTX)))
            assert "error" not in result, f"Failed for polymer {polymer}: {result}"
            assert "fill_time_s" in result, f"No fill_time_s for polymer {polymer}: {result}"


# ---------------------------------------------------------------------------
# 11: mold_cross_wlf_viscosity round-trip
# ---------------------------------------------------------------------------

class TestCrossWLFTool:
    def test_abs_shear_thinning(self):
        """ABS at high shear rate must return lower viscosity than at low shear rate."""
        from kerf_mold.injection_fill_tools import run_mold_cross_wlf_viscosity
        low  = json.loads(_run(run_mold_cross_wlf_viscosity(
            {"shear_rate_1_s": 1.0, "temperature_c": 230.0, "polymer_name": "ABS_Cycolac_T"}, CTX
        )))
        high = json.loads(_run(run_mold_cross_wlf_viscosity(
            {"shear_rate_1_s": 1000.0, "temperature_c": 230.0, "polymer_name": "ABS_Cycolac_T"}, CTX
        )))
        assert "error" not in low, f"Low-shear call failed: {low}"
        assert "error" not in high, f"High-shear call failed: {high}"
        assert "viscosity_pa_s" in low
        assert "viscosity_pa_s" in high
        # Shear-thinning: viscosity decreases with shear rate
        assert high["viscosity_pa_s"] < low["viscosity_pa_s"]

    def test_unknown_polymer_returns_error(self):
        """Unknown polymer returns an error payload (has 'error' key)."""
        from kerf_mold.injection_fill_tools import run_mold_cross_wlf_viscosity
        result = json.loads(_run(run_mold_cross_wlf_viscosity(
            {"shear_rate_1_s": 100.0, "temperature_c": 230.0, "polymer_name": "GHOST"}, CTX
        )))
        assert "error" in result

    def test_viscosity_positive_finite(self):
        """Tool must return a positive finite viscosity."""
        from kerf_mold.injection_fill_tools import run_mold_cross_wlf_viscosity
        result = json.loads(_run(run_mold_cross_wlf_viscosity(
            {"shear_rate_1_s": 100.0, "temperature_c": 285.0, "polymer_name": "PA66_Zytel"}, CTX
        )))
        assert "error" not in result, f"Tool returned error: {result}"
        assert "viscosity_pa_s" in result
        eta = result["viscosity_pa_s"]
        assert eta > 0.0
        assert math.isfinite(eta)


# ---------------------------------------------------------------------------
# 12: mold_detect_parting_line tool round-trip (unit cube B-rep)
# ---------------------------------------------------------------------------

class TestDetectPartingLineTool:
    def _wedge_body(self):
        """Wedge B-rep with faces straddling the parting plane for Z-pull.

        Faces:
          F_up:   normal = (0, 0.707, 0.707)  → dot(N, Z) = 0.707 > 0
          F_down: normal = (0, 0.707, -0.707) → dot(N, Z) = -0.707 < 0
        Edge E0 between F_up and F_down is a silhouette edge for Z-pull.
        """
        import math
        s = round(math.sqrt(2) / 2, 6)
        return {
            "vertices": [
                [0, 0, 0], [1, 0, 0], [0.5, 0, 0.5],
                [0, 1, 0], [1, 1, 0], [0.5, 1, 0.5],
            ],
            "faces": [
                {"id": "F_up",   "normal": [0,  s,  s], "vertices": [2, 5, 4, 1]},
                {"id": "F_down", "normal": [0,  s, -s], "vertices": [0, 1, 4, 3]},
                {"id": "F_left", "normal": [-1, 0, 0],  "vertices": [0, 2, 5, 3]},
            ],
            "edges": [
                # E0 shared by F_up and F_down — straddles the parting plane → silhouette
                {"id": "E0", "face_ids": ["F_up", "F_down"],
                 "p_start": [0, 0, 0], "p_end": [0, 1, 0]},
                # Other boundary edges (single-face or non-silhouette)
                {"id": "E1", "face_ids": ["F_up", "F_left"],
                 "p_start": [0, 0, 0], "p_end": [0.5, 0, 0.5]},
                {"id": "E2", "face_ids": ["F_down", "F_left"],
                 "p_start": [0, 0, 0], "p_end": [0, 1, 0]},
            ],
        }

    def test_detects_silhouette_edges(self):
        """Z-pull on a wedge body with faces straddling parting plane → silhouette edges detected."""
        from kerf_mold.parting_cavity_tools import run_mold_detect_parting_line
        args = {
            "body": self._wedge_body(),
            "pull_direction": [0, 0, 1],
            "draft_angle_min_deg": 1.0,
        }
        result = json.loads(_run(run_mold_detect_parting_line(args, CTX)))
        assert result.get("ok") is True
        segs = result.get("segments", [])
        silhouettes = [s for s in segs if s["classification"] == "silhouette"]
        # E0 between F_up (d>0) and F_down (d<0) is a silhouette edge
        assert len(silhouettes) > 0

    def test_total_length_positive(self):
        """total_length_mm should be positive when silhouette edges exist."""
        from kerf_mold.parting_cavity_tools import run_mold_detect_parting_line
        args = {
            "body": self._wedge_body(),
            "pull_direction": [0, 0, 1],
        }
        result = json.loads(_run(run_mold_detect_parting_line(args, CTX)))
        assert result.get("ok") is True
        assert result["total_length_mm"] > 0.0

    def test_honest_caveat_present(self):
        """Result must include a non-empty honest_caveat."""
        from kerf_mold.parting_cavity_tools import run_mold_detect_parting_line
        args = {"body": self._wedge_body(), "pull_direction": [0, 0, 1]}
        result = json.loads(_run(run_mold_detect_parting_line(args, CTX)))
        assert result.get("ok") is True
        assert len(result.get("honest_caveat", "")) > 30

    def test_missing_body_returns_error(self):
        """Missing 'body' argument must return an error payload (has 'error' key)."""
        from kerf_mold.parting_cavity_tools import run_mold_detect_parting_line
        result = json.loads(_run(run_mold_detect_parting_line({"pull_direction": [0, 0, 1]}, CTX)))
        assert "error" in result


# ---------------------------------------------------------------------------
# 13: mold_split_cavity_core tool round-trip
# ---------------------------------------------------------------------------

class TestSplitCavityCoreTool:
    def test_split_returns_ok(self):
        """Split on a cube body with a simple parting-line report returns split result."""
        from kerf_mold.parting_cavity_tools import run_mold_split_cavity_core
        body = {
            "vertices": [[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]],
            "faces": [
                {"id": "F_top",   "normal": [0, 0,  1], "vertices": [4, 5, 6, 7]},
                {"id": "F_front", "normal": [0, -1, 0], "vertices": [0, 1, 5, 4]},
            ],
            "edges": [],
        }
        pl_report = {
            "segments": [
                {"edge_id": "E0", "p_start": [0, 0, 0.5], "p_end": [1, 0, 0.5], "classification": "silhouette"},
                {"edge_id": "E1", "p_start": [1, 0, 0.5], "p_end": [1, 1, 0.5], "classification": "silhouette"},
                {"edge_id": "E2", "p_start": [1, 1, 0.5], "p_end": [0, 1, 0.5], "classification": "silhouette"},
                {"edge_id": "E3", "p_start": [0, 1, 0.5], "p_end": [0, 0, 0.5], "classification": "silhouette"},
            ],
            "total_length_mm": 4.0,
            "closed_loops": 1,
            "has_undercuts": False,
            "undercut_face_ids": [],
            "draft_deficient_face_ids": [],
        }
        args = {
            "body": body,
            "parting_line_report": pl_report,
            "pull_direction": [0, 0, 1],
        }
        result = json.loads(_run(run_mold_split_cavity_core(args, CTX)))
        assert result.get("ok") is True
        assert "parting_surface" in result, f"Missing parting_surface in: {result}"
        assert "cavity_body" in result
        assert "core_body" in result


# ---------------------------------------------------------------------------
# 14: mold_compute_warpage_index tool round-trip
# ---------------------------------------------------------------------------

class TestWarpageIndexTool:
    def test_low_risk_scenario(self):
        """Perfect conditions → index < 25, risk_level = 'low'."""
        from kerf_mold.warpage_index_tool import run_mold_compute_warpage_index
        args = {
            "wall_thickness_uniformity_pct": 100.0,
            "gate_location": "centered",
            "polymer_grade": "PC",
            "post_eject_cooling_time_s": 120.0,
            "mold_temp_C": 80.0,
        }
        result = json.loads(_run(run_mold_compute_warpage_index(args, CTX)))
        assert result.get("ok") is True or "warpage_index" in result
        idx = result.get("warpage_index") or result.get("result", {}).get("warpage_index")
        assert idx is not None
        assert idx < 25.0

    def test_high_risk_scenario(self):
        """Worst-case conditions → index > 70."""
        from kerf_mold.warpage_index_tool import run_mold_compute_warpage_index
        args = {
            "wall_thickness_uniformity_pct": 50.0,
            "gate_location": "corner",
            "polymer_grade": "GF-PA66",
            "post_eject_cooling_time_s": 2.0,
            "mold_temp_C": 150.0,
        }
        result = json.loads(_run(run_mold_compute_warpage_index(args, CTX)))
        assert result.get("ok") is True or "warpage_index" in result
        idx = result.get("warpage_index") or result.get("result", {}).get("warpage_index")
        assert idx is not None
        assert idx > 70.0

    def test_missing_gate_location_returns_error(self):
        """Missing gate_location must return an error payload."""
        from kerf_mold.warpage_index_tool import run_mold_compute_warpage_index
        args = {
            "wall_thickness_uniformity_pct": 80.0,
            "polymer_grade": "ABS",
            "post_eject_cooling_time_s": 30.0,
            "mold_temp_C": 60.0,
        }
        result = json.loads(_run(run_mold_compute_warpage_index(args, CTX)))
        assert result.get("ok") is not True


# ---------------------------------------------------------------------------
# 15: mold_check_runner_balance tool round-trip
# ---------------------------------------------------------------------------

class TestRunnerBalanceParity:
    def _balanced_segs(self):
        return [
            {"id": "sprue",   "length_mm": 30, "diameter_mm": 6, "parent_id": None},
            {"id": "R_left",  "length_mm": 40, "diameter_mm": 6, "parent_id": "sprue"},
            {"id": "R_right", "length_mm": 40, "diameter_mm": 6, "parent_id": "sprue"},
            {"id": "R_L1",    "length_mm": 25, "diameter_mm": 6, "parent_id": "R_left"},
            {"id": "R_L2",    "length_mm": 25, "diameter_mm": 6, "parent_id": "R_left"},
            {"id": "R_R1",    "length_mm": 25, "diameter_mm": 6, "parent_id": "R_right"},
            {"id": "R_R2",    "length_mm": 25, "diameter_mm": 6, "parent_id": "R_right"},
        ]

    def test_balanced_h4_ok(self):
        """H-pattern 4-cavity runner returns balanced=True."""
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        args = {
            "segments": self._balanced_segs(),
            "cavity_gate_ids": ["R_L1", "R_L2", "R_R1", "R_R2"],
        }
        result = json.loads(_run(run_mold_check_runner_balance(args, CTX)))
        assert result.get("ok") is True
        assert result["balanced"] is True
        assert result["max_imbalance_pct"] < 1.0

    def test_unbalanced_runner_flagged(self):
        """Asymmetric runner (2× leg) returns balanced=False."""
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        args = {
            "segments": [
                {"id": "sprue",   "length_mm": 10,  "diameter_mm": 8, "parent_id": None},
                {"id": "G_short", "length_mm": 50,  "diameter_mm": 6, "parent_id": "sprue"},
                {"id": "G_long",  "length_mm": 100, "diameter_mm": 6, "parent_id": "sprue"},
            ],
            "cavity_gate_ids": ["G_short", "G_long"],
        }
        result = json.loads(_run(run_mold_check_runner_balance(args, CTX)))
        assert result.get("ok") is True
        assert result["balanced"] is False
        assert result["max_imbalance_pct"] > 30.0

    def test_reference_citation_present(self):
        """Beaumont reference must appear in the response."""
        from kerf_mold.runner_balance_check_tool import run_mold_check_runner_balance
        args = {
            "segments": self._balanced_segs(),
            "cavity_gate_ids": ["R_L1", "R_L2", "R_R1", "R_R2"],
        }
        result = json.loads(_run(run_mold_check_runner_balance(args, CTX)))
        assert "Beaumont" in result.get("reference", "")
