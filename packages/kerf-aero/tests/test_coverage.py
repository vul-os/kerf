"""Tests for orbital/coverage.py — ground station contact interval analysis."""

from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_aero.orbital.coverage import (
    GroundStation,
    geodetic_to_ecef,
    gst_from_epoch,
    eci_to_ecef,
    elevation_angle,
    compute_contacts,
    coverage_analysis,
    ContactInterval,
    CoverageResult,
)
from kerf_aero.orbital.kepler import KeplerianElements, MU_EARTH


# ---------------------------------------------------------------------------
# Coordinate utility tests
# ---------------------------------------------------------------------------

class TestGeodeticToECEF:
    """Validate geodetic to ECEF conversion."""

    def test_equator_prime_meridian(self):
        """Equator at prime meridian (0, 0, 0) → ECEF ≈ (R_Earth, 0, 0)."""
        r = geodetic_to_ecef(0.0, 0.0, 0.0)
        assert abs(r[0] - 6378.137) < 1.0
        assert abs(r[1]) < 1.0
        assert abs(r[2]) < 0.1

    def test_north_pole(self):
        """North pole (90, 0, 0) → ECEF ≈ (0, 0, R_polar)."""
        r = geodetic_to_ecef(90.0, 0.0, 0.0)
        assert abs(r[0]) < 1.0
        assert abs(r[1]) < 1.0
        # Polar radius ≈ 6357 km
        assert abs(r[2] - 6357.0) < 5.0

    def test_altitude_increases_radius(self):
        """Higher altitude → larger ECEF magnitude."""
        r0 = geodetic_to_ecef(0.0, 0.0, 0.0)
        r1 = geodetic_to_ecef(0.0, 0.0, 400.0)
        assert np.linalg.norm(r1) > np.linalg.norm(r0)


class TestGSTAndECIToECEF:
    """Validate sidereal time and ECI→ECEF rotation."""

    def test_gst_increases_with_time(self):
        """GST should increase with time (Earth rotates)."""
        gst1 = gst_from_epoch(0.0)
        gst2 = gst_from_epoch(3600.0)  # 1 hour later
        # After 1 hour Earth rotates ~15 deg
        diff = (gst2 - gst1) % (2 * math.pi)
        expected = 7.2921150e-5 * 3600.0  # omega * t
        assert abs(diff - expected) < 1e-6

    def test_eci_ecef_rotation_magnitude(self):
        """ECI→ECEF rotation preserves vector magnitude."""
        r_eci = np.array([7000.0, 1000.0, 500.0])
        r_ecef = eci_to_ecef(r_eci, 0.0)
        np.testing.assert_allclose(
            np.linalg.norm(r_eci),
            np.linalg.norm(r_ecef),
            atol=1e-9,
        )


class TestElevationAngle:
    """Validate elevation angle calculation."""

    def test_satellite_directly_overhead(self):
        """Satellite directly above station → elevation ≈ 90°."""
        # Station at equator, prime meridian
        r_station = geodetic_to_ecef(0.0, 0.0, 0.0)
        # Satellite at 400 km directly above station (same lat/lon, higher alt)
        r_sat = geodetic_to_ecef(0.0, 0.0, 400.0)
        el = elevation_angle(r_station, r_sat, lat_deg=0.0, lon_deg=0.0)
        assert el > 80.0, f"Elevation should be near 90°; got {el:.1f}°"

    def test_satellite_below_horizon(self):
        """Satellite below horizon should have negative elevation."""
        r_station = geodetic_to_ecef(0.0, 0.0, 0.0)
        # Satellite at antipode (directly opposite side of Earth)
        r_sat = geodetic_to_ecef(0.0, 180.0, 0.0)
        el = elevation_angle(r_station, r_sat, lat_deg=0.0, lon_deg=0.0)
        assert el < 0.0, f"Antipodal satellite should be below horizon; got {el:.1f}°"


# ---------------------------------------------------------------------------
# Contact interval tests
# ---------------------------------------------------------------------------

class TestComputeContacts:
    """Validate contact interval detection for LEO satellite."""

    # ISS-like orbit: a=6778 km, i=51.6°
    ISS_ELEMENTS = KeplerianElements(
        a=6778.0,
        e=0.001,
        i=math.radians(51.6),
        raan=0.0,
        argp=0.0,
        nu=0.0,
    )

    # Test station: near equator, reasonable elevation mask
    STATION = GroundStation(
        name="test_eq",
        latitude_deg=0.0,
        longitude_deg=0.0,
        altitude_km=0.0,
        min_elevation_deg=5.0,
    )

    def test_contacts_over_24h(self):
        """ISS-like satellite should have multiple contacts over 24h from equatorial station."""
        analysis_s = 24 * 3600.0   # 24 hours
        contacts = compute_contacts(
            self.ISS_ELEMENTS,
            self.STATION,
            analysis_s,
            time_step_s=60.0,
        )
        # ISS passes about 5-6 times per 24h over equatorial station
        assert len(contacts) >= 2, (
            f"Expected ≥ 2 contacts in 24h; got {len(contacts)}"
        )

    def test_contact_durations_positive(self):
        """All contact durations should be positive."""
        contacts = compute_contacts(
            self.ISS_ELEMENTS,
            self.STATION,
            6 * 3600.0,
            time_step_s=60.0,
        )
        for c in contacts:
            assert c.duration_s > 0
            assert c.set_time_s > c.rise_time_s

    def test_contact_max_elevation_positive(self):
        """Max elevation during contact should be above min elevation."""
        contacts = compute_contacts(
            self.ISS_ELEMENTS,
            self.STATION,
            6 * 3600.0,
            time_step_s=60.0,
        )
        for c in contacts:
            assert c.max_elevation_deg >= self.STATION.min_elevation_deg - 1.0


class TestCoverageAnalysis:
    """Validate multi-station coverage analysis."""

    ISS_ELEMENTS = KeplerianElements(
        a=6778.0, e=0.001, i=math.radians(51.6),
        raan=0.0, argp=0.0, nu=0.0,
    )

    STATIONS = [
        GroundStation("equator", 0.0, 0.0, min_elevation_deg=5.0),
        GroundStation("high_lat", 52.0, 4.5, min_elevation_deg=5.0),
    ]

    def test_coverage_result_type(self):
        result = coverage_analysis(
            self.ISS_ELEMENTS,
            self.STATIONS,
            analysis_duration_s=3 * 3600.0,
            time_step_s=60.0,
        )
        assert isinstance(result, CoverageResult)

    def test_access_fraction_between_0_and_1(self):
        result = coverage_analysis(
            self.ISS_ELEMENTS,
            self.STATIONS,
            analysis_duration_s=6 * 3600.0,
            time_step_s=60.0,
        )
        assert 0.0 <= result.access_fraction <= 1.0

    def test_total_contact_time_positive(self):
        result = coverage_analysis(
            self.ISS_ELEMENTS,
            self.STATIONS,
            analysis_duration_s=6 * 3600.0,
            time_step_s=60.0,
        )
        assert result.total_contact_time_s >= 0.0

    def test_contacts_sorted_by_rise_time(self):
        result = coverage_analysis(
            self.ISS_ELEMENTS,
            self.STATIONS,
            analysis_duration_s=6 * 3600.0,
            time_step_s=60.0,
        )
        times = [c.rise_time_s for c in result.contacts]
        assert times == sorted(times)
