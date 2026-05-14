# kerf-wiring

Wiring / cable-harness diagram plugin for Kerf.

Compiles `.wiring` YAML files (WireViz harness descriptions) → SVG wiring
diagrams via the `POST /run-wireviz` pyworker route.

## Installation

```bash
pip install kerf-wiring            # plugin skeleton only (no WireViz)
pip install kerf-wiring[wireviz]   # includes WireViz for diagram rendering
```

## Licensing notice

`kerf-wiring` itself is MIT-licensed.

The optional `[wireviz]` extra pulls in
[WireViz](https://github.com/wireviz/WireViz) which is **GPLv3+**.
This has the following practical implications:

- **Hosted service**: Kerf's cloud backend invokes WireViz as a **separate
  subprocess** (via the pyworker route). Subprocess execution is not considered
  "linking" under the GPL, so the hosted service remains MIT-compatible.
- **Local / OSS install**: If you run the Kerf server locally *and* install
  the `[wireviz]` extra, WireViz is loaded in-process. By the terms of the GPL
  this means your installation of the combined work is subject to GPL
  obligations. You are free to use it for your own purposes; you are only
  obliged to share source code if you distribute the combined binary to others.
- **If you don't need wiring diagrams**: simply don't install the
  `[wireviz]` extra. The plugin loads cleanly, and the route returns a
  descriptive warning instead of crashing.

WireViz's GPLv3 notice: <https://github.com/wireviz/WireViz/blob/master/LICENSE>
