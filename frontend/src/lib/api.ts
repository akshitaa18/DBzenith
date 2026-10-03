const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`)
  if (!response.ok) throw new Error(`API request failed: ${response.status}`)
  return response.json()
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

export function getQueryDetail(queryId: number): Promise<QueryDetail> {
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

export async function analyzePlan(sql: string): Promise<PlanAnalysis> {
  const response = await fetch(`${API_BASE_URL}/api/v1/plans/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql }),
  })
  if (!response.ok) throw new Error(`Plan analysis failed: ${response.status}`)
  return response.json()
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

async function decideRecommendation(id: number, action: 'approve' | 'reject', reason = 'operator decision'): Promise<Recommendation> {
  const response = await fetch(`${API_BASE_URL}/api/v1/recommendations/${id}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!response.ok) throw new Error(`Recommendation ${action} failed: ${response.status}`)
  return response.json()
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

export async function createSimulation(recommendationId: number, benchmarkRuns = 3): Promise<Simulation> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ recommendation_id: recommendationId, benchmark_runs: benchmarkRuns }),
  })
  if (!response.ok) throw new Error(`Simulation failed: ${response.status}`)
  return response.json()
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

export async function sendAssistantMessage(
  message: string,
  sessionId?: string,
  role = 'dba'
): Promise<AssistantChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/assistant/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, role }),
  })
  if (!response.ok) throw new Error(`Assistant chat failed: ${response.status}`)
  return response.json()
}

export function getAssistantTools(): Promise<Array<{ name: string; description: string }>> {
  return request('/api/v1/assistant/tools')
}

