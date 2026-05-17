/**
 * /compare/altium — Kerf vs Altium Designer
 *
 * Honest, web-grounded comparison (last reviewed 2026-05-17).
 *
 * Altium Designer is the commercial ECAD benchmark: industry-leading
 * push-and-shove interactive routing, ActiveRoute autorouter, situs engine,
 * hierarchical and multi-board schematics, a mature rules system, HDI/RF
 * stack-up tooling, 3D PCB editor, MCAD CoDesigner (SOLIDWORKS / CREO / Inventor),
 * signal-integrity via HyperLynx / TouchStone I/O, and a cloud-collaboration
 * overlay in Altium 365. It is Windows-only, subscription-priced, and
 * widely considered the gold standard for serious PCB engineering work.
 *
 * Kerf does not match Altium's interactive routing polish or HDI/RF depth.
 * Where Kerf differs: open-core MIT, multi-discipline (mech + jewelry + ECAD),
 * chat-driven editing, BYO LLM, integrated simulation pre-compliance suite,
 * kerf-imports QIF/IBIS readers, IPC-2581 + IPC-D-356A + IDF exports, and
 * a significantly lower price of entry.
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
 * Build meta inline — 'altium' is not registered in compareMeta.js and the
 * constraint prohibits touching that file.
 * ---------------------------------------------------------------------- */
const BASE = 'https://kerf.sh'
const meta = {
  title: 'Kerf vs Altium Designer — PCB & ECAD tools compared',
  description:
    'Altium Designer is the industry-standard commercial ECAD platform. ' +
    "See how Kerf's open-core, multi-discipline, chat-driven approach compares.",
  canonical: `${BASE}/compare/altium`,
  ogImage: `${BASE}/og/compare-altium.png`,
  jsonLd: JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: 'Kerf vs Altium Designer — PCB & ECAD tools compared',
    description:
      'Altium Designer is the industry-standard commercial ECAD platform. ' +
      "See how Kerf's open-core, multi-discipline, chat-driven approach compares.",
    url: `${BASE}/compare/altium`,
    image: `${BASE}/og/compare-altium.png`,
    publisher: { '@type': 'Organization', name: 'Kerf', url: BASE },
  }),
  product: 'Altium Designer',
  slug: 'altium',
}

/* -------------------------------------------------------------------------
 * Feature-matrix rows
 * ---------------------------------------------------------------------- */
const TABLE = [
  // Licensing & platform
  {
    group: 'Licensing & platform',
    feature: 'License',
    competitor: `${WEAK} Proprietary subscription (AUD/USD per seat)`,
    kerf: `${GOOD} MIT open-core (permissive)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Cost',
    competitor: `${WEAK} ~$8 000–$10 000+ USD/seat/yr`,
    kerf: `${GOOD} Free local; pay-as-you-go hosted credits at cost`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Platform',
    competitor: `${WEAK} Windows only`,
    kerf: `${GOOD} Browser (hosted) + single-binary local (Win / macOS / Linux)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Cloud collaboration',
    competitor: `${WEAK} Altium 365 (separate SaaS subscription)`,
    kerf: `${GOOD} Integrated hosted SaaS; cloud git built-in`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Maturity',
    competitor: `${GOOD} 30+ yr lineage; production-hardened`,
    kerf: `${WEAK} Early-stage, < 2 yr public`,
  },

  // Schematic
  {
    group: 'Schematic capture',
    feature: 'Hierarchical schematic',
    competitor: `${GOOD} Multi-level hierarchical / flat hybrid`,
    kerf: `${GOOD} Hierarchical schematic`,
  },
  {
    group: 'Schematic capture',
    feature: 'Multi-board projects',
    competitor: `${GOOD} Multi-board (MB3D workspace)`,
    kerf: `${WEAK} Single-board per project today`,
  },
  {
    group: 'Schematic capture',
    feature: 'ERC depth',
    competitor: `${GOOD} Deep ERC — pin-type, bus, differential, custom rules`,
    kerf: `${GOOD} ERC + IPC-2221B presets`,
  },
  {
    group: 'Schematic capture',
    feature: 'SPICE simulation',
    competitor: `${GOOD} Mixed-signal SPICE (XSPICE-based)`,
    kerf: `${GOOD} SPICE + model library`,
  },

  // PCB layout
  {
    group: 'PCB layout',
    feature: 'Interactive push-and-shove router',
    competitor: `${GOOD} Situs engine — gold-standard push-and-shove`,
    kerf: `${WEAK} Shove router; less mature than Altium's situs`,
  },
  {
    group: 'PCB layout',
    feature: 'ActiveRoute autorouter',
    competitor: `${GOOD} ActiveRoute — interactive guided autorouting`,
    kerf: `${GOOD} FreeRouting integrated`,
  },
  {
    group: 'PCB layout',
    feature: 'Differential pairs',
    competitor: `${GOOD} Diff-pair routing + tuning (mature)`,
    kerf: `${WEAK} Length tuning; diff-pair workflow lighter`,
  },
  {
    group: 'PCB layout',
    feature: 'Length / skew tuning',
    competitor: `${GOOD} Xsignals + interactive tuning with constraints`,
    kerf: `${GOOD} Length tuning`,
  },
  {
    group: 'PCB layout',
    feature: 'DRC rules system',
    competitor: `${GOOD} Highly advanced — query-language, scoped, hierarchical`,
    kerf: `${GOOD} DRC + IPC-2221B presets`,
  },
  {
    group: 'PCB layout',
    feature: 'Via stitching / copper pour',
    competitor: `${GOOD} Stitching, teardrops, polygon pours`,
    kerf: `${GOOD} Via stitching + copper pour`,
  },
  {
    group: 'PCB layout',
    feature: '3D PCB editor',
    competitor: `${GOOD} Native 3D PCB — STEP import, clearance checks`,
    kerf: `${WEAK} Board 3D view; shallower than Altium's editor`,
  },

  // HDI / RF
  {
    group: 'HDI & RF',
    feature: 'HDI stackup & via types',
    competitor: `${GOOD} Buried / blind / micro-via, back-drill, HDI rules`,
    kerf: `${WEAK} Via types available; HDI rule depth lighter`,
  },
  {
    group: 'HDI & RF',
    feature: 'RF / impedance',
    competitor: `${GOOD} Layer-stack manager, impedance calculator, RF rules`,
    kerf: `${GOOD} scikit-rf S-parameter integration`,
  },
  {
    group: 'HDI & RF',
    feature: 'Flex / rigid-flex',
    competitor: `${GOOD} Rigid-flex design + 3D fold simulation`,
    kerf: `${GOOD} Flex stackup`,
  },

  // MCAD-ECAD
  {
    group: 'MCAD & cross-domain',
    feature: 'MCAD CoDesigner',
    competitor: `${GOOD} SOLIDWORKS / CREO / Inventor / CATIA co-design`,
    kerf: `${WEAK} IDF MCAD bridge + board STEP; no live co-design push`,
  },
  {
    group: 'MCAD & cross-domain',
    feature: 'Mechanical CAD (same tool)',
    competitor: `${GAP} External MCAD required`,
    kerf: `${GOOD} Full B-rep, sketcher, drawings, sheet metal in one workspace`,
  },

  // SI / EMC / PDN / thermal pre-compliance
  {
    group: 'SI / EMC / PDN / thermal',
    feature: 'Signal integrity / eye diagram',
    competitor: `${GOOD} HyperLynx SI integration; IBIS/Touchstone`,
    kerf: `${GOOD} si_eye_wizard — differential-pair SI + eye diagram`,
  },
  {
    group: 'SI / EMC / PDN / thermal',
    feature: 'PDN analysis',
    competitor: `${GOOD} PDN Analyzer (impedance / ripple)`,
    kerf: `${GOOD} pdn_wizard — per-net impedance, decap optimisation`,
  },
  {
    group: 'SI / EMC / PDN / thermal',
    feature: 'EMC pre-compliance',
    competitor: `${WEAK} Guidance via external HyperLynx EMC`,
    kerf: `${GOOD} emc_wizard — FCC §15.109 + CISPR 32, 10 m-eq Class B`,
  },
  {
    group: 'SI / EMC / PDN / thermal',
    feature: 'Thermal board analysis',
    competitor: `${WEAK} Via Altium 365 Simulation / external`,
    kerf: `${GOOD} thermal_board + sim_corner analysis`,
  },
  {
    group: 'SI / EMC / PDN / thermal',
    feature: 'IBIS / QIF import',
    competitor: `${GOOD} IBIS I/O (Touchstone-grade SI)`,
    kerf: `${GOOD} kerf-imports ibis_reader + qif_reader (ISO 23952)`,
  },

  // Fabrication & assembly
  {
    group: 'Fabrication output',
    feature: 'Gerber / Excellon / P&P',
    competitor: `${GOOD} Full fab output suite`,
    kerf: `${GOOD} Gerber / Excellon / P&P`,
  },
  {
    group: 'Fabrication output',
    feature: 'IPC-2581',
    competitor: `${GOOD} IPC-2581 export`,
    kerf: `${GOOD} IPC-2581 fab pack`,
  },
  {
    group: 'Fabrication output',
    feature: 'IPC-D-356A',
    competitor: `${GOOD} IPC-D-356A netlist`,
    kerf: `${GOOD} IPC-D-356A export`,
  },
  {
    group: 'Fabrication output',
    feature: 'IDF export',
    competitor: `${GOOD} IDF v2 / v3 export`,
    kerf: `${GOOD} IDF MCAD bridge`,
  },
  {
    group: 'Fabrication output',
    feature: 'BOM cost / DFM',
    competitor: `${WEAK} BOM export; cost via external or Altium 365`,
    kerf: `${GOOD} BOM cost + DFM checks built in`,
  },
  {
    group: 'Fabrication output',
    feature: 'Panelisation',
    competitor: `${WEAK} CAMtastic (basic) or external`,
    kerf: `${GOOD} Panelize built in`,
  },

  // Libraries & vault
  {
    group: 'Libraries & data management',
    feature: 'Component libraries / vault',
    competitor: `${GOOD} Altium 365 Parts Library, vault, lifecycle mgmt`,
    kerf: `${WEAK} Library mgmt + distributors; smaller catalog`,
  },
  {
    group: 'Libraries & data management',
    feature: 'Importers',
    competitor: `${GOOD} OrCAD / Allegro / PADS / Eagle / P-CAD / Protel`,
    kerf: `${WEAK} KiCad-oriented import`,
  },

  // Ecosystem & SDK
  {
    group: 'Ecosystem & SDK',
    feature: 'Chat / LLM editing',
    competitor: `${GAP} None`,
    kerf: `${GOOD} Chat-native — edits circuit source per turn`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'BYO LLM',
    competitor: `${GAP} Not applicable`,
    kerf: `${GOOD} BYO API key; any Anthropic / OpenAI compatible model`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'Scripting',
    competitor: `${GOOD} DelphiScript / VBScript / JavaScript (in-process)`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'Community & docs',
    competitor: `${GOOD} Extensive, decades-old, professional support`,
    kerf: `${WEAK} Early-stage, growing`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'Jewelry & mechanical domains',
    competitor: `${GAP} EDA only`,
    kerf: `${GOOD} B-rep CAD, jewelry tooling, sheet metal in same workspace`,
  },
]

/* -------------------------------------------------------------------------
 * Page component
 * ---------------------------------------------------------------------- */
export default function AltiumPage() {
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
            aria-label="Kerf versus Altium Designer comparison"
          >
            Kerf vs Altium Designer
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Altium Designer is the commercial ECAD benchmark. Its push-and-shove
            situs router, ActiveRoute autorouter, multi-board project support,
            MCAD CoDesigner, and deep HDI / RF rule system represent 30+ years
            of production refinement. Kerf will not out-Altium Altium on
            interactive PCB layout polish — that is an honest statement. Where
            Kerf differs is in open-core licensing, multi-discipline breadth,
            integrated pre-compliance simulation, chat-native editing, and a
            dramatically lower cost of entry.
          </p>
        </div>

        {/* Where Altium is strong */}
        <Section title="Where Altium Designer is strong">
          <ul
            className="flex flex-col gap-3"
            aria-label="Altium Designer strengths"
          >
            <Li>
              <strong className="text-ink-100">
                Gold-standard interactive PCB routing.
              </strong>{' '}
              The situs push-and-shove engine with interactive length tuning,
              Xsignals constraint management, and diff-pair routing is the
              industry benchmark. No other tool matches its routing fluency for
              dense, high-layer-count boards.
            </Li>
            <Li>
              <strong className="text-ink-100">
                ActiveRoute guided autorouter.
              </strong>{' '}
              Guides routing interactively across complex topologies while
              respecting all design rules — a qualitatively different experience
              from traditional batch autorouters.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Advanced rules system.
              </strong>{' '}
              Altium's query-language rules engine is hierarchical, scoped, and
              covers dozens of rule categories. Expert teams write precise
              constraints that cover every edge of a complex design.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Multi-board projects.
              </strong>{' '}
              Altium's MB3D workspace lets you design and verify assemblies
              across multiple interconnected PCBs in one project — a capability
              Kerf does not have today.
            </Li>
            <Li>
              <strong className="text-ink-100">
                MCAD CoDesigner.
              </strong>{' '}
              A live, bidirectional co-design link to SOLIDWORKS, CREO,
              Inventor, and CATIA — geometry changes push and pull across the
              MCAD/ECAD boundary without exporting files.
            </Li>
            <Li>
              <strong className="text-ink-100">
                3D PCB editor depth.
              </strong>{' '}
              Native 3D PCB editing with STEP body import, component clearance
              checking, bend simulation for flex boards, and export to MCAD tools
              is mature and battle-tested.
            </Li>
            <Li>
              <strong className="text-ink-100">
                HDI and RF specialisation.
              </strong>{' '}
              Buried, blind, and micro-via rules, back-drill support, HDI
              stack-up management, and RF-specific layer rules are deep and
              production-proven.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Library and vault maturity.
              </strong>{' '}
              Altium 365 Parts Library, lifecycle management, and a vault
              system provide component data governance that enterprises rely on.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Signal integrity (HyperLynx / TouchStone).
              </strong>{' '}
              Deep SI integration via HyperLynx, IBIS, and Touchstone-grade
              S-parameter I/O is well-established and trusted by hardware teams
              doing multi-GHz work.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Broad schematic importers.
              </strong>{' '}
              OrCAD, Allegro, PADS, Eagle, P-CAD, and Protel import paths ease
              migration from legacy EDA toolchains.
            </Li>
          </ul>
        </Section>

        {/* Altium pain points */}
        <Section title="Common Altium pain points">
          <ul
            className="flex flex-col gap-3"
            aria-label="Common Altium Designer pain points"
          >
            <Li>
              <strong className="text-ink-100">Expensive subscription.</strong>{' '}
              Altium Designer seats cost approximately $8 000–$10 000+ USD per
              year, making it difficult to justify for solo engineers, startups,
              or teams with variable workload.
            </Li>
            <Li>
              <strong className="text-ink-100">Windows-only.</strong>{' '}
              The desktop application runs on Windows only. macOS and Linux
              engineers must run it under a VM or Parallels — a friction point
              for cross-platform teams.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Cloud collaboration sold separately.
              </strong>{' '}
              Altium 365 is a separate SaaS product layered on top of the
              desktop licence. Getting your team onto a shared, browser-
              accessible workspace requires an additional subscription.
            </Li>
            <Li>
              <strong className="text-ink-100">Steep learning curve.</strong>{' '}
              The advanced rules system, hierarchical schematic model, and
              project-structure conventions have a significant ramp-up time.
              Altium's own training courses are multi-day affairs.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Vendor lock-in risk.
              </strong>{' '}
              The proprietary .PrjPcb / .SchDoc / .PcbDoc file formats and
              the Altium-specific scripting environment create meaningful
              switching costs over time.
            </Li>
          </ul>
        </Section>

        {/* Where Kerf differs */}
        <Section title="Where Kerf differs">
          <ul
            className="flex flex-col gap-3"
            aria-label="Where Kerf differs from Altium Designer"
          >
            <Li>
              <strong className="text-ink-100">
                Open-core MIT licence and transparent pricing.
              </strong>{' '}
              The core is permissively MIT-licensed and available on GitHub.
              Local use is free; hosted credits are billed at cost with no
              $10 000/yr seat fee.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Multi-discipline in one workspace.
              </strong>{' '}
              B-rep mechanical CAD, jewelry tooling, sheet metal, and the full
              EDA stack coexist. ECAD/MCAD co-design happens without exporting
              files and switching applications.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Chat-native workflow and BYO LLM.
              </strong>{' '}
              Describe a routing constraint, net class change, or schematic
              edit in plain English; the model edits the design source directly,
              backed by live doc-search. Bring your own Anthropic or compatible
              API key — no Altium-controlled AI pipeline.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Integrated SI / EMC / PDN / thermal pre-compliance suite.
              </strong>{' '}
              <code className="text-kerf-300 font-mono text-xs">si_eye_wizard</code>,{' '}
              <code className="text-kerf-300 font-mono text-xs">pdn_wizard</code>,{' '}
              <code className="text-kerf-300 font-mono text-xs">emc_wizard</code>{' '}
              (FCC §15.109 + CISPR 32, 10 m-equivalent Class B),{' '}
              <code className="text-kerf-300 font-mono text-xs">thermal_board</code>, and{' '}
              <code className="text-kerf-300 font-mono text-xs">sim_corner</code>{' '}
              analysis all ship in-box — workflows Altium addresses partly via
              external HyperLynx or Altium 365 Simulation.
            </Li>
            <Li>
              <strong className="text-ink-100">
                kerf-imports QIF and IBIS readers.
              </strong>{' '}
              Native kerf-imports support for QIF (ISO 23952) metrology data and
              IBIS behavioural models means vendor component data integrates
              directly into the design flow.
            </Li>
            <Li>
              <strong className="text-ink-100">
                IPC-2581 + IPC-D-356A + IDF exports out of the box.
              </strong>{' '}
              Vendor-neutral fabrication interchange formats — no separate
              module or Altium 365 subscription required.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Cross-platform, browser + local binary.
              </strong>{' '}
              Runs in the browser (hosted SaaS) or as a single local binary on
              Windows, macOS, and Linux — no Windows-only constraint.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate both PCB and mechanical tasks from a Python script on your
              own machine over HTTP/JSON-RPC — the same interface the LLM uses
              internally.
            </Li>
          </ul>
        </Section>

        {/* Honest gaps */}
        <Section title="Honest gaps — where Kerf is behind today">
          <ul
            className="flex flex-col gap-3"
            aria-label="Areas where Kerf is behind Altium Designer today"
          >
            <Li>
              <strong className="text-ink-100">
                Interactive routing polish.
              </strong>{' '}
              Altium's situs push-and-shove engine, Xsignals, and ActiveRoute
              represent decades of refinement. Kerf's shove router is functional
              but will not feel as fluid for complex, high-density boards today.
            </Li>
            <Li>
              <strong className="text-ink-100">
                HDI / RF rule depth.
              </strong>{' '}
              Buried/blind/micro-via rules, back-drill support, and RF-specific
              layer constraints are deeper in Altium today. Kerf supports the
              via types but the rule-system coverage is narrower.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Multi-board project support.
              </strong>{' '}
              Altium's MB3D workspace is an established workflow with no
              equivalent in Kerf today.
            </Li>
            <Li>
              <strong className="text-ink-100">
                MCAD CoDesigner live link.
              </strong>{' '}
              Altium's bidirectional push/pull co-design with SOLIDWORKS, CREO,
              and Inventor is a mature, real-time bridge. Kerf's IDF export and
              STEP are one-way snapshots by comparison.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Library and vault governance.
              </strong>{' '}
              Altium 365 Parts Library lifecycle management and vault revision
              control are enterprise-grade. Kerf's library management is
              functional but smaller in catalog and narrower in governance tools.
            </Li>
            <Li>
              <strong className="text-ink-100">
                3D PCB editor depth.
              </strong>{' '}
              Altium's native 3D PCB editor supports STEP body import, component
              clearance checks, and flex-board bend simulation at a depth Kerf
              does not match yet.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Importer breadth.
              </strong>{' '}
              Altium imports OrCAD, Allegro, PADS, Eagle, P-CAD, and Protel
              files. Kerf's EDA import path is KiCad-oriented and narrower.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Community and professional support.
              </strong>{' '}
              Altium has decades of forum posts, videos, training courses, and
              certified resellers. Kerf's community is early-stage.
            </Li>
          </ul>
        </Section>

        {/* Side by side */}
        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Altium Designer" />
          <TableFooter />
        </Section>

        {/* Migration notes */}
        <Section title="Migration notes">
          <ul
            className="flex flex-col gap-3"
            aria-label="Migration notes from Altium Designer to Kerf"
          >
            <Li>
              <strong className="text-ink-100">
                Schematic and ERC map cleanly.
              </strong>{' '}
              Hierarchical schematics, net classes, ERC rules, and SPICE
              simulation workflows all have functional equivalents in Kerf.
              Schematic data can be exported to KiCad format (Altium{' '}
              <span aria-hidden="true">→</span> KiCad{' '}
              <span aria-hidden="true">→</span> Kerf import).
            </Li>
            <Li>
              <strong className="text-ink-100">
                Gerber / IPC fabrication outputs are compatible.
              </strong>{' '}
              Existing Gerber/Excellon, IPC-D-356A, IPC-2581, and IDF fab packs
              produced from Altium are structurally compatible with Kerf's
              export pipeline; this is the lowest-friction handoff path.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Interactive layout depth is the gap to expect.
              </strong>{' '}
              Teams doing dense HDI or RF boards will notice the routing
              experience difference immediately. Factor in ramp-up time if that
              is your primary workload.
            </Li>
            <Li>
              <strong className="text-ink-100">
                The integrated SI / EMC / PDN / thermal suite is the Kerf
                differentiator.
              </strong>{' '}
              If your Altium workflow involves hand-off to HyperLynx or external
              PDN / EMC tools, the kerf simulation pre-compliance suite
              (sim_corner / thermal_board / si_eye_wizard / pdn_wizard /
              emc_wizard) is likely to reduce that external tooling dependency.
            </Li>
            <Li>
              <strong className="text-ink-100">
                kerf-imports handles IBIS and QIF.
              </strong>{' '}
              If you use IBIS models for SI analysis or QIF for metrology
              feedback, both readers are available natively in kerf-imports —
              no conversion step required.
            </Li>
          </ul>
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
