/**
 * /compare/blender — Kerf vs Blender
 *
 * Honest, web-grounded comparison (last reviewed 2026-05-17).
 *
 * Blender is a free, open-source DCC (Digital Content Creation) tool —
 * mesh-first modelling, sculpting, animation, rigging, and photoreal rendering
 * via Cycles/Eevee. It is NOT a B-rep parametric CAD application. It has no
 * NURBS solids, no STEP B-rep round-trip, no GD&T, and no engineering-calc
 * breadth. Geometry Nodes is a genuine visual node DAG but it is mesh-centric
 * and procedural in the DCC sense, not a CAD parametric feature history with
 * persistent face IDs.
 *
 * The comparison is framed honestly: these are different categories of tool
 * that overlap in organic/SubD work, PBR rendering, and mesh operations. The
 * practical path between them is glTF/USD/FBX export from Blender into Kerf,
 * not native .blend reading.
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
/* Inline meta — compareMeta.js does not have a 'blender' entry and must not  */
/* be edited per the task constraints.                                         */
/* -------------------------------------------------------------------------- */
const meta = {
  title: 'Kerf vs Blender — CAD vs DCC compared',
  description:
    'Blender is a world-class mesh/DCC tool, not a B-rep CAD. See where they ' +
    "overlap and where Kerf's parametric engineering workflow is the right fit.",
  canonical: 'https://kerf.sh/compare/blender',
  ogImage: 'https://kerf.sh/og/compare-blender.png',
  jsonLd: JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: 'Kerf vs Blender — CAD vs DCC compared',
    description:
      'Blender is a world-class mesh/DCC tool, not a B-rep CAD. See where they ' +
      "overlap and where Kerf's parametric engineering workflow is the right fit.",
    url: 'https://kerf.sh/compare/blender',
    image: 'https://kerf.sh/og/compare-blender.png',
    publisher: {
      '@type': 'Organization',
      name: 'Kerf',
      url: 'https://kerf.sh',
    },
  }),
  product: 'Blender',
  slug: 'blender',
}

/* -------------------------------------------------------------------------- */
/* Feature matrix                                                              */
/* -------------------------------------------------------------------------- */
const TABLE = [
  // Licensing & platform
  {
    group: 'Licensing & platform',
    feature: 'License',
    competitor: `${GOOD} GPL v2+ (free, copyleft)`,
    kerf: `${GOOD} MIT open-core (permissive)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Cost',
    competitor: `${GOOD} Free, no subscription`,
    kerf: `${GOOD} Free local binary; pay-as-you-go hosted`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Platform',
    competitor: `${GOOD} Win / macOS / Linux desktop`,
    kerf: `${GOOD} Browser (hosted) + single-binary local`,
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
    competitor: `${GOOD} 30+ yr history, vibrant community`,
    kerf: `${WEAK} Early-stage, < 2 yr public`,
  },

  // Geometry kernel
  {
    group: 'Geometry kernel',
    feature: 'Kernel type',
    competitor: `${WEAK} Mesh / BMesh half-edge — no B-rep solids`,
    kerf: `${GOOD} OCCT B-rep — exact rational geometry`,
  },
  {
    group: 'Geometry kernel',
    feature: 'Parametric history (feature DAG)',
    competitor: `${WEAK} Linear Modifier Stack per object — not a persistent face-ID DAG`,
    kerf: `${GOOD} OCCT feature tree — pad/pocket/revolve/loft; persistent face IDs`,
  },
  {
    group: 'Geometry kernel',
    feature: 'Constraint sketcher',
    competitor: `${GAP} No constraint-based sketcher`,
    kerf: `${GOOD} Sketcher v2 — geometric + dimensional constraints`,
  },
  {
    group: 'Geometry kernel',
    feature: 'Exact NURBS primitives',
    competitor: `${GAP} Mesh-approximated curves; no NURBS solids`,
    kerf: `${WEAK} NURBS Phase 4 — trim-by-curve, G3 combs (early)`,
  },
  {
    group: 'Geometry kernel',
    feature: 'STEP / IGES B-rep interop',
    competitor: `${GAP} No B-rep STEP round-trip; mesh glTF/FBX/OBJ export`,
    kerf: `${GOOD} STEP/IGES/3DM B-rep import + export`,
  },

  // Procedural / parametric
  {
    group: 'Procedural & parametric',
    feature: 'Visual node DAG',
    competitor: `${GOOD} Geometry Nodes — real mesh-centric procedural DAG`,
    kerf: `${WEAK} Parametric DAG engine landed; visual UI bindings still to come`,
  },
  {
    group: 'Procedural & parametric',
    feature: 'Modifier Stack',
    competitor: `${GOOD} Linear per-object modifiers (mirror, array, bevel, solidify…)`,
    kerf: `${WEAK} Feature tree covers common ops; no linear modifier stack`,
  },
  {
    group: 'Procedural & parametric',
    feature: 'Python scripting',
    competitor: `${GOOD} bpy — full in-process Python API`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC from your machine`,
  },

  // Mesh / sculpt / SubD
  {
    group: 'Mesh, sculpt & SubD',
    feature: 'Sculpting + dyntopo',
    competitor: `${GOOD} Full sculpt mode — dyntopo, multires, 30+ brushes`,
    kerf: `${WEAK} Mesh tools + quad remesh; no sculpt mode`,
  },
  {
    group: 'Mesh, sculpt & SubD',
    feature: 'SubD authoring',
    competitor: `${GOOD} Subdivision Surface modifier + creases`,
    kerf: `${WEAK} Quad remesh + surfacing; no SubD authoring`,
  },
  {
    group: 'Mesh, sculpt & SubD',
    feature: 'Mesh boolean',
    competitor: `${GOOD} Exact mesh boolean (Blender 3.x+)`,
    kerf: `${GOOD} OCCT exact B-rep boolean`,
  },

  // Rendering
  {
    group: 'Rendering',
    feature: 'Render quality / Cycles',
    competitor: `${GOOD} Cycles (path-traced) + Eevee (real-time) — benchmark quality`,
    kerf: `${WEAK} HDRI + ACES + bloom (heroShot.js); no path-traced Cycles equivalent`,
  },
  {
    group: 'Rendering',
    feature: 'PBR materials',
    competitor: `${GOOD} Node-based shader editor`,
    kerf: `${WEAK} PBR materials — library in progress`,
  },
  {
    group: 'Rendering',
    feature: 'Animation / rigging',
    competitor: `${GOOD} Full skeletal rig, NLA editor, shape keys, cloth sim`,
    kerf: `${GAP} No animation or rigging`,
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
    feature: 'Simulation pre-compliance',
    competitor: `${GAP} No CAE / FEM`,
    kerf: `${WEAK} Simulation pre-compliance (early)`,
  },
  {
    group: 'Engineering modules',
    feature: 'CNC CAM',
    competitor: `${GAP} No CAM`,
    kerf: `${GOOD} 3-axis CAM + tool DB; 5-axis 3+2`,
  },

  // Interop
  {
    group: 'Interop',
    feature: 'glTF / FBX / OBJ import',
    competitor: `${GOOD} Native export to glTF, FBX, OBJ, USD`,
    kerf: `${WEAK} glTF/OBJ import; FBX via conversion`,
  },
  {
    group: 'Interop',
    feature: '.blend native read',
    competitor: `${NA} Source format`,
    kerf: `${GAP} Low-priority; glTF/USD covers 90%+ of use cases`,
  },
  {
    group: 'Interop',
    feature: 'Chat / LLM editing',
    competitor: `${GAP} None`,
    kerf: `${GOOD} Chat-native — edits feature tree per turn`,
  },
]

/* -------------------------------------------------------------------------- */
/* Page component                                                              */
/* -------------------------------------------------------------------------- */

export default function BlenderPage() {
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
            Kerf vs Blender
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Blender is a world-class, GPL-licensed DCC tool: mesh-first modelling,
            sculpting, animation, rigging, Geometry Nodes, and benchmark-quality
            rendering via Cycles and Eevee. It is not a B-rep parametric CAD
            application. If you are evaluating Blender for product engineering,
            jewelry production, or electronics design work, this page lays out
            where the two tools overlap, where they diverge, and which is the
            right fit — or whether both belong in your pipeline.
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
            scope (mechanical, electronics, jewelry, architecture). Blender is
            a mesh-first DCC and animation platform. Comparing them is a bit
            like comparing Illustrator to AutoCAD — there is real overlap, but
            the primary jobs are different.
          </p>
        </section>

        {/* Where Blender is strong */}
        <Section title="Where Blender is strong">
          <ul className="flex flex-col gap-3" aria-label="Blender strengths">
            <Li>
              <strong className="text-ink-100">
                Free and open-source under GPL.
              </strong>{' '}
              Blender is fully free — no subscription, no per-seat cost, no
              cloud account. The GPL licence means the source code is publicly
              auditable and community-improvable.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Mesh-first modelling with BMesh.
              </strong>{' '}
              Blender's BMesh half-edge data structure gives fast, flexible mesh
              editing with N-gon support. For concept sculpting and organic forms
              it is the benchmark tool.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Geometry Nodes — a real visual node DAG.
              </strong>{' '}
              Geometry Nodes is a genuine procedural, mesh-centric node graph:
              instance scattering, field-driven deformation, simulation nodes.
              It is not CAD parametric history (no persistent face IDs, no
              constraint solver), but it is a powerful generative toolset with
              no equivalent in Kerf yet.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Sculpting, dyntopo, and multires.
              </strong>{' '}
              A full sculpt mode with dynamic topology, multi-resolution
              sculpting, and 30+ brushes. Organic character and concept work
              runs here; Kerf has no sculpt mode.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Cycles and Eevee render quality.
              </strong>{' '}
              Cycles is a physically-based path tracer with GPU support that
              sets the open-source benchmark for photoreal output. Eevee
              delivers real-time PBR preview. Kerf's heroShot renderer (HDRI +
              ACES + bloom) does not match Cycles quality.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Animation and rigging.
              </strong>{' '}
              Full skeletal animation, NLA editor, shape keys, cloth and fluid
              simulations, and camera animation — capabilities Kerf has no
              plans to replicate.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Vibrant artist community.
              </strong>{' '}
              Blender has millions of users, Blender Market, BlenderArtists, and
              an enormous library of tutorials, add-ons, and asset packs.
            </Li>
            <Li>
              <strong className="text-ink-100">Cross-platform desktop.</strong>{' '}
              Windows, macOS, and Linux — fully offline, no internet required.
            </Li>
          </ul>
        </Section>

        {/* What Blender is NOT */}
        <Section title="What Blender is not (for engineering use)">
          <ul
            className="flex flex-col gap-3"
            aria-label="Blender limitations for engineering"
          >
            <Li>
              <strong className="text-ink-100">Not a B-rep CAD kernel.</strong>{' '}
              Blender models are polygon meshes, not boundary-representation
              solids. There are no analytically exact planes, cylinders, or
              spline-trimmed surfaces — only triangle/quad approximations.
            </Li>
            <Li>
              <strong className="text-ink-100">No NURBS solids.</strong>{' '}
              Blender has NURBS curve objects but no NURBS surfacing in the
              engineering sense (no trim curves, no G-continuity analysis, no
              rational NURBS primitives for solids).
            </Li>
            <Li>
              <strong className="text-ink-100">No STEP B-rep round-trip.</strong>{' '}
              STEP and IGES transfer B-rep geometry that machines and CAM systems
              expect. Blender exports mesh formats (glTF, FBX, OBJ); there is no
              B-rep STEP writer.
            </Li>
            <Li>
              <strong className="text-ink-100">No GD&T or technical drawings.</strong>{' '}
              Engineering drawings with ASME Y14.5 geometric dimensioning and
              tolerancing, datum frames, and title blocks are out of scope for
              Blender by design.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Modifier Stack ≠ parametric feature history.
              </strong>{' '}
              Blender's Modifier Stack is linear per-object and destructive once
              applied. It does not maintain persistent face IDs, so downstream
              features cannot reference upstream faces by stable name the way a
              CAD feature tree does.
            </Li>
            <Li>
              <strong className="text-ink-100">No electronics, no engineering-calc breadth.</strong>{' '}
              There is no schematic editor, no PCB router, no BOM, no simulation
              pre-compliance — these are engineering disciplines Blender was
              never designed for.
            </Li>
          </ul>
        </Section>

        {/* Where Kerf differs */}
        <Section title="Where Kerf is positioned differently">
          <ul className="flex flex-col gap-3" aria-label="Kerf differentiators">
            <Li>
              <strong className="text-ink-100">
                B-rep solids with valid topology and tolerances.
              </strong>{' '}
              Kerf's OCCT kernel produces exact boundary-representation solids
              whose faces, edges, and vertices carry stable IDs that downstream
              features, drawings, and CAM paths can reference reliably.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Parametric feature history DAG.
              </strong>{' '}
              The feature tree (pad, pocket, revolve, loft, fillet, draft) is a
              persistent directed acyclic graph. Editing an early feature
              regenerates all downstream geometry — the same model-management
              guarantee CAD users rely on.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Multi-discipline in one workspace.
              </strong>{' '}
              Electronics (schematic + PCB + DRC + Gerber), jewelry (ring v4,
              gemstones v2, settings v3/v4, chain v2), 2D drawings, GD&T, CNC
              CAM, and architecture (IFC) share one environment. Blender focuses
              on a different set of problems.
            </Li>
            <Li>
              <strong className="text-ink-100">
                STEP / IGES / 3DM B-rep interop.
              </strong>{' '}
              Manufacturing and supply-chain tooling expects B-rep geometry in
              neutral exchange formats. Kerf reads and writes STEP and IGES;
              Blender cannot.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Overlap exists — and is intentional.
              </strong>{' '}
              Kerf has <code className="text-kerf-200 font-mono text-xs">subd.py</code>,{' '}
              <code className="text-kerf-200 font-mono text-xs">mesh_to_nurbs.py</code>,
              mesh booleans, PBR materials, and the heroShot renderer with HDRI
              + ACES + bloom. These cover the organic/jewelry use cases where
              Blender-style tools are useful — without requiring a second
              application for the rest of the workflow.
            </Li>
            <Li>
              <strong className="text-ink-100">MIT open-core, with a hosted option.</strong>{' '}
              The core is permissively MIT-licensed (Blender is copyleft GPL).
              A hosted SaaS version runs in the browser; a single binary installs
              locally via brew or curl.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a change in plain language; the LLM edits the feature
              tree / JSCAD source directly, backed by live doc-search.
            </Li>
          </ul>
        </Section>

        {/* Honest gaps */}
        <Section title="Honest gaps — where Blender wins">
          <ul className="flex flex-col gap-3" aria-label="Areas where Blender leads">
            <Li>
              <strong className="text-ink-100">
                Render quality: Cycles path-tracer.
              </strong>{' '}
              Physically-based path tracing with GPU acceleration, volumetrics,
              caustics, and subsurface scattering. Kerf's heroShot renderer is
              not in the same class for photoreal output.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Sculpting and organic form development.
              </strong>{' '}
              Dyntopo, multires, retopology, and a full brush library. Kerf has
              no sculpt mode and is not building one.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Animation, rigging, and simulation.
              </strong>{' '}
              Skeletal animation, NLA, cloth, fluid, particles — a complete
              film/game pipeline. Kerf has no plans here.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Geometry Nodes visual DAG.
              </strong>{' '}
              A mature, shipped visual node environment for mesh-centric
              procedural work. Kerf's parametric DAG engine has landed; the
              visual node UI bindings are still to come.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Community and ecosystem depth.
              </strong>{' '}
              Millions of users, thousands of add-ons, an enormous asset
              marketplace, and 30 years of accumulated tutorials. Kerf is
              early-stage by comparison.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Mesh modelling depth (Modifier Stack).
              </strong>{' '}
              Mirror, array, bevel, solidify, shrinkwrap, Boolean, subdivision,
              weld, and dozens more non-destructive modifiers. Kerf's feature
              tree covers engineering operations but not this breadth of
              mesh-level modifiers.
            </Li>
          </ul>
        </Section>

        {/* Interop / migration */}
        <Section title="Using Blender and Kerf together">
          <ul
            className="flex flex-col gap-3"
            aria-label="Blender and Kerf interop notes"
          >
            <Li>
              <strong className="text-ink-100">
                glTF / USD / FBX is the realistic interop path.
              </strong>{' '}
              Export your Blender asset as glTF 2.0 or USD; Kerf imports these
              as mesh geometry that can be referenced in assemblies or used as a
              base for B-rep operations. This covers 90%+ of hand-off use cases.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Native .blend reading is low-priority.
              </strong>{' '}
              The .blend format is undocumented at the block level and changes
              between Blender versions. glTF/USD export from Blender is the
              recommended path rather than native .blend parsing in Kerf.
            </Li>
            <Li>
              <strong className="text-ink-100">
                When to use Blender: organic concept and hero shots.
              </strong>{' '}
              Use Blender for character/organic concept work, film-quality
              product renders, and animation sequences. Export glTF or FBX into
              Kerf when you need engineering output.
            </Li>
            <Li>
              <strong className="text-ink-100">
                When to use Kerf: engineering, jewelry production, multi-discipline.
              </strong>{' '}
              Use Kerf when you need exact B-rep geometry, STEP export for
              manufacturing, GD&T drawings, PCB layout, or a parametric history
              that survives design iteration.
            </Li>
            <Li>
              <strong className="text-ink-100">
                When to use both: Blender for the shot, Kerf for the engineering.
              </strong>{' '}
              A common pipeline is to develop engineering geometry in Kerf
              (exact STEP, drawings, BOM), export glTF to Blender for the
              photoreal product hero shot or marketing animation, and keep the
              two files in sync when the design changes.
            </Li>
          </ul>
        </Section>

        {/* Feature matrix */}
        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Blender" />
          <TableFooter />
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
