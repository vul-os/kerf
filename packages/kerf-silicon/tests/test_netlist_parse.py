"""
Tests for kerf_silicon.bridges.netlist_parse.

Coverage:
  1. parse_netlist returns a NetlistAST with the expected module/cell/port counts.
  2. Cell types and connection bit-vectors are parsed correctly.
  3. Port directions are preserved.
  4. Empty JSON produces an empty but valid NetlistAST.
  5. Malformed / missing fields degrade gracefully (no exceptions).
"""

from __future__ import annotations

import pytest

from kerf_silicon.bridges.netlist_parse import (
    Cell,
    Connection,
    Module,
    NetlistAST,
    Port,
    parse_netlist,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_HALF_ADDER_JSON: dict = {
    "creator": "Yosys 0.38 (git sha1 abcdef01)",
    "modules": {
        "half_adder": {
            "ports": {
                "a": {"direction": "input",  "bits": [2]},
                "b": {"direction": "input",  "bits": [3]},
                "s": {"direction": "output", "bits": [4]},
                "c": {"direction": "output", "bits": [5]},
            },
            "cells": {
                "$xor$ha.v$1": {
                    "type": "$_XOR_",
                    "parameters": {},
                    "attributes": {"src": "ha.v:6"},
                    "connections": {
                        "A": [2],
                        "B": [3],
                        "Y": [4],
                    },
                },
                "$and$ha.v$2": {
                    "type": "$_AND_",
                    "parameters": {},
                    "attributes": {"src": "ha.v:7"},
                    "connections": {
                        "A": [2],
                        "B": [3],
                        "Y": [5],
                    },
                },
            },
            "netnames": {
                "a": {"bits": [2], "hide_name": 0},
                "b": {"bits": [3], "hide_name": 0},
                "s": {"bits": [4], "hide_name": 0},
                "c": {"bits": [5], "hide_name": 0},
            },
        }
    },
}

_COUNTER4_JSON: dict = {
    "creator": "Yosys 0.38",
    "modules": {
        "counter4": {
            "ports": {
                "clk":  {"direction": "input",  "bits": [2]},
                "rst":  {"direction": "input",  "bits": [3]},
                "q":    {"direction": "output", "bits": [4, 5, 6, 7]},
            },
            "cells": {
                "$dff$ctr$1": {
                    "type": "$_DFF_P_",
                    "parameters": {},
                    "attributes": {},
                    "connections": {
                        "C": [2],
                        "D": [8],
                        "Q": [4],
                    },
                },
                "$dff$ctr$2": {
                    "type": "$_DFF_P_",
                    "parameters": {},
                    "attributes": {},
                    "connections": {
                        "C": [2],
                        "D": [9],
                        "Q": [5],
                    },
                },
                "$dff$ctr$3": {
                    "type": "$_DFF_P_",
                    "parameters": {},
                    "attributes": {},
                    "connections": {
                        "C": [2],
                        "D": [10],
                        "Q": [6],
                    },
                },
                "$dff$ctr$4": {
                    "type": "$_DFF_P_",
                    "parameters": {},
                    "attributes": {},
                    "connections": {
                        "C": [2],
                        "D": [11],
                        "Q": [7],
                    },
                },
                "$add$ctr$1": {
                    "type": "$_XOR_",
                    "parameters": {},
                    "attributes": {},
                    "connections": {
                        "A": [4],
                        "B": ["1"],
                        "Y": [8],
                    },
                },
            },
            "netnames": {},
        }
    },
}


# ---------------------------------------------------------------------------
# 1. Module / cell / port counts
# ---------------------------------------------------------------------------

class TestHalfAdderParse:
    @pytest.fixture(autouse=True)
    def ast(self):
        self._ast = parse_netlist(_HALF_ADDER_JSON)

    def test_returns_netlist_ast(self):
        assert isinstance(self._ast, NetlistAST)

    def test_creator_preserved(self):
        assert "Yosys" in self._ast.creator

    def test_module_count(self):
        assert len(self._ast.modules) == 1

    def test_module_name(self):
        assert self._ast.modules[0].name == "half_adder"

    def test_port_count(self):
        mod = self._ast.modules[0]
        assert len(mod.ports) == 4

    def test_cell_count(self):
        mod = self._ast.modules[0]
        assert len(mod.cells) == 2


# ---------------------------------------------------------------------------
# 2. Cell types and connection bit-vectors
# ---------------------------------------------------------------------------

class TestCellParsing:
    @pytest.fixture(autouse=True)
    def setup(self):
        ast = parse_netlist(_HALF_ADDER_JSON)
        self.mod = ast.modules[0]
        self.cells_by_type = {c.cell_type: c for c in self.mod.cells}

    def test_xor_cell_present(self):
        assert "$_XOR_" in self.cells_by_type

    def test_and_cell_present(self):
        assert "$_AND_" in self.cells_by_type

    def test_xor_input_a_bit(self):
        xor = self.cells_by_type["$_XOR_"]
        assert xor.connections["A"] == (2,)

    def test_xor_input_b_bit(self):
        xor = self.cells_by_type["$_XOR_"]
        assert xor.connections["B"] == (3,)

    def test_xor_output_y_bit(self):
        xor = self.cells_by_type["$_XOR_"]
        assert xor.connections["Y"] == (4,)

    def test_and_output_y_bit(self):
        and_ = self.cells_by_type["$_AND_"]
        assert and_.connections["Y"] == (5,)

    def test_cell_attributes_preserved(self):
        xor = self.cells_by_type["$_XOR_"]
        assert "src" in xor.attributes

    def test_cell_name_preserved(self):
        names = {c.name for c in self.mod.cells}
        assert any("xor" in n.lower() for n in names)


# ---------------------------------------------------------------------------
# 3. Port directions
# ---------------------------------------------------------------------------

class TestPortDirections:
    @pytest.fixture(autouse=True)
    def setup(self):
        ast = parse_netlist(_HALF_ADDER_JSON)
        mod = ast.modules[0]
        self.ports_by_name = {p.name: p for p in mod.ports}

    def test_port_a_direction(self):
        assert self.ports_by_name["a"].direction == "input"

    def test_port_b_direction(self):
        assert self.ports_by_name["b"].direction == "input"

    def test_port_s_direction(self):
        assert self.ports_by_name["s"].direction == "output"

    def test_port_c_direction(self):
        assert self.ports_by_name["c"].direction == "output"

    def test_port_a_bits(self):
        assert self.ports_by_name["a"].bits == (2,)

    def test_port_s_bits(self):
        assert self.ports_by_name["s"].bits == (4,)


# ---------------------------------------------------------------------------
# 4. Multi-bit ports and constant-driver strings
# ---------------------------------------------------------------------------

class TestCounter4Parse:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.ast = parse_netlist(_COUNTER4_JSON)
        self.mod = self.ast.modules[0]

    def test_module_name(self):
        assert self.mod.name == "counter4"

    def test_cell_count(self):
        # 4 DFFs + 1 XOR adder
        assert len(self.mod.cells) == 5

    def test_q_port_is_4_bits(self):
        ports = {p.name: p for p in self.mod.ports}
        q = ports["q"]
        assert len(q.bits) == 4
        assert q.bits == (4, 5, 6, 7)

    def test_constant_driver_string_preserved(self):
        """Constant "1" drivers from Yosys must survive as strings."""
        cells_by_type = {}
        for c in self.mod.cells:
            cells_by_type.setdefault(c.cell_type, []).append(c)

        xor_cells = cells_by_type.get("$_XOR_", [])
        assert xor_cells, "Expected at least one XOR cell in counter4"
        # The constant driver "1" must be a string in the parsed bits.
        xor = xor_cells[0]
        all_bits = [b for bits in xor.connections.values() for b in bits]
        assert "1" in all_bits, (
            f"Expected constant '1' in XOR connections, got {xor.connections}"
        )

    def test_dff_cells_present(self):
        dff_cells = [c for c in self.mod.cells if c.cell_type == "$_DFF_P_"]
        assert len(dff_cells) == 4


# ---------------------------------------------------------------------------
# 5. Empty JSON → empty but valid AST
# ---------------------------------------------------------------------------

class TestEmptyNetlist:
    def test_empty_json(self):
        ast = parse_netlist({})
        assert isinstance(ast, NetlistAST)
        assert len(ast.modules) == 0
        assert ast.creator == ""

    def test_no_modules_key(self):
        ast = parse_netlist({"creator": "test"})
        assert len(ast.modules) == 0
        assert ast.creator == "test"


# ---------------------------------------------------------------------------
# 6. Graceful degradation on malformed fields
# ---------------------------------------------------------------------------

class TestMalformedFields:
    def test_missing_ports_key(self):
        """Module without 'ports' key must not raise."""
        j = {
            "modules": {
                "bare": {
                    "cells": {},
                    "netnames": {},
                }
            }
        }
        ast = parse_netlist(j)
        mod = ast.modules[0]
        assert mod.ports == ()

    def test_missing_cells_key(self):
        """Module without 'cells' key must not raise."""
        j = {
            "modules": {
                "bare": {
                    "ports": {},
                    "netnames": {},
                }
            }
        }
        ast = parse_netlist(j)
        mod = ast.modules[0]
        assert mod.cells == ()

    def test_non_list_bits_becomes_empty(self):
        """bits field that is not a list must produce an empty tuple."""
        j = {
            "modules": {
                "m": {
                    "ports": {
                        "x": {"direction": "input", "bits": "bad"},
                    },
                    "cells": {},
                    "netnames": {},
                }
            }
        }
        ast = parse_netlist(j)
        port = ast.modules[0].ports[0]
        assert port.bits == ()

    def test_integer_bit_preserved(self):
        """Integer bit IDs must stay as int, not coerced to str."""
        j = {
            "modules": {
                "m": {
                    "ports": {
                        "x": {"direction": "input", "bits": [42]},
                    },
                    "cells": {},
                    "netnames": {},
                }
            }
        }
        ast = parse_netlist(j)
        port = ast.modules[0].ports[0]
        assert port.bits == (42,)
        assert isinstance(port.bits[0], int)


# ---------------------------------------------------------------------------
# 7. Dataclass immutability
# ---------------------------------------------------------------------------

class TestFrozenDataclasses:
    def test_port_is_frozen(self):
        p = Port(name="x", direction="input", bits=(2,))
        with pytest.raises((AttributeError, TypeError)):
            p.name = "y"  # type: ignore[misc]

    def test_cell_is_frozen(self):
        c = Cell(
            name="$foo",
            cell_type="$_AND_",
            parameters={},
            attributes={},
            connections={},
        )
        with pytest.raises((AttributeError, TypeError)):
            c.name = "bar"  # type: ignore[misc]

    def test_module_is_frozen(self):
        m = Module(name="top", ports=(), cells=(), connections=())
        with pytest.raises((AttributeError, TypeError)):
            m.name = "other"  # type: ignore[misc]

    def test_netlist_ast_is_frozen(self):
        ast = NetlistAST(creator="test", modules=())
        with pytest.raises((AttributeError, TypeError)):
            ast.creator = "other"  # type: ignore[misc]
