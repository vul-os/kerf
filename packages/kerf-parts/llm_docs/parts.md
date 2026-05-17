# kerf-parts — MIT parts ingest pipeline

`kerf-parts` is a standalone Python package (not a FastAPI plugin) that ingests open-source part libraries into the Kerf parts library. It handles fetching upstream repositories, running adapter-specific parsing, computing deterministic content hashes for incremental re-seeding, and embedding attribution metadata automatically.

---

## Architecture

```
parts-sources.toml          — manifest of upstream sources to ingest
  ↓
kerf_parts.manifest         — Source dataclasses
  ↓
kerf_parts.fetch            — git clone / update of upstream repos
  ↓
kerf_parts.adapters.*       — source-specific parsers → KerfPart objects
  ↓
kerf_parts.provenance       — embed attribution (git history, LICENSE, AUTHORS)
  ↓
kerf_parts.seed             — write KerfPart objects to Kerf DB / files
```

---

## KerfPart (`kerf_parts.model`)

The canonical in-memory part representation. Maps directly to a `kind='part'` file's JSON content.

```python
@dataclass
class KerfPart:
    name: str
    category: str = ""
    description: str = ""
    manufacturer: str = ""
    mpn: str = ""           # Manufacturer Part Number
    value: str = ""
    datasheet_url: str = ""
    schematic_symbol: dict | None = None
    pcb_footprint: dict | None = None
    model_3d_paths: list[str] = []
    distributors: list[dict] = []
    metadata: dict = {}      # includes attribution block
    content_hash: str = ""   # SHA-256 of serialised doc; used for incremental seeding
    rel_path: str = ""       # e.g. "KiCad/Symbols/Device/R.part"
```

`part.to_part_doc()` produces the exact JSON body written to the `files` table. No schema migration required — this is the same format `kerf_api.tools.scaffold.run_create_part` already produces.

`part.ensure_hash()` computes `SHA-256(json.dumps(to_part_doc(), sort_keys=True))` if not already set. This makes re-seeding idempotent — unchanged parts are skipped.

---

## Adapters

### `adapters.kicad` — KiCad symbol/footprint library

Parses KiCad `.kicad_sym` symbol files and `.kicad_mod` footprint files. Extracts:
- Part name, description, keywords, datasheet URL
- Schematic symbol as a structured dict (compatible with Kerf's circuit editor)
- PCB footprint metadata
- Manufacturer and MPN from the `ki_keywords` / properties fields

### `adapters.bolts` — Bolts open-source fastener library

Parses the Bolts YAML/JSON specification files for standard fasteners (ISO, DIN, ANSI). Emits one `KerfPart` per fastener family/size combination with structured mechanical properties.

### `adapters.freecad_library` — FreeCAD parts library

Parses the FreeCAD Parts Library XML manifests. Extracts part metadata and 3D model paths.

### `adapters.jewelry_supplier` — jewelry supplier catalog

Parses jewelry supplier CSV/JSON catalogs for findings, chains, settings, and gemstone carriers.

---

## Attribution (`kerf_parts.provenance`)

Every ingested part MUST carry embedded authorship. The `build_attribution` function implements a strict fallback chain:

1. **Per-file git history** (strongest): scoped `git log --diff-filter=A --follow` on the upstream source file → `original_author`, `original_date`, `contributors`
2. **Repo-level authorship**: copyright holders parsed from `LICENSE`/`AUTHORS`/`CONTRIBUTORS` files
3. **Manifest fallback**: `source_project` + `license` from `parts-sources.toml`

```python
from kerf_parts.provenance import attach_attribution

attach_attribution(source, repo_path, part, source_file_rel)
# Stamps part.metadata["attribution"] and part.metadata["attribution_text"]
```

`attach_attribution` is the single call every adapter makes. Parts cannot leave the pipeline without provenance — a blank `original_author` is a bug, not a valid state.

Shallow clones: when `--depth 1` prevents seeing the creating commit, the code runs `git fetch --unshallow` (with progressive `--deepen` fallbacks). If the clone genuinely cannot be deepened, it falls back to repo-level authorship and flags `history_truncated=True`.

The `attribution_text` field is a human-readable one-liner that travels with the part into Workshop, BOM, and NOTICE files.

---

## Seed runner (`kerf_parts.seed`)

The seeder writes `KerfPart` objects into the Kerf DB by creating `kind='part'` rows in the `files` table under a designated "Parts Library" system project. It uses `content_hash` to skip unchanged parts on subsequent runs (incremental, idempotent).

---

## `parts-sources.toml`

Declares upstream sources:

```toml
[[source]]
name        = "KiCad Symbols"
git_url     = "https://gitlab.com/kicad/libraries/kicad-symbols"
ref         = "8.0.0"
license     = "CC-BY-SA-4.0"
adapter     = "kicad"

[[source]]
name        = "Bolts"
git_url     = "https://github.com/boltsparts/BOLTS"
ref         = "main"
license     = "LGPL-2.1-or-later"
adapter     = "bolts"
```

---

## LICENSES.md

The package ships `LICENSES.md` listing all upstream source licenses. This is auto-generated from the `attribution` blocks embedded in seeded parts, so the license notices and the data always stay in sync.
