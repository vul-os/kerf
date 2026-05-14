# Authoring `.jscad` files

JSCAD Parts are the default Kerf modeling surface. A `.jscad` file
exports a function whose return is an array of Objects. Each Object
has an `id` (string) and a `geom` (a JSCAD geometry value).

This is the kind you edit MOST often — and you usually edit it via
`edit_file` with a tight unique substring, not via any dedicated tool.

## Canonical file shape

```js
export default function ({ primitives, transforms, booleans, extrusions }) {
  const base = primitives.cuboid({ size: [40, 40, 10] })
  const peg  = transforms.translate([0, 0, 5],
    primitives.cylinder({ radius: 4, height: 20 }))

  return [
    { id: 'base', geom: base },
    { id: 'peg',  geom: peg },
  ]
}
```

The default export receives the `@jscad/modeling` namespaces spread
into a single object — destructure whichever namespaces you need.
The `[{id, geom}, ...]` return is canonical. Every entry is an
**Object**; `id` becomes its identity for assemblies and viewport
picking.

## Namespaced API

JSCAD's `@jscad/modeling` exposes a single root object. All operations
live under namespaces; importing them at the top is conventional.

| Namespace         | What it does                                              |
|-------------------|-----------------------------------------------------------|
| `primitives`      | `cuboid`, `cylinder`, `sphere`, `polyhedron`, `circle`, `rectangle`, `roundedCuboid`, `torus` |
| `transforms`      | `translate`, `rotate`, `rotateX/Y/Z`, `scale`, `mirror`   |
| `booleans`        | `union`, `subtract`, `intersect`                          |
| `extrusions`      | `extrudeLinear`, `extrudeRotate` (revolve), `project`     |
| `hulls`           | `hull`, `hullChain`                                       |
| `expansions`      | `offset`, `expand`                                        |
| `colors`          | `colorize`, `hsl2rgb`                                     |

Calls take an options object first, geometry last:

```js
extrusions.extrudeLinear({ height: 10 }, sketch2d)
booleans.subtract(base, peg)
transforms.translate([0, 0, 5], cylinder({ radius: 4, height: 20 }))
```

## Object identity

The `id` on each return entry is what assemblies reference and what
the Objects panel surfaces. Pick stable, descriptive ids (`base`,
`bracket-left`, `peg`). Don't use uuid-style randomness — assemblies
hard-link by id.

If you split a single Part into two, the user has to update any
assembly that referenced the old single Object — flag this in your
summary.

## Importing sketches

Use a top-level ES `import` statement — this is the **only** form the
runtime implements. The runner strips the import line, resolves the
`.sketch` path through the project tree, converts it to a JSCAD `Geom2`,
and injects it into the function's argument scope under the binding name
you choose.

```js
import profile from '/parts/bracket-outline.sketch'

export default function ({ extrusions }) {
  return [
    { id: 'wall', geom: extrusions.extrudeLinear({ height: 20 }, profile) },
  ]
}
```

The binding name (`profile` above) is arbitrary — pick something
descriptive. Multiple sketches work with multiple import lines:

```js
import outerProfile from '/parts/shell-outer.sketch'
import innerProfile from '/parts/shell-inner.sketch'

export default function ({ extrusions, booleans }) {
  const outer = extrusions.extrudeLinear({ height: 30 }, outerProfile)
  const inner = extrusions.extrudeLinear({ height: 30 }, innerProfile)
  return [{ id: 'shell', geom: booleans.subtract(outer, inner) }]
}
```

Sketches resolve to a `Geom2`. `extrudeLinear` and `extrudeRotate`
both accept it directly.

> **Do not** use `require('/x.sketch')` — the runtime does not implement
> CommonJS `require` resolution for sketch paths. Only the ES `import`
> form above is wired end-to-end.

## Equations as `params` — parametric values from `.equations`

Any `.equations` file in the project is evaluated and its resolved
values are injected into the JSCAD function as `params` — the same
argument object that carries the modeling namespaces. You don't need
to import or read the equations file; the runner merges the scope for
you before calling your function.

```js
// params.equations defines: wall_thickness = 3, height = 20
export default function ({ primitives, extrusions, params }) {
  const { wall_thickness, height } = params
  const profile = primitives.rectangle({ size: [60, 40] })
  const shell = extrusions.extrudeLinear({ height }, profile)
  return [{ id: 'shell', geom: shell }]
}
```

If the `.equations` file also drives sketch dimensions (via
`${wall_thickness}` placeholders in the sketch), then editing one
equation reflows both the sketch profile and the JSCAD extrusion
simultaneously — the sketch and the `.jscad` share the same param
scope.

`params` is always an object (never null). If no `.equations` file
exists in the project, `params` is `{}`. Always destructure with a
fallback if you want to handle that case:

```js
const { wall_thickness = 3 } = params   // fallback to 3 if no equations
```

> For the full equations file syntax and where values flow (sketches,
> features, JSCAD), see [`equations.md`](equations.md).

## Choosing `.jscad` vs `.feature`

| Aspect | `.sketch` + `.jscad` (mesh) | `.sketch` + `.feature` (BRep) |
|---|---|---|
| Geometry kernel | JSCAD CSG (mesh booleans) | OCCT (B-rep) |
| STEP export | Tessellated (lossy) | Lossless |
| Real fillets | No (`hull` / `roundedCuboid` only) | Yes (`feature_fillet`) |
| Programmability | Full JS — loops, conditionals, recursion | JSON tree; loops via configurations |
| Local dependency | None — pure JS | OCCT WASM (~6 MB) |
| Eval cost | ms-scale | 10s of ms to seconds |
| Manufacturing-grade | No (mesh tolerances) | Yes |
| Surfacing | Limited | NURBS sweep / network / blend |

**Rule of thumb:**

- Pick `.feature` when the user mentions STEP export, manufacturing,
  fillets, chamfers, draft angles, or interop with FreeCAD / SolidWorks.
- Pick `.sketch + .jscad` when the user wants quick parametric variants,
  mesh-only ops (`hull`, `colorize`, instancing), or has no OCCT installed.

## Complete worked example — sketch import + params + extrude

This is the canonical pattern emitted by the `extrude_sketch_to_jscad`
tool. Copy it as-is and edit the values:

```js
// Generated from /parts/bracket-outline.sketch
// Edit the sketch to change the profile; the 3D updates automatically.
// Edit params.equations to change bracket_h; it reflows here and in the sketch.
import profile from '/parts/bracket-outline.sketch'

export default function ({ extrusions, params }) {
  // params.bracket_h comes from the project's .equations file.
  // Fallback to 10 mm if no equations file exists yet.
  const height = params.bracket_h ?? 10

  const body = extrusions.extrudeLinear({ height }, profile)
  return [{ id: 'bracket', geom: body }]
}
```

The sketch (`/parts/bracket-outline.sketch`) contains the 2D profile with
constrained dimensions. The `.equations` file holds `bracket_h`. Changing
either one reflows the 3D without touching this file.

## Importing other JSCAD files

```js
import parts from '/shared/parts.jscad'  // not supported yet — use copy-paste for now
```

> Cross-file JSCAD imports are not yet implemented. For shared geometry,
> copy the relevant primitive definitions directly into your file or factor
> out the common shape into a `.sketch` profile and import that instead.

## Common edits

### Make a dimension parametric

If a value is local to this file, define it as a const at the top:

```js
export default function ({ primitives }) {
  const width = 40, height = 10, peg_d = 8
  const base = primitives.cuboid({ size: [width, width, height] })
  // ...
}
```

Then a `set the width to 60` request is a one-line `edit_file`.

For project-wide params shared with sketches and features, use a
`.equations` file and read from `params` (see the section above).

### Add a fillet (JSCAD path — no real B-rep round)

JSCAD doesn't expose a true fillet. Approximations:
- `roundedCuboid({ size, roundRadius })` — only useful for the whole
  outer shell.
- Boolean a quarter-cylinder along an edge to round it (visual fudge
  for renders, NOT for STEP export).

For a real fillet, use a `.feature` file (see `feature.md`).

### Add a new Object to an existing Part

`edit_file` to extend the return array:

```text
old:
  return [
    { id: 'base', geom: base },
  ]
new:
  return [
    { id: 'base', geom: base },
    { id: 'peg',  geom: translate([0,0,5], cylinder({ radius: 4, height: 20 })) },
  ]
```

Or use `duplicate_object` to clone a shape with a fresh id (the
duplicate_object tool understands the bracket-matched array literal
and writes a structurally-correct clone).

### Remove an Object from a Part

`delete_object` is the safe way (bracket-matched). `edit_file` works
too if the entry is a unique substring.

## Anti-patterns

- Don't return a single geometry instead of `[{id, geom}, ...]` — the
  rest of Kerf (assemblies, drawings, BOM) breaks.
- Don't `console.log` from JSCAD — the worker pipes errors to the
  problem panel; logs go nowhere useful.
- Don't use top-level `await` in a JSCAD module — the runner is
  synchronous.
- Don't reference Three.js directly. JSCAD's geometry is its own
  format; the renderer turns it into Three.js meshes.
- Don't use `require('@jscad/modeling')` or `require('/x.sketch')` —
  neither is implemented. The runner does not provide a CommonJS
  `require`. Use `export default function ({ ...namespaces })` for
  the modeling API and `import profile from '/x.sketch'` for sketches.
- Don't use `import` statements for `@jscad/modeling` — the runner
  strips all `import` lines from `@jscad/modeling`; namespaces are
  injected via the function argument automatically.
