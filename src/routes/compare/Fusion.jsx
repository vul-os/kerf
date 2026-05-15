/**
 * /compare/fusion — Kerf vs Fusion 360
 *
 * Fusion 360 pioneered cloud-connected parametric CAD with integrated CAM.
 * Kerf's differentiators are its MIT open-core, chat-native workflow,
 * electronics integration, and no per-seat subscription cost.
 */
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { makeCompareMeta } from './compareMeta.js'
import { Section, Li, CompareTable, TableFooter, CTAStrip } from './Freecad.jsx'

const meta = makeCompareMeta('fusion')

const TABLE = [
  { feature: 'License / cost',              competitor: 'Proprietary; ~$680/yr subscription',   kerf: 'MIT open-core; free local or hosted' },
  { feature: 'Parametric B-rep',            competitor: '✅ Mature timeline-based modelling',   kerf: '✅ OCCT feature tree — Pad/Pocket/Revolve/Fillet/Chamfer/Draft/etc.' },
  { feature: 'Constraint sketcher',         competitor: '✅ Full parametric sketcher',           kerf: '✅ Sketcher v2 (planegcs) — all major constraints' },
  { feature: 'Sheet metal',                 competitor: '✅ Full sheet metal WB',                kerf: '✅ Flange + unfold + flat-pattern DXF export' },
  { feature: 'Assembly',                    competitor: '✅ Full joint + motion study',          kerf: '⚠️ Assembly feature in progress' },
  { feature: '3-axis CAM',                  competitor: '✅ Built-in + simulation',              kerf: '✅ 3-axis CAM + tool DB' },
  { feature: '5-axis CAM',                  competitor: '✅ (paid tier)',                        kerf: '✅ 5-axis CAM 3+2' },
  { feature: 'FEM / simulation',            competitor: '✅ Linear static + thermal (paid)',     kerf: '❌ Not yet' },
  { feature: '2D drawings',                 competitor: '✅ Full drawing + annotations',         kerf: '✅ Multi-sheet TechDraw drawings + GD&T ASME Y14.5' },
  { feature: 'PCB / electronics',           competitor: '✅ EAGLE-derived PCB (Fusion Electron)',kerf: '✅ Full EDA — schematic, routing, DRC, Gerber, SPICE' },
  { feature: 'MCAD/ECAD integration',       competitor: '✅ Native ECAD workspace bridge',      kerf: '✅ Mechanical + electronics co-resident in same workspace' },
  { feature: 'Generative design',           competitor: '✅ Cloud-based generative design',     kerf: '❌ Not yet' },
  { feature: 'Chat / LLM editing',          competitor: '❌',                                   kerf: '✅ Chat-native — model edits source per turn' },
  { feature: 'Open source',                 competitor: '❌ Proprietary',                       kerf: '✅ MIT — full codebase on GitHub' },
  { feature: 'Offline / self-hosted',       competitor: '⚠️ Limited offline mode',             kerf: '✅ Full offline via single-binary local install' },
  { feature: 'Python scripting',            competitor: '✅ Fusion API + scripts',              kerf: '✅ kerf-sdk on PyPI — HTTP/JSON-RPC' },
  { feature: 'Jewelry / specialised tools', competitor: '❌ Generic CAD only',                 kerf: '✅ Jewelry domain: ring v4, gemstones v2, settings v3/v4, chain v2' },
]

export default function FusionPage() {
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
            Kerf vs Fusion 360
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Fusion 360 pioneered the cloud-connected parametric CAD model with
            integrated CAM, simulation, and electronics. Kerf covers similar
            ground — B-rep, CAM, electronics, drawings — with an MIT open-core
            licence, chat-native workflow, and no per-seat subscription.
          </p>
        </div>

        <Section title="Where Fusion 360 shines">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Mature integrated parametric CAD + CAM.</strong>{' '}
              Fusion's timeline-based modelling and CAM workspace are polished
              and well-documented, with years of user feedback baked in.
            </Li>
            <Li>
              <strong className="text-ink-100">Full assembly and motion simulation.</strong>{' '}
              Fusion's joint and contact-set assembly tools, including motion
              studies and interference detection, are production-ready. Kerf's
              assembly is still in progress.
            </Li>
            <Li>
              <strong className="text-ink-100">FEM simulation (paid tier).</strong>{' '}
              Linear static and thermal FEM analysis are built in — a capability
              Kerf does not yet have.
            </Li>
            <Li>
              <strong className="text-ink-100">Generative design.</strong>{' '}
              Cloud-based topology optimisation that explores the design space
              automatically — unique to Fusion's platform.
            </Li>
            <Li>
              <strong className="text-ink-100">Large community and training resources.</strong>{' '}
              Millions of users, extensive official tutorials, and a large
              third-party learning ecosystem.
            </Li>
          </ul>
        </Section>

        <Section title="Where Kerf is different">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">MIT open-core, dramatically lower cost.</strong>{' '}
              Fusion costs ~$680/yr per seat (personal use is restricted).
              Kerf's full feature set is MIT-licensed — self-host for free, or
              use hosted on a pay-as-you-go basis with no seat subscription.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a feature, constraint, or routing requirement in plain
              language; the LLM edits the source backed by live doc-search.
              Fusion has no equivalent LLM integration today.
            </Li>
            <Li>
              <strong className="text-ink-100">True offline, open-source local install.</strong>{' '}
              Kerf runs as a 32 MB single binary with no Autodesk account, no
              telemetry, and no limited-offline mode. The full codebase is on
              GitHub under MIT.
            </Li>
            <Li>
              <strong className="text-ink-100">Richer electronics stack.</strong>{' '}
              Kerf's EDA covers hierarchical schematic, shove router, SPICE +
              model lib, RF via scikit-rf, DRC + IPC-2221B presets, and a full
              Gerber/IPC-2581 fab pack — beyond what Fusion Electron offers.
            </Li>
            <Li>
              <strong className="text-ink-100">Jewelry domain built in.</strong>{' '}
              Ring v4, gemstones v2 (30 cuts), settings v3/v4, chain v2, and a
              31-template library are first-class — not available in Fusion at all.
            </Li>
          </ul>
        </Section>

        <Section title="Honest gaps">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Assembly is still in progress.</strong>{' '}
              Kerf's assembly feature is under active development. Fusion's full
              joint and motion simulation workflow is significantly ahead.
            </Li>
            <Li>
              <strong className="text-ink-100">No FEM simulation yet.</strong>{' '}
              Kerf does not yet have structural or thermal FEM analysis. Fusion's
              built-in simulation covers linear static and thermal.
            </Li>
            <Li>
              <strong className="text-ink-100">No generative design.</strong>{' '}
              Cloud topology optimisation is on Kerf's long-term roadmap but not
              yet available.
            </Li>
            <Li>
              <strong className="text-ink-100">Smaller community.</strong>{' '}
              Fusion's millions of users means more tutorials, forum answers, and
              third-party content than Kerf's early-stage community.
            </Li>
          </ul>
        </Section>

        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Fusion 360" />
          <TableFooter />
        </Section>

        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
