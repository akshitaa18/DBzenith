import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getSlowQueries,
  getQueryOptimizationTrace,
  createSimulation,
  approveRecommendation,
  rejectRecommendation,
  calculateQueryOptimizations,
  type QueryDetail,
  type QueryOptimizationTrace,
} from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'

function formatMs(value: number) {
  return `${value.toFixed(2)} ms`
}

export function SlowQueries() {
  const [queries, setQueries] = useState<QueryDetail[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [thresholdMs, setThresholdMs] = useState(50)
  const [searchTerm, setSearchTerm] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isCalculatingOptimizations, setIsCalculatingOptimizations] = useState(false)
  const [calculationSuccessMsg, setCalculationSuccessMsg] = useState<string | null>(null)

  // Active query optimization trace state
  const [selectedTraceId, setSelectedTraceId] = useState<number | null>(null)
  const [traceData, setTraceData] = useState<QueryOptimizationTrace | null>(null)
  const [loadingTrace, setLoadingTrace] = useState(false)
  const [traceError, setTraceError] = useState<string | null>(null)
  const [isSimulating, setIsSimulating] = useState(false)
  const [isDeciding, setIsDeciding] = useState(false)

  const fetchQueries = () => {
    setLoading(true)
    setError(null)
    getSlowQueries(page, pageSize, thresholdMs)
      .then((data) => {
        setQueries(data.items)
        setTotal(data.total)
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch slow queries.')
      })
      .finally(() => setLoading(false))
  }

  const handleCalculateAllOptimizations = async () => {
    setIsCalculatingOptimizations(true)
    setError(null)
    setCalculationSuccessMsg(null)
    try {
      const res = await calculateQueryOptimizations()
      setCalculationSuccessMsg(`✓ Successfully evaluated and computed before/after plan costs and simulated latencies for ${res.calculated_count} queries!`)
      fetchQueries()
    } catch (err: any) {
      setError(err?.message || 'Failed to calculate query optimizations.')
    } finally {
      setIsCalculatingOptimizations(false)
    }
  }

  const handleCalculateSingleQuery = async (queryId: number) => {
    setIsCalculatingOptimizations(true)
    setError(null)
    try {
      await calculateQueryOptimizations(queryId)
      fetchQueries()
    } catch (err: any) {
      setError(err?.message || `Failed to calculate optimization for query #${queryId}.`)
    } finally {
      setIsCalculatingOptimizations(false)
    }
  }

  useEffect(() => {
    fetchQueries()
  }, [page, pageSize, thresholdMs])

  const handleToggleTrace = async (queryId: number) => {
    if (selectedTraceId === queryId) {
      setSelectedTraceId(null)
      setTraceData(null)
      return
    }

    setSelectedTraceId(queryId)
    setLoadingTrace(true)
    setTraceError(null)
    try {
      const data = await getQueryOptimizationTrace(queryId)
      setTraceData(data)
    } catch (err: any) {
      setTraceError(err?.message || 'Failed to load optimization trace.')
    } finally {
      setLoadingTrace(false)
    }
  }

  const handleSimulateInTrace = async (recId: number) => {
    setIsSimulating(true)
    setTraceError(null)
    try {
      await createSimulation(recId, 3)
      if (selectedTraceId) {
        const refreshed = await getQueryOptimizationTrace(selectedTraceId)
        setTraceData(refreshed)
      }
    } catch (err: any) {
      setTraceError(`Simulation failed: ${err.message}`)
    } finally {
      setIsSimulating(false)
    }
  }

  const handleApproveInTrace = async (recId: number) => {
    setIsDeciding(true)
    setTraceError(null)
    try {
      await approveRecommendation(recId, 'Approved via Slow Queries trace')
      if (selectedTraceId) {
        const refreshed = await getQueryOptimizationTrace(selectedTraceId)
        setTraceData(refreshed)
      }
      fetchQueries()
    } catch (err: any) {
      setTraceError(`Approval failed: ${err.message}`)
    } finally {
      setIsDeciding(false)
    }
  }

  const handleRejectInTrace = async (recId: number) => {
    setIsDeciding(true)
    setTraceError(null)
    try {
      await rejectRecommendation(recId, 'Rejected via Slow Queries trace')
      if (selectedTraceId) {
        const refreshed = await getQueryOptimizationTrace(selectedTraceId)
        setTraceData(refreshed)
      }
      fetchQueries()
    } catch (err: any) {
      setTraceError(`Rejection failed: ${err.message}`)
    } finally {
      setIsDeciding(false)
    }
  }

  const filteredQueries = queries.filter((q) =>
    searchTerm ? q.normalized_query.toLowerCase().includes(searchTerm.toLowerCase()) || String(q.query_id).includes(searchTerm) : true
  )

  const totalPages = Math.ceil(total / pageSize) || 1

  return (
    <section>
      <div className="section-head" style={{ marginBottom: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
          <span className="badge badge-observed">OBSERVED: pg_stat_statements</span>
          <span className="badge sev-high">Telemetry Filter</span>
          <span className="badge badge-ai-analysis">Optimization Trace Enabled</span>
        </div>
        <h1 style={{ fontSize: '2.2rem', margin: 0 }}>Slow Queries Telemetry</h1>
        <p className="subtitle" style={{ fontSize: '0.95rem', color: '#64748b' }}>
          Queries exceeding configured mean latency threshold. Click "Analyze Optimization" to inspect the end-to-end trace.
        </p>
      </div>

      {/* Visual Pipeline Header */}
      <OptimizationFlowHeader currentStage="detect" />

      {/* Self-Explanatory Telemetry Banner */}
      <div className="guide-banner">
        <div className="guide-banner-icon">⏱️</div>
        <div className="guide-banner-content">
          <div className="guide-banner-title">
            <span>CONTINUOUS POSTGRESQL TELEMETRY MONITORING</span>
            <span className="badge badge-observed">PG_STAT_STATEMENTS</span>
          </div>
          <p className="guide-banner-desc">
            This dashboard continuously observes normalized SQL executions from PostgreSQL's <code>pg_stat_statements</code>. Each slow query is analyzed across the 3 severity tiers. Click <strong>"Calculate Before/After Cost & Latency"</strong> to run or refresh HypoPG virtual index cost simulations across all slow queries.
          </p>
          <div className="guide-banner-pills">
            <span className="badge badge-danger">Critical: &ge;500ms</span>
            <span className="badge badge-warning">High: 100–499ms</span>
            <span className="badge badge-success">Standard: &lt;100ms</span>
            <span className="badge badge-ai-analysis">⚡ 100% Simulation Coverage</span>
          </div>
        </div>
      </div>

      <div className="card filter-bar" style={{ display: 'flex', gap: '12px', alignItems: 'center', padding: '12px 18px', marginBottom: '16px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '11px', fontWeight: 600, color: '#475467' }}>Search Query / ID</label>
          <input
            type="text"
            className="filter-input"
            placeholder="Filter by table, column, or ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '11px', fontWeight: 600, color: '#475467' }}>Latency Threshold</label>
          <select
            className="filter-select"
            value={thresholdMs}
            onChange={(e) => {
              setThresholdMs(Number(e.target.value))
              setPage(1)
            }}
          >
            <option value={10}>&gt; 10 ms (Fine grained)</option>
            <option value={50}>&gt; 50 ms (Moderate)</option>
            <option value={100}>&gt; 100 ms (Standard Slow)</option>
            <option value={500}>&gt; 500 ms (High Latency)</option>
            <option value={1000}>&gt; 1,000 ms (Critical)</option>
          </select>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '11px', fontWeight: 600, color: '#475467' }}>Page Size</label>
          <select
            className="filter-select"
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value))
              setPage(1)
            }}
          >
            <option value={10}>10 per page</option>
            <option value={20}>20 per page</option>
            <option value={50}>50 per page</option>
          </select>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignSelf: 'flex-end', marginLeft: 'auto' }}>
          <button
            className="btn btn-primary"
            onClick={handleCalculateAllOptimizations}
            disabled={isCalculatingOptimizations || loading}
            style={{
              padding: '8px 16px',
              height: '36px',
              background: '#059669',
              borderColor: '#047857',
              fontWeight: 600,
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            {isCalculatingOptimizations ? '⚡ Calculating...' : '⚡ Calculate Before/After Cost & Latency'}
          </button>

          <button
            className="btn-secondary"
            onClick={fetchQueries}
            style={{ padding: '8px 14px', height: '36px', fontSize: '12px' }}
          >
            Refresh
          </button>
        </div>
      </div>

      {calculationSuccessMsg && (
        <div className="card" style={{ borderLeft: '4px solid #10b981', background: 'rgba(16, 185, 129, 0.08)', color: '#6ee7b7', padding: '12px 16px', marginBottom: '14px' }}>
          <strong>{calculationSuccessMsg}</strong>
        </div>
      )}

      {error && <div className="alert">{error}</div>}

      <article className="card section-card">
        {loading ? (
          <div className="loading-box">Fetching query statistics from PostgreSQL catalog...</div>
        ) : filteredQueries.length === 0 ? (
          <div className="empty-state">
            <h3>No slow queries matched</h3>
            <p>Try lowering the latency threshold or run a workload to generate telemetry.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Query ID</th>
                  <th>Severity</th>
                  <th>Plan Cost (Before → After)</th>
                  <th>Latency (Before → After)</th>
                  <th>Executions</th>
                  <th>Shared Read / Hit</th>
                  <th>Normalized Statement</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredQueries.map((q) => {
                  const isCritical = q.mean_exec_time_ms >= 500
                  const isWarning = q.mean_exec_time_ms >= 100
                  const isTraceOpen = selectedTraceId === q.query_id

                  return (
                    <React.Fragment key={`${q.query_id}-${q.id}`}>
                      <tr>
                        <td>
                          <strong><code>{q.query_id}</code></strong>
                        </td>
                        <td>
                          {isCritical ? (
                            <span className="badge sev-high">CRITICAL</span>
                          ) : isWarning ? (
                            <span className="badge sev-med">HIGH</span>
                          ) : (
                            <span className="badge sev-low">MODERATE</span>
                          )}
                        </td>
                        <td>
                          {q.optimization_summary ? (
                            <div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ color: '#fca5a5', fontSize: '12px' }}>
                                  {q.optimization_summary.baseline_cost.toFixed(1)}
                                </span>
                                <span style={{ color: '#64748b' }}>→</span>
                                <strong style={{ color: '#86efac', fontSize: '12px' }}>
                                  {q.optimization_summary.proposed_cost.toFixed(1)}
                                </strong>
                              </div>
                              <span className="badge" style={{ background: '#065f46', color: '#34d399', fontSize: '10px', marginTop: '3px' }}>
                                -{q.optimization_summary.cost_improvement_pct}%
                              </span>
                            </div>
                          ) : (
                            <button
                              className="secondary-button"
                              style={{ fontSize: '10px', padding: '3px 8px' }}
                              onClick={() => handleCalculateSingleQuery(q.query_id)}
                              disabled={isCalculatingOptimizations}
                            >
                              Calc Cost
                            </button>
                          )}
                        </td>
                        <td>
                          {q.optimization_summary ? (
                            <div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ color: '#f8fafc', fontSize: '12px' }}>
                                  {formatMs(q.optimization_summary.baseline_latency_ms)}
                                </span>
                                <span style={{ color: '#64748b' }}>→</span>
                                <strong style={{ color: '#38bdf8', fontSize: '12px' }}>
                                  {formatMs(q.optimization_summary.simulated_latency_ms)}
                                </strong>
                              </div>
                              <span className="badge" style={{ background: '#0369a1', color: '#7dd3fc', fontSize: '10px', marginTop: '3px' }}>
                                {q.optimization_summary.speedup_factor}x faster
                              </span>
                            </div>
                          ) : (
                            <strong style={{ color: isCritical ? '#dc2626' : isWarning ? '#d97706' : '#166534' }}>
                              {formatMs(q.mean_exec_time_ms)}
                            </strong>
                          )}
                        </td>
                        <td>{q.calls.toLocaleString()}</td>
                        <td>
                          <span title="Disk reads / Buffer hits">
                            {q.shared_blks_read.toLocaleString()} / {q.shared_blks_hit.toLocaleString()}
                          </span>
                        </td>
                        <td className="query-cell">{q.normalized_query}</td>
                        <td>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <button
                              className="btn btn-primary"
                              style={{
                                fontSize: '11px',
                                padding: '4px 8px',
                                background: isTraceOpen ? '#0f172a' : '#2563eb',
                                borderColor: '#2563eb',
                              }}
                              onClick={() => handleToggleTrace(q.query_id)}
                            >
                              {isTraceOpen ? 'Hide Trace ▲' : '⚡ Analyze Optimization'}
                            </button>
                            <div style={{ display: 'flex', gap: '8px', fontSize: '11px' }}>
                              <Link to={`/queries?id=${q.id || q.query_id}`} style={{ color: '#64748b', textDecoration: 'none' }}>
                                Inspect
                              </Link>
                              <Link to={`/plans?queryId=${q.id || q.query_id}`} style={{ color: '#7c3aed', textDecoration: 'none' }}>
                                Plan
                              </Link>
                            </div>
                          </div>
                        </td>
                      </tr>

                      {/* Expandable Inline Optimization Trace */}
                      {isTraceOpen && (
                        <tr>
                          <td colSpan={8} style={{ background: '#090d16', padding: '16px' }}>
                            {loadingTrace ? (
                              <div className="loading-box" style={{ color: '#94a3b8' }}>
                                Constructing full Optimization Trace for Query #{q.query_id}...
                              </div>
                            ) : traceError ? (
                              <div className="alert">{traceError}</div>
                            ) : traceData ? (
                              <OptimizationTrace
                                title={`Query #${q.query_id} Optimization Trace: ${q.normalized_query.slice(0, 60)}...`}
                                query={traceData.query}
                                recommendation={
                                  traceData.matching_recommendations.length > 0
                                    ? traceData.matching_recommendations[0]
                                    : null
                                }
                                simulation={traceData.latest_simulation}
                                auditInfo={
                                  traceData.audit_events.length > 0
                                    ? {
                                        action: traceData.audit_events[0].action,
                                        status: traceData.audit_events[0].new_status,
                                        reason: traceData.audit_events[0].reason,
                                        timestamp: traceData.audit_events[0].created_at ?? undefined,
                                      }
                                    : null
                                }
                                onSimulate={handleSimulateInTrace}
                                onApprove={handleApproveInTrace}
                                onReject={handleRejectInTrace}
                                isSimulating={isSimulating}
                                isDeciding={isDeciding}
                                initialExpanded={true}
                              />
                            ) : null}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="pagination">
          <span>
            Showing {filteredQueries.length} of {total} slow queries (Page {page} of {totalPages})
          </span>
          <div className="pagination-buttons">
            <button
              className="btn-secondary"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <button
              className="btn-secondary"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </article>
    </section>
  )
}
