"""
Tests for kerf_cad_core.optics.photon_map — Jensen 1996 photon-mapping engine.

Test plan
---------
 1. test_single_photon_gather_in_radius    — PhotonMap.gather on a single photon within
                                            radius → returns non-zero irradiance ≈ photon power / area.
 2. test_photon_outside_radius_not_gathered — Photon beyond radius → irradiance = 0.
 3. test_emit_total_count                  — emit_photons yields exactly n_photons.
 4. test_emit_one_per_wavelength_bucket    — with n_photons == len(wavelengths), each bucket has 1 photon.
 5. test_emit_wavelength_bucket_distribution — with n_photons=10, 3 wavelengths: counts [4,3,3].
 6. test_bk7_refractive_index_d_line       — BK7 at 587 nm ≈ 1.5168 ±0.01.
 7. test_bk7_normal_dispersion             — BK7 n(486) > n(587) > n(656) (normal dispersion).
 8. test_sf11_refractive_index             — SF11 at 587 nm ≈ 1.785 ±0.01.
 9. test_snell_refraction_angle            — photon entering glass at 30°, n1=1.0, n2=1.5 → refracted at
                                            arcsin(sin 30° / 1.5) ±0.1°.
10. test_snell_tir                         — photon hitting glass–air at supercritical angle → TIR (None).
11. test_snell_normal_incidence            — photon hitting normal incidence → direction unchanged.
12. test_trace_glass_diffuse_hit           — simple scene: glass sphere + diffuse floor → photon recorded.
13. test_trace_max_bounces_absorption      — scene with infinite glass loop → no photon stored after
                                            max_bounces (map is empty or has max_bounces-1 photons).
14. test_emit_deterministic                — emit_photons with rng_seed=0 called twice → identical output.
15. test_power_flux_conservation           — sum of stored photon power ≤ emitted power; escaping photons
                                            counted (the difference is escaped / TIR'd power, within 0.
16. test_gather_max_n_limit                — inserting 200 photons, gathering with max_n=10 → uses only
                                            10 closest.
17. test_material_from_glass_bk7          — material_from_glass("BK7") constructs correct material.
18. test_material_from_glass_unknown      — material_from_glass("UNKNOWN") raises KeyError.
19. test_wavelength_rgb_weight_bands      — _wavelength_to_rgb_weight maps red/green/blue correctly.

All tests: pure-Python, no network, no DB, no OCC.

References
----------
Jensen, H.W. (1996). "Global Illumination Using Photon Maps." EGWR 96.
Jensen, H.W. (2001). "Realistic Image Synthesis Using Photon Mapping." Ch. 7.
Schott AG — Optical Glass Data Sheets, 2023 (Sellmeier coefficients).

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pytest

from kerf_cad_core.optics.photon_map import (
    Photon,
    PhotonMap,
    Light,
    RefractiveMaterial,
    emit_photons,
    material_from_glass,
    trace_photons,
    _snell_refract,
    _reflect,
    _wavelength_to_rgb_weight,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_photon(pos=(0.0, 0.0, 0.0), dirn=(0.0, 0.0, -1.0), power=(1.0, 1.0, 1.0), wl=550.0):
    return Photon(
        position=np.array(pos, dtype=float),
        direction=np.array(dirn, dtype=float),
        power_rgb=np.array(power, dtype=float),
        wavelength_nm=wl,
    )


def _point_light(pos=(0.0, 5.0, 0.0), intensity=(1.0, 1.0, 1.0)):
    return Light(
        position=np.array(pos, dtype=float),
        intensity_rgb=np.array(intensity, dtype=float),
    )


# ---------------------------------------------------------------------------
# 1. Single photon gather within radius
# ---------------------------------------------------------------------------

def test_single_photon_gather_in_radius():
    """PhotonMap.gather on a single photon at distance < radius → non-zero irradiance."""
    ph = _make_photon(pos=(0.0, 0.0, 0.0), power=(2.0, 3.0, 4.0))
    pm = PhotonMap(photons=[ph])
    normal = np.array([0.0, 1.0, 0.0])
    result = pm.gather(np.array([0.0, 0.0, 0.0]), normal, radius=0.5)
    assert result.shape == (3,)
    assert np.all(result >= 0.0)
    # irradiance should be > 0 since photon is at query point
    assert np.sum(result) > 0.0


# ---------------------------------------------------------------------------
# 2. Photon outside radius not gathered
# ---------------------------------------------------------------------------

def test_photon_outside_radius_not_gathered():
    """Photon beyond gather radius → irradiance = 0."""
    ph = _make_photon(pos=(10.0, 0.0, 0.0))
    pm = PhotonMap(photons=[ph])
    normal = np.array([0.0, 1.0, 0.0])
    result = pm.gather(np.array([0.0, 0.0, 0.0]), normal, radius=0.5)
    assert np.all(result == 0.0)


# ---------------------------------------------------------------------------
# 3. emit_photons total count
# ---------------------------------------------------------------------------

def test_emit_total_count():
    """emit_photons returns exactly n_photons photons."""
    light = _point_light()
    photons = emit_photons(light, n_photons=50, wavelengths_nm=[450.0, 550.0, 650.0])
    assert len(photons) == 50


# ---------------------------------------------------------------------------
# 4. One photon per wavelength bucket when n_photons == len(wavelengths)
# ---------------------------------------------------------------------------

def test_emit_one_per_wavelength_bucket():
    """With n_photons == len(wavelengths), exactly one photon per bucket."""
    wls = [450.0, 550.0, 650.0]
    light = _point_light()
    photons = emit_photons(light, n_photons=3, wavelengths_nm=wls)
    assert len(photons) == 3
    emitted_wls = sorted(p.wavelength_nm for p in photons)
    assert emitted_wls == sorted(wls)


# ---------------------------------------------------------------------------
# 5. Wavelength bucket distribution for non-divisible count
# ---------------------------------------------------------------------------

def test_emit_wavelength_bucket_distribution():
    """n_photons=10, 3 wavelengths → buckets [4, 3, 3]."""
    wls = [450.0, 550.0, 650.0]
    light = _point_light()
    photons = emit_photons(light, n_photons=10, wavelengths_nm=wls)
    assert len(photons) == 10
    counts = {wl: sum(1 for p in photons if p.wavelength_nm == wl) for wl in wls}
    assert sorted(counts.values()) == [3, 3, 4]


# ---------------------------------------------------------------------------
# 6. BK7 refractive index at d-line
# ---------------------------------------------------------------------------

def test_bk7_refractive_index_d_line():
    """BK7 n(587.56 nm) ≈ 1.5168 ±0.01."""
    mat = material_from_glass("BK7")
    n = mat.refractive_index(587.56)
    assert abs(n - 1.5168) < 0.01, f"BK7 n(587 nm) = {n}, expected ≈ 1.5168"


# ---------------------------------------------------------------------------
# 7. BK7 normal dispersion (F > d > C wavelengths)
# ---------------------------------------------------------------------------

def test_bk7_normal_dispersion():
    """BK7 n(486 nm) > n(587 nm) > n(656 nm) — normal dispersion."""
    mat = material_from_glass("BK7")
    n_F = mat.refractive_index(486.1)   # F-line (blue)
    n_d = mat.refractive_index(587.6)   # d-line (green)
    n_C = mat.refractive_index(656.3)   # C-line (red)
    assert n_F > n_d > n_C, f"Dispersion violated: n_F={n_F}, n_d={n_d}, n_C={n_C}"


# ---------------------------------------------------------------------------
# 8. SF11 refractive index
# ---------------------------------------------------------------------------

def test_sf11_refractive_index():
    """SF11 n(587 nm) ≈ 1.785 ±0.01 (Schott catalog)."""
    mat = material_from_glass("SF11")
    n = mat.refractive_index(587.0)
    assert abs(n - 1.785) < 0.01, f"SF11 n(587 nm) = {n}, expected ≈ 1.785"


# ---------------------------------------------------------------------------
# 9. Snell refraction angle check
# ---------------------------------------------------------------------------

def test_snell_refraction_angle():
    """
    Photon entering glass at 30° angle-of-incidence, n1=1.0, n2=1.5.
    Expected refracted angle = arcsin(sin(30°)/1.5) ≈ 19.47°.
    Tolerance: ±0.1°.
    """
    theta_i_deg = 30.0
    theta_i = math.radians(theta_i_deg)
    n1, n2 = 1.0, 1.5

    # Incident direction: hits a flat interface normal to z-axis
    # Interface normal = (0, 0, 1)
    normal = np.array([0.0, 0.0, 1.0])
    # Incident ray going in +z with x-component to give 30° off-normal
    d = np.array([math.sin(theta_i), 0.0, math.cos(theta_i)])
    # Point toward the surface (anti-normal component)
    incident = np.array([math.sin(theta_i), 0.0, -math.cos(theta_i)])

    refracted = _snell_refract(incident, normal, n1, n2)
    assert refracted is not None, "Unexpected TIR at 30°"

    # Compute actual refraction angle
    cos_t = abs(float(np.dot(refracted, normal)))
    theta_t = math.degrees(math.acos(min(cos_t, 1.0)))

    expected_deg = math.degrees(math.asin(math.sin(theta_i) / n2))
    assert abs(theta_t - expected_deg) < 0.1, (
        f"Refracted angle {theta_t:.3f}° ≠ expected {expected_deg:.3f}°"
    )


# ---------------------------------------------------------------------------
# 10. Snell TIR
# ---------------------------------------------------------------------------

def test_snell_tir():
    """Photon hitting glass–air interface at supercritical angle → TIR (None)."""
    # Critical angle for n_glass=1.5 → n_air=1.0: sin_c = 1/1.5 → θ_c ≈ 41.8°
    # Use 50° > 41.8° → TIR
    theta_i = math.radians(50.0)
    normal = np.array([0.0, 0.0, 1.0])
    incident = np.array([math.sin(theta_i), 0.0, -math.cos(theta_i)])
    result = _snell_refract(incident, normal, n1=1.5, n2=1.0)
    assert result is None, f"Expected TIR but got refracted direction {result}"


# ---------------------------------------------------------------------------
# 11. Normal incidence → direction unchanged
# ---------------------------------------------------------------------------

def test_snell_normal_incidence():
    """Normal incidence (θ=0°) → refracted direction equals incident direction."""
    normal = np.array([0.0, 0.0, 1.0])
    incident = np.array([0.0, 0.0, -1.0])
    refracted = _snell_refract(incident, normal, n1=1.0, n2=1.5)
    assert refracted is not None
    # Refracted should be along -z
    assert abs(abs(refracted[2]) - 1.0) < 1e-10, f"Normal incidence direction error: {refracted}"


# ---------------------------------------------------------------------------
# 12. Trace glass + diffuse scene → photon recorded
# ---------------------------------------------------------------------------

def test_trace_glass_diffuse_hit():
    """
    Scene: first hit is glass (refract through), second hit is diffuse floor.
    Photon should be recorded in the map.
    """
    bk7 = material_from_glass("BK7")
    call_count = [0]

    def scene_intersect(origin, direction):
        call_count[0] += 1
        if call_count[0] == 1:
            # Glass surface at z = -1
            return {
                "t": 1.0,
                "position": np.array([0.0, 0.0, -1.0]),
                "normal": np.array([0.0, 0.0, 1.0]),
                "surface": "glass",
                "material": bk7,
                "n_inside": None,
            }
        else:
            # Diffuse floor at z = -5
            return {
                "t": 4.0,
                "position": np.array([0.0, 0.0, -5.0]),
                "normal": np.array([0.0, 0.0, 1.0]),
                "surface": "diffuse",
                "material": None,
            }

    photon = _make_photon(pos=(0.0, 0.0, 0.0), dirn=(0.0, 0.0, -1.0))
    pm = trace_photons([photon], scene_intersect, max_bounces=6)
    assert len(pm.photons) == 1
    assert pm.photons[0].position[2] == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# 13. Trace max bounces → absorption
# ---------------------------------------------------------------------------

def test_trace_max_bounces_absorption():
    """
    Scene returns only glass hits indefinitely.
    After max_bounces the photon is absorbed without being stored.
    """
    bk7 = material_from_glass("BK7")

    def scene_intersect(origin, direction):
        return {
            "t": 0.1,
            "position": origin + 0.1 * direction,
            "normal": -direction,  # Always facing the incoming photon
            "surface": "glass",
            "material": bk7,
            "n_inside": None,
        }

    photon = _make_photon()
    pm = trace_photons([photon], scene_intersect, max_bounces=3)
    # Photon should not have been recorded (no diffuse hit)
    assert len(pm.photons) == 0


# ---------------------------------------------------------------------------
# 14. Deterministic emission
# ---------------------------------------------------------------------------

def test_emit_deterministic():
    """emit_photons with rng_seed=0 called twice → identical positions/directions."""
    light = _point_light()
    wls = [450.0, 550.0, 650.0]
    p1 = emit_photons(light, n_photons=30, wavelengths_nm=wls, rng_seed=0)
    p2 = emit_photons(light, n_photons=30, wavelengths_nm=wls, rng_seed=0)
    assert len(p1) == len(p2)
    for a, b in zip(p1, p2):
        np.testing.assert_array_equal(a.position, b.position)
        np.testing.assert_array_equal(a.direction, b.direction)
        np.testing.assert_array_equal(a.power_rgb, b.power_rgb)
        assert a.wavelength_nm == b.wavelength_nm


# ---------------------------------------------------------------------------
# 15. Power flux conservation
# ---------------------------------------------------------------------------

def test_power_flux_conservation():
    """
    Total power emitted ≥ total power stored + escaped power.
    In a simple scene (all photons hitting a diffuse surface after 0 bounces),
    stored power = emitted power (within floating-point noise).
    """
    light = Light(
        position=np.array([0.0, 5.0, 0.0]),
        intensity_rgb=np.array([1.0, 1.0, 1.0]),
    )
    wls = [550.0]
    photons = emit_photons(light, n_photons=20, wavelengths_nm=wls, rng_seed=42)
    total_emitted = sum(float(np.sum(p.power_rgb)) for p in photons)

    # All photons hit a diffuse surface immediately
    def scene_intersect(origin, direction):
        return {
            "t": 1.0,
            "position": origin + direction,
            "normal": -direction,
            "surface": "diffuse",
            "material": None,
        }

    pm = trace_photons(photons, scene_intersect, max_bounces=6)
    total_stored = sum(float(np.sum(p.power_rgb)) for p in pm.photons)

    # All emitted power should be stored (no escapes, no glass, no absorption)
    assert abs(total_stored - total_emitted) < 1e-12 * max(total_emitted, 1.0)


# ---------------------------------------------------------------------------
# 16. Gather max_n limit
# ---------------------------------------------------------------------------

def test_gather_max_n_limit():
    """
    With 200 photons all at origin, gather max_n=10 uses only 10 photons.
    The result should be smaller than with max_n=200.
    """
    photons = [_make_photon(pos=(0.0, 0.0, 0.0), power=(1.0, 1.0, 1.0)) for _ in range(200)]
    pm = PhotonMap(photons=photons)
    normal = np.array([0.0, 1.0, 0.0])
    q = np.array([0.0, 0.0, 0.0])

    result_10 = pm.gather(q, normal, radius=1.0, max_n=10)
    result_200 = pm.gather(q, normal, radius=1.0, max_n=200)

    # Limited gather should be ≤ full gather
    assert np.sum(result_10) <= np.sum(result_200) + 1e-12


# ---------------------------------------------------------------------------
# 17. material_from_glass constructs BK7 correctly
# ---------------------------------------------------------------------------

def test_material_from_glass_bk7():
    """material_from_glass('BK7') produces correct name, Abbe number, and n(587)."""
    mat = material_from_glass("BK7")
    assert mat.name == "BK7"
    assert 60.0 < mat.abbe_number < 70.0, f"BK7 Abbe={mat.abbe_number}"
    n = mat.refractive_index(587.56)
    assert abs(n - 1.5168) < 0.01


# ---------------------------------------------------------------------------
# 18. material_from_glass unknown glass → KeyError
# ---------------------------------------------------------------------------

def test_material_from_glass_unknown():
    """material_from_glass('UNKNOWN') raises KeyError."""
    with pytest.raises(KeyError):
        material_from_glass("UNKNOWN")


# ---------------------------------------------------------------------------
# 19. Wavelength RGB weight bands
# ---------------------------------------------------------------------------

def test_wavelength_rgb_weight_bands():
    """_wavelength_to_rgb_weight maps wavelengths to correct RGB channels."""
    # Red band: 620–700 nm
    r = _wavelength_to_rgb_weight(660.0)
    assert r[0] == 1.0 and r[1] == 0.0 and r[2] == 0.0, f"Red band failed: {r}"

    # Green band: 500–620 nm
    g = _wavelength_to_rgb_weight(550.0)
    assert g[0] == 0.0 and g[1] == 1.0 and g[2] == 0.0, f"Green band failed: {g}"

    # Blue band: 380–500 nm
    b = _wavelength_to_rgb_weight(450.0)
    assert b[0] == 0.0 and b[1] == 0.0 and b[2] == 1.0, f"Blue band failed: {b}"
