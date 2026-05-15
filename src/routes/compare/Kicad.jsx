/**
 * /compare/kicad — Kerf vs KiCad
 *
 * KiCad is the gold-standard free EDA suite and significantly more mature
 * than Kerf on the pure PCB side. Kerf's differentiator is the unified
 * mechanical + electronics workspace and chat-native workflow.
 */
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { makeCompareMeta } from './compareMeta.js'
import { Section, Li, CompareTable, TableFooter, CTAStrip } from './Freecad.jsx'

const meta = makeCompareMeta('kicad')

const TABLE = [
  { feature: 'License',                    competitor: 'GPL v3',                               kerf: 'MIT open-core' },
  { feature: 'Schematic capture',          competitor: '✅ Eeschema — full hierarchical',      kerf: '✅ Hierarchical schematic, buses, net classes' },
  { feature: 'PCB layout',                 competitor: '✅ Pcbnew — mature, powerful',         kerf: '✅ Full PCB layout with via stitching, length tuning, pour' },
  { feature: 'DRC',                         competitor: '✅ Deep rules engine + custom rules',  kerf: '✅ DRC + IPC-2221B presets' },
  { feature: 'ERC',                         competitor: '✅ Mature ERC',                        kerf: '✅ ERC + extended depth' },
  { feature: 'Autorouter',                 competitor: '⚠️ Freerouting plugin (external)',     kerf: '✅ FreeRouting integrated' },
  { feature: 'Shove router',               competitor: '✅ Interactive push & shove',           kerf: '✅ Shove router' },
  { feature: 'SPICE simulation',           competitor: '✅ ngspice integrated',                 kerf: '✅ SPICE + model library' },
  { feature: 'RF tools',                   competitor: '⚠️ Third-party plugins',               kerf: '✅ scikit-rf integration' },
  { feature: 'Netlist export',             competitor: '✅ KiCad, OrCAD, CSV, others',         kerf: '✅ IPC-D-356A + KiCad/OrcadPADS/CSV netlist export' },
  { feature: 'Fab output',                 competitor: '✅ Gerber/Excellon/P&P/IPC-2581',      kerf: '✅ Gerber/Excellon/P&P/IPC-2581 fab pack, ODB++' },
  { feature: 'MCAD co-design',             competitor: '⚠️ STEP export + IDF bridge',         kerf: '✅ IDF MCAD bridge + board STEP + mechanical B-rep in same UI' },
  { feature: 'Chat / LLM editing',         competitor: '❌',                                   kerf: '✅ Chat-native — model edits source per turn' },
  { feature: 'Mechanical CAD (same tool)', competitor: '❌ Separate tool required',            kerf: '✅ Full B-rep, sketcher, drawings, sheet metal' },
  { feature: 'Component library mgmt',     competitor: '✅ KiCad official + community libs',   kerf: '✅ Library management + distributors + BOM' },
  { feature: 'Variants / DNP',             competitor: '✅ BOM variants',                      kerf: '✅ Variants (DNP)' },
  { feature: 'Panelisation',               competitor: '✅ KiKit (community plugin)',           kerf: '✅ Panelize built in' },
  { feature: 'Community size',             competitor: '✅ Very large, well-documented',       kerf: '⚠️ Early-stage, growing' },
]

export default function KicadPage() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />

      <main className="mx-auto max-w-4xl px-6 pt-12 pb-20">
        <Link
          to="/compare"
          className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100 transition-colors mb-8"
        >
          <ArrowLeft size={13} />
          All comparisons
        </Link>

        <div className="mb-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2">
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            Kerf vs KiCad
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            KiCad is the leading open-source EDA suite with a large, mature
            community. Kerf covers much of the same electronics ground and adds a
            unified mechanical CAD workspace and chat-driven workflow — but KiCad's
            depth on the pure PCB side is hard to match today.
          </p>
        </div>

        <Section title="Where KiCad shines">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Deep, mature EDA tooling.</strong>{' '}
              KiCad's Eeschema and Pcbnew have been refined over many years with
              an enormous community validating every edge case.
            </Li>
            <Li>
              <strong className="text-ink-100">Excellent SPICE integration.</strong>{' '}
              ngspice is built in with a polished waveform viewer. Probe
              placement and model libraries are first-class.
            </Li>
            <Li>
              <strong className="text-ink-100">Rich official and community component libraries.</strong>{' '}
              The KiCad official library covers tens of thousands of footprints and
              symbols. The community adds more weekly.
            </Li>
            <Li>
              <strong className="text-ink-100">Advanced DRC rules engine.</strong>{' '}
              Custom DRC rules via KiCad's expression language give professional
              teams fine-grained control over design rule checks.
            </Li>
            <Li>
              <strong className="text-ink-100">Completely free and desktop-first.</strong>{' '}
              No subscription, no cloud dependency, cross-platform (Windows, macOS,
              Linux).
            </Li>
          </ul>
        </Section>

        <Section title="Where Kerf is different">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Mechanical + electronics in one workspace.</strong>{' '}
              B-rep CAD, sketcher, drawings, and full EDA are co-resident.
              MCAD/ECAD co-design happens without switching tools or exporting
              IDF files.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a schematic change or routing constraint in plain English;
              the LLM edits the circuit source directly with doc-search backing.
            </Li>
            <Li>
              <strong className="text-ink-100">RF tools via scikit-rf.</strong>{' '}
              scikit-rf integration for S-parameter analysis is built in — a
              workflow KiCad handles only via third-party plugins.
            </Li>
            <Li>
              <strong className="text-ink-100">MIT open-core, hosted option.</strong>{' '}
              The entire codebase is MIT-licensed with a hosted SaaS path and a
              single-binary local install.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate PCB and mechanical tasks from a Python script on your own
              machine via the same JSON-RPC interface the LLM uses.
            </Li>
          </ul>
        </Section>

        <Section title="Honest gaps">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">KiCad's DRC is more powerful.</strong>{' '}
              Kerf's DRC covers IPC-2221B presets and standard rules, but KiCad's
              custom rules expression language gives experienced teams more control.
            </Li>
            <Li>
              <strong className="text-ink-100">Smaller component library.</strong>{' '}
              Kerf's library is growing, but KiCad's official + community libraries
              cover far more parts today.
            </Li>
            <Li>
              <strong className="text-ink-100">Less community documentation.</strong>{' '}
              KiCad has years of tutorials, forum answers, and videos. Kerf's
              community is early-stage.
            </Li>
            <Li>
              <strong className="text-ink-100">SPICE parity is partial.</strong>{' '}
              Kerf's SPICE + model lib is functional but doesn't yet match KiCad's
              waveform viewer polish or ngspice depth.
            </Li>
          </ul>
        </Section>

        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="KiCad" />
          <TableFooter />
        </Section>

        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
