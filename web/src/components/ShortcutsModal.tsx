// Global keyboard-shortcuts cheatsheet. Mounted once at the app root; the
// `?` key opens it from anywhere (except when typing in an input/textarea
// or Monaco). A small "?" footer chip in the bottom-right offers the same
// thing for users who don't know the shortcut yet.

import { useEffect, useState } from 'react'
import { Keyboard } from 'lucide-react'
import Modal from './Modal.jsx'

const GROUPS = [
  {
    title: 'Global',
    rows: [
      ['Cmd / Ctrl + S',      'Save the current file'],
      ['Cmd / Ctrl + Z',      'Undo (revision-aware)'],
      ['Cmd / Ctrl + Shift + Z', 'Redo'],
      ['Cmd / Ctrl + K',      'Focus the chat input'],
      ['?',                    'Open this cheatsheet'],
      ['Esc',                  'Cancel current tool / close popups'],
    ],
  },
  {
    title: 'Sketcher (.sketch)',
    rows: [
      ['L',  'Line tool'],
      ['C',  'Circle tool'],
      ['A',  'Arc (3-point)'],
      ['R',  'Rectangle'],
      ['P',  'Point'],
      ['B',  'B-spline'],
      ['Shift + E', 'Ellipse'],
      ['T',  'Trim'],
      ['E',  'Extend'],
      ['F',  'Fillet (2D)'],
      ['M',  'Mirror'],
      ['Shift + L', 'Linear pattern'],
      ['Shift + P', 'Polar pattern'],
      ['Shift + T', 'Toggle construction on selection'],
      ['H / V',     'Horizontal / vertical constraint on a line'],
      ['D',  'Dimension (auto-picks distance / radius / angle)'],
      ['Del','Delete selected entity (cascades dependent constraints)'],
      ['S / Esc', 'Back to select mode'],
    ],
  },
  {
    title: '3D viewport (Renderer + FeatureView)',
    rows: [
      ['Drag',         'Orbit'],
      ['Shift + drag', 'Pan'],
      ['Wheel',        'Zoom'],
      ['Click',        'Select Object / face / edge (depending on mode)'],
      ['Shift + click','Multi-select'],
      ['1 / 2 / 3 / 4','Measure mode (object / face / edge / vertex)'],
      ['Esc',           'Clear selected features'],
    ],
  },
  {
    title: 'Drawing (.drawing)',
    rows: [
      ['Click',     'Select view / dimension / annotation'],
      ['Alt + click', 'Bypass snap (free placement)'],
      ['Drag',      'Move the selected entity'],
      ['Del',       'Delete selected'],
    ],
  },
  {
    title: 'JSCAD code editor',
    rows: [
      ['Cmd / Ctrl + S', 'Re-evaluate now (also autosave)'],
      ['Cmd / Ctrl + /', 'Toggle line comment'],
      ['Cmd / Ctrl + F', 'Find'],
      ['Cmd / Ctrl + D', 'Select next occurrence'],
    ],
  },
  {
    title: 'File tree',
    rows: [
      ['F2',  'Rename'],
      ['Del', 'Soft-delete (restorable from Trash)'],
      ['Right-click', 'Context menu'],
      ['Drag', 'Move file between folders (where supported)'],
    ],
  },
]

function isTypingTarget(t) {
  if (!t) return false
  const tag = t.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (t.isContentEditable) return true
  if (t.closest && t.closest('.monaco-editor')) return true
  return false
}

export default function ShortcutsModal() {
  const [open, setOpen] = useState(false)

  // `?` opens the modal; Esc is handled by the canonical Modal.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === '?' && !e.metaKey && !e.ctrlKey && !e.altKey && !isTypingTarget(e.target)) {
        e.preventDefault()
        setOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Keyboard shortcuts (?)"
        aria-label="Keyboard shortcuts"
        className="fixed bottom-3 right-3 z-30 w-7 h-7 rounded-full bg-ink-900/90 border border-ink-700 text-ink-300 hover:text-kerf-300 hover:border-kerf-300/40 backdrop-blur flex items-center justify-center text-xs"
      >
        ?
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Keyboard shortcuts"
        widthClass="max-w-3xl"
        footer={
          <p className="text-[11px] text-ink-500 w-full text-left">
            Press{' '}
            <kbd className="font-mono px-1 py-0.5 bg-ink-950 border border-ink-700 rounded text-ink-300">?</kbd>
            {' '}from anywhere to open this.{' '}
            <kbd className="font-mono px-1 py-0.5 bg-ink-950 border border-ink-700 rounded text-ink-300">Esc</kbd>
            {' '}to close.
          </p>
        }
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-6 -mt-1">
          {GROUPS.map((g) => (
            <div key={g.title}>
              <div className="text-[11px] uppercase tracking-wide text-kerf-300 font-semibold mb-2 flex items-center gap-1.5">
                {g.title === 'Global' && <Keyboard size={11} />}
                {g.title}
              </div>
              <div className="space-y-1">
                {g.rows.map(([kbd, desc]) => (
                  <div key={kbd} className="flex items-baseline gap-3 text-xs">
                    <kbd className="font-mono text-[11px] px-1.5 py-0.5 bg-ink-950 border border-ink-700 rounded text-ink-200 whitespace-nowrap">
                      {kbd}
                    </kbd>
                    <span className="text-ink-300 flex-1">{desc}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Modal>
    </>
  )
}
