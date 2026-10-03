import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getHealth, getWorkloadSummary, getWorkloadSnapshots, type WorkloadSummary } from '../lib/api'

function formatMs(value: number) {
  return `${value.toFixed(2)} ms`
}

export function Overview() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<WorkloadSummary | null>(null)
  const [snapshots, setSnapshots] = useState<Array<Record<string, unknown>>>([])
  const [health, setHealth] = useState<{ status: string; service: string; version: string } | null>(null)

  useEffect(() => {
    Promise.all([getHealth(), getWorkloadSummary(), getWorkloadSnapshots(5)])
      .then(([h, s, snaps]) => {
        setHealth(h)
        setSummary(s)
        setSnapshots(snaps)
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch telemetry overview.')
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div className="loading-box">Loading PostgreSQL workload telemetry from pg_stat_statements...</div>
  }

  return (
    <section>
      <div className="hero" style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
          <span className="badge badge-observed">OBSERVED: pg_stat_statements</span>
          <span className="status online">API: {health?.status ?? 'online'}</span>
        </div>
        <h1 style={{ fontSize: '2.4rem', margin: '4px 0 10px 0' }}>Workload Telemetry Overview</h1>
        <p className="subtitle" style={{ fontSize: '1rem', color: '#64748b', maxWidth: '800px' }}>
          Live telemetry captured through DBZenith's privacy-preserving telemetry gateway. Metrics are
          derived directly from PostgreSQL statistics and catalog tables.
        </p>
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="grid metrics" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '14px', marginBottom: '20px' }}>
        <article className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Total Calls</h2>
            <span className="badge badge-observed">OBSERVED</span>
          </div>
          <strong style={{ fontSize: '26px' }}>{summary?.total_calls.toLocaleString() ?? '0'}</strong>
          <p>Total query executions recorded</p>
        </article>

        <article className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Cumulative Time</h2>
            <span className="badge badge-observed">OBSERVED</span>
          </div>
          <strong style={{ fontSize: '26px' }}>{summary ? formatMs(summary.total_exec_time_ms) : '0 ms'}</strong>
          <p>Execution time across all workers</p>
        </article>

        <article className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Unique Queries</h2>
            <span className="badge badge-observed">OBSERVED</span>
          </div>
          <strong style={{ fontSize: '26px' }}>{summary?.unique_queries ?? 0}</strong>
          <p>Distinct normalized query templates</p>
        </article>

        <article className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Slow Queries</h2>
            <span className="badge badge-observed">OBSERVED</span>
          </div>
          <strong style={{ fontSize: '26px', color: (summary?.slow_queries ?? 0) > 0 ? '#b91c1c' : '#166534' }}>
            {summary?.slow_queries ?? 0}
          </strong>
          <p>Queries exceeding latency threshold</p>
        </article>
      </div>

      <article className="card section-card">
        <div className="section-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <div>
            <h2 style={{ margin: 0 }}>Top Workload Queries</h2>
            <span className="muted">Ranked by total execution impact</span>
          </div>
          <span className="badge badge-observed">OBSERVED</span>
        </div>

        {summary?.top_queries?.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Query ID</th>
                  <th>Calls</th>
                  <th>Mean Latency</th>
                  <th>Total Time</th>
                  <th>Normalized Statement</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {summary.top_queries.map((q) => (
                  <tr key={q.query_id}>
                    <td><code>{q.query_id}</code></td>
                    <td>{q.calls.toLocaleString()}</td>
                    <td>
                      <span className={q.mean_exec_time_ms > 100 ? 'badge sev-high' : 'badge sev-low'}>
                        {formatMs(q.mean_exec_time_ms)}
                      </span>
                    </td>
                    <td>{formatMs(q.total_exec_time_ms)}</td>
                    <td className="query-cell">{q.query}</td>
                    <td>
                      <Link to={`/queries?id=${q.query_id}`} style={{ color: '#2563eb', textDecoration: 'none', fontWeight: 600 }}>
                        Inspect →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">
            <h3>No query executions captured</h3>
            <p>Run query traffic against the database to populate real pg_stat_statements telemetry.</p>
          </div>
        )}
      </article>

      {snapshots.length > 0 && (
        <article className="card section-card" style={{ marginTop: '20px' }}>
          <div className="section-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div>
              <h2 style={{ margin: 0 }}>Telemetry Snapshot History</h2>
              <span className="muted">Periodic captures from the background worker</span>
            </div>
            <span className="badge badge-observed">OBSERVED</span>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Snapshot ID</th>
                  <th>Captured At</th>
                  <th>Window Duration</th>
                  <th>Total Calls</th>
                  <th>Total Exec Time</th>
                  <th>Slow Queries</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((s, idx) => (
                  <tr key={String(s.id ?? idx)}>
                    <td><code>#{String(s.id ?? idx)}</code></td>
                    <td>{s.captured_at ? new Date(String(s.captured_at)).toLocaleString() : 'Recent'}</td>
                    <td>{String(s.window_seconds ?? 60)} s</td>
                    <td>{Number(s.total_calls ?? 0).toLocaleString()}</td>
                    <td>{formatMs(Number(s.total_exec_time_ms ?? 0))}</td>
                    <td>
                      <span className={Number(s.slow_queries ?? 0) > 0 ? 'badge sev-high' : 'badge sev-low'}>
                        {String(s.slow_queries ?? 0)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      )}
    </section>
  )
}
