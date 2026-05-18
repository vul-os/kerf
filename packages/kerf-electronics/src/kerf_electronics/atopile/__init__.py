"""atopile `.ato` source reader — pure-Python lexer + recursive-descent parser.

Quick start::

    from kerf_electronics.atopile import parse
    ast = parse(open("my_design.ato").read())

"""
from .parser import parse, ParseError
from . import ast

__all__ = ["parse", "ParseError", "ast"]
