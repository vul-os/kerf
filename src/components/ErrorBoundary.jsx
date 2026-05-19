/**
 * ErrorBoundary.jsx — React class component for catching render errors.
 *
 * React's error boundaries must be class components (hooks cannot catch
 * render errors). This boundary:
 *   - Catches errors thrown by any descendant during render/lifecycle.
 *   - Renders a fallback UI with the error message and a "Try again" button.
 *   - Logs errors to console.error (can be wired to a real error reporter via
 *     the `onError` prop).
 *   - Exposes a `reset()` method so parent components can programmatically
 *     clear the error state (e.g. after navigation).
 *
 * Public API
 * ──────────
 *   <ErrorBoundary fallback? onError? resetKeys?>
 *     - fallback:   ReactNode | (error, reset) => ReactNode
 *                   Custom fallback UI. Receives the caught error and a reset
 *                   function. If omitted, uses the built-in Kerf-styled card.
 *     - onError:    (error: Error, info: { componentStack }) => void
 *                   Called synchronously inside componentDidCatch. Wire to
 *                   Sentry / Datadog here.
 *     - resetKeys:  any[]
 *                   When any value in this array changes, the boundary resets
 *                   automatically (same pattern as react-error-boundary).
 *
 * Usage
 * ─────
 *   // Wrapping a route:
 *   <ErrorBoundary>
 *     <MyRoute />
 *   </ErrorBoundary>
 *
 *   // Custom fallback:
 *   <ErrorBoundary fallback={(err, reset) => (
 *     <div>Oops: {err.message} <button onClick={reset}>Retry</button></div>
 *   )}>
 *     <DataTable />
 *   </ErrorBoundary>
 */

import { Component } from 'react'
import clsx from 'clsx'
import { AlertTriangle, RefreshCw } from 'lucide-react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null, errorInfo: null }
    this.reset = this.reset.bind(this)
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo })
    // Built-in log; callers can suppress by providing onError that doesn't
    // call console.error.
    console.error('[ErrorBoundary]', error, errorInfo)
    this.props.onError?.(error, errorInfo)
  }

  componentDidUpdate(prevProps) {
    const { resetKeys } = this.props
    if (
      this.state.error &&
      resetKeys &&
      resetKeys.some((key, i) => key !== (prevProps.resetKeys || [])[i])
    ) {
      this.reset()
    }
  }

  reset() {
    this.setState({ error: null, errorInfo: null })
  }

  render() {
    const { error } = this.state
    const { fallback, children } = this.props

    if (!error) return children

    // Custom fallback
    if (typeof fallback === 'function') {
      return fallback(error, this.reset)
    }
    if (fallback != null) {
      return fallback
    }

    // Default Kerf-styled error card
    return (
      <div
        role="alert"
        aria-live="assertive"
        className={clsx(
          'flex flex-col items-center justify-center gap-4',
          'p-8 rounded-xl text-center',
          'bg-ink-900 border border-red-900/60',
          'text-ink-100',
        )}
      >
        <div aria-hidden="true" className="text-red-400">
          <AlertTriangle size={40} strokeWidth={1.5} />
        </div>

        <div className="flex flex-col gap-1">
          <p className="text-base font-semibold text-ink-100">
            Something went wrong
          </p>
          <p className="text-sm text-ink-400 max-w-sm font-mono break-all">
            {error.message}
          </p>
        </div>

        <button
          type="button"
          onClick={this.reset}
          className={clsx(
            'inline-flex items-center gap-2 h-9 px-4 text-sm font-medium rounded-lg',
            'bg-ink-700 text-ink-100 hover:bg-ink-600 border border-ink-600',
            'transition-colors duration-150',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/50 focus-visible:ring-offset-2 focus-visible:ring-offset-ink-950',
          )}
        >
          <RefreshCw size={14} aria-hidden="true" />
          Try again
        </button>
      </div>
    )
  }
}
