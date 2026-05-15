/**
 * /compare/kicad — Kerf vs KiCad
 *
 * Web-grounded (last reviewed 2026-05-15). KiCad 10.0 shipped March 2026
 * (10.0.2 in May 2026): GPL v3, fully free, cross-platform. It now natively
 * exports IPC-2581 *and* ODB++, gained an overhauled track-tuning system with
 * time-domain constraints, design variants, a graphical DRC rule editor, and
 * Allegro/PADS/gEDA importers. ngspice is built in. KiCad's depth and
 * community on the pure-PCB side are formidable.
 *
 * Kerf covers much of the same electronics ground and adds a unified
 * mechanical CAD workspace, chat-native editing, and the kerf-sdk — but does
 * not match KiCad's EDA maturity, library breadth, or community today.
 */
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { makeCompareMeta } from './compareMeta.js'
import {
  Section,
  Li,
  CompareTable,
  TableFooter,
  FairnessNote,
  CTAStrip,
  Breadcrumb,
  HeadMeta,
  GOOD,
  WEAK,
  GAP,
} from './Freecad.jsx'

const meta = makeCompareMeta('kicad')

const TABLE = [
  // Licensing & platform
  { group: 'Licensing & platform', feature: 'License',
    competitor: `${GOOD} GPL v3 (free, copyleft)`,
    kerf: `${GOOD} MIT open-core (permissive)` },
  { group: 'Licensing & platform', feature: 'Cost',
    competitor: `${GOOD} Free, no restrictions, no seats`,
    kerf: `${GOOD} Free local; pay-as-you-go hosted` },
  { group: 'Licensing & platform', feature: 'Platform',
    competitor: `${GOOD} Win / macOS / Linux desktop`,
    kerf: `${GOOD} Browser (hosted) + single-binary local` },
  { group: 'Licensing & platform', feature: 'Maturity',
    competitor: `${GOOD} v10 (2026), long lineage`,
    kerf: `${WEAK} Early-stage, < 2 yr public` },

  // Schematic
  { group: 'Schematic capture', feature: 'Hierarchical schematic',
    competitor: `${GOOD} Eeschema — dozens of sheets`,
    kerf: `${GOOD} Hierarchical schematic` },
  { group: 'Schematic capture', feature: 'Buses / net classes',
    competitor: `${GOOD} Buses, net classes, aggregate classes`,
    kerf: `${GOOD} Buses, net classes` },
  { group: 'Schematic capture', feature: 'ERC',
    competitor: `${GOOD} Mature ERC + exclusions w/ comments`,
    kerf: `${GOOD} ERC` },
  { group: 'Schematic capture', feature: 'SPICE simulation',
    competitor: `${GOOD} ngspice — AC/DC/transient, plotter`,
    kerf: `${GOOD} SPICE + model library` },

  // PCB layout
  { group: 'PCB layout', feature: 'Interactive routing',
    competitor: `${GOOD} Pcbnew push & shove (mature)`,
    kerf: `${GOOD} Shove router` },
  { group: 'PCB layout', feature: 'Length / skew tuning',
    competitor: `${GOOD} Overhauled tuner, time-domain constraints`,
    kerf: `${GOOD} Length tuning` },
  { group: 'PCB layout', feature: 'Differential pairs',
    competitor: `${GOOD} Diff-pair routing + tuning`,
    kerf: `${WEAK} Length tuning; diff-pair workflow lighter` },
  { group: 'PCB layout', feature: 'Via stitching / copper pour',
    competitor: `${GOOD} Stitching vias, zones/pours`,
    kerf: `${GOOD} Via stitching + copper pour` },
  { group: 'PCB layout', feature: 'Autorouter',
    competitor: `${WEAK} Freerouting (external plugin)`,
    kerf: `${GOOD} FreeRouting integrated` },
  { group: 'PCB layout', feature: 'DRC',
    competitor: `${GOOD} Graphical rule editor + custom expressions`,
    kerf: `${GOOD} DRC + IPC-2221B presets` },

  // High-speed / RF / PI
  { group: 'High-speed / RF', feature: 'RF / S-parameters',
    competitor: `${WEAK} Third-party plugins`,
    kerf: `${GOOD} scikit-rf integration` },
  { group: 'High-speed / RF', feature: 'Signal integrity / PDN',
    competitor: `${WEAK} Limited; via external tools`,
    kerf: `${GOOD} Signal integrity + PDN analysis` },
  { group: 'High-speed / RF', feature: 'Flex / stackup',
    competitor: `${GOOD} Stackup editor; rigid-flex (basic)`,
    kerf: `${GOOD} Flex stackup` },

  // Fabrication & assembly
  { group: 'Fabrication output', feature: 'Gerber / Excellon / P&P',
    competitor: `${GOOD} Full plot suite`,
    kerf: `${GOOD} Gerber / Excellon / P&P` },
  { group: 'Fabrication output', feature: 'IPC-2581',
    competitor: `${GOOD} Native export`,
    kerf: `${GOOD} IPC-2581 fab pack` },
  { group: 'Fabrication output', feature: 'ODB++',
    competitor: `${GOOD} Native export (single archive)`,
    kerf: `${GOOD} ODB++ export` },
  { group: 'Fabrication output', feature: 'Netlist export',
    competitor: `${GOOD} KiCad / OrCAD / PADS / CSV`,
    kerf: `${GOOD} IPC-D-356A + KiCad/OrcadPADS/CSV` },
  { group: 'Fabrication output', feature: 'Variants / DNP',
    competitor: `${GOOD} Design variants (v10)`,
    kerf: `${GOOD} Variants (DNP)` },
  { group: 'Fabrication output', feature: 'Panelisation',
    competitor: `${WEAK} KiKit (community plugin)`,
    kerf: `${GOOD} Panelize built in` },
  { group: 'Fabrication output', feature: 'Test point / fixture',
    competitor: `${WEAK} Manual / scripted`,
    kerf: `${GOOD} Testpoint / fixture tooling` },
  { group: 'Fabrication output', feature: 'BOM cost / DFM',
    competitor: `${WEAK} BOM export; cost via external`,
    kerf: `${GOOD} BOM cost + DFM checks` },

  // MCAD / cross-domain
  { group: 'MCAD & cross-domain', feature: 'Board STEP / IDF',
    competitor: `${GOOD} STEP export + IDF`,
    kerf: `${GOOD} IDF MCAD bridge + board STEP` },
  { group: 'MCAD & cross-domain', feature: 'Mechanical CAD (same tool)',
    competitor: `${GAP} Separate tool required`,
    kerf: `${GOOD} Full B-rep, sketcher, drawings, sheet metal` },

  // Ecosystem & SDK
  { group: 'Ecosystem & SDK', feature: 'Component libraries',
    competitor: `${GOOD} Huge official + community libs (v10: +952 sym)`,
    kerf: `${WEAK} Library mgmt + distributors; smaller catalog` },
  { group: 'Ecosystem & SDK', feature: 'Chat / LLM editing',
    competitor: `${GAP} None`,
    kerf: `${GOOD} Chat-native — edits circuit source per turn` },
  { group: 'Ecosystem & SDK', feature: 'Scripting',
    competitor: `${GOOD} Python (in-process) + IPC API`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC` },
  { group: 'Ecosystem & SDK', feature: 'Importers',
    competitor: `${GOOD} Allegro / PADS / gEDA / Eagle`,
    kerf: `${WEAK} KiCad-oriented import` },
  { group: 'Ecosystem & SDK', feature: 'Community & docs',
    competitor: `${GOOD} Very large, well-documented`,
    kerf: `${WEAK} Early-stage, growing` },
]

export default function KicadPage() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <HeadMeta meta={meta} />
      <Header />

      <main className="mx-auto max-w-4xl px-6 pt-12 pb-20">
        <Breadcrumb />

        <div className="mb-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2">
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            Kerf vs KiCad
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            KiCad is the reference open-source EDA suite. Version 10 (March
            2026) is genuinely deep: native IPC-2581 and ODB++ output, an
            overhauled track tuner with time-domain constraints, design
            variants, a graphical DRC rule editor, and a very large community.
            Kerf covers much of the same electronics ground and adds a unified
            mechanical CAD workspace and chat-driven editing — but KiCad's
            pure-PCB maturity and library breadth are hard to match today.
          </p>
        </div>

        <Section title="Where KiCad is strong">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Deep, mature EDA tooling.</strong>{' '}
              Eeschema and Pcbnew have been refined over many years with an
              enormous community validating edge cases on real boards.
            </Li>
            <Li>
              <strong className="text-ink-100">Best-in-class free DRC.</strong>{' '}
              KiCad 10 added a graphical DRC rule editor on top of its custom
              expression language — fine-grained, professional design-rule
              control that exceeds Kerf's IPC-2221B presets.
            </Li>
            <Li>
              <strong className="text-ink-100">Native IPC-2581 and ODB++.</strong>{' '}
              Both modern fabrication interchange formats export natively,
              including a single ODB++ archive — no plugins required.
            </Li>
            <Li>
              <strong className="text-ink-100">Overhauled high-speed tuning.</strong>{' '}
              Version 10's rewritten track-tuning system supports time-domain
              constraints and per-layer tuning profiles for serious high-speed
              work.
            </Li>
            <Li>
              <strong className="text-ink-100">Integrated ngspice.</strong>{' '}
              AC, DC-sweep, and transient simulation with a built-in plotter and
              mature model libraries — verify behaviour before layout.
            </Li>
            <Li>
              <strong className="text-ink-100">Vast component libraries.</strong>{' '}
              Tens of thousands of official symbols and footprints, plus a large
              community contribution stream (v10 alone added 952 symbols).
            </Li>
            <Li>
              <strong className="text-ink-100">Strong importers.</strong>{' '}
              Allegro, PADS, gEDA/Lepton, and Eagle import ease migration off
              proprietary tools.
            </Li>
            <Li>
              <strong className="text-ink-100">Completely free and offline.</strong>{' '}
              GPL v3, no seat limits, no commercial restrictions, fully offline,
              cross-platform.
            </Li>
          </ul>
        </Section>

        <Section title="Where Kerf differs">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Mechanical + electronics in one workspace.</strong>{' '}
              B-rep CAD, sketcher v2, drawings, sheet metal, and the full EDA
              stack are co-resident. ECAD/MCAD co-design happens without
              exporting IDF and switching tools.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a schematic change or routing constraint in plain
              English; the LLM edits the circuit source directly, backed by
              live doc-search.
            </Li>
            <Li>
              <strong className="text-ink-100">RF and PI built in.</strong>{' '}
              scikit-rf S-parameter analysis, signal integrity, and PDN analysis
              are first-class — workflows KiCad addresses only via external tools
              or third-party plugins.
            </Li>
            <Li>
              <strong className="text-ink-100">MIT open-core + hosted.</strong>{' '}
              The core is permissive MIT (vs KiCad's copyleft GPL), with a
              hosted browser option and a single-binary local install.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate PCB and mechanical tasks from a script on your own
              machine over HTTP/JSON-RPC — the same interface the LLM uses.
            </Li>
            <Li>
              <strong className="text-ink-100">Cost / DFM and fixtures built in.</strong>{' '}
              BOM cost, DFM checks, panelize, and test-point/fixture tooling
              ship in-box rather than as community plugins.
            </Li>
          </ul>
        </Section>

        <Section title="Honest gaps — where Kerf is behind today">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">KiCad's DRC is more powerful.</strong>{' '}
              Kerf covers IPC-2221B presets and standard rules; KiCad 10's
              custom-expression language plus graphical rule editor give expert
              teams considerably more control.
            </Li>
            <Li>
              <strong className="text-ink-100">Much smaller component library.</strong>{' '}
              KiCad's official + community libraries dwarf Kerf's catalog today.
            </Li>
            <Li>
              <strong className="text-ink-100">SPICE parity is partial.</strong>{' '}
              Kerf's SPICE + model lib is functional but does not match ngspice
              depth or KiCad's plotter polish.
            </Li>
            <Li>
              <strong className="text-ink-100">Diff-pair workflow is lighter.</strong>{' '}
              KiCad's interactive differential-pair routing and tuning are more
              refined than Kerf's today.
            </Li>
            <Li>
              <strong className="text-ink-100">Far less community documentation.</strong>{' '}
              KiCad has years of tutorials, forum answers, and videos; Kerf's
              community is early-stage.
            </Li>
            <Li>
              <strong className="text-ink-100">Fewer importers.</strong>{' '}
              KiCad 10 imports Allegro, PADS, gEDA, and Eagle directly; Kerf's
              EDA import path is narrower.
            </Li>
          </ul>
        </Section>

        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="KiCad" />
          <TableFooter />
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
