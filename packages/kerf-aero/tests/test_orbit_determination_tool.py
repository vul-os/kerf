"""
Dispatch tests for aero_orbit_determination LLM tool function.

Calls aero_orbit_determination from aerospace_tools and asserts a sane payload.
Uses synthetic observations from the orbit determination library.
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import numpy as np
import pytest

from kerf_aero.llm_tools.aerospace_tools import aero_orbit_determination
from kerf_aero.orbital.kepler import KeplerianElements, elements_to_state, MU_EARTH
from kerf_aero.orbital.orbit_determination import generate_synthetic_observations, geodetic_to_eci


def _leo_state():
    """400 km LEO truth state."""
    elems = KeplerianElements(
        a=6778.0,
        e=0.001,
        i=math.radians(28.5),
        raan=math.radians(45.0),
        argp=math.radians(30.0),
        nu=math.radians(0.0),
    )
    return elements_to_state(elems)


def _make_observations(n: int = 10, noise_km: float = 1e-4):
    """Generate synthetic range + range-rate observations."""
    r0, v0 = _leo_state()
    x_truth = np.concatenate([r0, v0])
    station_eci = geodetic_to_eci(lat_deg=0.0, lon_deg=0.0, alt_km=0.0)
    # Observation epochs spanning ~10 min
    t_obs = [i * 60.0 for i in range(n)]
    obs = generate_synthetic_observations(
        r0_truth=r0,
        v0_truth=v0,
        obs_times=t_obs,
        station_eci=station_eci,
        obs_type="both",
        sigma_range_km=noise_km,
        sigma_rrate_km_per_s=noise_km / 10.0,
    )
    # Convert to dicts for the LLM tool
    return [
        {
            "t": float(o.t),
            "obs_type": o.obs_type,
            "y": o.y.tolist(),
            "sigma": o.sigma.tolist(),
            "station_eci": o.station_eci.tolist(),
        }
        for o in obs
    ], x_truth.tolist()


class TestAeroOrbitDetermination:
    def test_happy_path_returns_ok(self):
        obs_dicts, x_truth = _make_observations(n=8, noise_km=1e-6)
        result = aero_orbit_determination(obs_dicts, x_truth)
        assert result["ok"] is True
        assert isinstance(result["converged"], bool)
        assert len(result["x_estimated"]) == 6
        assert result["n_observations"] == 8

    def test_converges_zero_noise(self):
        obs_dicts, x_truth = _make_observations(n=10, noise_km=1e-8)
        result = aero_orbit_determination(obs_dicts, x_truth, max_iter=15)
        assert result["ok"] is True
        # With tiny noise the estimate should be very close to truth
        x_est = result["x_estimated"]
        pos_err = math.sqrt(sum((x_est[i] - x_truth[i]) ** 2 for i in range(3)))
        assert pos_err < 1.0  # within 1 km

    def test_rms_residual_present(self):
        obs_dicts, x_truth = _make_observations(n=6)
        result = aero_orbit_determination(obs_dicts, x_truth)
        assert "rms_residual" in result
        assert result["rms_residual"] >= 0.0

    def test_covariance_trace_present(self):
        obs_dicts, x_truth = _make_observations(n=8)
        result = aero_orbit_determination(obs_dicts, x_truth)
        assert "covariance_trace" in result

    def test_empty_observations_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            aero_orbit_determination([], [1.0] * 6)

    def test_wrong_state_size_raises(self):
        obs_dicts, _ = _make_observations(n=4)
        with pytest.raises(ValueError, match="length 6"):
            aero_orbit_determination(obs_dicts, [1.0, 2.0, 3.0])

    def test_j2_enabled(self):
        obs_dicts, x_truth = _make_observations(n=6)
        result = aero_orbit_determination(obs_dicts, x_truth, include_j2=True, max_iter=5)
        assert result["ok"] is True
