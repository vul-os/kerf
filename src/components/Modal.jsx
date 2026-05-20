/**
 * Modal.jsx — Canonical accessible modal dialog.
 *
 * Features:
 *   - role="dialog" + aria-modal="true" + aria-labelledby
 *   - Focus trap: Tab/Shift+Tab cycle within the dialog
 *   - Focus return: restores focus to the trigger element on close
 *   - Scroll lock: body overflow hidden while open
 *   - Esc to close
 *   - Backdrop click to close
 *
 * Props:
 *   open        {boolean}    Whether the modal is visible.
 *   onClose     {fn}         Called when user dismisses (Esc / backdrop / X button).
 *   title       {string}     Dialog title (displayed in header, wired to aria-labelledby).
 *   children    {ReactNode}  Body content.
 *   footer      {ReactNode}  Optional footer content (right-aligned row below a divider).
 *   widthClass  {string}     Tailwind max-width class (default "max-w-md").
 *   titleId     {string}     Optional id override for the title element.
 */

import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import clsx from 'clsx'

// Focusable element selectors (ARIA best-practice list).
const FOCUSABLE =
  'a[href], area[href], input:not([disabled]):not([type="hidden"]), ' +
  'select:not([disabled]), textarea:not([disabled]), button:not([disabled]), ' +
  'iframe, object, embed, [tabindex]:not([tabindex="-1"]), [contenteditable]'

function getFocusable(container) {
  return Array.from(container.querySelectorAll(FOCUSABLE)).filter(
    (el) => !el.closest('[inert]') && el.offsetParent !== null,
  )
}

export default function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  widthClass = 'max-w-md',
  titleId = 'modal-title',
}) {
  const dialogRef = useRef(null)
  const previousFocusRef = useRef(null)

  // ── Focus return: capture trigger before opening ──────────────────────────
  useEffect(() => {
    if (open) {
      previousFocusRef.current = document.activeElement
    } else {
      // Restore focus when closing.
      if (previousFocusRef.current && typeof previousFocusRef.current.focus === 'function') {
        previousFocusRef.current.focus()
        previousFocusRef.current = null
      }
    }
  }, [open])

  // ── Move initial focus into the dialog ───────────────────────────────────
  useEffect(() => {
    if (!open || !dialogRef.current) return
    const focusable = getFocusable(dialogRef.current)
    if (focusable.length > 0) {
      focusable[0].focus()
    } else {
      dialogRef.current.focus()
    }
  }, [open])

  // ── Focus trap + Esc ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return

    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab') return

      const focusable = getFocusable(dialogRef.current)
      if (focusable.length === 0) {
        e.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown, true)
    return () => document.removeEventListener('keydown', handleKeyDown, true)
  }, [open, onClose])

  // ── Scroll lock ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    const original = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = original
    }
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 grid place-items-center px-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-ink-950/80 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Dialog panel */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={clsx(
          'relative w-full bg-ink-900 border border-ink-800 rounded-2xl shadow-2xl shadow-black/50',
          'outline-none',
          widthClass,
        )}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-ink-800">
          <h2
            id={titleId}
            className="font-display text-lg font-semibold tracking-tight"
          >
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-ink-400 hover:text-ink-100 transition-colors"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <div className="p-5">{children}</div>
        {footer && (
          <div className="px-5 py-4 border-t border-ink-800 flex justify-end gap-2">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
