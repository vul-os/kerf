// ErrorBoundary.test.jsx — Vitest smoke tests for ErrorBoundary.
//
// Strategy: renderToStaticMarkup (react-dom/server). React's error boundary
// componentDidCatch does not fire during SSR/static render, so we test the
// two states explicitly:
//   1. No error — renders children.
//   2. Error state — we test the fallback UI by accessing component methods
//      or by using the getDerivedStateFromError static method directly.
//
// For the "renders fallback when error occurs" tests we construct the component
// in its error state by calling getDerivedStateFromError + rendering the
// resulting state, or by rendering the fallback subtree in isolation.

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ErrorBoundary from './ErrorBoundary.jsx'

// ── Normal (no error) render ─────────────────────────────────────────────────

describe('ErrorBoundary — no error', () => {
  it('renders children when there is no error', () => {
    const html = renderToStaticMarkup(
      <ErrorBoundary>
        <span data-testid="child">Hello</span>
      </ErrorBoundary>,
    )
    expect(html).toContain('Hello')
  })

  it('renders multiple children without throwing', () => {
    expect(() =>
      renderToStaticMarkup(
        <ErrorBoundary>
          <div>A</div>
          <div>B</div>
        </ErrorBoundary>,
      ),
    ).not.toThrow()
  })
})

// ── getDerivedStateFromError ──────────────────────────────────────────────────

describe('ErrorBoundary — getDerivedStateFromError', () => {
  it('is a static method', () => {
    expect(typeof ErrorBoundary.getDerivedStateFromError).toBe('function')
  })

  it('returns { error } from the thrown error', () => {
    const err = new Error('boom')
    const state = ErrorBoundary.getDerivedStateFromError(err)
    expect(state).toEqual({ error: err })
  })

  it('stores the error object unchanged', () => {
    const err = new TypeError('type mismatch')
    const state = ErrorBoundary.getDerivedStateFromError(err)
    expect(state.error).toBe(err)
    expect(state.error.message).toBe('type mismatch')
  })
})

// ── Default fallback UI ───────────────────────────────────────────────────────
//
// We render the default fallback by manually constructing an instance in the
// error state and calling render() directly.

describe('ErrorBoundary — default fallback UI', () => {
  function makeInstance(error, extraProps = {}) {
    const instance = new ErrorBoundary({ children: null, ...extraProps })
    instance.state = { error, errorInfo: null }
    // Bind reset (constructor normally does this)
    instance.reset = instance.reset.bind(instance)
    return instance
  }

  it('renders role="alert" in the fallback', () => {
    const err = new Error('render failed')
    const instance = makeInstance(err)
    const html = renderToStaticMarkup(instance.render())
    expect(html).toMatch(/role="alert"/)
  })

  it('renders aria-live="assertive" in the fallback', () => {
    const err = new Error('render failed')
    const instance = makeInstance(err)
    const html = renderToStaticMarkup(instance.render())
    expect(html).toMatch(/aria-live="assertive"/)
  })

  it('displays the error message', () => {
    const err = new Error('something broke')
    const instance = makeInstance(err)
    const html = renderToStaticMarkup(instance.render())
    expect(html).toContain('something broke')
  })

  it('includes a "Try again" button', () => {
    const err = new Error('oops')
    const instance = makeInstance(err)
    const html = renderToStaticMarkup(instance.render())
    expect(html).toContain('Try again')
    expect(html).toMatch(/<button\b/)
  })

  it('renders children when error state is null', () => {
    const instance = new ErrorBoundary({ children: <span>child content</span> })
    instance.state = { error: null, errorInfo: null }
    instance.reset = instance.reset.bind(instance)
    const html = renderToStaticMarkup(instance.render())
    expect(html).toContain('child content')
  })
})

// ── Custom fallback function ──────────────────────────────────────────────────

describe('ErrorBoundary — custom fallback', () => {
  it('calls the fallback function with the error', () => {
    const err = new Error('custom error')
    const fallback = vi.fn(() => <div>Custom fallback</div>)
    const instance = new ErrorBoundary({
      children: null,
      fallback,
    })
    instance.state = { error: err, errorInfo: null }
    instance.reset = instance.reset.bind(instance)

    renderToStaticMarkup(instance.render())
    expect(fallback).toHaveBeenCalledWith(err, expect.any(Function))
  })

  it('renders the string returned by the fallback function', () => {
    const err = new Error('oops')
    const instance = new ErrorBoundary({
      children: null,
      fallback: (e) => <p>Caught: {e.message}</p>,
    })
    instance.state = { error: err, errorInfo: null }
    instance.reset = instance.reset.bind(instance)

    const html = renderToStaticMarkup(instance.render())
    expect(html).toContain('Caught: oops')
  })

  it('renders a ReactNode fallback directly when it is not a function', () => {
    const err = new Error('bang')
    const instance = new ErrorBoundary({
      children: null,
      fallback: <div>Static fallback</div>,
    })
    instance.state = { error: err, errorInfo: null }
    instance.reset = instance.reset.bind(instance)

    const html = renderToStaticMarkup(instance.render())
    expect(html).toContain('Static fallback')
  })
})

// ── onError callback ──────────────────────────────────────────────────────────

describe('ErrorBoundary — onError prop', () => {
  it('componentDidCatch calls onError with error and errorInfo', () => {
    const onError = vi.fn()
    // Suppress console.error for this test
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const err = new Error('caught')
    const info = { componentStack: 'at Foo\n  at Bar' }
    const instance = new ErrorBoundary({ children: null, onError })
    instance.state = { error: null, errorInfo: null }
    instance.setState = vi.fn((update) => { Object.assign(instance.state, update) })

    instance.componentDidCatch(err, info)

    expect(onError).toHaveBeenCalledWith(err, info)
    spy.mockRestore()
  })
})
