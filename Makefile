.PHONY: release test test-kernel test-domains test-all desktop

# ---------------------------------------------------------------------------
# Test tiers. See docs/TESTING.md for what each tier covers, the measured
# numbers behind it, and the known root causes of the red tiers.
# ---------------------------------------------------------------------------

# DEFAULT TIER — load-bearing product packages. Expected GREEN; a failure here
# is a real regression. ~5.0k tests, ~3 min. Gated in CI by
# .github/workflows/pytest.yml's `pytest-default` job, on every PR and every
# push to main (that workflow also runs the kernel + domain tiers, but only
# on push to main and only as non-blocking/informational — see its own
# comments). Before that workflow existed, NOTHING in .github/workflows/ ran
# pytest at all — see decisions.md, "pytest test-pollution triage"
# (2026-08-09), for how that let ~1000 failures go unnoticed for days.
test:
	PYTHONHASHSEED=0 pytest -n auto

# KERNEL TIER — kerf-cad-core, the geometry kernel. Load-bearing, but ~38.8k
# tests / ~75 min with 17 known failures, so it is not in the default gate.
# The two --ignore'd files contain non-terminating tests (see docs/TESTING.md).
#
# No --rootdir override needed here (an earlier version of this target forced
# one — see git history if curious). packages/kerf-cad-core/pyproject.toml no
# longer carries its own [tool.pytest.ini_options] table — see the comment
# above [tool.pytest.ini_options] in the repo-root pyproject.toml — so this
# scoped invocation, like every other pytest invocation anywhere in the repo,
# resolves rootdir up to the repo root automatically and keeps the repo-root
# conftest.py (asyncio.get_event_loop shim, sys.path setup) and
# --import-mode=importlib. Full diagnosis in decisions.md, "pytest rootdir
# footgun" (2026-08-09).
test-kernel:
	PYTHONHASHSEED=0 pytest packages/kerf-cad-core/tests -n auto --timeout=300 \
		--ignore=packages/kerf-cad-core/tests/test_curve_resample_uniform.py \
		--ignore=packages/kerf-cad-core/tests/test_subd_limit_area_volume.py

# EXPERIMENTAL TIER — the 22 engineering-domain packages. Aspirational; several
# are RED (kerf-fem). Do not treat a failure here as a release blocker without
# reading docs/TESTING.md first.
#
# This tier deadlocks if run as a plain `pytest packages/` — see docs/TESTING.md
# "Known traps" for the investigation. Three layers guard against it:
#   1. --timeout-method=thread: the default signal-based timeout does NOT
#      break the hang (confirmed — a stuck worker sits at 0% CPU for the
#      full --timeout=600 without the SIGALRM-based interrupt ever landing).
#      thread-method does interrupt it.
#   2. --deselect removes the diagnosed offender: every test in
#      TestNACA0012Viscous (kerf-aero's viscous panel solver, NACA 0012
#      case) was independently caught hanging across two full runs (mirrors
#      how the two non-terminating kerf-cad-core files are --ignore'd out
#      of test-kernel).
#   3. --max-worker-restart=2: (1) and (2) are necessary but NOT sufficient
#      on their own — by default xdist resubmits a crashed item's remaining
#      queue to a fresh replacement worker forever, and even after (2),
#      *other* undiagnosed instances of the same class of hang turned up
#      this way (confirmed: 3 separate crash/respawn cycles in one run,
#      each costing a full --timeout period, before the run finally
#      finished at 31 minutes). Capping restarts bounds that failure mode
#      instead of letting it cascade indefinitely, at the cost of the
#      remaining queued items being abandoned (reported honestly, not
#      silently dropped) if the cap is hit.
test-domains:
	PYTHONHASHSEED=0 pytest packages/ -n auto --timeout=600 --timeout-method=thread \
		--max-worker-restart=2 \
		--ignore=packages/kerf-cad-core \
		--deselect=packages/kerf-aero/tests/test_panel_2d_viscous.py::TestNACA0012Viscous

# Everything. Slow (~90 min) and currently RED by design — see docs/TESTING.md.
# Same deadlock risk as test-domains (this runs the same packages/ tree, plus
# kerf-cad-core) — same mitigation applied, see the comment above test-domains.
test-all:
	PYTHONHASHSEED=0 pytest packages/ -n auto --timeout=600 --timeout-method=thread \
		--max-worker-restart=2 \
		--deselect=packages/kerf-aero/tests/test_panel_2d_viscous.py::TestNACA0012Viscous


# Build the one-file Kerf desktop binary: frontend build + PyInstaller.
# See scripts/build-desktop.sh and docs/desktop-build.md — including what
# the binary does NOT include (OCCT B-rep, real FEM: both conda-only).
desktop:
	./scripts/build-desktop.sh

# Cut a release: verify a clean tree, bump every version string in lockstep,
# commit, tag, and push. Pushing the tag fires .github/workflows/release.yml
# (Docker images + installable tarballs + GitHub Release).
#
# Usage:
#   make release VERSION=0.2.0
#
# See docs/releasing.md for the full flow and what CI does with the tag.
release:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release VERSION=x.y.z"; \
		exit 1; \
	fi
	./scripts/bump-version.sh $(VERSION)
	git tag v$(VERSION)
	git push origin main
	git push origin v$(VERSION)
