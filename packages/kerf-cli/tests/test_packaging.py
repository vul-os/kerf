"""Packaging metadata tests for kerf-cli (T-139).

Verifies — without a network install — that:
  1. packages/kerf-cli/pyproject.toml is valid TOML and declares the expected
     [server] extra packages.
  2. The root pyproject.toml lists kerf-cli as a direct dependency and
     exposes a [server] extra that references kerf-cli[server].
  3. The `kerf` console_scripts entry-point resolves to the correct callable
     (kerf_cli.main:main) via importlib.metadata (uses the installed dist-info
     from the editable install — no network required).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]  # .../agent-<worktree>/
_CLI_PYPROJECT = _REPO_ROOT / "packages" / "kerf-cli" / "pyproject.toml"
_ROOT_PYPROJECT = _REPO_ROOT / "pyproject.toml"

_SERVER_PACKAGES_REQUIRED = {
    "kerf-core",
    "kerf-api",
    "kerf-auth",
    "kerf-billing",
    "kerf-cloud",
    "asyncpg",
    "uvicorn",
}


def _parse_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _server_dep_names(deps: list[str]) -> set[str]:
    """Extract bare package names (strip version specifiers and extras)."""
    names = set()
    for dep in deps:
        # Strip [extra] and version specifier — keep the package name.
        name = dep.split("[")[0].split(">")[0].split("=")[0].split("<")[0].split("!")[0]
        names.add(name.strip().lower())
    return names


# ---------------------------------------------------------------------------
# kerf-cli pyproject.toml tests
# ---------------------------------------------------------------------------

class TestKerfCliPyproject:
    def test_toml_is_valid(self):
        data = _parse_toml(_CLI_PYPROJECT)
        assert "project" in data

    def test_project_name(self):
        data = _parse_toml(_CLI_PYPROJECT)
        assert data["project"]["name"] == "kerf-cli"

    def test_console_scripts_entry_point(self):
        data = _parse_toml(_CLI_PYPROJECT)
        scripts = data["project"].get("scripts", {})
        assert "kerf" in scripts, "kerf console_scripts entry is missing"
        assert scripts["kerf"] == "kerf_cli.main:main"

    def test_server_extra_exists(self):
        data = _parse_toml(_CLI_PYPROJECT)
        extras = data["project"].get("optional-dependencies", {})
        assert "server" in extras, "[server] extra is missing from kerf-cli"

    def test_server_extra_contains_required_packages(self):
        data = _parse_toml(_CLI_PYPROJECT)
        server_deps = data["project"]["optional-dependencies"]["server"]
        names = _server_dep_names(server_deps)
        missing = _SERVER_PACKAGES_REQUIRED - names
        assert not missing, (
            f"[server] extra is missing packages: {sorted(missing)}"
        )

    def test_server_extra_has_version_constraints(self):
        data = _parse_toml(_CLI_PYPROJECT)
        server_deps = data["project"]["optional-dependencies"]["server"]
        # Every kerf-* dep must carry at least a >= constraint
        kerf_deps = [d for d in server_deps if d.startswith("kerf-")]
        for dep in kerf_deps:
            assert ">=" in dep, (
                f"kerf-* server dep '{dep}' is missing a >= version constraint"
            )

    def test_thin_install_has_no_server_deps_in_base(self):
        """Base dependencies must remain empty (thin install)."""
        data = _parse_toml(_CLI_PYPROJECT)
        base_deps = data["project"].get("dependencies", [])
        kerf_server_pkgs = [d for d in base_deps if d.startswith("kerf-")]
        assert not kerf_server_pkgs, (
            f"kerf-* packages must not appear in base dependencies: "
            f"{kerf_server_pkgs}"
        )

    def test_hatch_wheel_packages_set(self):
        data = _parse_toml(_CLI_PYPROJECT)
        wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
        assert "packages" in wheel
        assert "src/kerf_cli" in wheel["packages"]


# ---------------------------------------------------------------------------
# Root pyproject.toml tests
# ---------------------------------------------------------------------------

class TestRootPyproject:
    def test_toml_is_valid(self):
        data = _parse_toml(_ROOT_PYPROJECT)
        assert "project" in data

    def test_kerf_meta_name(self):
        data = _parse_toml(_ROOT_PYPROJECT)
        assert data["project"]["name"] == "kerf"

    def test_kerf_cli_is_base_dependency(self):
        data = _parse_toml(_ROOT_PYPROJECT)
        base_deps = data["project"].get("dependencies", [])
        names = _server_dep_names(base_deps)
        assert "kerf-cli" in names, (
            "kerf-cli must be a base dependency of the root kerf meta-package "
            "so that `pip install kerf` puts `kerf` on PATH"
        )

    def test_server_extra_references_kerf_cli_server(self):
        data = _parse_toml(_ROOT_PYPROJECT)
        extras = data["project"].get("optional-dependencies", {})
        assert "server" in extras, "root kerf pyproject is missing a [server] extra"
        server_deps = extras["server"]
        # At least one dep must reference kerf-cli[server]
        kerf_cli_server = [d for d in server_deps if "kerf-cli" in d and "server" in d]
        assert kerf_cli_server, (
            "root [server] extra must reference 'kerf-cli[server]'"
        )

    def test_uv_workspace_includes_kerf_cli(self):
        data = _parse_toml(_ROOT_PYPROJECT)
        members = data["tool"]["uv"]["workspace"]["members"]
        assert "packages/kerf-cli" in members

    def test_uv_sources_includes_kerf_cli(self):
        data = _parse_toml(_ROOT_PYPROJECT)
        sources = data["tool"]["uv"]["sources"]
        assert "kerf-cli" in sources
        assert sources["kerf-cli"] == {"workspace": True}


# ---------------------------------------------------------------------------
# importlib.metadata entry-point resolution
# ---------------------------------------------------------------------------

class TestEntryPointResolution:
    def test_kerf_entry_point_exists(self):
        import importlib.metadata as meta
        eps = meta.entry_points(group="console_scripts")
        kerf_eps = [e for e in eps if e.name == "kerf" and e.dist
                    and e.dist.name == "kerf-cli"]
        assert kerf_eps, (
            "No 'kerf' console_scripts entry-point found from kerf-cli dist. "
            "Is kerf-cli installed in editable mode?"
        )

    def test_kerf_entry_point_value(self):
        import importlib.metadata as meta
        eps = meta.entry_points(group="console_scripts")
        kerf_eps = [e for e in eps if e.name == "kerf" and e.dist
                    and e.dist.name == "kerf-cli"]
        assert kerf_eps, "kerf entry-point not found in kerf-cli dist-info"
        assert kerf_eps[0].value == "kerf_cli.main:main"

    def test_kerf_cli_dist_version(self):
        import importlib.metadata as meta
        dist = meta.distribution("kerf-cli")
        assert dist.metadata["Version"] == "0.1.0"

    def test_kerf_cli_server_extra_in_dist_requires(self):
        """Installed dist-info must advertise the server extra."""
        import importlib.metadata as meta
        dist = meta.distribution("kerf-cli")
        requires = dist.requires or []
        server_reqs = [r for r in requires if "extra == 'server'" in r]
        assert server_reqs, (
            "kerf-cli dist-info has no requires entries for extra == 'server'. "
            "Re-install with: pip install -e packages/kerf-cli"
        )
        # Verify the required packages appear in the installed metadata
        server_req_names = _server_dep_names(
            [r.split(";")[0].strip() for r in server_reqs]
        )
        for pkg in ("kerf-core", "kerf-api", "kerf-auth", "kerf-billing", "kerf-cloud"):
            assert pkg in server_req_names, (
                f"'{pkg}' not found in installed kerf-cli [server] requires. "
                f"Available: {sorted(server_req_names)}"
            )
