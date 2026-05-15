# kerf-parts — licensing & attribution

**This package is MIT-licensed**, inheriting the Kerf repository-root
`LICENSE`. The MIT terms cover the *code, the `parts-sources.toml`
manifest, and these license/attribution docs* — i.e. everything this
package commits to git.

## Kerf does NOT redistribute third-party parts data

`kerf-parts` is a **contributor-run pipeline**, not a data bundle. It clones
the upstream repositories listed in `parts-sources.toml` into a **gitignored**
cache (`<repo_root>/.parts-cache/`) on the machine of whoever runs it, and
converts them into a local library. **No fetched or converted third-party
data is ever committed to this repository.** The clone cache, the converted
output, and the generated attribution NOTICE are all gitignored
(`/.parts-cache/` in the repo-root `.gitignore`).

This separation is the whole point of the design: it lets Kerf's MIT repo
stay clean while still letting users pull in copyleft / share-alike parts
libraries *locally on demand*.

## Upstream sources and their licenses

| Source (`name`) | Upstream | License | Notes |
| --- | --- | --- | --- |
| `kicad-symbols` | gitlab.com/kicad/libraries/kicad-symbols | **CC-BY-SA-4.0 WITH the KiCad Library Exception** | Local fetch + use OK. Bundling into this MIT repo is **not** done. |
| `kicad-footprints` | gitlab.com/kicad/libraries/kicad-footprints | **CC-BY-SA-4.0 WITH the KiCad Library Exception** | Same as above. |
| `kicad-packages3D` | gitlab.com/kicad/libraries/kicad-packages3D | **CC-BY-SA-4.0 WITH the KiCad Library Exception** | Multi-GB; `heavy=true`, opt-in via `--heavy`. |
| `bolts` | github.com/boltsparts/BOLTS | **LGPL-2.1-or-later** | Parametric standard mechanical parts. |
| `freecad-library` | github.com/FreeCAD/FreeCAD-library | **CC0-1.0 / LGPL-2.1-or-later (mixed)** | Mixed-license data tree; treat conservatively. No upstream release tags (see manifest caveat). |

### KiCad Library Exception (important)

The KiCad official libraries are licensed **CC-BY-SA 4.0 with the KiCad
Library Exception**. The Exception explicitly permits using the symbols /
footprints / 3D models in your designs without the resulting design
inheriting CC-BY-SA. That makes **local fetch + use** completely fine.

It is **not** a grant to relicense or bundle the *library data itself* into
an MIT-licensed repository. Therefore `kerf-parts` never commits that data —
it is fetched locally per contributor. When the pipeline converts a KiCad
source it writes an attribution / NOTICE file into the **gitignored**
generated output directory (`.parts-cache/_generated/ATTRIBUTION-NOTICE.txt`),
satisfying the attribution requirement for the local copy without touching
the repo.

## Bumping a pinned source

Every source is pinned to a specific upstream tag/ref for reproducibility.
See the header comment in `parts-sources.toml` for the exact bump procedure.
Commit *only* the manifest change — never the cache or generated output.
