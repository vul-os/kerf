/**
 * /compare/3ds-max — Kerf vs Autodesk 3ds Max
 *
 * Honest, web-grounded comparison (last reviewed 2026-05-17).
 *
 * 3ds Max is a professional mesh-first DCC (Digital Content Creation) tool
 * built for architectural visualisation, game-art pipelines, VFX, and product
 * rendering. It is NOT a B-rep parametric CAD application. It has no NURBS
 * B-rep solids, no STEP B-rep round-trip, no GD&T, no parametric history in
 * the CAD sense (the Modifier Stack is linear and per-object), and no
 * engineering-calc breadth.
 *
 * The comparison is framed honestly: these are different categories of tool.
 * The overlap is real — jewelry hero rendering, archviz, and product
 * visualisation — but the primary jobs are different. Kerf wins for
 * engineering/manufacturing output; 3ds Max wins for production rendering,
 * animation, and the archviz/game-art workflow.
 */
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
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
  NA,
} from './Freecad.jsx'

/* -------------------------------------------------------------------------- */
/* Inline meta                                                                 */
/* -------------------------------------------------------------------------- */
const meta = {
  title: 'Kerf vs Autodesk 3ds Max — CAD vs DCC compared',
  description:
    '3ds Max is the industry standard for archviz and game-art rendering, not a ' +
    'B-rep CAD tool. See where Kerf and 3ds Max overlap and where each belongs ' +
    'in your pipeline.',
  canonical: 'https://kerf.sh/compare/3ds-max',
  ogImage: 'https://kerf.sh/og/compare-3ds-max.png',
  jsonLd: JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: 'Kerf vs Autodesk 3ds Max — CAD vs DCC compared',
    description:
      '3ds Max is the industry standard for archviz and game-art rendering, not a ' +
      'B-rep CAD tool. See where Kerf and 3ds Max overlap and where each belongs ' +
      'in your pipeline.',
    url: 'https://kerf.sh/compare/3ds-max',
    image: 'https://kerf.sh/og/compare-3ds-max.png',
    publisher: {
      '@type': 'Organization',
      name: 'Kerf',
      url: 'https://kerf.sh',
    },
  }),
  product: '3ds Max',
  slug: '3ds-max',
}

/* -------------------------------------------------------------------------- */
/* Feature matrix                                                              */
/* -------------------------------------------------------------------------- */
const TABLE = [
  // Licensing & platform
  {
    group: 'Licensing & platform',
    feature: 'License',
    competitor: `${WEAK} Autodesk subscription (commercial, expensive)`,
    kerf: `${GOOD} MIT open-core (permissive)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Cost',
    competitor: `${WEAK} ~$235 USD/month or ~$1,875/year`,
    kerf: `${GOOD} Free local binary; pay-as-you-go hosted`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Platform',
    competitor: `${WEAK} Windows desktop only (no macOS, no Linux)`,
    kerf: `${GOOD} Browser (hosted) + single-binary local (Win / macOS / Linux)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Hosted / cloud',
    competitor: `${GAP} Desktop only`,
    kerf: `${GOOD} Hosted SaaS + local install (brew/curl)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Maturity',
    competitor: `${GOOD} 35+ yr history; industry-standard in archviz + game art`,
    kerf: `${WEAK} Early-stage, < 2 yr public`,
  },

  // Geometry kernel
  {
    group: 'Geometry kernel',
    feature: 'Kernel type',
    competitor: `${WEAK} Mesh-first (poly / Edit Poly) — no B-rep solids`,
    kerf: `${GOOD} OCCT B-rep — exact rational geometry`,
  },
  {
    group: 'Geometry kernel',
    feature: 'Parametric history',
    competitor: `${WEAK} Linear Modifier Stack per object — not a persistent face-ID DAG`,
    kerf: `${GOOD} OCCT feature tree — pad/pocket/revolve/loft; persistent face IDs`,
  },
  {
    group: 'Geometry kernel',
    feature: 'Parametric primitives',
    competitor: `${GOOD} Rich parametric primitives (box, sphere, cylinder, spline loft, …)`,
    kerf: `${GOOD} Sketcher v2 + OCCT feature tree (pad, revolve, loft, …)`,
  },
  {
    group: 'Geometry kernel',
    feature: 'Constraint sketcher',
    competitor: `${GAP} No constraint-based 2-D sketcher`,
    kerf: `${GOOD} Sketcher v2 — geometric + dimensional constraints`,
  },
  {
    group: 'Geometry kernel',
    feature: 'Exact NURBS / B-rep solids',
    competitor: `${GAP} No NURBS B-rep solids; NURBS curves only for spline paths`,
    kerf: `${WEAK} NURBS Phase 4 — trim-by-curve, G3 combs (early)`,
  },
  {
    group: 'Geometry kernel',
    feature: 'STEP / IGES B-rep interop',
    competitor: `${WEAK} Via FBX/DWG; no native STEP B-rep round-trip; STEP plugin import only`,
    kerf: `${GOOD} STEP / IGES / 3DM B-rep import + export`,
  },

  // Rendering
  {
    group: 'Rendering',
    feature: 'Built-in renderer',
    competitor: `${GOOD} Arnold (Autodesk, GPU/CPU path tracer) built-in`,
    kerf: `${WEAK} HDRI + ACES + bloom + 2048×2048 supersampled heroShot; no path tracer`,
  },
  {
    group: 'Rendering',
    feature: 'Third-party render plugins',
    competitor: `${GOOD} V-Ray (most popular archviz), Corona, Redshift, Octane — mature ecosystem`,
    kerf: `${GAP} No third-party render plugin API yet`,
  },
  {
    group: 'Rendering',
    feature: 'Caustics / GI / dispersion',
    competitor: `${GOOD} Production caustics, GI, volumetric fog, motion blur via Arnold/V-Ray/Corona`,
    kerf: `${WEAK} Roadmap T-106 caustics/dispersion solver in progress (jewelry use case)`,
  },
  {
    group: 'Rendering',
    feature: 'PBR materials',
    competitor: `${GOOD} Physical Material + node-based Slate Material Editor; Substance integration`,
    kerf: `${WEAK} PBR material library in progress`,
  },
  {
    group: 'Rendering',
    feature: 'Archviz material libraries',
    competitor: `${GOOD} Extensive third-party libraries (Chaos Cosmos, Forest Pack, …)`,
    kerf: `${GAP} No archviz-specific material library yet`,
  },

  // Mesh modeling & animation
  {
    group: 'Mesh modeling & animation',
    feature: 'Poly / Edit Poly modeling',
    competitor: `${GOOD} Industry-standard Edit Poly — mature, feature-rich, non-destructive stack`,
    kerf: `${WEAK} Mesh tools + quad remesh; no Edit Poly equivalent`,
  },
  {
    group: 'Mesh modeling & animation',
    feature: 'Modifier Stack',
    competitor: `${GOOD} Dozens of non-destructive modifiers (TurboSmooth, Chamfer, Bevel, Bend, …)`,
    kerf: `${WEAK} Feature tree covers engineering ops; no mesh modifier stack`,
  },
  {
    group: 'Mesh modeling & animation',
    feature: 'Animation / rigging',
    competitor: `${GOOD} Full skeletal animation, IK/FK, CAT rig, Biped, morph targets, particle systems`,
    kerf: `${GAP} No animation or rigging`,
  },
  {
    group: 'Mesh modeling & animation',
    feature: 'Scripting',
    competitor: `${GOOD} MAXScript (native) + Python 3 scripting API`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC from your machine`,
  },

  // Engineering modules
  {
    group: 'Engineering modules',
    feature: 'GD&T / tolerances',
    competitor: `${GAP} No GD&T`,
    kerf: `${GOOD} ASME Y14.5 datum + tolerance framework`,
  },
  {
    group: 'Engineering modules',
    feature: '2D technical drawings',
    competitor: `${GAP} No technical drawing output`,
    kerf: `${GOOD} Multi-sheet drawings`,
  },
  {
    group: 'Engineering modules',
    feature: 'Electronics / PCB',
    competitor: `${GAP} Not applicable`,
    kerf: `${GOOD} Full EDA — schematic, routing, DRC, Gerber/IPC-2581`,
  },
  {
    group: 'Engineering modules',
    feature: 'CNC CAM',
    competitor: `${GAP} No CAM`,
    kerf: `${GOOD} 3-axis CAM + tool DB; 5-axis 3+2`,
  },
  {
    group: 'Engineering modules',
    feature: 'Chat / LLM editing',
    competitor: `${GAP} None`,
    kerf: `${GOOD} Chat-native — edits feature tree per turn`,
  },
]

/* -------------------------------------------------------------------------- */
/* Page component                                                              */
/* -------------------------------------------------------------------------- */

export default function Max3dsPage() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <HeadMeta meta={meta} />
      <Header />

      <main className="mx-auto max-w-4xl px-6 pt-12 pb-20">
        <Breadcrumb />

        {/* Hero */}
        <div className="mb-10">
          <p
            aria-label="Page category"
            className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2"
          >
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            Kerf vs Autodesk 3ds Max
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            3ds Max is the industry-standard DCC tool for architectural
            visualisation, game art, and VFX: mature poly modeling, a rich
            modifier stack, built-in Arnold rendering, and an unmatched
            plugin ecosystem (V-Ray, Corona, Forest Pack). It is not a B-rep
            parametric CAD application. If you are evaluating 3ds Max for
            product engineering, jewelry production, or electronics design
            work — or considering it alongside Kerf for a visualisation
            pipeline — this page lays out where the two tools overlap, where
            they diverge, and which belongs in your workflow.
          </p>
        </div>

        {/* Different categories callout */}
        <section
          aria-label="Category note"
          className="mb-10 rounded-xl border border-kerf-300/30 bg-kerf-300/5 px-5 py-4"
        >
          <p className="text-sm text-ink-200 leading-relaxed">
            <strong className="text-ink-100">
              These are different categories of tool.
            </strong>{' '}
            Kerf is a B-rep parametric CAD environment with multi-discipline
            scope (mechanical, electronics, jewelry, architecture). 3ds Max is
            a mesh-first DCC and production rendering platform. Comparing them
            is a bit like comparing SolidWorks to 3ds Max — there is real
            overlap in visualisation, but the primary jobs are different.
          </p>
        </section>

        {/* Where 3ds Max is strong */}
        <Section title="Where 3ds Max is strong">
          <ul
            className="flex flex-col gap-3"
            aria-label="3ds Max strengths"
          >
            <Li>
              <strong className="text-ink-100">
                Industry standard for archviz and game art.
              </strong>{' '}
              3ds Max has been the dominant platform for architectural
              visualisation and real-time game-asset pipelines for over 35
              years. The renderer ecosystem (V-Ray, Corona, Arnold) and
              associated material/vegetation libraries are unmatched in those
              verticals.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Mature poly and Edit Poly modeling.
              </strong>{' '}
              Edit Poly is a non-destructive mesh editing modifier with a deep
              history of production use. The Modifier Stack lets you layer
              operations (TurboSmooth, Chamfer, Bevel, Bend, Shell, …)
              non-destructively on any object — the closest analogue to a
              feature tree in DCC tooling, though it is per-object, linear,
              and mesh-centric rather than a B-rep feature DAG.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Arnold renderer built in.
              </strong>{' '}
              Arnold is a GPU/CPU path tracer capable of production caustics,
              global illumination, subsurface scattering, volumetrics, and
              motion blur. It ships with 3ds Max — no plugin purchase needed
              for high-quality output.
            </Li>
            <Li>
              <strong className="text-ink-100">
                V-Ray and Corona plugin ecosystem.
              </strong>{' '}
              V-Ray and Corona are the two dominant render engines for archviz.
              Both have decades of material libraries, lighting presets, and
              scatter tools built around the 3ds Max platform. Nothing in Kerf
              approaches this ecosystem depth for production interior renders.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Substance integration.
              </strong>{' '}
              3ds Max has first-class Adobe Substance integration — direct
              material channel import, live link from Substance Painter, and
              Substance procedural materials in the Slate editor. A large
              ecosystem of PBR texture libraries is therefore immediately
              accessible.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Animation, rigging, and simulation.
              </strong>{' '}
              Skeletal animation with IK/FK, the CAT and Biped rig systems,
              morph targets, particle flows, cloth, and fur/hair — a complete
              game/film character pipeline. Kerf has no plans to replicate
              any of this.
            </Li>
            <Li>
              <strong className="text-ink-100">
                MAXScript + Python scripting.
              </strong>{' '}
              MAXScript is a mature in-process scripting language with 20+
              years of community libraries. Python 3 scripting was added more
              recently. A large corpus of automation scripts exists for
              repetitive archviz and game-asset tasks.
            </Li>
            <Li>
              <strong className="text-ink-100">
                AutoCAD DWG import; FBX/STEP via plugins.
              </strong>{' '}
              Autodesk DWG is natively supported (same vendor). FBX is native.
              STEP import is available via plugins, though the geometry arrives
              as mesh, not B-rep.
            </Li>
          </ul>
        </Section>

        {/* What 3ds Max is NOT */}
        <Section title="What 3ds Max is not (for engineering use)">
          <ul
            className="flex flex-col gap-3"
            aria-label="3ds Max limitations for engineering"
          >
            <Li>
              <strong className="text-ink-100">Not a B-rep CAD kernel.</strong>{' '}
              3ds Max models are polygon meshes, not boundary-representation
              solids. There are no analytically exact planes, cylinders, or
              spline-trimmed surfaces — only triangle/quad approximations.
              This matters for manufacturing: a CNC machine or CAM system
              needs exact B-rep geometry, not a mesh.
            </Li>
            <Li>
              <strong className="text-ink-100">No NURBS B-rep solids.</strong>{' '}
              3ds Max supports NURBS curves and surfaces as spline loft
              objects, but there are no rational NURBS solids in the
              engineering sense — no trim curves maintaining manifold
              continuity, no G-continuity analysis, and no NURBS primitives
              suitable for STEP export as solids.
            </Li>
            <Li>
              <strong className="text-ink-100">No STEP B-rep round-trip.</strong>{' '}
              STEP and IGES transfer exact B-rep geometry that downstream CAM,
              FEA, and manufacturing tooling expects. 3ds Max can import STEP
              via plugin but the geometry tessellates into mesh on import. There
              is no B-rep STEP writer — you cannot produce a valid B-rep STEP
              file from 3ds Max.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Modifier Stack is not a CAD parametric history.
              </strong>{' '}
              The Modifier Stack is linear per-object and operates on mesh
              geometry. It does not maintain persistent face IDs across
              operations, so downstream features cannot reference upstream
              faces by stable name. Editing an early modifier does not
              propagate semantic changes the way a CAD feature tree does.
            </Li>
            <Li>
              <strong className="text-ink-100">No GD&T or technical drawings.</strong>{' '}
              Engineering drawings with ASME Y14.5 geometric dimensioning and
              tolerancing, datum frames, and title blocks are out of scope for
              3ds Max by design. This is a hard requirement for manufacturing
              handoff that 3ds Max cannot satisfy.
            </Li>
            <Li>
              <strong className="text-ink-100">
                No electronics, no engineering-calc breadth.
              </strong>{' '}
              There is no schematic editor, no PCB router, no BOM generator,
              no simulation pre-compliance — engineering disciplines 3ds Max
              was never designed for.
            </Li>
            <Li>
              <strong className="text-ink-100">Windows only.</strong>{' '}
              3ds Max is a Windows-only application. There is no macOS or
              Linux version. This is a platform constraint that affects teams
              working across operating systems.
            </Li>
          </ul>
        </Section>

        {/* Where Kerf differs */}
        <Section title="Where Kerf is positioned differently">
          <ul
            className="flex flex-col gap-3"
            aria-label="Kerf differentiators versus 3ds Max"
          >
            <Li>
              <strong className="text-ink-100">
                B-rep solids with exact geometry and persistent face IDs.
              </strong>{' '}
              Kerf's OCCT kernel produces exact boundary-representation solids.
              Every face, edge, and vertex carries a stable identifier that
              downstream features, drawings, CAM paths, and simulation meshes
              can reference reliably across design iterations. This is the
              fundamental guarantee that separates B-rep CAD from mesh DCC
              tools.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Parametric feature history DAG.
              </strong>{' '}
              The feature tree (pad, pocket, revolve, loft, fillet, draft) is
              a persistent directed acyclic graph. Editing an early feature
              regenerates all downstream geometry — the same model-management
              guarantee that mechanical engineers rely on. 3ds Max's Modifier
              Stack approximates this for mesh operations but does not provide
              the same semantic regeneration.
            </Li>
            <Li>
              <strong className="text-ink-100">
                STEP / IGES / 3DM B-rep interop.
              </strong>{' '}
              Manufacturing and supply-chain tooling expects B-rep geometry in
              neutral exchange formats. Kerf reads and writes STEP and IGES
              as B-rep solids. 3ds Max cannot produce B-rep STEP output.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Multi-discipline in one workspace.
              </strong>{' '}
              Electronics (schematic + PCB + DRC + Gerber), jewelry (ring v4,
              gemstones v2, settings v3/v4, chain v2), 2D technical drawings,
              GD&T, CNC CAM, and architecture (IFC) share a single
              environment. 3ds Max focuses on a different set of disciplines.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Rendering overlap is real — and the gap is closing.
              </strong>{' '}
              Kerf has PBR materials, HDRI environment lighting, ACES
              tonemapping, bloom, and a 2048×2048 supersampled hero-shot mode.
              For jewelry and product visualisation these capabilities are
              often sufficient — without opening a second application. The
              rendering gap versus Arnold/V-Ray/Corona in complex archviz
              scenes is acknowledged; roadmap T-106 caustics and dispersion
              solver is in progress to close the gap further for jewelry
              use cases.
            </Li>
            <Li>
              <strong className="text-ink-100">MIT open-core, with a hosted option.</strong>{' '}
              The core is permissively MIT-licensed. A hosted SaaS version
              runs in the browser; a single binary installs locally via brew
              or curl. 3ds Max requires an Autodesk subscription at
              approximately $235/month.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a change in plain language; the LLM edits the feature
              tree directly, backed by live doc-search. 3ds Max has MAXScript
              and Python scripting, but no conversational geometry-editing
              interface.
            </Li>
          </ul>
        </Section>

        {/* Honest gaps */}
        <Section title="Honest gaps — where 3ds Max wins">
          <ul
            className="flex flex-col gap-3"
            aria-label="Areas where 3ds Max leads"
          >
            <Li>
              <strong className="text-ink-100">
                Production renderer: Arnold, V-Ray, and Corona.
              </strong>{' '}
              Arnold is a production-grade GPU/CPU path tracer. V-Ray and
              Corona — the two dominant archviz engines — are available only
              as 3ds Max (and a handful of other DCC) plugins. Caustics, global
              illumination, volumetric fog, complex material layering, and
              motion blur in production archviz scenes are in a different
              class from Kerf's current hero-shot renderer.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Archviz workflow and material ecosystem.
              </strong>{' '}
              Decades of production-grade archviz-specific libraries: Chaos
              Cosmos, ForestPack, RailClone, Itoo Software, and thousands of
              V-Ray and Corona material packs. Kerf has no equivalent
              third-party archviz ecosystem.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Mature poly modeling (Edit Poly / Modifier Stack).
              </strong>{' '}
              Edit Poly is the benchmark for non-destructive mesh editing.
              The Modifier Stack breadth — TurboSmooth, Chamfer, Bevel,
              Bend, Shell, Cloth, Hair, Displace, and dozens more — has no
              equivalent in Kerf's feature tree.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Animation, rigging, and character pipelines.
              </strong>{' '}
              CAT rig, Biped, IK/FK, morph targets, particle flow, cloth and
              fur simulation — a complete game and film pipeline that Kerf
              has no plans to replicate.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Substance integration and texture library depth.
              </strong>{' '}
              First-class Substance Painter live link, Substance procedural
              materials in Slate, and access to the full Substance 3D Assets
              library. Kerf's PBR material library is still in progress.
            </Li>
            <Li>
              <strong className="text-ink-100">
                35 years of ecosystem: plugins, scripts, and community.
              </strong>{' '}
              A vast catalogue of production-tested plugins, MAXScript
              libraries, and tutorials. Kerf is early-stage by comparison.
            </Li>
          </ul>
        </Section>

        {/* Migration / interop */}
        <Section title="Using 3ds Max and Kerf together">
          <ul
            className="flex flex-col gap-3"
            aria-label="3ds Max and Kerf interop and pipeline notes"
          >
            <Li>
              <strong className="text-ink-100">
                When to use 3ds Max: archviz, game art, and animation.
              </strong>{' '}
              Use 3ds Max when you need production-grade architectural
              visualisation with V-Ray or Corona, game-art asset pipelines,
              character animation, or complex animated product sequences.
              The renderer and plugin ecosystem for these workflows is
              unmatched.
            </Li>
            <Li>
              <strong className="text-ink-100">
                When to use Kerf: engineering, jewelry, multi-discipline.
              </strong>{' '}
              Use Kerf when you need exact B-rep geometry, STEP/IGES export
              for manufacturing, GD&T drawings, PCB layout, CNC CAM paths,
              or a parametric history that survives design iteration. These
              requirements are outside 3ds Max's design scope.
            </Li>
            <Li>
              <strong className="text-ink-100">
                When to use both: Kerf for engineering output, 3ds Max for
                the hero render.
              </strong>{' '}
              A natural pipeline for product design and jewelry: develop
              engineering geometry in Kerf (exact STEP, drawings, BOM),
              export FBX or glTF to 3ds Max for the production archviz or
              product hero shot with V-Ray/Corona materials, and keep the
              two files in sync when the design changes. The STEP file stays
              with Kerf; the render-optimised mesh lives in 3ds Max.
            </Li>
            <Li>
              <strong className="text-ink-100">
                FBX is the practical interop bridge.
              </strong>{' '}
              FBX is native in both directions. Export from Kerf as FBX or
              glTF; import into 3ds Max as a render-ready mesh with UV maps
              intact. STEP import into 3ds Max arrives as mesh via plugin —
              round-trip B-rep is not supported on the 3ds Max side.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Rendering gap roadmap: T-106 caustics and dispersion solver.
              </strong>{' '}
              For jewelry use cases the rendering gap between Kerf heroShot
              and V-Ray/Corona is the most visible difference. Roadmap item
              T-106 — a caustics and dispersion solver aimed at gemstone and
              precious-metal renders — is in progress and will reduce the
              need for a separate render pipeline for those workflows.
            </Li>
          </ul>
        </Section>

        {/* Feature matrix */}
        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="3ds Max" />
          <TableFooter />
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
