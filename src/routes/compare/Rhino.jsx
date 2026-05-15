/**
 * /compare/rhino — Kerf vs Rhino (RhinoGold / Matrix)
 *
 * Rhino 3D with the RhinoGold or Matrix plugin is the professional reference
 * for NURBS-based jewelry and freeform industrial design. Kerf has a solid
 * jewelry foundation (gemstones v2, settings v3/v4, ring v4) but Rhino's
 * NURBS engine and parametric surface tooling are more mature.
 */
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { makeCompareMeta } from './compareMeta.js'
import { Section, Li, CompareTable, TableFooter, CTAStrip } from './Freecad.jsx'

const meta = makeCompareMeta('rhino')

const TABLE = [
  { feature: 'License / cost',              competitor: 'Proprietary; ~$995 + plugin cost',    kerf: 'MIT open-core; free local or hosted' },
  { feature: 'NURBS surface modelling',     competitor: '✅ Class-leading — Rhino kernel',      kerf: '⚠️ NURBS Phase 4 (trim-by-curve, G3 combs) — early stage' },
  { feature: 'Parametric solids (B-rep)',   competitor: '⚠️ Via Grasshopper or plugins',       kerf: '✅ Full OCCT B-rep feature tree — Pad/Pocket/Revolve/Fillet/etc.' },
  { feature: 'Jewelry: ring design',        competitor: '✅ RhinoGold / Matrix ring WBs',       kerf: '✅ Ring v4 + 31-template library' },
  { feature: 'Jewelry: gemstone settings',  competitor: '✅ Mature settings libraries',         kerf: '✅ Settings v3/v4 + gem-seat v2 + 30-cut gemstones v2' },
  { feature: 'Jewelry: chain design',       competitor: '✅ Dedicated chain tools',             kerf: '✅ Chain v2 + findings + decorative' },
  { feature: 'Jewelry: casting export',     competitor: '✅ STL / WAX mill paths',              kerf: '✅ Casting export' },
  { feature: 'Grasshopper visual scripting',competitor: '✅ Industry standard',                 kerf: '❌ Not available' },
  { feature: 'RhinoCAM / CAM',              competitor: '✅ Via RhinoCAM plugin',               kerf: '✅ 5-axis CAM 3+2, 3-axis CAM + tool DB built in' },
  { feature: 'PBR materials / rendering',   competitor: '✅ Raytraced + V-Ray/Enscape etc.',    kerf: '✅ PBR materials for jewelry; general rendering roadmap' },
  { feature: 'Chat / LLM editing',          competitor: '❌',                                   kerf: '✅ Chat-native — model edits source per turn' },
  { feature: 'Electronics integration',     competitor: '❌ Separate tool required',            kerf: '✅ Full EDA stack in same workspace' },
  { feature: 'GD&T / drawings',             competitor: '⚠️ Via Layout + annotation plugins',  kerf: '✅ TechDraw drawings + full ASME Y14.5 GD&T' },
  { feature: 'Python scripting',            competitor: '✅ rhinoscriptsyntax / RhinoCommon',   kerf: '✅ kerf-sdk on PyPI — HTTP/JSON-RPC' },
  { feature: 'Hosted / cloud option',       competitor: '❌ Desktop only',                     kerf: '✅ Hosted SaaS + single-binary local install' },
  { feature: 'IFC / arch workflows',        competitor: '⚠️ Via VisualARQ plugin',             kerf: '✅ IFC Tier 2 import + structural sketcher' },
]

export default function RhinoPage() {
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
            Kerf vs Rhino
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            Rhino 3D with RhinoGold or Matrix is the professional reference for
            jewelry CAD and freeform NURBS design. Kerf has a strong jewelry
            foundation — ring v4, gemstones v2, chain v2, 31 templates — but
            Rhino's NURBS engine and Grasshopper ecosystem are significantly more
            mature. This is an honest look at where each tool stands today.
          </p>
        </div>

        <Section title="Where Rhino shines">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">Class-leading NURBS engine.</strong>{' '}
              Rhino's kernel is the industry reference for freeform surface
              modelling — used in jewellery, industrial design, naval architecture,
              and aerospace. Its continuity tools (G0–G3) are production-proven.
            </Li>
            <Li>
              <strong className="text-ink-100">Grasshopper parametric scripting.</strong>{' '}
              Grasshopper is the gold standard for visual parametric scripting in
              3D. Its plugin ecosystem (thousands of components) covers everything
              from structural optimisation to pattern generation.
            </Li>
            <Li>
              <strong className="text-ink-100">Mature jewelry workbenches (RhinoGold / Matrix).</strong>{' '}
              Years of refinement in real goldsmith workshops. Sizing, stone
              setting, wax milling paths, and supplier catalogs are deeply
              integrated.
            </Li>
            <Li>
              <strong className="text-ink-100">Advanced rendering ecosystem.</strong>{' '}
              Raytraced viewport plus support for V-Ray, Enscape, and KeyShot.
              Photorealistic jewelry renders with accurate caustics and gem
              dispersion.
            </Li>
            <Li>
              <strong className="text-ink-100">RhinoCommon / Python scripting.</strong>{' '}
              rhinoscriptsyntax and RhinoCommon give access to every geometric
              operation in the kernel — extremely powerful for automation.
            </Li>
          </ul>
        </Section>

        <Section title="Where Kerf is different">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">MIT open-core, free to use.</strong>{' '}
              Rhino costs ~$995 per seat and RhinoGold/Matrix add hundreds more.
              Kerf's full jewelry workflow — ring v4, settings v3/v4, gemstones
              v2, chain v2, 31 templates — is MIT-licensed and free locally.
            </Li>
            <Li>
              <strong className="text-ink-100">Chat-native workflow.</strong>{' '}
              Describe what you want in plain language; the LLM edits the feature
              tree or JSCAD source with doc-search backing. No visual programming
              required.
            </Li>
            <Li>
              <strong className="text-ink-100">Integrated electronics and drawings.</strong>{' '}
              Full EDA (schematic, routing, DRC, Gerber), TechDraw drawings, and
              GD&T are in the same workspace — disciplines Rhino requires separate
              tools for.
            </Li>
            <Li>
              <strong className="text-ink-100">Hosted option, no install required.</strong>{' '}
              Sign up and design in the browser; or install a 32 MB binary locally.
              No macOS/Windows-only installer, no licence dongle.
            </Li>
            <Li>
              <strong className="text-ink-100">kerf-sdk Python scripting.</strong>{' '}
              Automate jewelry templates and feature trees from any Python script
              via HTTP/JSON-RPC on your own machine.
            </Li>
          </ul>
        </Section>

        <Section title="Honest gaps">
          <ul className="flex flex-col gap-3">
            <Li>
              <strong className="text-ink-100">NURBS surfacing is early in Kerf.</strong>{' '}
              NURBS Phase 4 (trim-by-curve, G3 combs) is functional but nowhere
              near Rhino's depth. Complex freeform surfaces — blendSrf, networkSrf,
              sweep2 — are on the roadmap but not yet shipped.
            </Li>
            <Li>
              <strong className="text-ink-100">No Grasshopper equivalent.</strong>{' '}
              Kerf has no visual parametric scripting environment. The chat and
              Python SDK fill some of that space but not all of it.
            </Li>
            <Li>
              <strong className="text-ink-100">Rendering is basic today.</strong>{' '}
              Kerf has PBR materials for jewelry, but caustics, dispersion, and
              photorealistic gem renders require external tools or renderers that
              Rhino already integrates.
            </Li>
            <Li>
              <strong className="text-ink-100">Jewelry plugin depth.</strong>{' '}
              RhinoGold and Matrix have years of goldsmith-driven UX refinements —
              supplier catalogues, wax path generation, sizing bars — that Kerf
              is still building toward.
            </Li>
          </ul>
        </Section>

        <Section title="Side by side">
          <CompareTable rows={TABLE} competitor="Rhino" />
          <TableFooter />
        </Section>

        <CTAStrip />
      </main>

      <Footer />
    </div>
  )
}
