#!/usr/bin/env python3
"""check-undeclared-imports.py — find imports nothing in the workspace declares.

WHY THIS EXISTS
---------------
`kerf_api/routes_git_diff.py` imported pygit2 at module top level while no
pyproject declared it. In CI the import raised inside the plugin's register(),
the WHOLE kerf-api plugin failed, and every /api/* route 404'd — which stranded
24 of 28 E2E specs on page.waitForURL for weeks. The Playwright output pointed
at the frontend; the cause was one missing line in a pyproject.

This checks the class rather than the instance. It reports only imports that are
(a) at module top level, so they execute at import time,
(b) NOT wrapped in try/except, so a miss is fatal rather than degraded, and
(c) declared by NO package in the workspace, directly or via the root pyproject.

Transitive arrivals are deliberately not flagged: botocore ships with boto3 and
starlette with fastapi, both of which ARE declared, so those are safe. Filtering
on the union of all declared deps is what takes the raw signal from 147 down to
the handful that can actually break a boot.

Exit code is 0 always — this is a report, not a gate, because a legitimate new
transitive can appear at any time. Read it, do not automate on it.

    python3 scripts/check-undeclared-imports.py
"""
import ast, pathlib, sys, re
try: import tomllib
except ImportError: import tomli as tomllib
STDLIB = set(sys.stdlib_module_names)
root = pathlib.Path('packages')
localnames = {p.name.lower().replace('-', '_') for p in root.iterdir()}

# Union of every dependency declared anywhere in the workspace, incl. the root pyproject.
declared_anywhere = set()
pjs = list(root.glob('*/pyproject.toml')) + [pathlib.Path('pyproject.toml')]
for pj in pjs:
    if not pj.exists(): continue
    proj = tomllib.loads(pj.read_text()).get('project', {})
    for d in proj.get('dependencies', []) + [x for v in proj.get('optional-dependencies', {}).values() for x in v]:
        declared_anywhere.add(re.split(r'[<>=!\[; ]', d.strip())[0].lower().replace('-', '_'))

ALIAS = {'jwt':'pyjwt', 'pil':'pillow', 'occ':'pythonocc_core', 'yaml':'pyyaml',
         'dotenv':'python_dotenv', 'sklearn':'scikit_learn', 'cv2':'opencv_python',
         'google':'google_generativeai', 'serial':'pyserial', 'usb':'pyusb'}

risky = {}
for pkg in sorted(root.iterdir()):
    pj, src = pkg / 'pyproject.toml', pkg / 'src'
    if not pj.exists() or not src.exists(): continue
    for f in src.rglob('*.py'):
        try: tree = ast.parse(f.read_text())
        except Exception: continue
        for node in tree.body:
            mods = []
            if isinstance(node, ast.Import):
                mods = [(a.name.split('.')[0], node.lineno) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [(node.module.split('.')[0], node.lineno)]
            for mod, line in mods:
                m = mod.lower()
                if m in STDLIB or m.startswith('_'): continue
                # Workspace packages ARE separately installable — an undeclared
                # sibling breaks any persona that does not happen to include it.
                # Only skip the package's own module.
                if m == pkg.name.lower().replace('-', '_'): continue
                canon = ALIAS.get(m, m)
                if canon in declared_anywhere or m in declared_anywhere: continue
                risky.setdefault((pkg.name, m), f"{f.relative_to(pkg)}:{line}")

print(f"Unguarded top-level imports declared by NO package in the workspace: {len(risky)}\n")
for (pkg, m), loc in sorted(risky.items()):
    print(f"  {pkg:<20} {m:<16} {loc}")

# ── Second report: unguarded imports of a SIBLING workspace package that the importing
# package does not declare. ────────────────────────────────────────────────────────────
#
# The first report asks "does anything provide this at all". That is the right question for
# a third-party dep and it is how the pygit2 fault was found. It is the WRONG question for a
# workspace sibling: kerf-chat is declared by the `full` persona, so it looks satisfied — but
# pip installs per package, and kerf-api imported kerf_chat without declaring it. Under `full`
# everything is present and CI passes; under a minimal persona the import raises inside
# register() and the entire kerf-api plugin fails, mounting 2 /api routes instead of ~200.
sib = {}
for pkg in sorted(root.iterdir()):
    pj, src = pkg / 'pyproject.toml', pkg / 'src'
    if not pj.exists() or not src.exists(): continue
    proj = tomllib.loads(pj.read_text()).get('project', {})
    own = set()
    for d in proj.get('dependencies', []) + [x for v in proj.get('optional-dependencies', {}).values() for x in v]:
        own.add(re.split(r'[<>=!\[; ]', d.strip())[0].lower().replace('-', '_'))
    selfname = pkg.name.lower().replace('-', '_')
    for f in src.rglob('*.py'):
        try: tree = ast.parse(f.read_text())
        except Exception: continue
        for node in tree.body:
            mods = []
            if isinstance(node, ast.Import):
                mods = [(a.name.split('.')[0], node.lineno) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [(node.module.split('.')[0], node.lineno)]
            for mod, line in mods:
                m = mod.lower()
                if m == selfname or m not in localnames or m in own: continue
                sib.setdefault((pkg.name, m), f"{f.relative_to(pkg)}:{line}")

print(f"\nUnguarded imports of an UNDECLARED workspace sibling: {len(sib)}\n")
for (pkg, m), loc in sorted(sib.items()):
    print(f"  {pkg:<20} {m:<22} {loc}")
