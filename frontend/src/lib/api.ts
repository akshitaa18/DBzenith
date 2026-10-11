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

export type ProvenanceState =
  | 'SYNTHETIC_DEMO'
  | 'LIVE_TELEMETRY'
  | 'HISTORICAL_OBSERVATION'
  | 'HYPOTHETICAL_PLAN_ESTIMATE'
  | 'SANDBOX_BENCHMARK'
  | 'VERIFIED_POST_CHANGE'

export type ProvenanceBadgeLabel = 'DEMO' | 'LIVE' | 'HISTORICAL' | 'ESTIMATED' | 'SIMULATED' | 'VERIFIED'

export type QueryOptimizationSummary = {
  baseline_cost: number
  proposed_cost: number
  cost_improvement_pct: number
  baseline_latency_ms: number
  simulated_latency_ms: number
  estimated_latency_ms?: number
  measured_latency_ms?: number | null
  speedup_factor: number
  recommendation_id?: number | null
  recommendation_type?: string | null
  proposed_change?: string | null
  provenance_state?: ProvenanceState | string
  provenance_badge?: ProvenanceBadgeLabel | string
  result_type?: string
  simulation_method?: string
  is_synthetic?: boolean
  is_measured?: boolean
  is_verified_speedup?: boolean
  estimate_vs_measured_explanation?: string
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
  provenance_state?: ProvenanceState | string
  provenance_badge?: ProvenanceBadgeLabel | string
  source_identifier?: string | null
  query_fingerprint?: string | null
  captured_at?: string | null
  window_seconds?: number | null
  is_synthetic?: boolean
  is_measured?: boolean
  is_stale?: boolean
  staleness_warning?: string | null
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
    query_fingerprint?: string | null
    provenance_state?: ProvenanceState | string
    provenance_badge?: ProvenanceBadgeLabel | string
    source_identifier?: string | null
    is_synthetic?: boolean
    is_measured?: boolean
  }>
  provenance_state?: ProvenanceState | string
  provenance_badge?: ProvenanceBadgeLabel | string
  source_identifier?: string | null
  collection_status?: string
  collection_error?: string | null
  is_synthetic?: boolean
  is_measured?: boolean
  is_stale?: boolean
  staleness_seconds?: number | null
  staleness_warning?: string | null
  demo_mode_active?: boolean
}

export type SlowQueriesFilterParams = {
  maxMeanMs?: number
  severity?: 'critical' | 'high' | 'moderate' | 'all' | string
  databaseName?: string
  userName?: string
  queryFingerprint?: string
  search?: string
  windowSeconds?: number
  sortBy?:
    | 'mean_exec_time_ms'
    | 'total_exec_time_ms'
    | 'calls'
    | 'rows'
    | 'shared_blks_read'
    | 'query_frequency_per_minute'
    | string
  sortDir?: 'asc' | 'desc' | string
}

export function getSlowQueries(
  page = 1,
  pageSize = 10,
  minMeanMs?: number,
  filters?: SlowQueriesFilterParams,
): Promise<QueryPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (minMeanMs !== undefined) params.set('min_mean_ms', String(minMeanMs))
  if (filters) {
    if (filters.maxMeanMs !== undefined) params.set('max_mean_ms', String(filters.maxMeanMs))
    if (filters.severity && filters.severity !== 'all') params.set('severity', filters.severity)
    if (filters.databaseName && filters.databaseName.trim()) params.set('database_name', filters.databaseName.trim())
    if (filters.userName && filters.userName.trim()) params.set('user_name', filters.userName.trim())
    if (filters.queryFingerprint && filters.queryFingerprint.trim()) {
      params.set('query_fingerprint', filters.queryFingerprint.trim())
    }
    if (filters.search && filters.search.trim()) params.set('search', filters.search.trim())
    if (filters.windowSeconds !== undefined && filters.windowSeconds > 0) {
      params.set('window_seconds', String(filters.windowSeconds))
    }
    if (filters.sortBy) params.set('sort_by', filters.sortBy)
    if (filters.sortDir) params.set('sort_dir', filters.sortDir)
  }
  return request(`/api/v1/queries/slow?${params}`)
}


export function getQueryDetail(queryId: number | string): Promise<QueryDetail> {
  return request(`/api/v1/queries/${queryId}`)
}

export function calculateQueryOptimizations(queryId?: number | string): Promise<{
  status: string
  calculated_count: number
  new_simulations_created: number
  result_type?: string
  is_measured?: boolean
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
  provenance_state?: ProvenanceState | string
  provenance_badge?: ProvenanceBadgeLabel | string
  source_identifier?: string | null
  is_synthetic?: boolean
  is_measured?: boolean
  model_version?: string | null
  estimate_vs_measured_explanation?: string
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

export type DetailedPlanNode = {
  node_id: string
  parent_id: string | null
  depth: number
  structural_path?: string
  node_type: string
  parent_relationship?: string | null
  relation_name?: string | null
  alias?: string | null
  index_name?: string | null
  join_type?: string | null
  strategy?: string | null
  sort_key?: string[]
  group_key?: string[]
  filter_condition?: string | null
  index_condition?: string | null
  join_condition?: string | null
  cost_unit: string
  startup_cost: number
  total_cost: number
  exclusive_cost: number
  cost_share_pct: number
  plan_rows: number
  plan_width: number
  has_actual_timing: boolean
  actual_startup_time_ms: number | null
  actual_total_time_ms: number | null
  actual_loops: number | null
  inclusive_actual_time_ms: number | null
  exclusive_actual_time_ms: number | null
  actual_time_share_pct: number | null
  actual_rows: number | null
  rows_removed_by_filter: number | null
  row_estimation_error_ratio: number | null
  row_estimation_q_error: number | null
  shared_hit_blocks: number
  shared_read_blocks: number
  shared_dirtied_blocks: number
  shared_written_blocks: number
  temp_read_blocks: number
  temp_written_blocks: number
  io_read_time_ms: number
  io_write_time_ms: number
  buffer_hit_ratio: number | null
  children_ids: string[]
}

export type ParsedPlanTree = {
  has_plan: boolean
  root_id: string | null
  nodes: DetailedPlanNode[]
  edges: Array<{ from: string; to: string }>
  node_count: number
  max_depth: number
  cost_unit: string
  startup_cost: number
  total_cost: number
  estimated_rows: number
  has_actual_timing: boolean
  planning_time_ms: number | null
  execution_time_ms: number | null
  actual_rows: number | null
  total_shared_hit_blocks: number
  total_shared_read_blocks: number
  total_shared_dirtied_blocks: number
  total_shared_written_blocks: number
  total_temp_read_blocks: number
  total_temp_written_blocks: number
  total_io_read_time_ms: number
  total_io_write_time_ms: number
  overall_buffer_hit_ratio: number | null
}

export type PlanNodeDiff = {
  diff_id: string
  change_type: string
  severity: string
  badges: string[]
  explanation: string
  relation_name: string | null
  baseline_node: DetailedPlanNode | null
  candidate_node: DetailedPlanNode | null
  metrics_delta: {
    cost_unit: string
    total_cost_delta: number
    exclusive_cost_delta: number
    estimated_rows_delta: number
    actual_time_delta_ms: number | null
    shared_hit_delta_blocks: number
    shared_read_delta_blocks: number
  }
}

export type PlanComparisonResult = {
  verdict: string
  narrative_explanation: string
  cost_unit: string
  cost_disclaimer: string
  has_actual_timing: boolean
  candidate_change_context: {
    sanitized_baseline_sql: string | null
    sanitized_candidate_sql: string | null
    candidate_index_ddl: string | null
    recommendation_id: number | null
  }
  cost_comparison: {
    unit: string
    is_measured_latency: boolean
    baseline_startup_cost: number
    baseline_total_cost: number
    candidate_startup_cost: number
    candidate_total_cost: number
    cost_delta: number
    cost_reduction_pct: number
    baseline_estimated_rows: number
    candidate_estimated_rows: number
    disclaimer: string
  }
  actual_execution_comparison: {
    unit: string
    is_measured_latency: boolean
    has_baseline_actuals: boolean
    has_candidate_actuals: boolean
    baseline_planning_time_ms: number | null
    candidate_planning_time_ms: number | null
    baseline_execution_time_ms: number | null
    candidate_execution_time_ms: number | null
    execution_time_delta_ms: number | null
    measured_speedup_pct: number | null
    baseline_actual_rows: number | null
    candidate_actual_rows: number | null
  }
  buffer_comparison: {
    baseline_shared_hit_blocks: number
    candidate_shared_hit_blocks: number
    shared_hit_delta_blocks: number
    baseline_shared_read_blocks: number
    candidate_shared_read_blocks: number
    shared_read_delta_blocks: number
    baseline_temp_written_blocks: number
    candidate_temp_written_blocks: number
    baseline_buffer_hit_ratio: number | null
    candidate_buffer_hit_ratio: number | null
  }
  structural_changes_summary: {
    shape_changed: boolean
    baseline_node_count: number
    candidate_node_count: number
    baseline_max_depth: number
    candidate_max_depth: number
    counts: Record<string, number>
    scan_changes: Array<Record<string, any>>
    join_changes: Array<Record<string, any>>
    sort_changes: Array<Record<string, any>>
  }
  cost_contributors: {
    unit: string
    baseline: Array<Record<string, any>>
    candidate: Array<Record<string, any>>
  }
  time_contributors: {
    unit: string
    available: boolean
    baseline: Array<Record<string, any>>
    candidate: Array<Record<string, any>>
  }
  baseline_plan: ParsedPlanTree
  candidate_plan: ParsedPlanTree
  node_diffs: PlanNodeDiff[]
}

export type BenchmarkSeriesMetrics = {
  unit: string
  is_measured: boolean
  warmup_runs_requested: number
  warmup_runs_completed: number
  measured_runs_requested: number
  sample_count: number
  failed_runs: number
  samples_ms: number[]
  cold_first_run_ms: number | null
  median_ms: number | null
  p95_ms: number | null
  p95_note: string
  mean_ms: number | null
  min_ms: number | null
  max_ms: number | null
  stddev_ms: number | null
  coefficient_of_variation: number | null
  shared_hit_blocks_median: number
  shared_read_blocks_median: number
  cache_hit_ratio: number | null
  cache_state: string
  actual_rows: number | null
}

export type SafeBenchmarkResult = {
  run_id: string
  status: 'completed' | 'estimate_only' | 'unsupported' | 'timeout' | 'cancelled' | 'invalid_sql' | 'busy' | 'failed' | string
  comparison_verdict: 'improved' | 'regressed' | 'inconclusive' | 'estimate_only' | 'unsupported' | 'timeout' | 'cancelled' | 'invalid_sql' | 'failed' | string
  verdict_explanation?: string
  unsupported_reason?: string | null
  error_reason?: string | null
  timeout_occurred?: boolean
  cancelled?: boolean
  is_comparable: boolean
  incomparability_reasons: string[]
  cost_unit: string
  cost_disclaimer: string
  safeguards: Record<string, any>
  environment: Record<string, any>
  baseline_metrics: BenchmarkSeriesMetrics
  candidate_metrics: BenchmarkSeriesMetrics
  measured_comparison: {
    unit: string
    is_measured: boolean
    baseline_median_ms: number | null
    candidate_median_ms: number | null
    baseline_p95_ms: number | null
    candidate_p95_ms: number | null
    median_delta_ms: number | null
    measured_speedup_pct: number | null
    p95_speedup_pct: number | null
    note: string
  }
  estimated_cost_comparison: PlanComparisonResult['cost_comparison']
  plan_comparison: PlanComparisonResult
  provenance_state?: string
  provenance_badge?: string
  source_identifier?: string | null
  is_measured?: boolean
  is_synthetic?: boolean
}

export type PlanComparisonExportResult = {
  format: 'json' | 'csv' | string
  content_type: string
  filename: string
  literals_scrubbed: boolean
  content: string
}

export function comparePlans(payload: {
  baseline_plan?: unknown
  candidate_plan?: unknown
  query_id?: number | string
  simulation_id?: number
  recommendation_id?: number
  baseline_sql?: string
  candidate_sql?: string
  candidate_index_ddl?: string
}): Promise<PlanComparisonResult> {
  return request('/api/v1/plans/compare', jsonBody(payload))
}

export function runSafeBenchmark(
  payload: {
    baseline_sql?: string
    candidate_sql?: string
    candidate_index_ddl?: string
    query_id?: number | string
    recommendation_id?: number
    baseline_plan?: unknown
    candidate_plan?: unknown
    parameters?: Record<string, unknown> | unknown[]
    warmup_runs?: number
    benchmark_runs?: number
    statement_timeout_ms?: number
    run_id?: string
    pre_cancelled?: boolean
  },
  signal?: AbortSignal,
): Promise<SafeBenchmarkResult> {
  const init = jsonBody(payload)
  if (signal) init.signal = signal
  return request('/api/v1/plans/benchmark', init)
}

export function cancelBenchmarkRun(runId: string): Promise<{
  run_id: string
  status: string
  cancelled: boolean
  message: string
}> {
  return request(`/api/v1/plans/benchmark/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })
}

export function exportPlanComparison(payload: {
  format: 'json' | 'csv'
  comparison?: unknown
  baseline_plan?: unknown
  candidate_plan?: unknown
  baseline_sql?: string
  candidate_sql?: string
  candidate_index_ddl?: string
  recommendation_id?: number
}): Promise<PlanComparisonExportResult> {
  return request('/api/v1/plans/compare/export', jsonBody(payload))
}


export type Recommendation = {
  id: number
  created_at: string
  updated_at: string | null
  type: string
  target: string
  proposed_change: string
  reason: string
  evidence?: Record<string, unknown>
  expected_benefit: string
  risk: string
  confidence: number
  affected_queries: Array<number | string | Record<string, unknown>>
  requires_approval: boolean
  status: 'pending' | 'approved' | 'rejected' | string
  lifecycle_state?: string
  candidate_simulation_id?: number | null
  baseline_metrics?: Record<string, any> | null
  post_change_metrics?: Record<string, any> | null
  impact_summary?: Record<string, any> | null
  deployment_details?: Record<string, any> | null
  decided_by?: string | null
  decided_at?: string | null
  decision_reason?: string | null
  applied_at?: string | null
  validated_at?: string | null
  provenance_state?: ProvenanceState | string
  provenance_badge?: ProvenanceBadgeLabel | string
  source_identifier?: string | null
  query_fingerprint?: string | null
  is_synthetic?: boolean
  is_measured?: boolean
  model_version?: string | null
  estimate_vs_measured_explanation?: string
}

export type RecommendationPage = {
  items: Recommendation[]
  page: number
  page_size: number
  total: number
}

export type LifecycleDashboardSummary = {
  total_recommendations: number
  awaiting_approval_count: number
  approved_or_ready_count: number
  applied_count: number
  validation_pending_count: number
  verified_successful_count: number
  regressed_count: number
  failed_count: number
  inconclusive_count: number
  rejected_count: number
  counts?: {
    total: number
    awaiting_approval: number
    ready_for_deployment: number
    applied_changes: number
    recently_validated: number
    successful_improvements: number
    regressions: number
    failed_validations: number
    inconclusive_measurements: number
  }
  state_counts: Record<string, number>
  awaiting_approval: Recommendation[]
  ready_for_deployment?: Recommendation[]
  applied_changes?: Recommendation[]
  recently_validated: Recommendation[]
  successful_improvements?: Recommendation[]
  verified_improvements?: Recommendation[]
  regressions: Recommendation[]
  failed_validations?: Recommendation[]
  inconclusive_measurements: Recommendation[]
}

export function getRecommendations(page = 1, pageSize = 20, status?: string, lifecycleState?: string): Promise<RecommendationPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (status) params.set('status', status)
  if (lifecycleState) params.set('lifecycle_state', lifecycleState)
  return request(`/api/v1/recommendations?${params}`)
}

export function getLifecycleDashboardSummary(): Promise<LifecycleDashboardSummary> {
  return request('/api/v1/recommendations/lifecycle/summary')
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

export function captureRecommendationBaseline(id: number): Promise<Recommendation> {
  return request(`/api/v1/recommendations/${id}/baseline`, { method: 'POST' })
}

export function transitionRecommendationLifecycle(
  id: number,
  targetState: string,
  reason = 'lifecycle transition',
): Promise<Recommendation> {
  return request(`/api/v1/recommendations/${id}/transition`, jsonBody({ target_state: targetState, reason }))
}

export function applyRecommendation(
  id: number,
  payload: {
    confirm_applied?: boolean
    verify_catalog?: boolean
    deployment_reference?: string
    reason: string
  },
): Promise<Recommendation> {
  return request(`/api/v1/recommendations/${id}/apply`, jsonBody(payload))
}

export function validateRecommendationOutcome(
  id: number,
  payload: {
    snapshot_id?: number
    simulation_id?: number
    use_sandbox_benchmark?: boolean
    post_change_observation?: Record<string, any>
    min_sample_size?: number
    reason?: string
  },
): Promise<Recommendation> {
  return request(`/api/v1/recommendations/${id}/validate`, jsonBody(payload))
}

export async function exportRecommendationLifecycle(
  id: number,
  format: 'json' | 'csv' = 'json',
): Promise<{ content: string; filename: string; mimeType: string }> {
  const res = await fetch(`${API_BASE_URL}/api/v1/recommendations/${id}/export?format=${format}`, {
    method: 'GET',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) {
    throw new Error(`Export failed (${res.status})`)
  }
  const content = await res.text()
  return {
    content,
    filename: `recommendation_${id}_lifecycle.${format}`,
    mimeType: format === 'csv' ? 'text/csv' : 'application/json',
  }
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
  baseline_plan?: Record<string, unknown> | null
  proposed_plan?: Record<string, unknown> | null
  error: string | null
  provenance_state?: ProvenanceState | string
  provenance_badge?: ProvenanceBadgeLabel | string
  source_identifier?: string | null
  simulation_method?: string | null
  result_type?: string | null
  is_synthetic?: boolean
  is_measured?: boolean
  is_verified_speedup?: boolean
  model_version?: string | null
  estimate_vs_measured_explanation?: string
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
  return request<Record<string, unknown>[]>(`/api/v1/workload/snapshots?limit=${limit}`)
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
  previous_lifecycle_state?: string | null
  new_lifecycle_state?: string | null
  actor_id?: string | null
  actor_username?: string | null
  actor_role?: string | null
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

export function getSecurityAuditEvents(
  limit = 100,
  filters?: {
    category?: string
    action?: string
    status?: string
    actor?: string
    search?: string
    page?: number
    pageSize?: number
  },
): Promise<SecurityAuditEvent[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (filters) {
    if (filters.category) params.set('category', filters.category)
    if (filters.action) params.set('action', filters.action)
    if (filters.status) params.set('status', filters.status)
    if (filters.actor) params.set('actor', filters.actor)
    if (filters.search) params.set('search', filters.search)
    if (filters.page !== undefined) params.set('page', String(filters.page))
    if (filters.pageSize !== undefined) params.set('page_size', String(filters.pageSize))
  }
  return request(`/api/v1/audit?${params}`)
}

export type QueryItem = QueryDetail

export type PaginatedAuditResult<T = Record<string, any>> = {
  ledger: 'security' | 'recommendations' | 'assistant' | string
  items: T[]
  page: number
  page_size: number
  total: number
  immutable?: boolean
}

export function queryAuditLedger<T = Record<string, any>>(params: {
  ledger: 'security' | 'recommendations' | 'assistant'
  category?: string
  action?: string
  status?: string
  actor?: string
  search?: string
  page?: number
  pageSize?: number
  page_size?: number
}): Promise<PaginatedAuditResult<T>> {
  const q = new URLSearchParams({
    ledger: params.ledger,
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? params.page_size ?? 25),
  })
  if (params.category && params.category.trim()) q.set('category', params.category.trim())
  if (params.action && params.action.trim()) q.set('action', params.action.trim())
  if (params.status && params.status.trim()) q.set('status', params.status.trim())
  if (params.actor && params.actor.trim()) q.set('actor', params.actor.trim())
  if (params.search && params.search.trim()) q.set('search', params.search.trim())
  return request(`/api/v1/audit/query?${q}`)
}

export async function exportAuditLedger(params: {
  ledger: 'security' | 'recommendations' | 'assistant'
  format: 'json' | 'csv'
  category?: string
  action?: string
  status?: string
  actor?: string
  search?: string
}): Promise<{ content: string; filename: string; mimeType: string; contentType: string }> {
  const q = new URLSearchParams({
    ledger: params.ledger,
    format: params.format,
  })
  if (params.category && params.category.trim()) q.set('category', params.category.trim())
  if (params.action && params.action.trim()) q.set('action', params.action.trim())
  if (params.status && params.status.trim()) q.set('status', params.status.trim())
  if (params.actor && params.actor.trim()) q.set('actor', params.actor.trim())
  if (params.search && params.search.trim()) q.set('search', params.search.trim())

  const res = await fetch(`${API_BASE_URL}/api/v1/audit/export?${q}`, {
    method: 'GET',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) {
    throw new Error(`Audit export failed (${res.status})`)
  }
  const content = await res.text()
  const mimeType = params.format === 'csv' ? 'text/csv' : 'application/json'
  return {
    content,
    filename: `dbzenith_${params.ledger}_audit.${params.format}`,
    mimeType,
    contentType: mimeType,
  }
}

export type SystemDiagnostics = {
  status?: 'healthy' | 'degraded' | 'critical' | string
  overall_status?: 'healthy' | 'degraded' | 'critical' | string
  checked_at: string
  api: {
    status: string
    service: string
    version: string
    environment?: string
  }
  primary_database?: {
    connected: boolean
    dsn_masked: string
    version: string
    database_name: string
    role: string
    read_only_capable: boolean
    error: string | null
  }
  sandbox_database?: {
    connected: boolean
    dsn_masked: string
    hypopg_available: boolean
    error: string | null
  }
  extensions?: {
    pg_stat_statements: {
      installed: boolean
      version?: string | null
      operational: boolean
      detail: string
    }
    hypopg: {
      installed: boolean
      version?: string | null
      operational: boolean
      detail: string
    }
  }
  collector?: {
    status: string
    last_successful_telemetry_at: string | null
    last_collection_error: string | null
    failure_count: number
    snapshot_count: number
    poll_interval_seconds: number
    slow_query_threshold_ms: number
    is_stale: boolean
    staleness_warning: string | null
    provenance_state: string
    provenance_badge: string
  }
  database?: {
    connected: boolean
    latency_ms: number
    dialect: string
    server_version: string
    major_version: number | null
    version_compatible: boolean
    db_user: string
    has_stats_permission: boolean
    is_superuser: boolean
    read_only_observation: boolean
    extensions: {
      pg_stat_statements: {
        installed: boolean
        readable: boolean
        status: string
        remediation_sql: string
      }
      hypopg: {
        installed: boolean
        status: string
        remediation_sql: string
      }
    }
    sandbox: {
      available: boolean
      mode: string
      dsn_masked: string
    }
    error: string | null
    connection_summary: {
      scheme: string
      host: string
      port: number | null
      database: string
      username: string
      dsn_masked: string
    }
  }
  sandbox?: {
    available: boolean
    mode: string
    dsn_masked: string
    connection_summary: {
      scheme: string
      host: string
      port: number | null
      database: string
      username: string
      dsn_masked: string
    }
  }
  telemetry?: {
    worker_status: string
    total_snapshots: number
    last_snapshot_at: string | null
    last_successful_telemetry_at: string | null
    last_live_telemetry_at: string | null
    latest_collection_status: string
    latest_collection_error: string | null
    collector_failure_count: number
    is_synthetic_active: boolean
    provenance_state: string
    telemetry_interval_seconds: number
    slow_query_threshold_ms: number
    collect_explain: boolean
  }
}

export function getSystemDiagnostics(): Promise<SystemDiagnostics> {
  return request('/api/v1/health/diagnostics')
}

export type ConnectionValidationStep = {
  step: string
  title: string
  status: 'pass' | 'passed' | 'warn' | 'warning' | 'fail' | 'failed' | string
  detail: string
  remediation: string | null
}

export type ConnectionValidationResult = {
  valid?: boolean
  overall_verdict?: 'ready' | 'connected_with_warnings' | 'connection_failed' | string
  overall_status?: 'ready' | 'degraded' | 'failed' | string
  checked_at?: string
  validated_at?: string
  target: string
  target_label?: string
  host_matches_configured?: boolean
  connection_profile?: {
    host: string
    port: number
    database: string
    username: string
    ssl_mode: string
    primary_dsn_masked: string
    sandbox_dsn_masked: string
    credentials_exposed: boolean
  }
  feature_availability?: {
    live_telemetry: boolean
    plan_inspection: boolean
    hypothetical_indexing: boolean
    safe_benchmarking: boolean
  }
  summary?: string
  steps: ConnectionValidationStep[]
}

export type DatabaseValidationResponse = ConnectionValidationResult

export function validateDatabaseConnection(payload?: {
  target?: 'primary' | 'sandbox' | 'both'
  host?: string
  port?: number
  database?: string
  username?: string
  ssl_mode?: 'disable' | 'allow' | 'prefer' | 'require' | 'verify-ca' | 'verify-full' | string
  verify_extensions?: boolean
}): Promise<ConnectionValidationResult> {
  return request('/api/v1/config/database/validate', jsonBody(payload || { target: 'both' }))
}

export type DatabaseConfigSettings = {
  database_url_masked: string
  sandbox_database_url_masked: string
  slow_query_threshold_ms: number
  telemetry_interval_seconds?: number
  telemetry_poll_seconds?: number
  collect_explain?: boolean
  read_only_observation?: boolean
}

export function getDatabaseConfig(): Promise<DatabaseConfigSettings> {
  return request('/api/v1/config/database')
}

export function updateDatabaseConfig(payload: {
  slow_query_threshold_ms?: number
  telemetry_interval_seconds?: number
  telemetry_poll_seconds?: number
  collect_explain?: boolean
}): Promise<{
  status: string
  slow_query_threshold_ms?: number
  telemetry_poll_seconds?: number
  config: DatabaseConfigSettings
}> {
  return request('/api/v1/config/database', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
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

export type QueryTelemetryHistoryPoint = {
  id: number
  snapshot_id: number
  captured_at: string | null
  window_seconds: number | null
  calls: number
  mean_exec_time_ms: number
  total_exec_time_ms: number
  min_exec_time_ms: number
  max_exec_time_ms: number
  rows: number
  shared_blks_hit: number
  shared_blks_read: number
  provenance_state?: string
  provenance_badge?: string
  is_synthetic?: boolean
  is_measured?: boolean
}

export type QueryOptimizationTrace = {
  query: QueryDetail
  telemetry_history?: QueryTelemetryHistoryPoint[]
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
  simulation_history?: Simulation[]
  allowed_next_states?: string[]
  audit_events: Array<{
    id: number
    created_at: string | null
    action: string
    previous_status: string | null
    new_status: string
    previous_lifecycle_state?: string | null
    new_lifecycle_state?: string | null
    actor_id?: string | null
    actor_username?: string | null
    actor_role?: string | null
    reason: string
    metadata?: Record<string, unknown>
  }>
  matching_queries: Array<{
    query_id: number
    normalized_query: string
    mean_exec_time_ms: number
    calls: number
    total_exec_time_ms: number
    rows: number
    explain_plan: unknown
    query_fingerprint?: string | null
    source_identifier?: string | null
    provenance_state?: string
    provenance_badge?: string
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
