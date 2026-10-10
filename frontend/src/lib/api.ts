const API_BASE_URL = String(import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export type UserRole = 'VIEWER' | 'ANALYST' | 'DBA' | 'ADMIN'

export type AuthUser = {
  id: number
  username: string
  email: string
  role: UserRole
}

export type StoredSession = {
  token: string
  user: AuthUser
  expiresAtMs: number
}

const TOKEN_KEY = 'dbzenith_token'
const SESSION_KEY = 'dbzenith_session_meta'

export function setAuthToken(token: string | null): void {
  try {
    if (typeof window === 'undefined') return
    if (token) {
      window.localStorage.setItem(TOKEN_KEY, token)
    } else {
      window.localStorage.removeItem(TOKEN_KEY)
      window.localStorage.removeItem(SESSION_KEY)
    }
  } catch {
    // Ignore storage access errors
  }
}

export function setAuthSession(token: string, user: AuthUser, expiresInSeconds: number): void {
  try {
    if (typeof window === 'undefined') return
    const expiresAtMs = Date.now() + Math.max(1, expiresInSeconds) * 1000
    window.localStorage.setItem(TOKEN_KEY, token)
    window.localStorage.setItem(
      SESSION_KEY,
      JSON.stringify({ token, user, expiresAtMs } satisfies StoredSession),
    )
  } catch {
    // Ignore storage access errors
  }
}

export function clearAuthSession(): void {
  try {
    if (typeof window === 'undefined') return
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(SESSION_KEY)
  } catch {
    // Ignore storage access errors
  }
}

export function getStoredSession(): { session: StoredSession | null; expired: boolean } {
  try {
    if (typeof window === 'undefined') return { session: null, expired: false }
    const raw = window.localStorage.getItem(SESSION_KEY)
    const token = window.localStorage.getItem(TOKEN_KEY)
    if (!raw || !token) return { session: null, expired: false }
    const parsed = JSON.parse(raw) as StoredSession
    if (!parsed.expiresAtMs || Date.now() >= parsed.expiresAtMs) {
      clearAuthSession()
      return { session: null, expired: true }
    }
    return { session: { ...parsed, token }, expired: false }
  } catch {
    clearAuthSession()
    return { session: null, expired: false }
  }
}

function sanitizeErrorDetail(rawDetail: string, status: number): string {
  const cleaned = rawDetail.split('\n')[0].trim()
  // Never expose raw stack traces, SQLAlchemy URLs, or internal file paths
  if (
    /traceback|sqlalchemy|psycopg|file "|line \d+/i.test(cleaned) ||
    cleaned.length > 220
  ) {
    if (status === 401) return 'Your session has expired or credentials are invalid. Please sign in again.'
    if (status === 403) return 'You do not have permission to perform this action.'
    if (status >= 500) return 'The backend service encountered an internal error. Please try again shortly.'
    return 'The request could not be completed. Please check your input and try again.'
  }
  return cleaned
}

function getAuthHeaders(existing?: HeadersInit): HeadersInit {
  const headers: Record<string, string> = {}
  if (existing) {
    if (existing instanceof Headers) {
      existing.forEach((v, k) => { headers[k] = v })
    } else if (Array.isArray(existing)) {
      for (const [k, v] of existing) headers[k] = v
    } else {
      Object.assign(headers, existing)
    }
  }
  try {
    const { session, expired } = getStoredSession()
    if (expired && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('dbzenith:session-expired'))
    }
    const token = session?.token ?? (typeof window !== 'undefined' ? window.localStorage.getItem(TOKEN_KEY) : null)
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`
    }
  } catch {
    // Ignore storage access errors
  }
  return headers
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`
  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      credentials: 'include',
      headers: getAuthHeaders(init?.headers),
    })
  } catch {
    const origin = API_BASE_URL || (typeof window !== 'undefined' ? window.location.origin : '')
    throw new Error(
      `Cannot reach the DBZenith API at ${origin || url}. Start the backend (port 8000) or run docker compose up.`,
    )
  }
  if (!response.ok) {
    let rawDetail = ''
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') {
        rawDetail = body.detail
      } else if (Array.isArray(body?.detail)) {
        rawDetail = body.detail.map((d: any) => d?.msg || 'Invalid input').join('; ')
      }
    } catch {
      rawDetail = ''
    }

    if (response.status === 401 && !path.includes('/auth/login')) {
      clearAuthSession()
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('dbzenith:session-expired'))
      }
    }

    const safeDetail = rawDetail ? `: ${sanitizeErrorDetail(rawDetail, response.status)}` : ''
    throw new Error(`API request failed: ${response.status}${safeDetail}`)
  }
  return response.json()
}

function jsonBody(payload: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}

export function getHealth(): Promise<{ status: string; service: string; version: string }> {
  return request('/api/v1/health')
}

export type QueryOptimizationSummary = {
  baseline_cost: number
  proposed_cost: number
  cost_improvement_pct: number
  baseline_latency_ms: number
  simulated_latency_ms: number
  speedup_factor: number
  recommendation_id?: number | null
  recommendation_type?: string | null
  proposed_change?: string | null
}

export type QueryDetail = {
  id: number
  query_id: number
  database_name: string | null
  user_name: string | null
  normalized_query: string
  calls: number
  total_exec_time_ms: number
  mean_exec_time_ms: number
  min_exec_time_ms: number
  max_exec_time_ms: number
  rows: number
  shared_blks_hit: number
  shared_blks_read: number
  shared_blks_dirtied: number
  shared_blks_written: number
  local_blks_hit: number
  local_blks_read: number
  temp_blks_read: number
  temp_blks_written: number
  blk_read_time_ms: number
  blk_write_time_ms: number
  query_frequency_per_minute: number
  predicate_info: Record<string, unknown> | null
  explain_plan: unknown
  optimization_summary?: QueryOptimizationSummary | null
}

export type QueryPage = {
  items: QueryDetail[]
  page: number
  page_size: number
  total: number
}

export type WorkloadSummary = {
  snapshot_id: number | null
  captured_at: string | null
  window_seconds: number
  total_calls: number
  total_exec_time_ms: number
  unique_queries: number
  slow_queries: number
  top_queries: Array<{
    id?: number
    query_id: number
    mean_exec_time_ms: number
    total_exec_time_ms: number
    calls: number
    query: string
  }>
}

export function getSlowQueries(page = 1, pageSize = 10, minMeanMs?: number): Promise<QueryPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (minMeanMs !== undefined) params.set('min_mean_ms', String(minMeanMs))
  return request(`/api/v1/queries/slow?${params}`)
}

export function getQueryDetail(queryId: number | string): Promise<QueryDetail> {
  return request(`/api/v1/queries/${queryId}`)
}

export function calculateQueryOptimizations(queryId?: number | string): Promise<{
  status: string
  calculated_count: number
  new_simulations_created: number
  items: QueryDetail[]
}> {
  const path = queryId !== undefined ? `/api/v1/queries/calculate-optimizations?query_id=${queryId}` : '/api/v1/queries/calculate-optimizations'
  return request(path, { method: 'POST' })
}

export function getWorkloadSummary(): Promise<WorkloadSummary> {
  return request('/api/v1/workload/summary')
}

export type PlanAnalysis = {
  id: number
  created_at: string
  query_id: number | null
  structural_hash: string
  sanitized_plan: unknown
  graph: { root_id: string; nodes: any[]; edges: Array<{ from: string; to: string }> }
  features: Record<string, number>
  bottlenecks: Array<{ type: string; severity: string; evidence: Record<string, unknown>; affected_node: string; explanation: string; possible_remediation: string }>
  explanation: { summary: string; feature_highlights: Record<string, number>; method: string; gnn?: any }
}

export function analyzePlan(
  arg: string | { sql?: string; query_id?: number | string; plan?: unknown }
): Promise<PlanAnalysis> {
  const payload = typeof arg === 'string' ? { sql: arg } : arg
  return request('/api/v1/plans/analyze', jsonBody(payload))
}

export function getPlanAnalysis(id: number): Promise<PlanAnalysis> {
  return request(`/api/v1/plans/${id}`)
}

export type Recommendation = {
  id: number
  created_at: string
  updated_at: string | null
  type: string
  target: string
  proposed_change: string
  reason: string
  evidence: Record<string, unknown>
  expected_benefit: string
  risk: string
  confidence: number
  affected_queries: Array<Record<string, unknown>>
  requires_approval: boolean
  status: 'pending' | 'approved' | 'rejected'
}

export type RecommendationPage = {
  items: Recommendation[]
  page: number
  page_size: number
  total: number
}

export function getRecommendations(page = 1, pageSize = 20, status?: string): Promise<RecommendationPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (status) params.set('status', status)
  return request(`/api/v1/recommendations?${params}`)
}

function decideRecommendation(id: number, action: 'approve' | 'reject', reason = 'operator decision'): Promise<Recommendation> {
  return request(`/api/v1/recommendations/${id}/${action}`, jsonBody({ reason }))
}

export function approveRecommendation(id: number, reason?: string): Promise<Recommendation> {
  return decideRecommendation(id, 'approve', reason)
}

export function rejectRecommendation(id: number, reason?: string): Promise<Recommendation> {
  return decideRecommendation(id, 'reject', reason)
}

export type Simulation = {
  id: number
  created_at: string
  recommendation_id: number | null
  status: 'running' | 'completed' | 'failed'
  baseline_cost: number | null
  proposed_cost: number | null
  improvement: number | null
  affected_queries: Array<Record<string, unknown>>
  plan_differences: Array<Record<string, unknown>>
  estimated_storage_impact: Record<string, unknown>
  write_overhead_estimate: Record<string, unknown>
  confidence: number
  limitations: string[]
  benchmark: Record<string, unknown>
  baseline_plans: Array<Record<string, unknown>>
  proposed_plans: Array<Record<string, unknown>>
  error: string | null
}

export function createSimulation(recommendationId: number, benchmarkRuns = 3): Promise<Simulation> {
  return request('/api/v1/simulations', jsonBody({ recommendation_id: recommendationId, benchmark_runs: benchmarkRuns }))
}

export function listSimulations(limit = 50): Promise<Simulation[]> {
  return request(`/api/v1/simulations?limit=${limit}`)
}

export function getSimulation(id: number): Promise<Simulation> {
  return request(`/api/v1/simulations/${id}`)
}

export type AssistantChatResponse = {
  session_id: string
  response: string
  safety_check_passed: boolean
  safety_violation_reason: string | null
  evidence: Record<string, unknown>
  analysis: Record<string, unknown>
  recommendations: Array<Record<string, unknown>>
  simulations: Array<Record<string, unknown>>
  approval_request: {
    approval_request?: {
      recommendation_id: number
      proposed_change: string
      status: string
      agent_approved: boolean
    }
    status?: string
    message?: string
  } | null
  audit_trail: Array<{
    timestamp: string
    event_type: string
    tool_name?: string
    output_summary?: string
  }>
}

export function sendAssistantMessage(
  message: string,
  sessionId?: string,
  role = 'dba'
): Promise<AssistantChatResponse> {
  return request('/api/v1/assistant/chat', jsonBody({ message, session_id: sessionId, role }))
}

export function getAssistantTools(): Promise<Array<{ name: string; description: string }>> {
  return request('/api/v1/assistant/tools')
}

export function getRlStatus(): Promise<{
  status: string
  trained_agent_available: boolean
  metadata: Record<string, unknown>
  actions_supported: string[]
  safety_invariant: string
}> {
  return request('/api/v1/rl/status')
}

export function optimizeWithRl(state?: Record<string, unknown>): Promise<{
  action_id: number
  action_type: string
  action_params: Record<string, unknown>
  predicted_reward: number
  confidence: number
  explanation: string
  policy_version: string
  model_type: string
  safety_constraints_passed: boolean
  simulated_cost_reduction_pct: number
}> {
  return request('/api/v1/rl/optimize', jsonBody(state || {}))
}

export function getReadiness(): Promise<{ status: string; database: string }> {
  return request('/api/v1/ready')
}

export async function getWorkloadSnapshots(limit = 10): Promise<Record<string, unknown>[]> {
  try {
    return await request<Record<string, unknown>[]>(`/api/v1/workload/snapshots?limit=${limit}`)
  } catch {
    const data = await request<Record<string, unknown>>(`/api/v1/workload/summary`)
    return [data]
  }
}

export function getAssistantAuditLogs(): Promise<Array<{
  timestamp: string
  session_id: string
  event_type: string
  tool_name?: string
  input_payload?: Record<string, unknown>
  output_summary?: string
  authorized: boolean
  security_flag?: string | null
}>> {
  return request('/api/v1/assistant/audit/all')
}

export type RecommendationAuditEvent = {
  id: number
  created_at: string | null
  recommendation_id: number
  action: string
  previous_status: string | null
  new_status: string
  reason: string
  metadata: Record<string, unknown>
}

export function getRecommendationAuditEvents(): Promise<RecommendationAuditEvent[]> {
  return request('/api/v1/recommendations/audit/events')
}

export type SecurityAuditEvent = {
  id: number
  timestamp: string | null
  event_category: string
  action: string
  actor_id: string | null
  actor_username: string | null
  actor_role: string | null
  target_entity: string | null
  target_id: string | null
  status: string
  ip_address: string | null
  details: Record<string, unknown>
}

export function getSecurityAuditEvents(limit = 100): Promise<SecurityAuditEvent[]> {
  return request(`/api/v1/audit?limit=${limit}`)
}

export type SQLRewriteResponse = {
  original_query: string
  rewritten_query: string
  transformation: string
  reason: string
  expected_benefit: string
  confidence: number
  validation_status: string
  safety_verdict: string
  cost_improvement_pct: number | null
  semantic_match: boolean | null
  production_modified: boolean
}

export function rewriteSql(sql: string, validateSandbox = true): Promise<SQLRewriteResponse> {
  return request('/api/v1/rewriter/rewrite', jsonBody({ sql, validate_sandbox: validateSandbox }))
}

export type QueryOptimizationTrace = {
  query: QueryDetail
  matching_recommendations: Recommendation[]
  latest_simulation: Simulation | null
  plan_analysis?: PlanAnalysis | null
  audit_events: Array<{
    id: number
    created_at: string | null
    action: string
    previous_status: string | null
    new_status: string
    reason: string
  }>
}

export function getQueryOptimizationTrace(queryId: number | string): Promise<QueryOptimizationTrace> {
  return request(`/api/v1/queries/${queryId}/trace`)
}

export type RecommendationTrace = {
  recommendation: Recommendation
  simulation: Simulation | null
  audit_events: Array<{
    id: number
    created_at: string | null
    action: string
    previous_status: string | null
    new_status: string
    reason: string
  }>
  matching_queries: Array<{
    query_id: number
    normalized_query: string
    mean_exec_time_ms: number
    calls: number
    total_exec_time_ms: number
    rows: number
    explain_plan: unknown
  }>
}

export function getRecommendationTrace(recommendationId: number): Promise<RecommendationTrace> {
  return request(`/api/v1/recommendations/${recommendationId}/trace`)
}

export function seedDemoWorkload(): Promise<{
  status: string
  message: string
  snapshot_id: number
  total_calls: number
  slow_queries: number
  recommendations_count: number
}> {
  return request('/api/v1/workload/seed-demo', { method: 'POST' })
}

export function collectTelemetry(): Promise<{
  status: string
  snapshot_id: number
  total_calls: number
  slow_queries: number
  recommendations_generated: number
}> {
  return request('/api/v1/workload/collect', { method: 'POST' })
}

export type ManagedUser = {
  id: number
  username: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
  last_login_at?: string | null
}

export async function loginUser(
  username: string,
  password: string,
): Promise<{
  access_token: string
  token_type: string
  expires_in_seconds: number
  user: AuthUser
}> {
  const res = await request<{
    access_token: string
    token_type: string
    expires_in_seconds: number
    user: AuthUser
  }>('/api/v1/auth/login', jsonBody({ username, password }))
  if (res?.access_token && res?.user) {
    setAuthSession(res.access_token, res.user, res.expires_in_seconds || 3600)
  }
  return res
}

export async function logoutUser(): Promise<void> {
  try {
    await request('/api/v1/auth/logout', { method: 'POST' })
  } catch {
    // Ensure client session is always cleared even if backend is unreachable
  } finally {
    clearAuthSession()
  }
}

export function getCurrentUserProfile(): Promise<{
  user_id: string
  username: string
  email: string
  role: UserRole
  issued_at: number
  expires_at: number
}> {
  return request('/api/v1/auth/me')
}

export function listUsers(): Promise<ManagedUser[]> {
  return request('/api/v1/auth/users')
}

export function createUser(payload: {
  username: string
  email: string
  password: string
  role: UserRole
}): Promise<ManagedUser> {
  return request('/api/v1/auth/users', jsonBody(payload))
}

export function updateUser(
  userId: number,
  payload: { role?: UserRole; is_active?: boolean },
): Promise<ManagedUser> {
  return request(`/api/v1/auth/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
