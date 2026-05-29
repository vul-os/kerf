"""Tests for Wave 4D manufacturing-UI composites routes.

Covers:
  POST /api/composites/clt       — LaminateStackup (layup_analysis envelope)
  POST /api/composites/afp       — AFPToolpathView
  POST /api/composites/fiber_map — FiberOrientationContour

No DB, no network.  kerf_composites must be available (conftest handles sys.path).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kerf_api.routes_composites_mfg import router
from kerf_core.dependencies import require_auth


# ---------------------------------------------------------------------------
# Test client — mount without auth (override require_auth dependency)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}
    return TestClient(app)


# ---------------------------------------------------------------------------
# Shared ply definition — T300/5208 CFRP, units in GPa / mm
# ---------------------------------------------------------------------------

PLY = {
    "angle": 0.0,
    "E1": 181.0,
    "E2": 10.3,
    "G12": 7.17,
    "nu12": 0.28,
    "thickness": 0.125,  # mm
}

def _ply(angle):
    return {**PLY, "angle": angle}


# ===========================================================================
# POST /api/composites/clt
# ===========================================================================

class TestCLTMfg:

    def test_round_trip_200(self, client):
        """Single-ply layup_analysis envelope → 200 + ok=True."""
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": [PLY], "name": "test"},
        })
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True

    def test_abd_matrices_present(self, client):
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": [PLY]},
        })
        body = r.json()
        for key in ("A_matrix_N_per_mm", "B_matrix_N", "D_matrix_N_mm"):
            assert key in body, f"Missing: {key}"

    def test_a_matrix_is_3x3(self, client):
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": [PLY]},
        })
        A = r.json()["A_matrix_N_per_mm"]
        assert len(A) == 3
        for row in A:
            assert len(row) == 3

    def test_total_thickness_correct(self, client):
        plies = [_ply(0), _ply(90), _ply(0)]
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": plies},
        })
        body = r.json()
        assert abs(body["total_thickness_mm"] - 0.375) < 1e-6

    def test_num_plies_correct(self, client):
        plies = [_ply(a) for a in [0, 45, -45, 90]]
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": plies},
        })
        assert r.json()["num_plies"] == 4

    def test_symmetric_flag_is_bool(self, client):
        """is_symmetric is returned as a boolean."""
        plies = [_ply(0), _ply(90), _ply(90), _ply(0)]
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": plies},
        })
        assert isinstance(r.json()["is_symmetric"], bool)

    def test_effective_moduli_present(self, client):
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": [PLY]},
        })
        moduli = r.json().get("effective_moduli")
        assert moduli is not None
        assert isinstance(moduli, dict)

    def test_empty_plies_returns_422(self, client):
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": []},
        })
        assert r.status_code == 422

    def test_missing_args_returns_422(self, client):
        r = client.post("/api/composites/clt", json={"tool": "layup_analysis"})
        assert r.status_code == 422

    def test_weight_field_present(self, client):
        r = client.post("/api/composites/clt", json={
            "tool": "layup_analysis",
            "args": {"plies": [PLY]},
        })
        assert "weight_g_per_m2" in r.json()


# ===========================================================================
# POST /api/composites/afp
# ===========================================================================

AFP_PARAMS = {
    "courseWidth": 6.35,
    "minRadius": 600,
    "towCount": 8,
    "angle": 0,
    "rampRate": 2,
    "dwellTemp": 180,
    "dwellTime": 60,
    "coolRate": 3,
}


class TestAFPMfg:

    def test_round_trip_200(self, client):
        r = client.post("/api/composites/afp", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_courses_present(self, client):
        r = client.post("/api/composites/afp", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        body = r.json()
        assert "courses" in body
        assert isinstance(body["courses"], list)

    def test_num_courses_matches_list(self, client):
        r = client.post("/api/composites/afp", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        body = r.json()
        assert body["num_courses"] == len(body["courses"])

    def test_course_shape(self, client):
        """Each course has expected keys."""
        r = client.post("/api/composites/afp", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        courses = r.json()["courses"]
        assert len(courses) > 0
        for c in courses:
            for key in ("course_id", "angle_deg", "start_x", "start_y",
                        "end_x", "end_y", "tow_width_mm", "length_mm"):
                assert key in c, f"Missing key in course: {key}"

    def test_cure_cycle_present(self, client):
        r = client.post("/api/composites/afp", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        body = r.json()
        cc = body.get("cure_cycle")
        assert cc is not None
        for key in ("dwell_temp_C", "dwell_time_min", "total_time_min"):
            assert key in cc

    def test_cure_cycle_total_time(self, client):
        """total_time_min = ramp + dwell + cool."""
        r = client.post("/api/composites/afp", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        cc = r.json()["cure_cycle"]
        # ramp = (180-25)/2 = 77.5, dwell = 60, cool = (180-25)/3 ≈ 51.67 → 189.2
        assert cc["total_time_min"] > 100

    def test_angle_45_returns_courses(self, client):
        params = {**AFP_PARAMS, "angle": 45}
        r = client.post("/api/composites/afp", json={
            "tool": "composites_afp_pathplan",
            "args": params,
        })
        assert r.status_code == 200
        assert r.json()["num_courses"] > 0

    def test_missing_args_returns_422(self, client):
        r = client.post("/api/composites/afp", json={"tool": "composites_afp_pathplan"})
        assert r.status_code == 422


# ===========================================================================
# POST /api/composites/afp?format=gcode
# ===========================================================================

class TestAFPExportGcode:

    def test_gcode_format_returns_200(self, client):
        """?format=gcode returns 200 with text/plain content."""
        r = client.post("/api/composites/afp?format=gcode", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("content-type", "")

    def test_gcode_content_is_string(self, client):
        """G-code response is a non-empty string."""
        r = client.post("/api/composites/afp?format=gcode", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert len(r.text) > 0

    def test_gcode_has_m200_fibre_start(self, client):
        """G-code contains M200 (fibre start) commands."""
        r = client.post("/api/composites/afp?format=gcode", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert "M200" in r.text

    def test_gcode_has_m201_fibre_stop(self, client):
        """G-code contains M201 (fibre stop) commands."""
        r = client.post("/api/composites/afp?format=gcode", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert "M201" in r.text

    def test_gcode_has_m202_tape_cut(self, client):
        """G-code contains M202 (tape cut) commands."""
        r = client.post("/api/composites/afp?format=gcode", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert "M202" in r.text

    def test_gcode_content_disposition(self, client):
        """Content-Disposition attachment header present."""
        r = client.post("/api/composites/afp?format=gcode", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".gcode" in cd

    def test_gcode_goto_lines_present(self, client):
        """G-code contains GOTO-type G00/G01 lines."""
        r = client.post("/api/composites/afp?format=gcode", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        lines = r.text.splitlines()
        g_lines = [l for l in lines if l.strip().startswith(("G00", "G01"))]
        assert len(g_lines) > 0

    def test_gcode_m30_program_end(self, client):
        """G-code ends with M30."""
        r = client.post("/api/composites/afp?format=gcode", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert "M30" in r.text


# ===========================================================================
# POST /api/composites/afp?format=apt
# ===========================================================================

class TestAFPExportAPT:

    def test_apt_format_returns_200(self, client):
        r = client.post("/api/composites/afp?format=apt", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("content-type", "")

    def test_apt_content_disposition(self, client):
        r = client.post("/api/composites/afp?format=apt", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".apt" in cd

    def test_apt_partno_header(self, client):
        r = client.post("/api/composites/afp?format=apt", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert "PARTNO" in r.text

    def test_apt_goto_lines_present(self, client):
        r = client.post("/api/composites/afp?format=apt", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        goto_lines = [l for l in r.text.splitlines() if l.strip().startswith("GOTO/")]
        assert len(goto_lines) > 0

    def test_apt_fedrat_present(self, client):
        r = client.post("/api/composites/afp?format=apt", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert "FEDRAT" in r.text

    def test_apt_end_statement(self, client):
        r = client.post("/api/composites/afp?format=apt", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert r.text.strip().endswith("END")

    def test_apt_auxfun_200_present(self, client):
        """AUXFUN/200 (fibre start) in APT output."""
        r = client.post("/api/composites/afp?format=apt", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert "AUXFUN/200" in r.text

    def test_apt_auxfun_202_present(self, client):
        """AUXFUN/202 (tape cut) in APT output."""
        r = client.post("/api/composites/afp?format=apt", json={
            "tool": "composites_afp_pathplan",
            "args": AFP_PARAMS,
        })
        assert "AUXFUN/202" in r.text


# ===========================================================================
# POST /api/composites/fiber_map
# ===========================================================================

DRAPE_PARAMS = {
    "surface": "flat",
    "u_range": [0, 100],
    "v_range": [0, 100],
    "nu": 10,
    "nv": 10,
    "radius": 150,
}


class TestFiberMapMfg:

    def test_round_trip_200(self, client):
        r = client.post("/api/composites/fiber_map", json={
            "tool": "composites_drape",
            "args": DRAPE_PARAMS,
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_shear_angle_stats_present(self, client):
        r = client.post("/api/composites/fiber_map", json={
            "tool": "composites_drape",
            "args": DRAPE_PARAMS,
        })
        body = r.json()
        shear = body.get("shear_angle_deg")
        assert shear is not None
        for key in ("mean", "max", "min"):
            assert key in shear

    def test_fiber_angles_array_length(self, client):
        """fiber_angles has nu×nv elements."""
        r = client.post("/api/composites/fiber_map", json={
            "tool": "composites_drape",
            "args": DRAPE_PARAMS,
        })
        body = r.json()
        assert "fiber_angles" in body
        assert len(body["fiber_angles"]) == DRAPE_PARAMS["nu"] * DRAPE_PARAMS["nv"]

    def test_corner_coords_present(self, client):
        r = client.post("/api/composites/fiber_map", json={
            "tool": "composites_drape",
            "args": DRAPE_PARAMS,
        })
        body = r.json()
        corners = body.get("corner_coords_mm")
        assert corners is not None
        assert len(corners) == 3
        for corner in corners:
            assert len(corner) == 3  # x, y, z

    def test_cylinder_x_surface(self, client):
        params = {**DRAPE_PARAMS, "surface": "cylinder_x"}
        r = client.post("/api/composites/fiber_map", json={
            "tool": "composites_drape",
            "args": params,
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_cylinder_y_surface(self, client):
        params = {**DRAPE_PARAMS, "surface": "cylinder_y"}
        r = client.post("/api/composites/fiber_map", json={
            "tool": "composites_drape",
            "args": params,
        })
        assert r.status_code == 200

    def test_invalid_surface_returns_422(self, client):
        params = {**DRAPE_PARAMS, "surface": "sphere"}
        r = client.post("/api/composites/fiber_map", json={
            "tool": "composites_drape",
            "args": params,
        })
        assert r.status_code == 422

    def test_missing_args_returns_422(self, client):
        r = client.post("/api/composites/fiber_map", json={"tool": "composites_drape"})
        assert r.status_code == 422
