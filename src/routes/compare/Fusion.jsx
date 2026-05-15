/**
 * /compare/fusion — Kerf vs Fusion 360
 *
 * Web-grounded (last reviewed 2026-05-15). Autodesk Fusion (formerly Fusion
 * 360) pioneered cloud-connected parametric CAD with integrated CAM, CAE,
 * and electronics. Commercial use is ~US$680/yr (~$85/mo); a restricted
 * free personal tier exists (must convert once non-commercial / >US$1,000
 * annual revenue); a startup programme is ~$150/3yr. Fusion Electronics is
 * the EAGLE-derived PCB workspace (standalone EAGLE end-of-life 2026-06-07),
 * with push & shove routing, base SPICE, and extension-gated signal
 * integrity / cooling. Generative design is cloud-based.
 *
 * Kerf covers similar ground — B-rep, CAM, electronics, drawings — with an
 * MIT open-core licence, chat-native workflow, jewelry domain, and no
 * per-seat subscription. Fusion's assembly/motion, FEM, generative design,
 * and community are ahead today.
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

const meta = makeCompareMeta('fusion')

const TABLE = [
  // Licensing & platform
  { group: 'Licensing & platform', feature: 'License',
    competitor: `${WEAK} Proprietary subscription`,
    kerf: `${GOOD} MIT open-core` },
  { group: 'Licensing & platform', feature: 'Cost',
    competitor: `${WEAK} ~US$680/yr (~$85/mo); startup ~$150/3yr`,
    kerf: `${GOOD} Free local; pay-as-you-go hosted` },
  { group: 'Licensing & platform', feature: 'Free tier',
    competitor: `${WEAK} Personal-use only (non-commercial, < US$1k rev)`,
    kerf: `${GOOD} Full free local install, no revenue cap` },
  { group: 'Licensing & platform', feature: 'Offline / self-host',
    competitor: `${WEAK} Limited offline; cloud-tied`,
    kerf: `${GOOD} Full offline single-binary install` },
  { group: 'Licensing & platform', feature: 'Open source',
    competitor: `${GAP} Proprietary`,
    kerf: `${GOOD} MIT — full codebase on GitHub` },
  { group: 'Licensing & platform', feature: 'Maturity',
    competitor: `${GOOD} Millions of users, mature`,
    kerf: `${WEAK} Early-stage, < 2 yr public` },

  // Modeling
  { group: 'Modeling', feature: 'Parametric B-rep',
    competitor: `${GOOD} Timeline-based modelling (mature)`,
    kerf: `${GOOD} OCCT feature tree — pad/pocket/revolve/loft/etc.` },
  { group: 'Modeling', feature: 'Constraint sketcher',
    competitor: `${GOOD} Full parametric sketcher`,
    kerf: `${GOOD} Sketcher v2 — all major constraints` },
  { group: 'Modeling', feature: 'Sheet metal',
    competitor: `${GOOD} Full sheet-metal workspace`,
    kerf: `${GOOD} Flange + unfold + flat-pattern DXF` },
  { group: 'Modeling', feature: 'Freeform / T-spline',
    competitor: `${GOOD} Sculpt (T-spline) freeform`,
    kerf: `${WEAK} NURBS Phase 4 (early); no T-spline sculpt` },

  // Assemblies
  { group: 'Assemblies', feature: 'Joints / mates',
    competitor: `${GOOD} Full joint system`,
    kerf: `${WEAK} Assembly mates (newer)` },
  { group: 'Assemblies', feature: 'Motion study',
    competitor: `${GOOD} Motion + interference detection`,
    kerf: `${GAP} Not yet` },

  // CAM / fabrication
  { group: 'CAM / fabrication', feature: '2.5/3-axis CAM',
    competitor: `${GOOD} Built-in + verified simulation`,
    kerf: `${GOOD} 3-axis CAM + tool DB` },
  { group: 'CAM / fabrication', feature: 'Multi-axis CAM',
    competitor: `${GOOD} 4/5-axis (paid extension)`,
    kerf: `${GOOD} 5-axis CAM 3+2` },
  { group: 'CAM / fabrication', feature: 'Additive / slicing',
    competitor: `${GOOD} Additive workspace`,
    kerf: `${GOOD} Slicing Tier 1` },

  // Simulation
  { group: 'Simulation', feature: 'FEM (static / thermal)',
    competitor: `${GOOD} Built-in (extension/cloud-metered)`,
    kerf: `${GAP} Not yet` },
  { group: 'Simulation', feature: 'Generative design',
    competitor: `${GOOD} Cloud topology optimisation`,
    kerf: `${GAP} Not yet` },

  // Drawings
  { group: 'Drawings & docs', feature: '2D drawings',
    competitor: `${GOOD} Full drawing + annotations`,
    kerf: `${GOOD} Multi-sheet drawings` },
  { group: 'Drawings & docs', feature: 'GD&T',
    competitor: `${GOOD} ASME / ISO GD&T`,
    kerf: `${GOOD} ASME Y14.5 GD&T framework` },

  // Electronics
  { group: 'Electronics', feature: 'Schematic + PCB',
    competitor: `${GOOD} Fusion Electronics (EAGLE-derived)`,
    kerf: `${GOOD} Hierarchical schematic + PCB layout` },
  { group: 'Electronics', feature: 'Routing',
    competitor: `${GOOD} Push & shove routing`,
    kerf: `${GOOD} Shove router + FreeRouting` },
  { group: 'Electronics', feature: 'SPICE / RF',
    competitor: `${WEAK} Base SPICE; SI via paid extension`,
    kerf: `${GOOD} SPICE + model lib + scikit-rf RF` },
  { group: 'Electronics', feature: 'Fab output',
    competitor: `${GOOD} Gerber / NC / IPC outputs`,
    kerf: `${GOOD} Gerber / Excellon / IPC-2581 / ODB++` },
  { group: 'Electronics', feature: 'MCAD/ECAD bridge',
    competitor: `${GOOD} Native ECAD↔MCAD link`,
    kerf: `${GOOD} Co-resident; IDF + board STEP` },

  // Domain breadth
  { group: 'Domain breadth', feature: 'Jewelry tooling',
    competitor: `${GAP} Generic CAD only`,
    kerf: `${GOOD} Ring v4, gemstones v2 (30 cuts), settings, chain v2` },
  { group: 'Domain breadth', feature: 'Architecture / IFC',
    competitor: `${GAP} Not an AEC tool`,
    kerf: `${WEAK} IFC Tier 2 import + structural grid` },

  // Ecosystem & SDK
  { group: 'Ecosystem & SDK', feature: 'Chat / LLM editing',
    competitor: `${GAP} None`,
    kerf: `${GOOD} Chat-native — edits source per turn` },
  { group: 'Ecosystem & SDK', feature: 'Scripting',
    competitor: `${GOOD} Fusion API (Python/C++)`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC` },
  { group: 'Ecosystem & SDK', feature: 'Community & training',
    competitor: `${GOOD} Millions of users, vast tutorials`,
    kerf: `${WEAK} Early-stage, growing` },
]

export default function FusionPage() {
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
            Kerf vs Fusion 360
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Autodesk Fusion pioneered cloud-connected parametric CAD with
            integrated CAM, CAE, and electronics, and has millions of users. It
            is a polished, mature platform at ~US$680/yr (with a restricted
            free personal tier). Kerf covers similar ground — B-rep, CAM,
            electronics, drawings — with an MIT open-core licence, chat-native
            workflow, a jewelry domain, and no per-seat subscription. Fusion's
            assembly/motion, FEM, generative design, and community are clearly
            ahead today; this is an honest look at both.
          </p>
        </div>

        <Section title="Where Fusion 360 is strong">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Mature integrated CAD + CAM.</strong>{' '}
              Timeline-based modelling and a polished CAM workspace with
              verified toolpath simulation, refined over many years of user
              feedback.
            </Li>
            <Li>
              <strong className="text-ink-100">Full assembly and motion.</strong>{' '}
              Joints, contact sets, motion studies, and interference detection
              are production-ready. Kerf's assembly mates are newer and lack
              motion study.
            </Li>
            <Li>
              <strong className="text-ink-100">Built-in FEM simulation.</strong>{' '}
              Linear static and thermal analysis (extension / cloud-metered) —
              a capability Kerf does not have at all.
            </Li>
            <Li>
              <strong className="text-ink-100">Cloud generative design.</strong>{' '}
              Automated topology exploration across the design space — a
              flagship Fusion capability with no Kerf equivalent yet.
            </Li>
            <Li>
              <strong className="text-ink-100">T-spline freeform (Sculpt).</strong>{' '}
              Organic surface modelling that Kerf's early NURBS Phase 4 does not
              match.
            </Li>
            <Li>
              <strong className="text-ink-100">Native ECAD↔MCAD link.</strong>{' '}
              Fusion Electronics ties the PCB workspace tightly to the
              mechanical model in one Autodesk platform.
            </Li>
            <Li>
              <strong className="text-ink-100">Huge community and training.</strong>{' '}
              Millions of users, extensive official tutorials, and a deep
              third-party learning ecosystem.
            </Li>
          </ul>
        </Section>

        <Section title="Where Kerf differs">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">MIT open-core, lower cost, no revenue cap.</strong>{' '}
              Fusion is ~US$680/yr and its free tier is non-commercial only
              (must convert past ~US$1,000 annual revenue). Kerf's full feature
              set is MIT — free locally with no revenue restriction.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a feature, constraint, or routing requirement in plain
              language; the LLM edits the source backed by live doc-search.
              Fusion has no comparable LLM integration.
            </Li>
            <Li>
              <strong className="text-ink-100">True offline, open codebase.</strong>{' '}
              A single binary with no Autodesk account and no limited-offline
              caveat. The full codebase is on GitHub under MIT.
            </Li>
            <Li>
              <strong className="text-ink-100">Richer in-box electronics.</strong>{' '}
              Hierarchical schematic, shove router + FreeRouting, SPICE + model
              lib, scikit-rf RF, DRC + IPC-2221B, and a Gerber/IPC-2581/ODB++
              fab pack — beyond Fusion Electronics' base feature set.
            </Li>
            <Li>
              <strong className="text-ink-100">Jewelry domain built in.</strong>{' '}
              Ring v4, gemstones v2 (30 cuts), settings v3/v4, chain v2, and a
              31-template library — not available in Fusion at all.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate over HTTP/JSON-RPC from your own machine — the same
              interface the LLM uses internally.
            </Li>
          </ul>
        </Section>

        <Section title="Honest gaps — where Kerf is behind today">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Assembly / motion is behind.</strong>{' '}
              Fusion's joint + motion-study + interference workflow is
              significantly ahead of Kerf's assembly mates.
            </Li>
            <Li>
              <strong className="text-ink-100">No FEM simulation.</strong>{' '}
              Kerf has no structural or thermal FEM. Fusion's built-in
              simulation covers linear static and thermal.
            </Li>
            <Li>
              <strong className="text-ink-100">No generative design.</strong>{' '}
              Cloud topology optimisation is roadmap, not shipped.
            </Li>
            <Li>
              <strong className="text-ink-100">No T-spline freeform.</strong>{' '}
              Fusion's Sculpt workspace has no Kerf counterpart; NURBS Phase 4
              is early.
            </Li>
            <Li>
              <strong className="text-ink-100">Smaller community.</strong>{' '}
              Fusion's millions of users mean far more tutorials, forum
              answers, and third-party content.
            </Li>
            <Li>
              <strong className="text-ink-100">Less hardened CAM verification.</strong>{' '}
              Fusion's CAM has years of in-the-field toolpath validation; Kerf's
              is younger.
            </Li>
          </ul>
        </Section>

        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Fusion 360" />
          <TableFooter />
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
