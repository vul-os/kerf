import { useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, ArrowRight } from 'lucide-react'
import { LogoWordmark } from '../components/Logo.jsx'
import Button from '../components/Button.jsx'
import Input from '../components/Input.jsx'
import Card from '../components/Card.jsx'
import { api, ApiError } from '../lib/api.js'
import { useAuth } from '../store/auth.js'

const ERROR_LABELS = {
  missing_tokens: 'Sign-in did not return tokens. Please try again.',
  me_failed: 'Could not load your account. Please sign in again.',
  google_denied: 'Google sign-in was cancelled.',
  google_state: 'Google sign-in failed a security check. Please try again.',
  github_denied: 'GitHub sign-in was cancelled.',
  github_state: 'GitHub sign-in failed a security check. Please try again.',
}

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const setSession = useAuth((s) => s.setSession)

  const sessionExpired = location.state?.sessionExpired === true

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // Initialize error directly from query string so we don't write state in an effect.
  const initialError = (() => {
    const e = params.get('error')
    if (!e) return null
    return ERROR_LABELS[e] || decodeURIComponent(e)
  })()
  const [error, setError] = useState(initialError)

  const onSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    setError(null)
    setSubmitting(true)
    try {
      const data = await api.login(email.trim(), password)
      setSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        user: data.user,
      })
      const dest = location.state?.from || '/projects'
      navigate(dest, { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || 'Could not sign in.')
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
                Welcome back
              </h1>
              <p className="mt-1 text-sm text-ink-400">
                Sign in to continue to your projects.
              </p>
            </header>

            {sessionExpired && !error && (
              <div
                role="status"
                aria-live="polite"
                data-testid="session-expired-banner"
                className="mb-5 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
              >
                <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden />
                <span>Your session expired — sign in again.</span>
              </div>
            )}

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
                autoComplete="current-password"
                required
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <div className="-mt-2 text-right">
                <Link
                  to="/forgot-password"
                  className="text-xs text-ink-400 hover:text-kerf-300"
                >
                  Forgot password?
                </Link>
              </div>
              <Button
                type="submit"
                variant="primary"
                size="lg"
                className="mt-1 w-full"
                disabled={submitting}
              >
                {submitting ? 'Signing in…' : 'Sign in'}
                {!submitting && <ArrowRight size={16} />}
              </Button>
            </form>

          </Card>

          <p className="mt-6 text-center text-sm text-ink-400">
            Don&apos;t have an account?{' '}
            <Link
              to="/signup"
              className="text-kerf-300 hover:text-kerf-200 font-medium"
            >
              Sign up
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
