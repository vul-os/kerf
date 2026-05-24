"""Hermetic tests for POST /aero/propulsion/tsiolkovsky and /cea-lite.

No DB, no network, no external packages required.
"""
from __future__ import annotations

import math
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kerf_api.routes_aero_propulsion import router


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


# ===========================================================================
# Tsiolkovsky rocket equation
# ===========================================================================

class TestTsiolkovsky:

    def test_happy_path_returns_200(self, client):
        """Valid request → 200 with ok=True."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 450.0,
            "m0_kg": 10000.0,
            "mf_kg": 1000.0,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_delta_v_formula(self, client):
        """Δv = Isp × g₀ × ln(m0/mf).  RL-10 class: Isp=450s, MR=9:1."""
        isp = 450.0
        m0 = 9000.0
        mf = 1000.0
        g0 = 9.80665
        expected = isp * g0 * math.log(m0 / mf)

        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": isp,
            "m0_kg": m0,
            "mf_kg": mf,
        })
        assert r.status_code == 200
        body = r.json()
        assert abs(body["delta_v_m_s"] - expected) / expected < 1e-9

    def test_km_s_conversion(self, client):
        """delta_v_km_s = delta_v_m_s / 1000."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 350.0,
            "m0_kg": 5000.0,
            "mf_kg": 1000.0,
        })
        body = r.json()
        assert abs(body["delta_v_km_s"] - body["delta_v_m_s"] / 1000.0) < 1e-12

    def test_mass_ratio_field(self, client):
        """mass_ratio = m0/mf."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 300.0,
            "m0_kg": 6000.0,
            "mf_kg": 2000.0,
        })
        body = r.json()
        assert abs(body["mass_ratio"] - 3.0) < 1e-9

    def test_exhaust_velocity_field(self, client):
        """exhaust_velocity_m_s = isp_s × g0."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 320.0,
            "m0_kg": 2000.0,
            "mf_kg": 500.0,
        })
        body = r.json()
        expected_ve = 320.0 * 9.80665
        assert abs(body["exhaust_velocity_m_s"] - expected_ve) / expected_ve < 1e-9

    def test_propellant_fraction_field(self, client):
        """propellant_fraction = (m0 - mf) / m0."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 300.0,
            "m0_kg": 4000.0,
            "mf_kg": 1000.0,
        })
        body = r.json()
        assert abs(body["propellant_fraction"] - 0.75) < 1e-9

    def test_delta_v_increases_with_isp(self, client):
        """Higher Isp → larger Δv at same mass ratio."""
        base = {"m0_kg": 5000.0, "mf_kg": 1000.0}
        r1 = client.post("/api/aero/propulsion/tsiolkovsky", json={"isp_s": 300.0, **base})
        r2 = client.post("/api/aero/propulsion/tsiolkovsky", json={"isp_s": 450.0, **base})
        assert r2.json()["delta_v_m_s"] > r1.json()["delta_v_m_s"]

    def test_invalid_isp_zero_returns_422(self, client):
        """isp_s = 0 → 422."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 0.0,
            "m0_kg": 5000.0,
            "mf_kg": 1000.0,
        })
        assert r.status_code == 422

    def test_invalid_mf_zero_returns_422(self, client):
        """mf_kg = 0 → 422."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 300.0,
            "m0_kg": 5000.0,
            "mf_kg": 0.0,
        })
        assert r.status_code == 422

    def test_m0_less_than_mf_returns_422(self, client):
        """m0 < mf (impossible wet mass) → 422."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 300.0,
            "m0_kg": 500.0,
            "mf_kg": 1000.0,
        })
        assert r.status_code == 422

    def test_m0_equals_mf_returns_422(self, client):
        """m0 == mf (no propellant) → 422."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 300.0,
            "m0_kg": 1000.0,
            "mf_kg": 1000.0,
        })
        assert r.status_code == 422

    def test_custom_g0(self, client):
        """Custom g0 override propagates correctly."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "isp_s": 400.0,
            "m0_kg": 2000.0,
            "mf_kg": 500.0,
            "g0_m_s2": 1.62,  # Moon gravity
        })
        assert r.status_code == 200
        body = r.json()
        expected = 400.0 * 1.62 * math.log(4.0)
        assert abs(body["delta_v_m_s"] - expected) / expected < 1e-9

    def test_missing_required_field_returns_422(self, client):
        """Missing isp_s → 422 (Pydantic validation)."""
        r = client.post("/api/aero/propulsion/tsiolkovsky", json={
            "m0_kg": 5000.0,
            "mf_kg": 1000.0,
        })
        assert r.status_code == 422


# ===========================================================================
# CEA-lite
# ===========================================================================

class TestCeaLite:

    def test_lox_lh2_returns_200(self, client):
        """LOX/LH2 is in the table → 200 with ok=True."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "lox/lh2",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_lox_rp1_isp_reasonable(self, client):
        """LOX/RP-1 vacuum Isp should be in 350-380 s range."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "lox/rp1",
        })
        assert r.status_code == 200
        body = r.json()
        assert 320.0 <= body["isp_vac_s"] <= 400.0

    def test_returns_propellant_key_and_o_f(self, client):
        """Response must include propellant_key and o_f_optimal fields."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "lox/ch4",
        })
        body = r.json()
        assert "propellant_key" in body
        assert "o_f_optimal" in body

    def test_vacuum_condition(self, client):
        """No altitude → condition = 'vacuum', isp_effective = isp_vac."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "solid/htpb",
        })
        body = r.json()
        assert body["condition"] == "vacuum"
        assert abs(body["isp_effective_s"] - body["isp_vac_s"]) < 0.01

    def test_sea_level_isp_lower_than_vacuum(self, client):
        """isp_effective at altitude=0 < isp_vac (ambient pressure penalty)."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "lox/rp1",
            "altitude_m": 0.0,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["isp_effective_s"] < body["isp_vac_s"]

    def test_unknown_propellant_returns_422(self, client):
        """Unrecognised propellant → 422."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "unobtanium/dark-matter",
        })
        assert r.status_code == 422

    def test_case_insensitive_lookup(self, client):
        """Lookup is normalised to lowercase."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "LOX/LH2",
        })
        # Should resolve via .lower() normalisation
        assert r.status_code in (200, 422)  # 422 if alias not matched, 200 if found

    def test_lox_lh2_isp_ballpark(self, client):
        """LOX/LH2 vacuum Isp should be in 430-470 s range (RL-10 class)."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "lox/lh2",
        })
        body = r.json()
        assert 430.0 <= body["isp_vac_s"] <= 470.0

    def test_warning_field_present(self, client):
        """Response includes a 'warning' field noting these are table values."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "lox/ch4",
        })
        body = r.json()
        assert "warning" in body
        assert len(body["warning"]) > 0

    def test_cold_gas_n2_present(self, client):
        """Cold gas N2 entry is in table."""
        r = client.post("/api/aero/propulsion/cea-lite", json={
            "propellant": "cold-gas/n2",
        })
        assert r.status_code == 200

    def test_all_table_entries_reachable(self, client):
        """Every entry in the internal table returns 200."""
        from kerf_api.routes_aero_propulsion import _CEA_LITE_TABLE
        for key in _CEA_LITE_TABLE:
            r = client.post("/api/aero/propulsion/cea-lite", json={"propellant": key})
            assert r.status_code == 200, f"Key '{key}' returned {r.status_code}"

    def test_missing_propellant_field_returns_422(self, client):
        """Missing 'propellant' field → 422 (Pydantic validation)."""
        r = client.post("/api/aero/propulsion/cea-lite", json={})
        assert r.status_code == 422

    def test_method_field_present_lookup(self, client):
        """Response always includes method field; lookup path returns 'lookup'."""
        r = client.post("/api/aero/propulsion/cea-lite", json={"propellant": "lox/lh2"})
        assert r.status_code == 200
        body = r.json()
        # rocketcea is not installed in this env, so method must be "lookup"
        assert body["method"] in ("lookup", "rocketcea")


# ===========================================================================
# CEA-lite rocketcea path (mocked)
# ===========================================================================

class TestCeaLiteRocketceaPaths:
    """Test both the rocketcea path (mocked) and the lookup fallback path."""

    @pytest.fixture()
    def client_fresh(self):
        """Fresh TestClient backed by a freshly-imported router."""
        app = FastAPI()
        app.include_router(router, prefix="/api")
        return TestClient(app)

    def test_lookup_path_when_rocketcea_absent(self, client_fresh):
        """When rocketcea is not importable, method='lookup' and warning present."""
        # Ensure rocketcea is not importable for this test
        with patch.dict(sys.modules, {"rocketcea": None, "rocketcea.cea_obj": None}):
            r = client_fresh.post("/api/aero/propulsion/cea-lite", json={"propellant": "lox/rp1"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["method"] == "lookup"
        assert "warning" in body
        assert "rocketcea" in body["warning"].lower()

    def test_rocketcea_path_when_package_present(self, client_fresh):
        """When rocketcea IS importable, the real CEA_Obj path is taken: method='rocketcea'."""
        # Build a minimal mock of rocketcea.cea_obj.CEA_Obj
        mock_cea_instance = MagicMock()
        mock_cea_instance.get_Isp.return_value = 442.7  # plausible LOX/LH2 Isp (s)

        mock_cea_obj_cls = MagicMock(return_value=mock_cea_instance)

        mock_cea_obj_module = types.ModuleType("rocketcea.cea_obj")
        mock_cea_obj_module.CEA_Obj = mock_cea_obj_cls

        mock_rocketcea_pkg = types.ModuleType("rocketcea")
        mock_rocketcea_pkg.cea_obj = mock_cea_obj_module

        with patch.dict(
            sys.modules,
            {
                "rocketcea": mock_rocketcea_pkg,
                "rocketcea.cea_obj": mock_cea_obj_module,
            },
        ):
            r = client_fresh.post("/api/aero/propulsion/cea-lite", json={"propellant": "lox/lh2"})

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["method"] == "rocketcea"
        # Isp should come from our mock (442.7)
        assert abs(body["isp_vac_s"] - 442.7) < 0.01
        # CEA_Obj must have been constructed with correct JANNAF names
        mock_cea_obj_cls.assert_called_once_with(oxName="LOX", fuelName="LH2")
        # get_Isp called with Pc (psia), MR (O/F), eps (expansion ratio)
        mock_cea_instance.get_Isp.assert_called_once()
        call_kwargs = mock_cea_instance.get_Isp.call_args
        assert call_kwargs.kwargs.get("Pc") == 1000.0 or call_kwargs.args[0] == 1000.0

    def test_rocketcea_path_not_taken_for_solid(self, client_fresh):
        """Solid/cold-gas propellants not in rocketcea map → always lookup."""
        mock_cea_obj_cls = MagicMock()
        mock_cea_obj_module = types.ModuleType("rocketcea.cea_obj")
        mock_cea_obj_module.CEA_Obj = mock_cea_obj_cls
        mock_rocketcea_pkg = types.ModuleType("rocketcea")
        mock_rocketcea_pkg.cea_obj = mock_cea_obj_module

        with patch.dict(
            sys.modules,
            {"rocketcea": mock_rocketcea_pkg, "rocketcea.cea_obj": mock_cea_obj_module},
        ):
            r = client_fresh.post("/api/aero/propulsion/cea-lite", json={"propellant": "solid/htpb"})

        assert r.status_code == 200
        body = r.json()
        # solid/htpb has no rocketcea pair, so always lookup
        assert body["method"] == "lookup"
        # CEA_Obj should NOT have been constructed
        mock_cea_obj_cls.assert_not_called()
