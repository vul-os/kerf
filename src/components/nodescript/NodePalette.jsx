/**
 * NodePalette.jsx — Left sidebar: searchable, collapsible node library.
 *
 * Props:
 *   onAddNode(def, position) — called when user clicks/drags a node entry
 *   collapsed               — boolean
 *   onToggleCollapse        — () → void
 */

import { useState, useCallback } from 'react'
import { getNodesByCategory, CATEGORY_COLORS } from './node_library.js'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'

const GROUPS = getNodesByCategory()

export default function NodePalette({ onAddNode, collapsed, onToggleCollapse }) {
  const [search, setSearch]           = useState('')
  const [openCats, setOpenCats]       = useState(() => {
    const m = new Map()
    for (const cat of GROUPS.keys()) m.set(cat, true)
    return m
  })

  const toggleCat = useCallback((cat) => {
    setOpenCats((prev) => {
      const next = new Map(prev)
      next.set(cat, !prev.get(cat))
      return next
    })
  }, [])

  const query = search.trim().toLowerCase()

  const filteredGroups = []
  for (const [cat, nodes] of GROUPS) {
    const filtered = query
      ? nodes.filter((n) => n.label.toLowerCase().includes(query) || cat.toLowerCase().includes(query))
      : nodes
    if (filtered.length > 0) filteredGroups.push([cat, filtered])
  }

  return (
    <aside
      style={{
        width: collapsed ? 36 : 220,
        minWidth: collapsed ? 36 : 220,
        transition: 'width 0.2s ease',
        background: '#0f1115',
        borderRight: '1px solid #1a1d24',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        zIndex: 10,
      }}
    >
      {/* Collapse toggle */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '8px 6px',
          borderBottom: '1px solid #1a1d24',
          gap: 6,
        }}
      >
        {!collapsed && (
          <span style={{ fontSize: 11, fontWeight: 600, color: '#b8bfcc', flex: 1, whiteSpace: 'nowrap' }}>
            Node Library
          </span>
        )}
        <button
          type="button"
          onClick={onToggleCollapse}
          title={collapsed ? 'Expand palette' : 'Collapse palette'}
          style={{
            background: 'none',
            border: 'none',
            color: '#5a6275',
            cursor: 'pointer',
            padding: '2px 4px',
            borderRadius: 4,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {!collapsed && (
        <>
          {/* Search */}
          <div style={{ padding: '6px 8px', borderBottom: '1px solid #1a1d24' }}>
            <div style={{ position: 'relative' }}>
              <Search
                size={12}
                style={{ position: 'absolute', left: 6, top: '50%', transform: 'translateY(-50%)', color: '#5a6275' }}
              />
              <input
                type="text"
                placeholder="Search nodes…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  width: '100%',
                  background: '#14171c',
                  border: '1px solid #2d323d',
                  borderRadius: 4,
                  color: '#e2e6ee',
                  fontSize: 11,
                  padding: '4px 6px 4px 22px',
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          </div>

          {/* Node groups */}
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {filteredGroups.map(([cat, nodes]) => {
              const catColor = CATEGORY_COLORS[cat] ?? '#6bd4ff'
              const open = openCats.get(cat) !== false
              return (
                <div key={cat}>
                  {/* Category header */}
                  <button
                    type="button"
                    onClick={() => toggleCat(cat)}
                    style={{
                      width: '100%',
                      background: 'none',
                      border: 'none',
                      borderBottom: '1px solid #14171c',
                      padding: '5px 8px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                  >
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: catColor,
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ fontSize: 10, fontWeight: 700, color: catColor, flex: 1, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                      {cat}
                    </span>
                    <span style={{ fontSize: 9, color: '#5a6275' }}>{open ? '▾' : '▸'}</span>
                  </button>

                  {/* Nodes */}
                  {open && nodes.map((def) => (
                    <button
                      key={def.id}
                      type="button"
                      title={def.description}
                      onClick={() => onAddNode?.(def)}
                      style={{
                        width: '100%',
                        background: 'none',
                        border: 'none',
                        padding: '5px 8px 5px 22px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        cursor: 'pointer',
                        textAlign: 'left',
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = '#14171c' }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'none' }}
                    >
                      <span
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          background: catColor,
                          opacity: 0.6,
                          flexShrink: 0,
                        }}
                      />
                      <span style={{ fontSize: 11, color: '#b8bfcc' }}>{def.label}</span>
                      {def.llm_tool_name && (
                        <span
                          style={{
                            marginLeft: 'auto',
                            fontSize: 8,
                            color: '#3a4150',
                            background: '#14171c',
                            border: '1px solid #232730',
                            borderRadius: 2,
                            padding: '0 3px',
                          }}
                        >
                          API
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )
            })}
            {filteredGroups.length === 0 && (
              <p style={{ fontSize: 11, color: '#5a6275', padding: '12px 8px', textAlign: 'center' }}>
                No nodes match "{search}"
              </p>
            )}
          </div>
        </>
      )}
    </aside>
  )
}
