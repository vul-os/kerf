"""Tests for the VHDL lexer (IEEE 1076-2008 subset)."""

from __future__ import annotations

import os
import pytest

from kerf_silicon.vhdl.lexer import Lexer, Token, TokenKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _lex(src: str, *, skip_comments: bool = True) -> list[Token]:
    return Lexer(src, skip_comments=skip_comments).tokenise()


def _kinds(tokens: list[Token]) -> list[TokenKind]:
    return [t.kind for t in tokens]


def _values_of_kind(tokens: list[Token], kind: TokenKind) -> list[str]:
    return [t.value for t in tokens if t.kind == kind]


# ---------------------------------------------------------------------------
# Basic tokenisation
# ---------------------------------------------------------------------------

class TestBasicTokens:
    def test_keywords_case_insensitive(self):
        tokens = _lex("Entity ENTITY entity")
        kinds = _kinds(tokens)
        # All three should be KEYWORD, then EOF
        assert kinds == [TokenKind.KEYWORD, TokenKind.KEYWORD, TokenKind.KEYWORD, TokenKind.EOF]
        assert all(t.value.lower() == "entity" for t in tokens[:-1])

    def test_identifier(self):
        tokens = _lex("my_signal")
        assert tokens[0].kind == TokenKind.IDENTIFIER
        assert tokens[0].value == "my_signal"

    def test_integer_literal(self):
        tokens = _lex("42")
        assert tokens[0].kind == TokenKind.INTEGER
        assert tokens[0].value == "42"

    def test_integer_with_underscores(self):
        tokens = _lex("1_000_000")
        assert tokens[0].kind == TokenKind.INTEGER

    def test_string_literal(self):
        tokens = _lex('"hello world"')
        assert tokens[0].kind == TokenKind.STRING
        assert tokens[0].value == '"hello world"'

    def test_char_literal_std_logic(self):
        for ch in ("'0'", "'1'", "'Z'", "'X'", "'L'", "'H'", "'-'", "'U'", "'W'"):
            tokens = _lex(ch)
            assert tokens[0].kind == TokenKind.CHAR_LITERAL, f"Failed for {ch}"

    def test_char_literal_ordinary(self):
        tokens = _lex("'a'")
        assert tokens[0].kind == TokenKind.CHAR_LITERAL


# ---------------------------------------------------------------------------
# Comment handling
# ---------------------------------------------------------------------------

class TestComments:
    def test_comment_skipped_by_default(self):
        tokens = _lex("a <= b; -- this is a comment\nc <= d;")
        kinds = _kinds(tokens)
        assert TokenKind.COMMENT not in kinds

    def test_comment_retained_when_requested(self):
        tokens = _lex("a <= b; -- this is a comment", skip_comments=False)
        kinds = _kinds(tokens)
        assert TokenKind.COMMENT in kinds

    def test_comment_value_contains_text(self):
        tokens = _lex("-- check hex X\"AB\"", skip_comments=False)
        comment_tokens = [t for t in tokens if t.kind == TokenKind.COMMENT]
        assert len(comment_tokens) == 1
        assert "hex" in comment_tokens[0].value

    def test_comment_does_not_bleed_into_next_line(self):
        src = "-- comment line\nentity foo is"
        tokens = _lex(src)
        assert tokens[0].kind == TokenKind.KEYWORD
        assert tokens[0].value.lower() == "entity"

    def test_comment_line_number(self):
        src = "entity foo is\n-- a comment\nend entity foo;"
        tokens = _lex(src, skip_comments=False)
        comment = next(t for t in tokens if t.kind == TokenKind.COMMENT)
        assert comment.line == 2


# ---------------------------------------------------------------------------
# Bit-string / hex literals
# ---------------------------------------------------------------------------

class TestBitStringLiterals:
    def test_hex_literal_upper(self):
        tokens = _lex('X"DEAD"')
        assert tokens[0].kind == TokenKind.BIT_STRING
        assert tokens[0].value == 'X"DEAD"'

    def test_hex_literal_lower(self):
        tokens = _lex('x"beef"')
        assert tokens[0].kind == TokenKind.BIT_STRING

    def test_binary_literal(self):
        tokens = _lex('B"10101010"')
        assert tokens[0].kind == TokenKind.BIT_STRING

    def test_binary_literal_lower(self):
        tokens = _lex('b"0000_1111"')
        assert tokens[0].kind == TokenKind.BIT_STRING

    def test_octal_literal(self):
        tokens = _lex('O"77"')
        assert tokens[0].kind == TokenKind.BIT_STRING

    def test_hex_literal_in_expression(self):
        tokens = _lex('rx_shift <= X"00";')
        bit_str = [t for t in tokens if t.kind == TokenKind.BIT_STRING]
        assert len(bit_str) == 1
        assert bit_str[0].value == 'X"00"'


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class TestOperators:
    def test_signal_assign(self):
        tokens = _lex("y <= a;")
        ops = [t for t in tokens if t.kind == TokenKind.SIGNAL_ASSIGN]
        assert len(ops) == 1

    def test_variable_assign(self):
        tokens = _lex("v := 0;")
        ops = [t for t in tokens if t.kind == TokenKind.ASSIGN]
        assert len(ops) == 1

    def test_association(self):
        tokens = _lex("a => b")
        ops = [t for t in tokens if t.kind == TokenKind.ASSOC]
        assert len(ops) == 1

    def test_neq(self):
        tokens = _lex("a /= b")
        ops = [t for t in tokens if t.kind == TokenKind.NEQ]
        assert len(ops) == 1


# ---------------------------------------------------------------------------
# Line numbers
# ---------------------------------------------------------------------------

class TestLineNumbers:
    def test_first_token_line_1(self):
        tokens = _lex("entity foo is")
        assert tokens[0].line == 1

    def test_multiline_line_numbers(self):
        src = "library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;"
        tokens = _lex(src)
        use_tok = next(t for t in tokens if t.kind == TokenKind.KEYWORD and t.value.lower() == "use")
        assert use_tok.line == 2

    def test_line_numbers_in_fixtures(self):
        """Every token in the and_gate fixture has a line number >= 1."""
        with open(os.path.join(_FIXTURES, "and_gate.vhd")) as f:
            src = f.read()
        tokens = _lex(src)
        assert all(t.line >= 1 for t in tokens)


# ---------------------------------------------------------------------------
# Fixture smoke tests
# ---------------------------------------------------------------------------

class TestFixtureLexing:
    @pytest.mark.parametrize("filename", ["and_gate.vhd", "counter.vhd", "uart_rx.vhd"])
    def test_fixture_lexes_without_error(self, filename):
        path = os.path.join(_FIXTURES, filename)
        with open(path) as f:
            src = f.read()
        tokens = _lex(src)
        assert len(tokens) > 10  # non-trivial output
        assert tokens[-1].kind == TokenKind.EOF

    def test_counter_contains_std_logic_vector_keyword(self):
        path = os.path.join(_FIXTURES, "counter.vhd")
        with open(path) as f:
            src = f.read()
        tokens = _lex(src)
        idents = [t.value.lower() for t in tokens if t.kind == TokenKind.IDENTIFIER]
        assert "std_logic_vector" in idents

    def test_uart_has_hex_literals(self):
        path = os.path.join(_FIXTURES, "uart_rx.vhd")
        with open(path) as f:
            src = f.read()
        tokens = _lex(src)
        bit_strs = [t for t in tokens if t.kind == TokenKind.BIT_STRING]
        assert len(bit_strs) >= 2  # X"00" appears twice
