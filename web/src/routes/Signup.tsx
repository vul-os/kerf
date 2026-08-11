import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertCircle, ArrowRight } from 'lucide-react'
import { LogoWordmark } from '../components/Logo.jsx'
import Button from '../components/Button.jsx'
import Input from '../components/Input.jsx'
import Card from '../components/Card.jsx'
import { api, ApiError } from '../lib/api.js'
import { useAuth } from '../store/auth.js'

export default function Signup() {
  const navigate = useNavigate()
  const setSession = useAuth((s) => s.setSession)

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [pwError, setPwError] = useState(null)

  const validatePw = (v) => {
    if (v.length > 0 && v.length < 8) {
      setPwError('Use at least 8 characters.')
    } else {
      setPwError(null)
    }
  }

  const onSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    if (password.length < 8) {
      setPwError('Use at least 8 characters.')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      const data = await api.register(email.trim(), password, name.trim())
      setSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        user: data.user,
      })
      navigate('/projects', { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || 'Could not create your account.')
      } else {
        setError('Could not reach the server. Try again in a moment.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-ink-950 text-ink-100">
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 opacity-[0.12]"
        style={{
          backgroundImage:
            'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.5) 1px, transparent 0)',
          backgroundSize: '28px 28px',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
          WebkitMaskImage:
            'radial-gradient(ellipse at center, black 30%, transparent 75%)',
        }}
      />

      <div className="relative flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <Link to="/" className="flex justify-center mb-8" aria-label="Kerf home">
            <LogoWordmark className="text-2xl" />
          </Link>

          <Card className="p-7">
            <header className="mb-6">
              <h1 className="font-display text-2xl font-semibold tracking-tight">
                Create your account
              </h1>
              <p className="mt-1 text-sm text-ink-400">
                Free while in beta. No card required.
              </p>
            </header>

            {error && (
              <div
                role="alert"
                aria-live="assertive"
                className="mb-5 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200"
              >
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={onSubmit} className="flex flex-col gap-4">
              <Input
                label="Name"
                type="text"
                name="name"
                autoComplete="name"
                required
                placeholder="Ada Lovelace"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <Input
                label="Email"
                type="email"
                name="email"
                autoComplete="email"
                required
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <Input
                label="Password"
                type="password"
                name="password"
                autoComplete="new-password"
                required
                minLength={8}
                placeholder="Minimum 8 characters"
                value={password}
                error={pwError}
                hint={!pwError ? '8 characters or more.' : undefined}
                onChange={(e) => {
                  setPassword(e.target.value)
                  validatePw(e.target.value)
                }}
              />
              <Button
                type="submit"
                variant="primary"
                size="lg"
                className="mt-1 w-full"
                disabled={submitting}
              >
                {submitting ? 'Creating account…' : 'Create account'}
                {!submitting && <ArrowRight size={16} />}
              </Button>
            </form>

          </Card>

          <p className="mt-6 text-center text-sm text-ink-400">
            Already have an account?{' '}
            <Link to="/login" className="text-kerf-300 hover:text-kerf-200 font-medium">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
