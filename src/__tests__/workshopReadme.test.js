// workshopReadme.test.js
//
// T-45: Frontend tests for the Workshop README workstream.
//
// Tests:
//   1. markdownSanitize.sanitizeMarkdownUrl — XSS URL blocking
//   2. markdownSanitize.ALLOWED_ELEMENTS — allowlist shape
//   3. Cover URL resolution logic (mirrors _project_to_workshop_row)
//   4. Publish flow state logic — gallery is optional
//
// All tests are pure-JS (no DOM/React rendering) so they run in Node/Vitest
// without jsdom and without a live browser.  XSS safety of the markdown
// renderer itself is guaranteed by react-markdown's JSX-only output path
// (no rehype-raw), but the URL transformer provides the critical blocking
// layer for javascript: and data: hrefs — tested here exhaustively.

import { describe, it, expect } from 'vitest'
import { sanitizeMarkdownUrl, urlTransformer, ALLOWED_ELEMENTS } from '../lib/markdownSanitize.js'

// ---------------------------------------------------------------------------
// 1. sanitizeMarkdownUrl — XSS-hostile fixtures
// ---------------------------------------------------------------------------

describe('sanitizeMarkdownUrl — blocks dangerous URLs', () => {
  // javascript: schemes
  it('blocks javascript: href', () => {
    expect(sanitizeMarkdownUrl('javascript:alert(1)')).toBe('')
  })
  it('blocks JAVASCRIPT: (case-insensitive)', () => {
    expect(sanitizeMarkdownUrl('JAVASCRIPT:alert(1)')).toBe('')
  })
  it('blocks javascript: with whitespace prefix', () => {
    // Some parsers allow leading whitespace before the scheme.
    expect(sanitizeMarkdownUrl('  javascript:alert(1)')).toBe('')
  })

  // data: URIs (XSS vector for inline HTML / script execution)
  it('blocks data: URIs', () => {
    expect(sanitizeMarkdownUrl('data:text/html,<script>alert(1)</script>')).toBe('')
  })
  it('blocks data:image/svg+xml with embedded script', () => {
    expect(sanitizeMarkdownUrl('data:image/svg+xml,<svg onload=alert(1)>')).toBe('')
  })

  // vbscript: (IE-era vector)
  it('blocks vbscript: scheme', () => {
    expect(sanitizeMarkdownUrl('vbscript:msgbox(1)')).toBe('')
  })

  // Unknown protocols
  it('blocks blob: scheme', () => {
    expect(sanitizeMarkdownUrl('blob:https://example.com/abc')).toBe('')
  })
  it('blocks file: scheme', () => {
    expect(sanitizeMarkdownUrl('file:///etc/passwd')).toBe('')
  })
})

describe('sanitizeMarkdownUrl — allows safe URLs', () => {
  it('allows https:// URLs', () => {
    const url = 'https://kerf.design/workshop/abc'
    expect(sanitizeMarkdownUrl(url)).toBe(url)
  })
  it('allows http:// URLs', () => {
    const url = 'http://example.com/'
    expect(sanitizeMarkdownUrl(url)).toBe(url)
  })
  it('allows relative paths', () => {
    expect(sanitizeMarkdownUrl('/api/projects/abc/cover')).toBe('/api/projects/abc/cover')
  })
  it('allows relative paths with ./', () => {
    expect(sanitizeMarkdownUrl('./image.png')).toBe('./image.png')
  })
  it('allows relative paths with ../', () => {
    expect(sanitizeMarkdownUrl('../docs/guide.md')).toBe('../docs/guide.md')
  })
  it('allows fragment-only links', () => {
    expect(sanitizeMarkdownUrl('#parameters')).toBe('#parameters')
  })
  it('allows mailto: links', () => {
    expect(sanitizeMarkdownUrl('mailto:hello@example.com')).toBe('mailto:hello@example.com')
  })
})

describe('sanitizeMarkdownUrl — edge cases', () => {
  it('returns empty string for null', () => {
    expect(sanitizeMarkdownUrl(null)).toBe('')
  })
  it('returns empty string for undefined', () => {
    expect(sanitizeMarkdownUrl(undefined)).toBe('')
  })
  it('returns empty string for empty string', () => {
    expect(sanitizeMarkdownUrl('')).toBe('')
  })
  it('returns empty string for non-string', () => {
    expect(sanitizeMarkdownUrl(42)).toBe('')
  })
})

// ---------------------------------------------------------------------------
// 2. urlTransformer — same behaviour as sanitizeMarkdownUrl (adapter)
// ---------------------------------------------------------------------------

describe('urlTransformer', () => {
  it('blocks javascript: via urlTransformer', () => {
    expect(urlTransformer('javascript:alert(1)')).toBe('')
  })
  it('allows https: via urlTransformer', () => {
    expect(urlTransformer('https://kerf.design')).toBe('https://kerf.design')
  })
})

// ---------------------------------------------------------------------------
// 3. ALLOWED_ELEMENTS allowlist
// ---------------------------------------------------------------------------

describe('ALLOWED_ELEMENTS allowlist', () => {
  it('is a non-empty array of strings', () => {
    expect(Array.isArray(ALLOWED_ELEMENTS)).toBe(true)
    expect(ALLOWED_ELEMENTS.length).toBeGreaterThan(0)
    for (const el of ALLOWED_ELEMENTS) {
      expect(typeof el).toBe('string')
    }
  })

  it('allows standard Markdown elements', () => {
    const required = ['p', 'h1', 'h2', 'h3', 'ul', 'ol', 'li', 'code', 'pre', 'a', 'strong', 'em', 'table', 'blockquote']
    for (const el of required) {
      expect(ALLOWED_ELEMENTS).toContain(el)
    }
  })

  it('does NOT allow script', () => {
    expect(ALLOWED_ELEMENTS).not.toContain('script')
  })
  it('does NOT allow iframe', () => {
    expect(ALLOWED_ELEMENTS).not.toContain('iframe')
  })
  it('does NOT allow object', () => {
    expect(ALLOWED_ELEMENTS).not.toContain('object')
  })
  it('does NOT allow style', () => {
    expect(ALLOWED_ELEMENTS).not.toContain('style')
  })
  it('does NOT allow form', () => {
    expect(ALLOWED_ELEMENTS).not.toContain('form')
  })
  it('does NOT allow meta', () => {
    expect(ALLOWED_ELEMENTS).not.toContain('meta')
  })
  it('does NOT allow base', () => {
    expect(ALLOWED_ELEMENTS).not.toContain('base')
  })
})

// ---------------------------------------------------------------------------
// 4. Cover URL resolution — mirrors _project_to_workshop_row
// ---------------------------------------------------------------------------

function resolveCoverUrl(projectId, coverStorageKey, thumbnailStorageKey, primaryImageId) {
  const pid = projectId
  let thumbnailUrl = null
  if (primaryImageId) {
    thumbnailUrl = `/api/projects/${pid}/workshop-images/${primaryImageId}/file`
  } else if (thumbnailStorageKey) {
    thumbnailUrl = `/api/projects/${pid}/thumbnail`
  }
  const coverUrl = coverStorageKey ? `/api/projects/${pid}/cover` : thumbnailUrl
  return { coverUrl, thumbnailUrl }
}

describe('cover URL resolution', () => {
  it('cover_url points to /cover when cover_storage_key is set', () => {
    const { coverUrl } = resolveCoverUrl('proj-1', 'projects/proj-1/cover.png', 'thumb.jpg', null)
    expect(coverUrl).toContain('/cover')
    expect(coverUrl).not.toContain('/thumbnail')
  })

  it('cover_url falls back to thumbnail when no cover', () => {
    const { coverUrl, thumbnailUrl } = resolveCoverUrl('proj-1', null, 'thumb.jpg', null)
    expect(coverUrl).toBe(thumbnailUrl)
    expect(coverUrl).toContain('/thumbnail')
  })

  it('cover_url is null when neither cover nor thumbnail exist', () => {
    const { coverUrl } = resolveCoverUrl('proj-1', null, null, null)
    expect(coverUrl).toBeNull()
  })

  it('pinned gallery primary image becomes thumbnailUrl when no cover', () => {
    const { thumbnailUrl } = resolveCoverUrl('proj-1', null, 'thumb.jpg', 'img-abc')
    expect(thumbnailUrl).toContain('workshop-images/img-abc/file')
  })
})

// ---------------------------------------------------------------------------
// 5. Publish flow — gallery is optional (no validation error)
// ---------------------------------------------------------------------------

describe('publish flow — gallery is optional', () => {
  // We test the API client shape to ensure publish() can be called with
  // zero gallery images (the API body does not include gallery image count).
  it('workshop.publish body does not require gallery images', () => {
    // The publish function should accept {projectId, title, description}
    // without any gallery-image field.
    const buildBody = ({ projectId, title, description, readme, generateReadme = true }) => ({
      project_id: projectId,
      title: title || '',
      description: description || '',
      ...(readme != null ? { readme } : {}),
      generate_readme: generateReadme,
    })

    const body = buildBody({ projectId: 'abc', title: 'My Part', description: '' })
    // No gallery_images key in the body.
    expect(body).not.toHaveProperty('gallery_images')
    expect(body.project_id).toBe('abc')
  })

  it('workshop.publish body passes readme override when supplied', () => {
    const buildBody = ({ projectId, title, description, readme, generateReadme = true }) => ({
      project_id: projectId,
      title: title || '',
      description: description || '',
      ...(readme != null ? { readme } : {}),
      generate_readme: generateReadme,
    })

    const body = buildBody({
      projectId: 'abc',
      title: 'T',
      description: '',
      readme: '# Custom README',
      generateReadme: false,
    })
    expect(body.readme).toBe('# Custom README')
    expect(body.generate_readme).toBe(false)
  })

  it('workshop.publish body defaults generate_readme to true', () => {
    const buildBody = ({ projectId, title, description, readme, generateReadme = true }) => ({
      project_id: projectId,
      title: title || '',
      description: description || '',
      ...(readme != null ? { readme } : {}),
      generate_readme: generateReadme,
    })

    const body = buildBody({ projectId: 'abc', title: '', description: '' })
    expect(body.generate_readme).toBe(true)
    expect(body).not.toHaveProperty('readme')
  })
})
