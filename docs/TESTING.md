# Testing

This document exists because, until 2026-07-19, nobody had ever run the whole
test suite. Per-package reports were green, but only for the packages they
covered, so the repo had no trustworthy notion of "green" — a real regression
and ordinary background noise looked exactly the same.

The suite has now been measured end to end, package by package. This is the
honest result, including the parts that are red.

## TL;DR

```bash
make test          # DEFAULT — load-bearing packages. GREEN. ~5.05k tests, ~2 min.
make test-kernel   # kerf-cad-core geometry kernel. ~38.8k tests, ~75 min, 17 known failures.
make test-domains  # the 21 remaining engineering domains. Experimental. Still RED (kerf-fem only) —
                    #   and can take 10-30+ min: see "Known traps" for a genuine cross-package hang.
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

| | full-suite run (2026-07-19) | measured per-package (after `a800d09b`) | after root cause #2 fix |
|---|---|---|---|
| failed | 1563 | **207** | **20** |
| errors | 180 | **29** (4 of which are now fixed → **25**) | **5** |

The remaining 20 failed / 5 errors are entirely `kerf-cad-core` (12 failed, 5
errors, kernel tier) and `kerf-fem` (8 failed, domain tier) — see root cause
#4 below.

The gap between the full-suite run and the per-package measurement is
explained by root cause #1 below: a `sys.modules` leak that only
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
| kerf-rules | 69 passed |

Verified as a single process, both serial and under `-n auto`, with identical
counts (`5050 passed, 77 skipped`, exit 0) — so the default tier is not
order-sensitive.

**2026-07-20: `kerf-rules` moved into the default tier.** It was sitting in
the domain/experimental list below even though it's a KBE rules engine
invoked by product code, not a simulation domain — load-bearing by any
reading, small (69 tests, all green), and adding it doesn't change the
default tier's runtime materially (still ~2 min). `kerf-billing` was
considered too but has **no tests to add** — see the note below the
experimental-tier table; it was removed from the repo entirely in `6f0e66ba`
("kerf is 100% MIT free software") and no longer exists as a package.

**Kernel tier — load-bearing, mostly green**

| package | result |
|---|---|
| kerf-cad-core | 38382 passed, 72 skipped, **12 failed, 5 errors** |

**Experimental tier — the 21 remaining engineering domains**

(`kerf-rules` moved to the default tier above on 2026-07-20 — see the note
there.)

Green: kerf-1dsim (117), kerf-aero (1223), kerf-apparel (161), kerf-bim (1782),
kerf-cam (1824), kerf-cfd (916), kerf-civil (783), kerf-composites (273),
kerf-costing (44), kerf-dental (538), kerf-energy (101), kerf-entertainment (36),
kerf-gdnt (229), kerf-horology (189), kerf-hvac (157), kerf-interior (141),
kerf-landscape (150), kerf-lca (221), kerf-manufacturing (115), kerf-marine (478),
kerf-microfluidics (75), kerf-motion (166), kerf-optics (450), kerf-packaging (163),
kerf-piping (414), kerf-plc (682), kerf-silicon (1418),
kerf-slicing (86), kerf-structural (409), kerf-systems (141), kerf-textiles (514),
kerf-wiring (402), kerf-woodworking (298), **kerf-mold (1269, fixed 2026-07-19),
kerf-electronics (6813 passed, 187 skipped, fixed 2026-07-19), kerf-firmware
(2555 passed, 1 skipped, fixed 2026-07-19)**.

kerf-aero's 1223 count above is measured **alone** and is accurate — the
package is fully green in isolation. It only produces failures/hangs as part
of a large combined run; see "Known traps" below.

Red:

| package | result |
|---|---|
| kerf-fem | 1306 passed, 15 skipped, **8 failed** |

`kerf-mold`, `kerf-electronics` and `kerf-firmware` were all-`get_event_loop`
(root cause #2) and are now fully green with zero genuine bugs found in any
of the three — see that section below for the exact before/after counts.

No Python tests at all (not a failure): kerf-pricing, kerf-sdk-rs and
kerf-sdk-ts (the latter two are Rust/TypeScript, covered by `cargo test` /
`npm test`). **kerf-billing isn't in this list because it doesn't exist any
more** — it was removed from the repo entirely in `6f0e66ba` ("kerf is 100%
MIT free software — BYO boxes; local usage telemetry kept"), an ancestor of
current `main`: no `pyproject.toml`, no `src/`, no `tests/`, not a workspace
member, zero remaining references anywhere in the tree. If you see a report
that treats "kerf-billing has no default-tier coverage" as a gap, that report
is stale — there is nothing to cover.

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

### 2. `asyncio.get_event_loop()` on Python 3.13 — FIXED 2026-07-19

Python 3.13 completed the long-running deprecation: `asyncio.get_event_loop()`
now raises `RuntimeError: There is no current event loop in thread 'MainThread'`
when no loop is running and none is set, instead of creating one.

Test code using it in a synchronous context (typically `setup_method`) died:

```
packages/kerf-mold/tests/test_ejector_pin_planner.py:377: in setup_method
    self._loop = asyncio.get_event_loop()
E   RuntimeError: There is no current event loop in thread 'MainThread'.
```

272 test files across the repo use `get_event_loop`, concentrated in
kerf-cad-core (156), kerf-mold (23) and kerf-electronics (11); most are inside
`async def` bodies where a loop is already running, so those are fine and were
deliberately left untouched. Only the synchronous-context uses failed —
35 files with a module-level `_run(coro)` / `run_async(coro)` helper or an
inline call chained directly as `asyncio.get_event_loop().run_until_complete(`,
plus 2 files (`test_ejector_pin_planner.py`, `test_ejector_stroke_verify.py`)
using a per-test `setup_method` that stashed `self._loop`.

**Fix applied**, matched to each call site's shape:

* The 35 one-shot call sites → `asyncio.get_event_loop().run_until_complete(`
  became `asyncio.run(`. Each call already created and discarded its result
  independently (no state carried between calls), so a fresh loop per call is
  both correct and the simplest modern idiom — no `pytest-asyncio` fixtures
  were introduced since nothing else in these files used them.
* The 2 `setup_method`/`self._loop` files → `asyncio.new_event_loop()` in
  `setup_method` (which pytest already re-runs per test, so the loop's
  lifetime was always meant to be per-test) plus a new `teardown_method` that
  calls `self._loop.close()`, since a loop created explicitly should be
  closed explicitly.

Verified: every failure and error in all three packages traced to this one
`RuntimeError` (confirmed via `--tb=line`, no unrelated exception types mixed
in) — **zero genuine bugs found in kerf-mold, kerf-electronics or
kerf-firmware**; the ~20 genuine individual bugs the triage flagged live
elsewhere (kerf-cad-core, kerf-fem — see #4).

| package | before | after |
|---|---|---|
| kerf-mold | 1104 passed, 145 failed, 20 errors | **1269 passed** |
| kerf-electronics | 6775 passed, 187 skipped, 38 failed | **6813 passed, 187 skipped** |
| kerf-firmware | 2551 passed, 1 skipped, 4 failed | **2555 passed, 1 skipped** |

Confirmed stable under `-n auto` too (10637 passed, 188 skipped across all
three together). `make test` (the gate) is unaffected — these are
domain-tier packages excluded from `testpaths` — reconfirmed at
**4981 passed, 77 skipped, exit 0** after this fix (now **5050 passed, 77
skipped** with `kerf-rules` added — see "The numbers" above).

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

**`make test-domains` deadlocks at full scale — investigated 2026-07-20, not
fully root-caused, now mitigated.** Running all 21 domain packages (plus the
default-tier ones, since `test-domains` is `pytest packages/` minus
`kerf-cad-core`) together under `-n auto`/`-n 8` reliably stalls, typically
around 93-99% complete, with every xdist worker sitting at **0% CPU** — not
spinning, blocked. This is a different failure from the two known-hung
`kerf-cad-core` files above (which are excluded from this tier entirely) and
from kerf-fem's 8 known assertion failures (which are fast, not hangs).

What was established by reproducing it directly (killing and re-running the
real `pytest packages/ -n auto --timeout=600 --ignore=packages/kerf-cad-core`
several times, foreground, with process/fd inspection via `ps`/`lsof` — no
`py-spy`/`lldb` stack traces were obtainable, both need `sudo` that wasn't
available):

* `--timeout=600` (the default signal-based timeout) does **not** break the
  hang — confirmed by watching a stuck worker sit at 0% CPU for the full
  600s with no interrupt ever landing. `--timeout-method=thread` **does**
  interrupt it (this is the one piece that matches the original report).
* `--timeout-method=thread` **alone is not sufficient**, though. By default
  pytest-xdist replaces a crashed worker and keeps handing it the remaining
  queue. In one full run this cascaded through **5 separate crash/respawn
  cycles over more than 60 minutes** without the run ever finishing — each
  replacement worker picked up the queue, hung again, and got killed again
  at the next 600s mark.
* Using `-x` (exit on first failure) to catch the culprit by name identified
  it precisely: `packages/kerf-aero/tests/test_panel_2d_viscous.py`, class
  `TestNACA0012Viscous` (the NACA 0012 viscous panel-solver integration
  tests). Across two separate reproductions, **all four** of that class's
  tests (`test_cd_within_15pct_of_xfoil`, `test_cl_symmetric`,
  `test_converges_within_50_iters`, `test_transition_detected_upper`) were
  independently caught as the worker's in-flight test at the moment of a
  timeout-triggered crash.
* This package/test is **not** individually suspicious: `panel_solve_viscous`
  (`packages/kerf-aero/src/kerf_aero/panel_2d_viscous.py`) is pure NumPy,
  every loop is a bounded `for ... in range(...)` (no `while`), and it makes
  no subprocess/network/thread calls of its own. `kerf-aero/tests` alone
  under `-n auto` passed **3/3** reruns in ~37s each. An 8-package subset
  chosen to include the other numerically-heaviest domains (`kerf-aero` +
  `kerf-cfd` + `kerf-cam` + `kerf-bim` + `kerf-electronics` + `kerf-silicon`
  + `kerf-firmware` + `kerf-mold`) also passed clean, no hang, in ~3.5 min.
  The hang only appeared at the full `test-domains`/`test-all` scale — one
  lsof snapshot of a stuck worker showed it holding an idle `kqueue`
  (0 pending events) plus a `com.apple.netsrc` control socket that no other
  worker had, which is *consistent with* (but doesn't prove) native-level
  contention — most plausibly in the BLAS/LAPACK backend NumPy's linear
  solve calls into, under the load of ~40+ concurrently-launched Python
  processes each spinning up their own BLAS thread pool. This was not
  chased further (would need a native stack trace, which needs `sudo` on
  this machine) — **treat this as narrowed, not root-caused.**
* Given (2), whack-a-mole `--deselect`ing individual tests isn't reliable —
  more, undiagnosed instances of the same class of hang surfaced elsewhere
  in the run even after deselecting the whole `TestNACA0012Viscous` class.
  The mitigation that was actually verified to make the command terminate is
  `--max-worker-restart=2`: it bounds the crash/respawn cascade instead of
  letting it run forever. A full verification run with all three mitigations
  together (`--timeout-method=thread --max-worker-restart=2` plus the
  `TestNACA0012Viscous` deselect) **completed in 31 minutes** (vs. never, for
  the unmitigated command), hitting the restart cap once along the way and
  finishing with an honest `11 failed, 31169 passed, 396 skipped` — the 8
  known kerf-fem failures plus 3 more kerf-aero `TestNACA0012Viscous` tests
  that got caught and force-failed by the safety net before the deselect
  fully suppressed that run's particular scheduling. `make test-domains` and
  `make test-all` now carry all three mitigations (see the comments above
  each target in the `Makefile`). **Expect `make test-domains` to
  legitimately take anywhere from ~10 to ~30+ minutes** depending on whether
  it hits the hang class again during a given run — this is a real,
  unresolved flakiness in the tier, not a documentation error.

## Load-bearing vs experimental

The split behind the tiers:

* **Load-bearing** — the product genuinely depends on these: `kerf-core`,
  `kerf-api`, `kerf-auth`, `kerf-cli`, `kerf-cloud`, `kerf-chat`, `kerf-pub`,
  the SDKs, `kerf-imports`, `kerf-parts`/`kerf-partsgen`, `kerf-plm`,
  `kerf-worker`, `kerf-render`, `kerf-tess`/`kerf-topo`/`kerf-mates`,
  `kerf-rules`, and the `kerf-cad-core` geometry kernel.
* **Experimental / domain** — the 21 remaining engineering domains (FEM, CFD,
  CAM, electronics, BIM, mold, marine, silicon, ...). Substantial and largely
  passing, but aspirational relative to what ships. They should not be able to
  block a release on their own.

`packages/kerf-v1/tests` and `packages/kerf-workers/tests` were listed in
`testpaths` but **neither directory has ever existed**; pytest skipped them
silently. They have been removed rather than left as decorative entries.

## If you are fixing this

Highest value first:

1. ~~Root cause #2 (`get_event_loop`)~~ — **done 2026-07-19**, cleared 187
   failures + 20 errors and turned kerf-mold, kerf-electronics and
   kerf-firmware fully green. Remaining red: kerf-cad-core (kernel tier, 12
   failed/5 errors) and kerf-fem (8 failed).
2. ~~`kerf-rules` missing from the default gate~~ — **done 2026-07-20**,
   added to `testpaths`. Default tier is now 5050 passed, 77 skipped.
3. ~~`make test-domains` deadlock~~ — **mitigated 2026-07-20** (not
   root-caused — see "Known traps"). The command now terminates instead of
   hanging forever, but the underlying `kerf-aero`/`TestNACA0012Viscous`
   cross-package hang is still there, just bounded. A real fix needs a
   native stack trace (`py-spy`/`lldb`, needs `sudo` — not available in this
   environment) to find out what's actually blocking inside NumPy's
   BLAS/LAPACK call at full-suite concurrency.
4. The `step_reader` circular import — one bug, restores a whole test file.
5. The two non-terminating kerf-cad-core files — until these are fixed, "run
   the whole suite" is not a thing anyone can actually do.
6. kerf-fem's result-dict drift — 8 failures, one API decision.
7. Port the 4 unported `kerf-imports` files off the deleted `backend/` tree.

When a tier goes green, move it into `testpaths` in `pyproject.toml` and delete
its row from this document. The point is for `make test` to keep meaning
something.
