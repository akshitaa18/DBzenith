import React, { useEffect, useState } from 'react'
import { createUser, listUsers, updateUser, type ManagedUser, type UserRole } from '../lib/api'
import { useAuth } from '../context/AuthContext'

const ROLES: UserRole[] = ['VIEWER', 'ANALYST', 'DBA', 'ADMIN']

export function UserAdminPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // New user form state
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<UserRole>('VIEWER')
  const [creating, setCreating] = useState(false)
  const [updatingId, setUpdatingId] = useState<number | null>(null)

  const loadUsers = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listUsers()
      setUsers(data)
    } catch (err: any) {
      setError(err?.message || 'Failed to load operator accounts.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadUsers()
  }, [])

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMsg(null)

    const cleanUsername = username.trim()
    const cleanEmail = email.trim()
    if (!/^[a-zA-Z0-9_-]{3,64}$/.test(cleanUsername)) {
      setError('Username must be 3–64 characters and contain only letters, digits, underscores, or hyphens.')
      return
    }
    if (!/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(cleanEmail)) {
      setError('Please enter a valid email address.')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters long.')
      return
    }

    setCreating(true)
    try {
      const created = await createUser({
        username: cleanUsername,
        email: cleanEmail,
        password,
        role,
      })
      setSuccessMsg(`Operator account "${created.username}" (${created.role}) created successfully.`)
      setUsername('')
      setEmail('')
      setPassword('')
      setRole('VIEWER')
      await loadUsers()
    } catch (err: any) {
      setError(err?.message || 'Failed to create operator account.')
    } finally {
      setCreating(false)
    }
  }

  const handleRoleChange = async (target: ManagedUser, newRole: UserRole) => {
    if (newRole === target.role) return
    setUpdatingId(target.id)
    setError(null)
    setSuccessMsg(null)
    try {
      const updated = await updateUser(target.id, { role: newRole })
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
      setSuccessMsg(`Updated role for "${updated.username}" to ${updated.role}.`)
    } catch (err: any) {
      setError(err?.message || 'Failed to update user role.')
    } finally {
      setUpdatingId(null)
    }
  }

  const handleToggleActive = async (target: ManagedUser) => {
    setUpdatingId(target.id)
    setError(null)
    setSuccessMsg(null)
    try {
      const updated = await updateUser(target.id, { is_active: !target.is_active })
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
      setSuccessMsg(
        `Account "${updated.username}" is now ${updated.is_active ? 'Active' : 'Suspended'}.`,
      )
    } catch (err: any) {
      setError(err?.message || 'Failed to update account status.')
    } finally {
      setUpdatingId(null)
    }
  }

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>Operator & RBAC Administration</h1>
            <span className="badge badge-approval-required">ADMIN ONLY</span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Provision DBZenith operator accounts, assign least-privilege RBAC roles (VIEWER, ANALYST, DBA, ADMIN), and manage account status.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={loadUsers} disabled={loading}>
          Refresh Accounts
        </button>
      </div>

      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}

      {successMsg && (
        <div
          role="status"
          className="card"
          style={{
            borderLeft: '4px solid #10b981',
            background: 'rgba(16, 185, 129, 0.08)',
            color: '#6ee7b7',
            padding: '12px 16px',
          }}
        >
          <strong>✓ Updated:</strong> {successMsg}
        </div>
      )}

      {/* Create Operator Form */}
      <article className="card">
        <h2 style={{ marginTop: 0, marginBottom: '12px', fontSize: '1.1rem' }}>Create New Operator Account</h2>
        <form
          onSubmit={handleCreateUser}
          noValidate
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
            gap: '12px',
            alignItems: 'end',
          }}
        >
          <div>
            <label htmlFor="new-username" style={{ display: 'block', fontSize: '0.78rem', color: '#94a3b8', marginBottom: '4px' }}>
              Username
            </label>
            <input
              id="new-username"
              type="text"
              placeholder="e.g. senior_dba"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={creating}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #334155',
                background: '#070c18',
                color: '#f8fafc',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div>
            <label htmlFor="new-email" style={{ display: 'block', fontSize: '0.78rem', color: '#94a3b8', marginBottom: '4px' }}>
              Email Address
            </label>
            <input
              id="new-email"
              type="email"
              placeholder="e.g. senior_dba@dbzenith.local"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={creating}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #334155',
                background: '#070c18',
                color: '#f8fafc',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div>
            <label htmlFor="new-password" style={{ display: 'block', fontSize: '0.78rem', color: '#94a3b8', marginBottom: '4px' }}>
              Initial Password (min 8 chars)
            </label>
            <input
              id="new-password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={creating}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #334155',
                background: '#070c18',
                color: '#f8fafc',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div>
            <label htmlFor="new-role" style={{ display: 'block', fontSize: '0.78rem', color: '#94a3b8', marginBottom: '4px' }}>
              Assigned Role
            </label>
            <select
              id="new-role"
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
              disabled={creating}
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #334155',
                background: '#070c18',
                color: '#f8fafc',
                boxSizing: 'border-box',
              }}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={creating}
              style={{ width: '100%', padding: '9px 14px', fontWeight: 700 }}
            >
              {creating ? 'Creating...' : '+ Create Operator'}
            </button>
          </div>
        </form>
      </article>

      {/* Registered Operators Table */}
      <article className="card">
        <h2 style={{ marginTop: 0, marginBottom: '12px', fontSize: '1.1rem' }}>
          Registered Operators ({users.length})
        </h2>

        {loading ? (
          <div className="loading-box">Loading operator accounts...</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Username</th>
                  <th>Email</th>
                  <th>RBAC Role</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const isSelf = currentUser?.username === u.username || currentUser?.id === u.id
                  const isUpdating = updatingId === u.id
                  return (
                    <tr key={u.id}>
                      <td><code>#{u.id}</code></td>
                      <td>
                        <strong>{u.username}</strong>
                        {isSelf && (
                          <span className="badge badge-observed" style={{ marginLeft: '6px', fontSize: '10px' }}>
                            YOU
                          </span>
                        )}
                      </td>
                      <td>{u.email}</td>
                      <td>
                        <select
                          aria-label={`Role for ${u.username}`}
                          value={u.role}
                          disabled={isSelf || isUpdating}
                          onChange={(e) => handleRoleChange(u, e.target.value as UserRole)}
                          style={{
                            padding: '4px 8px',
                            borderRadius: '4px',
                            border: '1px solid #334155',
                            background: '#070c18',
                            color: '#f8fafc',
                            fontSize: '0.8rem',
                          }}
                          title={isSelf ? 'Cannot modify your own ADMIN role' : 'Change operator role'}
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <span className={u.is_active ? 'badge sev-low' : 'badge sev-high'}>
                          {u.is_active ? 'ACTIVE' : 'SUSPENDED'}
                        </span>
                      </td>
                      <td style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                        {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={isSelf || isUpdating}
                          onClick={() => handleToggleActive(u)}
                          title={isSelf ? 'Cannot deactivate your own account' : undefined}
                          style={{ fontSize: '0.75rem', padding: '4px 10px' }}
                        >
                          {u.is_active ? 'Suspend' : 'Activate'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  )
}
