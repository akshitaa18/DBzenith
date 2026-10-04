import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getSlowQueries,
  getQueryOptimizationTrace,
  createSimulation,
  approveRecommendation,
  rejectRecommendation,
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
    try {
      await createSimulation(recId, 3)
      if (selectedTraceId) {
        const refreshed = await getQueryOptimizationTrace(selectedTraceId)
        setTraceData(refreshed)
      }
    } catch (err: any) {
      alert(`Simulation failed: ${err.message}`)
    } finally {
      setIsSimulating(false)
    }
  }

  const handleApproveInTrace = async (recId: number) => {
    setIsDeciding(true)
    try {
      await approveRecommendation(recId, 'Approved via Slow Queries trace')
      if (selectedTraceId) {
        const refreshed = await getQueryOptimizationTrace(selectedTraceId)
        setTraceData(refreshed)
      }
      fetchQueries()
    } catch (err: any) {
      alert(`Approval failed: ${err.message}`)
    } finally {
      setIsDeciding(false)
    }
  }

  const handleRejectInTrace = async (recId: number) => {
    setIsDeciding(true)
    try {
      await rejectRecommendation(recId, 'Rejected via Slow Queries trace')
      if (selectedTraceId) {
        const refreshed = await getQueryOptimizationTrace(selectedTraceId)
        setTraceData(refreshed)
      }
      fetchQueries()
    } catch (err: any) {
      alert(`Rejection failed: ${err.message}`)
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

        <button
          className="btn-secondary"
          onClick={fetchQueries}
          style={{ alignSelf: 'flex-end', padding: '8px 14px', height: '36px' }}
        >
          Refresh
        </button>
      </div>

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
                  <th>Mean Latency</th>
                  <th>Min / Max</th>
                  <th>Executions</th>
                  <th>Shared Read / Hit</th>
                  <th>Temp Spills</th>
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
                          <strong style={{ color: isCritical ? '#dc2626' : isWarning ? '#d97706' : '#166534' }}>
                            {formatMs(q.mean_exec_time_ms)}
                          </strong>
                        </td>
                        <td>
                          <small style={{ color: '#64748b' }}>
                            {formatMs(q.min_exec_time_ms)} / {formatMs(q.max_exec_time_ms)}
                          </small>
                        </td>
                        <td>{q.calls.toLocaleString()}</td>
                        <td>
                          <span title="Disk reads / Buffer hits">
                            {q.shared_blks_read.toLocaleString()} / {q.shared_blks_hit.toLocaleString()}
                          </span>
                        </td>
                        <td>
                          <span style={{ color: q.temp_blks_written > 0 ? '#b91c1c' : '#64748b' }}>
                            {q.temp_blks_written.toLocaleString()}
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
                              <Link to={`/queries?id=${q.query_id}`} style={{ color: '#64748b', textDecoration: 'none' }}>
                                Inspect
                              </Link>
                              <Link to={`/plans?queryId=${q.query_id}`} style={{ color: '#7c3aed', textDecoration: 'none' }}>
                                Plan
                              </Link>
                            </div>
                          </div>
                        </td>
                      </tr>

                      {/* Expandable Inline Optimization Trace */}
                      {isTraceOpen && (
                        <tr>
                          <td colSpan={9} style={{ background: '#090d16', padding: '16px' }}>
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
