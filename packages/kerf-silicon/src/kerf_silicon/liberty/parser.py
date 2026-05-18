"""parser.py — Recursive-descent parser for Synopsys Liberty (.lib) files.

Entry point::

    from kerf_silicon.liberty.parser import parse
    lib = parse(text)          # returns LibertyLibrary
    lib = parse_file(path)     # convenience wrapper

The parser is intentionally lenient: unknown attributes and groups are
consumed and silently discarded so that real-world .lib files with
vendor-specific extensions don't cause hard failures.
"""
from __future__ import annotations

import os
from typing import Iterator, List, Optional

from kerf_silicon.liberty.ast import (
    Cell,
    LUTable,
    LUTableTemplate,
    LibertyLibrary,
    OperatingConditions,
    Pin,
    SourcePos,
    TimingArc,
)
from kerf_silicon.liberty.lexer import (
    BACKSLASH,
    COLON,
    COMMA,
    EOF,
    IDENT,
    LBRACE,
    LPAREN,
    NUMBER,
    RBRACE,
    RPAREN,
    SEMICOLON,
    STRING,
    Token,
    tokenise,
)


# ---------------------------------------------------------------------------
# Parse error
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Raised when the token stream does not match the Liberty grammar."""

    def __init__(self, msg: str, pos: Optional[SourcePos] = None) -> None:
        location = f" at {pos}" if pos else ""
        super().__init__(f"ParseError{location}: {msg}")
        self.pos = pos


# ---------------------------------------------------------------------------
# Token stream helper
# ---------------------------------------------------------------------------


class _TokenStream:
    """Thin wrapper around the tokenise() generator providing peek/consume."""

    def __init__(self, tokens: Iterator[Token]) -> None:
        self._tokens = tokens
        self._buf: list[Token] = []
        self._advance()

    def _advance(self) -> None:
        self._current = next(self._tokens)

    def peek(self) -> Token:
        return self._current

    def consume(self) -> Token:
        tok = self._current
        self._advance()
        return tok

    def expect(self, type_: str) -> Token:
        tok = self.consume()
        if tok.type != type_:
            raise ParseError(
                f"expected {type_!r} but got {tok.type!r} ({tok.value!r})",
                tok.pos,
            )
        return tok

    def at_end(self) -> bool:
        return self._current.type == EOF


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, ts: _TokenStream) -> None:
        self._ts = ts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_name(self) -> tuple[str, SourcePos]:
        """Parse the parenthesised name that follows a group keyword.

        Handles both ``cell (NAME)`` and ``cell (NAME1, NAME2)`` forms;
        for multi-name groups we return the first name only.
        """
        self._ts.expect(LPAREN)
        tok = self._ts.peek()
        if tok.type in (IDENT, STRING, NUMBER):
            name = tok.value
            name_pos = tok.pos
            self._ts.consume()
        elif tok.type == RPAREN:
            # anonymous group — empty name
            name = ""
            name_pos = tok.pos
        else:
            raise ParseError(f"expected group name, got {tok.type!r}", tok.pos)

        # Drain any remaining items before RPAREN (e.g. multi-name groups)
        while self._ts.peek().type not in (RPAREN, EOF):
            self._ts.consume()
        self._ts.expect(RPAREN)
        return name, name_pos

    def _skip_paren_args(self) -> None:
        """Consume a ``( ... )`` argument list including nested parens.

        Assumes the opening ``(`` has NOT yet been consumed.
        """
        self._ts.expect(LPAREN)
        depth = 1
        while depth > 0 and not self._ts.at_end():
            t = self._ts.consume()
            if t.type == LPAREN:
                depth += 1
            elif t.type == RPAREN:
                depth -= 1

    def _skip_group_body(self) -> None:
        """Consume a Liberty group or paren-attribute block.

        Handles three shapes:
        * ``{ ... }``         — brace group (most groups)
        * ``(name) { ... }``  — named group whose name comes before the brace
        * ``(value) ;``       — paren-style simple attribute
          e.g. ``technology (cmos);``

        Assumes the keyword IDENT has already been consumed; next token is
        either ``{`` or ``(``.
        """
        if self._ts.peek().type == LPAREN:
            # consume the paren-arg list
            self._skip_paren_args()
            # now check: brace body follows → skip it; semicolon → done
            if self._ts.peek().type == LBRACE:
                self._skip_brace_body()
            else:
                if self._ts.peek().type == SEMICOLON:
                    self._ts.consume()
            return
        self._skip_brace_body()

    def _skip_brace_body(self) -> None:
        """Consume a complete ``{ ... }`` block including nested braces."""
        self._ts.expect(LBRACE)
        depth = 1
        while depth > 0 and not self._ts.at_end():
            t = self._ts.consume()
            if t.type == LBRACE:
                depth += 1
            elif t.type == RBRACE:
                depth -= 1

    def _parse_attribute_value(self) -> str:
        """Consume and return the textual value of a simple attribute.

        Handles both the colon form (``key : value ;``) and the bare
        form (``key value ;``).  Stops at ``;`` or ``}`` so that
        missing semicolons in some real-world files don't stall the parser.
        """
        tok = self._ts.peek()
        # Consume optional colon
        if tok.type == COLON:
            self._ts.consume()

        parts: list[str] = []
        while self._ts.peek().type not in (SEMICOLON, RBRACE, EOF):
            t = self._ts.consume()
            if t.type == LPAREN:
                # e.g. values("0.1, 0.2", "0.3, 0.4")  — collect raw
                inner = [t.value]
                depth = 1
                while depth > 0 and not self._ts.at_end():
                    it = self._ts.consume()
                    inner.append(it.value)
                    if it.type == LPAREN:
                        depth += 1
                    elif it.type == RPAREN:
                        depth -= 1
                parts.append("".join(inner))
            else:
                parts.append(t.value)

        # Consume optional semicolon
        if self._ts.peek().type == SEMICOLON:
            self._ts.consume()

        return " ".join(parts).strip()

    def _parse_values(self) -> list[float]:
        """Parse ``values("0.1, 0.2", "0.3, 0.4")`` -> flat list of floats."""
        self._ts.expect(LPAREN)
        raw_parts: list[str] = []

        while self._ts.peek().type not in (RPAREN, EOF):
            tok = self._ts.peek()
            if tok.type == STRING:
                raw_parts.append(self._ts.consume().value)
            elif tok.type in (NUMBER, IDENT):
                raw_parts.append(self._ts.consume().value)
            elif tok.type == COMMA:
                self._ts.consume()
            elif tok.type == BACKSLASH:
                # line continuation inside values list
                self._ts.consume()
            else:
                self._ts.consume()  # skip unexpected

        self._ts.expect(RPAREN)
        # Drain optional semicolon
        if self._ts.peek().type == SEMICOLON:
            self._ts.consume()

        floats: list[float] = []
        for part in raw_parts:
            for chunk in part.replace(",", " ").split():
                try:
                    floats.append(float(chunk))
                except ValueError:
                    pass  # skip non-numeric tokens inside values
        return floats

    # ------------------------------------------------------------------
    # Group parsers
    # ------------------------------------------------------------------

    def _parse_lu_table(self, group_name: str, pos: SourcePos) -> LUTable:
        """Parse ``cell_rise (template) { values(...); }``."""
        template, _ = self._parse_name()
        self._ts.expect(LBRACE)
        values: list[float] = []

        while self._ts.peek().type not in (RBRACE, EOF):
            tok = self._ts.peek()
            if tok.type == IDENT and tok.value == "values":
                self._ts.consume()
                if self._ts.peek().type == COLON:
                    self._ts.consume()
                values = self._parse_values()
            elif tok.type == IDENT:
                # skip other attributes (index_1, index_2, …)
                self._ts.consume()
                _ = self._parse_attribute_value()
            else:
                self._ts.consume()

        self._ts.expect(RBRACE)
        if self._ts.peek().type == SEMICOLON:
            self._ts.consume()

        return LUTable(template=template, values=values, pos=pos)

    def _parse_timing(self, pos: SourcePos) -> TimingArc:
        """Parse ``timing () { ... }``."""
        # consume the () — timing arcs have an anonymous or empty name
        self._ts.expect(LPAREN)
        if self._ts.peek().type != RPAREN:
            # Some files put a name here; consume it
            while self._ts.peek().type not in (RPAREN, EOF):
                self._ts.consume()
        self._ts.expect(RPAREN)
        self._ts.expect(LBRACE)

        arc = TimingArc(pos=pos)

        while self._ts.peek().type not in (RBRACE, EOF):
            tok = self._ts.peek()
            if tok.type != IDENT:
                self._ts.consume()
                continue

            key = tok.value
            key_pos = tok.pos
            self._ts.consume()

            if key in ("cell_rise", "cell_fall", "rise_transition", "fall_transition"):
                table = self._parse_lu_table(key, key_pos)
                if key == "cell_rise":
                    arc.cell_rise = table
                elif key == "cell_fall":
                    arc.cell_fall = table
                elif key == "rise_transition":
                    arc.rise_transition = table
                elif key == "fall_transition":
                    arc.fall_transition = table
            elif self._ts.peek().type in (COLON, NUMBER, STRING, IDENT):
                val = self._parse_attribute_value()
                if key == "related_pin":
                    arc.related_pin = val.strip('"')
                elif key == "timing_type":
                    arc.timing_type = val.strip('"')
                elif key == "timing_sense":
                    arc.timing_sense = val.strip('"')
            elif self._ts.peek().type == LPAREN:
                # nested group we don't care about
                self._skip_group_body()
            else:
                # skip lone SEMICOLON or other noise
                if self._ts.peek().type == SEMICOLON:
                    self._ts.consume()

        self._ts.expect(RBRACE)
        if self._ts.peek().type == SEMICOLON:
            self._ts.consume()
        return arc

    def _parse_pin(self, pos: SourcePos) -> Pin:
        """Parse ``pin (NAME) { ... }``."""
        name, _ = self._parse_name()
        self._ts.expect(LBRACE)

        pin = Pin(name=name, pos=pos)

        while self._ts.peek().type not in (RBRACE, EOF):
            tok = self._ts.peek()
            if tok.type != IDENT:
                self._ts.consume()
                continue

            key = tok.value
            key_pos = tok.pos
            self._ts.consume()

            if key == "timing":
                arc = self._parse_timing(key_pos)
                pin.timing_arcs.append(arc)
            elif self._ts.peek().type in (COLON, NUMBER, STRING, IDENT):
                val = self._parse_attribute_value()
                if key == "direction":
                    pin.direction = val.strip('"')
                elif key == "capacitance":
                    try:
                        pin.capacitance = float(val)
                    except ValueError:
                        pass
                elif key == "max_capacitance":
                    try:
                        pin.max_capacitance = float(val)
                    except ValueError:
                        pass
                elif key == "function":
                    pin.function = val.strip('"')
                elif key == "three_state":
                    pin.three_state = val.strip('"')
            elif self._ts.peek().type == LPAREN:
                self._skip_group_body()
            elif self._ts.peek().type == LBRACE:
                self._skip_brace_body()
            else:
                if self._ts.peek().type == SEMICOLON:
                    self._ts.consume()

        self._ts.expect(RBRACE)
        if self._ts.peek().type == SEMICOLON:
            self._ts.consume()
        return pin

    def _parse_cell(self, pos: SourcePos) -> Cell:
        """Parse ``cell (NAME) { ... }``."""
        name, _ = self._parse_name()
        self._ts.expect(LBRACE)

        cell = Cell(name=name, pos=pos)

        while self._ts.peek().type not in (RBRACE, EOF):
            tok = self._ts.peek()
            if tok.type != IDENT:
                self._ts.consume()
                continue

            key = tok.value
            key_pos = tok.pos
            self._ts.consume()

            if key == "pin":
                pin = self._parse_pin(key_pos)
                cell.pins.append(pin)
            elif self._ts.peek().type in (COLON, NUMBER, STRING, IDENT):
                val = self._parse_attribute_value()
                if key == "area":
                    try:
                        cell.area = float(val)
                    except ValueError:
                        pass
                elif key == "cell_leakage_power":
                    try:
                        cell.cell_leakage_power = float(val)
                    except ValueError:
                        pass
            elif self._ts.peek().type == LPAREN:
                # nested group (e.g. leakage_power, pg_pin, …)
                self._skip_group_body()
            elif self._ts.peek().type == LBRACE:
                self._skip_brace_body()
            else:
                if self._ts.peek().type == SEMICOLON:
                    self._ts.consume()

        self._ts.expect(RBRACE)
        if self._ts.peek().type == SEMICOLON:
            self._ts.consume()
        return cell

    def _parse_operating_conditions(self, pos: SourcePos) -> OperatingConditions:
        name, _ = self._parse_name()
        self._ts.expect(LBRACE)
        oc = OperatingConditions(name=name, pos=pos)

        while self._ts.peek().type not in (RBRACE, EOF):
            tok = self._ts.peek()
            if tok.type != IDENT:
                self._ts.consume()
                continue
            key = tok.value
            self._ts.consume()
            if self._ts.peek().type in (COLON, NUMBER, STRING, IDENT):
                val = self._parse_attribute_value()
                if key == "process":
                    try: oc.process = float(val)
                    except ValueError: pass
                elif key == "temperature":
                    try: oc.temperature = float(val)
                    except ValueError: pass
                elif key == "voltage":
                    try: oc.voltage = float(val)
                    except ValueError: pass
            else:
                if self._ts.peek().type == SEMICOLON:
                    self._ts.consume()

        self._ts.expect(RBRACE)
        if self._ts.peek().type == SEMICOLON:
            self._ts.consume()
        return oc

    def _parse_lu_table_template(self, pos: SourcePos) -> LUTableTemplate:
        name, _ = self._parse_name()
        self._ts.expect(LBRACE)
        tmpl = LUTableTemplate(name=name, pos=pos)

        while self._ts.peek().type not in (RBRACE, EOF):
            tok = self._ts.peek()
            if tok.type != IDENT:
                self._ts.consume()
                continue
            key = tok.value
            self._ts.consume()
            if self._ts.peek().type in (COLON, NUMBER, STRING, IDENT):
                val = self._parse_attribute_value()
                if key == "variable_1":
                    tmpl.variable_1 = val.strip('"')
                elif key == "variable_2":
                    tmpl.variable_2 = val.strip('"')
                elif key in ("index_1", "index_2"):
                    nums = [float(x) for x in val.replace(",", " ").split() if _is_float(x)]
                    if key == "index_1":
                        tmpl.index_1 = nums
                    else:
                        tmpl.index_2 = nums
            elif self._ts.peek().type == LPAREN:
                self._skip_group_body()
            else:
                if self._ts.peek().type == SEMICOLON:
                    self._ts.consume()

        self._ts.expect(RBRACE)
        if self._ts.peek().type == SEMICOLON:
            self._ts.consume()
        return tmpl

    # ------------------------------------------------------------------
    # Top-level
    # ------------------------------------------------------------------

    def parse_library(self) -> LibertyLibrary:
        """Parse the top-level ``library (NAME) { ... }`` group."""
        ts = self._ts

        # Skip any stray semicolons before the library group
        while ts.peek().type == SEMICOLON:
            ts.consume()

        if ts.peek().type == EOF:
            raise ParseError("empty input — no library group found")

        tok = ts.expect(IDENT)
        if tok.value != "library":
            raise ParseError(f"expected 'library' but got {tok.value!r}", tok.pos)

        name, name_pos = self._parse_name()
        lib_pos = SourcePos(line=tok.pos.line, col=tok.pos.col)
        ts.expect(LBRACE)

        lib = LibertyLibrary(name=name, pos=lib_pos)

        while ts.peek().type not in (RBRACE, EOF):
            tok = ts.peek()
            if tok.type != IDENT:
                ts.consume()
                continue

            key = tok.value
            key_pos = tok.pos
            ts.consume()

            if key == "cell":
                cell = self._parse_cell(key_pos)
                lib.cells.append(cell)
            elif key == "operating_conditions":
                oc = self._parse_operating_conditions(key_pos)
                lib.operating_conditions.append(oc)
            elif key == "lu_table_template":
                tmpl = self._parse_lu_table_template(key_pos)
                lib.lu_table_templates.append(tmpl)
            elif ts.peek().type in (COLON, NUMBER, STRING, IDENT):
                # simple attribute — consume and discard
                self._parse_attribute_value()
            elif ts.peek().type == LPAREN:
                # unknown group or paren-style attribute: technology (cmos);
                self._skip_group_body()
            elif ts.peek().type == LBRACE:
                self._skip_brace_body()
            else:
                if ts.peek().type == SEMICOLON:
                    ts.consume()

        ts.expect(RBRACE)
        return lib


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(text: str) -> LibertyLibrary:
    """Parse *text* as a Liberty library and return a :class:`LibertyLibrary`.

    Raises :class:`ParseError` on structural errors.
    """
    tokens = tokenise(text)
    ts = _TokenStream(tokens)
    parser = _Parser(ts)
    return parser.parse_library()


def parse_file(path: str | os.PathLike) -> LibertyLibrary:
    """Convenience wrapper: read *path* then call :func:`parse`."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return parse(text)
