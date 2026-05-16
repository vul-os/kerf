"""
Tests for the one-click fab bundle module.

All tests are hermetic (no network I/O).  A minimal synthetic board is
used as a shared fixture.  Tests cover:

  - Bundle file list and naming for JLCPCB / PCBWay / OSHPark / Seeed / AllPCB
  - Vendor-specific PnP CSV header formats
  - Vendor-specific BOM CSV formats (JLCPCB vs standard)
  - README content (mentions copper weight, surface finish, dimensions)
  - zip round-trip via stdlib zipfile
  - bundle_zip produces a valid ZIP
  - Unsupported vendor returns error key
  - vendor_presets() covers all known vendors
  - fab_readme() standalone behaviour
  - Options override works
  - IPC-2581 inclusion gated by include_ipc2581 option
  - Drill file present when include_drl=True, absent when False
  - All five vendors produce non-empty output
  - JLCPCB BOM has LCSC Part # column
  - PCBWay PnP has Ref/Value/Package columns
  - OSHPark Gerber naming uses standard extensions (GTL/GBL/GKO etc.)
"""

import io
import zipfile

import pytest

from kerf_electronics.fab.bundle import (
    bundle_zip,
    fab_bundle,
    fab_readme,
    vendor_presets,
)


# ─── Synthetic board fixture ──────────────────────────────────────────────────

BOARD = [
    {
        "type": "pcb_board",
        "width": 80.0,
        "height": 60.0,
        "center_x": 40.0,
        "center_y": 30.0,
    },
    # source components
    {
        "type": "source_component",
        "source_component_id": "sc_r1",
        "name": "R1",
        "value": "100R",
        "footprint": "R_0402",
        "mpn": "RC0402JR-07100RL",
        "manufacturer": "Yageo",
        "description": "Resistor 100R 5% 0402",
        "distributors": [
            {"name": "DigiKey", "part_number": "311-100GRCT-ND", "unit_price_usd": 0.08},
        ],
    },
    {
        "type": "source_component",
        "source_component_id": "sc_c1",
        "name": "C1",
        "value": "100nF",
        "footprint": "C_0402",
        "mpn": "GRM155R71C104KA88D",
        "manufacturer": "Murata",
        "description": "Capacitor 100nF 16V X7R 0402",
        "distributors": [
            {"name": "DigiKey", "part_number": "490-1532-1-ND", "unit_price_usd": 0.10},
        ],
    },
    {
        "type": "source_component",
        "source_component_id": "sc_u1",
        "name": "U1",
        "value": "STM32F103C8T6",
        "footprint": "LQFP-48",
        "mpn": "STM32F103C8T6",
        "manufacturer": "STMicroelectronics",
        "description": "32-bit MCU",
        "distributors": [
            {"name": "Mouser", "part_number": "511-STM32F103C8T6", "unit_price_usd": 3.20},
        ],
    },
    # pcb components
    {
        "type": "pcb_component",
        "pcb_component_id": "pcb_r1",
        "source_component_id": "sc_r1",
        "x": 10.0,
        "y": 15.0,
        "rotation": 0.0,
        "layer": "top_copper",
    },
    {
        "type": "pcb_component",
        "pcb_component_id": "pcb_c1",
        "source_component_id": "sc_c1",
        "x": 20.0,
        "y": 15.0,
        "rotation": 90.0,
        "layer": "top_copper",
    },
    {
        "type": "pcb_component",
        "pcb_component_id": "pcb_u1",
        "source_component_id": "sc_u1",
        "x": 40.0,
        "y": 30.0,
        "rotation": 0.0,
        "layer": "top_copper",
    },
    # SMT pads
    {
        "type": "pcb_smtpad",
        "source_component_id": "sc_r1",
        "x": 9.5,
        "y": 15.0,
        "width": 1.0,
        "height": 0.6,
        "shape": "rect",
        "layer": "top_copper",
    },
    {
        "type": "pcb_smtpad",
        "source_component_id": "sc_c1",
        "x": 20.0,
        "y": 14.5,
        "width": 1.0,
        "height": 0.6,
        "shape": "rect",
        "layer": "top_copper",
    },
    # via
    {
        "type": "pcb_via",
        "x": 30.0,
        "y": 20.0,
        "outer_diameter": 0.6,
        "hole_diameter": 0.3,
    },
    # trace
    {
        "type": "pcb_trace",
        "route": [
            {"x": 10.0, "y": 15.0, "width": 0.25, "layer": "top_copper"},
            {"x": 30.0, "y": 15.0, "width": 0.25, "layer": "top_copper"},
        ],
    },
]

EMPTY_BOARD: list[dict] = []


# ─── vendor_presets() ─────────────────────────────────────────────────────────

class TestVendorPresets:
    def test_all_five_vendors_present(self):
        presets = vendor_presets()
        for vendor in ("jlcpcb", "pcbway", "oshpark", "seeed", "allpcb"):
            assert vendor in presets, f"Missing vendor: {vendor}"

    def test_each_preset_has_required_keys(self):
        required = {
            "stem", "copper_weight", "surface_finish", "soldermask",
            "silkscreen", "board_thickness", "include_ipc2581", "include_drl",
        }
        for vendor, opts in vendor_presets().items():
            for key in required:
                assert key in opts, f"Vendor {vendor} missing key {key}"

    def test_jlcpcb_no_ipc2581_by_default(self):
        assert vendor_presets()["jlcpcb"]["include_ipc2581"] is False

    def test_pcbway_includes_ipc2581_by_default(self):
        assert vendor_presets()["pcbway"]["include_ipc2581"] is True

    def test_oshpark_is_enig(self):
        assert "ENIG" in vendor_presets()["oshpark"]["surface_finish"]

    def test_oshpark_is_purple(self):
        assert vendor_presets()["oshpark"]["soldermask"] == "purple"


# ─── fab_bundle() — JLCPCB ───────────────────────────────────────────────────

class TestFabBundleJlcpcb:
    def setup_method(self):
        self.bundle = fab_bundle(BOARD, vendor="jlcpcb")

    def test_no_error_key(self):
        assert "ERROR" not in self.bundle

    def test_has_readme(self):
        assert "README.txt" in self.bundle

    def test_gerber_files_use_gbr_extension(self):
        gbr_files = [f for f in self.bundle if f.endswith(".gbr")]
        assert len(gbr_files) > 0

    def test_top_copper_gerber_filename(self):
        assert "gerber_top_copper.gbr" in self.bundle

    def test_bottom_copper_gerber_filename(self):
        assert "gerber_bottom_copper.gbr" in self.bundle

    def test_board_outline_gerber_filename(self):
        assert "gerber_board_outline.gbr" in self.bundle

    def test_drill_file_present(self):
        drills = [f for f in self.bundle if f.endswith(".drl")]
        assert len(drills) > 0

    def test_drill_filename_is_gerber_drill(self):
        assert "gerber_drill.drl" in self.bundle

    def test_bom_csv_present(self):
        boms = [f for f in self.bundle if "bom" in f.lower() and f.endswith(".csv")]
        assert len(boms) > 0

    def test_cpl_csv_present(self):
        cpls = [f for f in self.bundle if "cpl" in f.lower() and f.endswith(".csv")]
        assert len(cpls) > 0

    def test_bom_has_lcsc_column(self):
        bom_key = next(f for f in self.bundle if "bom" in f.lower() and f.endswith(".csv"))
        bom_text = self.bundle[bom_key].decode("utf-8")
        assert "LCSC Part #" in bom_text

    def test_bom_has_all_parts(self):
        bom_key = next(f for f in self.bundle if "bom" in f.lower() and f.endswith(".csv"))
        bom_text = self.bundle[bom_key].decode("utf-8")
        # R1, C1, U1 should all appear in refdes column
        assert "R1" in bom_text
        assert "C1" in bom_text
        assert "U1" in bom_text

    def test_pnp_header_matches_jlcpcb_format(self):
        cpl_key = next(f for f in self.bundle if "cpl" in f.lower() and f.endswith(".csv"))
        cpl_text = self.bundle[cpl_key].decode("utf-8")
        header_line = cpl_text.splitlines()[0]
        assert "Designator" in header_line
        assert "Mid X" in header_line
        assert "Mid Y" in header_line
        assert "Layer" in header_line
        assert "Rotation" in header_line

    def test_no_ipc2581_xml_by_default(self):
        xml_files = [f for f in self.bundle if f.endswith(".xml")]
        assert len(xml_files) == 0

    def test_gerber_bytes_are_bytes(self):
        for fname, data in self.bundle.items():
            assert isinstance(data, bytes), f"Value for {fname} is not bytes"

    def test_all_values_are_bytes(self):
        for fname, data in self.bundle.items():
            assert isinstance(data, bytes)


# ─── fab_bundle() — PCBWay ───────────────────────────────────────────────────

class TestFabBundlePcbway:
    def setup_method(self):
        self.bundle = fab_bundle(BOARD, vendor="pcbway")

    def test_no_error_key(self):
        assert "ERROR" not in self.bundle

    def test_gerber_uses_standard_gtl_extension(self):
        gtl_files = [f for f in self.bundle if f.endswith(".GTL")]
        assert len(gtl_files) > 0

    def test_gerber_uses_standard_gbl_extension(self):
        gbl_files = [f for f in self.bundle if f.endswith(".GBL")]
        assert len(gbl_files) > 0

    def test_gerber_naming_differs_from_jlcpcb(self):
        jlcpcb_bundle = fab_bundle(BOARD, vendor="jlcpcb")
        pcbway_keys = set(self.bundle.keys())
        jlcpcb_keys = set(jlcpcb_bundle.keys())
        # They must differ — JLCPCB uses .gbr, PCBWay uses .GTL etc.
        assert pcbway_keys != jlcpcb_keys

    def test_pnp_has_ref_value_package_columns(self):
        pnp_key = next(f for f in self.bundle if "pnp" in f.lower() and f.endswith(".csv"))
        pnp_text = self.bundle[pnp_key].decode("utf-8")
        header_line = pnp_text.splitlines()[0]
        assert "Ref" in header_line
        assert "Value" in header_line
        assert "Package" in header_line

    def test_ipc2581_xml_present_by_default(self):
        xml_files = [f for f in self.bundle if f.endswith(".xml")]
        assert len(xml_files) > 0

    def test_drill_file_uses_drl_extension(self):
        drl_files = [f for f in self.bundle if f.endswith(".DRL")]
        assert len(drl_files) > 0


# ─── fab_bundle() — OSHPark ──────────────────────────────────────────────────

class TestFabBundleOshpark:
    def setup_method(self):
        self.bundle = fab_bundle(BOARD, vendor="oshpark")

    def test_no_error_key(self):
        assert "ERROR" not in self.bundle

    def test_uses_gtl_extension(self):
        assert any(f.endswith(".GTL") for f in self.bundle)

    def test_uses_gbl_extension(self):
        assert any(f.endswith(".GBL") for f in self.bundle)

    def test_uses_gto_extension(self):
        assert any(f.endswith(".GTO") for f in self.bundle)

    def test_uses_gko_extension(self):
        assert any(f.endswith(".GKO") for f in self.bundle)

    def test_naming_differs_from_jlcpcb(self):
        jlcpcb_bundle = fab_bundle(BOARD, vendor="jlcpcb")
        oshpark_keys = set(self.bundle.keys())
        jlcpcb_keys = set(jlcpcb_bundle.keys())
        assert oshpark_keys != jlcpcb_keys

    def test_naming_differs_from_pcbway_on_stem(self):
        # OSHPark and PCBWay both use standard extensions, but stem should be same 'board'
        # Verify they have the same set of Gerber extensions
        pcbway_bundle = fab_bundle(BOARD, vendor="pcbway")
        oshpark_gtl = [f for f in self.bundle if f.endswith(".GTL")]
        pcbway_gtl = [f for f in pcbway_bundle if f.endswith(".GTL")]
        # Both have GTL, names should be equal (both use stem 'board')
        assert oshpark_gtl == pcbway_gtl


# ─── fab_bundle() — Seeed and AllPCB ─────────────────────────────────────────

class TestFabBundleSeeedAllpcb:
    def test_seeed_bundle_nonempty(self):
        bundle = fab_bundle(BOARD, vendor="seeed")
        assert "ERROR" not in bundle
        assert len(bundle) > 0

    def test_allpcb_bundle_nonempty(self):
        bundle = fab_bundle(BOARD, vendor="allpcb")
        assert "ERROR" not in bundle
        assert len(bundle) > 0

    def test_seeed_has_readme(self):
        bundle = fab_bundle(BOARD, vendor="seeed")
        assert "README.txt" in bundle

    def test_allpcb_has_readme(self):
        bundle = fab_bundle(BOARD, vendor="allpcb")
        assert "README.txt" in bundle


# ─── Unsupported vendor ───────────────────────────────────────────────────────

class TestUnsupportedVendor:
    def test_unsupported_vendor_returns_error_key(self):
        bundle = fab_bundle(BOARD, vendor="badvendor")
        assert "ERROR" in bundle

    def test_error_message_mentions_vendor(self):
        bundle = fab_bundle(BOARD, vendor="badvendor")
        error_text = bundle["ERROR"].decode("utf-8")
        assert "badvendor" in error_text

    def test_unsupported_vendor_returns_no_other_keys(self):
        bundle = fab_bundle(BOARD, vendor="unknownfab")
        assert list(bundle.keys()) == ["ERROR"]


# ─── fab_readme() ─────────────────────────────────────────────────────────────

class TestFabReadme:
    def test_readme_mentions_copper_weight(self):
        readme = fab_readme(BOARD, vendor="jlcpcb", options={"copper_weight": "2oz"})
        assert "2oz" in readme

    def test_readme_mentions_surface_finish(self):
        readme = fab_readme(BOARD, vendor="jlcpcb", options={"surface_finish": "ENIG"})
        assert "ENIG" in readme

    def test_readme_mentions_board_dimensions(self):
        readme = fab_readme(BOARD, vendor="jlcpcb")
        # BOARD is 80x60 mm
        assert "80.0" in readme
        assert "60.0" in readme

    def test_readme_mentions_soldermask_colour(self):
        readme = fab_readme(BOARD, vendor="jlcpcb", options={"soldermask": "black"})
        assert "black" in readme

    def test_readme_mentions_silkscreen_colour(self):
        readme = fab_readme(BOARD, vendor="pcbway", options={"silkscreen": "black"})
        assert "black" in readme

    def test_readme_mentions_board_thickness(self):
        readme = fab_readme(BOARD, vendor="jlcpcb", options={"board_thickness": "0.8mm"})
        assert "0.8mm" in readme

    def test_readme_has_vendor_name_jlcpcb(self):
        readme = fab_readme(BOARD, vendor="jlcpcb")
        assert "JLCPCB" in readme

    def test_readme_has_vendor_name_pcbway(self):
        readme = fab_readme(BOARD, vendor="pcbway")
        assert "PCBWay" in readme

    def test_readme_has_vendor_name_oshpark(self):
        readme = fab_readme(BOARD, vendor="oshpark")
        assert "OSHPark" in readme

    def test_readme_special_instructions_appear(self):
        readme = fab_readme(BOARD, vendor="jlcpcb", options={"special": "IMPEDANCE_CONTROL_50OHM"})
        assert "IMPEDANCE_CONTROL_50OHM" in readme

    def test_readme_for_unknown_vendor_does_not_raise(self):
        # fab_readme does not validate vendor — it falls back gracefully
        readme = fab_readme(BOARD, vendor="unknownvendor")
        assert isinstance(readme, str)
        assert len(readme) > 0


# ─── Options override ─────────────────────────────────────────────────────────

class TestOptionsOverride:
    def test_custom_stem_in_filenames(self):
        bundle = fab_bundle(BOARD, vendor="pcbway", options={"stem": "mypcb"})
        gtl_files = [f for f in bundle if f.endswith(".GTL")]
        assert len(gtl_files) > 0
        assert all("mypcb" in f for f in gtl_files)

    def test_include_drl_false_removes_drill_file(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb", options={"include_drl": False})
        drl_files = [f for f in bundle if f.endswith(".drl") or f.endswith(".DRL")]
        assert len(drl_files) == 0

    def test_include_ipc2581_true_adds_xml(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb", options={"include_ipc2581": True})
        xml_files = [f for f in bundle if f.endswith(".xml")]
        assert len(xml_files) > 0


# ─── bundle_zip() ─────────────────────────────────────────────────────────────

class TestBundleZip:
    def test_bundle_zip_is_valid_zip(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb")
        zip_bytes = bundle_zip(bundle)
        assert zipfile.is_zipfile(io.BytesIO(zip_bytes))

    def test_bundle_zip_round_trip_all_entries(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb")
        zip_bytes = bundle_zip(bundle)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            zip_names = set(zf.namelist())
        assert zip_names == set(bundle.keys())

    def test_bundle_zip_entries_readable(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb")
        zip_bytes = bundle_zip(bundle)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            for name in zf.namelist():
                data = zf.read(name)
                assert isinstance(data, bytes)

    def test_bundle_zip_entry_contents_match(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb")
        zip_bytes = bundle_zip(bundle)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            for name, original_bytes in bundle.items():
                assert zf.read(name) == original_bytes

    def test_bundle_zip_empty_dict_produces_valid_zip(self):
        zip_bytes = bundle_zip({})
        assert zipfile.is_zipfile(io.BytesIO(zip_bytes))

    def test_bundle_zip_pcbway_round_trip(self):
        bundle = fab_bundle(BOARD, vendor="pcbway")
        zip_bytes = bundle_zip(bundle)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())
        assert names == set(bundle.keys())

    def test_bundle_zip_oshpark_round_trip(self):
        bundle = fab_bundle(BOARD, vendor="oshpark")
        zip_bytes = bundle_zip(bundle)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())
        assert names == set(bundle.keys())


# ─── Gerber content sanity ────────────────────────────────────────────────────

class TestGerberContent:
    def test_jlcpcb_top_copper_gerber_is_valid_rs274x(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb")
        content = bundle["gerber_top_copper.gbr"].decode("utf-8")
        # RS-274X files start with %FSLAX or G04 comments
        assert "M02" in content  # end of file marker

    def test_standard_gtl_contains_gerber_format(self):
        bundle = fab_bundle(BOARD, vendor="pcbway")
        gtl_key = next(f for f in bundle if f.endswith(".GTL"))
        content = bundle[gtl_key].decode("utf-8")
        assert "M02" in content

    def test_drill_file_has_excellon_header(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb")
        drill = bundle["gerber_drill.drl"].decode("utf-8")
        assert "M48" in drill  # Excellon header

    def test_drill_file_has_metric_marker(self):
        bundle = fab_bundle(BOARD, vendor="jlcpcb")
        drill = bundle["gerber_drill.drl"].decode("utf-8")
        assert "METRIC" in drill


# ─── Empty board robustness ───────────────────────────────────────────────────

class TestEmptyBoard:
    def test_empty_board_jlcpcb_does_not_raise(self):
        bundle = fab_bundle(EMPTY_BOARD, vendor="jlcpcb")
        assert isinstance(bundle, dict)

    def test_empty_board_has_readme(self):
        bundle = fab_bundle(EMPTY_BOARD, vendor="jlcpcb")
        assert "README.txt" in bundle

    def test_empty_board_zip_is_valid(self):
        bundle = fab_bundle(EMPTY_BOARD, vendor="pcbway")
        zip_bytes = bundle_zip(bundle)
        assert zipfile.is_zipfile(io.BytesIO(zip_bytes))
