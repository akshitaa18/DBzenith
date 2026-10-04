const API_BASE_URL = String(import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    const origin = API_BASE_URL || (typeof window !== 'undefined' ? window.location.origin : '')
    throw new Error(
      `Cannot reach the DBZenith API at ${origin || url}. Start the backend (port 8000) or run docker compose up.`,
    )
  }
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.detail === 'string' ? `: ${body.detail}` : ''
    } catch {
      detail = ''
    }
    throw new Error(`API request failed: ${response.status}${detail}`)
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

export function analyzePlan(sql: string): Promise<PlanAnalysis> {
  return request('/api/v1/plans/analyze', jsonBody({ sql }))
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
  const data = await request<Record<string, unknown>>(`/api/v1/workload/summary`)
  void limit
  return [data]
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
