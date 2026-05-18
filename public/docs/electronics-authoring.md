# Electronics Authoring: atopile + tscircuit

Two authoring styles, one fabrication target.

Kerf supports two first-class approaches to electronics design. Both compile
to the same CircuitJSON intermediate, generate the same gerber outputs, and
integrate with the same SPICE, RF, SI/EMC/PDN/thermal toolchain. The choice
is about how you prefer to think about a circuit — not about what you can
produce.

---

## 1. Two paths, same destination

Every circuit in Kerf — regardless of which authoring style you use — ends
up as CircuitJSON before it hits any downstream tool. That means:

- The same FreeRouting autoroute works for both.
- The same DRC / ERC rules apply.
- The same gerber exporter emits fab-ready files.
- The same BOM export pulls distributor pricing from DigiKey / Mouser / LCSC.
- The same mechanical link lets you place a PCB outline inside a 3D assembly.

You can mix files in a project. A `.ato` module can be instantiated inside a
`.circuit.tsx` schematic or vice versa, as long as the interface is expressed
as net connections.

---

## 2. atopile — code-first, `.ato`

atopile treats a circuit the way a software engineer treats a library:
components are modules with typed interfaces (ports), and you connect them
by assignment.

**File extension:** `.ato`

**Syntax flavour:** Python-like indentation, declarative instantiation,
assignment-as-connection.

```ato
module Blinker:
    mcu = new RP2040
    led = new LED_0603
    r = new Resistor

    r.value = 330ohm +/- 10%
    mcu.GPIO[0] ~ r.p1
    r.p2 ~ led.anode
    led.cathode ~ gnd
```

**Why atopile suits you:**

- **Native units** — resistance, capacitance, inductance and tolerances are
  first-class values. `330ohm +/- 10%` is not a string; the solver checks it.
- **Parametric by default** — override a parameter in a child module without
  touching its source. Inheritance works like class extension.
- **Git-friendly diffs** — because `.ato` is plain text with stable structure,
  pull-request diffs are readable. Changing a resistor value produces a
  one-line diff, not a binary blob.
- **Reusable modules** — publish a power-supply module to the Kerf Library;
  anyone can instantiate it with `new` and override the output voltage.

atopile is the right fit when your circuit is driven by calculations (filter
design, impedance matching, power budgets) and when you want the same
parametric-reuse story that JSCAD gives you on the mechanical side.

---

## 3. tscircuit — visual-first, `.tsx`

tscircuit brings JSX to electronics. You describe a circuit the way a React
developer describes a UI: components are JSX elements, props are parameters,
and the renderer turns the tree into a routed schematic or PCB view.

**File extension:** `.circuit.tsx`

**Syntax flavour:** TypeScript JSX, same mental model as React component trees.

```tsx
import { createCircuit } from '@tscircuit/core'

export default () => (
  <board width="50mm" height="30mm">
    <chip
      name="U1"
      footprint="soic8"
      schX={0}
      schY={0}
    />
    <resistor
      name="R1"
      resistance="10kohm"
      footprint="0402"
      schX={2}
      schY={0}
    />
    <trace from=".U1 .pin1" to=".R1 .pos" />
  </board>
)
```

**Why tscircuit suits you:**

- **Interactive preview** — the Kerf viewport renders a live schematic and PCB
  view as you type, with hot-reload powered by the tscircuit worker.
- **Big footprint catalog** — `@tscircuit/footprinter` ships thousands of
  verified IPC-compliant footprints; reference them by name in a prop.
- **JSX composability** — extract a voltage-divider into a component, accept
  props, render it multiple times. The same patterns you use in frontend work.
- **TypeScript types** — prop types for pad counts, pin mappings, and net
  names are checked by the TS compiler before the circuit ever evaluates.

tscircuit is the right fit when you are coming from a web-development
background, when you value the live-preview loop, or when you are building a
circuit that maps naturally to a component hierarchy (e.g. a module with a
defined connector interface that gets reused across board variants).

---

## 4. FAQ: when to choose which

**I want to do impedance-matched RF design with toleranced components.**

Use atopile. Native units and the parametric solver are built for this.
Derive characteristic impedance, express tolerances on passives, and let the
module system propagate constraints.

**I am prototyping a new dev-board and want to see the layout as I go.**

Use tscircuit. The live PCB preview updates on every keystroke. Drag
components in the interactive layout mode; the JSX updates to match.

**I want to publish a reusable power-supply block to the Library.**

Either works. atopile modules expose typed ports naturally and are easy to
instantiate with `new`. tscircuit components accept typed props and compose
well in JSX trees. Pick the one that matches the audience you are writing for.

**I have an existing KiCad schematic I want to import.**

Kerf's KiCad importer outputs `.circuit.tsx`. Start there, then refactor into
`.ato` modules if you want parametric reuse later.

**Can I use both in the same project?**

Yes. The CircuitJSON boundary is the common ground. A `.ato` module compiles
to a set of components and nets; a `.circuit.tsx` schematic does the same.
You can import either into the other via the Kerf module resolver.

**Which one does the LLM use?**

The chat agent defaults to tscircuit for new schematics (JSX is easier to
generate reliably) and uses atopile when you ask for parametric or
calculation-driven work. You can override the preference in the system prompt
or by starting a file with the relevant extension.

---

## Further reading

- [Electronics capabilities overview](/docs/electronics)
- [SPICE simulation](/docs/capabilities)
- [RF / S-parameter analysis](/docs/capabilities)
- [atopile language reference](https://atopile.io/docs)
- [tscircuit documentation](https://tscircuit.com/docs)
- [CircuitJSON spec](https://github.com/tscircuit/circuit-json)
