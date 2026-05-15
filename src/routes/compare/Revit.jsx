/**
 * /compare/revit — Kerf vs Revit
 *
 * Web-grounded (last reviewed 2026-05-15). Autodesk Revit 2026 is the
 * dominant BIM platform for architecture, engineering, and construction:
 * ~US$2,910/yr single-user (~$365/mo), a deep parametric family system,
 * full MEP (HVAC / electrical / plumbing / fabrication), Revit Structure,
 * mature IFC 2x3/4 plus STEP/3DM/SKP/OBJ interop, Navisworks clash
 * coordination, BIM 360 / Autodesk Docs cloud, and pyRevit + Dynamo.
 *
 * Kerf's arch/civil capabilities are real but fundamentally lighter — IFC
 * Tier 2 import, IFC export in progress, DXF, BIM primitives, structural
 * grid + steel framing, site grading, stairs, drawings, BOM. It is not a
 * full BIM platform today, and we say so plainly.
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

const meta = makeCompareMeta('revit')

const TABLE = [
  // Licensing & platform
  { group: 'Licensing & platform', feature: 'License',
    competitor: `${WEAK} Proprietary subscription`,
    kerf: `${GOOD} MIT open-core` },
  { group: 'Licensing & platform', feature: 'Cost',
    competitor: `${WEAK} ~US$2,910/yr single-user (~$365/mo)`,
    kerf: `${GOOD} Free local; pay-as-you-go hosted` },
  { group: 'Licensing & platform', feature: 'Platform',
    competitor: `${WEAK} Windows only`,
    kerf: `${GOOD} Browser (hosted) + single-binary local` },
  { group: 'Licensing & platform', feature: 'Cloud / collaboration',
    competitor: `${GOOD} BIM 360 / Autodesk Docs, worksharing`,
    kerf: `${WEAK} Workspace + member roles (not BIM-specific)` },
  { group: 'Licensing & platform', feature: 'Maturity',
    competitor: `${GOOD} Industry-standard, decades`,
    kerf: `${WEAK} Early-stage, < 2 yr public` },

  // BIM authoring
  { group: 'BIM authoring', feature: 'Parametric family system',
    competitor: `${GOOD} Deep family editor + types`,
    kerf: `${GAP} No native family authoring` },
  { group: 'BIM authoring', feature: 'Walls / doors / windows / slabs',
    competitor: `${GOOD} Full parametric building elements`,
    kerf: `${WEAK} BIM primitives (basic walls/doors/windows/slabs)` },
  { group: 'BIM authoring', feature: 'Stairs / ramps',
    competitor: `${GOOD} Full stair/ramp families`,
    kerf: `${WEAK} Stairs (basic)` },
  { group: 'BIM authoring', feature: 'Structural grid / framing',
    competitor: `${GOOD} Revit Structure + Robot`,
    kerf: `${WEAK} Structural grid + steel framing (early)` },
  { group: 'BIM authoring', feature: 'Site / earthwork',
    competitor: `${GOOD} Toposolids, site tools`,
    kerf: `${WEAK} Site grading / earthwork (basic)` },

  // MEP & coordination
  { group: 'MEP & coordination', feature: 'HVAC / plumbing / electrical',
    competitor: `${GOOD} Full Revit MEP + fabrication`,
    kerf: `${GAP} Not yet` },
  { group: 'MEP & coordination', feature: 'Clash detection',
    competitor: `${GOOD} Navisworks federated coordination`,
    kerf: `${GAP} Not yet` },
  { group: 'MEP & coordination', feature: 'Multi-user worksharing',
    competitor: `${GOOD} Worksets + BIM 360`,
    kerf: `${WEAK} General workspace roles, not BIM worksharing` },

  // Documentation
  { group: 'Drawings & docs', feature: 'Sheets / views',
    competitor: `${GOOD} Full sheet-set management`,
    kerf: `${GOOD} Multi-sheet drawings` },
  { group: 'Drawings & docs', feature: 'Schedules / BOM',
    competitor: `${GOOD} Parameter-driven schedules`,
    kerf: `${GOOD} BOM + distributors` },
  { group: 'Drawings & docs', feature: 'GD&T / tolerancing',
    competitor: `${WEAK} Not a mechanical-tolerance tool`,
    kerf: `${GOOD} ASME Y14.5 GD&T (mechanical side)` },

  // Interoperability
  { group: 'Interoperability', feature: 'IFC import',
    competitor: `${GOOD} Mature IFC 2x3 / 4`,
    kerf: `${GOOD} IFC Tier 2 import` },
  { group: 'Interoperability', feature: 'IFC export',
    competitor: `${GOOD} Certified IFC 2x3 / 4 export`,
    kerf: `${WEAK} IFC export in progress` },
  { group: 'Interoperability', feature: 'DXF / STEP / 3DM / SKP / OBJ',
    competitor: `${GOOD} Broad import/link/export`,
    kerf: `${WEAK} DXF + STEP/IGES; narrower set` },

  // Cross-domain
  { group: 'Cross-domain', feature: 'Electronics (same tool)',
    competitor: `${GAP} Separate tool required`,
    kerf: `${GOOD} Full EDA stack in same workspace` },
  { group: 'Cross-domain', feature: 'Mechanical B-rep CAD',
    competitor: `${WEAK} Not a mechanical CAD tool`,
    kerf: `${GOOD} OCCT feature tree, sketcher, CAM` },

  // Ecosystem & SDK
  { group: 'Ecosystem & SDK', feature: 'Chat / LLM editing',
    competitor: `${GAP} None`,
    kerf: `${GOOD} Chat-native — edits source per turn` },
  { group: 'Ecosystem & SDK', feature: 'Scripting / automation',
    competitor: `${GOOD} pyRevit + Dynamo + Revit API`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC` },
  { group: 'Ecosystem & SDK', feature: 'AEC plugin ecosystem',
    competitor: `${GOOD} Vast Autodesk App Store`,
    kerf: `${WEAK} Plugin API early-stage` },
  { group: 'Ecosystem & SDK', feature: 'Community & training',
    competitor: `${GOOD} Enormous, certified training`,
    kerf: `${WEAK} Early-stage, growing` },
]

export default function RevitPage() {
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
            Kerf vs Revit
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Revit is the dominant BIM platform for architecture, engineering,
            and construction — a deep parametric family system, full MEP, Revit
            Structure, mature IFC interoperability, and Navisworks clash
            coordination, at roughly US$2,910/yr per seat. Kerf's arch/civil
            workflow (IFC Tier 2 import, BIM primitives, structural grid + steel
            framing, site grading, stairs, drawings, BOM) is real but
            fundamentally lighter. Kerf is not a full BIM platform today, and
            this page says so plainly.
          </p>
        </div>

        <Section title="Where Revit is strong">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Deep parametric BIM family system.</strong>{' '}
              Revit's family editor lets every building element carry
              parameters, types, schedules, and metadata — the foundation of
              real BIM. Kerf has no native family authoring.
            </Li>
            <Li>
              <strong className="text-ink-100">Full MEP and structural disciplines.</strong>{' '}
              HVAC, electrical, plumbing, and MEP fabrication detailing, plus
              Revit Structure with Robot analysis — entire disciplines Kerf does
              not yet address.
            </Li>
            <Li>
              <strong className="text-ink-100">Mature, certified IFC round-trip.</strong>{' '}
              Years of IFC 2x3 / 4 import and export experience with broad
              openBIM certification and continual performance work.
            </Li>
            <Li>
              <strong className="text-ink-100">Clash detection and coordination.</strong>{' '}
              Revit models feed Navisworks for federated, multi-discipline
              clash detection — a core construction-coordination workflow.
            </Li>
            <Li>
              <strong className="text-ink-100">Worksharing at scale.</strong>{' '}
              Worksets plus BIM 360 / Autodesk Docs support large teams editing
              one model concurrently.
            </Li>
            <Li>
              <strong className="text-ink-100">Vast AEC ecosystem.</strong>{' '}
              The Autodesk App Store plus pyRevit and Dynamo cover almost every
              conceivable AEC workflow extension.
            </Li>
            <Li>
              <strong className="text-ink-100">Industry-standard interoperability.</strong>{' '}
              Imports/links/exports IFC, DXF, STEP, 3DM, SKP, and OBJ — the de
              facto exchange hub for AEC project teams.
            </Li>
          </ul>
        </Section>

        <Section title="Where Kerf differs">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">MIT open-core, dramatically lower cost.</strong>{' '}
              Revit is ~US$2,910/yr per seat. Kerf is MIT-licensed with a free
              local install and pay-as-you-go cloud — no per-seat subscription.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a building element or layout change in plain language;
              the LLM edits the model source backed by live doc-search.
            </Li>
            <Li>
              <strong className="text-ink-100">Mechanical + electronics in the same workspace.</strong>{' '}
              Teams designing smart buildings or integrated electronics can
              work on PCBs and mechanical enclosures without leaving Kerf.
            </Li>
            <Li>
              <strong className="text-ink-100">Single binary, zero-ops, cross-platform.</strong>{' '}
              Installs via brew or curl on macOS/Linux/Windows — no Windows-only
              requirement, no Autodesk account, no AD dependency.
            </Li>
            <Li>
              <strong className="text-ink-100">Mechanical-grade documentation.</strong>{' '}
              ASME Y14.5 GD&T and multi-sheet drawings serve product/fabrication
              work alongside architectural output.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate drawing generation, BOM export, and model manipulation
              from Python on your own machine via HTTP/JSON-RPC.
            </Li>
          </ul>
        </Section>

        <Section title="Honest gaps — where Kerf is behind today">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">No MEP or services.</strong>{' '}
              HVAC, plumbing, and electrical systems modelling are absent. Revit
              MEP is far ahead and this is a hard requirement for most AEC work.
            </Li>
            <Li>
              <strong className="text-ink-100">No parametric family authoring.</strong>{' '}
              Revit's family editor underpins real BIM. Kerf's BIM primitives
              are fixed, not author-your-own parametric components.
            </Li>
            <Li>
              <strong className="text-ink-100">No clash detection.</strong>{' '}
              Federated multi-discipline coordination (Navisworks-style) is not
              in Kerf.
            </Li>
            <Li>
              <strong className="text-ink-100">IFC export is in progress.</strong>{' '}
              Kerf imports IFC Tier 2 but full IFC export for round-trip
              interoperability is not yet complete.
            </Li>
            <Li>
              <strong className="text-ink-100">No BIM-grade worksharing.</strong>{' '}
              Kerf has general workspace roles, not concurrent BIM model
              worksharing at AEC team scale.
            </Li>
            <Li>
              <strong className="text-ink-100">Not a BIM platform today.</strong>{' '}
              For large multi-discipline AEC firms, Revit's depth is the
              appropriate choice; Kerf handles lighter arch tasks well.
            </Li>
          </ul>
        </Section>

        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Revit" />
          <TableFooter />
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
