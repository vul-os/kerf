"""Hand-rolled lexer for the atopile `.ato` language.

Produces a flat token stream consumed by the recursive-descent parser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional


class TK(Enum):
    # Keywords
    IMPORT = auto()
    FROM = auto()
    MODULE = auto()
    COMPONENT = auto()
    INTERFACE = auto()
    SIGNAL = auto()
    PIN = auto()
    NEW = auto()
    # Operators / punctuation
    TILDE = auto()      # ~  (connection)
    EQUALS = auto()     # =
    COLON = auto()      # :
    DOT = auto()        # .
    LPAREN = auto()     # (
    RPAREN = auto()     # )
    LBRACKET = auto()   # [
    RBRACKET = auto()   # ]
    COMMA = auto()      # ,
    ARROW = auto()      # ->
    # Literals / identifiers
    IDENT = auto()
    NUMBER = auto()     # numeric literal possibly followed by a unit suffix
    STRING = auto()     # double-quoted string
    # Layout
    NEWLINE = auto()
    INDENT = auto()
    DEDENT = auto()
    # Misc
    EOF = auto()


# ---------------------------------------------------------------------------
# Keyword table
# ---------------------------------------------------------------------------

_KEYWORDS: dict[str, TK] = {
    "import": TK.IMPORT,
    "from": TK.FROM,
    "module": TK.MODULE,
    "component": TK.COMPONENT,
    "interface": TK.INTERFACE,
    "signal": TK.SIGNAL,
    "pin": TK.PIN,
    "new": TK.NEW,
}


@dataclass
class Token:
    kind: TK
    value: str
    line: int   # 1-based
    col: int    # 0-based


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

# Numeric literal: integer or float, optionally followed immediately by a unit
# suffix (letters only, e.g. kohm, nF, V, MHz).
_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[a-zA-Z]+)?")
# Identifier: starts with letter or underscore
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class LexerError(Exception):
    def __init__(self, msg: str, line: int, col: int):
        super().__init__(f"{msg} at {line}:{col}")
        self.line = line
        self.col = col


def tokenise(source: str) -> List[Token]:
    """Tokenise *source* and return a list of :class:`Token` objects.

    Indentation is Python-style (spaces, 4 per level by convention).
    The lexer emits INDENT / DEDENT tokens at block boundaries and NEWLINE
    tokens at the end of logical lines.
    """
    tokens: List[Token] = []
    lines = source.splitlines(keepends=True)

    indent_stack: List[int] = [0]
    pending_dedents: int = 0

    for lineno, raw_line in enumerate(lines, start=1):
        # Strip the newline for processing, we'll handle it manually
        line = raw_line.rstrip("\n").rstrip("\r")

        # Skip blank lines and comment-only lines
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        # Measure leading whitespace
        indent = len(line) - len(stripped)

        if indent > indent_stack[-1]:
            tokens.append(Token(TK.INDENT, "", lineno, 0))
            indent_stack.append(indent)
        else:
            while indent_stack[-1] > indent:
                indent_stack.pop()
                tokens.append(Token(TK.DEDENT, "", lineno, 0))
            if indent_stack[-1] != indent:
                raise LexerError(
                    f"Inconsistent indentation (got {indent}, expected {indent_stack[-1]})",
                    lineno, 0,
                )

        # Scan the rest of the line
        pos = indent
        length = len(line)

        while pos < length:
            ch = line[pos]

            # Skip inline whitespace
            if ch in (" ", "\t"):
                pos += 1
                continue

            # Comment
            if ch == "#":
                break

            # String literal
            if ch == '"':
                end = pos + 1
                while end < length and line[end] != '"':
                    if line[end] == "\\":
                        end += 1  # skip escaped char
                    end += 1
                if end >= length:
                    raise LexerError("Unterminated string literal", lineno, pos)
                tokens.append(Token(TK.STRING, line[pos + 1 : end], lineno, pos))
                pos = end + 1
                continue

            # Two-char operators
            if pos + 1 < length and line[pos : pos + 2] == "->":
                tokens.append(Token(TK.ARROW, "->", lineno, pos))
                pos += 2
                continue

            # Single-char operators
            single_map: dict[str, TK] = {
                "~": TK.TILDE,
                "=": TK.EQUALS,
                ":": TK.COLON,
                ".": TK.DOT,
                "(": TK.LPAREN,
                ")": TK.RPAREN,
                "[": TK.LBRACKET,
                "]": TK.RBRACKET,
                ",": TK.COMMA,
            }
            if ch in single_map:
                tokens.append(Token(single_map[ch], ch, lineno, pos))
                pos += 1
                continue

            # Number (must check before identifier to catch "10kohm")
            m = _NUM_RE.match(line, pos)
            if m and m.start() == pos:
                tokens.append(Token(TK.NUMBER, m.group(), lineno, pos))
                pos = m.end()
                continue

            # Identifier or keyword
            m = _IDENT_RE.match(line, pos)
            if m and m.start() == pos:
                word = m.group()
                kind = _KEYWORDS.get(word, TK.IDENT)
                tokens.append(Token(kind, word, lineno, pos))
                pos = m.end()
                continue

            raise LexerError(f"Unexpected character {ch!r}", lineno, pos)

        # End of non-blank line → emit NEWLINE
        tokens.append(Token(TK.NEWLINE, "\n", lineno, length))

    # Close any open indent levels
    while len(indent_stack) > 1:
        indent_stack.pop()
        tokens.append(Token(TK.DEDENT, "", len(lines) + 1, 0))

    tokens.append(Token(TK.EOF, "", len(lines) + 1, 0))
    return tokens
