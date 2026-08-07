/**
 * markdownSanitize.js
 *
 * XSS-safety utilities for Workshop README rendering.
 *
 * react-markdown converts Markdown to React elements (JSX), NOT to raw HTML.
 * It never executes `<script>` tags found in the Markdown source — they are
 * stripped silently unless `rehype-raw` is enabled (which we do NOT use here).
 *
 * However, some vectors still require explicit blocking:
 *   - `javascript:` hrefs in links   → blocked by urlTransformer
 *   - `data:` and `vbscript:` URLs   → blocked by urlTransformer
 *   - Potentially dangerous tags      → blocked by allowedElements allowlist
 *
 * This module exports:
 *   ALLOWED_ELEMENTS  — whitelist of HTML tags react-markdown may render.
 *   urlTransformer    — function applied to every href/src before rendering.
 *   sanitizeMarkdownUrl — pure function: safe URL → original, dangerous URL → ''
 *
 * Usage (in a React component):
 *   import ReactMarkdown from 'react-markdown'
 *   import remarkGfm from 'remark-gfm'
 *   import { ALLOWED_ELEMENTS, urlTransformer } from '../lib/markdownSanitize.js'
 *
 *   <ReactMarkdown
 *     remarkPlugins={[remarkGfm]}
 *     allowedElements={ALLOWED_ELEMENTS}
 *     urlTransform={urlTransformer}
 *   >
 *     {markdown}
 *   </ReactMarkdown>
 */

/**
 * Allowlist of HTML element names that react-markdown may render.
 * Deliberately excludes: script, style, iframe, object, embed, form,
 * input, button, textarea, select, noscript, meta, link, base.
 */
export const ALLOWED_ELEMENTS = [
  'p', 'br', 'hr',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'strong', 'em', 'del', 's', 'sup', 'sub',
  'blockquote',
  'ul', 'ol', 'li',
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'pre', 'code',
  'a',
  'img',
  'div', 'span',
]

// URL schemes that are safe to embed as link targets or image sources.
const SAFE_URL_RE = /^(https?:|mailto:|#|\/|\.\/|\.\.\/)/i

/**
 * sanitizeMarkdownUrl(url) → string
 *
 * Returns the original URL if it starts with a safe scheme, otherwise ''.
 * Pure function — no DOM access — so it is testable in Node / Vitest.
 */
export function sanitizeMarkdownUrl(url) {
  if (!url || typeof url !== 'string') return ''
  const trimmed = url.trim()
  if (!trimmed) return ''
  // Block javascript:, data:, vbscript:, and any unknown scheme.
  if (SAFE_URL_RE.test(trimmed)) return trimmed
  return ''
}

/**
 * urlTransformer(url) → string
 *
 * Adapter for react-markdown's `urlTransform` prop (v10+).
 * Replaces the previous `transformLinkUri` / `transformImageUri` props.
 */
export function urlTransformer(url) {
  return sanitizeMarkdownUrl(url)
}
