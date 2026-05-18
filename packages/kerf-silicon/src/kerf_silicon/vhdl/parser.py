"""VHDL parser — IEEE 1076-2008 subset.

Recursive-descent.  Returns a :class:`~kerf_silicon.vhdl.ast.DesignFile`.

Supported constructs
--------------------
* ``library`` / ``use`` clauses
* ``entity … is generic(…); port(…); end entity;``
* ``architecture … of … is … begin … end architecture;``
* Signal / component declarations in the architecture declarative region
* Sequential statements: signal assignment (``<=``), variable assignment
  (``:=``), ``if``, ``case``, ``null``, ``return``
* Concurrent statements: process, component instantiation, generate
* Sensitivity lists, ``rising_edge`` / ``falling_edge`` calls
* Types: std_logic, std_logic_vector(N downto/to M), integer, bit, bit_vector,
  unsigned, signed, natural, positive, boolean, plus user-defined names
"""

from __future__ import annotations

from typing import Optional

from .ast import (
    Architecture,
    CaseStatement,
    ComponentDeclaration,
    ComponentInstantiation,
    DesignFile,
    Entity,
    GenerateStatement,
    Generic,
    IfStatement,
    LibraryClause,
    Port,
    PortMap,
    Process,
    Signal,
    SignalAssignment,
    TypeMark,
    UseClause,
    VariableAssignment,
    WhenBranch,
)
from .lexer import Lexer, Token, TokenKind


class ParseError(Exception):
    def __init__(self, message: str, token: Token) -> None:
        super().__init__(f"Line {token.line}, col {token.col}: {message} (got {token.value!r})")
        self.token = token


class Parser:
    """Parse *source* and return a :class:`~kerf_silicon.vhdl.ast.DesignFile`.

    Parameters
    ----------
    source:
        Full VHDL source text.
    """

    def __init__(self, source: str) -> None:
        lex = Lexer(source, skip_comments=True)
        self._tokens: list[Token] = lex.tokenise()
        self._pos: int = 0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse(self) -> DesignFile:
        df = DesignFile()
        while not self._at_eof():
            tok = self._peek()
            if tok.kind == TokenKind.KEYWORD:
                kw = tok.value.lower()
                if kw == "library":
                    df.library_clauses.append(self._parse_library_clause())
                elif kw == "use":
                    df.use_clauses.append(self._parse_use_clause())
                elif kw == "entity":
                    df.entities.append(self._parse_entity())
                elif kw == "architecture":
                    df.architectures.append(self._parse_architecture())
                elif kw == "package":
                    self._skip_until_end_unit()
                else:
                    self._advance()
            else:
                self._advance()
        return df

    # ------------------------------------------------------------------
    # Library / use
    # ------------------------------------------------------------------

    def _parse_library_clause(self) -> LibraryClause:
        kw = self._expect_keyword("library")
        names: list[str] = [self._expect_identifier()]
        while self._peek().kind == TokenKind.COMMA:
            self._advance()
            names.append(self._expect_identifier())
        self._expect(TokenKind.SEMICOLON)
        return LibraryClause(names=names, line=kw.line)

    def _parse_use_clause(self) -> UseClause:
        kw = self._expect_keyword("use")
        names: list[str] = [self._parse_selected_name()]
        while self._peek().kind == TokenKind.COMMA:
            self._advance()
            names.append(self._parse_selected_name())
        self._expect(TokenKind.SEMICOLON)
        return UseClause(selected_names=names, line=kw.line)

    def _parse_selected_name(self) -> str:
        parts: list[str] = [self._expect_identifier()]
        while self._peek().kind == TokenKind.DOT:
            self._advance()
            tok = self._peek()
            if tok.kind == TokenKind.KEYWORD and tok.value.lower() == "all":
                parts.append(self._advance().value)
            else:
                parts.append(self._expect_identifier())
        return ".".join(parts)

    # ------------------------------------------------------------------
    # Entity
    # ------------------------------------------------------------------

    def _parse_entity(self) -> Entity:
        kw = self._expect_keyword("entity")
        name = self._expect_identifier()
        self._expect_keyword("is")
        generics: list[Generic] = []
        ports: list[Port] = []

        # Optional generic clause
        if self._peek_keyword("generic"):
            generics = self._parse_generic_clause()

        # Optional port clause
        if self._peek_keyword("port"):
            ports = self._parse_port_clause()

        # Trailing declarations (attribute, …) — skip
        while not (self._peek_keyword("end") or self._at_eof()):
            self._advance()

        self._expect_keyword("end")
        # Optional 'entity' keyword and name after end
        if self._peek_keyword("entity"):
            self._advance()
        if self._peek().kind == TokenKind.IDENTIFIER:
            self._advance()
        self._expect(TokenKind.SEMICOLON)
        return Entity(name=name, generics=generics, ports=ports, line=kw.line)

    def _parse_generic_clause(self) -> list[Generic]:
        self._expect_keyword("generic")
        self._expect(TokenKind.LPAREN)
        generics: list[Generic] = []
        while not (self._peek().kind == TokenKind.RPAREN or self._at_eof()):
            generics.extend(self._parse_interface_element_list("generic"))
            if self._peek().kind == TokenKind.SEMICOLON:
                self._advance()
            else:
                break
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.SEMICOLON)
        return generics

    def _parse_port_clause(self) -> list[Port]:
        self._expect_keyword("port")
        self._expect(TokenKind.LPAREN)
        ports: list[Port] = []
        while not (self._peek().kind == TokenKind.RPAREN or self._at_eof()):
            ports.extend(self._parse_interface_element_list("port"))
            if self._peek().kind == TokenKind.SEMICOLON:
                self._advance()
            else:
                break
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.SEMICOLON)
        return ports

    def _parse_interface_element_list(self, kind: str):
        """Parse one or more names in a port/generic declaration group."""
        tok = self._peek()
        # skip optional 'signal' / 'constant' / 'variable' keyword
        if tok.kind == TokenKind.KEYWORD and tok.value.lower() in (
            "signal", "constant", "variable", "in", "out", "inout", "buffer",
        ):
            # Only consume if it looks like a qualifier, not a direction
            if tok.value.lower() in ("signal", "constant", "variable"):
                self._advance()

        names: list[str] = [self._expect_identifier()]
        while self._peek().kind == TokenKind.COMMA:
            self._advance()
            names.append(self._expect_identifier())
        self._expect(TokenKind.COLON)

        direction = "in"
        if kind == "port":
            if self._peek().kind == TokenKind.KEYWORD and self._peek().value.lower() in (
                "in", "out", "inout", "buffer", "linkage",
            ):
                direction = self._advance().value.lower()
        elif self._peek().kind == TokenKind.KEYWORD and self._peek().value.lower() in ("in", "out"):
            # Tolerate spurious direction on generics
            direction = self._advance().value.lower()

        type_mark = self._parse_type_mark()
        default: Optional[str] = None
        if self._peek().kind == TokenKind.ASSIGN:
            self._advance()
            default = self._collect_expression_until({TokenKind.SEMICOLON, TokenKind.RPAREN})

        if kind == "port":
            return [
                Port(name=n, direction=direction, type_mark=type_mark, default=default, line=tok.line)
                for n in names
            ]
        else:
            return [
                Generic(name=n, type_mark=type_mark, default=default, line=tok.line)
                for n in names
            ]

    # ------------------------------------------------------------------
    # Architecture
    # ------------------------------------------------------------------

    def _parse_architecture(self) -> Architecture:
        kw = self._expect_keyword("architecture")
        name = self._expect_identifier()
        self._expect_keyword("of")
        entity_name = self._expect_identifier()
        self._expect_keyword("is")

        declarations: list = []
        statements: list = []

        # Declarative region
        while not (self._peek_keyword("begin") or self._at_eof()):
            tok = self._peek()
            if tok.kind == TokenKind.KEYWORD:
                kw2 = tok.value.lower()
                if kw2 == "signal":
                    declarations.append(self._parse_signal_decl())
                elif kw2 == "component":
                    declarations.append(self._parse_component_decl())
                elif kw2 in ("type", "subtype", "constant", "shared", "attribute",
                             "alias", "file"):
                    self._skip_to_semicolon()
                else:
                    self._advance()
            else:
                self._advance()

        self._expect_keyword("begin")

        # Statement region
        while not (self._peek_keyword("end") or self._at_eof()):
            stmt = self._parse_concurrent_statement()
            if stmt is not None:
                statements.append(stmt)

        self._expect_keyword("end")
        if self._peek_keyword("architecture"):
            self._advance()
        if self._peek().kind == TokenKind.IDENTIFIER:
            self._advance()
        self._expect(TokenKind.SEMICOLON)
        return Architecture(
            name=name,
            entity_name=entity_name,
            declarations=declarations,
            statements=statements,
            line=kw.line,
        )

    def _parse_signal_decl(self) -> Signal:
        kw = self._expect_keyword("signal")
        name = self._expect_identifier()
        self._expect(TokenKind.COLON)
        type_mark = self._parse_type_mark()
        default: Optional[str] = None
        if self._peek().kind == TokenKind.ASSIGN:
            self._advance()
            default = self._collect_expression_until({TokenKind.SEMICOLON})
        self._expect(TokenKind.SEMICOLON)
        return Signal(name=name, type_mark=type_mark, default=default, line=kw.line)

    def _parse_component_decl(self) -> ComponentDeclaration:
        kw = self._expect_keyword("component")
        name = self._expect_identifier()
        if self._peek_keyword("is"):
            self._advance()
        generics: list[Generic] = []
        ports: list[Port] = []
        if self._peek_keyword("generic"):
            generics = self._parse_generic_clause()
        if self._peek_keyword("port"):
            ports = self._parse_port_clause()
        self._expect_keyword("end")
        if self._peek_keyword("component"):
            self._advance()
        if self._peek().kind == TokenKind.IDENTIFIER:
            self._advance()
        self._expect(TokenKind.SEMICOLON)
        return ComponentDeclaration(name=name, generics=generics, ports=ports, line=kw.line)

    # ------------------------------------------------------------------
    # Concurrent statements
    # ------------------------------------------------------------------

    def _parse_concurrent_statement(self):
        tok = self._peek()

        if tok.kind == TokenKind.KEYWORD:
            kw = tok.value.lower()
            if kw == "process":
                return self._parse_process(label=None)
            elif kw in ("assert", "report", "null", "with", "when"):
                self._skip_to_semicolon()
                return None
            else:
                self._advance()
                return None

        if tok.kind == TokenKind.IDENTIFIER:
            # Could be:
            #   label : process …
            #   label : ComponentName port map …
            #   label : for … generate …
            #   signal_name <= expr ;    (concurrent signal assignment)
            saved_pos = self._pos
            label_tok = self._advance()
            if self._peek().kind == TokenKind.COLON:
                self._advance()  # consume ':'
                next_tok = self._peek()
                if next_tok.kind == TokenKind.KEYWORD and next_tok.value.lower() == "process":
                    return self._parse_process(label=label_tok.value)
                elif next_tok.kind == TokenKind.KEYWORD and next_tok.value.lower() == "for":
                    return self._parse_generate(label=label_tok.value)
                elif next_tok.kind == TokenKind.KEYWORD and next_tok.value.lower() == "if":
                    # if-generate (VHDL 2008)
                    return self._parse_if_generate(label=label_tok.value)
                elif next_tok.kind == TokenKind.KEYWORD and next_tok.value.lower() == "entity":
                    # direct entity instantiation
                    return self._parse_component_instantiation(label=label_tok.value, direct=True)
                elif next_tok.kind == TokenKind.KEYWORD and next_tok.value.lower() == "component":
                    self._advance()  # consume 'component'
                    return self._parse_component_instantiation(label=label_tok.value, direct=False)
                elif next_tok.kind == TokenKind.IDENTIFIER:
                    # label : ComponentName port map
                    return self._parse_component_instantiation(label=label_tok.value, direct=False)
                else:
                    # Unknown — skip
                    self._skip_to_semicolon()
                    return None
            elif self._peek().kind == TokenKind.SIGNAL_ASSIGN:
                # Concurrent signal assignment (no label)
                self._advance()  # consume <=
                expr = self._collect_expression_until({TokenKind.SEMICOLON})
                self._expect(TokenKind.SEMICOLON)
                return SignalAssignment(target=label_tok.value, expression=expr, line=label_tok.line)
            else:
                # Back up and skip
                self._pos = saved_pos
                self._skip_to_semicolon()
                return None

        # Fallback
        self._advance()
        return None

    def _parse_process(self, label: Optional[str]) -> Process:
        kw = self._expect_keyword("process")
        sensitivity: list[str] = []
        if self._peek().kind == TokenKind.LPAREN:
            self._advance()
            while self._peek().kind != TokenKind.RPAREN and not self._at_eof():
                tok = self._peek()
                if tok.kind in (TokenKind.IDENTIFIER, TokenKind.KEYWORD):
                    name = self._advance().value
                    # Allow foo'event etc — skip attribute
                    if self._peek().kind == TokenKind.TICK:
                        self._advance()
                        self._advance()  # attribute name
                    sensitivity.append(name)
                elif tok.kind == TokenKind.COMMA:
                    self._advance()
                else:
                    self._advance()
            self._expect(TokenKind.RPAREN)

        # Optional 'is'
        if self._peek_keyword("is"):
            self._advance()

        declarations: list = []
        # Variable declarations before begin
        while not (self._peek_keyword("begin") or self._at_eof()):
            tok = self._peek()
            if tok.kind == TokenKind.KEYWORD and tok.value.lower() == "variable":
                self._skip_to_semicolon()
            else:
                self._advance()

        self._expect_keyword("begin")
        statements: list = []
        while not (self._peek_keyword("end") or self._at_eof()):
            stmt = self._parse_sequential_statement()
            if stmt is not None:
                statements.append(stmt)

        self._expect_keyword("end")
        if self._peek_keyword("process"):
            self._advance()
        if self._peek().kind == TokenKind.IDENTIFIER:
            self._advance()
        self._expect(TokenKind.SEMICOLON)
        return Process(
            sensitivity_list=sensitivity,
            declarations=declarations,
            statements=statements,
            label=label,
            line=kw.line,
        )

    def _parse_generate(self, label: str) -> GenerateStatement:
        kw = self._expect_keyword("for")
        scheme_parts: list[str] = ["for"]
        while not self._peek_keyword("generate") and not self._at_eof():
            scheme_parts.append(self._advance().value)
        scheme = " ".join(scheme_parts)
        self._expect_keyword("generate")
        stmts: list = []
        while not (self._peek_keyword("end") or self._at_eof()):
            stmt = self._parse_concurrent_statement()
            if stmt is not None:
                stmts.append(stmt)
        self._expect_keyword("end")
        if self._peek_keyword("generate"):
            self._advance()
        if self._peek().kind == TokenKind.IDENTIFIER:
            self._advance()
        self._expect(TokenKind.SEMICOLON)
        return GenerateStatement(label=label, scheme=scheme, statements=stmts, line=kw.line)

    def _parse_if_generate(self, label: str) -> GenerateStatement:
        kw = self._expect_keyword("if")
        scheme_parts: list[str] = ["if"]
        while not self._peek_keyword("generate") and not self._at_eof():
            scheme_parts.append(self._advance().value)
        scheme = " ".join(scheme_parts)
        self._expect_keyword("generate")
        stmts: list = []
        while not (self._peek_keyword("end") or self._at_eof()):
            stmt = self._parse_concurrent_statement()
            if stmt is not None:
                stmts.append(stmt)
        self._expect_keyword("end")
        if self._peek_keyword("generate"):
            self._advance()
        if self._peek().kind == TokenKind.IDENTIFIER:
            self._advance()
        self._expect(TokenKind.SEMICOLON)
        return GenerateStatement(label=label, scheme=scheme, statements=stmts, line=kw.line)

    def _parse_component_instantiation(
        self, label: str, direct: bool
    ) -> ComponentInstantiation:
        comp_tok = self._peek()
        if direct:
            # entity lib.name(arch)
            self._advance()  # 'entity'
            comp_name_parts = [self._expect_identifier()]
            if self._peek().kind == TokenKind.DOT:
                self._advance()
                comp_name_parts.append(self._expect_identifier())
            # optional architecture name in parens
            if self._peek().kind == TokenKind.LPAREN:
                self._advance()
                self._expect_identifier()
                self._expect(TokenKind.RPAREN)
            comp_name = ".".join(comp_name_parts)
        else:
            comp_name = self._expect_identifier()

        generic_map: list[PortMap] = []
        port_map: list[PortMap] = []

        if self._peek_keyword("generic"):
            self._advance()
            self._expect_keyword("map")
            self._expect(TokenKind.LPAREN)
            generic_map = self._parse_association_list()
            self._expect(TokenKind.RPAREN)

        if self._peek_keyword("port"):
            self._advance()
            self._expect_keyword("map")
            self._expect(TokenKind.LPAREN)
            port_map = self._parse_association_list()
            self._expect(TokenKind.RPAREN)

        self._expect(TokenKind.SEMICOLON)
        return ComponentInstantiation(
            label=label,
            component_name=comp_name,
            generic_map=generic_map,
            port_map=port_map,
            line=comp_tok.line,
        )

    def _parse_association_list(self) -> list[PortMap]:
        maps: list[PortMap] = []
        while not (self._peek().kind == TokenKind.RPAREN or self._at_eof()):
            tok = self._peek()
            # Try to detect  formal => actual  vs positional  actual
            saved = self._pos
            raw = self._collect_expression_until(
                {TokenKind.COMMA, TokenKind.RPAREN, TokenKind.ASSOC}
            )
            if self._peek().kind == TokenKind.ASSOC:
                formal = raw.strip()
                self._advance()  # consume =>
                actual = self._collect_expression_until({TokenKind.COMMA, TokenKind.RPAREN})
                maps.append(PortMap(formal=formal, actual=actual.strip(), line=tok.line))
            else:
                maps.append(PortMap(formal=None, actual=raw.strip(), line=tok.line))
            if self._peek().kind == TokenKind.COMMA:
                self._advance()
        return maps

    # ------------------------------------------------------------------
    # Sequential statements
    # ------------------------------------------------------------------

    def _parse_sequential_statement(self):
        tok = self._peek()
        if tok.kind == TokenKind.KEYWORD:
            kw = tok.value.lower()
            if kw == "if":
                return self._parse_if_statement()
            elif kw == "case":
                return self._parse_case_statement()
            elif kw in ("null", "wait", "assert", "report", "return", "exit",
                        "next", "raise"):
                self._skip_to_semicolon()
                return None
            else:
                self._advance()
                return None

        if tok.kind == TokenKind.IDENTIFIER:
            return self._parse_assignment_or_call()

        self._advance()
        return None

    def _parse_assignment_or_call(self):
        """signal <= expr;  |  var := expr;  |  procedure_call(…);"""
        tok = self._peek()
        target_parts: list[str] = [self._advance().value]

        # Allow indexed / selected names: foo(3), foo.bar, foo(3 downto 0)
        while self._peek().kind in (TokenKind.DOT, TokenKind.LPAREN):
            if self._peek().kind == TokenKind.DOT:
                target_parts.append(self._advance().value)
                target_parts.append(self._advance().value)
            else:
                # collect the bracketed part
                target_parts.append(self._advance().value)  # (
                depth = 1
                while depth and not self._at_eof():
                    t = self._advance()
                    target_parts.append(t.value)
                    if t.kind == TokenKind.LPAREN:
                        depth += 1
                    elif t.kind == TokenKind.RPAREN:
                        depth -= 1

        target = "".join(target_parts)

        if self._peek().kind == TokenKind.SIGNAL_ASSIGN:
            self._advance()
            # Collect until semicolon (respect parens)
            expr = self._collect_expression_until({TokenKind.SEMICOLON})
            self._expect(TokenKind.SEMICOLON)
            return SignalAssignment(target=target, expression=expr.strip(), line=tok.line)

        if self._peek().kind == TokenKind.ASSIGN:
            self._advance()
            expr = self._collect_expression_until({TokenKind.SEMICOLON})
            self._expect(TokenKind.SEMICOLON)
            return VariableAssignment(target=target, expression=expr.strip(), line=tok.line)

        # Procedure call or something else — skip to semicolon
        self._skip_to_semicolon()
        return None

    def _parse_if_statement(self) -> IfStatement:
        kw = self._expect_keyword("if")
        condition = self._collect_expression_until_keyword("then")
        self._expect_keyword("then")
        then_stmts: list = []
        while not (self._peek_keyword("elsif") or self._peek_keyword("else")
                   or self._peek_keyword("end") or self._at_eof()):
            s = self._parse_sequential_statement()
            if s is not None:
                then_stmts.append(s)

        elsif_branches: list[tuple[str, list]] = []
        while self._peek_keyword("elsif"):
            self._advance()
            ec = self._collect_expression_until_keyword("then")
            self._expect_keyword("then")
            e_stmts: list = []
            while not (self._peek_keyword("elsif") or self._peek_keyword("else")
                       or self._peek_keyword("end") or self._at_eof()):
                s = self._parse_sequential_statement()
                if s is not None:
                    e_stmts.append(s)
            elsif_branches.append((ec, e_stmts))

        else_stmts: list = []
        if self._peek_keyword("else"):
            self._advance()
            while not (self._peek_keyword("end") or self._at_eof()):
                s = self._parse_sequential_statement()
                if s is not None:
                    else_stmts.append(s)

        self._expect_keyword("end")
        self._expect_keyword("if")
        self._expect(TokenKind.SEMICOLON)
        return IfStatement(
            condition=condition.strip(),
            then_stmts=then_stmts,
            elsif_branches=elsif_branches,
            else_stmts=else_stmts,
            line=kw.line,
        )

    def _parse_case_statement(self) -> CaseStatement:
        kw = self._expect_keyword("case")
        expr = self._collect_expression_until_keyword("is")
        self._expect_keyword("is")
        branches: list[WhenBranch] = []
        while self._peek_keyword("when") and not self._at_eof():
            wb = self._parse_when_branch()
            branches.append(wb)
        self._expect_keyword("end")
        self._expect_keyword("case")
        self._expect(TokenKind.SEMICOLON)
        return CaseStatement(expression=expr.strip(), branches=branches, line=kw.line)

    def _parse_when_branch(self) -> WhenBranch:
        kw = self._expect_keyword("when")
        choices: list[str] = []
        raw = self._collect_expression_until({TokenKind.ASSOC})
        choices = [c.strip() for c in raw.split("|") if c.strip()]
        self._expect(TokenKind.ASSOC)
        stmts: list = []
        while not (self._peek_keyword("when") or self._peek_keyword("end") or self._at_eof()):
            s = self._parse_sequential_statement()
            if s is not None:
                stmts.append(s)
        return WhenBranch(choices=choices, stmts=stmts, line=kw.line)

    # ------------------------------------------------------------------
    # Type parsing
    # ------------------------------------------------------------------

    def _parse_type_mark(self) -> TypeMark:
        tok = self._peek()
        # Base type name — could be a keyword (e.g. 'integer') or identifier
        if tok.kind in (TokenKind.IDENTIFIER, TokenKind.KEYWORD):
            name = self._advance().value.lower()
        else:
            raise ParseError("Expected type name", tok)

        # Handle qualified names: std_logic_1164.std_logic (rare but valid)
        if self._peek().kind == TokenKind.DOT:
            self._advance()
            name += "." + self._advance().value.lower()

        constraint: Optional[str] = None
        # Constraint: parenthesised range e.g. (7 downto 0) or (0 to 7)
        if self._peek().kind == TokenKind.LPAREN:
            constraint = self._collect_balanced_parens()
        # Keyword-range: integer range 0 to 255
        elif self._peek_keyword("range"):
            self._advance()
            range_parts: list[str] = []
            while self._peek().kind not in (
                TokenKind.SEMICOLON, TokenKind.RPAREN, TokenKind.COMMA,
                TokenKind.ASSIGN,
            ) and not self._at_eof():
                range_parts.append(self._advance().value)
            constraint = "range " + " ".join(range_parts)

        return TypeMark(name=name, constraint=constraint, line=tok.line)

    # ------------------------------------------------------------------
    # Expression / collection helpers
    # ------------------------------------------------------------------

    def _collect_expression_until(self, stop_kinds: set[TokenKind]) -> str:
        """Collect tokens as raw text until one of *stop_kinds* is next.

        Respects balanced parentheses — stop tokens inside parens are ignored.
        """
        parts: list[str] = []
        depth = 0
        while not self._at_eof():
            tok = self._peek()
            if tok.kind == TokenKind.LPAREN:
                depth += 1
                parts.append(self._advance().value)
            elif tok.kind == TokenKind.RPAREN:
                if depth == 0:
                    break
                depth -= 1
                parts.append(self._advance().value)
            elif tok.kind in stop_kinds and depth == 0:
                break
            else:
                parts.append(self._advance().value)
        return " ".join(parts)

    def _collect_expression_until_keyword(self, kw: str) -> str:
        """Collect tokens as text until the keyword *kw* is next (depth-aware)."""
        parts: list[str] = []
        depth = 0
        while not self._at_eof():
            tok = self._peek()
            if tok.kind == TokenKind.LPAREN:
                depth += 1
                parts.append(self._advance().value)
            elif tok.kind == TokenKind.RPAREN:
                if depth == 0:
                    break
                depth -= 1
                parts.append(self._advance().value)
            elif (tok.kind == TokenKind.KEYWORD
                  and tok.value.lower() == kw
                  and depth == 0):
                break
            else:
                parts.append(self._advance().value)
        return " ".join(parts)

    def _collect_balanced_parens(self) -> str:
        """Collect a parenthesised expression including the outer parens."""
        self._expect(TokenKind.LPAREN)
        parts: list[str] = []
        depth = 1
        while depth and not self._at_eof():
            tok = self._advance()
            parts.append(tok.value)
            if tok.kind == TokenKind.LPAREN:
                depth += 1
            elif tok.kind == TokenKind.RPAREN:
                depth -= 1
        # Drop the closing paren we just consumed (it's in parts[-1])
        if parts:
            parts.pop()
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Low-level token stream helpers
    # ------------------------------------------------------------------

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        if tok.kind != TokenKind.EOF:
            self._pos += 1
        return tok

    def _at_eof(self) -> bool:
        return self._tokens[self._pos].kind == TokenKind.EOF

    def _peek_keyword(self, kw: str) -> bool:
        tok = self._peek()
        return tok.kind == TokenKind.KEYWORD and tok.value.lower() == kw

    def _expect(self, kind: TokenKind) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            raise ParseError(f"Expected {kind.name}", tok)
        return self._advance()

    def _expect_keyword(self, kw: str) -> Token:
        tok = self._peek()
        if not (tok.kind == TokenKind.KEYWORD and tok.value.lower() == kw):
            raise ParseError(f"Expected keyword '{kw}'", tok)
        return self._advance()

    def _expect_identifier(self) -> str:
        tok = self._peek()
        if tok.kind not in (TokenKind.IDENTIFIER, TokenKind.KEYWORD):
            raise ParseError("Expected identifier", tok)
        return self._advance().value

    def _skip_to_semicolon(self) -> None:
        """Consume tokens up to and including the next semicolon."""
        depth = 0
        while not self._at_eof():
            tok = self._advance()
            if tok.kind == TokenKind.LPAREN:
                depth += 1
            elif tok.kind == TokenKind.RPAREN:
                depth -= 1
            elif tok.kind == TokenKind.SEMICOLON and depth == 0:
                return

    def _skip_until_end_unit(self) -> None:
        """Skip until 'end' keyword followed by semicolon at nesting level 0."""
        depth = 0
        while not self._at_eof():
            tok = self._advance()
            if tok.kind == TokenKind.KEYWORD:
                kw = tok.value.lower()
                if kw in ("entity", "architecture", "package", "process",
                           "case", "if", "generate", "loop", "protected",
                           "record", "block", "component", "function",
                           "procedure"):
                    depth += 1
                elif kw == "end":
                    if depth == 0:
                        # consume optional label/name then semicolon
                        if self._peek().kind in (TokenKind.KEYWORD, TokenKind.IDENTIFIER):
                            self._advance()
                        if self._peek().kind == TokenKind.SEMICOLON:
                            self._advance()
                        return
                    depth -= 1
