/**
 * /compare/autocad — Kerf vs AutoCAD (Autodesk)
 *
 * Web-grounded (last reviewed 2026-05-17). AutoCAD is the 40+ year incumbent
 * for 2D drafting and the originator of the .dwg format — the de-facto
 * exchange format for 2D construction and AEC documentation. AutoCAD
 * LT/Standard/Plus/Prime/Ultimate (all subscription) plus a wide family of
 * verticals: Civil 3D, Architecture, MEP, Electrical, Plant 3D, Map 3D.
 * Subscription pricing is ~US$255/mo or ~US$2,030/yr for AutoCAD (single tool);
 * the AEC Collection bundle is ~US$3,475/yr. A 30-day free trial is offered.
 *
 * Kerf is NOT a drafting-first tool and is not positioned as an AutoCAD
 * replacement for production AEC work. AutoCAD owns 2D drafting + .dwg;
 * Kerf is a 3D parametric CAD with drawing export, multi-discipline scope,
 * and a chat-native workflow. The honest comparison is that they solve
 * different primary problems — AutoCAD for 2D drafting documentation +
 * AEC workflows; Kerf for 3D parametric design with integrated electronics,
 * jewelry, and simulation.
 *
 * DWG interchange: Kerf imports DWG (Tier 1 via kerf-imports import_dwg using
 * the libredwg bridge). Kerf does NOT export DWG natively — it writes DXF
 * instead (same .dwg/.dxf family; broadly compatible with AutoCAD and
 * AutoCAD LT).
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

/* -------------------------------------------------------------------------- */
/* Inline meta (autocad slug not yet wired in compareMeta.js; added here      */
/* so this page renders correctly without touching compareMeta.js)            */
/* -------------------------------------------------------------------------- */

const BASE = 'https://kerf.sh'
const meta = {
  title: 'Kerf vs AutoCAD — 3D parametric CAD vs 2D drafting compared',
  description:
    'AutoCAD is the 40-year incumbent for 2D drafting and .dwg. See where ' +
    "Kerf's 3D parametric, multi-discipline, MIT open-core approach fits — honestly.",
  canonical: `${BASE}/compare/autocad`,
  ogImage: `${BASE}/og/compare-autocad.png`,
  get jsonLd() {
    return JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'WebPage',
      name: this.title,
      description: this.description,
      url: this.canonical,
      image: this.ogImage,
      publisher: { '@type': 'Organization', name: 'Kerf', url: BASE },
    })
  },
  product: 'AutoCAD',
  slug: 'autocad',
}

/* -------------------------------------------------------------------------- */
/* Feature matrix                                                               */
/* -------------------------------------------------------------------------- */

const TABLE = [
  // Licensing & platform
  { group: 'Licensing & platform', feature: 'License',
    competitor: `${WEAK} Proprietary subscription`,
    kerf: `${GOOD} MIT open-core` },
  { group: 'Licensing & platform', feature: 'Cost',
    competitor: `${WEAK} ~US$255/mo or ~US$2,030/yr (AutoCAD); AEC Collection ~US$3,475/yr`,
    kerf: `${GOOD} Free local; pay-as-you-go hosted credits` },
  { group: 'Licensing & platform', feature: 'Free tier',
    competitor: `${WEAK} 30-day trial; AutoCAD LT Web limited free plan`,
    kerf: `${GOOD} Full free local install, no revenue cap` },
  { group: 'Licensing & platform', feature: 'Open source',
    competitor: `${GAP} Proprietary`,
    kerf: `${GOOD} MIT — full codebase on GitHub` },
  { group: 'Licensing & platform', feature: 'OS support',
    competitor: `${WEAK} Windows primary; macOS version (feature-restricted)`,
    kerf: `${GOOD} Browser (hosted) + binary local on Win / macOS / Linux` },
  { group: 'Licensing & platform', feature: 'Offline / self-host',
    competitor: `${GOOD} Desktop app, full offline once installed`,
    kerf: `${GOOD} Full offline single-binary install (brew / curl)` },
  { group: 'Licensing & platform', feature: 'Maturity',
    competitor: `${GOOD} 40+ year incumbent, millions of seats worldwide`,
    kerf: `${WEAK} Early-stage, < 2 yr public` },

  // Primary capability
  { group: 'Primary capability', feature: 'Design intent',
    competitor: `${GOOD} 2D drafting-first with 3D modelling; documentation-grade`,
    kerf: `${GOOD} 3D parametric-first with drawing export` },
  { group: 'Primary capability', feature: '2D drafting depth',
    competitor: `${GOOD} Industry-defining: dynamic blocks, paper-space layouts, dimension styles, sheet sets, layer standards, linetypes, hatch`,
    kerf: `${WEAK} Drawing views + dimensions; 2D drafting is not the primary focus` },
  { group: 'Primary capability', feature: '3D parametric modeling',
    competitor: `${WEAK} Solid/surface 3D modelling present but not competitive with Inventor / Fusion / SolidWorks`,
    kerf: `${GOOD} OCCT feature tree — pad/pocket/revolve/loft/boss-with-draft` },
  { group: 'Primary capability', feature: 'Constraint sketcher',
    competitor: `${WEAK} Basic 2D constraints; not a parametric history sketcher`,
    kerf: `${GOOD} Sketcher v2 — full parametric constraints` },
  { group: 'Primary capability', feature: 'Parametric history DAG',
    competitor: `${WEAK} Limited; no true feature history (that is Inventor)`,
    kerf: `${GOOD} Feature DAG + persistent face naming (Phase 4)` },

  // 2D drafting toolset
  { group: '2D drafting toolset', feature: 'Dynamic blocks',
    competitor: `${GOOD} Dynamic blocks with visibility states and action parameters`,
    kerf: `${GAP} Not available` },
  { group: '2D drafting toolset', feature: 'Paper-space layouts + viewports',
    competitor: `${GOOD} Full paper-space / model-space workflow with multi-scale viewports`,
    kerf: `${WEAK} Drawing sheets with standard view projection` },
  { group: '2D drafting toolset', feature: 'Dimension styles',
    competitor: `${GOOD} Named dimension styles, tolerances, ASME/ISO standards`,
    kerf: `${GOOD} ASME Y14.5 datum + tolerance framework` },
  { group: '2D drafting toolset', feature: 'Sheet sets',
    competitor: `${GOOD} Sheet Set Manager — multi-drawing coordinated output`,
    kerf: `${GAP} Not available` },
  { group: '2D drafting toolset', feature: 'CAD standards / drawing standards',
    competitor: `${GOOD} CAD Standards Manager, layer translators`,
    kerf: `${GAP} Not available` },
  { group: '2D drafting toolset', feature: 'Express Tools',
    competitor: `${GOOD} 50+ productivity tools (Overkill, Super Hatch, etc.)`,
    kerf: `${GAP} Not available` },

  // File formats
  { group: 'File formats', feature: '.dwg native read',
    competitor: `${GOOD} Native format owner`,
    kerf: `${GOOD} DWG import Tier 1 (libredwg bridge)` },
  { group: 'File formats', feature: '.dwg native write',
    competitor: `${GOOD} Native`,
    kerf: `${WEAK} No native DWG export — writes DXF (same family; broad compatibility)` },
  { group: 'File formats', feature: 'DXF read/write',
    competitor: `${GOOD} Full DXF support (originator)`,
    kerf: `${GOOD} DXF read (Tier 1) + DXF write` },
  { group: 'File formats', feature: 'STEP / IGES / IFC',
    competitor: `${GOOD} STEP / IGES (3D); IFC via Architecture vertical`,
    kerf: `${GOOD} STEP / IGES / IFC import; STEP export` },

  // Scripting & automation
  { group: 'Scripting & automation', feature: 'AutoLISP / .NET / VBA',
    competitor: `${GOOD} AutoLISP, Visual LISP, .NET API, VBA (legacy) — deep automation`,
    kerf: `${GAP} No AutoLISP/VBA — different paradigm` },
  { group: 'Scripting & automation', feature: 'Python scripting / SDK',
    competitor: `${WEAK} pyautocad (community); no official PyPI SDK`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC; first-class API` },
  { group: 'Scripting & automation', feature: 'Chat / LLM workflow',
    competitor: `${WEAK} AI Assist (Autodesk AI) — limited; not source-level editing`,
    kerf: `${GOOD} Chat-native — edits feature-tree source per turn, doc-search backed` },
  { group: 'Scripting & automation', feature: 'Command-line interface',
    competitor: `${GOOD} Industry-native command line; keyboard-driven power user workflow`,
    kerf: `${WEAK} Kerf has no AutoCAD-style command line; chat replaces it` },

  // AEC verticals
  { group: 'AEC verticals', feature: 'Civil 3D',
    competitor: `${GOOD} Full civil/infrastructure vertical (grading, corridors, alignments)`,
    kerf: `${GAP} Not available` },
  { group: 'AEC verticals', feature: 'AutoCAD Architecture / MEP',
    competitor: `${GOOD} AEC-specific wall/door/beam objects + M/E/P systems`,
    kerf: `${GAP} Not available` },
  { group: 'AEC verticals', feature: 'Plant 3D / P&ID',
    competitor: `${GOOD} Process plant design, piping, P&ID generation`,
    kerf: `${GAP} Not available` },
  { group: 'AEC verticals', feature: 'AutoCAD Electrical',
    competitor: `${GOOD} Electrical panel schedules, wire numbering, reports`,
    kerf: `${GAP} No panel-schedule vertical; Kerf covers PCB/schematic electronics` },
  { group: 'AEC verticals', feature: 'Architecture / BIM / IFC',
    competitor: `${WEAK} Via AutoCAD Architecture vertical; Revit is Autodesk's BIM flagship`,
    kerf: `${WEAK} IFC Tier 2 import + structural grid` },

  // Multi-discipline (Kerf scope)
  { group: 'Multi-discipline (Kerf scope)', feature: 'PCB / electronics',
    competitor: `${GAP} No PCB design — separate tool (AutoCAD Electrical covers panel wiring, not PCB)`,
    kerf: `${GOOD} Full EDA — schematic, routing, DRC, Gerber / IPC-2581 / ODB++` },
  { group: 'Multi-discipline (Kerf scope)', feature: 'Jewelry tooling',
    competitor: `${GAP} No jewelry modules`,
    kerf: `${GOOD} 40-module jewelry suite: ring v4, gemstones v2 (30 cuts), settings, chain v2, findings, casting export` },
  { group: 'Multi-discipline (Kerf scope)', feature: 'Electronics simulation (SI / EMC / PDN)',
    competitor: `${GAP} Not in AutoCAD`,
    kerf: `${GOOD} In-box SI, EMC, PDN, PCB thermal — no extension gating` },
  { group: 'Multi-discipline (Kerf scope)', feature: 'CAM / fabrication',
    competitor: `${GAP} No CAM — separate tool (HSMWorks / Fusion / Inventor CAM)`,
    kerf: `${GOOD} 3-axis CAM + tool DB; 5-axis 3+2; slicing Tier 1` },

  // Drawings / documentation
  { group: 'Drawings & documentation', feature: '2D drawings from 3D model',
    competitor: `${GOOD} Model-to-layout projection`,
    kerf: `${GOOD} Multi-sheet drawings from 3D model` },
  { group: 'Drawings & documentation', feature: 'GD&T',
    competitor: `${GOOD} ASME / ISO GD&T dimension objects`,
    kerf: `${GOOD} ASME Y14.5 datum + tolerance framework` },
  { group: 'Drawings & documentation', feature: 'Title blocks / borders',
    competitor: `${GOOD} Fully configurable, standards templates`,
    kerf: `${WEAK} Title block support (early)` },

  // Collaboration
  { group: 'Collaboration', feature: 'Cloud / multi-user',
    competitor: `${GOOD} AutoCAD web app + AutoCAD mobile; Autodesk Docs for file sharing`,
    kerf: `${GOOD} Hosted multi-user + cloud-git project sync` },
  { group: 'Collaboration', feature: 'BYO LLM / key',
    competitor: `${GAP} No configurable LLM`,
    kerf: `${GOOD} BYO key (kerf_byo) — use own Anthropic/OpenAI key` },

  // Ecosystem
  { group: 'Ecosystem', feature: 'Training materials / community',
    competitor: `${GOOD} 40+ years of official Autodesk courses, YouTube, certification, textbooks`,
    kerf: `${WEAK} Early-stage, growing` },
  { group: 'Ecosystem', feature: 'Vendor support & SLA',
    competitor: `${GOOD} Enterprise support, named CSM, Autodesk support tiers`,
    kerf: `${WEAK} Priority support = Enterprise tier only` },
]

/* -------------------------------------------------------------------------- */
/* Page                                                                         */
/* -------------------------------------------------------------------------- */

export default function AutocadPage() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <HeadMeta meta={meta} />
      <Header />

      <main
        className="mx-auto max-w-4xl px-6 pt-12 pb-20"
        aria-label="Kerf vs AutoCAD comparison"
      >
        <Breadcrumb />

        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <header className="mb-10">
          <p
            className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2"
            aria-hidden="true"
          >
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            Kerf vs AutoCAD
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            AutoCAD is a 40+ year incumbent — the tool that defined 2D
            computer-aided drafting, created the .dwg format, and remains the
            industry standard for AEC documentation worldwide. Autodesk has
            built an entire family of specialised verticals on top of it: Civil
            3D, Architecture, MEP, Electrical, Plant 3D. Kerf is not a
            replacement for that body of work. What Kerf offers is a different
            starting point: 3D parametric design, multi-discipline scope
            (electronics, jewelry, mechanical in one tool), a chat-native
            workflow, and an MIT open-core licence. Below is an honest look at
            both — including where AutoCAD is clearly ahead.
          </p>
        </header>

        {/* ── Honest positioning callout ───────────────────────────────── */}
        <aside
          aria-label="Honest positioning: Kerf is not an AutoCAD replacement"
          className="mb-10 rounded-xl border border-kerf-300/30 bg-kerf-300/5 px-5 py-4"
        >
          <h2 className="font-display text-base font-semibold text-kerf-200 mb-2">
            Honest positioning
          </h2>
          <p className="text-sm text-ink-300 leading-relaxed">
            <strong className="text-ink-100">Kerf is not an AutoCAD replacement</strong>{' '}
            for production AEC drafting. AutoCAD owns 2D drafting + .dwg; if
            your workflow centres on construction documents, sheet sets,
            dynamic blocks, Civil 3D corridors, or MEP systems, AutoCAD (or its
            verticals) is the appropriate tool and will remain so for the
            foreseeable future. Kerf is a 3D parametric CAD with drawing export,
            integrated electronics and jewelry, and a chat-driven workflow — a
            different primary problem. The comparison below is useful if you are
            evaluating Kerf for 3D design work where you currently use AutoCAD
            as a supplementary 3D tool, or if you are curious about DWG
            interchange.
          </p>
        </aside>

        {/* ── Where AutoCAD is strong ──────────────────────────────────── */}
        <Section title="Where AutoCAD is strong">
          <ul
            className="flex flex-col gap-3"
            aria-label="AutoCAD strengths"
          >
            <Li>
              <strong className="text-ink-100">The 2D drafting standard.</strong>{' '}
              AutoCAD invented the vocabulary of computer-aided 2D drafting —
              paper-space / model-space, dimension styles, hatch, linetypes,
              layer conventions, xrefs, dynamic blocks. Every other 2D CAD tool
              is measured against it. Kerf&#8217;s drawing capability is 3D-to-2D
              view projection, not drafting-first.
            </Li>
            <Li>
              <strong className="text-ink-100">.dwg as the industry interchange.</strong>{' '}
              Autodesk created .dwg and owns the reference implementation. The
              format is the lingua franca for construction documents,
              infrastructure, and manufacturing drawings worldwide. Kerf can
              read DWG (Tier 1 via libredwg) but does not write native .dwg —
              it writes DXF instead, which is broadly compatible but not
              identical.
            </Li>
            <Li>
              <strong className="text-ink-100">Dynamic blocks and sheet sets.</strong>{' '}
              AutoCAD&#8217;s dynamic block system — visibility states, action
              parameters, table-driven instances — has no equivalent in Kerf.
              Sheet Set Manager for coordinated multi-drawing output is similarly
              absent.
            </Li>
            <Li>
              <strong className="text-ink-100">AutoLISP / .NET / VBA scripting depth.</strong>{' '}
              A 40-year accumulation of AutoLISP routines, LISP macros, and
              .NET API scripts exists for AutoCAD. Kerf has a Python HTTP/JSON-RPC
              SDK and a chat-native workflow, but no AutoLISP compatibility and
              none of that ecosystem.
            </Li>
            <Li>
              <strong className="text-ink-100">Specialised AEC verticals.</strong>{' '}
              Civil 3D (grading, corridors, alignments, surfaces), AutoCAD
              Architecture (wall/door/window objects, room tags), AutoCAD MEP
              (ductwork, piping, electrical), AutoCAD Electrical (panel
              schedules, wire numbering), and Plant 3D (P&amp;ID, 3D plant
              design) are mature, industry-specific tools. Kerf has none of
              these.
            </Li>
            <Li>
              <strong className="text-ink-100">Express Tools and drafting productivity.</strong>{' '}
              Over 50 Express Tools (Overkill for duplicate removal, Super
              Hatch, Layer Isolate, etc.) and 40+ years of in-the-field
              keyboard shortcuts make AutoCAD extremely efficient for
              drafting-heavy workflows.
            </Li>
            <Li>
              <strong className="text-ink-100">Command-line power user workflow.</strong>{' '}
              AutoCAD&#8217;s command-line interface is a well-loved feature for
              power users — muscle memory built over decades. Whether this is a
              strength or a learning-curve depends on the user; Kerf replaces it
              with a chat interface.
            </Li>
            <Li>
              <strong className="text-ink-100">Decades of training material and certification.</strong>{' '}
              Official Autodesk courses, Autodesk Certified Professional
              accreditation, thousands of YouTube tutorials, and formal
              educational programmes exist worldwide. Kerf is early-stage and
              has limited training resources today.
            </Li>
            <Li>
              <strong className="text-ink-100">Vendor support infrastructure.</strong>{' '}
              Autodesk provides tiered enterprise support, named customer success
              managers, and SLA-backed support contracts for large accounts.
            </Li>
          </ul>
        </Section>

        {/* ── Where Kerf differs ───────────────────────────────────────── */}
        <Section title="Where Kerf differs">
          <ul
            className="flex flex-col gap-3"
            aria-label="Kerf differentiators vs AutoCAD"
          >
            <Li>
              <strong className="text-ink-100">3D parametric from the start.</strong>{' '}
              Kerf is built around a feature history DAG (OCCT kernel) with a
              full constraint sketcher — pad, pocket, revolve, loft,
              boss-with-draft, persistent face naming. AutoCAD&#8217;s 3D
              modelling is less capable than Autodesk&#8217;s own Inventor or
              Fusion 360.
            </Li>
            <Li>
              <strong className="text-ink-100">MIT open-core, no subscription.</strong>{' '}
              AutoCAD starts at ~US$2,030/yr (single tool) and the AEC
              Collection is ~US$3,475/yr. Kerf&#8217;s full feature set is
              MIT-licensed — free locally with no seat fee, no revenue
              restriction, and no feature-gating.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a feature, constraint, or dimension in plain language;
              the model edits the feature-tree source directly, backed by live
              doc-search so it does not invent API surface. AutoCAD&#8217;s AI
              Assist is add-on and not source-level.
            </Li>
            <Li>
              <strong className="text-ink-100">Multi-discipline in one tool.</strong>{' '}
              Electronics (schematic, PCB layout, DRC, Gerber / IPC-2581 /
              ODB++, pre-compliance simulation), jewelry (40 modules), and
              mechanical CAD coexist in a single Kerf workspace. AutoCAD is
              strictly a drafting / modelling tool; each additional discipline
              requires a separate Autodesk product.
            </Li>
            <Li>
              <strong className="text-ink-100">In-box electronics pre-compliance simulation.</strong>{' '}
              Signal integrity (transmission-line, via stub, differential pair),
              EMC/EMI, PDN (decap placement, target impedance, plane resonance),
              and PCB thermal are all included without extension gating.
              AutoCAD has no electronics simulation.
            </Li>
            <Li>
              <strong className="text-ink-100">40-module jewelry vertical.</strong>{' '}
              Ring v4, gemstones v2 (30 cuts), settings v3/v4, gem-seat v2,
              chain v2, findings, casting export, PBR gem/metal viewport
              materials, and a 31-template library. AutoCAD has no jewelry
              domain tooling.
            </Li>
            <Li>
              <strong className="text-ink-100">DWG import, DXF export.</strong>{' '}
              Kerf reads DWG (Tier 1, libredwg bridge) so existing AutoCAD
              geometry transfers. Kerf writes DXF rather than native .dwg —
              AutoCAD and AutoCAD LT open DXF natively, so this is broadly
              practical for downstream consumption.
            </Li>
            <Li>
              <strong className="text-ink-100">BYO LLM key.</strong>{' '}
              The{' '}
              <code className="font-mono text-kerf-300">kerf_byo</code> billing
              tier routes all inference to your own Anthropic or OpenAI key —
              zero LLM cost flows through Kerf. AutoCAD has no configurable LLM.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate over HTTP/JSON-RPC from your own machine — the same
              interface the LLM uses internally, so scripts and chat edits
              share one API surface. AutoCAD&#8217;s Python options are
              community-maintained rather than first-party.
            </Li>
            <Li>
              <strong className="text-ink-100">Full offline, single binary, open codebase.</strong>{' '}
              One binary (brew or curl install), no Autodesk account required,
              full MIT codebase on GitHub. AutoCAD is desktop-offline but
              proprietary.
            </Li>
          </ul>
        </Section>

        {/* ── Honest gaps ──────────────────────────────────────────────── */}
        <Section title="Honest gaps — where Kerf is behind today">
          <ul
            className="flex flex-col gap-3"
            aria-label="Areas where Kerf is behind AutoCAD"
          >
            <Li>
              <strong className="text-ink-100">2D drafting depth — not comparable.</strong>{' '}
              Dynamic blocks, sheet sets, paper-space / model-space layouts,
              dimension styles, layer standards, Express Tools, CAD Standards
              Manager — none of these exist in Kerf. If drafting is the primary
              job, AutoCAD is the correct tool.
            </Li>
            <Li>
              <strong className="text-ink-100">No native .dwg export.</strong>{' '}
              Kerf writes DXF, not .dwg. For workflows that require native .dwg
              output (some submitting authorities, legacy automation scripts),
              this is a real gap. DXF covers the majority of downstream
              consumption but is not identical.
            </Li>
            <Li>
              <strong className="text-ink-100">No AEC verticals at all.</strong>{' '}
              Civil 3D, AutoCAD Architecture, MEP, Electrical, Plant 3D — these
              are mature, domain-specific tools with no Kerf equivalent. For
              AEC professionals these verticals often define the workflow
              entirely.
            </Li>
            <Li>
              <strong className="text-ink-100">No AutoLISP / .NET ecosystem.</strong>{' '}
              A large body of automation scripts, LISP routines, and .NET
              plug-ins exists for AutoCAD. Kerf&#8217;s SDK is Python-first
              over HTTP/JSON-RPC — a different paradigm that does not run
              AutoLISP.
            </Li>
            <Li>
              <strong className="text-ink-100">No mechanical FEM.</strong>{' '}
              AutoCAD has no FEM either (that is Inventor / Nastran In-CAD),
              but Kerf also ships no structural FEM. Neither tool is the right
              choice for FEA-heavy structural work.
            </Li>
            <Li>
              <strong className="text-ink-100">Smaller community, fewer tutorials.</strong>{' '}
              AutoCAD has 40 years of official training, YouTube libraries,
              certification programmes, and textbooks. Kerf is early-stage;
              community resources are limited today.
            </Li>
            <Li>
              <strong className="text-ink-100">Younger, less-validated codebase.</strong>{' '}
              AutoCAD has been hardened across billions of files over four
              decades. Kerf is under two years public; rough edges will surface.
            </Li>
          </ul>
        </Section>

        {/* ── Migration notes ──────────────────────────────────────────── */}
        <Section title="Notes for AutoCAD users considering Kerf">
          <ul
            className="flex flex-col gap-3"
            aria-label="Migration notes for AutoCAD users"
          >
            <Li>
              <strong className="text-ink-100">Assess your primary workflow first.</strong>{' '}
              If your work is dominated by 2D drafting, construction
              documentation, sheet sets, or AEC-vertical tasks (Civil 3D, MEP,
              Electrical), Kerf is not a substitute — expect to keep AutoCAD or
              look at dedicated AEC alternatives (Civil 3D, Revit, and similar).
              Kerf makes sense as a primary tool for 3D parametric design work
              where AutoCAD is used as a supplementary modeller.
            </Li>
            <Li>
              <strong className="text-ink-100">DWG files come across cleanly.</strong>{' '}
              Kerf&#8217;s DWG import (Tier 1, libredwg bridge) reads AutoCAD
              geometry, layers, and basic annotation. Complex dynamic blocks and
              xref structures may not fully resolve — STEP export from any 3D
              AutoCAD work is more reliable than DWG for geometry transfer.
            </Li>
            <Li>
              <strong className="text-ink-100">DXF rather than DWG for output.</strong>{' '}
              Kerf writes DXF. AutoCAD and AutoCAD LT read DXF natively.
              For submitting to clients or authorities that specifically require
              .dwg, this requires a DXF→DWG conversion step (e.g. via AutoCAD
              itself, LibreCAD, or ODA converters).
            </Li>
            <Li>
              <strong className="text-ink-100">Command-line muscle memory does not transfer.</strong>{' '}
              AutoCAD&#8217;s command line (LINE, TRIM, OFFSET, FILLET…) is not
              present in Kerf. The chat workflow serves a similar intent — rapid
              feature creation via typed input — but the vocabulary and idioms
              are entirely different. Budget onboarding time.
            </Li>
            <Li>
              <strong className="text-ink-100">AutoLISP scripts do not run in Kerf.</strong>{' '}
              Existing LISP automation is not portable. The kerf-sdk Python API
              (HTTP/JSON-RPC) is the migration path for automation, but it is a
              rewrite, not a translation.
            </Li>
            <Li>
              <strong className="text-ink-100">Where Kerf genuinely adds scope.</strong>{' '}
              If you do 3D modelling in AutoCAD today and separately manage PCB
              design or jewelry tooling in other products, Kerf consolidates
              those disciplines in one workspace — a real reduction in context
              switching and file format friction.
            </Li>
          </ul>
        </Section>

        {/* ── Side-by-side table ───────────────────────────────────────── */}
        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="AutoCAD" />
          <TableFooter />
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
