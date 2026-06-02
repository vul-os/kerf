// ToolsLanding — /tools hub page linking to all standalone engineering-tool panels.
//
// Each card is a tile linking to a tool page. Kept intentionally minimal —
// these are specialist UI panels backed by LLM tools, not marketing pages.

import { Link } from 'react-router-dom'
import {
  Wrench, ShieldAlert, ArrowRight,
} from 'lucide-react'

const TOOLS = [
  {
    href: '/tools/geometry-inspector',
    icon: Wrench,
    iconColor: '#22d3ee',
    title: 'Geometry Inspector',
    desc: 'B-rep heal · validate · feature recognition · analysis — 28 tools across 4 sections.',
    tags: ['brep', 'heal', 'validate', 'feature-recog'],
  },
  {
    href: '/clash',
    icon: ShieldAlert,
    iconColor: '#ef4444',
    title: 'Assembly Clash',
    desc: 'Interference detection, clearance check, and motion sweep for assembly bodies. Möller–Trumbore + BVH.',
    tags: ['assembly', 'clash', 'clearance', 'motion'],
  },
]

export default function ToolsLanding() {
  return (
    <div style={{
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      background: '#0d1117',
      minHeight: '100vh',
      color: '#e5e7eb',
      padding: '32px 20px',
    }}>
      <div style={{ maxWidth: 900, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 28 }}>
        {/* Header */}
        <div style={{ borderBottom: '1px solid #1f2937', paddingBottom: 20 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#f3f4f6', margin: 0 }}>Engineering Tools</h1>
          <p style={{ fontSize: 12, color: '#6b7280', marginTop: 6 }}>
            Standalone analysis panels backed by kerf LLM tools. All dispatch to{' '}
            <code style={{ color: '#9ca3af' }}>POST /api/tools/call</code>.
          </p>
        </div>

        {/* Tiles grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: 14,
        }}>
          {TOOLS.map((t) => {
            const Icon = t.icon
            return (
              <Link
                key={t.href}
                to={t.href}
                style={{ textDecoration: 'none' }}
              >
                <div style={{
                  background: '#111827',
                  border: '1px solid #1f2937',
                  borderRadius: 8,
                  padding: 16,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 10,
                  transition: 'border-color 0.15s, background 0.15s',
                  cursor: 'pointer',
                }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = t.iconColor
                    e.currentTarget.style.background = '#161b26'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#1f2937'
                    e.currentTarget.style.background = '#111827'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Icon size={18} style={{ color: t.iconColor, flexShrink: 0 }} />
                    <span style={{ fontWeight: 700, fontSize: 14, color: '#f3f4f6' }}>{t.title}</span>
                    <ArrowRight size={13} style={{ color: '#374151', marginLeft: 'auto' }} />
                  </div>
                  <p style={{ fontSize: 12, color: '#9ca3af', margin: 0, lineHeight: 1.5 }}>{t.desc}</p>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {t.tags.map((tag) => (
                      <span key={tag} style={{
                        fontSize: 10,
                        background: '#1f2937',
                        border: '1px solid #374151',
                        borderRadius: 3,
                        color: '#6b7280',
                        padding: '1px 5px',
                      }}>{tag}</span>
                    ))}
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}
