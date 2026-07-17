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
})
