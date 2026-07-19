# Testing

This document exists because, until 2026-07-19, nobody had ever run the whole
test suite. Per-package reports were green, but only for the packages they
covered, so the repo had no trustworthy notion of "green" — a real regression
and ordinary background noise looked exactly the same.

The suite has now been measured end to end, package by package. This is the
honest result, including the parts that are red.

## TL;DR

```bash
make test          # DEFAULT — load-bearing packages. GREEN. ~5.0k tests, ~3 min.
make test-kernel   # kerf-cad-core geometry kernel. ~38.8k tests, ~75 min, 17 known failures.
make test-domains  # the 22 engineering domains. Experimental. Currently RED.
make test-all      # everything. ~90 min, RED by design.
```

A bare `pytest` runs the default tier (it is the `testpaths` set in
`pyproject.toml`). **If `make test` is red, that is a regression — treat it as
one.** The other tiers are explicitly labelled and must not be used as a gate
until the issues below are fixed.

## The numbers

### Where the "1563 failures" went

An independent full-suite run on 2026-07-19 reported:

```
1563 failed, 66097 passed, 549 skipped, 180 errors   (~41 min)
```

That number was real but almost entirely **collateral**, not 1563 independent
bugs. Re-measuring package by package after the fixes in `a800d09b` gives:

| | full-suite run (2026-07-19) | measured per-package (after fixes) |
|---|---|---|
| failed | 1563 | **207** |
| errors | 180 | **29** (4 of which are now fixed → **25**) |

The gap is explained by root cause #1 below: a `sys.modules` leak that only
manifests when many packages share one pytest process, which is exactly how the
full-suite run executed them. Running packages in isolation never showed it,
which is why every per-package report was green and the suite was not.

### Per-package results

Measured individually, `pytest packages/<pkg>/tests`, Python 3.13.9, macOS.

**Default tier — load-bearing, all green**

| package | result |
|---|---|
| kerf-api | 689 passed, 30 skipped |
| kerf-auth | 170 passed, 2 skipped |
| kerf-chat | 178 passed |
| kerf-cli | 156 passed |
| kerf-cloud | 208 passed |
| kerf-core | 345 passed, 18 skipped |
| kerf-imports | 1292 passed, 20 skipped |
| kerf-mates | 364 passed |
| kerf-parts | 357 passed |
| kerf-partsgen | 33 passed |
| kerf-plm | 475 passed, 4 skipped |
| kerf-pub | 169 passed |
| kerf-render | 433 passed, 1 skipped |
| kerf-sdk | 7 passed |
| kerf-tess | 33 passed |
| kerf-topo | 5 passed, 2 skipped |
| kerf-worker | 38 passed |

Verified as a single process, both serial and under `-n 8`, with identical
counts (`4981 passed, 77 skipped`, exit 0) — so the default tier is not
order-sensitive.

**Kernel tier — load-bearing, mostly green**

| package | result |
|---|---|
| kerf-cad-core | 38382 passed, 72 skipped, **12 failed, 5 errors** |

**Experimental tier — the 22 engineering domains**

Green: kerf-1dsim (117), kerf-aero (1223), kerf-apparel (161), kerf-bim (1782),
kerf-cam (1824), kerf-cfd (916), kerf-civil (783), kerf-composites (273),
kerf-costing (44), kerf-dental (538), kerf-energy (101), kerf-entertainment (36),
kerf-gdnt (229), kerf-horology (189), kerf-hvac (157), kerf-interior (141),
kerf-landscape (150), kerf-lca (221), kerf-manufacturing (115), kerf-marine (478),
kerf-microfluidics (75), kerf-motion (166), kerf-optics (450), kerf-packaging (163),
kerf-piping (414), kerf-plc (682), kerf-rules (69), kerf-silicon (1418),
kerf-slicing (86), kerf-structural (409), kerf-systems (141), kerf-textiles (514),
kerf-wiring (402), kerf-woodworking (298).

Red:

| package | result |
|---|---|
| kerf-mold | 1104 passed, **145 failed, 20 errors** |
| kerf-electronics | 6775 passed, 187 skipped, **38 failed** |
| kerf-fem | 1306 passed, 15 skipped, **8 failed** |
| kerf-firmware | 2551 passed, 1 skipped, **4 failed** |

No Python tests at all (not a failure): kerf-billing, kerf-pricing,
kerf-sdk-rs and kerf-sdk-ts (the latter two are Rust/TypeScript, covered by
`cargo test` / `npm test`).

## Root causes

Four causes account for essentially all of it.

### 1. `sys.modules` pollution across a shared pytest process — the big one

**Fixed in `a800d09b`.** Two `kerf-cad-core` test files
(`test_auto_lightweight.py`, `test_gkp_degree_op.py`) hand-loaded individual
`geom/*.py` submodules with `importlib` and registered bare
`types.ModuleType` stubs under `sys.modules["kerf_cad_core"]` and
`["kerf_cad_core.geom"]`, with no cleanup.

`sys.modules` is process-global, and those files sort early alphabetically, so
**every test file collected after them** got the hollow stub instead of the
real package — producing `"kerf_cad_core.geom" is not a package` and a long
tail of missing-export errors that look like unrelated bugs in unrelated
packages. Fixed by snapshotting and restoring the touched entries.

Evidence: `pytest packages/kerf-cad-core --collect-only -q` went from **96
collection errors to 0**, and collection rose from 36,318 to **38,844** tests —
2,526 tests that had never once executed.

This is why the full-suite number and the per-package numbers disagreed so
wildly, and it is the single most important thing to not reintroduce. **Never
write `sys.modules[...] = ...` at test-module scope without restoring it.**

### 2. `asyncio.get_event_loop()` on Python 3.13 — ~187 failures

Python 3.13 completed the long-running deprecation: `asyncio.get_event_loop()`
now raises `RuntimeError: There is no current event loop in thread 'MainThread'`
when no loop is running and none is set, instead of creating one.

Test code using it in a synchronous context (typically `setup_method`) dies:

```
packages/kerf-mold/tests/test_ejector_pin_planner.py:377: in setup_method
    self._loop = asyncio.get_event_loop()
E   RuntimeError: There is no current event loop in thread 'MainThread'.
```

Accounts for **145 failures + 20 errors in kerf-mold, 38 in kerf-electronics,
and 4 in kerf-firmware** — i.e. every currently-red experimental package except
kerf-fem. 272 test files across the repo use `get_event_loop`, concentrated in
kerf-cad-core (156), kerf-mold (23) and kerf-electronics (11); most are inside
`async def` bodies where a loop is already running, so they are fine. Only the
synchronous-context uses fail.

Fix (not yet applied — mechanical but touches many files): use
`asyncio.new_event_loop()` explicitly in setup, or `asyncio.run()`, or the
`pytest-asyncio` fixtures the repo already configures via `asyncio_mode = "auto"`.

### 3. Stale references to the deleted `backend/` tree — 4 errors, FIXED

Four `kerf-imports` test files hand-loaded their modules from a top-level
`backend/` directory that was removed in the `packages/` migration, giving
`FileNotFoundError: .../kerf/backend/tools/registry.py` at collection time.
Because these were *collection* errors they aborted the run rather than failing
a test, taking the whole package's signal with them.

Now guarded with a module-level `pytest.skip(..., allow_module_level=True)`
keyed on the missing tree, so they report honestly as skipped. **The underlying
tests are still unported** — that is 20 skipped tests in kerf-imports, not 20
passing ones.

### 4. Genuine individual bugs — 20 remaining

Not shared causes; real defects, each needing its own fix.

* **Circular import** — `kerf_cad_core.io.step_reader` cannot import
  `StepReadError` from itself: `ImportError: cannot import name 'StepReadError'
  from partially initialized module ... (most likely due to a circular
  import)`. Takes out `test_step_reader.py` entirely (1 error).
* **Missing module** — `kerf_cad_core.arch.bolt_shear_aisc_tools` does not
  exist; `test_bolt_shear_aisc.py` tests an LLM tool wrapper that was never
  written (3 failures).
* **kerf-cad-core `auto_lightweight`** — 3 real assertion failures
  (polynomial downgrade not detected, no redundant knot removed, `size_before`
  not positive). These are among the 2,526 tests that root cause #1 had been
  masking; they have probably been broken for a long time.
* **kerf-cad-core `subd_vertex_merge`** — 2 failures where vertex-merge and
  edge-collapse disagree on resulting vertex/face counts. Also newly visible.
* Plus `test_characteristic_curves.py` (4 errors), and single failures in
  `test_curvature_metrics.py`, `test_face_area_exact.py`,
  `test_gkp_subd_limit_curvature.py`, `test_mold_parting_line.py`.
* **kerf-fem** — 8 failures, all `KeyError` on result-dict keys
  (`node_displacements`, `element_vonmises_pa`, `factor_of_safety`,
  `max_vonmises_stress_pa`) in `test_solid_fem_tools.py`. API drift: the solver
  no longer returns the shape its tests expect.

### Not a root cause: the conda-forge scientific stack

Worth stating plainly, because it was the initial hypothesis. **No failure
measured here was caused by a missing conda-only CAD/scientific dependency.**
kerf-cad-core, kerf-fem, kerf-cfd, kerf-topo and kerf-cam all import and run
fine in a plain environment; kerf-cfd and kerf-cam are fully green. The
`uv sync --extra full` problem documented in `CONTRIBUTING.md` is a packaging
issue, not the reason tests fail.

## Known traps

**Two kerf-cad-core test files never terminate.**
`test_curve_resample_uniform.py` (hangs after 11 of 12 tests pass) and
`test_subd_limit_area_volume.py` (hangs after 18 of 26). A `--timeout=120`
with `--timeout-method=thread` does **not** interrupt them, which points at a
non-terminating loop in native/NumPy code that never yields to the interpreter.
`make test-kernel` `--ignore`s both. This is why the full suite could never
complete cleanly, and why any "full run" figure quoted before this document
was taken from a truncated run.

**Some packages are just slow, not broken.** kerf-textiles (7m34s),
kerf-cfd (6m39s), kerf-render (4m08s), kerf-cad-core's `test_metalens.py`
(20 tests, 8m20s) are heavy pure-Python numerics. An aggressive per-test
timeout reports them as failures when they are merely slow — all four are
green given `--timeout=600`. Do not tighten the timeout without checking this.

**kerf-cad-core is ~75 min.** 38,844 tests, dominated by numeric geometry.
Use `-n auto`, and expect the kernel tier to be a nightly rather than a
per-commit gate.

## Load-bearing vs experimental

The split behind the tiers:

* **Load-bearing** — the product genuinely depends on these: `kerf-core`,
  `kerf-api`, `kerf-auth`, `kerf-cli`, `kerf-cloud`, `kerf-chat`, `kerf-pub`,
  the SDKs, `kerf-imports`, `kerf-parts`/`kerf-partsgen`, `kerf-plm`,
  `kerf-worker`, `kerf-render`, `kerf-tess`/`kerf-topo`/`kerf-mates`, and the
  `kerf-cad-core` geometry kernel.
* **Experimental / domain** — the 22 engineering domains (FEM, CFD, CAM,
  electronics, BIM, mold, marine, silicon, ...). Substantial and largely
  passing, but aspirational relative to what ships. They should not be able to
  block a release on their own.

`packages/kerf-v1/tests` and `packages/kerf-workers/tests` were listed in
`testpaths` but **neither directory has ever existed**; pytest skipped them
silently. They have been removed rather than left as decorative entries.

## If you are fixing this

Highest value first:

1. Root cause #2 (`get_event_loop`) — one mechanical pass clears ~187 of the
   207 remaining failures and turns three domain packages green.
2. The `step_reader` circular import — one bug, restores a whole test file.
3. The two non-terminating kerf-cad-core files — until these are fixed, "run
   the whole suite" is not a thing anyone can actually do.
4. kerf-fem's result-dict drift — 8 failures, one API decision.
5. Port the 4 unported `kerf-imports` files off the deleted `backend/` tree.

When a tier goes green, move it into `testpaths` in `pyproject.toml` and delete
its row from this document. The point is for `make test` to keep meaning
something.
