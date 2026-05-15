/**
 * /compare/revit — Kerf vs Revit
 *
 * Revit is Autodesk's dominant BIM platform for architecture, engineering,
 * and construction. It has a deep, mature feature set built for large AEC
 * teams. Kerf's arch/civil capabilities are real but fundamentally lighter —
 * IFC Tier 2, DXF, drawings, BOM, stairs, structural sketcher.
 */
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { makeCompareMeta } from './compareMeta.js'
import { Section, Li, CompareTable, TableFooter, CTAStrip } from './Freecad.jsx'

const meta = makeCompareMeta('revit')

const TABLE = [
  { feature: 'License / cost',           competitor: 'Proprietary; ~$2,850/yr subscription',  kerf: 'MIT open-core; free local or hosted' },
  { feature: 'BIM object model',         competitor: '✅ Deep parametric family system',       kerf: '⚠️ IFC-based; no native family authoring yet' },
  { feature: 'IFC import',               competitor: '✅ Mature IFC import/export',             kerf: '✅ IFC Tier 2 import' },
  { feature: 'IFC export',               competitor: '✅ IFC 2×3 / 4',                         kerf: '⚠️ IFC export in progress' },
  { feature: 'DXF read/write',           competitor: '✅',                                     kerf: '✅ DXF read/write' },
  { feature: '2D drawings / sheets',     competitor: '✅ Full sheet set management',            kerf: '✅ Multi-sheet TechDraw drawings' },
  { feature: 'BOM / schedules',          competitor: '✅ Parameter-driven schedules',           kerf: '✅ BOM + distributors' },
  { feature: 'Stairs / ramps',           competitor: '✅ Full stair families',                  kerf: '✅ Stairs built in' },
  { feature: 'Structural analysis',      competitor: '✅ Via Revit Structure + Robot',          kerf: '✅ Structural sketcher (early)' },
  { feature: 'MEP / services',           competitor: '✅ Revit MEP workset',                    kerf: '❌ Not yet' },
  { feature: 'Coordination / clash',     competitor: '✅ Navisworks integration',               kerf: '❌ Not yet' },
  { feature: 'Multi-user worksharing',   competitor: '✅ Worksharing + BIM360',                 kerf: '✅ Workspace + member roles (general, not BIM-specific)' },
  { feature: 'Chat / LLM editing',       competitor: '❌',                                     kerf: '✅ Chat-native — model edits source per turn' },
  { feature: 'Electronics (same tool)',  competitor: '❌ Separate tool required',              kerf: '✅ Full EDA stack in same workspace' },
  { feature: 'Python scripting',         competitor: '✅ pyRevit + Dynamo',                    kerf: '✅ kerf-sdk on PyPI — HTTP/JSON-RPC' },
  { feature: 'Hosted / cloud option',    competitor: '✅ BIM 360 / Autodesk Docs',             kerf: '✅ Hosted SaaS + single-binary local install' },
  { feature: 'Pricing model',            competitor: '❌ Expensive subscription',              kerf: '✅ Free local; pay-as-you-go cloud' },
]

export default function RevitPage() {
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
            Kerf vs Revit
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Revit is the dominant BIM platform for architecture and construction,
            with a deep parametric family system built for large AEC teams. Kerf's
            arch workflow covers IFC Tier 2 import, DXF, drawings, BOM, stairs,
            and structural sketching — but is fundamentally lighter than Revit's
            full BIM stack.
          </p>
        </div>

        <Section title="Where Revit shines">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Deep parametric BIM family system.</strong>{' '}
              Revit's family authoring allows every building element to carry
              parameters, schedules, and metadata — the foundation of real
              BIM workflows.
            </Li>
            <Li>
              <strong className="text-ink-100">MEP and structural worksets.</strong>{' '}
              Revit MEP covers HVAC, plumbing, and electrical. Revit Structure
              integrates with Robot Structural Analysis. These are full
              disciplines Kerf does not yet address.
            </Li>
            <Li>
              <strong className="text-ink-100">Mature IFC round-trip.</strong>{' '}
              Revit has years of IFC 2×3 and IFC 4 import/export experience and
              is widely certified for BIM interoperability.
            </Li>
            <Li>
              <strong className="text-ink-100">Clash detection and coordination.</strong>{' '}
              Via Navisworks, Revit models feed directly into federated
              multi-discipline coordination workflows.
            </Li>
            <Li>
              <strong className="text-ink-100">Extensive AEC plugin ecosystem.</strong>{' '}
              Autodesk App Store and pyRevit + Dynamo cover almost every
              AEC workflow extension imaginable.
            </Li>
          </ul>
        </Section>

        <Section title="Where Kerf is different">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">MIT open-core, dramatically lower cost.</strong>{' '}
              Revit costs ~$2,850/year per seat. Kerf is MIT-licensed with a free
              local install and pay-as-you-go cloud — no per-seat subscription.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a building element or layout change in plain language; the
              LLM edits the model source backed by live doc-search.
            </Li>
            <Li>
              <strong className="text-ink-100">Mechanical + electronics in the same workspace.</strong>{' '}
              Architects designing smart buildings or integrated electronics don't
              need to leave Kerf to work on PCBs or mechanical enclosures.
            </Li>
            <Li>
              <strong className="text-ink-100">Single binary, zero-ops local install.</strong>{' '}
              32 MB binary via brew or curl. No Windows-only installer, no Active
              Directory dependency, no Autodesk account required.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate drawing generation, BOM export, and model manipulation
              from Python on your own machine via HTTP/JSON-RPC.
            </Li>
          </ul>
        </Section>

        <Section title="Honest gaps">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">No MEP / services support.</strong>{' '}
              HVAC, plumbing, and electrical systems modelling are not in Kerf.
              Revit MEP is far ahead here.
            </Li>
            <Li>
              <strong className="text-ink-100">No parametric family authoring.</strong>{' '}
              Revit's family editor allows teams to build parametric building
              components with schedules and parameters. Kerf has no equivalent yet.
            </Li>
            <Li>
              <strong className="text-ink-100">No clash detection.</strong>{' '}
              Multi-discipline coordination via federated models (Navisworks-style)
              is not yet in Kerf.
            </Li>
            <Li>
              <strong className="text-ink-100">IFC export is in progress.</strong>{' '}
              Kerf supports IFC Tier 2 import but IFC export for interoperability
              is not yet complete.
            </Li>
            <Li>
              <strong className="text-ink-100">Not a BIM platform today.</strong>{' '}
              Kerf's architecture support handles many AEC tasks well but does
              not claim BIM-level depth. For large multi-discipline AEC firms,
              Revit's toolset is more appropriate today.
            </Li>
          </ul>
        </Section>

        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Revit" />
          <TableFooter />
        </Section>

        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
