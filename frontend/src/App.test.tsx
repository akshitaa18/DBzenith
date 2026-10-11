import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import * as api from './lib/api'

const mockSummary: api.WorkloadSummary = {
  snapshot_id: 1,
  captured_at: '2026-10-10T12:00:00Z',
  window_seconds: 604800,
  total_calls: 127490,
  total_exec_time_ms: 4820000,
  unique_queries: 28,
  slow_queries: 21,
  top_queries: [],
}

const mockPendingRec: api.Recommendation = {
  id: 101,
  created_at: '2026-10-10T12:00:00Z',
  updated_at: '2026-10-10T12:00:00Z',
  type: 'index_where',
  target: 'orders',
  proposed_change: 'CREATE INDEX CONCURRENTLY ON orders (order_date);',
  reason: 'Sequential scan detected on orders.order_date',
  evidence: {},
  expected_benefit: '35-65% cost reduction',
  risk: 'low',
  confidence: 0.91,
  affected_queries: [{ query_id: 1001, calls: 500, mean_exec_time_ms: 210 }],
  requires_approval: true,
  status: 'pending',
}

describe('DBZenith Authentication, Session & RBAC Suite', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()

    vi.spyOn(api, 'getHealth').mockResolvedValue({ status: 'ok', service: 'DBZenith', version: '0.7.0' })
    vi.spyOn(api, 'getWorkloadSummary').mockResolvedValue(mockSummary)
    vi.spyOn(api, 'getWorkloadSnapshots').mockResolvedValue([])
    vi.spyOn(api, 'getRecommendations').mockResolvedValue({
      items: [mockPendingRec],
      page: 1,
      page_size: 20,
      total: 1,
    })
    vi.spyOn(api, 'getRecommendationTrace').mockResolvedValue({
      recommendation: mockPendingRec,
      simulation: null,
      audit_events: [],
      matching_queries: [],
    })
    vi.spyOn(api, 'listUsers').mockResolvedValue([
      {
        id: 1,
        username: 'admin',
        email: 'admin@dbzenith.local',
        role: 'ADMIN',
        is_active: true,
        created_at: '2026-10-10T10:00:00Z',
      },
      {
        id: 2,
        username: 'viewer',
        email: 'viewer@dbzenith.local',
        role: 'VIEWER',
        is_active: true,
        created_at: '2026-10-10T10:00:00Z',
      },
    ])
  })

  it('redirects unauthenticated users from protected dashboard routes to /login', async () => {
    render(
      <MemoryRouter initialEntries={['/recommendations']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: /Operator Sign In/i })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Overview/i })).not.toBeInTheDocument()
  })

  it('validates login inputs and displays friendly error on failed authentication', async () => {
    vi.spyOn(api, 'loginUser').mockRejectedValue(new Error('API request failed: 401: Invalid username or password.'))

    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    const submitBtn = await screen.findByRole('button', { name: /Sign In to DBZenith/i })
    fireEvent.click(submitBtn)
    expect(await screen.findByRole('alert')).toHaveTextContent(/valid username or email/i)

    fireEvent.change(screen.getByLabelText(/Username or Email/i), { target: { value: 'dba_operator' } })
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: 'wrongpass' } })
    fireEvent.click(submitBtn)

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid username\/email or password/i)
  })

  it('authenticates successfully, stores session, and displays identity and role in header', async () => {
    const dbaUser: api.AuthUser = {
      id: 2,
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
    }
    vi.spyOn(api, 'loginUser').mockImplementation(async () => {
      api.setAuthSession('valid-dba-token', dbaUser, 3600)
      return {
        access_token: 'valid-dba-token',
        token_type: 'Bearer',
        expires_in_seconds: 3600,
        user: dbaUser,
      }
    })
    vi.spyOn(api, 'getCurrentUserProfile').mockResolvedValue({
      user_id: '2',
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
      issued_at: Math.floor(Date.now() / 1000),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    })

    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )

    fireEvent.change(await screen.findByLabelText(/Username or Email/i), { target: { value: 'dba_operator' } })
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: 'DBZenith_DBA_2026!' } })
    fireEvent.click(screen.getByRole('button', { name: /Sign In to DBZenith/i }))

    const identityBox = await screen.findByTestId('authenticated-identity')
    expect(identityBox).toHaveTextContent('dba_operator')
    expect(identityBox).toHaveTextContent('DBA')
    expect(screen.getByRole('link', { name: /Overview/i })).toBeInTheDocument()
  })

  it('handles session expiry and manual logout cleanly', async () => {
    const dbaUser: api.AuthUser = {
      id: 2,
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
    }
    api.setAuthSession('active-token', dbaUser, 3600)
    vi.spyOn(api, 'getCurrentUserProfile').mockResolvedValue({
      user_id: '2',
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
      issued_at: Math.floor(Date.now() / 1000),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    })
    vi.spyOn(api, 'logoutUser').mockImplementation(async () => {
      api.clearAuthSession()
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('authenticated-identity')).toHaveTextContent('dba_operator')

    // Trigger centralized 401 session-expired event
    window.dispatchEvent(new CustomEvent('dbzenith:session-expired'))

    expect(await screen.findByRole('heading', { name: /Operator Sign In/i })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/Session Expired/i)
  })

  it('enforces role-based visibility across VIEWER, ANALYST, DBA, and ADMIN roles', async () => {
    const setupRole = (role: api.UserRole, username: string) => {
      const u: api.AuthUser = { id: 10, username, email: `${username}@dbzenith.local`, role }
      api.setAuthSession(`tok-${role}`, u, 3600)
      vi.spyOn(api, 'getCurrentUserProfile').mockResolvedValue({
        user_id: '10',
        username,
        email: u.email,
        role,
        issued_at: Math.floor(Date.now() / 1000),
        expires_at: Math.floor(Date.now() / 1000) + 3600,
      })
    }

    // 1. VIEWER: cannot see Approval Center, Audit Logs, User Admin, or Approve/Simulate buttons
    setupRole('VIEWER', 'viewer_user')
    const { unmount: unmountViewer } = render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('authenticated-identity')).toHaveTextContent('VIEWER')
    expect(screen.queryByRole('link', { name: /Approval Center/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Audit Logs/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /User Admin/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve Migration/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Load Enterprise Workload/i })).not.toBeInTheDocument()
    unmountViewer()

    // 2. ANALYST: sees Audit Logs and Simulate, but cannot see Approval Center, User Admin, or Approve button
    setupRole('ANALYST', 'analyst_user')
    const { unmount: unmountAnalyst } = render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('authenticated-identity')).toHaveTextContent('ANALYST')
    expect(screen.getByRole('link', { name: /Audit Logs/i })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Approval Center/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /User Admin/i })).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Run Sandbox Simulation/i })).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Approve Migration/i })).not.toBeInTheDocument()
    unmountAnalyst()

    // 3. DBA: sees Approval Center and Approve button, but gets 403 Forbidden if navigating to /users
    setupRole('DBA', 'dba_user')
    const { unmount: unmountDba } = render(
      <MemoryRouter initialEntries={['/users']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/403 FORBIDDEN/i)).toBeInTheDocument()
    expect(screen.getByText(/Insufficient Role Permissions/i)).toBeInTheDocument()
    unmountDba()

    // 4. ADMIN: sees User Admin (/users) and can manage operators
    setupRole('ADMIN', 'admin')
    render(
      <MemoryRouter initialEntries={['/users']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: /Operator & RBAC Administration/i })).toBeInTheDocument()
    expect(await screen.findByText('admin@dbzenith.local')).toBeInTheDocument()
  })

  it('attaches Bearer token and credentials on authenticated API requests and sanitizes raw stack traces on failure', async () => {
    vi.restoreAllMocks()
    const adminUser: api.AuthUser = {
      id: 1,
      username: 'admin',
      email: 'admin@dbzenith.local',
      role: 'ADMIN',
    }
    api.setAuthSession('jwt-secret-token-xyz', adminUser, 3600)

    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await api.listUsers()

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [, init] = fetchSpy.mock.calls[0]
    expect(init?.credentials).toBe('include')
    expect((init?.headers as Record<string, string>)['Authorization']).toBe('Bearer jwt-secret-token-xyz')

    // Verify raw stack traces from 500 errors are sanitized and never exposed
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: 'Traceback (most recent call last):\n  File "/app/main.py", line 42, in handler\nsqlalchemy.exc.OperationalError' }),
        { status: 500, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(api.listUsers()).rejects.toThrow(/internal error/i)
  })

  it('prevents protected pages from flashing sensitive information before /api/v1/auth/me resolves, and clears session if verification fails', async () => {
    const staleLocalUser: api.AuthUser = {
      id: 99,
      username: 'tampered_local_admin',
      email: 'tampered@dbzenith.local',
      role: 'ADMIN',
    }
    api.setAuthSession('unverified-token', staleLocalUser, 3600)

    let rejectMe!: (err: Error) => void
    vi.spyOn(api, 'getCurrentUserProfile').mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectMe = reject
        }),
    )

    render(
      <MemoryRouter initialEntries={['/recommendations']}>
        <App />
      </MemoryRouter>,
    )

    // While /api/v1/auth/me is in flight, must show verification spinner and NEVER flash protected data or unverified username
    expect(screen.getByText(/Verifying operator session/i)).toBeInTheDocument()
    expect(screen.queryByText('tampered_local_admin')).not.toBeInTheDocument()
    expect(screen.queryByText(/CREATE INDEX CONCURRENTLY ON orders/i)).not.toBeInTheDocument()

    // Now simulate /api/v1/auth/me failing (e.g., 401 or unreachable backend)
    rejectMe(new Error('API request failed: 401: Invalid or expired authentication token'))

    // Must clear localStorage session and redirect to /login with Session Expired notice
    expect(await screen.findByRole('heading', { name: /Operator Sign In/i })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/Session Expired/i)
    expect(window.localStorage.getItem('dbzenith_auth_session_v1')).toBeNull()
  })

  it('clears local authentication state on manual Sign Out button click', async () => {
    const dbaUser: api.AuthUser = {
      id: 2,
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
    }
    api.setAuthSession('active-token', dbaUser, 3600)
    vi.spyOn(api, 'getCurrentUserProfile').mockResolvedValue({
      user_id: '2',
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
      issued_at: Math.floor(Date.now() / 1000),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    })
    const logoutSpy = vi.spyOn(api, 'logoutUser').mockImplementation(async () => {
      api.clearAuthSession()
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('authenticated-identity')).toHaveTextContent('dba_operator')
    fireEvent.click(screen.getByRole('button', { name: /Sign Out/i }))

    expect(await screen.findByRole('heading', { name: /Operator Sign In/i })).toBeInTheDocument()
    expect(logoutSpy).toHaveBeenCalledTimes(1)
    expect(window.localStorage.getItem('dbzenith_auth_session_v1')).toBeNull()
  })

  it('preserves existing SlowQueries, PlanViewer, and ApprovalCenter workflows with role-aware controls', async () => {
    const dbaUser: api.AuthUser = {
      id: 2,
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
    }
    api.setAuthSession('dba-token', dbaUser, 3600)
    vi.spyOn(api, 'getCurrentUserProfile').mockResolvedValue({
      user_id: '2',
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
      issued_at: Math.floor(Date.now() / 1000),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    })
    vi.spyOn(api, 'getSlowQueries').mockResolvedValue({
      items: [
        {
          id: 1,
          query_id: 1001,
          database_name: 'dbzenith',
          user_name: 'postgres',
          normalized_query: 'SELECT * FROM orders WHERE order_date >= $1',
          calls: 500,
          total_exec_time_ms: 105000,
          mean_exec_time_ms: 210,
          min_exec_time_ms: 40,
          max_exec_time_ms: 890,
          rows: 5000,
          shared_blks_hit: 1200,
          shared_blks_read: 800,
          shared_blks_dirtied: 0,
          shared_blks_written: 0,
          local_blks_hit: 0,
          local_blks_read: 0,
          temp_blks_read: 0,
          temp_blks_written: 0,
          blk_read_time_ms: 45,
          blk_write_time_ms: 0,
          query_frequency_per_minute: 12.5,
          predicate_info: null,
          explain_plan: null,
        },
      ],
      page: 1,
      page_size: 10,
      total: 1,
    })
    vi.spyOn(api, 'getRecommendationAuditEvents').mockResolvedValue([])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const approveSpy = vi.spyOn(api, 'approveRecommendation').mockResolvedValue({
      ...mockPendingRec,
      status: 'approved',
    })

    const { unmount } = render(
      <MemoryRouter initialEntries={['/slow-queries']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/SELECT \* FROM orders WHERE order_date >= \$1/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Calculate Before\/After Cost & Latency/i })).toBeInTheDocument()
    unmount()

    render(
      <MemoryRouter initialEntries={['/approvals']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/CREATE INDEX CONCURRENTLY ON orders/i)).toBeInTheDocument()
    const approveBtn = await screen.findByRole('button', { name: /Approve Migration/i })
    fireEvent.click(approveBtn)
    await waitFor(() => {
      expect(approveSpy).toHaveBeenCalledWith(101, expect.any(String))
    })
  })

  it('displays DEMO banner for synthetic data, LIVE/HISTORICAL badges, missing timestamp notices, and ESTIMATED explanations', async () => {
    const dbaUser: api.AuthUser = {
      id: 2,
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
    }
    api.setAuthSession('dba-token', dbaUser, 3600)
    vi.spyOn(api, 'getCurrentUserProfile').mockResolvedValue({
      user_id: '2',
      username: 'dba_operator',
      email: 'dba@dbzenith.local',
      role: 'DBA',
      issued_at: Math.floor(Date.now() / 1000),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    })

    // 1. Synthetic Demo Mode
    vi.spyOn(api, 'getWorkloadSummary').mockResolvedValueOnce({
      ...mockSummary,
      provenance_state: 'SYNTHETIC_DEMO',
      provenance_badge: 'DEMO',
      source_identifier: 'synthetic://demo-workload-generator',
      collection_status: 'synthetic_seed',
      is_synthetic: true,
      is_measured: false,
      demo_mode_active: true,
    })

    const { unmount: unmountDemo } = render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('demo-provenance-banner')).toHaveTextContent(/Synthetic Demo Workload Active/i)
    expect(screen.getAllByTestId('provenance-badge-demo').length).toBeGreaterThan(0)
    expect(screen.getAllByTestId('estimate-vs-measured-notice')[0]).toHaveTextContent(
      /not a measured runtime benchmark/i,
    )
    unmountDemo()

    // 2. Missing collection timestamp + Stale warning + Collection Error
    vi.spyOn(api, 'getWorkloadSummary').mockResolvedValueOnce({
      ...mockSummary,
      captured_at: null,
      provenance_state: 'HISTORICAL_OBSERVATION',
      provenance_badge: 'HISTORICAL',
      source_identifier: 'postgresql://prod-db:5432/dbzenith',
      collection_status: 'error',
      collection_error: 'pg_stat_statements extension is not loaded',
      is_synthetic: false,
      is_measured: false,
      is_stale: true,
      staleness_warning: 'Collection timestamp is missing; displaying as historical observation.',
      demo_mode_active: false,
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('staleness-warning-banner')).toHaveTextContent(/Collection timestamp is missing/i)
    expect(screen.getByTestId('telemetry-captured-at')).toHaveTextContent(/Timestamp unavailable \(not current\)/i)
    expect(screen.getByTestId('collection-error-banner')).toHaveTextContent(/pg_stat_statements extension is not loaded/i)
    expect(screen.getAllByTestId('provenance-badge-historical').length).toBeGreaterThan(0)
  })
})
