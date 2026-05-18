"""T-170: Watchmaking / horology seed tests.

Verifies the three DoD deliverables per the task entry:

  1. Escape wheel + pallet fork generators satisfy the partsgen loader
     contract (FAMILY, SIZES, build callable — hermetic, no kernel needed).
  2. Involute tooth profile for the escape-wheel module passes the geometry
     validity check (``check_involute_profile``).
  3. ``train_calculator`` ratio for 3 Hz + 48-hour power reserve matches the
     analytically expected value.

Kernel-gated tests (cadquery / OCCT required) build the escape wheel,
pallet fork, gear train, and mainspring barrel solids and check that each
produces a valid non-degenerate solid.  These tests are skipped when no
kernel binding is present.

Analytic tests (no kernel required) cover the involute profile and the
train-ratio calculator — these always run.
"""

from __future__ import annotations

import math
import sys
import os

import pytest

# ---------------------------------------------------------------------------
# Path setup (mirror conftest, also needed for direct -m pytest invocations)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PACKAGES = os.path.dirname(_PKG)

for _entry in os.listdir(_PACKAGES):
    if not _entry.startswith("kerf-"):
        continue
    _src = os.path.join(_PACKAGES, _entry, "src")
    if os.path.isdir(_src) and _src not in sys.path:
        sys.path.insert(0, _src)

# ---------------------------------------------------------------------------
# Imports (after path setup)
# ---------------------------------------------------------------------------

from kerf_partsgen import kernel
from kerf_partsgen.loader import load_generator
from kerf_partsgen.generators.horology.involute import (
    involute_profile,
    check_involute_profile,
)
from kerf_partsgen.generators.horology.train_calculator import (
    compute_train_ratio,
    factorise_ratio,
)
from kerf_horology import (
    check_involute_profile as horology_check_profile,
    compute_train_ratio as horology_train_ratio,
)
from kerf_horology.tools import _train_calculator, _check_tooth_profile

# ---------------------------------------------------------------------------
# Kernel skip marker
# ---------------------------------------------------------------------------

needs_kernel = pytest.mark.skipif(
    not kernel.KERNEL_AVAILABLE,
    reason="no OCCT kernel binding (cadquery/pythonocc) installed",
)

# ---------------------------------------------------------------------------
# Loader contract tests (no kernel required)
# ---------------------------------------------------------------------------

_HOROLOGY_GEN_DIR = os.path.join(
    _PACKAGES,
    "kerf-partsgen",
    "src",
    "kerf_partsgen",
    "generators",
    "horology",
)


def _load(family_id: str):
    path = os.path.join(_HOROLOGY_GEN_DIR, f"{family_id}.py")
    return load_generator(path)


def test_escape_wheel_loader_contract():
    g = _load("escape_wheel")
    assert g.family_id == "horology_escape_wheel"
    assert g.domain == "horology"
    assert g.category == "horology/escapement"
    assert g.standard == "KERF-HOROLOGY"
    assert callable(g.build)


def test_escape_wheel_sizes_table():
    g = _load("escape_wheel")
    assert len(g.sizes) == 3
    labels = [r["size"] for r in g.sizes]
    assert "7¾liga" in labels, f"Expected 7¾liga in {labels}"
    for row in g.sizes:
        assert "params" in row
        assert "expect" in row
        p = row["params"]
        for key in ("outer_diameter", "num_teeth", "thickness",
                    "bore_diameter", "module"):
            assert key in p, f"{row['size']}: params missing {key!r}"
        assert p["num_teeth"] == 15, (
            f"{row['size']}: Swiss lever escape wheel must have 15 teeth"
        )
        assert p["outer_diameter"] > p["bore_diameter"], (
            f"{row['size']}: outer_diameter <= bore_diameter"
        )


def test_pallet_fork_loader_contract():
    g = _load("pallet_fork")
    assert g.family_id == "horology_pallet_fork"
    assert g.domain == "horology"
    assert g.category == "horology/escapement"
    assert callable(g.build)


def test_pallet_fork_sizes_table():
    g = _load("pallet_fork")
    assert len(g.sizes) >= 2
    for row in g.sizes:
        assert "params" in row
        assert "expect" in row
        p = row["params"]
        for key in ("length", "width", "thickness"):
            assert key in p
        assert p["length"] > 0 and p["width"] > 0 and p["thickness"] > 0


def test_gear_train_wheel_loader_contract():
    g = _load("gear_train")
    assert g.family_id == "horology_gear_train_wheel"
    assert g.domain == "horology"
    assert g.category == "horology/gear_train"
    assert callable(g.build)


def test_mainspring_barrel_loader_contract():
    g = _load("mainspring_barrel")
    assert g.family_id == "horology_mainspring_barrel"
    assert g.domain == "horology"
    assert g.category == "horology/barrel"
    assert callable(g.build)


# ---------------------------------------------------------------------------
# Involute profile tests — DoD criterion 2 (no kernel required)
# ---------------------------------------------------------------------------


def test_involute_profile_escape_wheel_passes():
    """Escape-wheel module (0.128 mm, 15 teeth, 20°) passes involute check.

    This is the DoD reference test: the 7¾liga escape wheel tooth profile
    must satisfy all five geometry validity criteria in check_involute_profile.
    """
    # 7¾liga escape wheel: OD=3.85mm, 15 teeth → module=3.85/15≈0.2567
    # Use the module from the generator's SIZES table
    from kerf_partsgen.generators.horology import escape_wheel as ew_mod
    row_7 = next(r for r in ew_mod.SIZES if r["size"] == "7¾liga")
    module = row_7["params"]["module"]
    num_teeth = row_7["params"]["num_teeth"]

    result = check_involute_profile(module, num_teeth, pressure_angle_deg=20.0)
    assert result.passed, (
        f"7¾liga escape wheel involute check FAILED: {result.reasons}"
    )


def test_involute_profile_standard_watch_gear():
    """Standard wristwatch gear (m=0.10, z=72, 20°) passes involute check."""
    result = check_involute_profile(0.10, 72, pressure_angle_deg=20.0)
    assert result.passed, (
        f"m0.10z72 involute check FAILED: {result.reasons}"
    )


def test_involute_profile_base_circle_lt_pitch():
    """Base-circle radius is always smaller than pitch radius."""
    for module in (0.10, 0.15, 0.20, 0.25):
        for z in (15, 30, 60, 80):
            result = check_involute_profile(module, z, 20.0)
            assert result.r_base < result.r_pitch, (
                f"m={module} z={z}: r_base {result.r_base} >= r_pitch {result.r_pitch}"
            )


def test_involute_profile_reaches_tip():
    """Profile must extend to the tip circle for every test case."""
    for module, z in ((0.10, 72), (0.128, 15), (0.20, 80)):
        pts = involute_profile(module, z, 20.0, n_points=60)
        r_tip = (module * z) / 2.0 + module  # r_pitch + addendum
        max_r = max(pt.r for pt in pts)
        assert max_r >= r_tip - 1e-4, (
            f"m={module} z={z}: max_r {max_r:.6f} < r_tip {r_tip:.6f}"
        )


def test_involute_profile_monotone_radius():
    """Involute profile points are ordered root-to-tip (non-decreasing r)."""
    pts = involute_profile(0.128, 15, 20.0, n_points=40)
    for i in range(1, len(pts)):
        assert pts[i].r >= pts[i - 1].r - 1e-10, (
            f"non-monotone at index {i}: r[{i}]={pts[i].r} < r[{i-1}]={pts[i-1].r}"
        )


def test_involute_check_returns_correct_radii():
    """check_involute_profile returns r_base, r_pitch, r_tip consistent with formulas."""
    module, z, alpha_deg = 0.20, 80, 20.0
    alpha = math.radians(alpha_deg)
    expected_r_p = (module * z) / 2.0
    expected_r_b = expected_r_p * math.cos(alpha)
    expected_r_a = expected_r_p + module

    result = check_involute_profile(module, z, alpha_deg)
    assert abs(result.r_pitch - expected_r_p) < 1e-9
    assert abs(result.r_base - expected_r_b) < 1e-9
    assert abs(result.r_tip - expected_r_a) < 1e-9


def test_horology_package_check_profile_re_export():
    """kerf_horology re-exports check_involute_profile and it works."""
    result = horology_check_profile(0.128, 15, 20.0)
    assert result.passed


# ---------------------------------------------------------------------------
# train_calculator tests — DoD criterion 3 (no kernel required)
# ---------------------------------------------------------------------------


def test_train_calculator_3hz_48h_ratio():
    """train_calculator ratio for 3 Hz + 48-hour reserve == 2304.0 (exact).

    This is the primary DoD reference test.

    Derivation:
        R = (freq_hz × 86400) / (escape_wheel_teeth × barrel_turns_per_day)
          = (3 × 86400) / (15 × 7.5)
          = 259200 / 112.5
          = 2304.0
    """
    spec = compute_train_ratio(
        freq_hz=3.0,
        power_reserve_hours=48.0,
        escape_wheel_teeth=15,
        barrel_turns_per_day=7.5,
    )
    assert abs(spec.required_ratio - 2304.0) < 1e-6, (
        f"Expected ratio 2304.0, got {spec.required_ratio}"
    )


def test_train_calculator_3hz_48h_barrel_turns():
    """barrel_turns_stored for 48-hour reserve with 7.5 turns/day == 15.0."""
    spec = compute_train_ratio(3.0, 48.0, barrel_turns_per_day=7.5)
    assert abs(spec.barrel_turns_stored - 15.0) < 1e-9, (
        f"Expected 15.0 barrel turns stored, got {spec.barrel_turns_stored}"
    )


def test_train_calculator_ratio_formula_exact():
    """R = (freq × 86400) / (teeth × turns_per_day) holds exactly for
    several standard frequencies."""
    cases = [
        # freq_hz, escape_teeth, turns_per_day, expected_ratio
        (2.5, 15, 7.5, (2.5 * 86400) / (15 * 7.5)),    # 18 000 bph
        (3.0, 15, 7.5, 2304.0),                          # 21 600 bph
        (4.0, 15, 7.5, (4.0 * 86400) / (15 * 7.5)),     # 28 800 bph
        (5.0, 15, 7.5, (5.0 * 86400) / (15 * 7.5)),     # 36 000 bph
    ]
    for freq, teeth, tpd, expected in cases:
        spec = compute_train_ratio(freq, 48.0, escape_wheel_teeth=teeth,
                                   barrel_turns_per_day=tpd)
        assert abs(spec.required_ratio - expected) < 1e-6, (
            f"freq={freq}: expected {expected}, got {spec.required_ratio}"
        )


def test_train_calculator_3hz_48h_stages_product():
    """The product of the 3-stage integer ratios is within 5% of 2304."""
    spec = compute_train_ratio(3.0, 48.0)
    product = math.prod(s.ratio for s in spec.stages)
    assert abs(product - spec.required_ratio) / spec.required_ratio < 0.05, (
        f"Stage product {product:.4f} deviates from required "
        f"{spec.required_ratio:.4f} by more than 5%"
    )
    assert len(spec.stages) == 3


def test_train_calculator_stages_integer_teeth():
    """All factorised stages have integer wheel_teeth and pinion_leaves."""
    spec = compute_train_ratio(3.0, 48.0)
    for s in spec.stages:
        assert isinstance(s.wheel_teeth, int), f"wheel_teeth not int: {s.wheel_teeth}"
        assert isinstance(s.pinion_leaves, int), f"pinion_leaves not int: {s.pinion_leaves}"
        assert s.wheel_teeth >= 60
        assert 6 <= s.pinion_leaves <= 12


def test_train_calculator_power_reserve_independence():
    """Required ratio is independent of power reserve (only barrel_turns_stored changes)."""
    spec_48 = compute_train_ratio(3.0, 48.0)
    spec_72 = compute_train_ratio(3.0, 72.0)
    assert abs(spec_48.required_ratio - spec_72.required_ratio) < 1e-6, (
        "Required ratio changed with power reserve — should be constant"
    )
    assert abs(spec_72.barrel_turns_stored - spec_48.barrel_turns_stored * 1.5) < 1e-9


def test_train_calculator_tool_wrapper():
    """_train_calculator tool returns JSON-serialisable dict with correct ratio."""
    result = _train_calculator(3.0, 48.0)
    assert "required_ratio" in result
    assert abs(result["required_ratio"] - 2304.0) < 0.001
    assert "barrel_turns_stored" in result
    assert abs(result["barrel_turns_stored"] - 15.0) < 0.001
    assert len(result["stages"]) == 3


def test_check_tooth_profile_tool_wrapper():
    """_check_tooth_profile tool returns a passed=True result for valid inputs."""
    result = _check_tooth_profile(0.128, 15, 20.0)
    assert result["passed"] is True
    assert result["reasons"] == []
    assert result["r_base_mm"] > 0
    assert result["r_pitch_mm"] > result["r_base_mm"]
    assert result["r_tip_mm"] > result["r_pitch_mm"]


def test_horology_package_train_ratio_re_export():
    """kerf_horology re-exports compute_train_ratio and it computes correctly."""
    spec = horology_train_ratio(3.0, 48.0)
    assert abs(spec.required_ratio - 2304.0) < 1e-6


# ---------------------------------------------------------------------------
# Factorise ratio
# ---------------------------------------------------------------------------


def test_factorise_ratio_3_stages():
    """factorise_ratio(2304, 3) returns 3 stages whose product is close to 2304."""
    stages = factorise_ratio(2304.0, n_stages=3)
    assert len(stages) == 3
    product = math.prod(s.ratio for s in stages)
    assert abs(product - 2304.0) / 2304.0 < 0.05


def test_factorise_ratio_integer_teeth():
    """All stages from factorise_ratio have integer wheel/pinion counts."""
    stages = factorise_ratio(2304.0, n_stages=3)
    for s in stages:
        assert isinstance(s.wheel_teeth, int)
        assert isinstance(s.pinion_leaves, int)


# ---------------------------------------------------------------------------
# Volume formula tests (no kernel required)
# ---------------------------------------------------------------------------


def test_escape_wheel_volume_formula():
    """Declared volumes match annular-cylinder formula for escape wheels."""
    from kerf_partsgen.generators.horology import escape_wheel as ew_mod
    for row in ew_mod.SIZES:
        p = row["params"]
        outer_r = p["outer_diameter"] / 2.0
        bore_r = p["bore_diameter"] / 2.0
        h = p["thickness"]
        expected_vol = math.pi * (outer_r ** 2 - bore_r ** 2) * h
        declared_vol = row["expect"]["volume_mm3"]
        assert abs(declared_vol - expected_vol) < 0.001, (
            f"{row['size']}: declared vol {declared_vol} vs formula {expected_vol:.4f}"
        )


def test_pallet_fork_volume_formula():
    """Declared volumes match L×W×T box formula for pallet forks."""
    from kerf_partsgen.generators.horology import pallet_fork as pf_mod
    for row in pf_mod.SIZES:
        p = row["params"]
        expected_vol = p["length"] * p["width"] * p["thickness"]
        declared_vol = row["expect"]["volume_mm3"]
        assert abs(declared_vol - expected_vol) < 0.001, (
            f"{row['size']}: declared vol {declared_vol} vs formula {expected_vol:.4f}"
        )


# ---------------------------------------------------------------------------
# Kernel-gated geometry tests (cadquery / OCCT required)
# ---------------------------------------------------------------------------


@needs_kernel
def test_escape_wheel_builds_valid_solids():
    """build() returns valid, non-degenerate solids for all escape wheel sizes."""
    from kerf_partsgen.generators.horology import escape_wheel as ew_mod
    for row in ew_mod.SIZES:
        built = ew_mod.build(row)
        assert built.is_valid, f"{row['size']}: kernel reports invalid solid"
        assert built.volume_mm3 > 0.0, f"{row['size']}: non-positive volume"


@needs_kernel
def test_pallet_fork_builds_valid_solids():
    """build() returns valid, non-degenerate solids for all pallet fork sizes."""
    from kerf_partsgen.generators.horology import pallet_fork as pf_mod
    for row in pf_mod.SIZES:
        built = pf_mod.build(row)
        assert built.is_valid, f"{row['size']}: kernel reports invalid solid"
        assert built.volume_mm3 > 0.0, f"{row['size']}: non-positive volume"


@needs_kernel
def test_gear_train_wheel_builds_valid_solids():
    """build() returns valid, non-degenerate solids for all gear-train wheel sizes."""
    from kerf_partsgen.generators.horology import gear_train as gt_mod
    for row in gt_mod.SIZES:
        built = gt_mod.build(row)
        assert built.is_valid, f"{row['size']}: kernel reports invalid solid"
        assert built.volume_mm3 > 0.0, f"{row['size']}: non-positive volume"


@needs_kernel
def test_mainspring_barrel_builds_valid_solids():
    """build() returns valid, non-degenerate solids for all mainspring barrel sizes."""
    from kerf_partsgen.generators.horology import mainspring_barrel as mb_mod
    for row in mb_mod.SIZES:
        built = mb_mod.build(row)
        assert built.is_valid, f"{row['size']}: kernel reports invalid solid"
        assert built.volume_mm3 > 0.0, f"{row['size']}: non-positive volume"
