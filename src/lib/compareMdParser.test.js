/**
 * compareMdParser.test.js — unit tests for parseFrontmatter + parseCompareMd.
 */

import { describe, it, expect } from 'vitest'
import { parseFrontmatter, parseCompareMd } from './compareMdParser.js'

// ── parseFrontmatter ──────────────────────────────────────────────────────────

describe('parseFrontmatter', () => {
  it('returns empty data + original body when no front-matter block', () => {
    const raw = '# Hello\n\nParagraph.'
    const { data, body } = parseFrontmatter(raw)
    expect(data).toEqual({})
    expect(body).toBe(raw)
  })

  it('parses a simple front-matter block', () => {
    const raw = '---\nslug: fusion\ncompetitor: Autodesk Fusion 360\n---\n# Body'
    const { data, body } = parseFrontmatter(raw)
    expect(data.slug).toBe('fusion')
    expect(data.competitor).toBe('Autodesk Fusion 360')
    expect(body).toBe('# Body')
  })

  it('strips double quotes from string values', () => {
    const raw = '---\nhero_tagline: "Two tools, two models"\n---\n'
    const { data } = parseFrontmatter(raw)
    expect(data.hero_tagline).toBe('Two tools, two models')
  })

  it('strips single quotes from string values', () => {
    const raw = "---\nhero_tagline: 'Two tools'\n---\n"
    const { data } = parseFrontmatter(raw)
    expect(data.hero_tagline).toBe('Two tools')
  })

  it('converts integer strings to numbers', () => {
    const raw = '---\norder: 3\n---\n'
    const { data } = parseFrontmatter(raw)
    expect(data.order).toBe(3)
    expect(typeof data.order).toBe('number')
  })

  it('handles CRLF line endings', () => {
    const raw = '---\r\nslug: kicad\r\n---\r\n# Title'
    const { data, body } = parseFrontmatter(raw)
    expect(data.slug).toBe('kicad')
    expect(body).toBe('# Title')
  })

  it('returns empty data and full string for null/undefined input', () => {
    expect(parseFrontmatter(null)).toEqual({ data: {}, body: '' })
    expect(parseFrontmatter(undefined)).toEqual({ data: {}, body: '' })
    expect(parseFrontmatter('')).toEqual({ data: {}, body: '' })
  })

  it('ignores comment lines in the YAML block', () => {
    const raw = '---\n# this is a comment\nslug: rhino\n---\n'
    const { data } = parseFrontmatter(raw)
    expect(data.slug).toBe('rhino')
    expect(data['# this is a comment']).toBeUndefined()
  })

  it('returns body with at least one leading newline stripped', () => {
    const raw = '---\nslug: test\n---\n# Heading'
    const { body } = parseFrontmatter(raw)
    // Immediately-following content (no blank line) should not have a leading newline
    expect(body.startsWith('# Heading')).toBe(true)
  })

  it('returns body containing the heading even when preceded by a blank line', () => {
    const raw = '---\nslug: test\n---\n\n# Heading'
    const { body } = parseFrontmatter(raw)
    // The closing --- strips one \n; a blank line leaves \n# Heading
    expect(body).toContain('# Heading')
  })
})

// ── parseCompareMd ────────────────────────────────────────────────────────────

describe('parseCompareMd', () => {
  const FULL_MD = `---
slug: fusion
competitor: Autodesk Fusion 360
category: cad-mechanical
left: right-vendor
right: fusion
hero_tagline: "Two CAD tools, two cognitive models"
reviewed_at: 2026-05-19
order: 1
---
# Kerf vs Fusion 360

Intro paragraph that describes both tools.

## Where Fusion is strong

- **CAM.** HSMWorks lineage.

## Side by side

| Feature | Fusion 360 | Kerf |
|---|---|---|
| License | ⚠️ Proprietary | ✅ MIT |
`

  it('parses all front-matter fields', () => {
    const meta = parseCompareMd(FULL_MD)
    expect(meta.slug).toBe('fusion')
    expect(meta.competitor).toBe('Autodesk Fusion 360')
    expect(meta.category).toBe('cad-mechanical')
    expect(meta.hero_tagline).toBe('Two CAD tools, two cognitive models')
    expect(meta.right).toBe('fusion')
    expect(meta.reviewed_at).toBe('2026-05-19')
    expect(meta.order).toBe(1)
  })

  it('ALWAYS sets left to "kerf" regardless of front-matter left: value', () => {
    // The front-matter says left: right-vendor — must be overridden.
    const meta = parseCompareMd(FULL_MD)
    expect(meta.left).toBe('kerf')
  })

  it('left is "kerf" even when front-matter is absent', () => {
    const meta = parseCompareMd('# Some compare page\n\nBody text.')
    expect(meta.left).toBe('kerf')
  })

  it('extracts the title from the first H1', () => {
    const meta = parseCompareMd(FULL_MD)
    expect(meta.title).toBe('Kerf vs Fusion 360')
  })

  it('body contains the markdown content after front-matter', () => {
    const meta = parseCompareMd(FULL_MD)
    expect(meta.body).toContain('# Kerf vs Fusion 360')
    expect(meta.body).toContain('## Where Fusion is strong')
  })

  it('uses slugFallback when front-matter slug is absent', () => {
    const md = '---\ncompetitor: KiCad\n---\n# Kerf vs KiCad'
    const meta = parseCompareMd(md, 'kicad')
    expect(meta.slug).toBe('kicad')
  })

  it('returns empty string defaults for missing string fields', () => {
    const meta = parseCompareMd('')
    expect(meta.slug).toBe('')
    expect(meta.competitor).toBe('')
    expect(meta.category).toBe('')
    expect(meta.hero_tagline).toBe('')
  })

  it('returns null for missing reviewed_at', () => {
    const meta = parseCompareMd('---\nslug: test\n---\n')
    expect(meta.reviewed_at).toBeNull()
  })

  it('returns null for missing order', () => {
    const meta = parseCompareMd('---\nslug: test\n---\n')
    expect(meta.order).toBeNull()
  })
})
