"""
conftest.py for kerf-systems tests.

Ensures src/ is on the path so tests can import kerf_systems directly
without an editable install.
"""
import sys
import os

# Add the package src/ to sys.path
_here = os.path.dirname(__file__)
_src = os.path.normpath(os.path.join(_here, "..", "src"))
if _src not in sys.path:
    sys.path.insert(0, _src)
