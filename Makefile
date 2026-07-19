.PHONY: release

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
