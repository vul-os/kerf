// PublishButton.test.jsx — vitest coverage for the distributed Workshop
// publish flow (decisions.md 2026-07-17 "Final form" ADR; dmtap §22.7's
// normative irrevocability-warning MUST; docs/distributed-workshop.md
// "Publishing is irrevocable").
//
// Component tests render the step sub-components directly via
// react-dom/server's renderToStaticMarkup (no jsdom/@testing-library/react
// in this repo's toolchain — see src/cloud/GitPanel.test.jsx), which lets us
// assert on a given step's markup without driving PublishModal's internal
// async orchestration (identity check + publish call).
//
// Covers:
//   1. Identity prompt step + identity-created step (pub key + back-it-up note).
//   2. Metadata form — Continue is gated on name + license + units being set.
//   3. Confirmation step — the exact irrevocability warning text renders,
//      and Publish stays disabled until the "I understand" box is checked.
//   4. No "Unpublish" surface anywhere (irrevocable, no takedown).

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  IdentityStep, IdentityCreatedStep, MetadataStep, ConfirmStep, SuccessStep,
  ChildrenStep, emptyChildRow, isChildRowValid, buildChildrenPayload,
} from '../PublishButton.jsx'

const __dirname = dirname(fileURLToPath(import.meta.url))
const publishSrc = readFileSync(join(__dirname, '../PublishButton.jsx'), 'utf8')

const emptyForm = {
  name: '', description: '', kind: 'part', units: 'mm',
  licensePreset: '', licenseCustom: '', tagsRaw: '',
}

// ---------------------------------------------------------------------------
// 1. Identity steps
// ---------------------------------------------------------------------------

describe('IdentityStep', () => {
  it('prompts to create a publishing identity, not an account', () => {
    const html = renderToStaticMarkup(<IdentityStep identityError={null} creating={false} onCreate={() => {}} />)
    expect(html).toContain('Create your publishing identity')
    expect(html).toContain("isn&#x27;t an account with")
  })

  it('surfaces an identity error inline', () => {
    const html = renderToStaticMarkup(<IdentityStep identityError="offline" creating={false} onCreate={() => {}} />)
    expect(html).toContain('offline')
  })
})

describe('IdentityCreatedStep', () => {
  it('shows the new pub key and a "back it up" note', () => {
    const html = renderToStaticMarkup(<IdentityCreatedStep pubKey="ed25519:deadbeef" onContinue={() => {}} />)
    expect(html).toContain('ed25519:deadbeef')
    expect(html).toContain('back it up')
  })
})

// ---------------------------------------------------------------------------
// 2. Metadata form validation
// ---------------------------------------------------------------------------

describe('MetadataStep — required fields gate Continue', () => {
  it('Continue is disabled when the form is empty (no name, no license)', () => {
    const html = renderToStaticMarkup(
      <MetadataStep form={emptyForm} setForm={() => {}} error={null} onContinue={() => {}} />,
    )
    expect(html).toMatch(/disabled=""[^>]*>\s*Continue/)
  })

  it('Continue stays disabled with a name but no license chosen', () => {
    const form = { ...emptyForm, name: 'M3 Bracket' }
    const html = renderToStaticMarkup(
      <MetadataStep form={form} setForm={() => {}} error={null} onContinue={() => {}} />,
    )
    expect(html).toMatch(/disabled=""[^>]*>\s*Continue/)
  })

  it('Continue is enabled once name + a preset license + units are set', () => {
    const form = { ...emptyForm, name: 'M3 Bracket', licensePreset: 'MIT' }
    const html = renderToStaticMarkup(
      <MetadataStep form={form} setForm={() => {}} error={null} onContinue={() => {}} />,
    )
    expect(html).not.toMatch(/disabled=""[^>]*>\s*Continue/)
  })

  it('a custom SPDX expression counts as the license once filled in', () => {
    const emptyCustom = { ...emptyForm, name: 'M3 Bracket', licensePreset: '__custom__', licenseCustom: '' }
    const emptyCustomHtml = renderToStaticMarkup(
      <MetadataStep form={emptyCustom} setForm={() => {}} error={null} onContinue={() => {}} />,
    )
    expect(emptyCustomHtml).toMatch(/disabled=""[^>]*>\s*Continue/)

    const filledCustom = { ...emptyCustom, licenseCustom: 'TAPR-OHL-1.0' }
    const filledHtml = renderToStaticMarkup(
      <MetadataStep form={filledCustom} setForm={() => {}} error={null} onContinue={() => {}} />,
    )
    expect(filledHtml).not.toMatch(/disabled=""[^>]*>\s*Continue/)
    expect(filledHtml).toContain('SPDX expression')
  })

  it('units defaults to mm and is offered alongside cm/m/in/ft', () => {
    const html = renderToStaticMarkup(
      <MetadataStep form={emptyForm} setForm={() => {}} error={null} onContinue={() => {}} />,
    )
    for (const u of ['mm', 'cm', 'm', 'in', 'ft']) {
      expect(html).toContain(`>${u}<`)
    }
  })

  it('offers common SPDX licenses including CERN-OHL variants', () => {
    const html = renderToStaticMarkup(
      <MetadataStep form={emptyForm} setForm={() => {}} error={null} onContinue={() => {}} />,
    )
    expect(html).toContain('CERN-OHL-S-2.0')
    expect(html).toContain('CERN-OHL-W-2.0')
    expect(html).toContain('CERN-OHL-P-2.0')
    expect(html).toContain('CC-BY-4.0')
    expect(html).toContain('MIT')
  })

  it('offers every artifact kind from the contract', () => {
    const html = renderToStaticMarkup(
      <MetadataStep form={emptyForm} setForm={() => {}} error={null} onContinue={() => {}} />,
    )
    for (const kind of ['Part', 'Assembly', 'PCB', 'Schematic', 'Drawing', 'Dataset', 'Doc']) {
      expect(html).toContain(kind)
    }
  })
})

// ---------------------------------------------------------------------------
// 2b. Assembly children (§23.6.2) — pin/track picker
// ---------------------------------------------------------------------------

describe('emptyChildRow / isChildRowValid / buildChildrenPayload', () => {
  it('a fresh row defaults to track with quantity 1', () => {
    expect(emptyChildRow()).toEqual({ refKind: 'track', announceId: '', manifestRoot: '', quantity: 1 })
  })

  it('a track row is valid only once an announce is chosen', () => {
    expect(isChildRowValid({ refKind: 'track', announceId: '', manifestRoot: '', quantity: 1 })).toBe(false)
    expect(isChildRowValid({ refKind: 'track', announceId: 'ann-1', manifestRoot: '', quantity: 1 })).toBe(true)
  })

  it('a pin row is valid only once a manifest_root is filled in', () => {
    expect(isChildRowValid({ refKind: 'pin', announceId: '', manifestRoot: '  ', quantity: 1 })).toBe(false)
    expect(isChildRowValid({ refKind: 'pin', announceId: '', manifestRoot: 'root-1', quantity: 1 })).toBe(true)
  })

  it('quantity must be a positive integer', () => {
    expect(isChildRowValid({ refKind: 'track', announceId: 'ann-1', manifestRoot: '', quantity: 0 })).toBe(false)
    expect(isChildRowValid({ refKind: 'track', announceId: 'ann-1', manifestRoot: '', quantity: -1 })).toBe(false)
    expect(isChildRowValid({ refKind: 'track', announceId: 'ann-1', manifestRoot: '', quantity: 1.5 })).toBe(false)
    expect(isChildRowValid({ refKind: 'track', announceId: 'ann-1', manifestRoot: '', quantity: 2 })).toBe(true)
  })

  it('builds the exact publish payload shape: track sends announce_id, pin sends manifest_root', () => {
    const rows = [
      { refKind: 'track', announceId: 'ann-child-1', manifestRoot: '', quantity: 2 },
      { refKind: 'pin', announceId: '', manifestRoot: '  root-xyz  ', quantity: '3' },
    ]
    expect(buildChildrenPayload(rows)).toEqual([
      { ref_kind: 'track', announce_id: 'ann-child-1', quantity: 2 },
      { ref_kind: 'pin', manifest_root: 'root-xyz', quantity: 3 },
    ])
  })
})

describe('ChildrenStep', () => {
  const candidates = [
    { announce_id: 'ann-1', name: 'M3 Bracket', kind: 'part' },
    { announce_id: 'ann-2', name: 'Gearbox v1', kind: 'assembly' },
  ]

  it('requires at least one child — Continue is disabled with zero rows', () => {
    const html = renderToStaticMarkup(
      <ChildrenStep
        rows={[]}
        setRows={() => {}}
        candidates={candidates}
        candidatesLoading={false}
        candidatesError={null}
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('data-testid="no-children-hint"')
    expect(html).toMatch(/disabled=""[^>]*data-testid="children-continue-button"/)
  })

  it('an incomplete track row (no announce chosen) keeps Continue disabled', () => {
    const html = renderToStaticMarkup(
      <ChildrenStep
        rows={[emptyChildRow()]}
        setRows={() => {}}
        candidates={candidates}
        candidatesLoading={false}
        candidatesError={null}
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toMatch(/disabled=""[^>]*data-testid="children-continue-button"/)
  })

  it('a valid track row (announce chosen, quantity set) enables Continue', () => {
    const html = renderToStaticMarkup(
      <ChildrenStep
        rows={[{ refKind: 'track', announceId: 'ann-1', manifestRoot: '', quantity: 1 }]}
        setRows={() => {}}
        candidates={candidates}
        candidatesLoading={false}
        candidatesError={null}
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).not.toMatch(/disabled=""[^>]*data-testid="children-continue-button"/)
  })

  it('the picker lists candidate name + kind for track rows', () => {
    const html = renderToStaticMarkup(
      <ChildrenStep
        rows={[emptyChildRow()]}
        setRows={() => {}}
        candidates={candidates}
        candidatesLoading={false}
        candidatesError={null}
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('M3 Bracket')
    expect(html).toContain('Gearbox v1')
    expect(html).toContain('data-testid="child-announce-select"')
  })

  it('a pin row (advanced) shows a free-text manifest-root input instead of the picker', () => {
    const html = renderToStaticMarkup(
      <ChildrenStep
        rows={[{ refKind: 'pin', announceId: '', manifestRoot: '', quantity: 1 }]}
        setRows={() => {}}
        candidates={candidates}
        candidatesLoading={false}
        candidatesError={null}
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('data-testid="child-manifest-root-input"')
    expect(html).not.toContain('data-testid="child-announce-select"')
    expect(html).toContain('Pin (advanced)')
  })

  it('explains pin vs track in one line each', () => {
    const trackHtml = renderToStaticMarkup(
      <ChildrenStep
        rows={[emptyChildRow()]}
        setRows={() => {}}
        candidates={candidates}
        candidatesLoading={false}
        candidatesError={null}
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(trackHtml).toContain('Track = follows the author&#x27;s latest revision')

    const pinHtml = renderToStaticMarkup(
      <ChildrenStep
        rows={[{ refKind: 'pin', announceId: '', manifestRoot: '', quantity: 1 }]}
        setRows={() => {}}
        candidates={candidates}
        candidatesLoading={false}
        candidatesError={null}
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(pinHtml).toContain('Pin = exact bytes forever')
  })

  it('surfaces a candidates-fetch error without blocking the pin row option', () => {
    const html = renderToStaticMarkup(
      <ChildrenStep
        rows={[emptyChildRow()]}
        setRows={() => {}}
        candidates={[]}
        candidatesLoading={false}
        candidatesError="Could not load your published artifacts."
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('Could not load your published artifacts.')
    expect(html).toContain('Pin (advanced)')
  })

  it('renders one row per entry with a remove button and an add-child button', () => {
    const html = renderToStaticMarkup(
      <ChildrenStep
        rows={[emptyChildRow(), emptyChildRow()]}
        setRows={() => {}}
        candidates={candidates}
        candidatesLoading={false}
        candidatesError={null}
        error={null}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html.match(/data-testid="assembly-child-row"/g)).toHaveLength(2)
    expect(html.match(/data-testid="remove-child-row"/g)).toHaveLength(2)
    expect(html).toContain('data-testid="add-child-row"')
  })
})

// ---------------------------------------------------------------------------
// 3. Irrevocability confirmation step
// ---------------------------------------------------------------------------

describe('ConfirmStep — explicit irrevocability confirmation (dmtap §22.7)', () => {
  it('renders the exact required warning text', () => {
    const html = renderToStaticMarkup(
      <ConfirmStep form={emptyForm} submitting={false} error={null} onBack={() => {}} onConfirm={() => {}} />,
    )
    expect(html).toContain('data-testid="irrevocable-warning"')
    expect(html).toContain(
      'Publishing is public and irrevocable — a published artifact cannot be unpublished.',
    )
  })

  it('the Publish button starts disabled until the "I understand" box is checked', () => {
    const html = renderToStaticMarkup(
      <ConfirmStep form={emptyForm} submitting={false} error={null} onBack={() => {}} onConfirm={() => {}} />,
    )
    // The checkbox itself must default unchecked...
    expect(html).not.toMatch(/data-testid="irrevocable-ack-checkbox"[^>]*checked/)
    // ...and the confirm button must be disabled as a result.
    expect(html).toMatch(/disabled=""[^>]*data-testid="confirm-publish-button"/)
  })

  it('surfaces a submit error inline without losing the warning', () => {
    const html = renderToStaticMarkup(
      <ConfirmStep form={emptyForm} submitting={false} error="Publish failed." onBack={() => {}} onConfirm={() => {}} />,
    )
    expect(html).toContain('Publish failed.')
    expect(html).toContain('data-testid="irrevocable-warning"')
  })
})

describe('SuccessStep', () => {
  it('shows the returned announce_id', () => {
    const html = renderToStaticMarkup(<SuccessStep announceId="ann-123" onClose={() => {}} />)
    expect(html).toContain('ann-123')
  })
})

// ---------------------------------------------------------------------------
// 4. No unpublish surface; drives pub.publish, not the old workshop.publish
// ---------------------------------------------------------------------------

describe('PublishButton.jsx — irrevocable, no takedown', () => {
  it('has no Unpublish button/handler anywhere (prose mentioning "unpublished" is fine)', () => {
    expect(publishSrc).not.toContain('onUnpublish')
    expect(publishSrc).not.toMatch(/workshop\.unpublish/)
    expect(publishSrc).not.toMatch(/>\s*Unpublish\s*</)
  })

  it('drives pub.publish with the new metadata contract, not the old workshop API', () => {
    expect(publishSrc).toContain('pub.publish')
    expect(publishSrc).toContain('pub.getIdentity')
    expect(publishSrc).toContain('pub.createIdentity')
    expect(publishSrc).not.toContain('workshop.publish')
    expect(publishSrc).not.toContain('generateReadme')
  })

  it('fetches assembly-candidates for the children picker and sends children on publish', () => {
    expect(publishSrc).toContain('pub.assemblyCandidates')
    expect(publishSrc).toContain('buildChildrenPayload(childRows)')
  })
})
