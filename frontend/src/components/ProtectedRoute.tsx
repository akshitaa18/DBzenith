import React from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import type { UserRole } from '../lib/api'

interface ProtectedRouteProps {
  children: React.ReactNode
  minRole?: UserRole
}

export function ProtectedRoute({ children, minRole }: ProtectedRouteProps) {
  const { user, isAuthenticated, isLoading, sessionExpired, hasMinRole } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="loading-box" style={{ margin: '48px auto', maxWidth: '520px', textAlign: 'center' }}>
        Verifying operator session and RBAC credentials...
      </div>
    )
  }

  if (!isAuthenticated || !user) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search, expired: sessionExpired }}
      />
    )
  }

  if (minRole && !hasMinRole(minRole)) {
    return (
      <section className="card" style={{ maxWidth: '640px', margin: '40px auto', padding: '32px', borderLeft: '4px solid #ef4444' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
          <span className="badge sev-high">403 FORBIDDEN</span>
          <span className="badge badge-approval-required">RBAC ENFORCED</span>
        </div>
        <h1 style={{ margin: '0 0 10px 0', fontSize: '1.5rem' }}>Insufficient Role Permissions</h1>
        <p style={{ color: '#94a3b8', lineHeight: 1.6, marginBottom: '18px' }}>
          Your current authenticated session (<strong>{user.username}</strong> — role{' '}
          <code>{user.role}</code>) does not have permission to access this view. At least{' '}
          <strong>{minRole}</strong> privileges are required.
        </p>
        <div style={{ display: 'flex', gap: '12px' }}>
          <Link to="/" className="btn btn-primary" style={{ textDecoration: 'none' }}>
            Return to Overview Dashboard
          </Link>
        </div>
      </section>
    )
  }

  return <>{children}</>
}
