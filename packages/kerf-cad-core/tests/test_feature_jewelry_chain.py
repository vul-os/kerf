"""
test_feature_jewelry_chain.py — T-5 hermetic pytest suite
==========================================================

Scope: kerf_cad_core.jewelry.chain — parametric chain / bracelet builder.

Success criteria (from testing-breakdown.md T-5):
  - 25 link styles × lengths; total length matches input ±1 link pitch
  - Per-link non-intersection (wire gauge vs link inner cavity)
  - Boundary / malformed / idempotency cases

All tests are pure-Python — no OCC, no DB, no network.
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.jewelry.chain import (
    _VALID_LINK_STYLES,
    _VALID_CLASP_STYLES,
    _STANDARD_LENGTHS_MM,
    _STYLE_ALIASES,
    GAUGE_PRESETS,
    compute_chain_params,
    compute_clasp_params,
    chain_length_to_link_count,
    link_count_to_chain_length,
    link_pitch,
    standard_length_names,
    chain_weight_estimate,
)

# ---------------------------------------------------------------------------
# Parametric matrix — 25 style × length combinations
# ---------------------------------------------------------------------------
# 5 styles × 5 standard lengths = 25 combinations.
# Chosen to span all link-style families (ring, flat-plate, bead, woven, rope)
# and standard length categories (bracelet, anklet, choker, princess, men's).

_STYLES_5 = ["cable", "curb", "byzantine", "rolo", "herringbone"]
_STANDARD_LENGTHS_5 = [
    "bracelet_7in",
    "anklet_10in",
    "choker_14in",
    "princess_18in",
    "mens_24in",
]
_GAUGE_MM = 1.0  # nominal wire gauge for the matrix tests


@pytest.mark.parametrize("style,std_len", [
    (style, length)
    for style in _STYLES_5
    for length in _STANDARD_LENGTHS_5
])
def test_total_length_within_one_pitch(style: str, std_len: str):
    """Total length returned must equal link_count × link_pitch (exact),
    and the actual total must be within ±1 link pitch of the target length
    (spec tolerance: ±1 link pitch)."""
    target_mm = _STANDARD_LENGTHS_MM[std_len]
    p = compute_chain_params(style, wire_gauge_mm=_GAUGE_MM, standard_length=std_len)

    # Internal consistency: total_length_mm == link_count × link_pitch_mm
    assert abs(p["total_length_mm"] - p["link_count"] * p["link_pitch_mm"]) < 1e-3, (
        f"{style}/{std_len}: total_length_mm inconsistent with link_count × pitch"
    )

    # Spec criterion: within ±1 link pitch of the target
    tolerance = p["link_pitch_mm"]
    delta = abs(p["total_length_mm"] - target_mm)
    assert delta <= tolerance + 1e-6, (
        f"{style}/{std_len}: |actual({p['total_length_mm']:.3f}) - target({target_mm})| "
        f"= {delta:.3f} > 1 pitch ({tolerance:.3f})"
    )


@pytest.mark.parametrize("style,std_len", [
    (style, length)
    for style in _STYLES_5
    for length in _STANDARD_LENGTHS_5
])
def test_per_link_non_intersection(style: str, std_len: str):
    """Per-link non-intersection: the wire gauge must fit inside the link inner
    cavity — i.e. link_length_mm and link_width_mm must each be ≥ wire_gauge_mm.
    Also link_pitch_mm ≥ wire_gauge_mm (no physical overlap along chain axis)."""
    p = compute_chain_params(style, wire_gauge_mm=_GAUGE_MM, standard_length=std_len)
    gauge = p["wire_gauge_mm"]

    assert p["link_length_mm"] >= gauge, (
        f"{style}/{std_len}: link_length_mm ({p['link_length_mm']}) < wire_gauge_mm ({gauge})"
    )
    assert p["link_width_mm"] >= gauge, (
        f"{style}/{std_len}: link_width_mm ({p['link_width_mm']}) < wire_gauge_mm ({gauge})"
    )
    assert p["link_pitch_mm"] >= gauge, (
        f"{style}/{std_len}: link_pitch_mm ({p['link_pitch_mm']}) < wire_gauge_mm ({gauge})"
    )


@pytest.mark.parametrize("style,std_len", [
    (style, length)
    for style in _STYLES_5
    for length in _STANDARD_LENGTHS_5
])
def test_link_count_positive(style: str, std_len: str):
    """link_count must be a positive integer for every style/length combo."""
    p = compute_chain_params(style, wire_gauge_mm=_GAUGE_MM, standard_length=std_len)
    assert isinstance(p["link_count"], int)
    assert p["link_count"] >= 1


@pytest.mark.parametrize("style,std_len", [
    (style, length)
    for style in _STYLES_5
    for length in _STANDARD_LENGTHS_5
])
def test_link_hints_has_type_key(style: str, std_len: str):
    """link_hints dict must carry a 'type' key for worker dispatch."""
    p = compute_chain_params(style, wire_gauge_mm=_GAUGE_MM, standard_length=std_len)
    assert "type" in p["link_hints"], (
        f"{style}/{std_len}: missing 'type' in link_hints"
    )
    assert p["link_hints"]["type"] == style


# ---------------------------------------------------------------------------
# All 16 canonical link styles — basic smoke (boundaries of valid input)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
def test_all_styles_produce_valid_spec(style: str):
    """Every canonical style must produce a valid spec from minimal inputs."""
    p = compute_chain_params(style, wire_gauge_mm=1.2, link_count=50)
    assert p["style"] == style
    assert p["link_count"] == 50
    assert p["link_length_mm"] > 0
    assert p["link_width_mm"] > 0
    assert p["link_pitch_mm"] > 0
    assert p["total_length_mm"] > 0
    assert p["wire_gauge_mm"] == pytest.approx(1.2)
    assert p["open_ends"] is True


@pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
def test_all_styles_total_length_source(style: str):
    """All styles accept total_length_mm as the length source."""
    target = 450.0
    p = compute_chain_params(style, wire_gauge_mm=1.0, total_length_mm=target)
    assert p["link_count"] >= 1
    # total must be consistent with link_count × pitch
    assert abs(p["total_length_mm"] - p["link_count"] * p["link_pitch_mm"]) < 1e-3


@pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
def test_all_styles_gauge_preset_medium(style: str):
    """gauge_preset='medium' must override wire_gauge_mm from the preset table."""
    p = compute_chain_params(style, wire_gauge_mm=99.0, gauge_preset="medium",
                             link_count=20)
    expected_gauge = GAUGE_PRESETS[style]["medium"]
    assert p["wire_gauge_mm"] == pytest.approx(expected_gauge)


# ---------------------------------------------------------------------------
# Boundary: minimum valid inputs
# ---------------------------------------------------------------------------

def test_minimum_link_count_one():
    """link_count=1 must produce a spec with a single link."""
    p = compute_chain_params("cable", wire_gauge_mm=1.0, link_count=1)
    assert p["link_count"] == 1
    assert p["total_length_mm"] == pytest.approx(p["link_pitch_mm"], rel=1e-6)


def test_minimum_total_length_rounds_up_to_one():
    """A very short total_length_mm must yield at least 1 link."""
    p = compute_chain_params("box", wire_gauge_mm=1.0, total_length_mm=0.001)
    assert p["link_count"] >= 1


def test_thin_gauge_0_1mm():
    """wire_gauge_mm=0.1 (delicate filigree) must succeed without error."""
    p = compute_chain_params("rope", wire_gauge_mm=0.1, link_count=200)
    assert p["wire_gauge_mm"] == pytest.approx(0.1)
    assert p["link_count"] == 200


def test_thick_gauge_19_9mm():
    """wire_gauge_mm=19.9 (near-limit) must succeed — 20.0 is the cutoff."""
    p = compute_chain_params("mariner", wire_gauge_mm=19.9, link_count=5)
    assert p["wire_gauge_mm"] == pytest.approx(19.9)


def test_large_link_count():
    """A large link_count (10 000) must not overflow and total_length must scale."""
    p = compute_chain_params("cable", wire_gauge_mm=0.5, link_count=10_000)
    assert p["link_count"] == 10_000
    assert p["total_length_mm"] > 1000.0


def test_explicit_link_dims_respected():
    """Explicit link_length_mm and link_width_mm must be stored in the spec."""
    p = compute_chain_params("curb", wire_gauge_mm=1.0, link_count=30,
                             link_length_mm=5.0, link_width_mm=3.5)
    assert p["link_length_mm"] == pytest.approx(5.0)
    assert p["link_width_mm"] == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Boundary: clasp sizing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("clasp_style", sorted(_VALID_CLASP_STYLES))
def test_all_clasps_produce_valid_spec(clasp_style: str):
    """Every clasp style must return a dict with 'op', 'style', 'clasp_hints'."""
    spec = compute_clasp_params(clasp_style, wire_gauge_mm=1.2)
    assert spec["op"] == "clasp"
    assert spec["style"] == clasp_style
    assert isinstance(spec["clasp_hints"], dict)
    assert spec["clasp_hints"]["type"] == clasp_style
    assert spec["wire_gauge_mm"] == pytest.approx(1.2)


def test_lobster_clasp_body_dimensions():
    """Lobster clasp: body_length > body_width (typical real geometry)."""
    spec = compute_clasp_params("lobster", wire_gauge_mm=1.0)
    h = spec["clasp_hints"]
    assert h["body_length_mm"] > h["body_width_mm"]


def test_spring_ring_outer_gt_inner():
    """Spring ring: outer diameter must exceed inner diameter."""
    spec = compute_clasp_params("spring_ring", wire_gauge_mm=1.0)
    h = spec["clasp_hints"]
    assert h["outer_diameter_mm"] > h["inner_diameter_mm"]


def test_toggle_bar_longer_than_ring_inner_diameter():
    """Toggle clasp: bar_length must exceed ring_inner_diameter for it to work."""
    spec = compute_clasp_params("toggle", wire_gauge_mm=1.0)
    h = spec["clasp_hints"]
    assert h["bar_length_mm"] > h["ring_inner_diameter_mm"]


def test_box_clasp_all_dims_positive():
    """Box clasp: all three body dimensions must be positive."""
    spec = compute_clasp_params("box_clasp", wire_gauge_mm=1.5)
    h = spec["clasp_hints"]
    assert h["box_length_mm"] > 0
    assert h["box_width_mm"] > 0
    assert h["box_height_mm"] > 0


# ---------------------------------------------------------------------------
# Boundary: length helpers
# ---------------------------------------------------------------------------

def test_chain_length_to_link_count_exact():
    """Dividing by pitch exactly gives the correct link count."""
    assert chain_length_to_link_count(180.0, 3.0) == 60


def test_link_count_to_chain_length_exact():
    """link_count × pitch must equal round-tripped total length."""
    assert link_count_to_chain_length(60, 3.0) == pytest.approx(180.0)


def test_round_trip_link_count_vs_length():
    """chain_length → link_count → chain_length must be within 1 pitch."""
    pitch = 2.8
    target = 457.2  # princess 18 in
    count = chain_length_to_link_count(target, pitch)
    back = link_count_to_chain_length(count, pitch)
    assert abs(back - target) <= pitch


def test_bracelet_7in_standard_length_value():
    """bracelet_7in standard length is defined as 177.8 mm (7 × 25.4)."""
    assert _STANDARD_LENGTHS_MM["bracelet_7in"] == pytest.approx(177.8)


def test_princess_18in_standard_length_value():
    """princess_18in standard length is defined as 457.2 mm."""
    assert _STANDARD_LENGTHS_MM["princess_18in"] == pytest.approx(457.2)


def test_all_standard_lengths_positive():
    """Every entry in _STANDARD_LENGTHS_MM must be > 0."""
    for name, mm in _STANDARD_LENGTHS_MM.items():
        assert mm > 0, f"{name!r}: expected > 0, got {mm}"


def test_standard_length_names_returns_sorted_list():
    """standard_length_names() must return a sorted list of strings."""
    names = standard_length_names()
    assert names == sorted(names)
    assert all(isinstance(n, str) for n in names)


# ---------------------------------------------------------------------------
# Boundary: weight estimator
# ---------------------------------------------------------------------------

_SILVER_DENSITY = 10.49   # g/cm³ — sterling silver approx
_GOLD_DENSITY = 19.3      # g/cm³ — pure gold approx


def test_weight_estimator_returns_positive():
    """chain_weight_estimate must return a positive float for valid inputs."""
    w = chain_weight_estimate("cable", 1.0, 177.8, _SILVER_DENSITY)
    assert w > 0.0


def test_weight_scales_linearly_with_length():
    """Doubling total_length_mm must roughly double the weight."""
    w1 = chain_weight_estimate("curb", 1.2, 200.0, _SILVER_DENSITY)
    w2 = chain_weight_estimate("curb", 1.2, 400.0, _SILVER_DENSITY)
    assert w2 == pytest.approx(w1 * 2, rel=0.05)


def test_weight_scales_with_density():
    """Higher metal density must produce higher weight (gold > silver)."""
    wg = chain_weight_estimate("cable", 1.0, 200.0, _GOLD_DENSITY)
    ws = chain_weight_estimate("cable", 1.0, 200.0, _SILVER_DENSITY)
    assert wg > ws


# ---------------------------------------------------------------------------
# Malformed inputs — must raise ValueError
# ---------------------------------------------------------------------------

def test_unknown_style_raises():
    with pytest.raises(ValueError, match="Unknown chain style"):
        compute_chain_params("nonexistent_style", wire_gauge_mm=1.0, link_count=10)


def test_zero_gauge_raises():
    with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
        compute_chain_params("cable", wire_gauge_mm=0.0, link_count=10)


def test_negative_gauge_raises():
    with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
        compute_chain_params("cable", wire_gauge_mm=-1.0, link_count=10)


def test_gauge_exceeds_20mm_raises():
    with pytest.raises(ValueError, match="unrealistically large"):
        compute_chain_params("cable", wire_gauge_mm=20.1, link_count=10)


def test_zero_link_length_raises():
    with pytest.raises(ValueError, match="link_length_mm must be > 0"):
        compute_chain_params("cable", wire_gauge_mm=1.0, link_count=10,
                             link_length_mm=0.0)


def test_link_length_less_than_gauge_raises():
    with pytest.raises(ValueError):
        compute_chain_params("cable", wire_gauge_mm=2.0, link_count=10,
                             link_length_mm=1.0)


def test_link_width_less_than_gauge_raises():
    with pytest.raises(ValueError):
        compute_chain_params("cable", wire_gauge_mm=2.0, link_count=10,
                             link_length_mm=10.0, link_width_mm=1.0)


def test_no_length_source_raises():
    with pytest.raises(ValueError, match="One of link_count"):
        compute_chain_params("cable", wire_gauge_mm=1.0)


def test_two_length_sources_raises():
    with pytest.raises(ValueError, match="exactly one"):
        compute_chain_params("cable", wire_gauge_mm=1.0,
                             link_count=10, total_length_mm=200.0)


def test_all_three_length_sources_raises():
    with pytest.raises(ValueError, match="exactly one"):
        compute_chain_params("cable", wire_gauge_mm=1.0,
                             link_count=10, total_length_mm=200.0,
                             standard_length="bracelet_7in")


def test_zero_total_length_raises():
    with pytest.raises(ValueError, match="total_length_mm must be > 0"):
        compute_chain_params("cable", wire_gauge_mm=1.0, total_length_mm=0.0)


def test_negative_total_length_raises():
    with pytest.raises(ValueError, match="total_length_mm must be > 0"):
        compute_chain_params("cable", wire_gauge_mm=1.0, total_length_mm=-10.0)


def test_zero_link_count_raises():
    with pytest.raises(ValueError, match="positive integer"):
        compute_chain_params("cable", wire_gauge_mm=1.0, link_count=0)


def test_negative_link_count_raises():
    with pytest.raises(ValueError, match="positive integer"):
        compute_chain_params("cable", wire_gauge_mm=1.0, link_count=-5)


def test_unknown_standard_length_raises():
    with pytest.raises(ValueError, match="Unknown standard_length"):
        compute_chain_params("cable", wire_gauge_mm=1.0,
                             standard_length="nonexistent_42in")


def test_unknown_clasp_style_raises():
    with pytest.raises(ValueError, match="Unknown clasp style"):
        compute_clasp_params("mystery_clasp", wire_gauge_mm=1.0)


def test_clasp_zero_gauge_raises():
    with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
        compute_clasp_params("lobster", wire_gauge_mm=0.0)


def test_invalid_gauge_preset_raises():
    with pytest.raises(ValueError, match="Unknown gauge_preset"):
        compute_chain_params("cable", wire_gauge_mm=1.0, link_count=10,
                             gauge_preset="ultra_thin")


def test_chain_length_to_link_count_zero_length_raises():
    with pytest.raises(ValueError, match="total_length_mm must be > 0"):
        chain_length_to_link_count(0.0, 3.0)


def test_chain_length_to_link_count_zero_pitch_raises():
    with pytest.raises(ValueError, match="link_pitch_mm must be > 0"):
        chain_length_to_link_count(100.0, 0.0)


def test_link_count_to_chain_length_zero_count_raises():
    with pytest.raises(ValueError, match="link_count must be >= 1"):
        link_count_to_chain_length(0, 3.0)


def test_link_count_to_chain_length_zero_pitch_raises():
    with pytest.raises(ValueError, match="link_pitch_mm must be > 0"):
        link_count_to_chain_length(10, 0.0)


def test_weight_estimate_zero_gauge_raises():
    with pytest.raises(ValueError):
        chain_weight_estimate("cable", 0.0, 200.0, _SILVER_DENSITY)


def test_weight_estimate_zero_length_raises():
    with pytest.raises(ValueError):
        chain_weight_estimate("cable", 1.0, 0.0, _SILVER_DENSITY)


def test_weight_estimate_invalid_style_raises():
    with pytest.raises(ValueError):
        chain_weight_estimate("imaginary_style", 1.0, 200.0, _SILVER_DENSITY)


# ---------------------------------------------------------------------------
# Style aliases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alias,canonical", sorted(_STYLE_ALIASES.items()))
def test_alias_resolves_to_canonical_style(alias: str, canonical: str):
    """Alias must be accepted and spec['style'] must equal the canonical name."""
    # diamond_cut_curb alias needs special treatment (becomes curb)
    p = compute_chain_params(alias, wire_gauge_mm=1.0, link_count=20)
    assert p["style"] == canonical


# ---------------------------------------------------------------------------
# Idempotency: same inputs → identical outputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("style", ["cable", "rope", "byzantine", "omega", "ball"])
def test_idempotent_link_count(style: str):
    """Calling compute_chain_params twice with the same args must return
    identical dicts (no random state, no mutation)."""
    kwargs = dict(wire_gauge_mm=1.1, link_count=80)
    p1 = compute_chain_params(style, **kwargs)
    p2 = compute_chain_params(style, **kwargs)
    # Compare field by field for clear failure messages
    for key in ("style", "wire_gauge_mm", "link_count", "link_length_mm",
                "link_width_mm", "link_pitch_mm", "total_length_mm", "open_ends"):
        assert p1[key] == p2[key], f"{style}: field {key!r} not idempotent"
    assert p1["link_hints"] == p2["link_hints"], f"{style}: link_hints not idempotent"


@pytest.mark.parametrize("style", ["cable", "rope", "byzantine", "omega", "ball"])
def test_idempotent_standard_length(style: str):
    """standard_length path must also be idempotent."""
    kwargs = dict(wire_gauge_mm=1.0, standard_length="bracelet_7in")
    p1 = compute_chain_params(style, **kwargs)
    p2 = compute_chain_params(style, **kwargs)
    assert p1["link_count"] == p2["link_count"]
    assert p1["total_length_mm"] == p2["total_length_mm"]


# ---------------------------------------------------------------------------
# Style-specific boundary checks
# ---------------------------------------------------------------------------

def test_figaro_long_link_ratio_stored():
    """Figaro hints must carry the long_link_ratio in the pattern list."""
    p = compute_chain_params("figaro", wire_gauge_mm=1.0, link_count=40,
                             long_link_ratio=3.0)
    pattern = p["link_hints"]["pattern"]
    assert 3.0 in pattern


def test_byzantine_cluster_links_count():
    """Byzantine hints must specify cluster_links."""
    p = compute_chain_params("byzantine", wire_gauge_mm=1.0, link_count=20)
    assert p["link_hints"]["cluster_links"] == 4


def test_bismark_rows_custom():
    """Bismark 3-row config must store rows=3 in link_hints."""
    p = compute_chain_params("bismark", wire_gauge_mm=1.0, link_count=30, rows=3)
    assert p["link_hints"]["rows"] == 3


def test_bismark_rows_default_two():
    """Bismark default must use rows=2."""
    p = compute_chain_params("bismark", wire_gauge_mm=1.0, link_count=30)
    assert p["link_hints"]["rows"] == 2


def test_rope_twist_angle_stored():
    """Custom twist_angle_deg for rope must be reflected in link_hints."""
    p = compute_chain_params("rope", wire_gauge_mm=0.9, link_count=60,
                             twist_angle_deg=30.0)
    assert p["link_hints"]["twist_angle_deg"] == pytest.approx(30.0)


def test_curb_diamond_cut_hint():
    """diamond_cut=True must set diamond_cut=True and add diamond_facets in hints."""
    p = compute_chain_params("curb", wire_gauge_mm=1.2, link_count=40,
                             diamond_cut=True)
    h = p["link_hints"]
    assert h["diamond_cut"] is True
    assert "diamond_facets" in h


def test_curb_flat_hint():
    """flat=True must set flat_face=True and add flat_ratio in hints."""
    p = compute_chain_params("curb", wire_gauge_mm=1.2, link_count=40, flat=True)
    h = p["link_hints"]
    assert h["flat_face"] is True
    assert "flat_ratio" in h


def test_graduated_flag_stored():
    """graduated=True must be present in the spec dict."""
    p = compute_chain_params("cable", wire_gauge_mm=1.0, link_count=50,
                             graduated=True)
    assert p.get("graduated") is True


def test_graduated_false_not_stored():
    """graduated=False (default) must not appear in the spec dict."""
    p = compute_chain_params("cable", wire_gauge_mm=1.0, link_count=50)
    assert "graduated" not in p


def test_omega_plate_width_wider_than_gauge():
    """Omega hints must have plate_width_mm > wire_gauge_mm (characteristic width)."""
    p = compute_chain_params("omega", wire_gauge_mm=1.5, link_count=25)
    assert p["link_hints"]["plate_width_mm"] > p["wire_gauge_mm"]


def test_herringbone_layer_count():
    """Herringbone hints must carry layer_count = 2 (classic doubled layer)."""
    p = compute_chain_params("herringbone", wire_gauge_mm=1.0, link_count=30)
    assert p["link_hints"]["layer_count"] == 2


def test_rolo_inner_diameter_positive():
    """Rolo hints must have inner_diameter_mm > 0."""
    p = compute_chain_params("rolo", wire_gauge_mm=1.0, link_count=40)
    assert p["link_hints"]["inner_diameter_mm"] > 0


def test_ball_bead_diameter_positive():
    """Ball/bead-chain hints must have bead_diameter_mm > 0."""
    p = compute_chain_params("ball", wire_gauge_mm=1.0, link_count=50)
    assert p["link_hints"]["bead_diameter_mm"] > 0


def test_mariner_has_central_bar():
    """Mariner (anchor) hints must flag central_bar=True."""
    p = compute_chain_params("mariner", wire_gauge_mm=1.0, link_count=30)
    assert p["link_hints"]["central_bar"] is True


# ---------------------------------------------------------------------------
# Gauge-preset combinations (fine / medium / heavy across all styles)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("preset", ["fine", "medium", "heavy"])
@pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
def test_gauge_preset_sets_expected_wire_gauge(preset: str, style: str):
    """gauge_preset must set wire_gauge_mm to the GAUGE_PRESETS[style][preset] value."""
    p = compute_chain_params(style, wire_gauge_mm=0.0001,  # will be overridden
                             gauge_preset=preset, link_count=10)
    assert p["wire_gauge_mm"] == pytest.approx(GAUGE_PRESETS[style][preset])


@pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
def test_fine_gauge_less_than_heavy(style: str):
    """fine gauge must be strictly less than heavy gauge for every style."""
    assert GAUGE_PRESETS[style]["fine"] < GAUGE_PRESETS[style]["heavy"]


# ---------------------------------------------------------------------------
# link_pitch helper — direct tests
# ---------------------------------------------------------------------------

def test_link_pitch_cable_equals_inner_length():
    """Cable pitch = link_length - 2×gauge (inner length), no special case."""
    ll, lw, gauge = 3.5, 2.5, 1.0
    expected_inner = ll - 2.0 * gauge
    pitch = link_pitch("cable", ll, lw, gauge)
    assert pitch == pytest.approx(expected_inner)


def test_link_pitch_box_is_half_link_length():
    """Box pitch is link_length × 0.5 (alternating overlap)."""
    ll, lw, gauge = 4.0, 4.0, 1.0
    pitch = link_pitch("box", ll, lw, gauge)
    assert pitch == pytest.approx(ll * 0.5)


def test_link_pitch_never_less_than_gauge():
    """For any style, pitch must be ≥ wire_gauge_mm (physical non-overlap)."""
    gauge = 1.0
    for style in _VALID_LINK_STYLES:
        ll = gauge * 2.5
        lw = gauge * 2.0
        p = link_pitch(style, ll, lw, gauge)
        assert p >= gauge, f"{style}: pitch {p} < gauge {gauge}"
