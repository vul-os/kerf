"""Tests for POST /aero/orbit/propagate.

Run with:
    PYTHONPATH=packages/kerf-core/src:packages/kerf-aero/src:packages/kerf-api/src \\
        python3 -m pytest packages/kerf-api/tests/test_routes_aero_orbit.py -x

These tests are hermetic — no database, no external services.
"""
from __future__ import annotations

import math
import sys
import os
import pathlib

# ---------------------------------------------------------------------------
# Bootstrap: add every packages/<pkg>/src to sys.path so kerf_* imports work
# without pip install -e.
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).parent
_PACKAGES_ROOT = _HERE.parent.parent

for _entry in _PACKAGES_ROOT.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

# ---------------------------------------------------------------------------

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kerf_api.routes_aero_orbit import router

# Minimal test app — no DB lifespan needed; this route is stateless.
app = FastAPI()
app.include_router(router, prefix="/api")

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leo_body(
    altitude_km: float = 400.0,
    e: float = 0.0,
    duration_s: float | None = None,
    n_steps: int = 100,
) -> dict:
    """Build a request body for a circular LEO orbit at altitude_km."""
    R_EARTH = 6_378.137  # km
    a = R_EARTH + altitude_km
    # One full period by default
    if duration_s is None:
        mu = 398_600.4418
        duration_s = 2.0 * math.pi * math.sqrt(a ** 3 / mu)
    return {
        "a": a,
        "e": e,
        "i": math.radians(51.6),   # ISS-like inclination
        "Omega": 0.0,
        "omega": 0.0,
        "nu0": 0.0,
        "duration_s": duration_s,
        "n_steps": n_steps,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPropagateLEO:
    """Basic propagation for a LEO circular orbit."""

    def test_returns_200(self):
        resp = client.post("/api/aero/orbit/propagate", json=_leo_body())
        assert resp.status_code == 200

    def test_ok_flag(self):
        resp = client.post("/api/aero/orbit/propagate", json=_leo_body())
        assert resp.json()["ok"] is True

    def test_trajectory_length_matches_n_steps(self):
        body = _leo_body(n_steps=50)
        resp = client.post("/api/aero/orbit/propagate", json=body)
        data = resp.json()
        assert data["n_steps"] == 50
        assert len(data["trajectory"]) == 50

    def test_trajectory_points_have_xyz(self):
        resp = client.post("/api/aero/orbit/propagate", json=_leo_body(n_steps=10))
        traj = resp.json()["trajectory"]
        for pt in traj:
            assert "x" in pt and "y" in pt and "z" in pt

    def test_leo_radius_approx_correct(self):
        """All trajectory points should be ~6778 km from Earth's centre (±1 km)."""
        altitude = 400.0
        R_EARTH = 6_378.137
        expected_r = R_EARTH + altitude

        resp = client.post("/api/aero/orbit/propagate", json=_leo_body(n_steps=20))
        traj = resp.json()["trajectory"]
        for pt in traj:
            r = math.sqrt(pt["x"] ** 2 + pt["y"] ** 2 + pt["z"] ** 2)
            assert abs(r - expected_r) < 1.0, (
                f"Point radius {r:.3f} km deviates from expected {expected_r:.3f} km"
            )

    def test_duration_echoed(self):
        body = _leo_body(duration_s=5500.0)
        resp = client.post("/api/aero/orbit/propagate", json=body)
        assert resp.json()["duration_s"] == pytest.approx(5500.0)


class TestLEOPeriod:
    """Sanity-check: 400 km LEO period is approximately 92 minutes."""

    def test_leo_period_approx_92_min(self):
        R_EARTH = 6_378.137
        MU = 398_600.4418
        a = R_EARTH + 400.0
        T = 2.0 * math.pi * math.sqrt(a ** 3 / MU)
        # 92 minutes = 5520 s; allow ±60 s tolerance
        assert abs(T - 5520.0) < 60.0, f"Period {T:.1f} s is not ~92 min"

    def test_propagate_one_period_returns_to_start(self):
        """After one full period the satellite should be within ~1 km of start."""
        body = _leo_body(n_steps=500)
        resp = client.post("/api/aero/orbit/propagate", json=body)
        traj = resp.json()["trajectory"]
        start = traj[0]
        end   = traj[-1]
        dist = math.sqrt(
            (end["x"] - start["x"]) ** 2 +
            (end["y"] - start["y"]) ** 2 +
            (end["z"] - start["z"]) ** 2
        )
        assert dist < 1.0, (
            f"Orbit not closed: start-to-end distance = {dist:.4f} km"
        )


class TestEllipticOrbit:
    """Eccentric (elliptic) orbit propagation."""

    def test_elliptic_orbit_variable_radius(self):
        """An e=0.3 orbit should have varying altitude (not constant radius)."""
        body = {
            "a": 8000.0,
            "e": 0.3,
            "i": math.radians(28.5),
            "Omega": 0.0,
            "omega": 0.0,
            "nu0": 0.0,
            "duration_s": 7_000.0,
            "n_steps": 50,
        }
        resp = client.post("/api/aero/orbit/propagate", json=body)
        traj = resp.json()["trajectory"]
        radii = [math.sqrt(p["x"] ** 2 + p["y"] ** 2 + p["z"] ** 2) for p in traj]
        assert max(radii) - min(radii) > 100.0, (
            "Expected varying radius for eccentric orbit"
        )


class TestValidation:
    """Input validation and error responses."""

    def test_negative_sma_returns_422(self):
        body = _leo_body()
        body["a"] = -100.0
        resp = client.post("/api/aero/orbit/propagate", json=body)
        assert resp.status_code == 422

    def test_eccentricity_gte_1_returns_422(self):
        body = _leo_body()
        body["e"] = 1.0
        resp = client.post("/api/aero/orbit/propagate", json=body)
        assert resp.status_code == 422

    def test_negative_duration_returns_422(self):
        body = _leo_body(duration_s=5500.0)
        body["duration_s"] = -1.0
        resp = client.post("/api/aero/orbit/propagate", json=body)
        assert resp.status_code == 422

    def test_n_steps_too_small_returns_422(self):
        body = _leo_body(n_steps=1)
        resp = client.post("/api/aero/orbit/propagate", json=body)
        assert resp.status_code == 422

    def test_missing_sma_returns_422(self):
        body = _leo_body()
        del body["a"]
        resp = client.post("/api/aero/orbit/propagate", json=body)
        assert resp.status_code == 422


class TestKeplerModule:
    """Direct unit tests for kerf_aero.orbital.kepler (no HTTP)."""

    def test_orbital_period_leo_approx(self):
        from kerf_aero.orbital.kepler import orbital_period, R_EARTH_KM
        T = orbital_period(R_EARTH_KM + 400.0)
        # 92 min ± 1 min
        assert 91 * 60 < T < 93 * 60

    def test_propagate_returns_correct_length(self):
        from kerf_aero.orbital.kepler import OrbitalElements, propagate_orbit, R_EARTH_KM
        el = OrbitalElements(
            a=R_EARTH_KM + 400, e=0.0,
            i=math.radians(51.6), raan=0.0, argp=0.0, nu0=0.0,
        )
        pts = propagate_orbit(el, 5500.0, n_steps=100)
        assert len(pts) == 100

    def test_propagate_validates_e_lt_1(self):
        from kerf_aero.orbital.kepler import OrbitalElements, propagate_orbit, R_EARTH_KM
        el = OrbitalElements(a=7000, e=1.0, i=0, raan=0, argp=0, nu0=0)
        with pytest.raises(ValueError):
            propagate_orbit(el, 5000.0, 50)

    def test_propagate_validates_n_steps_gte_2(self):
        from kerf_aero.orbital.kepler import OrbitalElements, propagate_orbit, R_EARTH_KM
        el = OrbitalElements(a=7000, e=0.0, i=0, raan=0, argp=0, nu0=0)
        with pytest.raises(ValueError):
            propagate_orbit(el, 5000.0, n_steps=1)
