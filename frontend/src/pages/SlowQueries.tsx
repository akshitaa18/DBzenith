import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getSlowQueries, type QueryDetail } from '../lib/api'

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
        </div>
        <h1 style={{ fontSize: '2.2rem', margin: 0 }}>Slow Queries Telemetry</h1>
        <p className="subtitle" style={{ fontSize: '0.95rem', color: '#64748b' }}>
          Queries exceeding configured mean latency threshold. Telemetry is masked and privacy-safe.
        </p>
      </div>

      <div className="card filter-bar" style={{ display: 'flex', gap: '12px', alignItems: 'center', padding: '12px 18px', marginBottom: '16px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '11px', fontWeight: 600, color: '#475467' }}>Search Query / ID</label>
          <input
            type="text"
            className="filter-input"
            placeholder="Filter by statement or query ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '11px', fontWeight: 600, color: '#475467' }}>Min Latency Threshold (ms)</label>
          <select
            className="filter-select"
            value={thresholdMs}
            onChange={(e) => {
              setThresholdMs(Number(e.target.value))
              setPage(1)
            }}
          >
            <option value={10}>&gt; 10 ms (All Active)</option>
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

                  return (
                    <tr key={`${q.query_id}-${q.id}`}>
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
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <Link to={`/queries?id=${q.query_id}`} style={{ color: '#2563eb', fontWeight: 600, textDecoration: 'none' }}>
                            Inspect
                          </Link>
                          <Link to={`/plans?queryId=${q.query_id}`} style={{ color: '#7c3aed', fontWeight: 600, textDecoration: 'none' }}>
                            Plan
                          </Link>
                        </div>
                      </td>
                    </tr>
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
