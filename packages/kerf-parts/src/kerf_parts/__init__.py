"""kerf-parts: contributor-run, MIT-clean pipeline that fetches pinned
open-source CAD parts repositories into a gitignored local cache and
converts them into Kerf-native library parts.

MIT-licensed (inherits the repo-root LICENSE). This package ships ONLY
code, the source manifest, and license/attribution docs — it never bundles
or redistributes third-party parts data. See packages/kerf-parts/LICENSES.md.
"""

__all__ = ["manifest", "fetch", "seed", "model", "adapters", "tools", "plugin"]
