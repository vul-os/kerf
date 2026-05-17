/**
 * /compare/civil3d — Kerf vs Autodesk Civil 3D
 *
 * Web-grounded (last reviewed 2026-05-17). Autodesk Civil 3D is the
 * industry-standard civil infrastructure design tool: corridor modelling
 * (roads/highways/rail), alignments + profiles + cross-sections, dynamic
 * TIN surfaces, pipe networks (gravity + pressure), parcels, point clouds,
 * survey data integration, and plan production with sheet sets — all inside
 * AutoCAD DWG. Available via the Autodesk AEC Collection (~US$4,150/yr).
 *
 * Kerf is NOT a Civil 3D replacement at production-civil-infrastructure scale.
 * Civil 3D owns corridor/alignment/profile depth and pipe-network breadth.
 * Kerf's civil-adjacent modules (kerf_cad_core.civil, geotech, surveying,
 * hydrology, earthworks, pavement, geodesy) are useful for analysis work but
 * do not approach Civil 3D's drafting or corridor depth.
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

/* Build the meta object inline — civil3d is not yet registered in
   compareMeta.js, so we construct the same shape manually. */
const BASE = 'https://kerf.sh'
const slug = 'civil3d'
const title = 'Kerf vs Civil 3D — civil infrastructure design compared'
const description =
  'Civil 3D is the industry-standard civil infrastructure design tool. ' +
  'See how Kerf’s open-core civil-adjacent modules honestly compare.'
const canonical = `${BASE}/compare/${slug}`
const ogImage = `${BASE}/og/compare-${slug}.png`
const meta = {
  title,
  description,
  canonical,
  ogImage,
  product: 'Civil 3D',
  slug,
  jsonLd: JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: title,
    description,
    url: canonical,
    image: ogImage,
    publisher: { '@type': 'Organization', name: 'Kerf', url: BASE },
  }),
}

const TABLE = [
  // Licensing & platform
  {
    group: 'Licensing & platform',
    feature: 'License',
    competitor: `${WEAK} Proprietary subscription`,
    kerf: `${GOOD} MIT open-core`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Cost',
    competitor: `${WEAK} AEC Collection ~US$4,150/yr (includes Civil 3D, Revit, etc.)`,
    kerf: `${GOOD} Free local; pay-as-you-go hosted`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Platform',
    competitor: `${WEAK} Windows-primary (Civil 3D is Windows-only)`,
    kerf: `${GOOD} Browser (hosted) + single-binary local (macOS/Linux/Windows)`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Vendor lock-in',
    competitor: `${WEAK} DWG-centric; Autodesk ecosystem dependency`,
    kerf: `${GOOD} Open formats; MIT licence`,
  },
  {
    group: 'Licensing & platform',
    feature: 'Maturity',
    competitor: `${GOOD} Decades of production use; industry-standard`,
    kerf: `${WEAK} Early-stage, < 2 yr public`,
  },

  // Civil infrastructure (core Civil 3D territory)
  {
    group: 'Civil infrastructure design',
    feature: 'Corridor modelling (roads / highways / rail)',
    competitor: `${GOOD} Industry-standard — full corridor assemblies, subassemblies, targets`,
    kerf: `${GAP} Not available`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'Alignments + profiles + cross-sections',
    competitor: `${GOOD} Full alignment/profile/section design with design criteria`,
    kerf: `${GAP} Not available`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'Dynamic TIN surfaces (grading / toposolids)',
    competitor: `${GOOD} Composite TINs, grading objects, dynamic surface comparison`,
    kerf: `${WEAK} Basic earthwork / site grading; no TIN surface dynamics`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'Pipe networks — gravity (storm + sanitary)',
    competitor: `${GOOD} Full gravity pipe network design, sizing, and analysis`,
    kerf: `${GAP} Not available`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'Pressure pipe networks',
    competitor: `${GOOD} Pressure pipe parts, fittings, and plan production`,
    kerf: `${GAP} Not available`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'Parcels + lot layout',
    competitor: `${GOOD} Parcel creation, sizing, and report generation`,
    kerf: `${GAP} Not available`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'Point clouds',
    competitor: `${GOOD} ReCap integration; point-cloud to surface workflows`,
    kerf: `${GAP} Not available`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'Survey data integration',
    competitor: `${GOOD} Survey database, figures, least-squares adjustment`,
    kerf: `${WEAK} Surveying module (Vincenty-validated geodesy, basic reduction); no survey DB`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'Plan production + sheet sets',
    competitor: `${GOOD} Automated plan and profile sheets, plan production tools`,
    kerf: `${WEAK} Multi-sheet drawings (general); no civil plan production automation`,
  },
  {
    group: 'Civil infrastructure design',
    feature: 'AutoCAD DWG native',
    competitor: `${GOOD} Built on AutoCAD; full DWG authoring`,
    kerf: `${WEAK} DXF import/export; no DWG authoring`,
  },

  // Civil-adjacent analysis (Kerf's territory)
  {
    group: 'Civil-adjacent analysis',
    feature: 'Hydrology (TR-55 / rational method)',
    competitor: `${WEAK} Not a hydrology analysis tool (exports to HEC-RAS / Civil Storm)`,
    kerf: `${GOOD} kerf_cad_core.hydrology — TR-55 runoff, time of concentration`,
  },
  {
    group: 'Civil-adjacent analysis',
    feature: 'Geotechnical (Coulomb / bearing)',
    competitor: `${WEAK} Not a geotech analysis tool`,
    kerf: `${GOOD} kerf_cad_core.geotech — Coulomb earth pressure, bearing capacity`,
  },
  {
    group: 'Civil-adjacent analysis',
    feature: 'Pavement design (AASHTO-aware)',
    competitor: `${WEAK} Not a standalone pavement design tool`,
    kerf: `${WEAK} kerf_cad_core.pavement — AASHTO-aware in roadmap; partial today`,
  },
  {
    group: 'Civil-adjacent analysis',
    feature: 'Geodesy (Vincenty / datum transforms)',
    competitor: `${WEAK} Survey-level coordinate geometry; not a geodesy engine`,
    kerf: `${GOOD} kerf_cad_core.geodesy — Vincenty-validated, citable reference validation`,
  },
  {
    group: 'Civil-adjacent analysis',
    feature: 'Wind load (ASCE 7)',
    competitor: `${GAP} Not applicable`,
    kerf: `${GOOD} kerf_cad_core.windload — ASCE 7 wind pressure`,
  },
  {
    group: 'Civil-adjacent analysis',
    feature: 'Seismic (ASCE 7)',
    competitor: `${GAP} Not applicable`,
    kerf: `${GOOD} kerf_cad_core.seismic — ASCE 7 spectral response`,
  },
  {
    group: 'Civil-adjacent analysis',
    feature: 'Earthworks / cut-fill',
    competitor: `${GOOD} Full earthwork volume calculation from corridor and surfaces`,
    kerf: `${WEAK} Basic earthworks module; no corridor-driven volumes`,
  },

  // Cross-domain
  {
    group: 'Cross-domain',
    feature: 'Mechanical B-rep CAD',
    competitor: `${WEAK} AutoCAD 3D solids (not parametric B-rep)`,
    kerf: `${GOOD} OCCT feature tree, sketcher, CAM`,
  },
  {
    group: 'Cross-domain',
    feature: 'Electronics (same tool)',
    competitor: `${GAP} Separate tool required`,
    kerf: `${GOOD} Full EDA stack in same workspace`,
  },
  {
    group: 'Cross-domain',
    feature: 'BIM coordination',
    competitor: `${WEAK} Via Navisworks / Autodesk Docs; not native Civil 3D`,
    kerf: `${WEAK} IFC Tier 2 import, BIM primitives; not a BIM coordination platform`,
  },

  // Ecosystem & SDK
  {
    group: 'Ecosystem & SDK',
    feature: 'Chat / LLM editing',
    competitor: `${GAP} None`,
    kerf: `${GOOD} Chat-native — edits source per turn, doc-search backed`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'Scripting / automation',
    competitor: `${GOOD} Civil 3D API (.NET / COM / Python via pyautocad)`,
    kerf: `${GOOD} kerf-sdk on PyPI — HTTP/JSON-RPC`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'AEC Collection ecosystem',
    competitor: `${GOOD} Civil 3D + Revit + InfraWorks + Navisworks in one bundle`,
    kerf: `${WEAK} Multi-domain, but no civil infrastructure depth`,
  },
  {
    group: 'Ecosystem & SDK',
    feature: 'Community & training',
    competitor: `${GOOD} Large, certified, decades of training resources`,
    kerf: `${WEAK} Early-stage, growing`,
  },
]

export default function Civil3dPage() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <HeadMeta meta={meta} />
      <Header />

      <main
        className="mx-auto max-w-4xl px-6 pt-12 pb-20"
        aria-label="Kerf vs Civil 3D comparison"
      >
        <Breadcrumb />

        <div className="mb-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2">
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            Kerf vs Civil&nbsp;3D
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Autodesk Civil 3D is the industry-standard civil infrastructure
            design platform: corridor modelling for roads, highways, and rail;
            full alignment + profile + cross-section design; dynamic TIN
            surfaces; gravity and pressure pipe networks; parcels; point
            clouds; survey integration; and automated plan-production sheets
            — all inside AutoCAD DWG, available via the Autodesk AEC
            Collection (~US$4,150/yr, Windows-primary). Kerf has
            civil-adjacent analysis modules (hydrology, geotech, surveying,
            geodesy, pavement, earthworks) but{' '}
            <strong className="text-ink-200">
              is not a Civil 3D replacement at production-civil-infrastructure
              scale
            </strong>
            . This page says so plainly.
          </p>
        </div>

        <Section title="Where Civil 3D is strong">
          <ul
            className="flex flex-col gap-3"
            aria-label="Civil 3D strengths"
          >
            <Li>
              <strong className="text-ink-100">
                Industry-standard corridor modelling.
              </strong>{' '}
              Civil 3D&rsquo;s corridor assemblies and subassemblies are the
              production workflow for road, highway, and rail design: dynamic
              cross-sections tied to alignment and profile geometry, automated
              earthwork volumes, and parametric target rules. Kerf has no
              corridor capability.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Alignments, profiles, and cross-sections.
              </strong>{' '}
              Horizontal alignments with design criteria, vertical profiles
              with sight-distance checking, and section sheets with automated
              labelling form the backbone of civil design. Kerf does not offer
              this workflow.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Dynamic TIN surfaces and grading.
              </strong>{' '}
              Composite TINs built from survey data, breaklines, and grading
              objects update dynamically when upstream geometry changes. Cut
              and fill volumes derive from surface comparison, not manual
              calculation. Kerf&rsquo;s earthwork module is basic by
              comparison.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Pipe networks — gravity and pressure.
              </strong>{' '}
              Full storm drainage, sanitary sewer, and pressure pipe design
              with part families, structure sizing, and interference checking
              — multiple discipline networks Kerf does not address.
            </Li>
            <Li>
              <strong className="text-ink-100">Parcels and lot layout.</strong>{' '}
              Automated parcel creation, lot sizing, ROW labelling, and area
              report generation are core land-development deliverables built
              into Civil 3D. Kerf has no parcel concept.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Point clouds and ReCap integration.
              </strong>{' '}
              Civil 3D ingests ReCap point clouds directly for existing-ground
              surface creation and design-check workflows — essential for
              survey-based projects. Kerf does not support point clouds.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Survey database and least-squares adjustment.
              </strong>{' '}
              Civil 3D manages field observations, figures, traverse
              closures, and least-squares network adjustment in a survey
              database — a full survey-reduction workflow. Kerf&rsquo;s
              surveying module covers geodetic computations (Vincenty,
              datum transforms) but not a field-observation survey database.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Automated plan production with sheet sets.
              </strong>{' '}
              Civil 3D generates plan-and-profile sheets, cross-section
              sheets, and quantity reports automatically from the design model
              — a core deliverable workflow for civil engineers. Kerf produces
              general multi-sheet drawings but has no civil plan-production
              automation.
            </Li>
            <Li>
              <strong className="text-ink-100">
                AutoCAD DWG native and AEC Collection bundle.
              </strong>{' '}
              Civil 3D runs inside AutoCAD, producing DWG files that the
              entire civil and survey industry reads. The AEC Collection
              bundles Civil 3D, Revit, InfraWorks, Navisworks, and more under
              one subscription — a well-integrated infrastructure design stack
              with decades of production history.
            </Li>
          </ul>
        </Section>

        <Section title="Where Kerf has relevant capability">
          <ul
            className="flex flex-col gap-3"
            aria-label="Kerf civil-adjacent strengths"
          >
            <Li>
              <strong className="text-ink-100">
                Hydrology analysis (TR-55).
              </strong>{' '}
              The <span className="font-mono text-ink-200">kerf_cad_core.hydrology</span>{' '}
              module implements TR-55 runoff curve numbers and time-of-concentration
              methods with citable reference validation. Civil 3D does not perform
              hydrological analysis natively — it exports to HEC-RAS, Civil Storm,
              or similar tools. For preliminary hydrology on smaller catchments,
              Kerf&rsquo;s module provides audit-friendly calculations in the same
              workspace.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Geotechnical analysis (Coulomb, bearing capacity).
              </strong>{' '}
              <span className="font-mono text-ink-200">kerf_cad_core.geotech</span>{' '}
              covers Coulomb lateral earth pressure, bearing capacity (Terzaghi /
              Meyerhof), and slope stability checks — calculations Civil 3D does
              not provide. For civil engineers needing geotech figures alongside
              their design drawings, Kerf keeps the workflow in one tool.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Geodesy and survey computations.
              </strong>{' '}
              <span className="font-mono text-ink-200">kerf_cad_core.geodesy</span>{' '}
              and the surveying module offer Vincenty-validated geodesic distance
              and bearing, datum transforms, and coordinate reductions — with
              each formula traceable to a published reference. This complements
              Civil 3D&rsquo;s survey database rather than replacing it.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Wind and seismic load calculations (ASCE 7).
              </strong>{' '}
              For structures that are part of a civil project — bridges,
              retaining walls, sign structures — Kerf&rsquo;s ASCE 7 wind and
              seismic modules provide code-referenced load calculations in the
              same workspace.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Open-core, cross-platform, no per-seat subscription.
              </strong>{' '}
              MIT-licensed with a free local binary (brew/curl) or a
              pay-as-you-go hosted option — no Autodesk account, no
              Windows-only requirement. Civil engineers who want quick analysis
              checks on macOS or Linux will not encounter a licensing wall.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Multi-discipline workspace.
              </strong>{' '}
              Civil projects increasingly involve mechanical structures,
              electronic instrumentation, and sensor hardware. Kerf&rsquo;s
              integrated mechanical B-rep CAD, EDA stack, and BOM mean those
              components live in the same workspace — without an AEC Collection
              seat.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe a calculation scenario, ask for a sensitivity run on
              runoff parameters, or generate a geotech summary in plain
              language; the LLM edits the analysis source directly, backed by
              live doc-search so it cites real module API rather than inventing
              it.
            </Li>
          </ul>
        </Section>

        <Section title="Honest gaps — where Civil 3D is the right tool">
          <ul
            className="flex flex-col gap-3"
            aria-label="Honest Kerf gaps vs Civil 3D"
          >
            <Li>
              <strong className="text-ink-100">
                Kerf is not a Civil 3D replacement.
              </strong>{' '}
              For production civil infrastructure work — roads, highways, rail,
              subdivision land development, municipal drainage — Civil 3D&rsquo;s
              corridor + alignment + profile depth, dynamic TIN surfaces, and
              pipe network breadth are the appropriate choice. Kerf does not
              have these capabilities and they are not on a near-term roadmap.
            </Li>
            <Li>
              <strong className="text-ink-100">
                No corridor or alignment tooling.
              </strong>{' '}
              Civil 3D&rsquo;s corridor assemblies, subassemblies, alignment
              design criteria, profile grade control, and section sheet
              automation are absent from Kerf entirely.
            </Li>
            <Li>
              <strong className="text-ink-100">No pipe network design.</strong>{' '}
              Storm drain, sanitary sewer, and pressure pipe design with Civil
              3D&rsquo;s part families, structure-sizing rules, and interference
              checking are not in Kerf.
            </Li>
            <Li>
              <strong className="text-ink-100">
                No dynamic TIN surfaces or grading.
              </strong>{' '}
              Civil 3D&rsquo;s composite TIN surfaces, grading objects, and
              dynamic earthwork volumes derived from surface comparison are
              unique to the Civil 3D data model. Kerf&rsquo;s earthwork module
              is analytical, not a live-surface modeller.
            </Li>
            <Li>
              <strong className="text-ink-100">No DWG authoring.</strong>{' '}
              The civil and survey industry reads DWG. Civil 3D produces
              AutoCAD DWG natively; Kerf can import/export DXF but does not
              produce DWG and does not carry AutoCAD object enablers.
            </Li>
            <Li>
              <strong className="text-ink-100">
                No point-cloud or survey-database workflow.
              </strong>{' '}
              Point cloud ingestion (ReCap), breakline extraction, and a
              field-observation survey database with traverse closure and
              least-squares adjustment are not in Kerf.
            </Li>
            <Li>
              <strong className="text-ink-100">
                Landscape and site design: Vectorworks Landmark competes more
                directly with Civil 3D here.
              </strong>{' '}
              For landscape architecture and detailed site design, Vectorworks
              Landmark is often considered a stronger alternative to Civil 3D
              than either Kerf or other infrastructure tools — worth noting for
              users evaluating the full market.
            </Li>
          </ul>
        </Section>

        <Section title="Migration notes for Civil 3D users">
          <ul
            className="flex flex-col gap-3"
            aria-label="Migration notes for Civil 3D users considering Kerf"
          >
            <Li>
              <strong className="text-ink-100">
                Kerf complements rather than replaces Civil 3D.
              </strong>{' '}
              The most productive pattern for a Civil 3D user is to keep
              Civil 3D for corridor design, pipe networks, plan production,
              and DWG deliverables, and use Kerf&rsquo;s civil-adjacent modules
              (hydrology, geotech, geodesy, pavement, seismic, wind) for
              analysis work that Civil 3D hands off to external tools. A single
              Kerf workspace can hold the TR-55 hydrology run, the Coulomb
              retaining-wall check, and the structural-element CAD alongside
              each other, with results auditable against published references.
            </Li>
            <Li>
              <strong className="text-ink-100">
                What will feel familiar.
              </strong>{' '}
              Multi-sheet drawing output, BOM/quantity reporting, and
              Python-based scripting (kerf-sdk over HTTP/JSON-RPC) will be
              recognisable workflows. The coordinate and units approach
              (metres/feet, geodetic CRS) is consistent with civil convention.
            </Li>
            <Li>
              <strong className="text-ink-100">
                What is structurally different.
              </strong>{' '}
              Kerf&rsquo;s data model is a parametric B-rep feature tree, not
              a civil object model (alignments, profiles, corridors,
              parcels). There is no concept of a horizontal geometry or
              superelevation table; the &ldquo;model&rdquo; is a solid/surface
              feature tree that happens to include civil-engineering calculation
              modules. Think of it as engineering calculation + general CAD,
              not civil drafting.
            </Li>
            <Li>
              <strong className="text-ink-100">
                What to expect on interoperability.
              </strong>{' '}
              DXF export from Civil 3D can bring 2D geometry into Kerf for
              reference, but Civil 3D&rsquo;s intelligent objects (corridors,
              surfaces, pipe networks) lose their intelligence when round-
              tripping through DXF. A LandXML export of alignments and
              surfaces from Civil 3D is a better handoff format for analysis
              work; Kerf&rsquo;s LandXML import is on the civil roadmap but
              not yet shipped.
            </Li>
          </ul>
        </Section>

        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Civil 3D" />
          <TableFooter />
        </Section>

        <FairnessNote />
        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
