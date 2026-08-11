import { useState } from 'react'
import { AlertCircle, KeyRound, Loader2, Lock, Terminal } from 'lucide-react'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import Input from '../components/Input.jsx'
import { LogoMark } from '../components/Logo.jsx'
import { api, ApiError } from '../lib/api.js'
import { useAuth } from '../store/auth.js'

/**
 * First run, and the sign-in behind it.
 *
 * Kerf is one node with one password. There are no accounts, so there is
 * nothing to look up — you set a password when you install it, and you type
 * that password to get in.
 *
 * This screen covers the three states the server can report:
 *
 *   unclaimed, reachable   -> choose a password (this is the first run)
 *   unclaimed, remote      -> refuse, and say to use the CLI on the machine
 *   claimed                -> ask for the password
 *
 * The middle one is the interesting case and it is not an edge case. An
 * unconfigured node belongs to whoever reaches it first, so claiming one over
 * a network is a race with a stranger. The server only allows it over
 * loopback; here we explain why rather than showing a form that would 403.
 */

export const MIN_PASSWORD_LENGTH = 8

export interface SetupState {
  configured: boolean
  can_configure_here: boolean
  reason: string
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen grid place-items-center bg-ink-950 px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-3 mb-7">
          <LogoMark size={36} />
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-kerf-300">
            Kerf
          </p>
        </div>
        <Card className="p-6">{children}</Card>
      </div>
    </div>
  )
}

function Problem({ message }: { message: string }) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200"
    >
      <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  )
}

/** Claiming is refused from here — the operator sets the password on the box. */
export function SetupBlocked({ reason }: { reason: string }) {
  return (
    <Shell>
      <div className="flex items-center gap-2 mb-3">
        <Lock size={16} className="text-amber-300" aria-hidden />
        <h1 className="font-display text-lg font-semibold tracking-tight">
          Set the password on the machine
        </h1>
      </div>
      <p className="text-[13px] text-ink-300 leading-relaxed mb-4">{reason}</p>
      <div className="rounded-lg border border-ink-800 bg-ink-950 px-3 py-2.5">
        <p className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-[0.18em] text-ink-500 mb-1">
          <Terminal size={11} aria-hidden />
          On the server
        </p>
        <code className="text-[12px] font-mono text-kerf-300 break-all">
          kerf admin set-password
        </code>
      </div>
      <p className="mt-4 text-[11px] text-ink-500 leading-relaxed">
        Reload this page once it is set.
      </p>
    </Shell>
  )
}

/** First run: choose the password that will guard this node. */
export function SetupClaim({ onClaimed }: { onClaimed: () => void }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH
  const mismatch = confirm.length > 0 && confirm !== password
  const ready = password.length >= MIN_PASSWORD_LENGTH && confirm === password

  const submit = async (e?: { preventDefault?: () => void }) => {
    e?.preventDefault?.()
    if (!ready || busy) return
    setBusy(true)
    setError(null)
    try {
      await api.claimNode(password)
      onClaimed()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not set the password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell>
      <div className="flex items-center gap-2 mb-2">
        <KeyRound size={16} className="text-kerf-300" aria-hidden />
        <h1 className="font-display text-lg font-semibold tracking-tight">
          Set a password
        </h1>
      </div>
      <p className="text-[13px] text-ink-300 leading-relaxed mb-5">
        This node has no password yet. Pick one — it is the only credential, and
        anyone with it can use this Kerf and everything on it.
      </p>

      <form className="flex flex-col gap-4" onSubmit={submit}>
        {error && <Problem message={error} />}

        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
        />
        <Input
          label="Confirm"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          placeholder="Type it again"
        />

        {/* Said before they submit, not after: there is no reset email, so a
            forgotten password means going to the machine. */}
        <p className="text-[11px] text-ink-500 leading-relaxed">
          {tooShort
            ? `Use at least ${MIN_PASSWORD_LENGTH} characters.`
            : mismatch
              ? 'The two entries do not match.'
              : 'Store it somewhere. There is no reset email — recovering it means running kerf admin set-password on this machine.'}
        </p>

        <Button type="submit" variant="primary" size="md" disabled={!ready || busy}>
          {busy ? <Loader2 size={13} className="animate-spin" /> : <KeyRound size={13} />}
          {busy ? 'Setting…' : 'Set password'}
        </Button>
      </form>
    </Shell>
  )
}

/** The node is claimed; ask for the password. */
export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const signInWithNodePassword = useAuth((s) => s.signInWithNodePassword)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e?: { preventDefault?: () => void }) => {
    e?.preventDefault?.()
    if (!password || busy) return
    setBusy(true)
    setError(null)
    try {
      await signInWithNodePassword(password)
      onSignedIn()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Incorrect password.')
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell>
      <h1 className="font-display text-lg font-semibold tracking-tight mb-5">
        Unlock this Kerf
      </h1>

      <form className="flex flex-col gap-4" onSubmit={submit}>
        {error && <Problem message={error} />}

        <Input
          label="Password"
          type="password"
          autoComplete="current-password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Node password"
        />

        <Button type="submit" variant="primary" size="md" disabled={!password || busy}>
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Lock size={13} />}
          {busy ? 'Unlocking…' : 'Unlock'}
        </Button>
      </form>

      <p className="mt-5 text-[11px] text-ink-500 leading-relaxed">
        Forgotten it? Run <code className="font-mono text-ink-400">kerf admin
        set-password</code> on the machine running this node.
      </p>
    </Shell>
  )
}

/** Picks the right screen for the server's reported state. */
export default function Setup({
  state,
  onReady,
}: {
  state: SetupState
  onReady: () => void
}) {
  if (state.configured) return <SignIn onSignedIn={onReady} />
  if (!state.can_configure_here) return <SetupBlocked reason={state.reason} />
  return <SetupClaim onClaimed={onReady} />
}
