/**
 * /compare — hub page linking to each tool comparison.
 *
 * Five cards: FreeCAD · KiCad · Rhino · Revit · Fusion 360
 * No raster assets; inline SVG iconography via Lucide. Shares the same
 * prominent fairness note as every comparison page.
 */
import { Link } from 'react-router-dom'
import { ArrowRight, Code2, CircuitBoard, Gem, Building2, Cloud } from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { FairnessNote } from './Freecad.jsx'

const CARDS = [
  {
    slug: 'freecad',
    icon: Code2,
    label: 'FreeCAD',
    tagline: 'Open-source parametric B-rep modeller',
    blurb:
      'FreeCAD 1.0 is a mature, LGPL, desktop parametric CAD package with a built-in Assembly workbench, FEM, and a decade-old workbench community. We compare it honestly against Kerf.',
    accent: 'cyan-edge',
  },
  {
    slug: 'kicad',
    icon: CircuitBoard,
    label: 'KiCad',
    tagline: 'Open-source EDA suite',
    blurb:
      "KiCad 10 (2026) is a deep, free EDA suite with native IPC-2581/ODB++ and a huge library. See where it leads and where Kerf's unified electronics + mechanical workspace differs.",
    accent: 'magenta-edge',
  },
  {
    slug: 'rhino',
    icon: Gem,
    label: 'Rhino',
    tagline: 'NURBS & jewelry CAD (MatrixGold / RhinoGold)',
    blurb:
      'Rhino 8 with MatrixGold / RhinoGold is the professional reference for NURBS surfacing and jewelry. Honest gaps and real capabilities on both sides.',
    accent: 'kerf-300',
  },
  {
    slug: 'revit',
    icon: Building2,
    label: 'Revit',
    tagline: 'Industry-standard BIM platform',
    blurb:
      "Revit is Autodesk's dominant BIM platform for AEC, with full MEP and family authoring. We compare its depth with Kerf's lighter, IFC-capable open-core workspace.",
    accent: 'cyan-edge',
  },
  {
    slug: 'fusion',
    icon: Cloud,
    label: 'Fusion 360',
    tagline: 'Cloud-connected mechanical CAD',
    blurb:
      "Fusion 360 pioneered cloud-connected parametric CAD with CAM, FEM, and generative design. See where it leads and where Kerf's open-core, chat-driven approach differs.",
    accent: 'magenta-edge',
  },
]

function CompareCard({ slug, icon: Icon, label, tagline, blurb }) {
  return (
    <Link
      to={`/compare/${slug}`}
      className="group relative flex flex-col rounded-2xl border border-ink-800 bg-ink-900/40 p-5 sm:p-6 hover:border-ink-700 hover:bg-ink-900/70 transition-colors"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <span className="grid place-items-center w-9 h-9 rounded-lg bg-kerf-300/10 border border-kerf-300/30 text-kerf-300 shrink-0">
            <Icon size={16} />
          </span>
          <div>
            <h2 className="font-display text-base font-semibold tracking-tight text-ink-100">
              Kerf vs {label}
            </h2>
            <p className="text-xs text-ink-400 font-mono mt-0.5">{tagline}</p>
          </div>
        </div>
        <ArrowRight
          size={15}
          className="text-ink-500 group-hover:text-kerf-300 group-hover:translate-x-0.5 transition-all shrink-0 mt-1"
        />
      </div>
      <p className="text-sm text-ink-300 leading-relaxed">{blurb}</p>
    </Link>
  )
}

export default function CompareHub() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />

      <main className="mx-auto max-w-4xl px-6 pt-14 pb-20">
        {/* Hero */}
        <div className="mb-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2">
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            How does Kerf compare?
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            These tools are genuinely excellent — many are decades old, deeply
            validated, and free or affordable. Kerf is young by comparison.
            These pages credit each competitor's real strengths first and
            generously, state Kerf's gaps without spin, and use a comprehensive
            side-by-side table where the competitor often wins. The aim is an
            honest decision aid, not marketing.
          </p>
        </div>

        {/* Cards grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {CARDS.map((card) => (
            <CompareCard key={card.slug} {...card} />
          ))}
        </div>

        {/* Fairness footer — same component used on every comparison page */}
        <FairnessNote />
      </main>

      <Footer />
    </div>
  )
}
