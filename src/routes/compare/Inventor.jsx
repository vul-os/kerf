/**
 * /compare/inventor — Kerf vs Autodesk Inventor
 *
 * Honest, web-grounded comparison (last reviewed 2026-05-17).
 *
 * Autodesk Inventor is a top-tier parametric mechanical CAD platform with
 * ~30 years of vendor maturity. Inventor Professional subscription ~US$2,545/yr
 * (single-user); available via Autodesk AEC/Product Design & Manufacturing
 * Collection at higher bundled prices. Windows-only native desktop application.
 * Comprehensive part/assembly/drawing workflow, Frame Generator, Tube & Pipe,
 * Cable & Harness, Inventor Studio (visualisation), Stress Analysis (FEA),
 * Dynamic Simulation (multi-body dynamics with a full joint catalog), Sheet
 * Metal, Mold Design, large-assembly management, iLogic rules engine, and
 * Vault PDM integration.
 *
 * Autodesk positions Inventor as the professional manufacturing/MFG tool and
 * Fusion 360 as the cloud-native / SMB product; Inventor retains the dominant
 * position for large industrial customers (aerospace, automotive, industrial
 * equipment) who live inside the Autodesk ecosystem.
 *
 * Kerf is NOT a production mechanical CAD replacement at Inventor's depth or
 * maturity — that is an honest statement. Kerf's differentiators are MIT
 * open-core licensing, chat-driven UX, cross-discipline scope (electronic +
 * jewelry + mech), parametric history DAG with persistent face IDs, 620
 * analytic-oracle kernel tests, in-box process-sim (weld/forming/AM/moldflow/
 * CAM), and a browser + local-binary deployment model.
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
} from './Freecad.jsx'

/* -------------------------------------------------------------------------
 * Inline meta — Inventor does not yet have a compareMeta.js entry; we keep
 * the full meta inline so the page self-contains without touching that file.
 * ---------------------------------------------------------------------- */
const BASE = 'https://kerf.sh'
const meta = {
  title: 'Kerf vs Autodesk Inventor — mechanical CAD compared',
  description:
    'Autodesk Inventor is a top-tier professional mechanical CAD platform. ' +
    "See how Kerf's MIT open-core, chat-driven, multi-discipline workspace " +
    'compares — honestly.',
  canonical: `${BASE}/compare/inventor`,
  ogImage: `${BASE}/og/compare-inventor.png`,
  jsonLd: JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: 'Kerf vs Autodesk Inventor — mechanical CAD compared',
    description:
      'Autodesk Inventor is a top-tier professional mechanical CAD platform. ' +
      "See how Kerf's MIT open-core, chat-driven, multi-discipline workspace " +
      'compares — honestly.',
    url: `${BASE}/compare/inventor`,
    image: `${BASE}/og/compare-inventor.png`,
    publisher: { '@type': 'Organization', name: 'Kerf', url: BASE },
  }),
  product: 'Autodesk Inventor',
  slug: 'inventor',
}

/* -------------------------------------------------------------------------
 * Feature-matrix rows
 * ---------------------------------------------------------------------- */
const TABLE = [
  // Licensing & platform
  {
    group: 'Licensing & platform',
    feature: 'License',
    competitor: `${WEAK} Proprietary subscription (Autodesk)`,
    kerf: `${GOOD} MIT open-core (permissive)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Cost',
    competitor: `${WEAK} ~US$2,545/yr single-user; or via AEC/PD&M Collection`,
    kerf: `${GOOD} Free local install; pay-as-you-go hosted credits at cost`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Platform',
    competitor: `${WEAK} Windows only (native desktop)`,
    kerf: `${GOOD} Browser (hosted) + single-binary local (Win / macOS / Linux)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Offline / self-host',
    competitor: `${GOOD} Full offline (subscription or network licence)`,
    kerf: `${GOOD} Full offline single-binary (brew / curl install)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Open source',
    competitor: `${GAP} Proprietary`,
    kerf: `${GOOD} MIT — full codebase on GitHub`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Maturity',
    competitor: `${GOOD} ~30 yr; large installed base in MFG / industrial`,
    kerf: `${WEAK} Early-stage, < 2 yr public`,
  },

  // Modeling
  {
    group: 'Modeling',
    feature: 'Parametric B-rep',
    competitor: `${GOOD} Feature-tree B-rep (ShapeManager kernel); MFG-grade`,
    kerf: `${GOOD} OCCT feature tree — pad/pocket/revolve/loft/boss-with-draft`,
  },
  {
    group: 'Modeling',
    feature: 'History DAG / persistent naming',
    competitor: `${GOOD} Full feature history with rollback and adaptive features`,
    kerf: `${GOOD} Feature DAG + persistent face naming (Phase 4)`,
  },
  {
    group: 'Modeling',
    feature: 'Constraint sketcher',
    competitor: `${GOOD} Full parametric sketcher (2D + 3D sketch)`,
    kerf: `${GOOD} Sketcher v2 — all major constraints`,
  },
  {
    group: 'Modeling',
    feature: 'Direct modeling',
    competitor: `${GOOD} AnyCAD direct-import editing + feature-based history`,
    kerf: `${WEAK} Feature-tree primary; limited direct editing`,
  },
  {
    group: 'Modeling',
    feature: 'Sheet metal',
    competitor: `${GOOD} Full sheet-metal workspace — flanges, punch/die, flat pattern, DXF`,
    kerf: `${GOOD} Flange + unfold + flat-pattern DXF`,
  },
  {
    group: 'Modeling',
    feature: 'Mold design',
    competitor: `${GOOD} Mold Design module — cavity, core, parting surface`,
    kerf: `${WEAK} Moldflow process sim (moldflow_sim); no full mold workspace`,
  },
  {
    group: 'Modeling',
    feature: 'NURBS surfacing',
    competitor: `${GOOD} Surface modeling with lofted / swept NURBS`,
    kerf: `${WEAK} NURBS Phase 4 (early); trim-by-curve, C2 continuity`,
  },

  // Assemblies
  {
    group: 'Assemblies',
    feature: 'Mates / joints',
    competitor: `${GOOD} Full constraint system — flush/coincident/angle/tangent/insert`,
    kerf: `${WEAK} Assembly mates (newer, fewer mate types per T-108)`,
  },
  {
    group: 'Assemblies',
    feature: 'Dynamic Simulation (joints)',
    competitor: `${GOOD} Multi-body dynamics: rigid/revolute/slider/cylindrical/spherical/planar joints`,
    kerf: `${GAP} Not yet; mech assembly mates only`,
  },
  {
    group: 'Assemblies',
    feature: 'Frame Generator',
    competitor: `${GOOD} Purpose-built structural frame design (profiles, weldments, beam analysis)`,
    kerf: `${WEAK} Structural grid + weld simulation; no frame-generator workspace`,
  },
  {
    group: 'Assemblies',
    feature: 'Large assembly management',
    competitor: `${GOOD} Level-of-detail reps, substitute reps, demand-loading`,
    kerf: `${WEAK} No dedicated large-assembly tooling today`,
  },
  {
    group: 'Assemblies',
    feature: 'Tube & Pipe',
    competitor: `${GOOD} Routed Tube & Pipe with standard fittings + isometric drawings`,
    kerf: `${GAP} Not yet`,
  },
  {
    group: 'Assemblies',
    feature: 'Cable & Harness',
    competitor: `${GOOD} Cable & Harness workspace — wire routing, nailboard drawings`,
    kerf: `${GAP} Not yet`,
  },

  // Speciality
  {
    group: 'Specialty tooling',
    feature: 'iLogic rules engine',
    competitor: `${GOOD} iLogic — VBA/Visual Basic rules that drive parameters + features`,
    kerf: `${GOOD} Chat-driven scripting + kerf-sdk Python; no iLogic equivalent`,
  },
  {
    group: 'Specialty tooling',
    feature: 'Inventor Studio (rendering)',
    competitor: `${GOOD} Ray-trace rendering + animation inside Inventor`,
    kerf: `${WEAK} PBR viewport; no dedicated ray-trace studio`,
  },
  {
    group: 'Specialty tooling',
    feature: 'Vault PDM',
    competitor: `${GOOD} Vault integration — lifecycle, check-in/out, BOM`,
    kerf: `${GOOD} file_revisions (fine-grained undo) + cloud git (GitHub sync)`,
  },

  // Simulation
  {
    group: 'Simulation — mechanical',
    feature: 'Stress Analysis (FEA)',
    competitor: `${GOOD} In-box Stress Analysis (linear static FEA) on parts + assemblies`,
    kerf: `${GAP} Not yet; roadmap`,
  },
  {
    group: 'Simulation — mechanical',
    feature: 'Dynamic Simulation (multi-body)',
    competitor: `${GOOD} Full joint catalog, redundant constraints detection, motion loads`,
    kerf: `${GAP} Not yet`,
  },
  {
    group: 'Simulation — mechanical',
    feature: 'Process simulation (weld/forming/AM)',
    competitor: `${WEAK} Via Autodesk Nastran / Netfabb (separate products)`,
    kerf: `${GOOD} Weld sim + forming sim + AM/SLA process sim + moldflow — in-box`,
  },

  // CAM / fabrication
  {
    group: 'CAM / fabrication',
    feature: '2.5 / 3-axis CAM',
    competitor: `${WEAK} Requires HSMWorks or Fusion/CAM add-in (extra cost or separate)`,
    kerf: `${GOOD} 3-axis CAM + tool DB (in-box)`,
  },
  {
    group: 'CAM / fabrication',
    feature: 'Multi-axis CAM',
    competitor: `${WEAK} HSMWorks 4/5-axis (add-in, extra cost)`,
    kerf: `${GOOD} 5-axis CAM 3+2 (in-box)`,
  },
  {
    group: 'CAM / fabrication',
    feature: 'Additive / slicing',
    competitor: `${WEAK} Via Netfabb (separate Autodesk product)`,
    kerf: `${GOOD} Slicing Tier 1 (in-box)`,
  },

  // Drawings & docs
  {
    group: 'Drawings & docs',
    feature: '2D drawings',
    competitor: `${GOOD} Full drawing environment with ANSI/ISO templates`,
    kerf: `${GOOD} Multi-sheet drawings`,
  },
  {
    group: 'Drawings & docs',
    feature: 'GD&T',
    competitor: `${GOOD} ASME Y14.5 / ISO 1101 GD&T annotations`,
    kerf: `${GOOD} ASME Y14.5 datum + tolerance framework`,
  },
  {
    group: 'Drawings & docs',
    feature: 'BOM management',
    competitor: `${GOOD} Structured BOM with iParts / iAssemblies`,
    kerf: `${GOOD} BOM + distributors (kerf-parts in-box)`,
  },

  // Electronics
  {
    group: 'Electronics',
    feature: 'ECAD integration',
    competitor: `${WEAK} AnyCAD or Fusion Electronics bridge (not in Inventor itself)`,
    kerf: `${GOOD} Full hierarchical schematic + PCB layout in-box`,
  },
  {
    group: 'Electronics',
    feature: 'MCAD/ECAD co-design',
    competitor: `${WEAK} STEP or IDF round-trip; no co-resident workspace`,
    kerf: `${GOOD} Co-resident ECAD/MCAD; IDF + board STEP export`,
  },
  {
    group: 'Electronics',
    feature: 'SI / EMC / PDN / thermal (PCB)',
    competitor: `${GAP} External tools required`,
    kerf: `${GOOD} si_eye_wizard + emc_wizard + pdn_wizard + thermal_board — in-box`,
  },

  // Domain breadth
  {
    group: 'Domain breadth',
    feature: 'Jewelry tooling',
    competitor: `${GAP} Generic CAD only — no jewelry modules`,
    kerf: `${GOOD} 40-module jewelry suite: ring v4, gemstones v2, settings v3/v4, chain v2`,
  },
  {
    group: 'Domain breadth',
    feature: 'Architecture / IFC',
    competitor: `${GAP} Not an AEC tool (Revit is the Autodesk AEC product)`,
    kerf: `${WEAK} IFC Tier 2 import + structural grid`,
  },

  // Kernel quality
  {
    group: 'Kernel quality',
    feature: 'Kernel',
    competitor: `${GOOD} ShapeManager (Autodesk's Parasolid-derived kernel); mature`,
    kerf: `${GOOD} OpenCASCADE (OCCT) — widely used open-source B-rep kernel`,
  },
  {
    group: 'Kernel quality',
    feature: 'Test coverage',
    competitor: `${GOOD} Decades of field validation across millions of manufacturing files`,
    kerf: `${GOOD} 620 analytic-oracle kernel tests (exact closed-form references)`,
  },

  // Collaboration
  {
    group: 'Collaboration',
    feature: 'Multi-user cloud edit',
    competitor: `${WEAK} Fusion Team (Autodesk Docs) cloud — separate subscription`,
    kerf: `${GOOD} Cloud hosted multi-user + cloud-git project sync`,
  },
  {
    group: 'Collaboration',
    feature: 'Version control',
    competitor: `${GOOD} Vault PDM (check-in/out, lifecycle); Autodesk Docs for cloud`,
    kerf: `${GOOD} file_revisions (fine-grained undo) + cloud git (GitHub sync)`,
  },

  // Ecosystem & SDK
  {
    group: 'Ecosystem & SDK',
    feature: 'Chat / LLM editing',
    competitor: `${GAP} None`,
    kerf: `${GOOD} Chat-native — edits feature source per turn, doc-search backed`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'BYO LLM',
    competitor: `${GAP} Not applicable`,
    kerf: `${GOOD} BYO API key (kerf_byo bucket); any Anthropic/OpenAI compatible model`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'Scripting / automation',
    competitor: `${GOOD} iLogic (VB rules), Inventor API (COM/.NET), ApprenticeServer`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'Add-in ecosystem',
    competitor: `${GOOD} Autodesk App Store; HSMWorks, Vault, Nastran, Netfabb`,
    kerf: `${WEAK} Early-stage; plugin architecture (kerf-* packages)`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'Community & training',
    competitor: `${GOOD} Large global user base; Autodesk University; certified training`,
    kerf: `${WEAK} Early-stage, growing`,
  },
]

/* -------------------------------------------------------------------------
 * Page component
 * ---------------------------------------------------------------------- */
export default function InventorPage() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <HeadMeta meta={meta} />
      <Header />

      <main className="mx-auto max-w-4xl px-6 pt-12 pb-20">
        <Breadcrumb />

        {/* Hero */}
        <div className="mb-10">
          <p
            className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2"
            aria-hidden="true"
          >
            Compare
          </p>
          <h1
            className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight"
            aria-label="Kerf versus Autodesk Inventor comparison"
          >
            Kerf vs Autodesk Inventor
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Autodesk Inventor is a top-tier professional mechanical CAD
            platform with roughly 30 years of refinement and a dominant
            position in industrial manufacturing, aerospace, and automotive
            design. It delivers comprehensive parametric part and assembly
            workflows, an integrated dynamic simulation environment with a
            full joint catalog, Frame Generator, Tube &amp; Pipe, Cable &amp;
            Harness, in-box Stress Analysis FEA, and deep Vault PDM
            integration. Kerf will not out-Inventor Inventor on assembly
            dynamics, large-assembly performance, or specialty MFG tooling —
            that is an honest statement. Where Kerf differs is MIT open-core
            licensing, chat-native editing, no Windows-only constraint, no
            per-seat fee, a multi-discipline workspace unifying mechanical,
            electronics, and jewelry design, and in-box process simulation
            (weld, forming, AM, moldflow) without add-ins or separate
            Autodesk products.
          </p>
        </div>

        {/* Where Inventor is strong */}
        <Section title="Where Inventor is strong">
          <ul
            className="flex flex-col gap-3"
            aria-label="Autodesk Inventor strengths"
          >
            <Li>
              <strong className="text-ink-100">
                Comprehensive parametric mechanical CAD.
              </strong>{' '}
              Inventor is Autodesk&#8217;s SOLIDWORKS competitor for
              professional mechanical and manufacturing design. Its feature
              tree, constraint-based sketcher, and ShapeManager kernel have
              been refined over ~30 years of industrial production use across
              millions of part and assembly files.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Dynamic Simulation with a full joint catalog.
              </strong>{' '}
              Inventor&#8217;s Dynamic Simulation workspace supports multi-body
              dynamics with rigid, revolute, sliding, cylindrical, spherical,
              and planar joint types, redundant constraint detection, and
              motion-load export back into the FEA environment. Kerf has no
              equivalent today (roadmap T-108).
            </Li>
            <Li>
              <strong className="text-ink-100">
                In-box Stress Analysis (FEA).
              </strong>{' '}
              Linear static FEA on parts and assemblies ships inside Inventor
              Professional — no external solver licence required. Results
              drive design parameter feedback directly inside the part
              environment. Kerf has no structural FEM today.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Frame Generator for weldments and structural members.
              </strong>{' '}
              Frame Generator automates structural-frame design from profiles,
              generates weldment cut lists, applies end treatments and gussets,
              and feeds beam analysis. Kerf has no frame-generator workspace.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Tube &amp; Pipe and Cable &amp; Harness.
              </strong>{' '}
              Routed Tube &amp; Pipe (with standard fittings, bends, and
              isometric drawings) and Cable &amp; Harness (wire routing,
              nailboard drawings, harness flattening) are purpose-built
              specialty workflows inside Inventor that Kerf does not replicate.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Mold Design module.
              </strong>{' '}
              The Mold Design workspace handles cavity/core layout, parting
              surface generation, runner and gate design, and mold-base
              assembly — a tooling workflow for injection-mold designers that
              Kerf does not match.
            </Li>
            <Li>
              <strong className="text-ink-100">
                iLogic rules engine.
              </strong>{' '}
              iLogic lets designers embed Visual Basic rules that drive
              parameters, suppress features, and trigger events — enabling
              configurable product families without writing full macros.
              Kerf&#8217;s closest analogy is chat-driven feature editing and
              kerf-sdk Python scripting, which are more flexible for new
              workflows but lack iLogic&#8217;s declarative configurator model.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Large-assembly management.
              </strong>{' '}
              Level-of-detail representations, substitute representations,
              demand-loading, and associative simplification handle multi-
              thousand-part assemblies that would stress any lighter CAD
              environment. Kerf has no equivalent large-assembly tooling today.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Vault PDM integration.
              </strong>{' '}
              Deep integration with Autodesk Vault for check-in/check-out,
              lifecycle management, BOM roll-up, and ECO workflows is a
              mature PDM story for teams that live in the Autodesk ecosystem.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Inventor Studio (visualisation).
              </strong>{' '}
              Ray-trace rendering, animation authoring, and presentation output
              are built into Inventor Studio without needing a separate
              rendering tool.
            </Li>
          </ul>
        </Section>

        {/* Common Inventor pain points */}
        <Section title="Common Inventor pain points">
          <ul
            className="flex flex-col gap-3"
            aria-label="Common Autodesk Inventor pain points"
          >
            <Li>
              <strong className="text-ink-100">Subscription pricing.</strong>{' '}
              Inventor Professional runs ~US$2,545/yr per seat; the
              Product Design &amp; Manufacturing Collection (which bundles
              Inventor, Fusion, Vault, and Nastran) is ~US$3,115/yr. There
              is no perpetual-licence option since Autodesk retired perpetual
              sales in 2021 — every seat is a recurring subscription.
            </Li>
            <Li>
              <strong className="text-ink-100">Windows only.</strong>{' '}
              Inventor is a Windows-native desktop application. macOS and
              Linux engineers must virtualise or maintain a dedicated Windows
              machine — a meaningful overhead for cross-platform teams or
              individuals.
            </Li>
            <Li>
              <strong className="text-ink-100">
                CAM requires a separate product or add-in.
              </strong>{' '}
              Inventor ships no native CAM. Professional workflows use
              HSMWorks for Inventor (extra cost) or route geometry through
              Fusion 360 for CAM — adding an extra product licence and a
              round-trip workflow.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Autodesk pushes Fusion for cloud-native features.
              </strong>{' '}
              Autodesk&#8217;s cloud-first investments concentrate on Fusion
              360, not Inventor. Cloud collaboration for Inventor requires
              Autodesk Docs / Fusion Team (a separate subscription layer),
              and generative design is Fusion-only. Inventor users sometimes
              feel like a product on the slower investment track.
            </Li>
            <Li>
              <strong className="text-ink-100">
                AnyCAD bridge needed for non-Inventor files.
              </strong>{' '}
              Importing native files from SOLIDWORKS, Creo, or NX requires
              the AnyCAD / AnyCAD Advanced feature, which can surface
              translation artefacts and does not import parametric history.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Complex install and ecosystem inertia.
              </strong>{' '}
              A full Inventor installation with Vault, HSMWorks, and simulation
              modules is a multi-gigabyte, multi-step process. Teams invested
              in that ecosystem face real switching costs regardless of which
              tool they move to.
            </Li>
            <Li>
              <strong className="text-ink-100">
                No multi-discipline breadth.
              </strong>{' '}
              Electronics design, PCB layout, and jewelry tooling are entirely
              outside Inventor&#8217;s scope. Teams with cross-discipline
              workloads must manage separate tool ecosystems with file-exchange
              workflows and separate licences.
            </Li>
          </ul>
        </Section>

        {/* Where Kerf differs */}
        <Section title="Where Kerf differs">
          <ul
            className="flex flex-col gap-3"
            aria-label="Where Kerf differs from Autodesk Inventor"
          >
            <Li>
              <strong className="text-ink-100">MIT open-core, no seat fee.</strong>{' '}
              The full feature set is MIT-licensed and free to install locally.
              There is no ~$2,500/yr subscription, no subscription-only lock-in,
              and no commercial-use restriction.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Chat-native workflow and BYO LLM.
              </strong>{' '}
              Describe a feature, sketch constraint, or assembly change in
              plain English; the model edits the feature-tree source per turn,
              backed by live doc-search so it does not hallucinate API surface.
              Bring your own Anthropic or compatible API key with zero billing
              routed through Kerf.
            </Li>
            <Li>
              <strong className="text-ink-100">CAM included in-box.</strong>{' '}
              3-axis CAM with tool DB and 5-axis 3+2 ship as part of the core
              product — no HSMWorks licence, no Fusion round-trip required.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Cross-platform, browser + local binary.
              </strong>{' '}
              Runs in the browser (hosted SaaS) or as a single local binary on
              Windows, macOS, and Linux. No Parallels, no dedicated Windows box,
              no multi-gigabyte installer.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Full ECAD in one workspace — no add-in.
              </strong>{' '}
              Hierarchical schematic, PCB layout, shove router, SPICE, IPC
              fab output, and the full pre-compliance simulation suite (SI,
              EMC, PDN, thermal) are built into the same workspace as the
              B-rep modeller — no separate ECAD licence, no IDF round-trip.
            </Li>
            <Li>
              <strong className="text-ink-100">
                In-box process simulation for weld, forming, AM, and moldflow.
              </strong>{' '}
              Inventor users who need weld or AM process simulation must reach
              for separate Autodesk products (Netfabb, Nastran). Kerf ships
              weld simulation, sheet-forming simulation, AM/SLA process
              simulation, and moldflow simulation in-box, without add-in
              purchases.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Parametric history DAG + persistent face IDs.
              </strong>{' '}
              Kerf&#8217;s Phase 4 persistent face naming is conceptually
              equivalent to Inventor&#8217;s adaptive feature references:
              downstream features survive upstream edits without breaking.
              620 analytic-oracle kernel tests provide exact closed-form
              references for geometric accuracy.
            </Li>
            <Li>
              <strong className="text-ink-100">40-module jewelry domain.</strong>{' '}
              Ring v4, gemstones v2 (30 cuts), settings v3/v4, gem-seat v2,
              chain v2, findings, casting export, full cost panel, and PBR
              gem/metal viewport materials — a professional jewelry vertical
              that has no Inventor counterpart.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Cloud git built in, no PDM server.
              </strong>{' '}
              Every project gets fine-grained file revision history (undo) plus
              deliberate cloud-git commits with GitHub sync — no Vault server
              setup, no Autodesk Docs subscription required for version
              control.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate B-rep, PCB, and jewelry workflows from a Python script
              on your own machine over HTTP/JSON-RPC — the same interface the
              LLM uses internally, so scripts and chat edits are first-class
              and composable.
            </Li>
          </ul>
        </Section>

        {/* Honest gaps */}
        <Section title="Honest gaps — where Kerf is behind today">
          <ul
            className="flex flex-col gap-3"
            aria-label="Areas where Kerf is behind Autodesk Inventor today"
          >
            <Li>
              <strong className="text-ink-100">
                Dynamic Simulation (multi-body dynamics).
              </strong>{' '}
              Inventor&#8217;s full joint catalog — rigid, revolute, slider,
              cylindrical, spherical, planar — with motion-load export to FEA
              is a production workflow Kerf has no equivalent for today
              (roadmap T-108 tracks assembly mate depth).
            </Li>
            <Li>
              <strong className="text-ink-100">Structural FEA.</strong>{' '}
              Inventor&#8217;s in-box Stress Analysis (linear static FEA on
              parts and assemblies) is a production tool used by real
              engineering teams. Kerf ships no structural FEM.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Frame Generator, Tube &amp; Pipe, Cable &amp; Harness.
              </strong>{' '}
              These are purpose-built specialty modules with years of
              industrial refinement. Kerf has no frame-generator workspace,
              no routed Tube &amp; Pipe, and no Cable &amp; Harness
              environment.
            </Li>
            <Li>
              <strong className="text-ink-100">Mold Design workspace.</strong>{' '}
              Inventor&#8217;s Mold Design module — cavity/core, parting
              surfaces, runner/gate design, and mold-base assembly — is a
              tooling workflow for injection-mold designers that Kerf does
              not replicate. Kerf&#8217;s moldflow process simulation covers
              fill analysis, not mold construction.
            </Li>
            <Li>
              <strong className="text-ink-100">
                iLogic configurator model.
              </strong>{' '}
              iLogic&#8217;s declarative rules engine for product configuration
              families has no direct Kerf equivalent. Chat-driven scripting
              and kerf-sdk Python are more flexible for novel workflows but
              do not model the same structured configurator pattern.
            </Li>
            <Li>
              <strong className="text-ink-100">Large-assembly tooling.</strong>{' '}
              Level-of-detail representations, substitute representations, and
              demand-loading are well-tested Inventor workflows for multi-
              thousand-part assemblies. Kerf has no equivalent today.
            </Li>
            <Li>
              <strong className="text-ink-100">Vault PDM depth.</strong>{' '}
              Autodesk Vault provides lifecycle management, check-in/check-out
              with file-locking, ECO workflows, and BOM roll-up. Kerf&#8217;s
              cloud-git version control covers the basics but lacks a full
              PDM lifecycle layer.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Inventor API and iLogic ecosystem.
              </strong>{' '}
              The Inventor COM API + iLogic ecosystem has decades of depth
              covering every feature, mate, and drawing entity. Kerf&#8217;s
              kerf-sdk is younger and covers major workflows but lacks
              equivalent API breadth.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Vendor maturity and training.
              </strong>{' '}
              ~30 years of industrial refinement, Autodesk University, a large
              certified reseller network, and an enormous body of training
              content are irreplaceable near-term. Kerf is early-stage.
            </Li>
          </ul>
        </Section>

        {/* Migration notes */}
        <Section title="Notes for Inventor users considering Kerf">
          <ul
            className="flex flex-col gap-3"
            aria-label="Migration notes for Autodesk Inventor users"
          >
            <Li>
              <strong className="text-ink-100">
                Parametric concepts map directly.
              </strong>{' '}
              Feature tree, constraint sketcher, multi-sheet drawings with
              GD&amp;T, sheet metal with flat pattern, BOM management, and a
              Python scripting API all exist in Kerf with comparable intent.
              An Inventor user will recognise the design paradigm immediately.
            </Li>
            <Li>
              <strong className="text-ink-100">
                STEP is the migration path.
              </strong>{' '}
              Kerf imports STEP and IGES. Export from Inventor to STEP first;
              the B-rep geometry transfers cleanly even though parametric
              history and iLogic rules do not.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Assembly-heavy and simulation-heavy workflows: expect real gaps.
              </strong>{' '}
              Teams whose primary output is dynamic simulation, stress
              analysis, large assemblies with motion studies, or routed Tube
              &amp; Pipe will notice the capability difference quickly.
              Factor significant ramp-up time and validate that the gaps are
              acceptable for your specific workloads before switching.
            </Li>
            <Li>
              <strong className="text-ink-100">
                CAM and process-sim are where cost changes most visibly.
              </strong>{' '}
              If your Inventor workflow depends on an HSMWorks or Fusion CAM
              licence, or on Netfabb for AM process simulation, Kerf&#8217;s
              in-box 3-axis, 5-axis 3+2 CAM, and process-sim suite can
              reduce those add-in costs. Validate toolpaths and process-sim
              outputs carefully on your own geometry.
            </Li>
            <Li>
              <strong className="text-ink-100">
                The ECAD + MCAD integration is Kerf&#8217;s differentiator.
              </strong>{' '}
              If your team currently maintains separate ECAD and MCAD tools
              with a manual STEP or IDF handoff workflow, Kerf&#8217;s
              co-resident workspace removes that boundary and adds an in-box
              electronics pre-compliance suite — without a separate Autodesk
              Fusion Electronics subscription.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Multi-discipline scope is the long-term differentiator.
              </strong>{' '}
              Inventor excels at pure mechanical manufacturing. If your
              workload is exclusively large-scale mechanical assemblies with
              deep dynamics simulation, Inventor&#8217;s maturity and depth
              are hard to match. If your workload spans mechanical, electronics,
              and other disciplines in one team, Kerf&#8217;s unified workspace
              without per-discipline licensing is the design goal.
            </Li>
          </ul>
        </Section>

        {/* Side by side */}
        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Autodesk Inventor" />
          <TableFooter />
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
