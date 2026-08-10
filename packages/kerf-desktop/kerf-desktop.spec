# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — the one-file Kerf desktop binary.

Embeds:
  - The lean persona's Python packages (see pyproject.toml's dependency
    comment for exactly why "lean": pythonOCC and FEniCSx/dolfinx are
    conda-forge-only and cannot be frozen — see docs/desktop-build.md).
  - The built React frontend (web/dist), added as data under "web_dist/" in
    the bundle. At runtime kerf_desktop.main points KERF_FRONTEND_DIST at
    sys._MEIPASS/web_dist, and kerf_core.app._mount_frontend (unmodified —
    including its path-traversal guard) serves it exactly as it does behind
    the Docker build's /app/dist.

Run via scripts/build-desktop.sh (or `make desktop`), which builds web/dist
first, then invokes PyInstaller against this spec. Running `pyinstaller
kerf-desktop.spec` directly works too as long as ../../web/dist already
exists and every package below is importable from the current interpreter
(e.g. the venv scripts/build-desktop.sh creates and installs into).
"""

import os

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

block_cipher = None

# This spec lives at packages/kerf-desktop/kerf-desktop.spec.
_SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
_REPO_ROOT = os.path.abspath(os.path.join(_SPEC_DIR, "..", ".."))
_WEB_DIST = os.path.join(_REPO_ROOT, "web", "dist")

if not os.path.isdir(_WEB_DIST) or not os.path.isfile(os.path.join(_WEB_DIST, "index.html")):
    raise SystemExit(
        f"web/dist not found or incomplete at {_WEB_DIST!r} — run `npm run build` in web/ "
        "(or use scripts/build-desktop.sh, which does this for you) before running PyInstaller."
    )

# Every importable package in the lean/desktop persona: kerf-core, kerf-auth,
# kerf-api, kerf-chat (server stack) + kerf-cad-core, kerf-tess, kerf-fem,
# kerf-cam, kerf-topo, kerf-mates (compute plugins, pip-installable base
# only — occ/fenicsx extras excluded) + kerf-desktop itself.
_KERF_MODULES = [
    "kerf_core",
    "kerf_auth",
    "kerf_api",
    "kerf_chat",
    "kerf_cad_core",
    "kerf_tess",
    "kerf_fem",
    "kerf_cam",
    "kerf_topo",
    "kerf_mates",
    "kerf_desktop",
]
# Matching PyPI/local distribution names, for copy_metadata: kerf_core.app
# discovers plugins via importlib.metadata.entry_points(group="kerf.plugins"),
# which reads each package's installed *.dist-info/entry_points.txt. Without
# copying that metadata into the frozen bundle, every plugin silently fails to
# register — the app boots but every /run-*, /compile-*, /auth/* route is gone.
_KERF_DISTS = [
    "kerf-core",
    "kerf-auth",
    "kerf-api",
    "kerf-chat",
    "kerf-cad-core",
    "kerf-tess",
    "kerf-fem",
    "kerf-cam",
    "kerf-topo",
    "kerf-mates",
    "kerf-desktop",
]

hiddenimports = []
for _mod in _KERF_MODULES:
    hiddenimports += collect_submodules(_mod)

# uvicorn[standard]'s optional accelerators (uvloop, httptools, websockets)
# and the LLM SDKs are imported dynamically / lazily in ways modulegraph's
# static analysis can miss.
for _mod in [
    "uvicorn",
    "anthropic",
    "openai",
    "google.genai",
    "boto3",
    "botocore",
    "pydantic",
    "webview",
]:
    hiddenimports += collect_submodules(_mod)

datas = [(_WEB_DIST, "web_dist")]
for _dist in _KERF_DISTS:
    datas += copy_metadata(_dist)
# uvicorn/anthropic/openai/boto3 read their own package metadata (version
# pins, entry points) at import time in a couple of code paths.
for _dist in ["uvicorn", "anthropic", "openai", "boto3", "botocore", "pywebview"]:
    try:
        datas += copy_metadata(_dist)
    except Exception:
        pass

a = Analysis(
    [os.path.join(_SPEC_DIR, "src", "kerf_desktop", "main.py")],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pygit2 ships its own libcrypto.3.dylib in pygit2/.dylibs. PyInstaller
    # collects it alongside Python's libssl.3.dylib, and at load time the
    # dynamic linker resolves libcrypto to pygit2's copy — which lacks the
    # _CRYPTO_calloc symbol libssl expects, so `import ssl` (via uvicorn)
    # died with a dlopen ImportError before the server ever started.
    #
    # Excluding it is safe and correct here: pygit2 backs the S3 git storer
    # only, its import is already guarded (`try: import pygit2` in
    # kerf_core/storage/git_storer.py), and the desktop build ships a lean
    # local-filesystem persona that never constructs that storer.
    excludes=["pygit2"],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="kerf-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
