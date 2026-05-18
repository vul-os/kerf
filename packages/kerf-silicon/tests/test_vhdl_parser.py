"""Tests for the VHDL parser (IEEE 1076-2008 subset)."""

from __future__ import annotations

import os
import pytest

from kerf_silicon.vhdl.parser import Parser
from kerf_silicon.vhdl import ast

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _parse_fixture(filename: str) -> ast.DesignFile:
    path = os.path.join(_FIXTURES, filename)
    with open(path) as f:
        src = f.read()
    return Parser(src).parse()


def _parse(src: str) -> ast.DesignFile:
    return Parser(src).parse()


# ---------------------------------------------------------------------------
# All fixtures produce non-empty ASTs
# ---------------------------------------------------------------------------

class TestFixtureNonEmpty:
    def test_and_gate_parses(self):
        df = _parse_fixture("and_gate.vhd")
        assert len(df.entities) >= 1
        assert len(df.architectures) >= 1

    def test_counter_parses(self):
        df = _parse_fixture("counter.vhd")
        assert len(df.entities) >= 1
        assert len(df.architectures) >= 1

    def test_uart_rx_parses(self):
        df = _parse_fixture("uart_rx.vhd")
        assert len(df.entities) >= 1
        assert len(df.architectures) >= 1


# ---------------------------------------------------------------------------
# Library / use clauses
# ---------------------------------------------------------------------------

class TestLibraryUse:
    def test_library_clause_name(self):
        df = _parse_fixture("and_gate.vhd")
        assert any("IEEE" in lc.names for lc in df.library_clauses)

    def test_use_clause_std_logic(self):
        df = _parse_fixture("and_gate.vhd")
        all_use = " ".join(
            ".".join(uc.selected_names) for uc in df.use_clauses
        ).lower()
        assert "std_logic_1164" in all_use

    def test_library_clause_line_number(self):
        df = _parse_fixture("and_gate.vhd")
        assert df.library_clauses[0].line >= 1


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------

class TestEntity:
    def test_and_gate_entity_name(self):
        df = _parse_fixture("and_gate.vhd")
        names = [e.name.lower() for e in df.entities]
        assert "and_gate" in names

    def test_and_gate_ports(self):
        df = _parse_fixture("and_gate.vhd")
        entity = df.entities[0]
        assert len(entity.ports) == 3
        port_names = [p.name.lower() for p in entity.ports]
        assert "a" in port_names
        assert "b" in port_names
        assert "y" in port_names

    def test_and_gate_port_directions(self):
        df = _parse_fixture("and_gate.vhd")
        entity = df.entities[0]
        port_map = {p.name.lower(): p.direction.lower() for p in entity.ports}
        assert port_map["a"] == "in"
        assert port_map["b"] == "in"
        assert port_map["y"] == "out"

    def test_counter_entity_has_generic(self):
        df = _parse_fixture("counter.vhd")
        entity = df.entities[0]
        assert len(entity.generics) >= 1
        gen_names = [g.name.lower() for g in entity.generics]
        assert "width" in gen_names

    def test_entity_line_number(self):
        df = _parse_fixture("and_gate.vhd")
        assert df.entities[0].line >= 1


# ---------------------------------------------------------------------------
# Counter — specific oracle: count port is std_logic_vector(7 downto 0)
# ---------------------------------------------------------------------------

class TestCounterPort:
    def test_count_port_type_name(self):
        df = _parse_fixture("counter.vhd")
        entity = df.entities[0]
        count_port = next(p for p in entity.ports if p.name.lower() == "count")
        assert count_port.type_mark.name.lower() == "std_logic_vector"

    def test_count_port_constraint(self):
        df = _parse_fixture("counter.vhd")
        entity = df.entities[0]
        count_port = next(p for p in entity.ports if p.name.lower() == "count")
        constraint = (count_port.type_mark.constraint or "").lower()
        assert "downto" in constraint
        assert "7" in constraint
        assert "0" in constraint

    def test_count_signal_in_architecture(self):
        """The count_reg internal signal is std_logic_vector(7 downto 0)."""
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        signals = [d for d in arch.declarations if isinstance(d, ast.Signal)]
        count_reg = next(
            (s for s in signals if s.name.lower() == "count_reg"), None
        )
        assert count_reg is not None
        assert count_reg.type_mark.name.lower() == "std_logic_vector"
        constraint = (count_reg.type_mark.constraint or "").lower()
        assert "downto" in constraint


# ---------------------------------------------------------------------------
# UART RX — 4 case branches
# ---------------------------------------------------------------------------

class TestUartRx:
    def _get_case_stmt(self) -> ast.CaseStatement:
        df = _parse_fixture("uart_rx.vhd")
        arch = df.architectures[0]
        # Find the process that contains the case statement
        for stmt in arch.statements:
            if isinstance(stmt, ast.Process):
                for s in stmt.statements:
                    if isinstance(s, ast.IfStatement):
                        # Look inside else branch for the outer if (rising_edge)
                        # Walk the nested ifs to find the case
                        for inner in s.then_stmts:
                            if isinstance(inner, ast.IfStatement):
                                for sub in inner.else_stmts:
                                    if isinstance(sub, ast.CaseStatement):
                                        return sub
        # Fallback: deep search
        return self._deep_find_case(df)

    def _deep_find_case(self, df: ast.DesignFile) -> ast.CaseStatement:
        def walk(node):
            if isinstance(node, ast.CaseStatement):
                return node
            for attr in ("then_stmts", "else_stmts", "statements", "stmts"):
                children = getattr(node, attr, [])
                for c in children:
                    r = walk(c)
                    if r is not None:
                        return r
            for branch in getattr(node, "elsif_branches", []):
                for c in branch[1]:
                    r = walk(c)
                    if r is not None:
                        return r
            return None

        for arch in df.architectures:
            for stmt in arch.statements:
                r = walk(stmt)
                if r is not None:
                    return r
        raise AssertionError("No CaseStatement found in uart_rx.vhd")

    def test_uart_has_case_statement(self):
        case_stmt = self._deep_find_case(_parse_fixture("uart_rx.vhd"))
        assert case_stmt is not None

    def test_uart_case_has_4_branches(self):
        case_stmt = self._deep_find_case(_parse_fixture("uart_rx.vhd"))
        assert len(case_stmt.branches) == 4

    def test_uart_case_branch_names(self):
        case_stmt = self._deep_find_case(_parse_fixture("uart_rx.vhd"))
        all_choices: list[str] = []
        for b in case_stmt.branches:
            all_choices.extend(c.lower() for c in b.choices)
        assert "idle" in all_choices
        assert "start" in all_choices
        assert "data" in all_choices
        assert "stop" in all_choices

    def test_uart_case_line_number(self):
        case_stmt = self._deep_find_case(_parse_fixture("uart_rx.vhd"))
        assert case_stmt.line >= 1


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------

class TestArchitecture:
    def test_and_gate_architecture_name(self):
        df = _parse_fixture("and_gate.vhd")
        arch = df.architectures[0]
        assert arch.name.lower() == "rtl"
        assert arch.entity_name.lower() == "and_gate"

    def test_architecture_has_statements(self):
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        assert len(arch.statements) > 0

    def test_architecture_has_signal_declarations(self):
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        signals = [d for d in arch.declarations if isinstance(d, ast.Signal)]
        assert len(signals) >= 1

    def test_architecture_line_number(self):
        df = _parse_fixture("and_gate.vhd")
        assert df.architectures[0].line >= 1


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------

class TestProcess:
    def test_counter_has_process(self):
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        procs = [s for s in arch.statements if isinstance(s, ast.Process)]
        assert len(procs) >= 1

    def test_counter_process_sensitivity_list(self):
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        proc = next(s for s in arch.statements if isinstance(s, ast.Process))
        assert any("clk" in sig.lower() for sig in proc.sensitivity_list)

    def test_process_has_statements(self):
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        proc = next(s for s in arch.statements if isinstance(s, ast.Process))
        assert len(proc.statements) > 0

    def test_process_line_number(self):
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        proc = next(s for s in arch.statements if isinstance(s, ast.Process))
        assert proc.line >= 1


# ---------------------------------------------------------------------------
# Signal assignment
# ---------------------------------------------------------------------------

class TestSignalAssignment:
    def test_and_gate_signal_assignment(self):
        df = _parse_fixture("and_gate.vhd")
        arch = df.architectures[0]
        assigns = [s for s in arch.statements if isinstance(s, ast.SignalAssignment)]
        assert len(assigns) >= 1

    def test_and_gate_assignment_target(self):
        df = _parse_fixture("and_gate.vhd")
        arch = df.architectures[0]
        assigns = [s for s in arch.statements if isinstance(s, ast.SignalAssignment)]
        targets = [a.target.lower() for a in assigns]
        assert "y" in targets

    def test_signal_assignment_line_number(self):
        df = _parse_fixture("and_gate.vhd")
        arch = df.architectures[0]
        assigns = [s for s in arch.statements if isinstance(s, ast.SignalAssignment)]
        assert assigns[0].line >= 1


# ---------------------------------------------------------------------------
# If statement
# ---------------------------------------------------------------------------

class TestIfStatement:
    def test_counter_has_if_statement(self):
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        proc = next(s for s in arch.statements if isinstance(s, ast.Process))

        def has_if(stmts):
            return any(isinstance(s, ast.IfStatement) for s in stmts)

        assert has_if(proc.statements)

    def test_if_statement_line_number(self):
        df = _parse_fixture("counter.vhd")
        arch = df.architectures[0]
        proc = next(s for s in arch.statements if isinstance(s, ast.Process))
        if_stmt = next(s for s in proc.statements if isinstance(s, ast.IfStatement))
        assert if_stmt.line >= 1


# ---------------------------------------------------------------------------
# Inline (non-fixture) parsing
# ---------------------------------------------------------------------------

class TestInlineParsing:
    def test_simple_entity(self):
        src = """
        library IEEE;
        use IEEE.STD_LOGIC_1164.ALL;
        entity foo is
            port ( clk : in std_logic; q : out std_logic );
        end entity foo;
        architecture rtl of foo is
        begin
        end architecture rtl;
        """
        df = _parse(src)
        assert len(df.entities) == 1
        assert df.entities[0].name.lower() == "foo"

    def test_signal_type_integer(self):
        src = """
        entity e is end entity e;
        architecture a of e is
            signal cnt : integer := 0;
        begin
        end architecture a;
        """
        df = _parse(src)
        signals = [d for d in df.architectures[0].declarations if isinstance(d, ast.Signal)]
        assert len(signals) == 1
        assert signals[0].type_mark.name.lower() == "integer"

    def test_multiple_library_clauses(self):
        src = """
        library IEEE;
        library WORK;
        entity e is end entity e;
        architecture a of e is begin end architecture a;
        """
        df = _parse(src)
        assert len(df.library_clauses) == 2
