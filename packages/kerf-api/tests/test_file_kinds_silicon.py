"""T-248: Regression guard for silicon/EDA + firmware file kinds.

Asserts that FILE_KINDS contains all 11 new kinds added in T-248:
  hdl_vhdl, hdl_verilog, spice_netlist, gds_layout, oasis_layout,
  lef_lib, def_design, liberty_lib, silicon_flow, silicon_pdk,
  firmware_project

These kinds must be present in FILE_KINDS (API allow-list) and in the
DB files_kind_check constraint (validated by existing test_file_kinds.py).
"""
from __future__ import annotations

import pytest

from kerf_api.routes import FILE_KINDS

T248_KINDS = {
    "hdl_vhdl",
    "hdl_verilog",
    "spice_netlist",
    "gds_layout",
    "oasis_layout",
    "lef_lib",
    "def_design",
    "liberty_lib",
    "silicon_flow",
    "silicon_pdk",
    "firmware_project",
}


@pytest.mark.parametrize("kind", sorted(T248_KINDS))
def test_silicon_kind_in_file_kinds(kind: str) -> None:
    assert kind in FILE_KINDS, (
        f"T-248 silicon/EDA/firmware kind '{kind}' missing from FILE_KINDS"
    )


def test_all_t248_kinds_present() -> None:
    missing = T248_KINDS - set(FILE_KINDS)
    assert not missing, (
        f"T-248 kinds missing from FILE_KINDS: {sorted(missing)}"
    )
