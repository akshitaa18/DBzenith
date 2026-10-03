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
