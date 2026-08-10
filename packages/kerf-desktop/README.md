# kerf-desktop

One-process, one-binary native Kerf app. No sidecar: the FastAPI app
(`kerf_core.app:create_app`) runs on uvicorn in a background thread inside
the same process, and a native OS webview (pywebview — WebView2 on Windows,
WebKit on macOS/Linux, not a bundled Chromium) points at it. PyInstaller
freezes the whole thing, including the built React frontend, into one file.

- `kerf-desktop` — run from an installed environment (unfrozen): picks a
  free localhost port, boots the server, waits for `/health`, opens the
  window, and shuts the server down when the window closes.
- `packages/kerf-desktop/kerf-desktop.spec` — the PyInstaller spec that
  embeds `web/dist` and produces the one-file binary.
- `scripts/build-desktop.sh` (or `make desktop`) — builds the frontend, then
  runs PyInstaller against the spec.

See [`docs/desktop-build.md`](../../docs/desktop-build.md) for what the
binary includes and — honestly — what it does not (OCCT B-rep and real FEM
solves are excluded; both depend on conda-forge-only packages that cannot be
frozen).
