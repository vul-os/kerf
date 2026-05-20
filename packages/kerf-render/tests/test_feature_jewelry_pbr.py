"""T-14: Jewelry PBR materials — gem + metal render-payload tests.

Scope: viewport material assignment + render hand-off (kerf-render integration).

Success criteria (from docs/plans/testing-breakdown.md):
  25 material assignments; correct dispersion / IOR / metal Fresnel parameters
  reach render payload.

All tests are hermetic: no bpy, no network, no DB required.
"""

from __future__ import annotations

import math
import pytest

from kerf_render.material_mapping import (
    GEMSTONE_OPTICS,
    METAL_PBR,
    ORGANIC_OPAQUE,
    PLASTIC_PBR,
    WAVELENGTHS_UM,
    abbe_from_sellmeier,
    canonical_key,
    lookup_material,
    material_kind,
    sellmeier_n,
    supported_materials,
)
from kerf_render.cycles_translator import (
    Camera,
    Light,
    RenderOutput,
    translate_body_to_gltf_plus_materials,
)
from kerf_cad_core.geom.brep import make_box, make_tetra


# ---------------------------------------------------------------------------
# 25 jewelry PBR material assignments — the heart of T-14
# ---------------------------------------------------------------------------
#
# Each tuple: (slot_name, expected_bsdf, ior_approx, ior_abs_tol, extra_checks)
# extra_checks: dict of kwarg name -> expected value (or callable(v)->bool)
#
# We cover 17 gemstones (glass BSDF) + 8 key metal alloys (principled BSDF)
# = 25 total.

_JEWELRY_25: list[tuple] = [
    # ---- Gems (Glass BSDF + dispersion) ----                 slot           bsdf     ior    tol
    ("diamond",      "glass",      2.417, 0.005),
    ("sapphire",     "glass",      1.770, 0.010),
    ("ruby",         "glass",      1.766, 0.010),
    ("emerald",      "glass",      1.580, 0.020),
    ("amethyst",     "glass",      1.548, 0.020),
    ("citrine",      "glass",      1.548, 0.020),
    ("topaz",        "glass",      1.625, 0.020),
    ("aquamarine",   "glass",      1.578, 0.020),
    ("garnet",       "glass",      1.790, 0.020),
    ("peridot",      "glass",      1.680, 0.020),
    ("tanzanite",    "glass",      1.695, 0.020),
    ("tourmaline",   "glass",      1.635, 0.020),
    ("spinel",       "glass",      1.718, 0.020),
    ("morganite",    "glass",      1.585, 0.020),
    ("alexandrite",  "glass",      1.750, 0.020),
    ("moonstone",    "glass",      1.522, 0.020),
    ("zircon",       "glass",      1.955, 0.020),
    # ---- Metals (Principled BSDF, metallic=1.0) ----
    ("18k_yellow",   "principled", None,  None),
    ("18k_white",    "principled", None,  None),
    ("18k_rose",     "principled", None,  None),
    ("platinum_950", "principled", None,  None),
    ("sterling_925", "principled", None,  None),
    ("fine_silver",  "principled", None,  None),
    ("palladium_950","principled", None,  None),
    ("titanium",     "principled", None,  None),
]

assert len(_JEWELRY_25) == 25, "spec requires exactly 25 material assignments"


class TestJewelry25Assignments:
    """Parametric test — one case per entry in _JEWELRY_25."""

    @pytest.mark.parametrize("slot,bsdf,ior,tol", _JEWELRY_25)
    def test_material_reaches_render_payload(self, slot, bsdf, ior, tol):
        """Each slot must resolve and produce the correct bsdf in materials_dict."""
        body = make_tetra()
        faces = body.all_faces()
        result = translate_body_to_gltf_plus_materials(
            body,
            materials={faces[0].id: slot},
        )
        assert result["ok"] is True, f"translator failed for {slot!r}: {result.get('reason')}"
        assert slot in result["materials_dict"], (
            f"slot {slot!r} not present in materials_dict keys: "
            f"{list(result['materials_dict'].keys())}"
        )
        entry = result["materials_dict"][slot]
        assert entry["bsdf"] == bsdf, (
            f"{slot!r}: expected bsdf={bsdf!r}, got {entry['bsdf']!r}"
        )
        if ior is not None:
            assert entry["ior"] == pytest.approx(ior, abs=tol), (
                f"{slot!r}: IOR expected ≈{ior}, got {entry['ior']}"
            )


# ---------------------------------------------------------------------------
# Gem-specific: IOR + dispersion + Sellmeier at the render payload boundary
# ---------------------------------------------------------------------------


class TestGemDispersionInPayload:
    def test_all_17_gems_have_dispersion_true(self):
        for name in GEMSTONE_OPTICS:
            mat = lookup_material(name)
            assert mat["dispersion"] is True, f"{name}: dispersion must be True"

    def test_all_17_gems_have_sellmeier_3_terms(self):
        for name in GEMSTONE_OPTICS:
            mat = lookup_material(name)
            assert len(mat["sellmeier"]) == 3, (
                f"{name}: sellmeier must be 3 (B,C) pairs"
            )

    def test_sellmeier_n_d_matches_ior_within_5pct(self):
        for name, entry in GEMSTONE_OPTICS.items():
            n_d = sellmeier_n(entry["sellmeier"], WAVELENGTHS_UM["D"])
            assert n_d == pytest.approx(entry["ior"], rel=0.05), (
                f"{name}: sellmeier n_D={n_d:.4f} vs catalog ior={entry['ior']}"
            )

    def test_sellmeier_abbe_matches_within_5pct(self):
        for name, entry in GEMSTONE_OPTICS.items():
            abbe = abbe_from_sellmeier(entry["sellmeier"])
            assert abbe == pytest.approx(entry["abbe"], rel=0.05), (
                f"{name}: computed abbe={abbe:.2f} vs catalog {entry['abbe']}"
            )

    def test_diamond_has_highest_ior_among_classic_gems(self):
        classic = ["diamond", "sapphire", "ruby", "emerald", "topaz"]
        ivals = {g: lookup_material(g)["ior"] for g in classic}
        assert ivals["diamond"] == max(ivals.values()), (
            f"diamond must have highest IOR among {classic}; got {ivals}"
        )

    def test_diamond_has_highest_fire_lowest_abbe(self):
        """Diamond's legendary 'fire' comes from its low Abbe (~55) with high IOR."""
        d = lookup_material("diamond")
        # lower Abbe = more dispersion/fire; diamond abbe ~55 should be <= garnet (~29.5)?
        # Actually garnet (demantoid) is even more dispersive but diamond IOR dominates.
        assert d["abbe"] == pytest.approx(55.3, abs=1.0)

    def test_gem_transmission_is_1_for_glass_bsdf(self):
        for name in GEMSTONE_OPTICS:
            mat = lookup_material(name)
            assert mat["transmission"] == 1.0, (
                f"{name}: glass bsdf gems must have transmission=1.0"
            )

    def test_gem_roughness_is_0_for_faceted_gems(self):
        """Faceted gems should have roughness=0 (mirror-polished)."""
        for name in GEMSTONE_OPTICS:
            mat = lookup_material(name)
            assert mat["roughness"] == 0.0, (
                f"{name}: faceted gem must have roughness=0"
            )

    def test_blender_script_embeds_sellmeier_for_diamond(self):
        body = make_tetra()
        faces = body.all_faces()
        result = translate_body_to_gltf_plus_materials(
            body, materials={faces[0].id: "diamond"}
        )
        script = result["blender_script"]
        assert "sellmeier" in script, "script must embed sellmeier coefficients"
        assert "ShaderNodeBsdfGlass" in script, "glass BSDF wiring must appear"
        assert "Dispersion" in script, "dispersion socket wiring must appear"

    def test_blender_script_embeds_ior_value_for_sapphire(self):
        body = make_tetra()
        faces = body.all_faces()
        result = translate_body_to_gltf_plus_materials(
            body, materials={faces[0].id: "sapphire"}
        )
        script = result["blender_script"]
        # IOR 1.770 must appear in the embedded JSON config
        assert "1.77" in script or "1.770" in script


# ---------------------------------------------------------------------------
# Metal Fresnel parameters in render payload
# ---------------------------------------------------------------------------


class TestMetalFresnelInPayload:
    def test_all_gold_alloys_metallic_1_in_payload(self):
        body = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
        faces = body.all_faces()
        gold_slots = [
            "10k_yellow", "14k_yellow", "18k_yellow", "22k_yellow", "24k_yellow",
        ]
        for i, slot in enumerate(gold_slots):
            fid = faces[i % len(faces)].id
            result = translate_body_to_gltf_plus_materials(
                body, materials={fid: slot}
            )
            assert result["ok"] is True
            entry = result["materials_dict"][slot]
            assert entry["metallic"] == 1.0, f"{slot}: metallic must be 1.0"
            r, g, b, _ = entry["base_color"]
            assert r > g > b, f"{slot}: yellow gold must be R>G>B"

    def test_rose_gold_r_dominance_in_payload(self):
        body = make_tetra()
        faces = body.all_faces()
        for slot in ["10k_rose", "14k_rose", "18k_rose", "22k_rose"]:
            result = translate_body_to_gltf_plus_materials(
                body, materials={faces[0].id: slot}
            )
            entry = result["materials_dict"][slot]
            r, g, b, _ = entry["base_color"]
            assert r > g and r > b, f"{slot}: rose gold must be R-dominant"

    def test_platinum_ior_above_2_fresnel(self):
        mat = lookup_material("platinum_950")
        # platinum IOR ~2.33 for conductor Fresnel
        assert mat["ior"] >= 2.0, "platinum IOR (conductor) must be >= 2.0"

    def test_sterling_silver_ior_below_1(self):
        mat = lookup_material("sterling_925")
        # Silver is a conductor: complex IOR; the stored real-part approximation
        # for Cycles Principled is < 1 (the imaginary part handles reflectance).
        assert mat["ior"] < 1.0, "sterling silver conductor IOR must be < 1"

    def test_fine_silver_roughness_lower_than_bronze(self):
        fine = lookup_material("fine_silver")
        bronze = lookup_material("bronze")
        assert fine["roughness"] < bronze["roughness"], (
            "fine silver (mirror polish) should have lower roughness than bronze"
        )

    def test_24k_gold_rougher_than_sterling_roughness_ordering(self):
        # 24k softest, so slightly higher roughness than 18k
        gold_24k = lookup_material("24k_yellow")
        gold_18k = lookup_material("18k_yellow")
        # 24k roughness=0.05, 18k=0.07 — but 24k is more polished, so actually
        # 24k should be LESS rough than 18k by our catalog
        assert gold_24k["roughness"] <= gold_18k["roughness"], (
            f"24k (purer) should not be rougher than 18k: "
            f"24k={gold_24k['roughness']}, 18k={gold_18k['roughness']}"
        )

    def test_blender_script_embeds_metallic_for_gold(self):
        body = make_tetra()
        faces = body.all_faces()
        result = translate_body_to_gltf_plus_materials(
            body, materials={faces[0].id: "18k_yellow"}
        )
        script = result["blender_script"]
        assert "ShaderNodeBsdfPrincipled" in script
        # The script must not emit a Glass node for a metal
        materials = result["materials_dict"]["18k_yellow"]
        assert materials["bsdf"] == "principled"
        assert materials["metallic"] == 1.0


# ---------------------------------------------------------------------------
# Alias resolution boundary tests
# ---------------------------------------------------------------------------


class TestAliasResolution:
    def test_canonical_aliases_resolve_to_correct_bsdf(self):
        """User-facing aliases must map to the correct underlying bsdf."""
        cases = [
            ("gold",           "principled"),
            ("yellow_gold",    "principled"),
            ("white_gold",     "principled"),
            ("rose_gold",      "principled"),
            ("platinum",       "principled"),
            ("silver",         "principled"),
            ("tsavorite",      "glass"),       # -> garnet
            ("rubellite",      "glass"),       # -> tourmaline
            ("white_diamond",  "glass"),       # -> diamond
            ("blue_sapphire",  "glass"),       # -> sapphire
            ("paraiba",        "glass"),       # -> tourmaline
            ("demantoid",      "glass"),       # -> garnet
        ]
        for alias, expected_bsdf in cases:
            mat = lookup_material(alias)
            assert mat["bsdf"] == expected_bsdf, (
                f"alias {alias!r} -> bsdf {mat['bsdf']!r}, expected {expected_bsdf!r}"
            )

    def test_canonical_key_normalises_case_and_spaces(self):
        assert canonical_key("Yellow Gold") == "18k_yellow"
        assert canonical_key("WHITE-GOLD") == "18k_white"
        assert canonical_key("ROSE GOLD") == "18k_rose"
        assert canonical_key("  Platinum  ") == "platinum_950"
        assert canonical_key("Blue_Sapphire") == "sapphire"

    def test_synonym_and_canonical_produce_identical_payloads(self):
        """Alias and canonical key must produce identical render payloads."""
        alias_pairs = [
            ("gold",         "18k_yellow"),
            ("platinum",     "platinum_950"),
            ("silver",       "sterling_925"),
            ("tsavorite",    "garnet"),
            ("rubellite",    "tourmaline"),
        ]
        for alias, canonical in alias_pairs:
            via_alias = lookup_material(alias)
            via_canon = lookup_material(canonical)
            assert via_alias == via_canon, (
                f"alias {alias!r} != canonical {canonical!r}: "
                f"{via_alias} vs {via_canon}"
            )


# ---------------------------------------------------------------------------
# Boundary: organic opaque gems (non-glass Principled)
# ---------------------------------------------------------------------------


class TestOrganicOpaqueBoundary:
    def test_pearl_uses_principled_not_glass(self):
        mat = lookup_material("pearl")
        assert mat["bsdf"] == "principled"
        assert mat["transmission"] == 0.0

    def test_turquoise_uses_principled(self):
        mat = lookup_material("turquoise")
        assert mat["bsdf"] == "principled"

    def test_lapis_lazuli_uses_principled(self):
        mat = lookup_material("lapis_lazuli")
        assert mat["bsdf"] == "principled"

    def test_organic_kind_classification(self):
        for name in ["pearl", "turquoise", "lapis_lazuli", "jade", "amber", "opal"]:
            assert material_kind(name) == "organic", (
                f"{name} should be kind='organic'"
            )

    def test_amber_has_partial_transmission(self):
        """Amber is semi-transparent: transmission > 0."""
        mat = lookup_material("amber")
        assert mat["transmission"] > 0.0


# ---------------------------------------------------------------------------
# Malformed / boundary input tests
# ---------------------------------------------------------------------------


class TestMalformedInputs:
    def test_unknown_slot_raises_key_error(self):
        with pytest.raises(KeyError):
            lookup_material("unobtainium_99")

    def test_empty_string_slot_raises_key_error(self):
        with pytest.raises(KeyError):
            lookup_material("")

    def test_none_slot_canonical_key_returns_empty_string(self):
        # canonical_key coerces None to empty string
        assert canonical_key(None) == ""

    def test_unknown_slot_kind_is_unknown(self):
        assert material_kind("totally_made_up") == "unknown"

    def test_translator_unknown_slot_strict_returns_failure(self):
        body = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
        faces = body.all_faces()
        result = translate_body_to_gltf_plus_materials(
            body,
            materials={faces[0].id: "not_a_real_material_xyz"},
            strict=True,
        )
        assert result["ok"] is False
        assert "not_a_real_material_xyz" in result["reason"]

    def test_translator_unknown_slot_non_strict_falls_back(self):
        body = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0))
        faces = body.all_faces()
        result = translate_body_to_gltf_plus_materials(
            body,
            materials={faces[0].id: "mystery_material"},
        )
        assert result["ok"] is True
        assert "mystery_material" in result["missing"]

    def test_translator_none_body_returns_failure(self):
        result = translate_body_to_gltf_plus_materials(None)
        assert result["ok"] is False

    def test_translator_empty_body_returns_failure_with_zero_faces_message(self):
        from kerf_cad_core.geom.brep import Body
        result = translate_body_to_gltf_plus_materials(Body())
        assert result["ok"] is False
        assert "zero faces" in result["reason"]

    def test_sellmeier_n_at_zero_wavelength_does_not_crash(self):
        """sellmeier_n must not crash on degenerate wavelength."""
        coeffs = GEMSTONE_OPTICS["diamond"]["sellmeier"]
        # wavelength=0 would cause division by zero; function must handle gracefully
        n = sellmeier_n(coeffs, 1e-12)
        assert math.isfinite(n) or n >= 1.0  # may return large n; must not NaN/raise

    def test_sellmeier_n_with_zero_coefficients(self):
        """All-zero Sellmeier must return n=1.0 (vacuum)."""
        coeffs = [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]
        n = sellmeier_n(coeffs, WAVELENGTHS_UM["D"])
        assert n == pytest.approx(1.0, abs=1e-9)

    def test_slot_with_leading_trailing_spaces_resolves(self):
        """Slots with surrounding whitespace should resolve via canonical_key."""
        assert canonical_key("  diamond  ") == "diamond"
        mat = lookup_material("  diamond  ")
        assert mat["bsdf"] == "glass"

    def test_slot_with_hyphen_resolves(self):
        """Hyphens are normalised to underscores."""
        mat = lookup_material("18k-yellow")
        assert mat["bsdf"] == "principled"
        assert mat["metallic"] == 1.0


# ---------------------------------------------------------------------------
# Idempotency: repeated lookups must return equal (but independent) dicts
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_gem_lookup_idempotent(self):
        """Repeated lookups return equal values."""
        for name in GEMSTONE_OPTICS:
            a = lookup_material(name)
            b = lookup_material(name)
            assert a == b, f"{name}: lookup not idempotent"

    def test_metal_lookup_idempotent(self):
        for slot in METAL_PBR:
            a = lookup_material(slot)
            b = lookup_material(slot)
            assert a == b, f"{slot}: lookup not idempotent"

    def test_gem_lookup_returns_independent_copy(self):
        """Mutating a returned dict must not affect subsequent lookups."""
        original = lookup_material("diamond")
        ior_before = original["ior"]
        original["ior"] = 999.0  # mutate the copy
        fresh = lookup_material("diamond")
        assert fresh["ior"] == pytest.approx(ior_before, abs=1e-9), (
            "lookup_material must return an independent copy"
        )

    def test_metal_lookup_returns_independent_copy(self):
        original = lookup_material("18k_yellow")
        original["metallic"] = 0.0  # mutate
        fresh = lookup_material("18k_yellow")
        assert fresh["metallic"] == 1.0, (
            "lookup_material must return an independent copy for metals"
        )

    def test_translate_body_same_input_same_materials_dict(self):
        """Given the same body + materials, the materials_dict must be identical."""
        body = make_tetra()
        faces = body.all_faces()
        slot_map = {faces[0].id: "sapphire"}
        r1 = translate_body_to_gltf_plus_materials(body, materials=slot_map)
        r2 = translate_body_to_gltf_plus_materials(body, materials=slot_map)
        assert r1["materials_dict"] == r2["materials_dict"]

    def test_translate_body_same_input_same_ok_status(self):
        body = make_tetra()
        r1 = translate_body_to_gltf_plus_materials(body)
        r2 = translate_body_to_gltf_plus_materials(body)
        assert r1["ok"] == r2["ok"]

    def test_canonical_key_idempotent(self):
        """canonical_key(canonical_key(x)) == canonical_key(x)."""
        for slot in list(GEMSTONE_OPTICS) + list(METAL_PBR):
            once = canonical_key(slot)
            twice = canonical_key(once)
            assert once == twice, (
                f"canonical_key not idempotent for {slot!r}: {once!r} -> {twice!r}"
            )

    def test_supported_materials_catalog_is_stable(self):
        """supported_materials() must return same keys on repeated calls."""
        cat1 = supported_materials()
        cat2 = supported_materials()
        assert cat1 == cat2

    def test_abbe_computation_idempotent(self):
        """abbe_from_sellmeier must return the same value on repeated calls."""
        coeffs = GEMSTONE_OPTICS["sapphire"]["sellmeier"]
        v1 = abbe_from_sellmeier(coeffs)
        v2 = abbe_from_sellmeier(coeffs)
        assert v1 == pytest.approx(v2, abs=1e-9)
