"""Recursive-descent parser for the atopile `.ato` language.

Entry point::

    from kerf_electronics.atopile.parser import parse
    ast_root = parse(source_text)

Returns a :class:`~kerf_electronics.atopile.ast.Module` root node.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .ast import (
    Assignment,
    ComponentBlock,
    ComponentInstance,
    Connection,
    DottedName,
    Identifier,
    ImportStatement,
    InterfaceBlock,
    ModuleBlock,
    Module,
    ParameterDecl,
    PinDecl,
    QuantityLiteral,
    SignalDecl,
    SourceLoc,
    StringLiteral,
)
from .lexer import TK, Token, tokenise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNIT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)(.*)")

# SI prefix multipliers (only what atopile commonly uses)
_SI_MULTIPLIERS: dict[str, float] = {
    "T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
}

# Common base units (everything else after stripping a prefix)
_BASE_UNITS = {
    "ohm", "Ohm", "OHM", "F", "H", "V", "A", "W", "Hz", "m",
}


def _parse_quantity(raw: str, loc: SourceLoc) -> QuantityLiteral:
    """Parse a raw number string like ``10kohm``, ``100nF``, ``3.3`` into a
    :class:`QuantityLiteral`.
    """
    m = _UNIT_RE.match(raw)
    if not m:
        raise ParseError(f"Cannot parse quantity {raw!r}", loc)
    num_str, suffix = m.group(1), m.group(2)
    num = float(num_str)
    # Apply SI prefix if present
    if suffix and suffix[0] in _SI_MULTIPLIERS:
        # Check it's really a prefix (rest is a base unit or nothing)
        num *= _SI_MULTIPLIERS[suffix[0]]
        unit = suffix[1:]
    else:
        unit = suffix
    return QuantityLiteral(value=num, unit=unit, raw=raw, loc=loc)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class ParseError(Exception):
    def __init__(self, msg: str, loc: SourceLoc):
        super().__init__(f"{msg} at {loc}")
        self.loc = loc


class Parser:
    def __init__(self, tokens: List[Token]):
        self._tokens = tokens
        self._pos = 0

    # ------------------------------------------------------------------
    # Token navigation
    # ------------------------------------------------------------------

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _peek_kind(self) -> TK:
        return self._tokens[self._pos].kind

    def _at(self, *kinds: TK) -> bool:
        return self._peek_kind() in kinds

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        if tok.kind != TK.EOF:
            self._pos += 1
        return tok

    def _expect(self, kind: TK) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            raise ParseError(
                f"Expected {kind.name} but got {tok.kind.name} ({tok.value!r})",
                SourceLoc(tok.line, tok.col),
            )
        return self._advance()

    def _loc(self) -> SourceLoc:
        tok = self._peek()
        return SourceLoc(tok.line, tok.col)

    def _skip_newlines(self) -> None:
        while self._at(TK.NEWLINE):
            self._advance()

    # ------------------------------------------------------------------
    # Grammar rules
    # ------------------------------------------------------------------

    def parse_module(self) -> Module:
        root = Module()
        self._skip_newlines()
        while not self._at(TK.EOF):
            if self._at(TK.IMPORT):
                root.imports.append(self._parse_import())
            elif self._at(TK.MODULE):
                root.blocks.append(self._parse_module_block())
            elif self._at(TK.COMPONENT):
                root.blocks.append(self._parse_component_block())
            elif self._at(TK.INTERFACE):
                root.blocks.append(self._parse_interface_block())
            elif self._at(TK.NEWLINE):
                self._advance()
            else:
                tok = self._peek()
                raise ParseError(
                    f"Unexpected top-level token {tok.kind.name} ({tok.value!r})",
                    SourceLoc(tok.line, tok.col),
                )
        return root

    # ------------------------------------------------------------------

    def _parse_import(self) -> ImportStatement:
        loc = self._loc()
        self._expect(TK.IMPORT)
        name_tok = self._expect(TK.IDENT)
        self._expect(TK.FROM)
        path_tok = self._expect(TK.STRING)
        if self._at(TK.NEWLINE):
            self._advance()
        return ImportStatement(name=name_tok.value, path=path_tok.value, loc=loc)

    # ------------------------------------------------------------------

    def _parse_block_header(
        self, keyword: TK
    ) -> tuple[str, Optional[str], SourceLoc]:
        """Parse ``<keyword> <Name> [from <Base>]:`` and return (name, base, loc)."""
        loc = self._loc()
        self._expect(keyword)
        name_tok = self._expect(TK.IDENT)
        base: Optional[str] = None
        if self._at(TK.FROM):
            self._advance()
            base_tok = self._expect(TK.IDENT)
            base = base_tok.value
        self._expect(TK.COLON)
        if self._at(TK.NEWLINE):
            self._advance()
        return name_tok.value, base, loc

    def _parse_block_body(self) -> List[object]:
        self._expect(TK.INDENT)
        self._skip_newlines()
        body: List[object] = []
        while not self._at(TK.DEDENT, TK.EOF):
            stmt = self._parse_statement()
            if stmt is not None:
                body.append(stmt)
            self._skip_newlines()
        if self._at(TK.DEDENT):
            self._advance()
        return body

    def _parse_module_block(self) -> ModuleBlock:
        name, base, loc = self._parse_block_header(TK.MODULE)
        body = self._parse_block_body()
        return ModuleBlock(name=name, base=base, body=body, loc=loc)

    def _parse_component_block(self) -> ComponentBlock:
        name, base, loc = self._parse_block_header(TK.COMPONENT)
        body = self._parse_block_body()
        return ComponentBlock(name=name, base=base, body=body, loc=loc)

    def _parse_interface_block(self) -> InterfaceBlock:
        name, base, loc = self._parse_block_header(TK.INTERFACE)
        body = self._parse_block_body()
        return InterfaceBlock(name=name, base=base, body=body, loc=loc)

    # ------------------------------------------------------------------

    def _parse_statement(self) -> Optional[object]:
        """Parse a single statement inside a block body."""
        tok = self._peek()

        if tok.kind == TK.NEWLINE:
            self._advance()
            return None

        if tok.kind == TK.SIGNAL:
            return self._parse_signal_decl()

        if tok.kind == TK.PIN:
            return self._parse_pin_decl()

        if tok.kind == TK.MODULE:
            return self._parse_module_block()

        if tok.kind == TK.COMPONENT:
            return self._parse_component_block()

        if tok.kind == TK.INTERFACE:
            return self._parse_interface_block()

        # Must be an identifier-led statement: assignment, component_instance,
        # connection, or parameter declaration.
        if tok.kind == TK.IDENT:
            return self._parse_ident_led_stmt()

        raise ParseError(
            f"Unexpected statement token {tok.kind.name} ({tok.value!r})",
            SourceLoc(tok.line, tok.col),
        )

    def _parse_signal_decl(self) -> SignalDecl:
        loc = self._loc()
        self._expect(TK.SIGNAL)
        name_tok = self._expect(TK.IDENT)
        if self._at(TK.NEWLINE):
            self._advance()
        return SignalDecl(name=name_tok.value, loc=loc)

    def _parse_pin_decl(self) -> PinDecl:
        loc = self._loc()
        self._expect(TK.PIN)
        name_tok = self._expect(TK.IDENT)
        if self._at(TK.NEWLINE):
            self._advance()
        return PinDecl(name=name_tok.value, loc=loc)

    # ------------------------------------------------------------------
    # Identifier-led statements
    # ------------------------------------------------------------------

    def _parse_dotted_name(self) -> DottedName:
        """Parse ``name(.name)*`` — stops before any non-DOT token."""
        tok = self._peek()
        loc = SourceLoc(tok.line, tok.col)
        parts: List[str] = []
        first = self._expect(TK.IDENT)
        parts.append(first.value)
        while self._at(TK.DOT):
            self._advance()  # consume '.'
            part = self._expect(TK.IDENT)
            parts.append(part.value)
        return DottedName(parts=parts, loc=loc)

    def _parse_value(self) -> object:
        """Parse a rhs value: number literal, string literal, or identifier."""
        tok = self._peek()
        loc = SourceLoc(tok.line, tok.col)

        if tok.kind == TK.NUMBER:
            self._advance()
            return _parse_quantity(tok.value, loc)

        if tok.kind == TK.STRING:
            self._advance()
            return StringLiteral(value=tok.value, loc=loc)

        if tok.kind == TK.IDENT:
            self._advance()
            return Identifier(name=tok.value, loc=loc)

        raise ParseError(
            f"Expected value (number, string or identifier), got {tok.kind.name}",
            loc,
        )

    def _parse_ident_led_stmt(self) -> object:
        """Parse a statement that begins with an identifier.

        Possibilities:
          - ``name = new TypeName``          → ComponentInstance
          - ``name.attr = <value>``           → Assignment
          - ``name = <value>``                → Assignment
          - ``name.attr ~ other.attr``        → Connection
          - ``name: TypeName``                → ParameterDecl
        """
        loc = self._loc()
        lhs = self._parse_dotted_name()

        tok = self._peek()

        # Connection  ``lhs ~ rhs``
        if tok.kind == TK.TILDE:
            self._advance()
            rhs = self._parse_dotted_name()
            if self._at(TK.NEWLINE):
                self._advance()
            return Connection(left=lhs, right=rhs, loc=loc)

        # Assignment or ComponentInstance  ``lhs = ...``
        if tok.kind == TK.EQUALS:
            self._advance()
            # ``= new TypeName``
            if self._at(TK.NEW):
                self._advance()
                type_tok = self._expect(TK.IDENT)
                if self._at(TK.NEWLINE):
                    self._advance()
                return ComponentInstance(
                    instance_name=lhs.name,
                    type_name=type_tok.value,
                    loc=loc,
                )
            # ordinary assignment
            value = self._parse_value()
            if self._at(TK.NEWLINE):
                self._advance()
            return Assignment(target=lhs, value=value, loc=loc)

        # Parameter declaration  ``lhs : TypeName``
        if tok.kind == TK.COLON:
            self._advance()
            type_tok = self._expect(TK.IDENT)
            default = None
            if self._at(TK.EQUALS):
                self._advance()
                default = self._parse_value()
            if self._at(TK.NEWLINE):
                self._advance()
            return ParameterDecl(
                name=lhs.name,
                type_name=type_tok.value,
                default=default,
                loc=loc,
            )

        raise ParseError(
            f"Unexpected token {tok.kind.name} after identifier",
            SourceLoc(tok.line, tok.col),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(source: str) -> Module:
    """Parse *source* (the text of a `.ato` file) and return an AST root.

    Raises :class:`ParseError` on syntax errors.
    """
    tokens = tokenise(source)
    return Parser(tokens).parse_module()
