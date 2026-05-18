"""VHDL lexer — IEEE 1076-2008 subset.

Case-insensitive: keyword recognition is done after folding to lower-case.
Identifiers are returned in their original case.

Supported token kinds
---------------------
* Keywords (case-insensitive)
* Identifiers (plain and extended: ``\\foo\\``)
* Integer literals (decimal)
* Bit-string literals: ``B"0101"``, ``X"DEAD"``
* Character literals: ``'0'``, ``'1'``, ``'Z'``, ``'X'``, ``'L'``, ``'H'``,
  ``'-'``, ``'U'``, ``'W'`` (std_logic values), and any other single character
* String literals: ``"hello"``
* Operators and delimiters: ``<= := => : ; , . ( ) [ ] & | + - * / < > = /=
  <= >= **``
* Line comments (``--`` to end-of-line) — emitted as COMMENT tokens so tests
  can verify them
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator, Optional


# ---------------------------------------------------------------------------
# Token kinds
# ---------------------------------------------------------------------------

class TokenKind(Enum):
    # Literals
    INTEGER = auto()
    BIT_STRING = auto()      # B"…" / O"…" / X"…"
    STRING = auto()
    CHAR_LITERAL = auto()    # 'x' — std_logic values & ordinary chars

    # Names
    IDENTIFIER = auto()
    KEYWORD = auto()

    # Punctuation / operators
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    SEMICOLON = auto()
    COLON = auto()
    COMMA = auto()
    DOT = auto()
    TICK = auto()            # attribute  foo'event

    ASSIGN = auto()          # :=
    SIGNAL_ASSIGN = auto()   # <=
    ASSOC = auto()           # =>
    BOX = auto()             # <>
    NEQ = auto()             # /=
    GEQ = auto()             # >=
    LEQ = auto()             # <= (same token as SIGNAL_ASSIGN — context decides)
    GT = auto()              # >
    LT = auto()              # <
    EQ = auto()              # =
    AMP = auto()             # &
    BAR = auto()             # |
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    POWER = auto()           # **

    # Trivia
    COMMENT = auto()

    # Sentinel
    EOF = auto()


# ---------------------------------------------------------------------------
# VHDL 2008 reserved words (lower-case)
# ---------------------------------------------------------------------------

_KEYWORDS: frozenset[str] = frozenset({
    "abs", "access", "after", "alias", "all", "and", "architecture", "array",
    "assert", "assume", "attribute",
    "begin", "block", "body", "buffer", "bus",
    "case", "component", "configuration", "constant", "context", "cover",
    "default", "disconnect", "downto",
    "else", "elsif", "end", "entity", "exit",
    "fairness", "file", "for", "force", "function",
    "generate", "generic", "group", "guarded",
    "if", "impure", "in", "inertial", "inout", "is",
    "label", "library", "linkage", "literal", "loop",
    "map", "mod",
    "nand", "new", "next", "nor", "not", "null",
    "of", "on", "open", "or", "others", "out",
    "package", "parameter", "port", "postponed", "procedure", "process",
    "property", "protected", "pure",
    "range", "record", "register", "reject", "release", "rem", "report",
    "restrict", "return", "rol", "ror",
    "select", "sequence", "severity", "signal", "shared", "sla", "sll",
    "sra", "srl", "strong", "subtype",
    "then", "to", "transport", "type",
    "unaffected", "units", "until", "use",
    "variable", "vmode", "vprop", "vunit",
    "wait", "when", "while", "with",
    "xnor", "xor",
})


# ---------------------------------------------------------------------------
# Token dataclass
# ---------------------------------------------------------------------------

@dataclass
class Token:
    kind: TokenKind
    value: str        # raw text as it appeared in source
    line: int         # 1-based line number
    col: int          # 1-based column


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

# Pre-compiled patterns for the main scan loop.
# Order matters — longer / more-specific patterns must come first.
_TOKEN_PATTERNS: list[tuple[str, TokenKind | None]] = [
    # Whitespace — skip
    (r"[ \t\r\n]+", None),

    # Line comment -- ...
    (r"--[^\n]*", TokenKind.COMMENT),

    # Bit-string literals  B"…"  O"…"  X"…"  (case-insensitive base char)
    (r'[bBoOxX]"[^"]*"', TokenKind.BIT_STRING),

    # Ordinary string literals "..."   (doubled "" is the escape)
    (r'"(?:[^"]|"")*"', TokenKind.STRING),

    # Character literals  '.' — single character between single quotes
    (r"'[^']'", TokenKind.CHAR_LITERAL),

    # Two-char operators (must precede single-char variants)
    (r":=",  TokenKind.ASSIGN),
    (r"<=",  TokenKind.SIGNAL_ASSIGN),   # also serves as LEQ
    (r"=>",  TokenKind.ASSOC),
    (r"<>",  TokenKind.BOX),
    (r"/=",  TokenKind.NEQ),
    (r">=",  TokenKind.GEQ),
    (r"\*\*", TokenKind.POWER),

    # Single-char operators / punctuation
    (r"\(",  TokenKind.LPAREN),
    (r"\)",  TokenKind.RPAREN),
    (r"\[",  TokenKind.LBRACKET),
    (r"\]",  TokenKind.RBRACKET),
    (r";",   TokenKind.SEMICOLON),
    (r":",   TokenKind.COLON),
    (r",",   TokenKind.COMMA),
    (r"\.",  TokenKind.DOT),
    (r"'",   TokenKind.TICK),
    (r"<",   TokenKind.LT),
    (r">",   TokenKind.GT),
    (r"=",   TokenKind.EQ),
    (r"&",   TokenKind.AMP),
    (r"\|",  TokenKind.BAR),
    (r"\+",  TokenKind.PLUS),
    (r"-",   TokenKind.MINUS),
    (r"\*",  TokenKind.STAR),
    (r"/",   TokenKind.SLASH),

    # Decimal integer literals (must come before identifiers)
    (r"\d[\d_]*", TokenKind.INTEGER),

    # Extended identifiers  \foo bar\
    (r"\\[^\\]+\\", TokenKind.IDENTIFIER),

    # Basic identifiers (letters, digits, underscores — must start with letter)
    (r"[A-Za-z][A-Za-z0-9_]*", TokenKind.IDENTIFIER),
]

_MASTER_RE = re.compile(
    "|".join(f"({pat})" for pat, _ in _TOKEN_PATTERNS),
    flags=re.DOTALL,
)


class LexerError(Exception):
    def __init__(self, message: str, line: int, col: int) -> None:
        super().__init__(f"Line {line}, col {col}: {message}")
        self.line = line
        self.col = col


class Lexer:
    """Tokenise a VHDL source string.

    Parameters
    ----------
    source:
        Full VHDL source text.
    skip_comments:
        When *True* (the default), COMMENT tokens are dropped from the output.
        Set to *False* to retain them (useful for tests).
    """

    def __init__(self, source: str, *, skip_comments: bool = True) -> None:
        self._source = source
        self._skip_comments = skip_comments
        self._tokens: list[Token] = []
        self._pos: int = 0
        self._tokenised: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tokenise(self) -> list[Token]:
        """Return the full token list (cached after first call)."""
        if not self._tokenised:
            self._tokens = list(self._scan())
            self._tokenised = True
        return self._tokens

    def __iter__(self) -> Iterator[Token]:
        return iter(self.tokenise())

    # ------------------------------------------------------------------
    # Internal scanning
    # ------------------------------------------------------------------

    def _scan(self) -> Iterator[Token]:
        source = self._source
        pos = 0
        line = 1
        line_start = 0

        while pos < len(source):
            m = _MASTER_RE.match(source, pos)
            if m is None:
                col = pos - line_start + 1
                raise LexerError(
                    f"Unexpected character {source[pos]!r}", line, col
                )

            raw = m.group(0)
            col = pos - line_start + 1

            # Determine which group matched
            group_idx = next(i for i, g in enumerate(m.groups()) if g is not None)
            kind = _TOKEN_PATTERNS[group_idx][1]

            # Advance position and track line numbers
            newlines = raw.count("\n")
            if newlines:
                line += newlines
                line_start = pos + raw.rfind("\n") + 1

            pos = m.end()

            if kind is None:
                # Whitespace — skip
                continue

            if kind == TokenKind.COMMENT and self._skip_comments:
                continue

            # Distinguish keyword from identifier
            if kind == TokenKind.IDENTIFIER:
                if raw.lower() in _KEYWORDS:
                    kind = TokenKind.KEYWORD

            yield Token(kind=kind, value=raw, line=line, col=col)

        yield Token(kind=TokenKind.EOF, value="", line=line, col=len(source) - line_start + 1)
