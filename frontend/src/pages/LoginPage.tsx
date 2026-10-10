import React, { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const DEMO_ACCOUNTS = [
  { role: 'ADMIN', username: 'admin', email: 'admin@dbzenith.local', password: 'DBZenith_Admin_2026!', desc: 'Full system & user administration' },
  { role: 'DBA', username: 'dba_operator', email: 'dba@dbzenith.local', password: 'DBZenith_DBA_2026!', desc: 'Approve/reject migrations & run simulations' },
  { role: 'ANALYST', username: 'analyst', email: 'analyst@dbzenith.local', password: 'DBZenith_Analyst_2026!', desc: 'Analyze plans & run sandbox simulations' },
  { role: 'VIEWER', username: 'viewer', email: 'viewer@dbzenith.local', password: 'DBZenith_Viewer_2026!', desc: 'Read-only telemetry & recommendations' },
]

function formatFriendlyLoginError(rawMessage: string): string {
  if (!rawMessage) return 'Sign-in failed. Please verify your credentials and try again.'
  if (rawMessage.includes('401') || /invalid username or password/i.test(rawMessage)) {
    return 'Invalid username/email or password, or the account is inactive.'
  }
  if (rawMessage.includes('429') || /rate limit/i.test(rawMessage)) {
    return 'Too many sign-in attempts. Please wait a moment before trying again.'
  }
  if (/cannot reach|network|fetch/i.test(rawMessage)) {
    return 'Unable to reach the DBZenith authentication service. Please ensure the backend (port 8000) is running.'
  }
  return 'Authentication failed. Please check your credentials and try again.'
}

export function LoginPage() {
  const { isAuthenticated, isLoading, sessionExpired, login, clearExpiredNotice } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const state = (location.state as { from?: string; expired?: boolean } | null) ?? null
  const redirectTarget = state?.from && state.from !== '/login' ? state.from : '/'
  const showExpiredBanner = Boolean(sessionExpired || state?.expired)

  const [usernameOrEmail, setUsernameOrEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!isLoading && isAuthenticated) {
    return <Navigate to={redirectTarget} replace />
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    clearExpiredNotice()

    const trimmedUser = usernameOrEmail.trim()
    if (trimmedUser.length < 2) {
      setError('Please enter a valid username or email address (at least 2 characters).')
      return
    }
    if (password.length < 4) {
      setError('Please enter your password (at least 4 characters).')
      return
    }

    setSubmitting(true)
    try {
      await login(trimmedUser, password)
      navigate(redirectTarget, { replace: true })
    } catch (err: any) {
      setError(formatFriendlyLoginError(String(err?.message || '')))
    } finally {
      setSubmitting(false)
    }
  }

  const handleQuickFill = (acc: (typeof DEMO_ACCOUNTS)[number]) => {
    setError(null)
    clearExpiredNotice()
    setUsernameOrEmail(acc.username)
    setPassword(acc.password)
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '24px',
        background: '#070c18',
        color: '#f8fafc',
      }}
    >
      <div
        className="card"
        style={{
          width: '100%',
          maxWidth: '480px',
          padding: '32px',
          border: '1px solid #1e293b',
          background: '#0f172a',
          borderRadius: '12px',
          boxShadow: '0 20px 40px rgba(0, 0, 0, 0.45)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.35rem', fontWeight: 800 }}>
            <span>⚡</span>
            <span>DBZenith</span>
          </div>
          <span className="badge badge-approval-required">RBAC SECURED</span>
        </div>

        <h1 style={{ margin: '0 0 6px 0', fontSize: '1.4rem' }}>Operator Sign In</h1>
        <p style={{ margin: '0 0 20px 0', fontSize: '0.875rem', color: '#94a3b8' }}>
          Authenticate with your DBZenith operator account to access PostgreSQL workload telemetry, HypoPG simulations, and approval workflows.
        </p>

        {showExpiredBanner && !error && (
          <div
            role="status"
            style={{
              background: 'rgba(245, 158, 11, 0.12)',
              border: '1px solid rgba(245, 158, 11, 0.4)',
              borderLeft: '4px solid #f59e0b',
              color: '#fcd34d',
              padding: '10px 14px',
              borderRadius: '6px',
              fontSize: '0.85rem',
              marginBottom: '16px',
            }}
          >
            <strong>Session Expired:</strong> Your authentication session has expired or ended. Please sign in again to continue.
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="alert"
            style={{
              background: 'rgba(239, 68, 68, 0.12)',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              borderLeft: '4px solid #ef4444',
              color: '#fca5a5',
              padding: '10px 14px',
              borderRadius: '6px',
              fontSize: '0.85rem',
              marginBottom: '16px',
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <label
              htmlFor="login-username"
              style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#cbd5e1', marginBottom: '6px' }}
            >
              Username or Email
            </label>
            <input
              id="login-username"
              name="username"
              type="text"
              autoComplete="username"
              placeholder="e.g. dba_operator or dba@dbzenith.local"
              value={usernameOrEmail}
              onChange={(e) => setUsernameOrEmail(e.target.value)}
              disabled={submitting}
              required
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #334155',
                background: '#070c18',
                color: '#f8fafc',
                fontSize: '0.9rem',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div>
            <label
              htmlFor="login-password"
              style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#cbd5e1', marginBottom: '6px' }}
            >
              Password
            </label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              placeholder="Enter operator password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
              required
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #334155',
                background: '#070c18',
                color: '#f8fafc',
                fontSize: '0.9rem',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting}
            style={{
              padding: '11px 16px',
              fontWeight: 700,
              fontSize: '0.95rem',
              marginTop: '4px',
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: submitting ? 0.7 : 1,
            }}
          >
            {submitting ? 'Signing in...' : 'Sign In to DBZenith'}
          </button>
        </form>

        {/* Quick Operator Presets for Evaluation */}
        <div style={{ marginTop: '24px', paddingTop: '18px', borderTop: '1px solid #1e293b' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', marginBottom: '10px', letterSpacing: '0.05em' }}>
            QUICK FILL EVALUATION PROFILES
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            {DEMO_ACCOUNTS.map((acc) => (
              <button
                key={acc.role}
                type="button"
                disabled={submitting}
                onClick={() => handleQuickFill(acc)}
                style={{
                  textAlign: 'left',
                  padding: '8px 10px',
                  borderRadius: '6px',
                  border: '1px solid #1e293b',
                  background: '#0b1324',
                  color: '#cbd5e1',
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  fontSize: '0.75rem',
                }}
              >
                <div style={{ fontWeight: 700, color: '#38bdf8' }}>{acc.role} — {acc.username}</div>
                <div style={{ color: '#64748b', fontSize: '0.7rem', marginTop: '2px' }}>{acc.desc}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
