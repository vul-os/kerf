.PHONY: release test test-kernel test-domains test-all

# ---------------------------------------------------------------------------
# Test tiers. See docs/TESTING.md for what each tier covers, the measured
# numbers behind it, and the known root causes of the red tiers.
# ---------------------------------------------------------------------------

# DEFAULT TIER — load-bearing product packages. Expected GREEN; a failure here
# is a real regression. ~5.0k tests, ~3 min. This is what CI gates on.
test:
	PYTHONHASHSEED=0 pytest -n auto

# KERNEL TIER — kerf-cad-core, the geometry kernel. Load-bearing, but ~38.8k
# tests / ~75 min with 17 known failures, so it is not in the default gate.
# The two --ignore'd files contain non-terminating tests (see docs/TESTING.md).
test-kernel:
	PYTHONHASHSEED=0 pytest packages/kerf-cad-core/tests -n auto --timeout=300 \
		--ignore=packages/kerf-cad-core/tests/test_curve_resample_uniform.py \
		--ignore=packages/kerf-cad-core/tests/test_subd_limit_area_volume.py

# EXPERIMENTAL TIER — the 22 engineering-domain packages. Aspirational; several
# are RED (kerf-mold, kerf-electronics, kerf-fem, kerf-firmware). Do not treat
# a failure here as a release blocker without reading docs/TESTING.md first.
test-domains:
	PYTHONHASHSEED=0 pytest packages/ -n auto --timeout=600 \
		--ignore=packages/kerf-cad-core

# Everything. Slow (~90 min) and currently RED by design — see docs/TESTING.md.
test-all:
	PYTHONHASHSEED=0 pytest packages/ -n auto --timeout=600


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
