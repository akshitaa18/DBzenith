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
    vi.spyOn(api, 'comparePlans').mockResolvedValue({
      verdict: 'estimate_only_improved',
      narrative_explanation: 'Planner estimated total cost changed from 950.00 to 85.00 planner_cost_units.',
      cost_unit: 'planner_cost_units',
      cost_disclaimer: 'PostgreSQL planner costs are arbitrary relative page/CPU cost units, NOT milliseconds.',
      has_actual_timing: false,
      candidate_change_context: {
        sanitized_baseline_sql: 'SELECT id FROM orders WHERE status = <STR>',
        sanitized_candidate_sql: 'SELECT id FROM orders WHERE status = <STR>',
        candidate_index_ddl: 'CREATE INDEX idx_orders_status ON orders (status)',
        recommendation_id: null,
      },
      cost_comparison: {
        unit: 'planner_cost_units',
        is_measured_latency: false,
        baseline_startup_cost: 0,
        baseline_total_cost: 950,
        candidate_startup_cost: 0.42,
        candidate_total_cost: 85,
        cost_delta: -865,
        cost_reduction_pct: 91.05,
        baseline_estimated_rows: 1000,
        candidate_estimated_rows: 100,
        disclaimer: 'PostgreSQL planner costs are arbitrary relative page/CPU cost units, NOT milliseconds.',
      },
      actual_execution_comparison: {
        unit: 'ms',
        is_measured_latency: false,
        has_baseline_actuals: false,
        has_candidate_actuals: false,
        baseline_planning_time_ms: null,
        candidate_planning_time_ms: null,
        baseline_execution_time_ms: null,
        candidate_execution_time_ms: null,
        execution_time_delta_ms: null,
        measured_speedup_pct: null,
        baseline_actual_rows: null,
        candidate_actual_rows: null,
      },
      buffer_comparison: {
        baseline_shared_hit_blocks: 0,
        candidate_shared_hit_blocks: 0,
        shared_hit_delta_blocks: 0,
        baseline_shared_read_blocks: 0,
        candidate_shared_read_blocks: 0,
        shared_read_delta_blocks: 0,
        baseline_temp_written_blocks: 0,
        candidate_temp_written_blocks: 0,
        baseline_buffer_hit_ratio: null,
        candidate_buffer_hit_ratio: null,
      },
      structural_changes_summary: {
        shape_changed: true,
        baseline_node_count: 1,
        candidate_node_count: 1,
        baseline_max_depth: 0,
        candidate_max_depth: 0,
        counts: { scan_upgraded: 1 },
        scan_changes: [],
        join_changes: [],
        sort_changes: [],
      },
      cost_contributors: {
        unit: 'planner_cost_units',
        baseline: [
          {
            rank: 1,
            node_id: 'n0',
            node_type: 'Seq Scan',
            target: 'orders',
            exclusive_cost: 950,
            inclusive_cost: 950,
            cost_share_pct: 100,
            cost_unit: 'planner_cost_units',
            plan_rows: 1000,
            explanation: 'Seq Scan on orders contributes 950.00 planner_cost_units (100.0% of total estimated plan cost).',
          },
        ],
        candidate: [
          {
            rank: 1,
            node_id: 'n0',
            node_type: 'Index Scan',
            target: 'orders',
            exclusive_cost: 85,
            inclusive_cost: 85,
            cost_share_pct: 100,
            cost_unit: 'planner_cost_units',
            plan_rows: 100,
            explanation: 'Index Scan on orders contributes 85.00 planner_cost_units (100.0% of total estimated plan cost).',
          },
        ],
      },
      time_contributors: {
        unit: 'ms',
        available: false,
        baseline: [],
        candidate: [],
      },
      baseline_plan: {
        has_plan: true,
        root_id: 'n0',
        nodes: [
          {
            node_id: 'n0',
            parent_id: null,
            depth: 0,
            node_type: 'Seq Scan',
            relation_name: 'orders',
            cost_unit: 'planner_cost_units',
            startup_cost: 0,
            total_cost: 950,
            exclusive_cost: 950,
            cost_share_pct: 100,
            plan_rows: 1000,
            plan_width: 64,
            has_actual_timing: false,
            actual_startup_time_ms: null,
            actual_total_time_ms: null,
            actual_loops: null,
            inclusive_actual_time_ms: null,
            exclusive_actual_time_ms: null,
            actual_time_share_pct: null,
            actual_rows: null,
            rows_removed_by_filter: null,
            row_estimation_error_ratio: null,
            row_estimation_q_error: null,
            shared_hit_blocks: 0,
            shared_read_blocks: 0,
            shared_dirtied_blocks: 0,
            shared_written_blocks: 0,
            temp_read_blocks: 0,
            temp_written_blocks: 0,
            io_read_time_ms: 0,
            io_write_time_ms: 0,
            buffer_hit_ratio: null,
            children_ids: [],
          },
        ],
        edges: [],
        node_count: 1,
        max_depth: 0,
        cost_unit: 'planner_cost_units',
        startup_cost: 0,
        total_cost: 950,
        estimated_rows: 1000,
        has_actual_timing: false,
        planning_time_ms: null,
        execution_time_ms: null,
        actual_rows: null,
        total_shared_hit_blocks: 0,
        total_shared_read_blocks: 0,
        total_shared_dirtied_blocks: 0,
        total_shared_written_blocks: 0,
        total_temp_read_blocks: 0,
        total_temp_written_blocks: 0,
        total_io_read_time_ms: 0,
        total_io_write_time_ms: 0,
        overall_buffer_hit_ratio: null,
      },
      candidate_plan: {
        has_plan: true,
        root_id: 'n0',
        nodes: [
          {
            node_id: 'n0',
            parent_id: null,
            depth: 0,
            node_type: 'Index Scan',
            relation_name: 'orders',
            index_name: 'idx_orders_status',
            cost_unit: 'planner_cost_units',
            startup_cost: 0.42,
            total_cost: 85,
            exclusive_cost: 85,
            cost_share_pct: 100,
            plan_rows: 100,
            plan_width: 64,
            has_actual_timing: false,
            actual_startup_time_ms: null,
            actual_total_time_ms: null,
            actual_loops: null,
            inclusive_actual_time_ms: null,
            exclusive_actual_time_ms: null,
            actual_time_share_pct: null,
            actual_rows: null,
            rows_removed_by_filter: null,
            row_estimation_error_ratio: null,
            row_estimation_q_error: null,
            shared_hit_blocks: 0,
            shared_read_blocks: 0,
            shared_dirtied_blocks: 0,
            shared_written_blocks: 0,
            temp_read_blocks: 0,
            temp_written_blocks: 0,
            io_read_time_ms: 0,
            io_write_time_ms: 0,
            buffer_hit_ratio: null,
            children_ids: [],
          },
        ],
        edges: [],
        node_count: 1,
        max_depth: 0,
        cost_unit: 'planner_cost_units',
        startup_cost: 0.42,
        total_cost: 85,
        estimated_rows: 100,
        has_actual_timing: false,
        planning_time_ms: null,
        execution_time_ms: null,
        actual_rows: null,
        total_shared_hit_blocks: 0,
        total_shared_read_blocks: 0,
        total_shared_dirtied_blocks: 0,
        total_shared_written_blocks: 0,
        total_temp_read_blocks: 0,
        total_temp_written_blocks: 0,
        total_io_read_time_ms: 0,
        total_io_write_time_ms: 0,
        overall_buffer_hit_ratio: null,
      },
      node_diffs: [
        {
          diff_id: 'diff_0',
          change_type: 'scan_upgraded',
          severity: 'improvement',
          badges: ['SCAN UPGRADED: Seq Scan -> Index Scan'],
          explanation: "Access path on 'orders' upgraded from Seq Scan to Index Scan via idx_orders_status.",
          relation_name: 'orders',
          baseline_node: null,
          candidate_node: null,
          metrics_delta: {
            cost_unit: 'planner_cost_units',
            total_cost_delta: -865,
            exclusive_cost_delta: -865,
            estimated_rows_delta: -900,
            actual_time_delta_ms: null,
            shared_hit_delta_blocks: 0,
            shared_read_delta_blocks: 0,
          },
        },
      ],
    })
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

  it('renders Phase 5 Optimization Lifecycle & Impact Tracker on Overview and RecommendationLifecyclePanel on Recommendations', async () => {
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

    const mockRec: api.Recommendation = {
      id: 205,
      created_at: new Date().toISOString(),
      updated_at: null,
      type: 'index',
      target: 'orders',
      proposed_change: 'CREATE INDEX idx_orders_status ON orders(status);',
      reason: 'High sequential scan latency',
      expected_benefit: 'Estimated 70% latency reduction (unmeasured estimate)',
      risk: 'low',
      confidence: 0.91,
      status: 'approved',
      lifecycle_state: 'verified_successful',
      requires_approval: true,
      affected_queries: [101],
      query_fingerprint: 'fp_orders_status_101',
      candidate_simulation_id: 12,
      decided_by: 'dba_operator',
      decided_at: new Date().toISOString(),
      decision_reason: 'Approved after sandbox validation',
      baseline_metrics: {
        mean_latency_ms: 140.0,
        p50_latency_ms: 125.0,
        p95_latency_ms: 210.0,
        p99_latency_ms: 245.0,
        sample_size: 400,
        window_seconds: 3600,
        throughput_qps: 0.111,
        error_count: 0,
        provenance_state: 'LIVE_TELEMETRY',
        is_measured: true,
        is_synthetic: false,
      },
      post_change_metrics: {
        mean_latency_ms: 28.0,
        p50_latency_ms: 24.0,
        p95_latency_ms: 41.0,
        p99_latency_ms: 49.0,
        sample_size: 500,
        window_seconds: 3600,
        throughput_qps: 0.139,
        error_count: 0,
        provenance_state: 'VERIFIED_POST_CHANGE',
        is_measured: true,
        is_synthetic: false,
      },
      impact_summary: {
        is_comparable: true,
        incomparability_reasons: [],
        outcome_classification: 'verified_successful',
        environment: 'production',
        is_synthetic: false,
        is_measured: true,
        latency_improvement_pct: 80.0,
        latency_delta_pct: -80.0,
        latency_delta_ms: -112.0,
        confidence_assessment: {
          sample_count_before: 400,
          sample_count_after: 500,
          window_seconds_before: 3600,
          window_seconds_after: 3600,
          variability_before_cv: 0.18,
          variability_after_cv: 0.14,
          causality_disclaimer:
            'Observed before/after changes reflect workload measurements across different time windows and do not establish strict causal proof.',
          uncertainty_notes: [],
        },
      },
      provenance_state: 'VERIFIED_POST_CHANGE',
      provenance_badge: 'VERIFIED: Post-Change',
      is_measured: true,
      is_synthetic: false,
    }

    vi.spyOn(api, 'getLifecycleDashboardSummary').mockResolvedValue({
      total_recommendations: 1,
      awaiting_approval_count: 0,
      approved_or_ready_count: 0,
      applied_count: 0,
      validation_pending_count: 0,
      verified_successful_count: 1,
      regressed_count: 0,
      failed_count: 0,
      inconclusive_count: 0,
      rejected_count: 0,
      state_counts: { verified_successful: 1 },
      awaiting_approval: [],
      recently_validated: [mockRec],
      verified_improvements: [mockRec],
      regressions: [],
      inconclusive_measurements: [],
    })

    vi.spyOn(api, 'getRecommendations').mockResolvedValue({
      items: [mockRec],
      total: 1,
      page: 1,
      page_size: 10,
    })

    vi.spyOn(api, 'getRecommendationTrace').mockResolvedValue({
      recommendation: mockRec,
      matching_queries: [],
      simulation: null,
      simulation_history: [],
      audit_events: [
        {
          id: 1,
          action: 'approved',
          previous_status: 'pending',
          new_status: 'approved',
          previous_lifecycle_state: 'awaiting_approval',
          new_lifecycle_state: 'approved',
          actor_username: 'dba_operator',
          actor_role: 'DBA',
          reason: 'Approved after sandbox validation',
          created_at: new Date().toISOString(),
        },
      ],
      allowed_next_states: ['validation_pending'],
    })

    render(
      <MemoryRouter initialEntries={['/recommendations']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/LIFECYCLE: VERIFIED SUCCESSFUL/i)).toBeInTheDocument()
    const detailBtn = await screen.findByRole('button', { name: /Lifecycle & Impact Detail/i })
    fireEvent.click(detailBtn)

    expect(await screen.findByTestId('lifecycle-panel-205')).toBeInTheDocument()
    expect(screen.getByTestId('causality-disclaimer')).toHaveTextContent(/do not establish strict causal proof/i)
  })

  it('renders Phase 6 PlanComparisonWorkbench with side-by-side plan diff, separate cost vs ms panels, unsupported state, and sanitized export', async () => {
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

    vi.spyOn(api, 'analyzePlan').mockResolvedValue({
      id: 1,
      created_at: new Date().toISOString(),
      query_id: 101,
      structural_hash: 'abcdef1234567890abcdef1234567890',
      sanitized_plan: {},
      graph: { root_id: 'n0', nodes: [], edges: [] },
      features: { node_count: 1, total_cost: 950, total_rows: 1000, total_actual_time_ms: 0, seq_scan_fraction: 1.0 },
      bottlenecks: [],
      explanation: { summary: 'Seq Scan', feature_highlights: {}, method: 'deterministic' },
    })

    const benchmarkSpy = vi.spyOn(api, 'runSafeBenchmark').mockResolvedValueOnce({
      run_id: 'bench-test-1',
      status: 'unsupported',
      comparison_verdict: 'unsupported',
      verdict_explanation: 'Statement contains unsafe or side-effect keyword matching pg_sleep. EXPLAIN ANALYZE refused.',
      unsupported_reason: 'Statement contains unsafe or side-effect keyword matching pg_sleep. EXPLAIN ANALYZE refused.',
      is_comparable: false,
      incomparability_reasons: ['Unsafe query'],
      cost_unit: 'planner_cost_units',
      cost_disclaimer: 'PostgreSQL planner costs are arbitrary relative page/CPU cost units, NOT milliseconds.',
      safeguards: { isolated_sandbox_only: true },
      environment: {},
      baseline_metrics: {
        unit: 'ms',
        is_measured: false,
        warmup_runs_requested: 1,
        warmup_runs_completed: 0,
        measured_runs_requested: 3,
        sample_count: 0,
        failed_runs: 0,
        samples_ms: [],
        cold_first_run_ms: null,
        median_ms: null,
        p95_ms: null,
        p95_note: 'No samples',
        mean_ms: null,
        min_ms: null,
        max_ms: null,
        stddev_ms: null,
        coefficient_of_variation: null,
        shared_hit_blocks_median: 0,
        shared_read_blocks_median: 0,
        cache_hit_ratio: null,
        cache_state: 'unmeasured',
        actual_rows: null,
      },
      candidate_metrics: {
        unit: 'ms',
        is_measured: false,
        warmup_runs_requested: 1,
        warmup_runs_completed: 0,
        measured_runs_requested: 3,
        sample_count: 0,
        failed_runs: 0,
        samples_ms: [],
        cold_first_run_ms: null,
        median_ms: null,
        p95_ms: null,
        p95_note: 'No samples',
        mean_ms: null,
        min_ms: null,
        max_ms: null,
        stddev_ms: null,
        coefficient_of_variation: null,
        shared_hit_blocks_median: 0,
        shared_read_blocks_median: 0,
        cache_hit_ratio: null,
        cache_state: 'unmeasured',
        actual_rows: null,
      },
      measured_comparison: {
        unit: 'ms',
        is_measured: false,
        baseline_median_ms: null,
        candidate_median_ms: null,
        baseline_p95_ms: null,
        candidate_p95_ms: null,
        median_delta_ms: null,
        measured_speedup_pct: null,
        p95_speedup_pct: null,
        note: 'Unsupported query',
      },
      estimated_cost_comparison: {
        unit: 'planner_cost_units',
        is_measured_latency: false,
        baseline_startup_cost: 0,
        baseline_total_cost: 950,
        candidate_startup_cost: 0.42,
        candidate_total_cost: 85,
        cost_delta: -865,
        cost_reduction_pct: 91.05,
        baseline_estimated_rows: 1000,
        candidate_estimated_rows: 100,
        disclaimer: 'NOT milliseconds',
      },
      plan_comparison: (await api.comparePlans({})) as api.PlanComparisonResult,
    })

    const exportSpy = vi.spyOn(api, 'exportPlanComparison').mockResolvedValue({
      format: 'json',
      content_type: 'application/json',
      filename: 'dbzenith_plan_comparison.json',
      literals_scrubbed: true,
      content: '{"cost_unit": "planner_cost_units", "sanitized_baseline_sql": "SELECT id FROM orders WHERE status = <STR>"}',
    })

    render(
      <MemoryRouter initialEntries={['/plans']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('plan-comparison-workbench')).toBeInTheDocument()
    // Verify Planner Cost Panel and Measured Latency Panel are rendered separately
    expect(await screen.findByTestId('planner-cost-panel')).toHaveTextContent(/Arbitrary Cost Units — NOT ms/i)
    expect(screen.getByTestId('measured-latency-panel')).toHaveTextContent(/Measured Sandbox Execution Time \(Milliseconds\)/i)
    expect(screen.getByTestId('unmeasured-latency-notice')).toHaveTextContent(/No Measured Execution Time Available/i)

    // Verify side-by-side plan trees and scan upgrade diff badge
    expect(screen.getByTestId('baseline-plan-tree-card')).toHaveTextContent(/Seq Scan/i)
    expect(screen.getByTestId('candidate-plan-tree-card')).toHaveTextContent(/Index Scan/i)
    expect(screen.getByTestId('plan-node-diff-scan_upgraded')).toHaveTextContent(/SCAN UPGRADED: Seq Scan -> Index Scan/i)

    // Trigger benchmark and verify unsupported query banner
    fireEvent.click(screen.getByTestId('run-safe-benchmark-btn'))
    await waitFor(() => {
      expect(benchmarkSpy).toHaveBeenCalled()
    })
    expect(await screen.findByTestId('benchmark-status-unsupported')).toHaveTextContent(
      /Query Not Supported for Safe Sandbox Execution/i,
    )

    // Trigger authorized sanitized JSON export
    fireEvent.click(screen.getByTestId('export-plan-json-btn'))
    await waitFor(() => {
      expect(exportSpy).toHaveBeenCalled()
    })
    expect(await screen.findByTestId('export-preview-card')).toHaveTextContent(/Literals Scrubbed: YES/i)
    expect(screen.getByTestId('export-preview-content')).toHaveTextContent(/SELECT id FROM orders WHERE status = <STR>/i)
  })

  it('Phase 7: SlowQueries server-side filtering & sorting preserves filters when navigating to QueryDetails and back', async () => {
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

    const slowSpy = vi.spyOn(api, 'getSlowQueries').mockResolvedValue({
      items: [
        {
          id: 1,
          query_id: 1001,
          database_name: 'dbzenith',
          user_name: 'postgres',
          normalized_query: 'SELECT * FROM orders WHERE order_date >= $1',
          query_fingerprint: 'fp_orders_date',
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

    const mockQueryItem: api.QueryItem = {
      id: 1,
      query_id: 1001,
      database_name: 'dbzenith',
      user_name: 'postgres',
      normalized_query: 'SELECT * FROM orders WHERE order_date >= $1',
      query_fingerprint: 'fp_orders_date',
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
    }
    vi.spyOn(api, 'getQueryDetail').mockResolvedValue(mockQueryItem)
    vi.spyOn(api, 'getQueryOptimizationTrace').mockResolvedValue({
      query: mockQueryItem,
      matching_recommendations: [mockPendingRec],
      latest_simulation: null,
      plan_analysis: null,
      audit_events: [],
      telemetry_history: [
        {
          id: 1,
          snapshot_id: 1,
          captured_at: '2026-10-10T12:00:00Z',
          window_seconds: 3600,
          calls: 500,
          mean_exec_time_ms: 210,
          total_exec_time_ms: 105000,
          min_exec_time_ms: 40,
          max_exec_time_ms: 890,
          rows: 5000,
          shared_blks_hit: 1200,
          shared_blks_read: 800,
          provenance_badge: 'LIVE',
          provenance_state: 'LIVE_TELEMETRY',
        },
      ],
    })

    render(
      <MemoryRouter initialEntries={['/slow-queries?severity=critical&min_mean_ms=150&database_name=dbzenith']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/SELECT \* FROM orders WHERE order_date >= \$1/i)).toBeInTheDocument()
    expect(slowSpy).toHaveBeenCalledWith(
      1,
      10,
      150,
      expect.objectContaining({
        severity: 'critical',
        databaseName: 'dbzenith',
      }),
    )

    // Navigate to QueryDetails and verify telemetry history + linked recommendations + back link with preserved filters
    fireEvent.click(screen.getByRole('link', { name: /Inspect Details/i }))
    expect(await screen.findByTestId('query-telemetry-history-card')).toBeInTheDocument()
    expect(screen.getByTestId('query-linked-recommendations-card')).toHaveTextContent(/CREATE INDEX CONCURRENTLY ON orders/i)

    const backLink = screen.getByTestId('back-to-slow-queries-link')
    expect(backLink.getAttribute('href')).toContain('severity=critical')
    expect(backLink.getAttribute('href')).toContain('min_mean_ms=150')
  })

  it('Phase 7: ApprovalCenter accessible confirmation modal, AuditLogs server-side export, and SystemHealth 6-step connection validation', async () => {
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

    const approveSpy = vi.spyOn(api, 'approveRecommendation').mockResolvedValue({
      ...mockPendingRec,
      status: 'approved',
    })

    // 1. ApprovalCenter accessible modal dialog (when window.confirm is not mocked)
    const { unmount: unmountApprovals } = render(
      <MemoryRouter initialEntries={['/approvals']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('approval-permission-badge')).toHaveTextContent(/Required Role: DBA \/ ADMIN/i)
    fireEvent.change(screen.getByLabelText(/Decision rationale for recommendation 101/i), {
      target: { value: 'Verified zero lock risk in staging' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Approve Migration/i }))

    // Modal dialog must appear before API call is executed
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent(/Confirm Approval of Recommendation #101/i)
    expect(approveSpy).not.toHaveBeenCalled()

    // Confirm inside dialog
    fireEvent.click(screen.getByRole('button', { name: /Confirm Approval/i }))
    await waitFor(() => {
      expect(approveSpy).toHaveBeenCalledWith(101, 'Verified zero lock risk in staging')
    })
    unmountApprovals()

    // 2. AuditLogs server-side query & CSV export
    vi.spyOn(api, 'queryAuditLedger').mockResolvedValue({
      ledger: 'recommendations',
      items: [
        {
          id: 1,
          recommendation_id: 101,
          action: 'approved',
          previous_status: 'pending',
          new_status: 'approved',
          reason: 'Verified zero lock risk in staging',
          metadata: {},
          created_at: '2026-10-10T12:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    })
    const exportAuditSpy = vi.spyOn(api, 'exportAuditLedger').mockResolvedValue({
      filename: 'dbzenith_audit_recommendations.csv',
      mimeType: 'text/csv',
      contentType: 'text/csv',
      content: 'id,recommendation_id,action\n1,101,approved\n',
    })

    const { unmount: unmountAudit } = render(
      <MemoryRouter initialEntries={['/audit']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/Verified zero lock risk in staging/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Export filtered audit logs as CSV/i }))
    await waitFor(() => {
      expect(exportAuditSpy).toHaveBeenCalledWith(expect.objectContaining({ ledger: 'recommendations', format: 'csv' }))
    })
    expect(await screen.findByRole('status')).toHaveTextContent(/dbzenith_audit_recommendations\.csv/i)
    unmountAudit()

    // 3. SystemHealth & Guided Database Connection Validation
    vi.spyOn(api, 'getReadiness').mockResolvedValue({ status: 'ready', database: 'ok' })
    vi.spyOn(api, 'getSystemDiagnostics').mockResolvedValue({
      status: 'healthy',
      checked_at: '2026-10-10T12:00:00Z',
      api: { status: 'ok', service: 'DBZenith', version: '0.7.0', environment: 'development' },
      primary_database: {
        connected: true,
        dsn_masked: 'postgresql://postgres:***@localhost:5432/dbzenith',
        version: 'PostgreSQL 16.4',
        database_name: 'dbzenith',
        role: 'postgres',
        read_only_capable: true,
        error: null,
      },
      sandbox_database: {
        connected: true,
        dsn_masked: 'postgresql://postgres:***@localhost:5433/dbzenith_sandbox',
        hypopg_available: true,
        error: null,
      },
      extensions: {
        pg_stat_statements: {
          installed: true,
          version: '1.10',
          operational: true,
          detail: 'pg_stat_statements is installed and actively collecting query digests.',
        },
        hypopg: {
          installed: true,
          version: '1.4.0',
          operational: true,
          detail: 'HypoPG virtual index catalog is operational.',
        },
      },
      collector: {
        status: 'ok',
        last_successful_telemetry_at: '2026-10-10T12:00:00Z',
        last_collection_error: null,
        failure_count: 0,
        snapshot_count: 14,
        poll_interval_seconds: 30,
        slow_query_threshold_ms: 80,
        is_stale: false,
        staleness_warning: null,
        provenance_state: 'LIVE_TELEMETRY',
        provenance_badge: 'LIVE',
      },
    })
    const validateSpy = vi.spyOn(api, 'validateDatabaseConnection').mockResolvedValue({
      overall_status: 'ready',
      target: 'primary',
      target_label: 'postgresql://postgres:***@localhost:5432/dbzenith',
      validated_at: '2026-10-10T12:00:00Z',
      steps: [
        { step: 'connectivity', title: 'TCP & PostgreSQL Handshake', status: 'passed', detail: 'Connected to PostgreSQL 16.4', remediation: null },
        { step: 'pg_stat_statements', title: 'pg_stat_statements Telemetry Extension', status: 'passed', detail: 'Extension active', remediation: null },
      ],
      feature_availability: {
        live_telemetry: true,
        plan_inspection: true,
        hypothetical_indexing: true,
        safe_benchmarking: true,
      },
      summary: 'Connection and required extensions verified.',
    })

    render(
      <MemoryRouter initialEntries={['/health']}>
        <App />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('extension-checks-card')).toHaveTextContent(/pg_stat_statements is installed/i)
    })
    fireEvent.click(screen.getByRole('button', { name: /Validate Connection & Extensions/i }))
    await waitFor(() => {
      expect(validateSpy).toHaveBeenCalled()
    })
    expect(await screen.findByTestId('validation-results-panel')).toHaveTextContent(/Connection and required extensions verified/i)
  })
})


