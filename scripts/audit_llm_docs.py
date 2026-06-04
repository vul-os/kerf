#!/usr/bin/env python3
"""
Audit and generate llm_docs/*.md files for all registered LLM tools.

Usage:
    python scripts/audit_llm_docs.py [--dry-run] [--pkg PACKAGE_NAME]

Strategy:
  1. Extract tool names directly from module SOURCE (ToolSpec name=...) — this is
     the authoritative list and avoids import-order attribution errors.
  2. Import every module in _TOOL_MODULES order so all tools get registered.
  3. Look up ToolSpec from the global Registry by name.
  4. For each module, generate/update llm_docs/<shortname>.md.
  5. Write docs/llm-tools-coverage.md.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
for pkg_dir in REPO_ROOT.joinpath("packages").iterdir():
    src = pkg_dir / "src"
    if src.is_dir():
        sys.path.insert(0, str(src))

try:
    from kerf_chat.tools.registry import Registry, ToolSpec
except ImportError:
    print("ERROR: kerf_chat.tools.registry not found.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

def get_doc_shortname(module_path: str) -> str:
    """Derive the llm_docs/*.md filename (without .md) from a module path."""
    parts = module_path.split(".")
    last = parts[-1]
    if last == "tools" and len(parts) >= 2:
        parent = parts[-2]
        if parent.startswith("kerf_"):
            return parent[5:]
        return parent
    return last


def module_path_to_file(module_path: str) -> str | None:
    """Resolve a dotted module path to its .py file."""
    parts = module_path.split(".")
    for base in sys.path:
        path = os.path.join(base, *parts) + ".py"
        if os.path.exists(path):
            return path
        path = os.path.join(base, *parts, "__init__.py")
        if os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------------------
# Source-based tool name extraction (authoritative)
# ---------------------------------------------------------------------------

def extract_tool_names_from_source(module_path: str) -> list[str]:
    """Parse Python source to find ToolSpec(name=...) declarations.

    This is the authoritative method — it avoids import-order attribution
    problems where transitive imports register tools under the wrong module.
    """
    file_path = module_path_to_file(module_path)
    if not file_path:
        return []

    with open(file_path) as f:
        content = f.read()

    tool_names: list[str] = []
    for m in re.finditer(r"ToolSpec\s*\(", content):
        snippet = content[m.end() : m.end() + 400]
        nm = re.search(r"\bname\s*=\s*[\"']([^\"']+)[\"']", snippet)
        if nm and nm.group(1) not in tool_names:
            tool_names.append(nm.group(1))

    return tool_names


# ---------------------------------------------------------------------------
# Plugin module extraction
# ---------------------------------------------------------------------------

def extract_tool_modules(plugin_path: str) -> list[str]:
    """Parse plugin.py and return ordered, dedup'd list of tool module paths."""
    with open(plugin_path) as f:
        content = f.read()

    modules: list[str] = []

    # Pattern 1: _TOOL_MODULES = [...]
    m = re.search(r"_TOOL_MODULES\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if m:
        for line in m.group(1).split("\n"):
            line = line.strip()
            hit = re.match(r'"([^"]+)"', line) or re.match(r"'([^']+)'", line)
            if hit:
                modules.append(hit.group(1))

    # Pattern 2: (indented) tool_modules = [...] (may contain tuples)
    for m in re.finditer(
        r"(?:^    |\n    )_?tool_modules\s*=\s*\[(.*?)\]", content, re.DOTALL
    ):
        for line in m.group(1).split("\n"):
            line = line.strip()
            # 3-tuple: ("module.path", "spec_name", "handler_name")
            hit = re.match(r'\("([^"]+)"', line)
            if hit:
                modules.append(hit.group(1))
                continue
            hit = re.match(r'"([^"]+)"', line) or re.match(r"'([^']+)'", line)
            if hit:
                modules.append(hit.group(1))

    return list(dict.fromkeys(modules))


# ---------------------------------------------------------------------------
# Bulk import all modules and build Registry index
# ---------------------------------------------------------------------------

def build_registry_index(pkg_root: str, modules: list[str]) -> dict[str, "ToolSpec"]:
    """Import all modules and return {tool_name: ToolSpec} index.

    Pre-importing the package __init__ first avoids over-attribution to
    the first explicitly imported module.
    """
    try:
        importlib.import_module(pkg_root)
    except Exception:
        pass

    for mod_path in modules:
        try:
            importlib.import_module(mod_path)
        except Exception:
            pass

    return {t.spec.name: t.spec for t in Registry}


# ---------------------------------------------------------------------------
# Doc generation
# ---------------------------------------------------------------------------

def _json_block(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2)
    except Exception:
        return str(obj)


def generate_doc(
    module_path: str,
    tools: list[tuple[str, "ToolSpec"]],
    domain: str,
) -> str:
    """Generate markdown content for an llm_docs file."""
    shortname = get_doc_shortname(module_path)
    pkg_root = module_path.split(".")[0]

    if len(tools) == 1:
        tool_name, spec = tools[0]
        lines = [
            f"# {tool_name}",
            "",
            f"*Module: `{module_path}` · Domain: {domain}*",
            "",
            "## Description",
            "",
            spec.description.strip(),
            "",
            "## Input schema",
            "",
            "```json",
            _json_block(spec.input_schema),
            "```",
            "",
            "## Example call",
            "",
            "```python",
            "import json",
            f"# Invoke via the kerf chat tool runner.",
            f"result = json.loads(await tool_runner.run(",
            f'    tool_name="{tool_name}",',
            f"    args={{",
            f"        # fill required fields — see Input schema above",
            f"    }}",
            f"))",
            "```",
            "",
            "## See also",
            "",
            f"- Package: `{pkg_root}`",
            "",
        ]
        return "\n".join(lines)
    else:
        lines = [
            f"# {shortname}",
            "",
            f"*Module: `{module_path}` · Domain: {domain}*",
            "",
            f"This module registers **{len(tools)}** LLM tool(s):",
            "",
        ]
        for tname, _ in tools:
            lines.append(f"- [`{tname}`](#{tname.replace('_', '-')})")
        lines += ["", "---", ""]

        for tname, tspec in tools:
            lines += [
                f"## `{tname}`",
                "",
                tspec.description.strip(),
                "",
                "### Input schema",
                "",
                "```json",
                _json_block(tspec.input_schema),
                "```",
                "",
                "---",
                "",
            ]

        lines += [
            "## See also",
            "",
            f"- Package: `{pkg_root}`",
            "",
        ]
        return "\n".join(lines)


def generate_stub_doc(module_path: str, domain: str, reason: str) -> str:
    """Stub doc for modules with no importable tools."""
    shortname = get_doc_shortname(module_path)
    pkg_root = module_path.split(".")[0]
    return (
        f"# {shortname}\n\n"
        f"*Module: `{module_path}` · Domain: {domain}*\n\n"
        f"> **Note:** {reason}\n\n"
        f"## See also\n\n"
        f"- Package: `{pkg_root}`\n"
    )


# ---------------------------------------------------------------------------
# Verify existing doc accuracy
# ---------------------------------------------------------------------------

def check_doc_accuracy(
    doc_path: str, tools: list[tuple[str, "ToolSpec"]]
) -> list[str]:
    """Return list of accuracy issues in an existing doc."""
    issues: list[str] = []
    with open(doc_path) as f:
        content = f.read()

    for tool_name, spec in tools:
        if tool_name not in content:
            issues.append(f"tool name '{tool_name}' not found in doc")
            continue
        for prop in list(spec.input_schema.get("required", []))[:2]:
            if not any(
                marker in content
                for marker in [f'"{prop}"', f"'{prop}'", f"`{prop}`", f" {prop} "]
            ):
                issues.append(f"required prop '{prop}' for '{tool_name}' not documented")

    return issues


# ---------------------------------------------------------------------------
# Package configs
# ---------------------------------------------------------------------------

PACKAGES = [
    {
        "name": "kerf-cad-core",
        "domain": "cad",
        "pkg_root": "kerf_cad_core",
        "plugin": "packages/kerf-cad-core/src/kerf_cad_core/plugin.py",
        "llm_docs": "packages/kerf-cad-core/llm_docs",
    },
    {
        "name": "kerf-electronics",
        "domain": "electronics",
        "pkg_root": "kerf_electronics",
        "plugin": "packages/kerf-electronics/src/kerf_electronics/plugin.py",
        "llm_docs": "packages/kerf-electronics/llm_docs",
    },
    {
        "name": "kerf-bim",
        "domain": "bim",
        "pkg_root": "kerf_bim",
        "plugin": "packages/kerf-bim/src/kerf_bim/plugin.py",
        "llm_docs": "packages/kerf-bim/llm_docs",
    },
    {
        "name": "kerf-imports",
        "domain": "imports",
        "pkg_root": "kerf_imports",
        "plugin": "packages/kerf-imports/src/kerf_imports/plugin.py",
        "llm_docs": "packages/kerf-imports/llm_docs",
    },
    {
        "name": "kerf-parts",
        "domain": "parts",
        "pkg_root": "kerf_parts",
        "plugin": "packages/kerf-parts/src/kerf_parts/plugin.py",
        "llm_docs": "packages/kerf-parts/llm_docs",
    },
    {
        "name": "kerf-woodworking",
        "domain": "woodworking",
        "pkg_root": "kerf_woodworking",
        "plugin": "packages/kerf-woodworking/src/kerf_woodworking/plugin.py",
        "llm_docs": "packages/kerf-woodworking/llm_docs",
    },
    {
        "name": "kerf-api",
        "domain": "api",
        "pkg_root": "kerf_api",
        "plugin": "packages/kerf-api/src/kerf_api/plugin.py",
        "llm_docs": "packages/kerf-api/llm_docs",
    },
    {
        "name": "kerf-lca",
        "domain": "lca",
        "pkg_root": "kerf_lca",
        "plugin": "packages/kerf-lca/src/kerf_lca/plugin.py",
        "llm_docs": "packages/kerf-lca/llm_docs",
    },
]


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def write_coverage_report(
    summary: dict,
    report_path: str,
    all_tools_by_pkg: dict,
    import_errors: list,
) -> None:
    today = summary["date"]
    total = summary["total_modules"]
    with_docs = summary["modules_with_docs"]
    pct = 100 * with_docs // max(total, 1)

    lines = [
        "# LLM Tools Coverage Report",
        "",
        f"*Generated: {today} · Script: `scripts/audit_llm_docs.py`*",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total modules | {total} |",
        f"| Modules with llm\\_docs | {with_docs} |",
        f"| Coverage | {with_docs}/{total} ({pct}%) |",
        f"| Docs created this run | {summary['created']} |",
        f"| Docs updated this run | {summary['updated']} |",
        f"| Import errors | {len(import_errors)} |",
        "",
        "## Domain coverage matrix",
        "",
        "| Package | Domain | Modules | With docs | Coverage |",
        "|---------|--------|---------|-----------|----------|",
    ]

    for pkg_name, stats in summary["by_package"].items():
        t = stats["total"]
        w = stats.get("with_docs", 0)
        p = 100 * w // max(t, 1)
        d = stats.get("domain", "?")
        lines.append(f"| `{pkg_name}` | {d} | {t} | {w} | {p}% |")

    lines += [
        "",
        "## Registered tools by package",
        "",
    ]

    for pkg_name, tools_info in all_tools_by_pkg.items():
        lines.append(f"### `{pkg_name}`")
        lines.append("")
        if tools_info:
            lines.append("| Module | Tools | Doc file |")
            lines.append("|--------|-------|----------|")
            for mod_path, tool_names, shortname, has_doc in tools_info:
                tlist = ", ".join(f"`{t}`" for t in tool_names[:4])
                if len(tool_names) > 4:
                    tlist += f" +{len(tool_names)-4}"
                if not tlist:
                    tlist = "—"
                status = f"`{shortname}.md`" if has_doc else f"~~`{shortname}.md`~~"
                lines.append(f"| `{mod_path}` | {tlist} | {status} |")
        else:
            lines.append("*No tool modules.*")
        lines.append("")

    if import_errors:
        lines += [
            "## Import errors",
            "",
            "| Package | Module | Error |",
            "|---------|--------|-------|",
        ]
        for e in import_errors:
            err = e["error"][:80].replace("|", "\\|")
            lines.append(f"| `{e['package']}` | `{e['module']}` | {err} |")
        lines.append("")

    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text("\n".join(lines))
    print(f"\n  Coverage report: {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, filter_pkg: str | None = None) -> dict:
    os.chdir(REPO_ROOT)

    from datetime import date
    today = date.today().isoformat()

    summary: dict = {
        "date": today,
        "total_modules": 0,
        "modules_with_docs": 0,
        "created": 0,
        "updated": 0,
        "by_package": {},
    }
    all_import_errors: list = []
    all_tools_by_pkg: dict = {}

    for pkg_cfg in PACKAGES:
        pkg_name = pkg_cfg["name"]
        if filter_pkg and filter_pkg not in pkg_name:
            continue

        domain = pkg_cfg["domain"]
        pkg_root = pkg_cfg["pkg_root"]
        plugin_path = pkg_cfg["plugin"]
        llm_docs_dir = Path(pkg_cfg["llm_docs"])

        modules = extract_tool_modules(plugin_path)
        existing_docs = {f.stem for f in llm_docs_dir.glob("*.md")} if llm_docs_dir.is_dir() else set()

        print(f"\n{'='*60}")
        print(f"  Package: {pkg_name}  ({len(modules)} modules)")
        print(f"{'='*60}")

        # Import ALL modules to build the global Registry
        print(f"  Importing all modules...")
        registry_index = build_registry_index(pkg_root, modules)
        print(f"  Registry: {len(registry_index)} tools across all modules")

        pkg_stats = {
            "domain": domain,
            "total": len(modules),
            "with_docs": 0,
            "created": 0,
            "updated": 0,
        }
        pkg_tools_info = []

        for mod_path in modules:
            shortname = get_doc_shortname(mod_path)
            doc_path = llm_docs_dir / f"{shortname}.md"

            # Get tool names from SOURCE (authoritative)
            source_names = extract_tool_names_from_source(mod_path)

            # Try to look up specs from Registry
            tools: list[tuple[str, "ToolSpec"]] = []
            missing_from_registry: list[str] = []

            for name in source_names:
                if name in registry_index:
                    tools.append((name, registry_index[name]))
                else:
                    missing_from_registry.append(name)

            # Check file existence
            has_doc = doc_path.exists()

            if has_doc:
                pkg_stats["with_docs"] += 1
                # Check accuracy
                if tools:
                    issues = check_doc_accuracy(str(doc_path), tools)
                    if issues:
                        print(f"  UPDATE: {shortname}.md  ({len(issues)} drift issue(s))")
                        for issue in issues[:2]:
                            print(f"    - {issue}")
                        new_content = generate_doc(mod_path, tools, domain)
                        if not dry_run:
                            doc_path.write_text(new_content)
                        pkg_stats["updated"] += 1
                        summary["updated"] += 1
            else:
                # Need to create
                if tools:
                    print(
                        f"  CREATE: {shortname}.md  "
                        f"({len(tools)} tool(s): "
                        f"{', '.join(n for n,_ in tools[:3])}"
                        f"{'...' if len(tools) > 3 else ''})"
                    )
                    new_content = generate_doc(mod_path, tools, domain)
                elif missing_from_registry:
                    # Source found names but Registry doesn't have them (optional dep?)
                    reason = (
                        f"Tools {missing_from_registry} defined in source but not in "
                        f"Registry — likely require an optional dependency."
                    )
                    print(f"  CREATE (stub): {shortname}.md  [{reason[:60]}]")
                    all_import_errors.append({
                        "package": pkg_name,
                        "module": mod_path,
                        "error": reason,
                    })
                    new_content = generate_stub_doc(mod_path, domain, reason)
                elif source_names:
                    # Source found names but none in Registry
                    reason = f"Tool(s) {source_names} defined in source but none registered."
                    print(f"  CREATE (stub): {shortname}.md  [{reason[:60]}]")
                    new_content = generate_stub_doc(mod_path, domain, reason)
                else:
                    # No tools in source — might be a utility module
                    reason = "Module registered in plugin but defines no ToolSpec."
                    print(f"  CREATE (no-tools): {shortname}.md  [{mod_path}]")
                    new_content = generate_stub_doc(mod_path, domain, reason)

                if not dry_run:
                    llm_docs_dir.mkdir(parents=True, exist_ok=True)
                    doc_path.write_text(new_content)
                pkg_stats["created"] += 1
                pkg_stats["with_docs"] += 1
                summary["created"] += 1

            pkg_tools_info.append((
                mod_path,
                [n for n, _ in tools],
                shortname,
                has_doc or (not dry_run),
            ))

        all_tools_by_pkg[pkg_name] = pkg_tools_info
        summary["total_modules"] += pkg_stats["total"]
        summary["modules_with_docs"] += pkg_stats["with_docs"]
        summary["by_package"][pkg_name] = pkg_stats

        print(
            f"\n  Result: {pkg_stats['with_docs']}/{pkg_stats['total']} covered, "
            f"{pkg_stats['created']} created, {pkg_stats['updated']} updated"
        )

    summary["import_errors"] = all_import_errors

    if not dry_run:
        write_coverage_report(
            summary,
            "docs/llm-tools-coverage.md",
            all_tools_by_pkg,
            all_import_errors,
        )

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pkg", default=None)
    args = parser.parse_args()

    summary = run(dry_run=args.dry_run, filter_pkg=args.pkg)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total modules:     {summary['total_modules']}")
    print(f"With docs:         {summary['modules_with_docs']}")
    print(f"Coverage:          {summary['modules_with_docs']}/{summary['total_modules']}")
    print(f"Created:           {summary['created']}")
    print(f"Updated:           {summary['updated']}")
    print(f"Import errors:     {len(summary.get('import_errors', []))}")
