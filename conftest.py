"""Repo-root conftest.

1. Put every plugin's ``src/`` on sys.path so ``from kerf_<name> import ...``
   works in tests without ``pip install -e``.
2. Install a test-only compatibility shim: ``tools.X`` resolves to the
   canonical plugin module that owns X. This lets legacy tests written
   against the pre-plugin layout keep working without rewriting them.
3. Restore pre-3.10 ``asyncio.get_event_loop()`` semantics in the test
   process so the ~110 test files that use the legacy
   ``get_event_loop().run_until_complete(...)`` pattern keep working under
   Python 3.13 (which removed the implicit loop auto-create). Production
   code is unaffected — conftest.py is loaded only by pytest.
"""
import asyncio
import os
import sys
import types


# (3) asyncio compatibility shim for the test process.
_orig_get_event_loop = asyncio.get_event_loop


def _get_event_loop_compat():
    try:
        return _orig_get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


asyncio.get_event_loop = _get_event_loop_compat


_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _add_plugin_src_paths() -> None:
    """Insert every packages/kerf-<x>/src onto sys.path."""
    pkg_dir = os.path.join(_REPO_ROOT, "packages")
    if not os.path.isdir(pkg_dir):
        return
    for entry in os.listdir(pkg_dir):
        if not entry.startswith("kerf-"):
            continue
        src = os.path.join(pkg_dir, entry, "src")
        if os.path.isdir(src) and src not in sys.path:
            sys.path.insert(0, src)


_add_plugin_src_paths()


def _install_tools_shim() -> None:
    """Test-only: make ``tools.X`` resolve to the plugin module that owns X.

    Production code uses ``kerf_<plugin>.tools.X`` directly; this shim only
    serves tests that haven't been rewritten yet.
    """
    # Parent namespace package
    tools_pkg = types.ModuleType("tools")
    tools_pkg.__path__ = []  # mark as namespace package
    sys.modules.setdefault("tools", tools_pkg)

    # Map "tools.<name>" -> "<canonical_module>"
    # The compat list is short — only modules referenced by tests.
    mapping = {
        "tools.context": "kerf_core.utils.context",
        "tools.registry": "kerf_chat.tools.registry",
        "tools.executor": "kerf_chat.tools.executor",
        "tools.docs": "kerf_chat.tools.docs",
        "tools.file_ops": "kerf_api.tools.file_ops",
        "tools.object_ops": "kerf_api.tools.object_ops",
        "tools.scaffold": "kerf_api.tools.scaffold",
        "tools.validation": "kerf_api.tools.validation",
        "tools.equations": "kerf_api.tools.equations",
        "tools.configurations": "kerf_api.tools.configurations",
        "tools.revisions": "kerf_api.tools.revisions",
        "tools.layers": "kerf_api.tools.layers",
        "tools.project_layers": "kerf_api.tools.project_layers",
        "tools.material": "kerf_api.tools.material",
        "tools.surfacing": "kerf_cad_core.surfacing",
        "tools.sketch": "kerf_cad_core.sketch",
        "tools.solvespace_wrapper": "kerf_mates.solver",
        "tools.tolerance": "kerf_mates.tolerance",
        "tools.feature_draft": "kerf_imports.tools.feature_draft",
        "tools.feature_mirror": "kerf_imports.tools.feature_mirror",
        "tools.feature_helix": "kerf_imports.tools.feature_helix",
        "tools.feature_rib": "kerf_imports.tools.feature_rib",
        "tools.feature_multi_transform": "kerf_imports.tools.feature_multi_transform",
        "tools.subd": "kerf_imports.tools.subd",
        "tools.mesh": "kerf_imports.tools.mesh",
        "tools.curve_ops": "kerf_imports.tools.curve_ops",
        "tools.draft": "kerf_imports.tools.draft",
        "tools.inspection": "kerf_imports.tools.inspection",
        "tools.graph": "kerf_imports.tools.graph",
        "tools.import_3dm": "kerf_imports.tools.import_3dm",
        "tools.sheet_revisions": "kerf_imports.tools.sheet_revisions",
        "tools.bim": "kerf_bim.tools.bim",
        "tools.bim_categories": "kerf_bim.tools.bim_categories",
        "tools.element_types": "kerf_bim.tools.element_types",
        "tools.family": "kerf_bim.tools.family",
        "tools.schedule": "kerf_bim.tools.schedule",
        "tools.view": "kerf_bim.tools.view",
        "tools.sheet": "kerf_bim.tools.sheet",
        "tools.stairs": "kerf_bim.tools.stairs",
        "tools.railings": "kerf_bim.tools.railings",
        "tools.mep": "kerf_bim.tools.mep",
        "tools.curtain_wall": "kerf_bim.tools.curtain_wall",
        "tools.pcb_drc": "kerf_electronics.tools.pcb_drc",
        "tools.pcb_layer_tools": "kerf_electronics.tools.pcb_layer_tools",
        "tools.routing": "kerf_electronics.tools.routing",
        "tools.sim": "kerf_electronics.tools.sim",
        "tools.erc": "kerf_electronics.tools.erc",
        "tools.buses": "kerf_electronics.tools.buses",
        "tools.net_classes": "kerf_electronics.tools.net_classes",
        "tools.length_tuning": "kerf_electronics.tools.length_tuning",
        "tools.via_stitching": "kerf_electronics.tools.via_stitching",
        "tools.shove_router": "kerf_electronics.tools.shove_router",
        "tools.pad_overrides": "kerf_electronics.tools.pad_overrides",
        "tools.hier_schematic": "kerf_electronics.tools.hier_schematic",
        "tools.rf": "kerf_electronics.tools.rf",
        "tools.autoroute": "kerf_electronics.tools.autoroute",
        "tools.pour": "kerf_electronics.tools.pour",
        "tools.assembly": "kerf_api.tools.assembly_management",
        "tools.render": "kerf_render.tools",
    }

    import importlib
    for alias, canonical in mapping.items():
        try:
            mod = importlib.import_module(canonical)
            sys.modules.setdefault(alias, mod)
            # Also attach to the tools namespace so attribute access works
            short = alias.split(".", 1)[1]
            setattr(tools_pkg, short, mod)
        except ImportError:
            # Heavy-dep plugins may not import without their deps installed;
            # the tests that need them will skip via pytest.importorskip.
            continue


_install_tools_shim()
