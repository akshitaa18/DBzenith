import React, { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
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
import { ProvenanceBadge } from '../components/ProvenanceBadge'
import { useAuth } from '../context/AuthContext'

const FILTER_STORAGE_KEY = 'dbzenith_slow_queries_filters'

function formatMs(value: number) {
  return `${value.toFixed(2)} ms`
}

export function SlowQueries() {
  const { canSimulate, canApprove } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  // Initialize from URL searchParams (or restore from sessionStorage if URL is bare)
  const initialParams = (() => {
    if (Array.from(searchParams.keys()).length > 0) return searchParams
    try {
      const saved = typeof window !== 'undefined' ? window.sessionStorage.getItem(FILTER_STORAGE_KEY) : null
      if (saved) return new URLSearchParams(saved)
    } catch {
      // Ignore storage errors
    }
    return searchParams
  })()

  const [queries, setQueries] = useState<QueryDetail[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(() => Math.max(1, Number(initialParams.get('page') || 1)))
  const [pageSize, setPageSize] = useState(() => Number(initialParams.get('page_size') || 10))
  const [thresholdMs, setThresholdMs] = useState(() =>
    initialParams.get('min_mean_ms') !== null ? Number(initialParams.get('min_mean_ms')) : 50,
  )
  const [severityFilter, setSeverityFilter] = useState(() => initialParams.get('severity') || 'all')
  const [windowSeconds, setWindowSeconds] = useState<number | undefined>(() =>
    initialParams.get('window_seconds') ? Number(initialParams.get('window_seconds')) : undefined,
  )
  const [databaseFilter, setDatabaseFilter] = useState(() => initialParams.get('database_name') || '')
  const [fingerprintFilter, setFingerprintFilter] = useState(() => initialParams.get('query_fingerprint') || '')
  const [searchTerm, setSearchTerm] = useState(() => initialParams.get('search') || '')
  const [sortBy, setSortBy] = useState(() => initialParams.get('sort_by') || 'mean_exec_time_ms')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(() =>
    initialParams.get('sort_dir') === 'asc' ? 'asc' : 'desc',
  )

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

  // Sync active filters to URL searchParams and sessionStorage for seamless navigation persistence
  useEffect(() => {
    const next = new URLSearchParams()
    if (page > 1) next.set('page', String(page))
    if (pageSize !== 10) next.set('page_size', String(pageSize))
    if (thresholdMs !== 50) next.set('min_mean_ms', String(thresholdMs))
    if (severityFilter && severityFilter !== 'all') next.set('severity', severityFilter)
    if (windowSeconds !== undefined && windowSeconds > 0) next.set('window_seconds', String(windowSeconds))
    if (databaseFilter.trim()) next.set('database_name', databaseFilter.trim())
    if (fingerprintFilter.trim()) next.set('query_fingerprint', fingerprintFilter.trim())
    if (searchTerm.trim()) next.set('search', searchTerm.trim())
    if (sortBy !== 'mean_exec_time_ms') next.set('sort_by', sortBy)
    if (sortDir !== 'desc') next.set('sort_dir', sortDir)

    const qs = next.toString()
    if (qs !== searchParams.toString()) {
      setSearchParams(next, { replace: true })
    }
    try {
      if (typeof window !== 'undefined') {
        if (qs) {
          window.sessionStorage.setItem(FILTER_STORAGE_KEY, qs)
        } else {
          window.sessionStorage.removeItem(FILTER_STORAGE_KEY)
        }
      }
    } catch {
      // Ignore storage errors
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    page,
    pageSize,
    thresholdMs,
    severityFilter,
    windowSeconds,
    databaseFilter,
    fingerprintFilter,
    searchTerm,
    sortBy,
    sortDir,
  ])

  const hasExtraFilters =
    severityFilter !== 'all' ||
    windowSeconds !== undefined ||
    Boolean(databaseFilter.trim()) ||
    Boolean(fingerprintFilter.trim()) ||
    Boolean(searchTerm.trim()) ||
    sortBy !== 'mean_exec_time_ms' ||
    sortDir !== 'desc'

  const fetchQueries = () => {
    setLoading(true)
    setError(null)
    const filterPayload = hasExtraFilters
      ? {
          severity: severityFilter,
          windowSeconds,
          databaseName: databaseFilter,
          queryFingerprint: fingerprintFilter,
          search: searchTerm,
          sortBy,
          sortDir,
        }
      : undefined
    const req = filterPayload
      ? getSlowQueries(page, pageSize, thresholdMs, filterPayload)
      : getSlowQueries(page, pageSize, thresholdMs)

    req
      .then((data) => {
        setQueries(data.items || [])
        setTotal(data.total ?? 0)
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch slow queries.')
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchQueries()
  }, [
    page,
    pageSize,
    thresholdMs,
    severityFilter,
    windowSeconds,
    databaseFilter,
    fingerprintFilter,
    searchTerm,
    sortBy,
    sortDir,
  ])

  const handleSortColumn = (col: string) => {
    if (sortBy === col) {
      setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortBy(col)
      setSortDir('desc')
    }
    setPage(1)
  }

  const handleResetFilters = () => {
    setPage(1)
    setPageSize(10)
    setThresholdMs(50)
    setSeverityFilter('all')
    setWindowSeconds(undefined)
    setDatabaseFilter('')
    setFingerprintFilter('')
    setSearchTerm('')
    setSortBy('mean_exec_time_ms')
    setSortDir('desc')
    try {
      if (typeof window !== 'undefined') {
        window.sessionStorage.removeItem(FILTER_STORAGE_KEY)
      }
    } catch {
      // Ignore storage errors
    }
  }

  const handleCalculateAllOptimizations = async () => {
    setIsCalculatingOptimizations(true)
    setError(null)
    setCalculationSuccessMsg(null)
    try {
      const res = await calculateQueryOptimizations()
      setCalculationSuccessMsg(
        `✓ Successfully evaluated and computed hypothetical before/after plan cost estimates for ${res.calculated_count} queries!`,
      )
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

  const totalPages = Math.ceil(total / pageSize) || 1
  const firstQuery = queries[0]
  const currentFilterQueryString = searchParams.toString()
  const returnToPath = currentFilterQueryString
    ? `/slow-queries?${currentFilterQueryString}`
    : '/slow-queries'

  const renderSortIndicator = (col: string) => {
    if (sortBy !== col) return <span style={{ color: '#475569', marginLeft: '4px' }}>↕</span>
    return (
      <span style={{ color: '#38bdf8', marginLeft: '4px' }}>
        {sortDir === 'desc' ? '▼' : '▲'}
      </span>
    )
  }

  return (
    <section>
      <div className="section-head" style={{ marginBottom: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
          {firstQuery && (
            <ProvenanceBadge
              badge={firstQuery.provenance_badge}
              state={firstQuery.provenance_state}
              isSynthetic={firstQuery.is_synthetic}
              prefix="DATA SOURCE"
            />
          )}
          <span className="badge badge-observed">OBSERVED: pg_stat_statements</span>
          <span className="badge sev-high">Server-Side Telemetry Filter</span>
          <span className="badge badge-ai-analysis">Optimization Trace Enabled</span>
        </div>
        <h1 style={{ fontSize: '2.2rem', margin: 0 }}>Slow Queries Telemetry</h1>
        <p className="subtitle" style={{ fontSize: '0.95rem', color: '#94a3b8' }}>
          Server-side paginated, sorted, and filtered query observations by time window, database, query fingerprint, latency threshold, and severity. Filters are preserved when navigating to Query Details.
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
            Observes normalized SQL executions from PostgreSQL's <code>pg_stat_statements</code>. Filter by observation time window, database/schema, query fingerprint, latency threshold, or severity tier, and sort by execution metrics.
          </p>
          <div className="guide-banner-pills">
            <span className="badge badge-danger">Critical: &ge;500ms</span>
            <span className="badge badge-warning">High: 100–499ms</span>
            <span className="badge badge-success">Moderate: &lt;100ms</span>
            <span className="badge badge-ai-analysis">⚡ Preserves Filters Across Navigation</span>
          </div>
        </div>
      </div>

      {/* Server-Side Filter & Sort Bar */}
      <div
        className="card filter-bar"
        data-testid="slow-queries-filter-bar"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
          gap: '12px',
          alignItems: 'end',
          padding: '14px 18px',
          marginBottom: '16px',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label htmlFor="sq-search-input" style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8' }}>
            Search SQL / Query ID
          </label>
          <input
            id="sq-search-input"
            type="text"
            className="filter-input"
            style={{ minWidth: 'unset', width: '100%', boxSizing: 'border-box' }}
            placeholder="Table, predicate, or query ID..."
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value)
              setPage(1)
            }}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label htmlFor="sq-fingerprint-input" style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8' }}>
            Query Fingerprint
          </label>
          <input
            id="sq-fingerprint-input"
            type="text"
            className="filter-input"
            style={{ minWidth: 'unset', width: '100%', boxSizing: 'border-box' }}
            placeholder="e.g. qfp_8a3f..."
            value={fingerprintFilter}
            onChange={(e) => {
              setFingerprintFilter(e.target.value)
              setPage(1)
            }}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label htmlFor="sq-db-input" style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8' }}>
            Database / Schema
          </label>
          <input
            id="sq-db-input"
            type="text"
            className="filter-input"
            style={{ minWidth: 'unset', width: '100%', boxSizing: 'border-box' }}
            placeholder="e.g. dbzenith_prod"
            value={databaseFilter}
            onChange={(e) => {
              setDatabaseFilter(e.target.value)
              setPage(1)
            }}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label htmlFor="sq-window-select" style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8' }}>
            Time Window
          </label>
          <select
            id="sq-window-select"
            className="filter-select"
            value={windowSeconds ?? ''}
            onChange={(e) => {
              setWindowSeconds(e.target.value ? Number(e.target.value) : undefined)
              setPage(1)
            }}
          >
            <option value="">All Captured Windows</option>
            <option value={60}>Last 1 Minute (60s)</option>
            <option value={3600}>Last 1 Hour (3,600s)</option>
            <option value={86400}>Last 24 Hours (86,400s)</option>
            <option value={604800}>Last 7 Days (604,800s)</option>
          </select>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label htmlFor="sq-threshold-select" style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8' }}>
            Latency Threshold
          </label>
          <select
            id="sq-threshold-select"
            className="filter-select"
            value={thresholdMs}
            onChange={(e) => {
              setThresholdMs(Number(e.target.value))
              setPage(1)
            }}
          >
            <option value={0}>&ge; 0 ms (All Queries)</option>
            <option value={10}>&gt; 10 ms (Fine grained)</option>
            <option value={50}>&gt; 50 ms (Moderate)</option>
            <option value={100}>&gt; 100 ms (Standard Slow)</option>
            <option value={500}>&gt; 500 ms (High Latency)</option>
            <option value={1000}>&gt; 1,000 ms (Critical)</option>
          </select>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label htmlFor="sq-severity-select" style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8' }}>
            Severity Tier
          </label>
          <select
            id="sq-severity-select"
            className="filter-select"
            value={severityFilter}
            onChange={(e) => {
              setSeverityFilter(e.target.value)
              setPage(1)
            }}
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical (&ge;500 ms)</option>
            <option value="high">High (100–499 ms)</option>
            <option value="moderate">Moderate (&lt;100 ms)</option>
          </select>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label htmlFor="sq-sort-select" style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8' }}>
            Sort By
          </label>
          <div style={{ display: 'flex', gap: '4px' }}>
            <select
              id="sq-sort-select"
              className="filter-select"
              style={{ flex: 1 }}
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value)
                setPage(1)
              }}
            >
              <option value="mean_exec_time_ms">Mean Latency</option>
              <option value="total_exec_time_ms">Total Time</option>
              <option value="calls">Execution Calls</option>
              <option value="rows">Rows Returned</option>
              <option value="shared_blks_read">Shared Disk Reads</option>
              <option value="query_frequency_per_minute">Frequency / min</option>
            </select>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              aria-label={`Sort direction ${sortDir === 'desc' ? 'descending' : 'ascending'}`}
              onClick={() => {
                setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'))
                setPage(1)
              }}
              title="Toggle sort direction"
            >
              {sortDir === 'desc' ? '▼ DESC' : '▲ ASC'}
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label htmlFor="sq-pagesize-select" style={{ fontSize: '11px', fontWeight: 600, color: '#94a3b8' }}>
            Page Size
          </label>
          <select
            id="sq-pagesize-select"
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
      </div>

      {/* Action Toolbar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '12px', color: '#94a3b8' }}>
            Matched <strong>{total}</strong> queries
          </span>
          {(hasExtraFilters || thresholdMs !== 50) && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleResetFilters}
            >
              Reset Filters
            </button>
          )}
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          {canSimulate && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleCalculateAllOptimizations}
              disabled={isCalculatingOptimizations || loading}
              style={{
                padding: '7px 14px',
                background: '#059669',
                borderColor: '#047857',
                fontWeight: 600,
                fontSize: '12px',
              }}
            >
              {isCalculatingOptimizations ? '⚡ Calculating...' : '⚡ Calculate Before/After Cost & Latency'}
            </button>
          )}
          <button
            type="button"
            className="btn btn-secondary"
            onClick={fetchQueries}
            style={{ padding: '7px 14px', fontSize: '12px' }}
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

      {error && (
        <div
          className="alert"
          role="alert"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}
        >
          <span>{error}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={fetchQueries}>
            Retry
          </button>
        </div>
      )}

      <article className="card section-card">
        {loading ? (
          <div className="loading-box">Fetching query statistics from PostgreSQL catalog...</div>
        ) : queries.length === 0 ? (
          <div className="empty-state">
            <h3>No slow queries matched</h3>
            <p>Try lowering the latency threshold or clearing active filters.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Query ID / Fingerprint</th>
                  <th>Database</th>
                  <th>Provenance</th>
                  <th>Severity</th>
                  <th>Plan Cost (Before → After)</th>
                  <th
                    className="th-sortable"
                    onClick={() => handleSortColumn('mean_exec_time_ms')}
                    title="Sort by Mean Latency"
                  >
                    Latency (Before → After) {renderSortIndicator('mean_exec_time_ms')}
                  </th>
                  <th
                    className="th-sortable"
                    onClick={() => handleSortColumn('calls')}
                    title="Sort by Execution Calls"
                  >
                    Executions {renderSortIndicator('calls')}
                  </th>
                  <th
                    className="th-sortable"
                    onClick={() => handleSortColumn('shared_blks_read')}
                    title="Sort by Shared Disk Reads"
                  >
                    Shared Read / Hit {renderSortIndicator('shared_blks_read')}
                  </th>
                  <th>Normalized Statement</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {queries.map((q) => {
                  const isCritical = q.mean_exec_time_ms >= 500
                  const isWarning = q.mean_exec_time_ms >= 100
                  const isTraceOpen = selectedTraceId === q.query_id
                  const detailHref = `/queries?id=${q.id || q.query_id}&returnTo=${encodeURIComponent(returnToPath)}`

                  return (
                    <React.Fragment key={`${q.query_id}-${q.id}`}>
                      <tr>
                        <td>
                          <div>
                            <strong><code>{q.query_id}</code></strong>
                          </div>
                          {q.query_fingerprint && (
                            <div style={{ fontSize: '10px', color: '#64748b', fontFamily: 'monospace' }}>
                              {q.query_fingerprint}
                            </div>
                          )}
                        </td>
                        <td>
                          <span style={{ fontSize: '11px', color: '#cbd5e1', fontFamily: 'monospace' }}>
                            {q.database_name || 'default'}
                          </span>
                        </td>
                        <td>
                          <ProvenanceBadge
                            badge={q.provenance_badge}
                            state={q.provenance_state}
                            isSynthetic={q.is_synthetic}
                          />
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
                          ) : canSimulate ? (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              style={{ fontSize: '10px', padding: '3px 8px' }}
                              onClick={() => handleCalculateSingleQuery(q.query_id)}
                              disabled={isCalculatingOptimizations}
                            >
                              Calc Cost
                            </button>
                          ) : (
                            <span style={{ color: '#64748b', fontSize: '11px' }}>—</span>
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
                              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '3px', flexWrap: 'wrap' }}>
                                <ProvenanceBadge
                                  badge={q.optimization_summary.provenance_badge || (q.optimization_summary.is_measured ? 'SIMULATED' : 'ESTIMATED')}
                                  state={q.optimization_summary.provenance_state}
                                  isSynthetic={q.optimization_summary.is_synthetic}
                                  style={{ fontSize: '9px', padding: '1px 6px' }}
                                />
                                <span className="badge" style={{ background: '#0369a1', color: '#7dd3fc', fontSize: '10px' }}>
                                  {q.optimization_summary.is_measured
                                    ? `${q.optimization_summary.speedup_factor}x benchmark`
                                    : `Est. ${q.optimization_summary.speedup_factor}x (unmeasured)`}
                                </span>
                              </div>
                            </div>
                          ) : (
                            <strong style={{ color: isCritical ? '#fca5a5' : isWarning ? '#fcd34d' : '#6ee7b7' }}>
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
                              type="button"
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
                              <Link to={detailHref} style={{ color: '#38bdf8', textDecoration: 'none', fontWeight: 600 }}>
                                Inspect Details
                              </Link>
                              <Link to={`/plans?queryId=${q.id || q.query_id}`} style={{ color: '#a78bfa', textDecoration: 'none' }}>
                                Plan
                              </Link>
                            </div>
                          </div>
                        </td>
                      </tr>

                      {/* Expandable Inline Optimization Trace */}
                      {isTraceOpen && (
                        <tr>
                          <td colSpan={10} style={{ background: '#090d16', padding: '16px' }}>
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
                                onSimulate={canSimulate ? handleSimulateInTrace : undefined}
                                onApprove={canApprove ? handleApproveInTrace : undefined}
                                onReject={canApprove ? handleRejectInTrace : undefined}
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
            Showing {queries.length} of {total} slow queries (Page {page} of {totalPages})
          </span>
          <div className="pagination-buttons">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn btn-secondary"
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
