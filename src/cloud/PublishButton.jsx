// PublishButton — toolbar drop-in for the editor. Publishes a project to
// the distributed Workshop over DMTAP-PUB (decisions.md's 2026-07-17
// "Final form" ADR; docs/distributed-workshop.md).
//
// Flow:
//   1. Check for a local publishing identity (Ed25519 keypair). If absent,
//      prompt to create one first — it signs every publish and is not an
//      account with anyone.
//   2. Collect metadata: name, description, artifact kind, SPDX license
//      (required), length unit (required, mm default), tags.
//   3. Explicit confirmation step warning that publishing is irrevocable —
//      normative client MUST per dmtap §22.7 — before the actual publish
//      call fires.
//   4. Show the resulting announce_id on success.
//
// There is no "Unpublish" — once published, an object may be swarmed to
// other holders and there is no protocol-level takedown (see
// docs/distributed-workshop.md "Publishing is irrevocable"). Superseding or
// deprecating a mistake is a future publish, not a delete.

import { useEffect, useState } from 'react'
import {
  AlertCircle, Check, Copy, Globe, KeyRound, Loader2, ShieldAlert,
} from 'lucide-react'
import Modal from '../components/Modal.jsx'
import Button from '../components/Button.jsx'
import Input, { Textarea } from '../components/Input.jsx'
import { ApiError } from '../lib/api.js'
import { pub } from './api.js'

const KIND_OPTIONS = [
  { value: 'part', label: 'Part' },
  { value: 'assembly', label: 'Assembly' },
  { value: 'pcb', label: 'PCB' },
  { value: 'schematic', label: 'Schematic' },
  { value: 'drawing', label: 'Drawing' },
  { value: 'dataset', label: 'Dataset' },
  { value: 'doc', label: 'Doc' },
]

// Common SPDX identifiers relevant to hardware/CAD publishing, per
// docs/distributed-workshop.md ("CERN-OHL for hardware, MIT/Apache-2.0 for
// accompanying software/firmware, CC-BY/CC0 for docs, and more"). A free-text
// fallback covers anything not on this shortlist — the field is a required
// SPDX *expression*, not constrained to this exact set.
const LICENSE_OPTIONS = [
  'CERN-OHL-S-2.0',
  'CERN-OHL-W-2.0',
  'CERN-OHL-P-2.0',
  'MIT',
  'Apache-2.0',
  'GPL-3.0-only',
  'CC-BY-4.0',
  'CC-BY-SA-4.0',
  'CC0-1.0',
]
const CUSTOM_LICENSE = '__custom__'

const UNIT_OPTIONS = ['mm', 'cm', 'm', 'in', 'ft']

const IRREVOCABLE_WARNING =
  'Publishing is public and irrevocable — a published artifact cannot be unpublished.'

export function IdentityStep({ identityError, creating, onCreate }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-2.5 rounded-lg border border-ink-800 bg-ink-850/40 p-4">
        <KeyRound size={16} className="mt-0.5 text-kerf-300 shrink-0" />
        <div className="text-sm text-ink-300 leading-relaxed">
          Publishing signs an announcement with your identity key so anyone
          can verify you as the publisher. This isn&apos;t an account with
          anyone — it&apos;s a local Ed25519 keypair kept on this node.
        </div>
      </div>
      {identityError && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <span>{identityError}</span>
        </div>
      )}
      <Button variant="primary" size="md" onClick={onCreate} disabled={creating} className="self-start">
        {creating
          ? <><Loader2 size={14} className="animate-spin" /> Creating…</>
          : <><KeyRound size={14} /> Create your publishing identity</>}
      </Button>
    </div>
  )
}

export function IdentityCreatedStep({ pubKey, onContinue }) {
  const [copied, setCopied] = useState(false)
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(pubKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* clipboard unavailable — the key is still shown inline */ }
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4">
        <Check size={16} className="mt-0.5 text-emerald-300 shrink-0" />
        <div className="text-sm text-emerald-100 leading-relaxed">
          Publishing identity created. This key signs everything you publish
          from this node — <strong>back it up</strong>; there is no account
          recovery for it.
        </div>
      </div>
      <div className="flex items-center gap-2 rounded-lg bg-ink-950 border border-ink-800 px-3 py-2">
        <code className="flex-1 text-xs font-mono text-ink-200 break-all">{pubKey}</code>
        <button
          type="button"
          onClick={onCopy}
          className="p-1.5 rounded text-ink-400 hover:text-ink-100 hover:bg-ink-800 shrink-0"
          title="Copy to clipboard"
        >
          {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
        </button>
      </div>
      <Button variant="primary" size="md" onClick={onContinue} className="self-start">
        Continue to publish
      </Button>
    </div>
  )
}

export function MetadataStep({ form, setForm, error, onContinue }) {
  const licenseIsCustom = form.licensePreset === CUSTOM_LICENSE
  const valid = form.name.trim() && (licenseIsCustom ? form.licenseCustom.trim() : form.licensePreset) && form.units

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); if (valid) onContinue() }}
      className="flex flex-col gap-4"
    >
      <Input
        label="Name"
        value={form.name}
        onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
        required
      />
      <Textarea
        label="Description"
        rows={3}
        value={form.description}
        onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        placeholder="What is it? Who's it for?"
      />

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-ink-200 tracking-wide uppercase">Kind</span>
          <select
            value={form.kind}
            onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}
            className="h-10 rounded-lg bg-ink-900 border border-ink-700 px-3 text-sm text-ink-100 focus:outline-none focus:border-kerf-300 focus:ring-4 focus:ring-kerf-300/20"
          >
            {KIND_OPTIONS.map((k) => (
              <option key={k.value} value={k.value}>{k.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-ink-200 tracking-wide uppercase">Length unit</span>
          <select
            value={form.units}
            onChange={(e) => setForm((f) => ({ ...f, units: e.target.value }))}
            className="h-10 rounded-lg bg-ink-900 border border-ink-700 px-3 text-sm text-ink-100 focus:outline-none focus:border-kerf-300 focus:ring-4 focus:ring-kerf-300/20"
          >
            {UNIT_OPTIONS.map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-ink-200 tracking-wide uppercase">
          License <span className="text-red-400">*</span>
        </span>
        <select
          value={form.licensePreset}
          onChange={(e) => setForm((f) => ({ ...f, licensePreset: e.target.value }))}
          className="h-10 rounded-lg bg-ink-900 border border-ink-700 px-3 text-sm text-ink-100 focus:outline-none focus:border-kerf-300 focus:ring-4 focus:ring-kerf-300/20"
        >
          <option value="">Choose a license…</option>
          {LICENSE_OPTIONS.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
          <option value={CUSTOM_LICENSE}>Other SPDX expression…</option>
        </select>
      </label>
      {licenseIsCustom && (
        <Input
          label="SPDX expression"
          placeholder="e.g. TAPR-OHL-1.0"
          value={form.licenseCustom}
          onChange={(e) => setForm((f) => ({ ...f, licenseCustom: e.target.value }))}
        />
      )}

      <Input
        label="Tags (comma-separated)"
        placeholder="bracket, 3d-printed, m3"
        value={form.tagsRaw}
        onChange={(e) => setForm((f) => ({ ...f, tagsRaw: e.target.value }))}
      />

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <Button type="submit" variant="primary" size="md" disabled={!valid} className="self-start">
        Continue
      </Button>
    </form>
  )
}

export function ConfirmStep({ form, submitting, error, onBack, onConfirm }) {
  const [ack, setAck] = useState(false)
  return (
    <div className="flex flex-col gap-4">
      <div
        className="flex items-start gap-2.5 rounded-lg border border-red-500/40 bg-red-500/10 p-4"
        role="alert"
        data-testid="irrevocable-warning"
      >
        <ShieldAlert size={18} className="mt-0.5 text-red-300 shrink-0" />
        <p className="text-sm text-red-100 leading-relaxed font-medium">
          {IRREVOCABLE_WARNING}
        </p>
      </div>
      <p className="text-xs text-ink-400 leading-relaxed">
        As soon as any other node holds a copy, there is no mechanism —
        protocol-level or otherwise — to force that copy to disappear. You
        can publish a corrected revision later (supersede) or mark this one
        deprecated, but you cannot delete it from the network.
      </p>
      <label className="flex items-center gap-2.5 text-sm text-ink-200 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={ack}
          onChange={(e) => setAck(e.target.checked)}
          className="w-4 h-4 rounded border-ink-600 bg-ink-900 text-kerf-300 focus:ring-kerf-300/40"
          data-testid="irrevocable-ack-checkbox"
        />
        I understand this cannot be undone.
      </label>
      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="md" onClick={onBack} disabled={submitting}>
          Back
        </Button>
        <Button
          variant="primary"
          size="md"
          onClick={onConfirm}
          disabled={!ack || submitting}
          data-testid="confirm-publish-button"
        >
          {submitting
            ? <><Loader2 size={14} className="animate-spin" /> Publishing…</>
            : <><Globe size={14} /> Publish permanently</>}
        </Button>
      </div>
    </div>
  )
}

export function SuccessStep({ announceId, onClose }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4">
        <Check size={16} className="mt-0.5 text-emerald-300 shrink-0" />
        <div className="text-sm text-emerald-100 leading-relaxed">
          Published. Anyone following your feed can see it now.
        </div>
      </div>
      <div className="rounded-lg bg-ink-950 border border-ink-800 px-3 py-2">
        <p className="text-[10px] uppercase tracking-widest font-mono text-ink-500">Announcement</p>
        <code className="text-xs font-mono text-ink-200 break-all">{announceId}</code>
      </div>
      <Button variant="primary" size="md" onClick={onClose} className="self-start">
        Done
      </Button>
    </div>
  )
}

function PublishModal({ open, onClose, project, onPublished }) {
  const [step, setStep] = useState('loading') // loading | identity | identity-created | form | confirm | success
  const [identityError, setIdentityError] = useState(null)
  const [creatingIdentity, setCreatingIdentity] = useState(false)
  const [newPubKey, setNewPubKey] = useState(null)

  const [form, setForm] = useState(() => ({
    name: project?.name || '',
    description: '',
    kind: 'part',
    units: 'mm',
    licensePreset: '',
    licenseCustom: '',
    tagsRaw: '',
  }))
  const [formError, setFormError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [announceId, setAnnounceId] = useState(null)

  useEffect(() => {
    if (!open) return
    setStep('loading')
    setIdentityError(null)
    setSubmitError(null)
    setFormError(null)
    setAnnounceId(null)
    setForm({
      name: project?.name || '',
      description: '',
      kind: 'part',
      units: 'mm',
      licensePreset: '',
      licenseCustom: '',
      tagsRaw: '',
    })
    pub.getIdentity()
      .then((res) => {
        if (res?.pub) setStep('form')
        else setStep('identity')
      })
      .catch((err) => {
        setIdentityError(err instanceof ApiError ? err.message : 'Could not check publishing identity.')
        setStep('identity')
      })
  }, [open, project?.id, project?.name])

  if (!open) return null

  const onCreateIdentity = async () => {
    setCreatingIdentity(true)
    setIdentityError(null)
    try {
      const res = await pub.createIdentity()
      setNewPubKey(res?.pub || '')
      setStep('identity-created')
    } catch (err) {
      setIdentityError(err instanceof ApiError ? err.message : 'Could not create identity.')
    } finally {
      setCreatingIdentity(false)
    }
  }

  const onConfirmPublish = async () => {
    setSubmitting(true)
    setSubmitError(null)
    try {
      const license = form.licensePreset === CUSTOM_LICENSE ? form.licenseCustom.trim() : form.licensePreset
      const tags = form.tagsRaw.split(',').map((t) => t.trim()).filter(Boolean)
      const res = await pub.publish({
        projectId: project.id,
        metadata: {
          name: form.name.trim(),
          description: form.description.trim(),
          artifact_kind: form.kind,
          license,
          units: form.units,
          tags,
        },
      })
      setAnnounceId(res?.announce_id || null)
      setStep('success')
      onPublished?.(res)
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : 'Publish failed.')
    } finally {
      setSubmitting(false)
    }
  }

  const titles = {
    loading: 'Publish to Workshop',
    identity: 'Create your publishing identity',
    'identity-created': 'Publishing identity created',
    form: 'Publish to Workshop',
    confirm: 'Confirm publish',
    success: 'Published',
  }

  return (
    <Modal open={open} onClose={onClose} title={titles[step]} widthClass="max-w-lg">
      {step === 'loading' && (
        <div className="flex items-center gap-2 text-sm text-ink-400 py-6 justify-center">
          <Loader2 size={16} className="animate-spin" /> Checking identity…
        </div>
      )}
      {step === 'identity' && (
        <IdentityStep identityError={identityError} creating={creatingIdentity} onCreate={onCreateIdentity} />
      )}
      {step === 'identity-created' && (
        <IdentityCreatedStep pubKey={newPubKey} onContinue={() => setStep('form')} />
      )}
      {step === 'form' && (
        <MetadataStep
          form={form}
          setForm={setForm}
          error={formError}
          onContinue={() => { setFormError(null); setStep('confirm') }}
        />
      )}
      {step === 'confirm' && (
        <ConfirmStep
          form={form}
          submitting={submitting}
          error={submitError}
          onBack={() => setStep('form')}
          onConfirm={onConfirmPublish}
        />
      )}
      {step === 'success' && (
        <SuccessStep announceId={announceId} onClose={onClose} />
      )}
    </Modal>
  )
}

// captureSnapshot is accepted for backward-compat with existing Editor.jsx
// call sites but is unused: the distributed Workshop's publish metadata
// (docs/distributed-workshop.md) has no thumbnail/cover field.
export function PublishButton({ project, size = 'sm', variant = 'ghost' }) {
  const [open, setOpen] = useState(false)

  if (!project?.id) return null

  return (
    <>
      <Button variant={variant} size={size} onClick={() => setOpen(true)}>
        <Globe size={14} /> Publish
      </Button>
      <PublishModal
        open={open}
        onClose={() => setOpen(false)}
        project={project}
        onPublished={() => {}}
      />
    </>
  )
}

export default PublishButton
