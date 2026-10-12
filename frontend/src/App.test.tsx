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

  it('Phase 8: Index Portfolio Advisor displays statistics completeness warnings, Candidate Requiring DBA Review labels, overlapping/low-usage/composite proposals, and syncs candidates', async () => {
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

    const mockPortfolio: api.IndexPortfolioResponse = {
      generated_at: '2026-10-12T12:00:00Z',
      read_only_analysis: true,
      auto_drop_enabled: false,
      governance_notice:
        'All index recommendations are advisory candidates requiring human DBA review. DBZenith never automatically drops or creates indexes in production.',
      statistics_status: {
        stats_reset_at: '2026-10-12T11:30:00Z',
        stats_age_hours: 0.5,
        stats_recently_reset: true,
        incomplete_statistics: true,
        catalog_reachable: true,
        warnings: ['PostgreSQL statistics were reset 0.5h ago (<24h). Low scan counts do NOT prove an index is unused.'],
      },
      summary: {
        total_indexes: 4,
        total_index_size_bytes: 18432000,
        total_index_size_pretty: '17.6 MB',
        duplicate_or_overlapping_count: 1,
        low_usage_candidate_count: 1,
        missing_or_composite_proposals_count: 1,
        unsupported_index_type_count: 1,
        reclaimable_bytes_estimate: 10240000,
        reclaimable_pretty_estimate: '9.8 MB',
      },
      pagination: {
        page: 1,
        page_size: 20,
        total_indexes: 4,
        total_pages: 1,
      },
      indexes: [
        {
          schema_name: 'public',
          table_name: 'orders',
          index_name: 'idx_orders_customer_id',
          access_method: 'btree',
          is_unique: false,
          is_primary: false,
          key_columns: ['customer_id'],
          include_columns: [],
          where_predicate: null,
          indexdef: 'CREATE INDEX idx_orders_customer_id ON public.orders USING btree (customer_id)',
          index_size_bytes: 2048000,
          index_size_pretty: '2.0 MB',
          table_size_bytes: 50000000,
          idx_scan: 120,
          idx_tup_read: 500,
          idx_tup_fetch: 500,
          table_writes_total: 15000,
          usage_classification: 'active',
          supported_for_prefix_overlap: true,
          stats_available: true,
        },
      ],
      overlapping_candidates: [
        {
          candidate_type: 'overlapping_prefix_index',
          label: 'Candidate Requiring DBA Review',
          requires_dba_review: true,
          auto_drop_permitted: false,
          schema_name: 'public',
          table_name: 'orders',
          index_name: 'idx_orders_customer_id',
          overlapping_with_index: 'idx_orders_cust_status',
          access_method: 'btree',
          narrow_columns: ['customer_id'],
          covering_columns: ['customer_id', 'status'],
          where_predicate: null,
          index_size_bytes: 2048000,
          index_size_pretty: '2.0 MB',
          idx_scan: 120,
          covering_idx_scan: 4500,
          table_writes_total: 15000,
          confidence: 0.84,
          risk_level: 'medium',
          rationale: 'idx_orders_customer_id is a leading-column prefix of idx_orders_cust_status.',
          risk_notes: 'Never drop without staging plan verification.',
          review_sql: '-- CANDIDATE REQUIRING DBA REVIEW\n-- DROP INDEX CONCURRENTLY idx_orders_customer_id;',
          evidence: {},
        },
      ],
      low_usage_candidates: [
        {
          candidate_type: 'low_usage_index_review',
          label: 'Candidate Requiring DBA Review',
          requires_dba_review: true,
          auto_drop_permitted: false,
          schema_name: 'public',
          table_name: 'orders',
          index_name: 'idx_orders_legacy_promo',
          access_method: 'btree',
          key_columns: ['promo_code'],
          index_size_bytes: 8192000,
          index_size_pretty: '7.8 MB',
          idx_scan: 0,
          table_writes_total: 15000,
          stats_reset_at: '2026-10-12T11:30:00Z',
          stats_age_hours: 0.5,
          stats_recently_reset: true,
          index_age_hours: 120,
          referenced_in_observed_workload: false,
          supporting_query_count: 0,
          supporting_queries: [],
          confidence: 0.35,
          risk_level: 'high',
          rationale: '0 scans observed, but statistics were reset 0.5h ago.',
          risk_notes: 'Never automatically drop an index merely because usage counters are low.',
          review_sql: '-- CANDIDATE REQUIRING DBA REVIEW (DO NOT AUTO-DROP)',
        },
      ],
      column_access_analysis: [],
      missing_index_proposals: [
        {
          candidate_type: 'composite_index',
          label: 'Candidate Requiring DBA Review',
          requires_dba_review: true,
          auto_drop_permitted: false,
          table_name: 'orders',
          index_name: 'idx_orders_customer_id_order_date',
          key_columns: ['customer_id', 'order_date'],
          where_predicate: null,
          proposed_sql: 'CREATE INDEX CONCURRENTLY idx_orders_customer_id_order_date ON orders (customer_id, order_date);',
          expected_benefit_pct: 42.5,
          confidence: 0.85,
          risk_level: 'low',
          write_overhead_assessment: 'Moderate table write rate (15,000 tuple writes).',
          table_writes_total: 15000,
          existing_table_index_count: 2,
          selectivity_notes: ['customer_id: high selectivity'],
          rationale: 'Composite B-tree index places equality filter customer_id before range/sort column order_date.',
          supporting_query_count: 1,
          supporting_queries: [
            {
              query_id: 501,
              query_fingerprint: 'fp_orders_cust_date',
              calls: 250,
              mean_exec_time_ms: 185.4,
            },
          ],
          catalog_observations: {},
        },
      ],
      unsupported_index_notices: [],
      provenance_state: 'LIVE_TELEMETRY',
      source_identifier: 'postgresql://localhost:5432/dbzenith',
      is_synthetic: false,
    }

    vi.spyOn(api, 'getIndexPortfolio').mockResolvedValue(mockPortfolio)
    const analyzeSpy = vi.spyOn(api, 'analyzeIndexPortfolio').mockResolvedValue({
      status: 'completed',
      persisted_recommendation_ids: [801],
      persisted_count: 1,
      portfolio: mockPortfolio,
    })

    render(
      <MemoryRouter initialEntries={['/index-portfolio']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('index-portfolio-page')).toBeInTheDocument()
    expect(screen.getByTestId('stats-completeness-banner')).toHaveTextContent(
      /Incomplete or Recently Reset PostgreSQL Catalog Statistics Detected/i,
    )
    expect(screen.getAllByText(/Candidate Requiring DBA Review/i).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(/idx_orders_customer_id is a leading-column prefix/i)).toBeInTheDocument()

    // Switch to Composite & Partial Proposals tab
    fireEvent.click(screen.getByRole('button', { name: /Composite & Partial Proposals/i }))
    expect(
      await screen.findByText(/CREATE INDEX CONCURRENTLY idx_orders_customer_id_order_date/i),
    ).toBeInTheDocument()

    // Sync candidates to lifecycle
    fireEvent.click(screen.getByRole('button', { name: /Sync Candidates to Lifecycle/i }))
    await waitFor(() => {
      expect(analyzeSpy).toHaveBeenCalledWith(true)
    })
    expect(
      await screen.findByText(/Synced 1 new index candidate\(s\) into the Optimization Lifecycle Tracker/i),
    ).toBeInTheDocument()
  })

  it('Phase 8: Workload Regression Alerts renders active/acknowledged/resolved states, insufficient history diagnostics, and DBA acknowledgment/resolution workflow', async () => {
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

    const mockAlert: api.WorkloadAlertItem = {
      id: 42,
      rule_id: 1,
      rule_name: 'Query Mean Latency Regression',
      dedup_key: 'rule:1:metric:mean_exec_time_ms:fp:fp_orders_lookup',
      status: 'active',
      severity: 'critical',
      metric_name: 'mean_exec_time_ms',
      scope: 'query',
      title: 'Query Mean Latency Regression: fp_orders_lookup (245.0 ms)',
      summary: 'Query fingerprint fp_orders_lookup rose from baseline 100.0 ms to 245.0 ms (+145.0%) across 2 consecutive observations.',
      started_at: '2026-10-12T10:00:00Z',
      last_observed_at: '2026-10-12T10:15:00Z',
      occurrence_count: 2,
      consecutive_breaches: 2,
      baseline_value: 100,
      current_value: 245,
      threshold_value: 50,
      deviation_pct: 145,
      baseline_sample_count: 3,
      comparison_sample_count: 2,
      affected_query_fingerprints: [
        {
          query_id: 777,
          query_fingerprint: 'fp_orders_lookup',
          normalized_query: 'SELECT * FROM orders WHERE customer_id = $1',
          calls: 100,
          mean_exec_time_ms: 245,
        },
      ],
      evidence: {},
      provenance_state: 'LIVE_TELEMETRY',
      source_identifier: 'postgresql://localhost:5432/dbzenith',
      is_synthetic: false,
      audit_history: [
        {
          id: 1,
          alert_id: 42,
          rule_id: 1,
          action: 'triggered',
          previous_status: null,
          new_status: 'active',
          actor_id: 'system',
          actor_username: 'system:alert_engine',
          actor_role: 'SYSTEM',
          reason: 'Breached 50% threshold across 2 consecutive samples.',
          details: {},
          created_at: '2026-10-12T10:00:00Z',
        },
      ],
    }

    vi.spyOn(api, 'getWorkloadAlerts').mockResolvedValue({
      items: [mockAlert],
      pagination: { page: 1, page_size: 15, total_items: 1, total_pages: 1 },
      status_counts: { active: 1, acknowledged: 0, resolved: 1, total: 2 },
      severity_counts: { critical: 1, high: 0, warning: 0, info: 0 },
      diagnostics: {
        evaluated_at: '2026-10-12T10:15:00Z',
        insufficient_history: [
          {
            rule_id: 1,
            rule_name: 'Query Mean Latency Regression',
            reason_code: 'insufficient_baseline_samples',
            detail: 'Query fingerprint fp_new_query has 1 observation, fewer than required 3 baseline samples.',
          },
        ],
        suppressed_evaluations: [],
        unsupported_metrics: [],
        supported_metrics: {
          mean_exec_time_ms: {
            label: 'Mean Execution Latency (ms)',
            unit: 'ms',
            scope: ['query', 'workload'],
            default_operator: 'pct_increase',
            description: 'Average query execution latency in milliseconds.',
          },
        },
      },
    })
    vi.spyOn(api, 'getWorkloadAlertDetail').mockResolvedValue(mockAlert)
    vi.spyOn(api, 'getAlertRules').mockResolvedValue({
      items: [],
      total: 0,
      supported_metrics: {
        mean_exec_time_ms: {
          label: 'Mean Execution Latency (ms)',
          unit: 'ms',
          scope: ['query', 'workload'],
          default_operator: 'pct_increase',
          description: 'Average query execution latency in milliseconds.',
        },
      },
    })
    vi.spyOn(api, 'getAlertAuditHistory').mockResolvedValue({
      items: mockAlert.audit_history || [],
      pagination: { page: 1, page_size: 40, total_items: 1, total_pages: 1 },
    })

    const ackSpy = vi.spyOn(api, 'acknowledgeWorkloadAlert').mockResolvedValue({
      ...mockAlert,
      status: 'acknowledged',
      acknowledged_by: 'dba_operator',
    })

    render(
      <MemoryRouter initialEntries={['/alerts']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('workload-alerts-page')).toBeInTheDocument()
    const matches = await screen.findAllByText(/Query Mean Latency Regression: fp_orders_lookup/i)
    expect(matches.length).toBeGreaterThanOrEqual(1)

    // Acknowledge the active alert
    fireEvent.change(
      screen.getByPlaceholderText(/Document investigation note or resolution root cause/i),
      { target: { value: 'Investigating missing index on orders.customer_id' } },
    )
    fireEvent.click(screen.getByRole('button', { name: /Acknowledge Alert/i }))
    await waitFor(() => {
      expect(ackSpy).toHaveBeenCalledWith(42, 'Investigating missing index on orders.customer_id')
    })

    // Switch to Diagnostics tab and verify insufficient history is explicitly surfaced
    fireEvent.click(screen.getByRole('button', { name: /Insufficient History & Noise Suppression/i }))
    expect(await screen.findByTestId('insufficient-history-section')).toHaveTextContent(
      /insufficient_baseline_samples/i,
    )
  })

  it('renders Phase 9 GnnAnalysisPage with GNN/RL evaluation reports, leakage audit, provenance classes, and deterministic fallback transparency', async () => {
    const analystUser: api.AuthUser = {
      id: 3,
      username: 'analyst_operator',
      email: 'analyst@dbzenith.local',
      role: 'ANALYST',
    }
    api.setAuthSession('analyst-token', analystUser, 3600)
    vi.spyOn(api, 'getCurrentUserProfile').mockResolvedValue({
      user_id: '3',
      username: 'analyst_operator',
      email: 'analyst@dbzenith.local',
      role: 'ANALYST',
      issued_at: Math.floor(Date.now() / 1000),
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    })

    vi.spyOn(api, 'getGnnEvaluation').mockResolvedValue({
      model_name: 'BottleneckGNN',
      model_version: 'v0.7.0-synth-20261003',
      evaluation_version: 'phase9-grouped-eval-v1',
      evaluated_at: '2026-10-12T12:00:00Z',
      dataset_type: 'SYNTHETIC_AND_REPRESENTATIVE_HELD_OUT_PLANS',
      validated_on_real_workloads: false,
      reproducibility: {
        legacy_seed: 7,
        evaluation_seed: 202609,
        python_version: '3.13.0',
        torch_version: '2.6.0',
        pyg_available: false,
        normalizer_version: 1,
        feature_count: 21,
        artifact_sha256_prefix: 'a1b2c3d4e5f60718',
        metrics_reproducible_from_saved_predictions: true,
      },
      dataset_sizes: {
        legacy_synthetic: { total_graphs: 250, train_graphs: 200, validation_graphs: 50, validation_nodes: 80 },
        grouped_leakage_free: {
          total_graphs: 288,
          train_graphs: 192,
          train_nodes: 564,
          validation_graphs: 48,
          validation_nodes: 144,
          test_graphs: 48,
          test_nodes: 144,
          held_out_workload_graphs: 6,
          held_out_workload_nodes: 15,
        },
      },
      legacy_perfect_score_investigation: {
        reported_accuracy: 1.0,
        reported_macro_f1: 1.0,
        leakage_and_shortcut_audit: { exact_duplicate_node_count: 30 },
        explanation:
          '30 of the 80 validation nodes (37.5%) were byte-for-byte identical duplicates of training child nodes and had 1-to-1 operator shortcuts.',
      },
      grouped_leakage_audit: { group_id_overlap_count: 0 },
      grouped_validation_metrics: {
        gnn: {
          accuracy: 0.965,
          macro_precision: 0.96,
          macro_recall: 0.95,
          macro_f1: 0.955,
          weighted_f1: 0.965,
          total_nodes: 144,
          per_class: {
            none: { precision: 0.98, recall: 0.98, f1: 0.98, support: 96 },
            sequential_scan: { precision: 0.95, recall: 0.95, f1: 0.95, support: 12 },
          },
          confusion_matrix: { labels: ['none', 'sequential_scan'], matrix: [[94, 2], [1, 11]] },
        },
      },
      grouped_test_metrics: {
        gnn: {
          accuracy: 0.9722,
          macro_precision: 0.945,
          macro_recall: 0.95,
          macro_f1: 0.9462,
          weighted_f1: 0.972,
          total_nodes: 144,
          per_class: {
            none: { precision: 0.9896, recall: 0.9896, f1: 0.9896, support: 96 },
            sequential_scan: { precision: 0.9231, recall: 1.0, f1: 0.96, support: 12 },
          },
          confusion_matrix: { labels: ['none', 'sequential_scan'], matrix: [[95, 1], [0, 12]] },
        },
        mlp_baseline: {
          accuracy: 0.9583,
          macro_precision: 0.92,
          macro_recall: 0.93,
          macro_f1: 0.925,
          weighted_f1: 0.958,
          total_nodes: 144,
          per_class: {},
          confusion_matrix: { labels: ['none', 'sequential_scan'], matrix: [[94, 2], [1, 11]] },
        },
        rule_based_baseline: {
          accuracy: 0.9931,
          macro_precision: 0.985,
          macro_recall: 0.99,
          macro_f1: 0.987,
          weighted_f1: 0.993,
          total_nodes: 144,
          per_class: {},
          confusion_matrix: { labels: ['none', 'sequential_scan'], matrix: [[95, 1], [0, 12]] },
        },
      },
      held_out_workload_metrics: {
        gnn: {
          accuracy: 0.9333,
          macro_precision: 0.9,
          macro_recall: 0.9,
          macro_f1: 0.9,
          weighted_f1: 0.93,
          total_nodes: 15,
          per_class: {},
          confusion_matrix: { labels: ['none', 'sequential_scan'], matrix: [[9, 1], [0, 5]] },
        },
        rule_based_baseline: {
          accuracy: 1.0,
          macro_precision: 1.0,
          macro_recall: 1.0,
          macro_f1: 1.0,
          weighted_f1: 1.0,
          total_nodes: 15,
          per_class: {},
          confusion_matrix: { labels: ['none', 'sequential_scan'], matrix: [[10, 0], [0, 5]] },
        },
      },
      known_limitations: [
        'Trained and evaluated on synthetic and representative held-out EXPLAIN plans; not validated on live production customer workloads.',
      ],
    })

    vi.spyOn(api, 'getRlEvaluation').mockResolvedValue({
      model_name: 'DBZenith DQN Optimization Policy',
      model_version: 'v0.8.0',
      evaluation_version: 'phase9-rl-eval-v1',
      evaluated_at: '2026-10-12T12:00:00Z',
      dataset_type: 'SYNTHETIC_SANDBOX_SIMULATION_AND_MULTI_REGIME_OOD_WORKLOAD',
      validated_on_real_workloads: false,
      reproducibility: {
        evaluation_seed: 20000,
        python_version: '3.13.0',
        torch_version: '2.6.0',
        numpy_version: '2.2.0',
        state_dim: 38,
        action_dim: 6,
        artifact_sha256_prefix: 'f1e2d3c4b5a69788',
        metrics_reproducible_from_saved_predictions: true,
      },
      training_regression_investigation: {
        artifact_found: true,
        recorded_total_regressions: 303,
        recorded_total_training_steps: 2221,
        recorded_training_regression_rate_pct: 13.64,
        recorded_action_counts: { PARTITION_TABLE: 846, DROP_INDEX: 245 },
        partition_table_selection_share_pct: 38.09,
        root_causes: [
          'Exploratory DROP_INDEX when redundant_index_count==0 caused -60% latency regressions (303 total events).',
        ],
      },
      held_out_in_distribution_comparison: {
        rl_agent: {
          total_actions: 500,
          valid_action_rate_pct: 100.0,
          regression_frequency_pct: 0.0,
          failure_rate_pct: 0.0,
          mean_reward: 17.5,
          std_reward: 0.9,
          reward_stability: { mean_reward: 17.5, std_reward: 0.9, median_reward: 17.6, iqr_reward: 1.1, min_reward: 15.0, max_reward: 19.2 },
          improvement_distribution: {
            latency_improvement_pct: { p10: 26, p25: 29, p50_median: 34, p75: 40, p90: 43, mean: 34.5, std: 5.2 },
            throughput_improvement_pct: { p10: 35, p25: 41, p50_median: 52, p75: 66, p90: 76, mean: 54.0, std: 12.1 },
          },
          action_distribution: { PARTITION_TABLE: 483, REWRITE_QUERY: 17 },
        },
        baseline_policy: {
          total_actions: 500,
          valid_action_rate_pct: 100.0,
          regression_frequency_pct: 0.0,
          failure_rate_pct: 0.0,
          mean_reward: 9.7,
          std_reward: 0.5,
          reward_stability: { mean_reward: 9.7, std_reward: 0.5, median_reward: 9.7, iqr_reward: 0.6, min_reward: 8.5, max_reward: 10.9 },
          improvement_distribution: {
            latency_improvement_pct: { p10: 16, p25: 20, p50_median: 25, p75: 30, p90: 34, mean: 25.2, std: 5.5 },
            throughput_improvement_pct: { p10: 19, p25: 25, p50_median: 33, p75: 43, p90: 51, mean: 34.5, std: 9.8 },
          },
          action_distribution: { REWRITE_QUERY: 420, CREATE_INDEX: 80 },
        },
        no_change_policy: {
          total_actions: 500,
          valid_action_rate_pct: 100.0,
          regression_frequency_pct: 0.0,
          failure_rate_pct: 0.0,
          mean_reward: 0.0,
          std_reward: 0.0,
          reward_stability: { mean_reward: 0, std_reward: 0, median_reward: 0, iqr_reward: 0, min_reward: 0, max_reward: 0 },
          improvement_distribution: {
            latency_improvement_pct: { p10: 0, p25: 0, p50_median: 0, p75: 0, p90: 0, mean: 0, std: 0 },
            throughput_improvement_pct: { p10: 0, p25: 0, p50_median: 0, p75: 0, p90: 0, mean: 0, std: 0 },
          },
          action_distribution: { NO_OP: 500 },
        },
        random_policy: {
          total_actions: 500,
          valid_action_rate_pct: 84.0,
          regression_frequency_pct: 10.6,
          failure_rate_pct: 10.6,
          mean_reward: 1.5,
          std_reward: 4.1,
          reward_stability: { mean_reward: 1.5, std_reward: 4.1, median_reward: 1.9, iqr_reward: 5.2, min_reward: -8.0, max_reward: 9.5 },
          improvement_distribution: {
            latency_improvement_pct: { p10: -12, p25: 0, p50_median: 18, p75: 31, p90: 41, mean: 14.3, std: 25.0 },
            throughput_improvement_pct: { p10: -10, p25: 0, p50_median: 22, p75: 44, p90: 69, mean: 26.8, std: 32.0 },
          },
          action_distribution: { NO_OP: 85, CREATE_INDEX: 83, DROP_INDEX: 82, REWRITE_QUERY: 84, PARTITION_TABLE: 83, CHANGE_JOIN_STRATEGY: 83 },
        },
        markdown_table: '',
      },
      diverse_multi_regime_evaluation: {
        scenario_count: 24,
        regimes_covered: ['high_seq_scan_unindexed', 'small_table_nested_loop_ood'],
        policy_summaries: {
          raw_dqn_agent: {
            total_actions: 24,
            valid_action_rate_pct: 50.0,
            regression_frequency_pct: 16.67,
            failure_rate_pct: 16.67,
            mean_reward: 0.51,
            std_reward: 1.85,
            reward_stability: { mean_reward: 0.51, std_reward: 1.85, median_reward: 1.2, iqr_reward: 0.8, min_reward: -3.05, max_reward: 1.8 },
            improvement_distribution: {
              latency_improvement_pct: { p10: -10, p25: 16, p50_median: 24, p75: 30, p90: 33, mean: 19.2, std: 14.5 },
              throughput_improvement_pct: { p10: -9, p25: 19, p50_median: 31, p75: 42, p90: 49, mean: 26.4, std: 19.2 },
            },
            action_distribution: { REWRITE_QUERY: 20, PARTITION_TABLE: 4 },
          },
          safety_gated_dqn_agent: {
            total_actions: 24,
            valid_action_rate_pct: 100.0,
            regression_frequency_pct: 0.0,
            failure_rate_pct: 0.0,
            mean_reward: 0.88,
            std_reward: 0.65,
            reward_stability: { mean_reward: 0.88, std_reward: 0.65, median_reward: 0.91, iqr_reward: 1.0, min_reward: 0.0, max_reward: 1.9 },
            improvement_distribution: {
              latency_improvement_pct: { p10: 0, p25: 5, p50_median: 24, p75: 31, p90: 36, mean: 19.8, std: 13.2 },
              throughput_improvement_pct: { p10: 0, p25: 5, p50_median: 31, p75: 45, p90: 56, mean: 27.5, std: 19.1 },
            },
            action_distribution: { REWRITE_QUERY: 12, CHANGE_JOIN_STRATEGY: 4, NO_OP: 8 },
          },
        },
      },
      known_limitations: [
        'RL outputs are advisory proposals only and cannot directly authorize or execute production DDL/DML changes.',
      ],
    })

    vi.spyOn(api, 'analyzePlan').mockResolvedValue({
      id: 99,
      created_at: '2026-10-12T12:00:00Z',
      query_id: 1,
      structural_hash: 'hash_phase9_test',
      sanitized_plan: {},
      graph: {
        root_id: 'n1',
        nodes: [{ node_id: 'n1', node_type: 'Seq Scan', relation: 'orders', total_cost: 320, plan_rows: 10000 }],
        edges: [],
      },
      features: { node_count: 1, total_cost: 320, seq_scan_fraction: 1.0 },
      bottlenecks: [
        {
          type: 'sequential_scan',
          severity: 'high',
          affected_node: 'n1',
          explanation: 'Full relation scan on orders.',
          evidence: { total_cost: 320 },
          possible_remediation: 'CREATE INDEX CONCURRENTLY ON orders (status);',
        },
      ],
      explanation: {
        summary: 'Seq Scan bottleneck',
        gnn_summary: 'GNN classified sequential scan on orders (confidence: 96%) as the dominant bottleneck.',
        feature_highlights: {},
        method: 'GNN classification (GCN) + deterministic explanation layer',
        gnn: {
          model_version: 'v0.7.0-synth-20261003',
          source_classification: 'LEARNED_MODEL',
          is_fallback: false,
          flagged_bottlenecks: [{ node_id: 'n1', prediction: 'sequential_scan', confidence: 0.96 }],
        },
      } as any,
    })

    render(
      <MemoryRouter initialEntries={['/gnn']}>
        <App />
      </MemoryRouter>,
    )

    expect(
      await screen.findByText(/SYNTHETIC \/ HELD-OUT EVAL ONLY — NOT VALIDATED ON REAL PRODUCTION WORKLOADS/i),
    ).toBeInTheDocument()
    expect(await screen.findByText(/Model Evaluation & Transparency Registry/i)).toBeInTheDocument()

    // Trigger plan analysis
    fireEvent.click(screen.getByRole('button', { name: /Analyze with GNN/i }))
    expect(await screen.findByText(/hash_phase9_test/i)).toBeInTheDocument()

    // Open Model Evaluation & Transparency tab
    fireEvent.click(screen.getByRole('button', { name: /Model Evaluation & Transparency/i }))
    expect(
      await screen.findByText(/Part A: GNN Bottleneck Classifier Evaluation & Leakage Investigation/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/30 of the 80 validation nodes \(37.5%\) were byte-for-byte identical duplicates/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Part B: Reinforcement Learning Policy Evaluation & Training Regression Audit/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/safety_gated_dqn_agent/i)).toBeInTheDocument()
  })
})




