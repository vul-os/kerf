// Workshop.test.jsx — vitest coverage for the distributed Workshop UI
// (decisions.md 2026-07-17 "Final form" ADR; docs/distributed-workshop.md).
//
// This repo has no jsdom/@testing-library/react in its test toolchain (see
// src/cloud/GitPanel.test.jsx's header comment) — component tests use
// react-dom/server's renderToStaticMarkup against small, prop-driven
// sub-components, matching the pattern in src/__tests__/wave3UiWiring.test.jsx.
//
// Covers:
//   1. AvailabilityBadge — all four honest states, each with the right
//      data-status + human label (on-node / available / stale / unreachable).
//   2. WorkshopCard — deprecated banner, superseded badge, pin/unpin label.
//   3. BrowseEmptyState — "set of feeds you follow" empty state vs the
//      "nothing published yet" state once feeds exist.
//   4. FollowsPanel — empty state, populated list with remove affordances,
//      the always-present "Add feed" form.
//   5. Source-text: no like/fork/slug-listing language survives from the
//      retired account-based Workshop model.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  AvailabilityBadge, WorkshopCard, BrowseEmptyState, FollowsPanel, BomTable,
} from '../Workshop.jsx'

const __dirname = dirname(fileURLToPath(import.meta.url))
const workshopSrc = readFileSync(join(__dirname, '../Workshop.jsx'), 'utf8')

// ---------------------------------------------------------------------------
// 1. AvailabilityBadge
// ---------------------------------------------------------------------------

describe('AvailabilityBadge', () => {
  it('on-node renders green-ish state with "On this node"', () => {
    const html = renderToStaticMarkup(<AvailabilityBadge availability={{ status: 'on-node' }} />)
    expect(html).toContain('data-status="on-node"')
    expect(html).toContain('On this node')
  })

  it('available renders holder count + relative verified time', () => {
    const html = renderToStaticMarkup(
      <AvailabilityBadge availability={{ status: 'available', holders: 3, last_verified: new Date().toISOString() }} />,
    )
    expect(html).toContain('data-status="available"')
    expect(html).toContain('Available')
    expect(html).toContain('3 holders')
  })

  it('available with exactly 1 holder is singular', () => {
    const html = renderToStaticMarkup(
      <AvailabilityBadge availability={{ status: 'available', holders: 1, last_verified: new Date().toISOString() }} />,
    )
    expect(html).toContain('1 holder,')
    expect(html).not.toContain('1 holders')
  })

  it('stale renders last-seen time', () => {
    const html = renderToStaticMarkup(
      <AvailabilityBadge availability={{ status: 'stale', last_verified: new Date(Date.now() - 86400000).toISOString() }} />,
    )
    expect(html).toContain('data-status="stale"')
    expect(html).toContain('Stale')
  })

  it('unreachable renders with no holder/verified claim', () => {
    const html = renderToStaticMarkup(<AvailabilityBadge availability={{ status: 'unreachable' }} />)
    expect(html).toContain('data-status="unreachable"')
    expect(html).toContain('Unreachable')
  })

  it('missing availability falls back to unreachable, never a fake spinner', () => {
    const html = renderToStaticMarkup(<AvailabilityBadge availability={undefined} />)
    expect(html).toContain('data-status="unreachable"')
  })
})

// ---------------------------------------------------------------------------
// 2. WorkshopCard
// ---------------------------------------------------------------------------

const baseItem = {
  announce_id: 'ann-1',
  pub: 'ed25519:abcdefghijklmnopqrstuvwxyz',
  meta: { name: 'M3 Bracket', description: 'A bracket.', artifact_kind: 'part', license: 'CERN-OHL-S-2.0', units: 'mm', tags: ['bracket'] },
  ts: new Date().toISOString(),
  availability: { status: 'on-node' },
  pinned: false,
}

describe('WorkshopCard', () => {
  it('renders name, kind, license, units', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard item={baseItem} onTogglePin={() => {}} pinBusy={false} />,
    )
    expect(html).toContain('M3 Bracket')
    expect(html).toContain('CERN-OHL-S-2.0')
    expect(html).toContain('mm')
  })

  it('shows a deprecated warning banner when meta.deprecated is true', () => {
    const item = { ...baseItem, meta: { ...baseItem.meta, deprecated: true, deprecated_reason: 'superseded by v2' } }
    const html = renderToStaticMarkup(<WorkshopCard item={item} onTogglePin={() => {}} pinBusy={false} />)
    expect(html).toContain('data-testid="deprecated-banner"')
    expect(html).toContain('Deprecated')
    expect(html).toContain('superseded by v2')
  })

  it('does not show the deprecated banner when meta.deprecated is falsy', () => {
    const html = renderToStaticMarkup(<WorkshopCard item={baseItem} onTogglePin={() => {}} pinBusy={false} />)
    expect(html).not.toContain('data-testid="deprecated-banner"')
  })

  it('shows a "Superseded" badge when the caller flags it', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard item={baseItem} superseded onTogglePin={() => {}} pinBusy={false} />,
    )
    expect(html).toContain('Superseded')
  })

  it('pin toggle reads "Pin" when not pinned, "Unpin" when pinned', () => {
    const notPinned = renderToStaticMarkup(<WorkshopCard item={baseItem} onTogglePin={() => {}} pinBusy={false} />)
    expect(notPinned).toContain('Pin')
    expect(notPinned).not.toContain('Unpin')
    const pinned = renderToStaticMarkup(<WorkshopCard item={{ ...baseItem, pinned: true }} onTogglePin={() => {}} pinBusy={false} />)
    expect(pinned).toContain('Unpin')
  })

  it('pin toggle is disabled while a pin/unpin request is in flight', () => {
    const html = renderToStaticMarkup(<WorkshopCard item={baseItem} onTogglePin={() => {}} pinBusy />)
    expect(html).toMatch(/disabled="?"?[^>]*data-testid="pin-toggle"/)
  })

  it('falls back to a truncated pub key when no follow label is supplied', () => {
    const html = renderToStaticMarkup(<WorkshopCard item={baseItem} onTogglePin={() => {}} pinBusy={false} />)
    expect(html).toContain('ed25519:a')
  })

  it('prefers the follow label over the raw pub key', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard item={baseItem} publisherLabel="Kerf default feed" onTogglePin={() => {}} pinBusy={false} />,
    )
    expect(html).toContain('Kerf default feed')
  })
})

// ---------------------------------------------------------------------------
// 2b. WorkshopCard — BOM action + pin/hydration notes
// ---------------------------------------------------------------------------

describe('WorkshopCard — BOM action', () => {
  it('shows a BOM button for assembly-kind items', () => {
    const item = { ...baseItem, meta: { ...baseItem.meta, artifact_kind: 'assembly' } }
    const html = renderToStaticMarkup(
      <WorkshopCard item={item} onTogglePin={() => {}} pinBusy={false} onOpenBom={() => {}} />,
    )
    expect(html).toContain('data-testid="bom-button"')
  })

  it('does not show a BOM button for non-assembly items', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard item={baseItem} onTogglePin={() => {}} pinBusy={false} />,
    )
    expect(html).not.toContain('data-testid="bom-button"')
  })
})

describe('WorkshopCard — pin hydration states', () => {
  it('shows a success note once hydrated:true', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard
        item={baseItem}
        onTogglePin={() => {}}
        pinBusy={false}
        pinNote={{ kind: 'success' }}
      />,
    )
    expect(html).toContain('data-testid="pin-success-note"')
    expect(html).toContain('now serving from this node')
  })

  it('shows a partial state with a Retry fetch button when pinned but not hydrated', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard
        item={baseItem}
        onTogglePin={() => {}}
        pinBusy={false}
        pinNote={{ kind: 'partial', missingChunks: 3 }}
        onRetryHydrate={() => {}}
        hydrateBusy={false}
      />,
    )
    expect(html).toContain('data-testid="pin-partial-note"')
    expect(html).toContain('3 chunks not yet fetched')
    expect(html).toContain('data-testid="hydrate-retry-button"')
  })

  it('singularizes "chunk" when exactly one is missing', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard
        item={baseItem}
        onTogglePin={() => {}}
        pinBusy={false}
        pinNote={{ kind: 'partial', missingChunks: 1 }}
        onRetryHydrate={() => {}}
        hydrateBusy={false}
      />,
    )
    expect(html).toContain('1 chunk not yet fetched')
    expect(html).not.toContain('1 chunks')
  })

  it('the retry button is disabled while a hydrate retry is in flight', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard
        item={baseItem}
        onTogglePin={() => {}}
        pinBusy={false}
        pinNote={{ kind: 'partial', missingChunks: 2 }}
        onRetryHydrate={() => {}}
        hydrateBusy
      />,
    )
    expect(html).toMatch(/disabled="?"?[^>]*data-testid="hydrate-retry-button"/)
  })

  it('shows an error note when the pin response reports an error', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard
        item={baseItem}
        onTogglePin={() => {}}
        pinBusy={false}
        pinNote={{ kind: 'error', message: 'gateway unreachable' }}
      />,
    )
    expect(html).toContain('data-testid="pin-error-note"')
    expect(html).toContain('gateway unreachable')
  })

  it('shows no pin note at all when pinNote is undefined', () => {
    const html = renderToStaticMarkup(
      <WorkshopCard item={baseItem} onTogglePin={() => {}} pinBusy={false} />,
    )
    expect(html).not.toContain('data-testid="pin-success-note"')
    expect(html).not.toContain('data-testid="pin-partial-note"')
    expect(html).not.toContain('data-testid="pin-error-note"')
  })
})

// ---------------------------------------------------------------------------
// 2c. BomTable — BOM view (§23.6.3)
// ---------------------------------------------------------------------------

describe('BomTable', () => {
  it('shows a loading state', () => {
    const html = renderToStaticMarkup(<BomTable loading error={null} bom={null} />)
    expect(html).toContain('Loading BOM')
  })

  it('shows an error state', () => {
    const html = renderToStaticMarkup(<BomTable loading={false} error="Could not load the BOM." bom={null} />)
    expect(html).toContain('data-testid="bom-error"')
    expect(html).toContain('Could not load the BOM.')
  })

  it('renders one row per part with ref, kind, resolved announce, and quantity', () => {
    const bom = {
      announce_id: 'ann-top',
      parts: [
        { ref: 'ref-aaaaaaaaaaaaaaaaaaaa', ref_kind: 'track', resolved_announce: 'ann-resolved-bbbbbbbbbbbbbbbb', quantity_total: 4 },
        { ref: 'ref-cccccccccccccccccccc', ref_kind: 'pin', resolved_announce: null, quantity_total: 1 },
      ],
      cycles: [],
    }
    const html = renderToStaticMarkup(<BomTable loading={false} error={null} bom={bom} />)
    expect(html).toContain('data-testid="bom-table"')
    expect(html.match(/data-testid="bom-row"/g)).toHaveLength(2)
    expect(html).toContain('track')
    expect(html).toContain('pin')
    expect(html).toContain('4')
    expect(html).toContain('—') // no resolved_announce for the pin leaf
  })

  it('shows an empty state when there are no resolvable parts and no cycles', () => {
    const html = renderToStaticMarkup(<BomTable loading={false} error={null} bom={{ parts: [], cycles: [] }} />)
    expect(html).toContain('data-testid="bom-empty"')
  })

  it('shows a prominent cycle warning naming the offending ref and path', () => {
    const bom = {
      parts: [],
      cycles: [{ ref: 'ref-loop-aaaaaaaaaaaaaaaa', ref_kind: 'track', path: ['ref-loop-aaaaaaaaaaaaaaaa', 'ref-mid-bbbbbbbbbbbbbbbb'] }],
    }
    const html = renderToStaticMarkup(<BomTable loading={false} error={null} bom={bom} />)
    expect(html).toContain('data-testid="bom-cycle-warning"')
    expect(html).toContain('Cycle detected')
    expect(html).toContain('this subtree&#x27;s BOM is not computable')
  })

  it('shows both a cycle warning and a table when the BOM has some resolvable parts alongside a cycle', () => {
    const bom = {
      parts: [{ ref: 'ref-ok', ref_kind: 'track', resolved_announce: 'ann-ok', quantity_total: 1 }],
      cycles: [{ ref: 'ref-loop', ref_kind: 'pin', path: ['ref-loop'] }],
    }
    const html = renderToStaticMarkup(<BomTable loading={false} error={null} bom={bom} />)
    expect(html).toContain('data-testid="bom-cycle-warning"')
    expect(html).toContain('data-testid="bom-table"')
  })
})

// ---------------------------------------------------------------------------
// 3. BrowseEmptyState
// ---------------------------------------------------------------------------

describe('BrowseEmptyState', () => {
  it('explains "a workshop is the set of feeds you follow" when there are no follows', () => {
    const html = renderToStaticMarkup(<BrowseEmptyState hasFollows={false} onGoToFeeds={() => {}} />)
    expect(html).toContain('set of feeds you follow')
    expect(html).toContain('data-testid="workshop-empty-no-follows"')
    expect(html).toContain('Add feed')
  })

  it('shows the "nothing published" state once feeds are followed', () => {
    const html = renderToStaticMarkup(<BrowseEmptyState hasFollows onGoToFeeds={() => {}} />)
    expect(html).toContain('data-testid="workshop-empty"')
    expect(html).not.toContain('set of feeds you follow')
  })
})

// ---------------------------------------------------------------------------
// 4. FollowsPanel — follows CRUD surface
// ---------------------------------------------------------------------------

describe('FollowsPanel', () => {
  it('shows the empty state + explanation when there are no follows', () => {
    const html = renderToStaticMarkup(
      <FollowsPanel follows={[]} loading={false} error={null} onAdd={async () => {}} onRemove={async () => {}} />,
    )
    expect(html).toContain('data-testid="follows-empty"')
    expect(html).toContain('set of feeds you follow')
  })

  it('lists each followed feed with a label/pub and a remove button', () => {
    const follows = [
      { pub: 'ed25519:aaaa111122223333', label: 'Kerf default feed', gateway_url: 'https://kerf.sh' },
      { pub: 'ed25519:bbbb444455556666', label: '', gateway_url: 'https://example.com' },
    ]
    const html = renderToStaticMarkup(
      <FollowsPanel follows={follows} loading={false} error={null} onAdd={async () => {}} onRemove={async () => {}} />,
    )
    expect(html).toContain('data-testid="follows-list"')
    expect(html).toContain('Kerf default feed')
    // Second follow has no label — falls back to a truncated pub key, not
    // blank; the full key is still present via the title attribute.
    expect(html).toContain('title="ed25519:bbbb444455556666"')
    expect(html).toContain('556666')
    expect(html).toContain('Unfollow')
  })

  it('always renders the Add feed form (pub key, label, gateway URL)', () => {
    const html = renderToStaticMarkup(
      <FollowsPanel follows={[]} loading={false} error={null} onAdd={async () => {}} onRemove={async () => {}} />,
    )
    expect(html).toContain('Publisher key')
    expect(html).toContain('Gateway URL')
    expect(html).toContain('Add feed')
  })

  it('surfaces a load error banner without hiding the add form', () => {
    const html = renderToStaticMarkup(
      <FollowsPanel follows={[]} loading={false} error="Could not load feeds." onAdd={async () => {}} onRemove={async () => {}} />,
    )
    expect(html).toContain('Could not load feeds.')
    expect(html).toContain('Add feed')
  })
})

// ---------------------------------------------------------------------------
// 5. Source-text: the retired account-based Workshop model is gone
// ---------------------------------------------------------------------------

describe('Workshop.jsx — retired account-based model is gone', () => {
  it('does not reference likes/forks/slugs from the old hosted listings model', () => {
    expect(workshopSrc).not.toContain('toggleLike')
    expect(workshopSrc).not.toContain('liked_by_me')
    expect(workshopSrc).not.toContain('.fork(')
    expect(workshopSrc).not.toContain('/api/workshop/')
  })

  it('is not gated behind cloudEnabled — a core MIT node capability', () => {
    // The file may explain in a comment that it's deliberately ungated;
    // it must never actually branch on the flag (e.g. `cloudEnabled &&`).
    expect(workshopSrc).not.toMatch(/cloudEnabled\s*&&/)
    expect(workshopSrc).not.toMatch(/\{cloudEnabled\}/)
  })

  it('drives the pub client, not the old workshop client', () => {
    expect(workshopSrc).toContain("from './api.js'")
    expect(workshopSrc).toContain('pub.listWorkshop')
    expect(workshopSrc).toContain('pub.listFollows')
  })

  it('drives the BOM view and pin-hydration retry through the pub client', () => {
    expect(workshopSrc).toContain('pub.bom')
    expect(workshopSrc).toContain('pub.hydratePin')
  })

  it('refreshes the workshop list after a pin/hydrate action so badges catch up', () => {
    // applyPinResult() is the shared handler behind pin() and hydratePin();
    // it must call loadAll() so availability badges (server-derived) update.
    const applyBody = workshopSrc.slice(
      workshopSrc.indexOf('const applyPinResult'),
      workshopSrc.indexOf('const onTogglePin'),
    )
    expect(applyBody).toContain('loadAll()')
  })
})
