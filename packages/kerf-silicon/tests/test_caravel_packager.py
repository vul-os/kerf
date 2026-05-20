"""test_caravel_packager.py — pytest suite for the Efabless Caravel packager.

Tests
-----
TestCounterFixturePackaging
    Happy-path end-to-end with the counter_project fixture.

TestWrapperGeneration
    user_project_wrapper.v structure and port presence.

TestPinOrderGeneration
    pin_order.cfg contains the 38 GPIO pins + Wishbone + LA pins.

TestConfigTcl
    openlane_config.tcl key/value assertions.

TestValidation
    Port-signature checks and CDC violation detection.

TestPackageLayout
    Output directory matches the caravel_user_project template layout.

TestIdempotency
    Re-running package_for_caravel() produces the same result.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from kerf_silicon.caravel import ValidationError, package_for_caravel
from kerf_silicon.caravel.config_tcl import generate_config_tcl
from kerf_silicon.caravel.pin_order import generate_pin_order
from kerf_silicon.caravel.validate import (
    check_cdc,
    collect_rtl_sources,
    validate,
    validate_port_signature,
)
from kerf_silicon.caravel.wrapper import generate_wrapper

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "caravel"
_COUNTER_DIR = _FIXTURES_DIR / "counter_project"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FULL_CARAVEL_MODULE = textwrap.dedent(
    """\
    module user_top (
        input  wire        wb_clk_i,
        input  wire        wb_rst_i,
        input  wire        wbs_stb_i,
        input  wire        wbs_cyc_i,
        input  wire        wbs_we_i,
        input  wire [3:0]  wbs_sel_i,
        input  wire [31:0] wbs_dat_i,
        input  wire [31:0] wbs_adr_i,
        output wire        wbs_ack_o,
        output wire [31:0] wbs_dat_o,
        input  wire [127:0] la_data_in,
        output wire [127:0] la_data_out,
        input  wire [127:0] la_oenb,
        input  wire [37:0] io_in,
        output wire [37:0] io_out,
        output wire [37:0] io_oeb,
        input  wire        user_clock2,
        output wire [2:0]  user_irq
    );
        assign wbs_ack_o  = 1'b0;
        assign wbs_dat_o  = 32'b0;
        assign la_data_out = 128'b0;
        assign io_out      = 38'b0;
        assign io_oeb      = 38'hFFFFFFFFFF;
        assign user_irq    = 3'b0;
    endmodule
    """
)

_VALID_INFO = {
    "project": {
        "title": "Test Project",
        "author": "Tester",
        "description": "A test Caravel project.",
        "top_module": "user_top",
        "language": "Verilog",
    }
}


def _make_design(tmp_path: Path, rtl: str = _FULL_CARAVEL_MODULE) -> Path:
    d = tmp_path / "design"
    d.mkdir(parents=True, exist_ok=True)
    (d / "top.v").write_text(rtl)
    return d


# ---------------------------------------------------------------------------
# Counter fixture packaging (happy path)
# ---------------------------------------------------------------------------


class TestCounterFixturePackaging:
    def test_fixture_exists(self):
        assert _COUNTER_DIR.is_dir(), f"Fixture directory missing: {_COUNTER_DIR}"
        assert (_COUNTER_DIR / "counter.v").exists()

    def test_package_returns_path(self, tmp_path: Path):
        info = json.loads((_COUNTER_DIR / "project_info.json").read_text())
        # Copy fixture to tmp_path so we don't pollute the source tree
        import shutil
        design = tmp_path / "counter_project"
        shutil.copytree(_COUNTER_DIR, design)
        result = package_for_caravel(design, info)
        assert isinstance(result, Path)

    def test_output_inside_design_dir(self, tmp_path: Path):
        import shutil
        info = json.loads((_COUNTER_DIR / "project_info.json").read_text())
        design = tmp_path / "counter_project"
        shutil.copytree(_COUNTER_DIR, design)
        result = package_for_caravel(design, info)
        assert result.parent == design

    def test_wrapper_v_written(self, tmp_path: Path):
        import shutil
        info = json.loads((_COUNTER_DIR / "project_info.json").read_text())
        design = tmp_path / "counter_project"
        shutil.copytree(_COUNTER_DIR, design)
        out = package_for_caravel(design, info)
        wrapper = out / "verilog" / "rtl" / "user_project_wrapper.v"
        assert wrapper.exists()

    def test_config_tcl_written(self, tmp_path: Path):
        import shutil
        info = json.loads((_COUNTER_DIR / "project_info.json").read_text())
        design = tmp_path / "counter_project"
        shutil.copytree(_COUNTER_DIR, design)
        out = package_for_caravel(design, info)
        cfg = out / "openlane" / "user_project_wrapper" / "config.tcl"
        assert cfg.exists()

    def test_pin_order_written(self, tmp_path: Path):
        import shutil
        info = json.loads((_COUNTER_DIR / "project_info.json").read_text())
        design = tmp_path / "counter_project"
        shutil.copytree(_COUNTER_DIR, design)
        out = package_for_caravel(design, info)
        pin_cfg = out / "openlane" / "user_project_wrapper" / "pin_order.cfg"
        assert pin_cfg.exists()

    def test_user_rtl_copied(self, tmp_path: Path):
        import shutil
        info = json.loads((_COUNTER_DIR / "project_info.json").read_text())
        design = tmp_path / "counter_project"
        shutil.copytree(_COUNTER_DIR, design)
        out = package_for_caravel(design, info)
        rtl_dir = out / "verilog" / "rtl"
        verilog_files = list(rtl_dir.rglob("*.v"))
        # wrapper.v + counter.v = at least 2
        assert len(verilog_files) >= 2

    def test_summary_written(self, tmp_path: Path):
        import shutil
        info = json.loads((_COUNTER_DIR / "project_info.json").read_text())
        design = tmp_path / "counter_project"
        shutil.copytree(_COUNTER_DIR, design)
        out = package_for_caravel(design, info)
        assert (out / "PACKAGE_SUMMARY.txt").exists()


# ---------------------------------------------------------------------------
# Wrapper generation
# ---------------------------------------------------------------------------


class TestWrapperGeneration:
    def test_contains_user_module_name(self):
        text = generate_wrapper("my_user_module")
        assert "my_user_module" in text

    def test_contains_wrapper_module_name(self):
        text = generate_wrapper("my_user_module")
        assert "user_project_wrapper" in text

    def test_gpio_bus_38bit(self):
        text = generate_wrapper("user_top")
        assert "[37:0]" in text

    def test_wishbone_ports_present(self):
        text = generate_wrapper("user_top")
        for port in ("wb_clk_i", "wb_rst_i", "wbs_stb_i", "wbs_cyc_i",
                     "wbs_we_i", "wbs_sel_i", "wbs_dat_i", "wbs_adr_i",
                     "wbs_ack_o", "wbs_dat_o"):
            assert port in text, f"Missing Wishbone port: {port}"

    def test_la_ports_present(self):
        text = generate_wrapper("user_top")
        for port in ("la_data_in", "la_data_out", "la_oenb"):
            assert port in text, f"Missing LA port: {port}"

    def test_la_width_128bit(self):
        text = generate_wrapper("user_top")
        assert "[127:0]" in text

    def test_user_irq_3bit(self):
        text = generate_wrapper("user_top")
        assert "[2:0]" in text
        assert "user_irq" in text

    def test_default_nettype_none(self):
        text = generate_wrapper("user_top")
        assert "`default_nettype none" in text

    def test_instantiation_uses_named_connections(self):
        text = generate_wrapper("user_top")
        # Named port connections: .port_name (signal)
        assert ".wb_clk_i" in text
        assert ".io_in" in text


# ---------------------------------------------------------------------------
# pin_order.cfg generation
# ---------------------------------------------------------------------------


class TestPinOrderGeneration:
    def test_gpio_pins_present(self):
        text = generate_pin_order()
        for i in range(38):
            assert f"io_in[{i}]" in text
            assert f"io_out[{i}]" in text
            assert f"io_oeb[{i}]" in text

    def test_wishbone_pins_present(self):
        text = generate_pin_order()
        for port in ("wb_clk_i", "wb_rst_i", "wbs_stb_i", "wbs_cyc_i"):
            assert port in text, f"Missing: {port}"

    def test_la_pins_present(self):
        text = generate_pin_order()
        assert "la_data_in[0]" in text
        assert "la_data_in[127]" in text
        assert "la_data_out[0]" in text
        assert "la_oenb[0]" in text

    def test_direction_markers(self):
        text = generate_pin_order()
        assert "#S" in text or "#E" in text

    def test_38_io_in_entries(self):
        text = generate_pin_order()
        count = sum(1 for i in range(38) if f"io_in[{i}]" in text)
        assert count == 38


# ---------------------------------------------------------------------------
# OpenLane config.tcl generation
# ---------------------------------------------------------------------------


class TestConfigTcl:
    def test_design_name_set(self):
        text = generate_config_tcl("user_counter")
        assert "user_counter" in text

    def test_die_area_1mm2(self):
        text = generate_config_tcl("user_counter")
        assert "1000 1000" in text

    def test_clock_port_wb_clk_i(self):
        text = generate_config_tcl("user_counter")
        assert "wb_clk_i" in text

    def test_default_clock_period_10ns(self):
        text = generate_config_tcl("user_counter")
        assert '"10"' in text or "10.0" in text or " 10 " in text

    def test_custom_clock_period(self):
        text = generate_config_tcl("user_counter", clock_period_ns=20.0)
        assert "20.0" in text

    def test_pdk_sky130a(self):
        text = generate_config_tcl("user_counter")
        assert "sky130A" in text

    def test_set_env_format(self):
        text = generate_config_tcl("user_counter")
        assert "set ::env(" in text

    def test_extra_config_override(self):
        text = generate_config_tcl(
            "user_counter",
            extra_config={"FP_CORE_UTIL": "60"},
        )
        assert '"60"' in text

    def test_std_cell_library(self):
        text = generate_config_tcl("user_counter")
        assert "sky130_fd_sc_hd" in text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_design_passes(self, tmp_path: Path):
        d = _make_design(tmp_path)
        # Should not raise
        validate(d, _VALID_INFO)

    def test_missing_io_in_raises(self, tmp_path: Path):
        bad = _FULL_CARAVEL_MODULE.replace(
            "input  wire [37:0] io_in,\n", ""
        )
        d = _make_design(tmp_path, bad)
        with pytest.raises(ValidationError, match="io_in"):
            validate(d, _VALID_INFO)

    def test_wrong_gpio_width_raises(self, tmp_path: Path):
        bad = _FULL_CARAVEL_MODULE.replace(
            "input  wire [37:0] io_in",
            "input  wire [31:0] io_in",
        )
        d = _make_design(tmp_path, bad)
        with pytest.raises(ValidationError, match="io_in"):
            validate(d, _VALID_INFO)

    def test_missing_wbs_dat_i_raises(self, tmp_path: Path):
        bad = _FULL_CARAVEL_MODULE.replace(
            "input  wire [31:0] wbs_dat_i,\n", ""
        )
        d = _make_design(tmp_path, bad)
        with pytest.raises(ValidationError, match="wbs_dat_i"):
            validate(d, _VALID_INFO)

    def test_missing_la_data_in_raises(self, tmp_path: Path):
        bad = _FULL_CARAVEL_MODULE.replace(
            "input  wire [127:0] la_data_in,\n", ""
        )
        d = _make_design(tmp_path, bad)
        with pytest.raises(ValidationError, match="la_data_in"):
            validate(d, _VALID_INFO)

    def test_missing_wb_clk_raises(self, tmp_path: Path):
        bad = _FULL_CARAVEL_MODULE.replace(
            "input  wire        wb_clk_i,\n", ""
        )
        d = _make_design(tmp_path, bad)
        with pytest.raises(ValidationError, match="wb_clk_i"):
            validate(d, _VALID_INFO)

    def test_missing_metadata_raises(self, tmp_path: Path):
        d = _make_design(tmp_path)
        bad_info = {"project": {"title": "X"}}  # missing required fields
        with pytest.raises(ValidationError):
            validate(d, bad_info)

    def test_invalid_language_raises(self, tmp_path: Path):
        d = _make_design(tmp_path)
        bad_info = dict(_VALID_INFO)
        bad_info = {
            "project": {**_VALID_INFO["project"], "language": "INTERCAL"}
        }
        with pytest.raises(ValidationError, match="language"):
            validate(d, bad_info)

    def test_no_rtl_sources_raises(self, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        with pytest.raises(ValidationError, match="No RTL source files"):
            validate(d, _VALID_INFO)

    def test_design_dir_missing_raises(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError):
            validate(missing, _VALID_INFO)

    # ---- CDC check ----

    def test_cdc_violation_raises(self, tmp_path: Path):
        """always block clocked by user_clock2 samples wbs_dat_i → CDC error."""
        cdc_rtl = _FULL_CARAVEL_MODULE + textwrap.dedent(
            """
            // Bad: samples Wishbone data on a different clock without a sync
            always @(posedge user_clock2) begin
                if (wbs_dat_i != 0) begin
                    /* do something */
                end
            end
            """
        )
        d = _make_design(tmp_path, cdc_rtl)
        with pytest.raises(ValidationError, match="[Cc]lock"):
            validate(d, _VALID_INFO)

    def test_cdc_with_synchroniser_passes(self, tmp_path: Path):
        """Same CDC pattern but with a synchroniser cell → should pass."""
        sync_rtl = _FULL_CARAVEL_MODULE + textwrap.dedent(
            """
            // Proper: data is synchronised before being used on user_clock2
            wire [31:0] wbs_dat_i_sync;
            cdc_sync #(.WIDTH(32)) u_sync (
                .clk(user_clock2),
                .d(wbs_dat_i),
                .q(wbs_dat_i_sync)
            );
            always @(posedge user_clock2) begin
                if (wbs_dat_i_sync != 0) begin
                    /* do something */
                end
            end
            """
        )
        d = _make_design(tmp_path, sync_rtl)
        # Should not raise
        validate(d, _VALID_INFO)

    def test_wb_clk_always_block_no_cdc(self, tmp_path: Path):
        """always block on wb_clk_i sampling wbs signals is NOT a CDC violation."""
        same_clk_rtl = _FULL_CARAVEL_MODULE + textwrap.dedent(
            """
            always @(posedge wb_clk_i) begin
                if (wbs_dat_i != 0) begin
                    /* do something */
                end
            end
            """
        )
        d = _make_design(tmp_path, same_clk_rtl)
        # Should not raise — same clock domain
        validate(d, _VALID_INFO)


# ---------------------------------------------------------------------------
# Package layout
# ---------------------------------------------------------------------------


class TestPackageLayout:
    def test_openlane_dir_exists(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO)
        assert (out / "openlane" / "user_project_wrapper").is_dir()

    def test_verilog_rtl_dir_exists(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO)
        assert (out / "verilog" / "rtl").is_dir()

    def test_config_tcl_in_openlane_dir(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO)
        assert (out / "openlane" / "user_project_wrapper" / "config.tcl").exists()

    def test_pin_order_in_openlane_dir(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO)
        assert (out / "openlane" / "user_project_wrapper" / "pin_order.cfg").exists()

    def test_wrapper_v_in_rtl_dir(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO)
        assert (out / "verilog" / "rtl" / "user_project_wrapper.v").exists()

    def test_wrapper_v_contains_user_module(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO)
        text = (out / "verilog" / "rtl" / "user_project_wrapper.v").read_text()
        assert "user_top" in text

    def test_package_summary_exists(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO)
        assert (out / "PACKAGE_SUMMARY.txt").exists()

    def test_summary_mentions_1mm2(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO)
        summary = (out / "PACKAGE_SUMMARY.txt").read_text()
        assert "1 mm" in summary or "1000" in summary


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_call_overwrites_cleanly(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out1 = package_for_caravel(d, _VALID_INFO)
        out2 = package_for_caravel(d, _VALID_INFO)
        assert out1 == out2
        assert out2.is_dir()

    def test_clock_period_reflected_in_config(self, tmp_path: Path):
        d = _make_design(tmp_path)
        out = package_for_caravel(d, _VALID_INFO, clock_period_ns=5.0)
        cfg = (out / "openlane" / "user_project_wrapper" / "config.tcl").read_text()
        assert "5.0" in cfg
