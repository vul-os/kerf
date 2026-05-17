/**
 * KernelDepth — landing section that translates Kerf's geometry-kernel depth
 * into user-visible behaviour.
 *
 * The rest of the Landing page is honest about *breadth* (mech / electronic /
 * jewelry / architecture). This section is the missing half: the foundation
 * those breadth claims rest on — valid B-rep topology after every boolean,
 * G1/G2 fillets, a parametric history DAG with persistent face naming,
 * tolerant solid booleans, hardened SSI, closest-point — without name-dropping
 * any specific kernel vendor (per public_readme_scope: stay user-value
 * focused, not architecture name-drop).
 *
 * Layout matches the rest of the Landing surface (DomainSpotlights, etc):
 *   - max-w-7xl outer
 *   - ink-* / kerf-* palette only
 *   - inline SVG, no raster
 *   - Tailwind responsive (sm: / lg:)
 */
import { ArrowRight, ShieldCheck, Layers, Sigma } from 'lucide-react'
import { Link } from 'react-router-dom'

/* -------------------------------------------------------------------------- */
/* Three user-language proof cards                                            */
/* -------------------------------------------------------------------------- */

const PROOFS = [
  {
    icon: Sigma,
    eyebrow: 'Parametric history',
    title: 'Edit a stone size — your prong fillets survive.',
    body: 'Parametric edits survive across fillets and booleans via persistent face IDs. Change a ring size, a stock thickness, a stone diameter — downstream fillets, holes, and chamfers re-resolve to the same logical faces instead of breaking.',
    detail: 'persistent face IDs · feature DAG re-evaluation',
  },
  {
    icon: ShieldCheck,
    eyebrow: 'Tolerant booleans',
    title: 'Cut a hole in your part — booleans produce a watertight solid.',
    body: 'Union, difference, and intersection on solids are validated for closed-shell topology before they return. No silent "invalid solid" dead-ends from a fuse that almost-but-didn\'t match at a tolerance boundary.',
    detail: 'closed-shell validation on every result',
  },
  {
    icon: Layers,
    eyebrow: 'Continuity-graded fillets',
    title: 'Round an edge — pick G1 tangent or G2 curvature.',
    body: 'Rolling-ball fillets are sewn back into a validated body with an explicit continuity classifier against the supporting faces. You see the continuity grade the surface actually achieves — not a checkbox the UI claims.',
    detail: 'G1 / G2 continuity classifier',
  },
]

/* -------------------------------------------------------------------------- */
/* Quiet-credibility stat strip                                               */
/* -------------------------------------------------------------------------- */

const STATS = [
  {
    value: '620',
    label: 'kernel tests',
    sub: 'all analytic-oracle verified',
  },
  {
    value: 'V−E+F = 2',
    label: 'topology invariant',
    sub: 're-checked after every op',
  },
  {
    value: 'G1 / G2',
    label: 'fillet continuity',
    sub: 'graded, not assumed',
  },
  {
    value: '3 verticals',
    label: 'jewelry · mech · electronic',
    sub: 'one workspace, one kernel',
  },
]

/* -------------------------------------------------------------------------- */
/* Survival diagram — small inline SVG showing param edit → fillet survives   */
/* -------------------------------------------------------------------------- */

function SurvivalDiagram({ className = '' }) {
  return (
    <svg
      viewBox="0 0 320 140"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Diagram showing a downstream fillet surviving an upstream parameter edit via persistent face identity"
    >
      <defs>
        <linearGradient id="kd-block" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#232730" />
          <stop offset="100%" stopColor="#1a1d24" />
        </linearGradient>
        <linearGradient id="kd-block-after" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#2d323d" />
          <stop offset="100%" stopColor="#1f2229" />
        </linearGradient>
      </defs>

      {/* before — short block + fillet pill */}
      <g aria-label="before">
        <rect x="20" y="68" width="80" height="44" rx="2" fill="url(#kd-block)" stroke="#3a4150" />
        {/* fillet indicator — yellow arc on top-right edge */}
        <path d="M 92,68 Q 100,68 100,76" fill="none" stroke="#ffd633" strokeWidth="2" />
        <path d="M 28,68 Q 20,68 20,76" fill="none" stroke="#ffd633" strokeWidth="2" />
        <text x="60" y="128" textAnchor="middle" fontSize="8" fontFamily="ui-monospace, monospace" fill="#5a6275">
          height = 12 mm
        </text>
        <text x="60" y="60" textAnchor="middle" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#ffd633" opacity="0.8">
          Fillet-A · ↦ TopCap
        </text>
      </g>

      {/* arrow with label */}
      <g>
        <line x1="116" y1="90" x2="200" y2="90" stroke="#3a4150" strokeWidth="1" strokeDasharray="3 3" />
        <polygon points="200,90 194,86 194,94" fill="#5a6275" />
        <rect x="128" y="76" width="64" height="14" rx="3" fill="#0f1115" stroke="#232730" />
        <text x="160" y="86" textAnchor="middle" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#ffd633">
          set_param(h, 28)
        </text>
      </g>

      {/* after — taller block, fillet still pinned to top */}
      <g aria-label="after">
        <rect x="216" y="40" width="80" height="72" rx="2" fill="url(#kd-block-after)" stroke="#3a4150" />
        {/* fillet indicator — yellow arc, still on top edge */}
        <path d="M 288,40 Q 296,40 296,48" fill="none" stroke="#ffd633" strokeWidth="2" />
        <path d="M 224,40 Q 216,40 216,48" fill="none" stroke="#ffd633" strokeWidth="2" />
        <text x="256" y="128" textAnchor="middle" fontSize="8" fontFamily="ui-monospace, monospace" fill="#5a6275">
          height = 28 mm
        </text>
        <text x="256" y="32" textAnchor="middle" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#ffd633" opacity="0.8">
          Fillet-A · ↦ TopCap
        </text>
      </g>

      {/* baseline */}
      <line x1="8" y1="118" x2="312" y2="118" stroke="#1a1d24" strokeWidth="1" />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Public export                                                              */
/* -------------------------------------------------------------------------- */

export default function KernelDepth() {
  return (
    <section
      className="relative border-t border-ink-900"
      aria-label="Kernel depth — what stays true after every edit"
    >
      <div className="mx-auto max-w-7xl px-6 py-12 lg:py-14">
        <div className="max-w-2xl mb-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300">
            What stays true after every edit
          </p>
          <h2 className="mt-2 font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em]">
            A geometry kernel,
            <br />
            <span className="text-ink-300">not just a renderer.</span>
          </h2>
          <p className="mt-3 text-ink-300 leading-relaxed">
            Most chat-driven CAD tools draw triangles. Kerf carries a real
            topological model behind every feature — so the things you build
            on top of each other don&apos;t fall apart when you go back and
            change a parameter.
          </p>
        </div>

        {/* Three proof cards in user language */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {PROOFS.map((p) => (
            <article
              key={p.title}
              className="group relative rounded-2xl border border-ink-800 bg-ink-900/40 p-5 transition-colors hover:border-ink-700 hover:bg-ink-900/60"
              aria-label={p.eyebrow}
            >
              <div className="flex items-center gap-2.5 mb-3">
                <span className="grid place-items-center w-7 h-7 rounded-md bg-kerf-300/10 border border-kerf-300/30 text-kerf-300">
                  <p.icon size={13} />
                </span>
                <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-kerf-300">
                  {p.eyebrow}
                </p>
              </div>
              <h3 className="font-display text-lg font-semibold tracking-tight text-ink-100 mb-2 leading-snug">
                {p.title}
              </h3>
              <p className="text-sm text-ink-300 leading-relaxed mb-3">
                {p.body}
              </p>
              <p className="text-[11px] text-ink-500 font-mono">{p.detail}</p>
            </article>
          ))}
        </div>

        {/* Visual: param edit survival diagram + quiet stat strip */}
        <div className="mt-6 grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-4">
          <div
            className="rounded-2xl border border-ink-800 bg-ink-950/60 backdrop-blur p-5"
            aria-label="Persistent face identity survival diagram"
          >
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-500 mb-3">
              Parametric edit · before / after
            </p>
            <SurvivalDiagram className="block w-full h-auto" />
            <p className="mt-3 text-xs text-ink-400 leading-relaxed">
              Fillet-A&apos;s reference to <span className="text-kerf-300 font-mono">TopCap</span> is
              a name, not an index. Re-evaluate with a new height — the fillet
              re-resolves to the same logical face on the new body.
            </p>
          </div>

          <div
            className="rounded-2xl border border-ink-800 bg-ink-900/40 p-5 flex flex-col gap-3"
            aria-label="Kernel credibility figures"
          >
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-500">
              Quiet credibility
            </p>
            <ul className="grid grid-cols-2 gap-3">
              {STATS.map((s) => (
                <li
                  key={s.label}
                  className="rounded-lg border border-ink-800 bg-ink-950/40 p-3"
                >
                  <div className="font-display text-lg font-semibold tracking-tight text-kerf-300 leading-none">
                    {s.value}
                  </div>
                  <div className="mt-1.5 text-[11px] text-ink-200 font-mono">
                    {s.label}
                  </div>
                  <div className="text-[10px] text-ink-500 font-mono mt-0.5 leading-tight">
                    {s.sub}
                  </div>
                </li>
              ))}
            </ul>
            <Link
              to="/docs/architecture"
              className="mt-1 inline-flex items-center gap-1.5 text-sm font-medium text-kerf-300 hover:text-kerf-200 transition-colors"
              aria-label="Read the architecture docs"
            >
              How the kernel works
              <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      </div>
    </section>
  )
}
