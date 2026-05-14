"""
conftest.py — session-wide setup for the backend test suite.

Ensures the real `tools` package is imported as a proper Python package
*before* any test module is collected.  Some test files use importlib.util
to load individual modules with stub registries; if they run before any
direct `from tools.xxx import ...` test, they can leave a broken
`sys.modules['tools']` state that makes later direct-imports fail with
"'tools' is not a package".

Importing `tools` here (at collection time) locks in the real package
object under `sys.modules['tools']` so subsequent `sys.modules.setdefault`
calls in individual test modules are no-ops for the top-level key.
"""
import sys
import os

# Add backend/ to sys.path so `import tools` resolves to the real package.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import tools  # noqa: F401  — side-effect: locks in real package in sys.modules
