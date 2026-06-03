/**
 * PropertyInspector.jsx — Right sidebar for the selected node's parameters.
 *
 * Props:
 *   node       – selected node record (or null)
 *   def        – node definition from node_library (or null)
 *   result     – last run result for this node
 *   onChange   – (nodeId, paramName, value) → void
 */

import { useCallback } from 'react'
import { CATEGORY_COLORS } from './node_library.js'
import { X } from 'lucide-react'

function ParamRow({ pin, value, nodeId, onChange }) {
  const handleChange = useCallback((e) => {
    let v = e.target.value
    if (pin.type === 'number') {
      const n = parseFloat(v)
      if (!isNaN(n)) v = n
    }
    onChange(nodeId, pin.name, v)
  }, [pin, nodeId, onChange])

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0' }}>
      <label
        htmlFor={`param-${nodeId}-${pin.name}`}
        style={{ fontSize: 11, color: '#8a93a6', flex: '0 0 80px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        title={pin.name}
      >
        {pin.name}
      </label>
      <input
        id={`param-${nodeId}-${pin.name}`}
        type={pin.type === 'number' ? 'number' : 'text'}
        step={pin.type === 'number' ? 'any' : undefined}
        value={value ?? ''}
        onChange={handleChange}
        style={{
          flex: 1,
          background: '#14171c',
          border: '1px solid #2d323d',
          borderRadius: 4,
          color: '#e2e6ee',
          fontSize: 11,
          padding: '3px 6px',
          outline: 'none',
          minWidth: 0,
        }}
        onFocus={(e) => { e.target.style.borderColor = '#6bd4ff' }}
        onBlur={(e)  => { e.target.style.borderColor = '#2d323d' }}
      />
    </div>
  )
}

export default function PropertyInspector({ node, def, result, onChange }) {
  if (!node || !def) {
    return (
      <aside
        style={{
          width: 220,
          minWidth: 220,
          background: '#0f1115',
          borderLeft: '1px solid #1a1d24',
          padding: 12,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <p style={{ fontSize: 11, color: '#3a4150', textAlign: 'center' }}>
          Select a node to edit its parameters.
        </p>
      </aside>
    )
  }

  const catColor = CATEGORY_COLORS[def.category] ?? '#6bd4ff'
  const editableInputs = def.inputs.filter((pin) => {
    // Only show params that are NOT currently wired (wired inputs show the connected value)
    return true
  })

  return (
    <aside
      style={{
        width: 220,
        minWidth: 220,
        background: '#0f1115',
        borderLeft: '1px solid #1a1d24',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '8px 10px',
          borderBottom: '1px solid #1a1d24',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
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
        <span style={{ fontSize: 12, fontWeight: 600, color: '#e2e6ee', flex: 1 }}>{def.label}</span>
        <span style={{
          fontSize: 9,
          color: catColor,
          background: catColor + '18',
          border: `1px solid ${catColor}40`,
          borderRadius: 3,
          padding: '1px 5px',
        }}>
          {def.category}
        </span>
      </div>

      {/* Description */}
      {def.description && (
        <p style={{ fontSize: 10, color: '#5a6275', padding: '6px 10px', margin: 0, borderBottom: '1px solid #14171c' }}>
          {def.description}
        </p>
      )}

      {/* Parameters */}
      <div style={{ padding: '8px 10px', overflowY: 'auto', flex: 1 }}>
        {editableInputs.length > 0 ? (
          <>
            <p style={{ fontSize: 9, fontWeight: 700, color: '#3a4150', letterSpacing: '0.08em', textTransform: 'uppercase', margin: '0 0 6px' }}>
              Parameters
            </p>
            {editableInputs.map((pin) => (
              <ParamRow
                key={pin.name}
                pin={pin}
                value={node.params?.[pin.name] ?? pin.default ?? ''}
                nodeId={node.id}
                onChange={onChange}
              />
            ))}
          </>
        ) : (
          <p style={{ fontSize: 11, color: '#3a4150' }}>No editable parameters.</p>
        )}

        {/* Outputs info */}
        {def.outputs.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <p style={{ fontSize: 9, fontWeight: 700, color: '#3a4150', letterSpacing: '0.08em', textTransform: 'uppercase', margin: '0 0 4px' }}>
              Outputs
            </p>
            {def.outputs.map((o) => (
              <div key={o.name} style={{ display: 'flex', gap: 6, padding: '2px 0', alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: '#8a93a6' }}>{o.name}</span>
                <span style={{ fontSize: 9, color: '#3a4150', marginLeft: 'auto' }}>{o.type}</span>
              </div>
            ))}
          </div>
        )}

        {/* LLM tool badge */}
        {def.llm_tool_name && (
          <div style={{ marginTop: 10, padding: '5px 7px', background: '#14171c', borderRadius: 4, border: '1px solid #232730' }}>
            <p style={{ margin: 0, fontSize: 9, color: '#5a6275' }}>
              LLM tool
            </p>
            <p style={{ margin: '2px 0 0', fontSize: 10, color: '#6bd4ff', fontFamily: 'var(--font-mono)' }}>
              {def.llm_tool_name}
            </p>
          </div>
        )}
      </div>

      {/* Result panel */}
      {result !== undefined && (
        <div
          style={{
            padding: '6px 10px',
            borderTop: '1px solid #1a1d24',
            background: '#14171c',
          }}
        >
          <p style={{ margin: '0 0 4px', fontSize: 9, fontWeight: 700, color: '#3a4150', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Last Result
          </p>
          <pre
            style={{
              margin: 0,
              fontSize: 9,
              color: result?.error ? '#ef4444' : '#34d399',
              fontFamily: 'var(--font-mono)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              maxHeight: 100,
              overflowY: 'auto',
            }}
          >
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </aside>
  )
}
