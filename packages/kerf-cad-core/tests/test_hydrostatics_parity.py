"""
test_hydrostatics_parity.py — Three-way hydrostatics parity test.

Verifies that all three hull-hydrostatics entry points produce consistent
displacement, waterplane area, and KB for a known analytic hull (box barge).

Entry points under test
-----------------------
1. kerf_cad_core.navalarch.hydrostatics  — canonical (displacement_from_offsets,
   waterplane_properties, vertical_centres)
2. kerf_cad_core.marine.hull.hydrostatics  — offset-table path in marine/hull.py
3. kerf_marine.hydrostatics.compute_hydrostatics — separate package, own sections.py

Analytic oracle (box barge)
---------------------------
  L=50 m, B=10 m, T=3 m, ρ=1.025 t/m³
  ∇ = L·B·T = 1500 m³
  Δ = 1.025 × 1500 = 1537.5 t
  A_wp = L·B = 500 m²
  KB  = T/2 = 1.5 m   (exact for rectangular section)

All three paths must agree within 1 % relative tolerance on ∇ and A_wp,
and within 5 % on KB (formula-based estimates may differ slightly).

Author: imranparuk
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Box-barge parameters
# ---------------------------------------------------------------------------
L = 50.0
B = 10.0
T = 3.0
RHO_SW = 1.025   # t/m³ (kerf-marine convention)
RHO_SW_KG = 1025.0  # kg/m³ (navalarch convention)
N_ST = 11   # stations for numerical integration
N_WL = 7    # waterlines for numerical integration

ANALYTIC_VOLUME = L * B * T          # 1500 m³
ANALYTIC_DISP_T = RHO_SW * ANALYTIC_VOLUME  # 1537.5 t
ANALYTIC_AWP = L * B                 # 500 m²
ANALYTIC_KB = T / 2.0                # 1.5 m  (box barge exact)


# ---------------------------------------------------------------------------
# Helpers to build offset tables in each format
# ---------------------------------------------------------------------------

def _navalarch_stations_and_areas():
    """
    Build equally-spaced stations and constant sectional areas for a box barge.
    Sectional area at each station = B × T (full beam × draft).
    """
    import numpy as np
    xs = list(float(x) for x in [L * i / (N_ST - 1) for i in range(N_ST)])
    As = [B * T] * N_ST   # constant area (box barge)
    return xs, As


def _navalarch_waterplane_stations_and_hbs():
    """Half-breadths at the design waterline: B/2 at every station."""
    xs = [L * i / (N_ST - 1) for i in range(N_ST)]
    ys = [B / 2.0] * N_ST
    return xs, ys


def _marine_hull_offsets():
    """
    Build offset rows in kerf_cad_core.marine.hull format:
    {station, waterline, half_breadth} dicts.
    """
    rows = []
    for i in range(N_ST):
        st = L * i / (N_ST - 1)
        for j in range(N_WL):
            wl = T * j / (N_WL - 1)
            rows.append({"station": st, "waterline": wl, "half_breadth": B / 2.0})
    return rows


def _kerf_marine_offset_table():
    """Build a kerf_marine.sections.OffsetTable for the same box barge."""
    from kerf_marine.sections import OffsetTable
    table = OffsetTable()
    for i in range(N_ST):
        st = L * i / (N_ST - 1)
        for j in range(N_WL):
            wl = T * j / (N_WL - 1)
            table.add(float(st), float(wl), B / 2.0)
    return table


# ---------------------------------------------------------------------------
# Collect results from all three entry points
# ---------------------------------------------------------------------------

def _navalarch_results():
    """
    Compute displacement (volume), waterplane area, and KB from navalarch.
    Uses displacement_from_offsets + waterplane_properties + vertical_centres.
    """
    from kerf_cad_core.navalarch.hydrostatics import (
        displacement_from_offsets,
        waterplane_properties,
        vertical_centres,
    )

    xs, As = _navalarch_stations_and_areas()
    xs_wp, ys_wp = _navalarch_waterplane_stations_and_hbs()

    disp_res = displacement_from_offsets(xs, As, rho=RHO_SW_KG)
    assert disp_res["ok"], f"navalarch displacement_from_offsets failed: {disp_res}"

    wp_res = waterplane_properties(xs_wp, ys_wp)
    assert wp_res["ok"], f"navalarch waterplane_properties failed: {wp_res}"

    vc_res = vertical_centres(T=T, Cb=1.0)  # Cb=1 for box barge
    assert vc_res["ok"], f"navalarch vertical_centres failed: {vc_res}"

    return {
        "volume_m3": disp_res["volume_m3"],
        "displacement_t": disp_res["displacement_t"],
        "Awp_m2": wp_res["Aw_m2"],
        "KB_m": vc_res["KB_box_m"],   # exact T/2 for box
    }


def _marine_hull_results():
    """Compute displacement, waterplane area from kerf_cad_core.marine.hull.hydrostatics."""
    from kerf_cad_core.marine.hull import hydrostatics

    rows = _marine_hull_offsets()
    res = hydrostatics(rows, design_waterline=T)
    assert res["ok"], f"marine.hull.hydrostatics failed: {res}"

    # marine/hull.py does not compute displacement_t or KB directly;
    # derive displacement_t from volume and density, KB from first principles
    volume = res["displaced_volume_m3"]
    displacement_t = volume * RHO_SW
    # KB for box barge is T/2 (analytic); marine/hull does not compute KB
    return {
        "volume_m3": volume,
        "displacement_t": displacement_t,
        "Awp_m2": res["waterplane_area_m2"],
        "KB_m": T / 2.0,   # analytic oracle (marine/hull does not expose KB)
    }


def _kerf_marine_results():
    """Compute full hydrostatics from kerf_marine.hydrostatics.compute_hydrostatics."""
    from kerf_marine.hydrostatics import compute_hydrostatics

    table = _kerf_marine_offset_table()
    ht = compute_hydrostatics(table, draft=T, rho=RHO_SW)
    return {
        "volume_m3": ht.volume,
        "displacement_t": ht.displacement,
        "Awp_m2": ht.waterplane_area,
        "KB_m": ht.kb,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHydrostaticsParity:
    """Cross-package parity: all three entry points must agree on a box barge."""

    REL_TOL = 0.01   # 1 % relative tolerance for volume / area
    KB_TOL  = 0.05   # 5 % relative tolerance for KB (formula differences)

    @pytest.fixture(scope="class")
    def all_results(self):
        return {
            "navalarch":    _navalarch_results(),
            "marine_hull":  _marine_hull_results(),
            "kerf_marine":  _kerf_marine_results(),
        }

    # -- Analytic oracle checks (each entry point vs closed-form) -----------

    def test_navalarch_volume_oracle(self, all_results):
        v = all_results["navalarch"]["volume_m3"]
        assert abs(v - ANALYTIC_VOLUME) / ANALYTIC_VOLUME < self.REL_TOL, (
            f"navalarch volume {v:.3f} vs oracle {ANALYTIC_VOLUME}"
        )

    def test_marine_hull_volume_oracle(self, all_results):
        v = all_results["marine_hull"]["volume_m3"]
        assert abs(v - ANALYTIC_VOLUME) / ANALYTIC_VOLUME < self.REL_TOL, (
            f"marine_hull volume {v:.3f} vs oracle {ANALYTIC_VOLUME}"
        )

    def test_kerf_marine_volume_oracle(self, all_results):
        v = all_results["kerf_marine"]["volume_m3"]
        assert abs(v - ANALYTIC_VOLUME) / ANALYTIC_VOLUME < self.REL_TOL, (
            f"kerf_marine volume {v:.3f} vs oracle {ANALYTIC_VOLUME}"
        )

    def test_navalarch_displacement_oracle(self, all_results):
        d = all_results["navalarch"]["displacement_t"]
        assert abs(d - ANALYTIC_DISP_T) / ANALYTIC_DISP_T < self.REL_TOL

    def test_marine_hull_displacement_oracle(self, all_results):
        d = all_results["marine_hull"]["displacement_t"]
        assert abs(d - ANALYTIC_DISP_T) / ANALYTIC_DISP_T < self.REL_TOL

    def test_kerf_marine_displacement_oracle(self, all_results):
        d = all_results["kerf_marine"]["displacement_t"]
        assert abs(d - ANALYTIC_DISP_T) / ANALYTIC_DISP_T < self.REL_TOL

    def test_navalarch_awp_oracle(self, all_results):
        a = all_results["navalarch"]["Awp_m2"]
        assert abs(a - ANALYTIC_AWP) / ANALYTIC_AWP < self.REL_TOL

    def test_marine_hull_awp_oracle(self, all_results):
        a = all_results["marine_hull"]["Awp_m2"]
        assert abs(a - ANALYTIC_AWP) / ANALYTIC_AWP < self.REL_TOL

    def test_kerf_marine_awp_oracle(self, all_results):
        a = all_results["kerf_marine"]["Awp_m2"]
        assert abs(a - ANALYTIC_AWP) / ANALYTIC_AWP < self.REL_TOL

    def test_navalarch_kb_oracle(self, all_results):
        kb = all_results["navalarch"]["KB_m"]
        assert abs(kb - ANALYTIC_KB) / ANALYTIC_KB < self.KB_TOL

    def test_kerf_marine_kb_oracle(self, all_results):
        kb = all_results["kerf_marine"]["KB_m"]
        assert abs(kb - ANALYTIC_KB) / ANALYTIC_KB < self.KB_TOL

    # -- Cross-entry-point parity (the three must agree with each other) ---

    def test_volume_parity_navalarch_vs_marine_hull(self, all_results):
        v1 = all_results["navalarch"]["volume_m3"]
        v2 = all_results["marine_hull"]["volume_m3"]
        assert abs(v1 - v2) / max(v1, v2) < self.REL_TOL, (
            f"volume mismatch: navalarch={v1:.4f}, marine_hull={v2:.4f}"
        )

    def test_volume_parity_navalarch_vs_kerf_marine(self, all_results):
        v1 = all_results["navalarch"]["volume_m3"]
        v2 = all_results["kerf_marine"]["volume_m3"]
        assert abs(v1 - v2) / max(v1, v2) < self.REL_TOL, (
            f"volume mismatch: navalarch={v1:.4f}, kerf_marine={v2:.4f}"
        )

    def test_volume_parity_marine_hull_vs_kerf_marine(self, all_results):
        v1 = all_results["marine_hull"]["volume_m3"]
        v2 = all_results["kerf_marine"]["volume_m3"]
        assert abs(v1 - v2) / max(v1, v2) < self.REL_TOL, (
            f"volume mismatch: marine_hull={v1:.4f}, kerf_marine={v2:.4f}"
        )

    def test_awp_parity_navalarch_vs_marine_hull(self, all_results):
        a1 = all_results["navalarch"]["Awp_m2"]
        a2 = all_results["marine_hull"]["Awp_m2"]
        assert abs(a1 - a2) / max(a1, a2) < self.REL_TOL, (
            f"Awp mismatch: navalarch={a1:.4f}, marine_hull={a2:.4f}"
        )

    def test_awp_parity_navalarch_vs_kerf_marine(self, all_results):
        a1 = all_results["navalarch"]["Awp_m2"]
        a2 = all_results["kerf_marine"]["Awp_m2"]
        assert abs(a1 - a2) / max(a1, a2) < self.REL_TOL, (
            f"Awp mismatch: navalarch={a1:.4f}, kerf_marine={a2:.4f}"
        )

    def test_awp_parity_marine_hull_vs_kerf_marine(self, all_results):
        a1 = all_results["marine_hull"]["Awp_m2"]
        a2 = all_results["kerf_marine"]["Awp_m2"]
        assert abs(a1 - a2) / max(a1, a2) < self.REL_TOL, (
            f"Awp mismatch: marine_hull={a1:.4f}, kerf_marine={a2:.4f}"
        )

    def test_kb_parity_navalarch_vs_kerf_marine(self, all_results):
        k1 = all_results["navalarch"]["KB_m"]
        k2 = all_results["kerf_marine"]["KB_m"]
        assert abs(k1 - k2) / max(k1, k2) < self.KB_TOL, (
            f"KB mismatch: navalarch={k1:.4f}, kerf_marine={k2:.4f}"
        )

    def test_displacement_parity_all_three(self, all_results):
        """All three displacement values agree with each other within 1 %."""
        d1 = all_results["navalarch"]["displacement_t"]
        d2 = all_results["marine_hull"]["displacement_t"]
        d3 = all_results["kerf_marine"]["displacement_t"]
        max_d = max(d1, d2, d3)
        assert abs(d1 - d2) / max_d < self.REL_TOL
        assert abs(d1 - d3) / max_d < self.REL_TOL
        assert abs(d2 - d3) / max_d < self.REL_TOL


class TestHydrostaticsParityScalars:
    """Quick scalar checks — single-value assertions for CI speed."""

    def test_navalarch_volume_within_1pct(self):
        r = _navalarch_results()
        assert abs(r["volume_m3"] - ANALYTIC_VOLUME) / ANALYTIC_VOLUME < 0.01

    def test_marine_hull_volume_within_1pct(self):
        r = _marine_hull_results()
        assert abs(r["volume_m3"] - ANALYTIC_VOLUME) / ANALYTIC_VOLUME < 0.01

    def test_kerf_marine_volume_within_1pct(self):
        r = _kerf_marine_results()
        assert abs(r["volume_m3"] - ANALYTIC_VOLUME) / ANALYTIC_VOLUME < 0.01

    def test_kerf_marine_awp_within_1pct(self):
        r = _kerf_marine_results()
        assert abs(r["Awp_m2"] - ANALYTIC_AWP) / ANALYTIC_AWP < 0.01

    def test_kerf_marine_kb_within_5pct(self):
        r = _kerf_marine_results()
        assert abs(r["KB_m"] - ANALYTIC_KB) / ANALYTIC_KB < 0.05
