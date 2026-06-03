/**
 * /tools — Domain-panel landing page.
 *
 * 3-column card grid linking to every shipped specialist panel:
 *   Optics Design, Geometry Inspector, Structural / Arch, Manufacturing,
 *   GD&T, FEM Simulation, and the FeatureView (NURBS + CAM + SubD).
 *
 * Palette: ink-* / kerf-* / cyan-edge / magenta-edge.
 * Tailwind only. Mobile-first (1 → 2 → 3 col). No raster assets.
 */
import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Eye,
  ScanLine,
  Building2,
  Factory,
  ShieldCheck,
  Activity,
  Layers,
  ArrowRight,
  Telescope,
  Cpu,
  FileText,
} from 'lucide-react'
import Header from '../components/Header.jsx'
import Footer from '../components/Footer.jsx'
import Button from '../components/Button.jsx'

/* -------------------------------------------------------------------------- */
/* SEO                                                                         */
/* -------------------------------------------------------------------------- */

function setMeta(name, content) {
  let el = document.querySelector(`meta[name="${name}"]`)
  if (!el) { el = document.createElement('meta'); el.setAttribute('name', name); document.head.appendChild(el) }
  el.setAttribute('content', content)
}
function setProp(prop, content) {
  let el = document.querySelector(`meta[property="${prop}"]`)
  if (!el) { el = document.createElement('meta'); el.setAttribute('property', prop); document.head.appendChild(el) }
  el.setAttribute('content', content)
}

const META = {
  title: 'Engineering tool panels — Kerf',
  description: 'Dedicated solver panels for optics, B-rep inspection, structural analysis, mold & electronics manufacturing, GD&T, FEM simulation and more.',
  canonicalUrl: 'https://kerf.sh/tools',
  ogImage: 'https://kerf.sh/og/tools.png',
}

/* -------------------------------------------------------------------------- */
/* Panel data                                                                  */
/* -------------------------------------------------------------------------- */

const PANELS = [
  {
    slug: 'drawings',
    name: 'Engineering Drawings',
    Icon: FileText,
    accent: 'cyan',
    route: '/drawings',
    toolCount: 8,
    blurb:
      'HLR auto-views (ISO 128-30), ISO 129-1:2018 auto-dim, measurement chains, oblique/silhouette projections, inspection reports, and PDF/DXF/SVG export — 8 drawing tools.',
  },
  {
    slug: 'optics',
    name: 'Optics Design',
    Icon: Telescope,
    accent: 'cyan',
    route: '/optics',
    toolCount: 45,
    blurb:
      'Sequential ray tracing, lens aberration analysis, MTF/PSF computation, pupil & field analysis — 45 geometric optics tools.',
  },
  {
    slug: 'inspect',
    name: 'Geometry Inspector',
    Icon: ScanLine,
    accent: 'kerf',
    route: '/inspect',
    toolCount: 28,
    blurb:
      'B-rep healing, manifold validation, feature recognition, wall-thickness analysis and boolean ops — 28 solid-modelling tools.',
  },
  {
    slug: 'structural',
    name: 'Structural / Arch',
    Icon: Building2,
    accent: 'kerf',
    route: '/structural',
    toolCount: 24,
    blurb:
      'Beam & slab sizing, wind lateral loads, steel connections, shear walls, footings, and stair geometry — 24 structural solvers.',
  },
  {
    slug: 'mfg',
    name: 'Manufacturing',
    Icon: Factory,
    accent: 'magenta',
    route: '/mfg',
    toolCount: 39,
    blurb:
      'Injection mold flow, cooling, ejection, plus PCB power, signal integrity, thermal and RF tools — 21 mold + 18 electronics tools.',
  },
  {
    slug: 'gdt',
    name: 'GD&T',
    Icon: ShieldCheck,
    accent: 'cyan',
    route: '/gdt',
    toolCount: 9,
    blurb:
      'ASME Y14.5-2018 runout checks, composite position, datum reference frames, and dimension-chain tolerance analysis — 9 GDT tools.',
  },
  {
    slug: 'simulation',
    name: 'FEM Simulation',
    Icon: Activity,
    accent: 'kerf',
    route: '/simulation',
    toolCount: 20,
    blurb:
      'Linear static, modal, buckling, fatigue, vibration PSD, and CFD solvers with mesh upload and result visualisation — 20+ FEM tools.',
  },
  {
    slug: 'features',
    name: 'Feature View',
    Icon: Layers,
    accent: 'magenta',
    route: '/projects',
    toolCount: 80,
    blurb:
      'NURBS surfacing, Class-A G2/G3 blends, 5-axis CAM, SubD authoring, and full parametric feature tree inside the editor — 80+ tools.',
    cta: 'Open editor',
  },
  {
    slug: 'configurator',
    name: 'PLM Configurator',
    Icon: Cpu,
    accent: 'kerf',
    route: '/configurator',
    toolCount: 6,
    blurb:
      'Variant BOM configurator — rule-driven option selection, BOM diff, part-number generation, and costing rollup for product families.',
  },
  {
    slug: 'sysml-trace',
    name: 'SysML Traceability',
    Icon: Activity,
    accent: 'cyan',
    route: '/sysml-trace',
    toolCount: 4,
    blurb:
      'Requirement-to-test traceability matrix, SysML block diagram import, coverage gap analysis, and NASA-style verification cross-reference.',
  },
  {
    slug: 'pathtracer',
    name: 'WebGPU Path Tracer',
    Icon: Eye,
    accent: 'magenta',
    route: '/pathtracer',
    toolCount: 1,
    blurb:
      'Spectral WebGPU path tracer — physically-based rendering directly in the browser. HDR environment maps, glass refraction, and subsurface scattering (preview).',
  },
]

/* -------------------------------------------------------------------------- */
/* Accent helpers                                                               */
/* -------------------------------------------------------------------------- */

const ACCENT_BORDER = {
  cyan: 'border-cyan-500/30 hover:border-cyan-500/60',
  kerf: 'border-kerf-500/30 hover:border-kerf-500/60',
  magenta: 'border-pink-500/30 hover:border-pink-500/60',
}
const ACCENT_ICON_BG = {
  cyan: 'bg-cyan-500/10 text-cyan-400',
  kerf: 'bg-kerf-500/10 text-kerf-300',
  magenta: 'bg-pink-500/10 text-pink-400',
}
const ACCENT_BADGE = {
  cyan: 'bg-cyan-500/10 text-cyan-400',
  kerf: 'bg-kerf-500/10 text-kerf-300',
  magenta: 'bg-pink-500/10 text-pink-400',
}

/* -------------------------------------------------------------------------- */
/* PanelCard                                                                    */
/* -------------------------------------------------------------------------- */

function PanelCard({ panel }) {
  const { name, Icon, accent, route, toolCount, blurb, cta = 'Open' } = panel
  return (
    <div
      className={[
        'group relative flex flex-col gap-4 rounded-xl border bg-ink-900/60 p-6',
        'transition-all duration-200 hover:bg-ink-800/60',
        ACCENT_BORDER[accent],
      ].join(' ')}
    >
      {/* Icon + badge row */}
      <div className="flex items-start justify-between gap-3">
        <div className={['flex items-center justify-center w-10 h-10 rounded-lg shrink-0', ACCENT_ICON_BG[accent]].join(' ')}>
          <Icon size={20} strokeWidth={1.5} />
        </div>
        <span className={['text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full', ACCENT_BADGE[accent]].join(' ')}>
          {toolCount}+ tools
        </span>
      </div>

      {/* Text */}
      <div className="flex flex-col gap-1.5 flex-1">
        <h3 className="text-sm font-semibold text-ink-100 leading-tight">{name}</h3>
        <p className="text-xs text-ink-400 leading-relaxed">{blurb}</p>
      </div>

      {/* CTA */}
      <Link
        to={route}
        className={[
          'inline-flex items-center gap-1.5 text-xs font-medium transition-colors mt-auto',
          accent === 'cyan' ? 'text-cyan-400 hover:text-cyan-300' :
          accent === 'magenta' ? 'text-pink-400 hover:text-pink-300' :
          'text-kerf-300 hover:text-kerf-200',
        ].join(' ')}
      >
        {cta}
        <ArrowRight size={12} strokeWidth={2} className="group-hover:translate-x-0.5 transition-transform" />
      </Link>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                         */
/* -------------------------------------------------------------------------- */

export default function Tools() {
  useEffect(() => {
    document.title = META.title
    setMeta('description', META.description)
    setProp('og:title', META.title)
    setProp('og:description', META.description)
    setProp('og:url', META.canonicalUrl)
    setProp('og:image', META.ogImage)
    let canon = document.querySelector('link[rel="canonical"]')
    if (!canon) { canon = document.createElement('link'); canon.rel = 'canonical'; document.head.appendChild(canon) }
    canon.href = META.canonicalUrl
  }, [])

  const totalTools = PANELS.reduce((s, p) => s + p.toolCount, 0)

  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />

      <main>
        {/* Hero strip */}
        <section className="mx-auto max-w-7xl px-4 sm:px-6 pt-16 pb-10">
          <div className="flex flex-col gap-4 max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-kerf-700/50 bg-kerf-900/30 text-kerf-300 text-xs font-mono w-fit">
              <Cpu size={12} />
              {totalTools}+ engineering tools
            </div>
            <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-ink-50">
              Domain Panels
            </h1>
            <p className="text-base text-ink-400 leading-relaxed">
              Dedicated solver panels for every engineering discipline.
              Each panel wires validated backend tools directly into the browser — no plugin installs.
            </p>
          </div>
        </section>

        {/* Card grid */}
        <section className="mx-auto max-w-7xl px-4 sm:px-6 pb-20">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {PANELS.map((panel) => (
              <PanelCard key={panel.slug} panel={panel} />
            ))}
          </div>
        </section>

        {/* Bottom CTA */}
        <section className="border-t border-ink-900">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 py-12 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
            <div className="flex flex-col gap-1">
              <span className="text-sm font-semibold text-ink-100">Everything in the editor too</span>
              <span className="text-xs text-ink-400">All tools are also reachable from the chat panel inside any project.</span>
            </div>
            <Button as={Link} to="/projects" variant="primary" size="sm">
              Open a project
            </Button>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}
