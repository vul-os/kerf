"""lexer.py — Tokeniser for Synopsys Liberty (.lib) files.

Token types
-----------
IDENT       bare identifier / keyword
NUMBER      integer or floating-point literal (returned as string; parser converts)
STRING      double-quoted string (content without the surrounding quotes)
LBRACE      {
RBRACE      }
LPAREN      (
RPAREN      )
SEMICOLON   ;
COLON       :
COMMA       ,
BACKSLASH   \\ (line-continuation)
EOF         sentinel — emitted once at end of input

Comments
--------
Both ``/* ... */`` block comments and ``// ...`` line comments are skipped
by the lexer; they never appear in the token stream.

Line/column tracking
--------------------
Every Token carries a zero-based (line, col) SourcePos so the parser (and
any diagnostics layer above it) can point back into the source text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from kerf_silicon.liberty.ast import SourcePos

# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------

IDENT     = "IDENT"
NUMBER    = "NUMBER"
STRING    = "STRING"
LBRACE    = "LBRACE"
RBRACE    = "RBRACE"
LPAREN    = "LPAREN"
RPAREN    = "RPAREN"
SEMICOLON = "SEMICOLON"
COLON     = "COLON"
COMMA     = "COMMA"
BACKSLASH = "BACKSLASH"
EOF       = "EOF"

# ---------------------------------------------------------------------------
# Token dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    type: str
    value: str
    pos: SourcePos

    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, {self.pos})"


# ---------------------------------------------------------------------------
# Master regex — order matters: longer / more specific alternatives first
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, str]] = [
    ("BLOCK_COMMENT",  r"/\*.*?\*/"),          # /* ... */  (DOTALL)
    ("LINE_COMMENT",   r"//[^\n]*"),            # // ...
    ("NEWLINE",        r"\n"),                  # track lines
    ("WHITESPACE",     r"[ \t\r]+"),            # skip
    ("STRING",         r'"(?:[^"\\]|\\.)*"'),   # "..."
    ("NUMBER",         r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"),
    ("IDENT",          r"[A-Za-z_][A-Za-z0-9_!.']*"),  # incl. !A style
    ("LBRACE",         r"\{"),
    ("RBRACE",         r"\}"),
    ("LPAREN",         r"\("),
    ("RPAREN",         r"\)"),
    ("SEMICOLON",      r";"),
    ("COLON",          r":"),
    ("COMMA",          r","),
    ("BACKSLASH",      r"\\"),
]

_MASTER_RE = re.compile(
    "|".join(f"(?P<{name}>{pat})" for name, pat in _PATTERNS),
    re.DOTALL,
)

# Single-char token map for the simple operator types
_SINGLE = {
    "{": LBRACE,
    "}": RBRACE,
    "(": LPAREN,
    ")": RPAREN,
    ";": SEMICOLON,
    ":": COLON,
    ",": COMMA,
    "\\": BACKSLASH,
}


# ---------------------------------------------------------------------------
# Public tokenise() generator
# ---------------------------------------------------------------------------


def tokenise(text: str) -> Iterator[Token]:
    """Yield Token objects for every meaningful token in *text*.

    Skips whitespace, newlines (but advances the internal line counter),
    and ``/* */`` / ``//`` comments.  Raises ``LexError`` on unrecognised
    input.  Terminates with a single ``EOF`` token.
    """
    line = 0
    line_start = 0  # character offset of current line's start

    for m in _MASTER_RE.finditer(text):
        kind = m.lastgroup
        raw  = m.group()
        col  = m.start() - line_start

        if kind == "NEWLINE":
            line += 1
            line_start = m.end()
            continue
        if kind in ("WHITESPACE", "BLOCK_COMMENT", "LINE_COMMENT"):
            # Still need to count newlines inside block comments
            if kind == "BLOCK_COMMENT":
                newlines = raw.count("\n")
                if newlines:
                    line += newlines
                    line_start = m.start() + raw.rfind("\n") + 1
            continue

        pos = SourcePos(line=line, col=col)

        if kind == "STRING":
            # Strip surrounding quotes and unescape \" inside
            value = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            yield Token(STRING, value, pos)
        elif kind == "NUMBER":
            yield Token(NUMBER, raw, pos)
        elif kind == "IDENT":
            yield Token(IDENT, raw, pos)
        else:
            # single-char operators
            tok_type = _SINGLE.get(raw, kind)
            yield Token(tok_type, raw, pos)

    # Emit a sentinel EOF at end-of-file
    yield Token(EOF, "", SourcePos(line=line, col=0))


class LexError(Exception):
    """Raised when the lexer encounters unrecognised input."""
