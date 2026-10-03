import { useEffect, useState } from 'react'
import { getHealth, getSlowQueries, getWorkloadSummary, type QueryDetail, type WorkloadSummary } from '../lib/api'

function formatMs(value: number) {
  return `${value.toFixed(2)} ms`
}

function shortQuery(query: string) {
  return query.length > 90 ? `${query.slice(0, 90)}…` : query
}

export function Dashboard() {
  const [status, setStatus] = useState<'checking' | 'online' | 'offline'>('checking')
  const [summary, setSummary] = useState<WorkloadSummary | null>(null)
  const [slow, setSlow] = useState<QueryDetail[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getHealth(), getWorkloadSummary(), getSlowQueries(1, 8)])
      .then(([, workload, slowQueries]) => {
        setStatus('online')
        setSummary(workload)
        setSlow(slowQueries.items)
      })
      .catch(() => {
        setStatus('offline')
        setError('Telemetry is unavailable. Make sure PostgreSQL and the backend are running.')
      })
  }, [])

  return (
    <section>
      <div className="hero">
        <p className="eyebrow">PostgreSQL workload telemetry</p>
        <h1>DBZenith</h1>
        <p className="subtitle">
          Live workload visibility from PostgreSQL statistics, catalogs, optional pg_qualstats data,
          and EXPLAIN JSON plans.
        </p>
        <span className={`status ${status}`}>API: {status}</span>
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="grid metrics">
        <article className="card"><h2>Calls</h2><strong>{summary?.total_calls.toLocaleString() ?? '—'}</strong><p>Observed in the latest snapshot</p></article>
        <article className="card"><h2>Unique queries</h2><strong>{summary?.unique_queries ?? '—'}</strong><p>pg_stat_statements entries</p></article>
        <article className="card"><h2>Slow queries</h2><strong>{summary?.slow_queries ?? '—'}</strong><p>Above configured mean latency threshold</p></article>
        <article className="card"><h2>Total execution</h2><strong>{summary ? formatMs(summary.total_exec_time_ms) : '—'}</strong><p>Cumulative execution time</p></article>
      </div>

      <article className="card section-card">
        <div className="section-heading"><h2>Top workload</h2><span>{summary?.captured_at ? new Date(summary.captured_at).toLocaleString() : 'No snapshot yet'}</span></div>
        {summary?.top_queries.length ? (
          <div className="table-wrap"><table><thead><tr><th>Query ID</th><th>Calls</th><th>Mean</th><th>Total</th><th>Query</th></tr></thead>
            <tbody>{summary.top_queries.map((q) => <tr key={q.query_id}><td>{q.query_id}</td><td>{q.calls.toLocaleString()}</td><td>{formatMs(q.mean_exec_time_ms)}</td><td>{formatMs(q.total_exec_time_ms)}</td><td className="query-cell">{shortQuery(q.query)}</td></tr>)}</tbody>
          </table></div>
        ) : <p className="muted">Run the synthetic workload to populate real telemetry.</p>}
      </article>

      <article className="card section-card">
        <div className="section-heading"><h2>Slow queries</h2><span>Mean execution time</span></div>
        {slow.length ? (
          <div className="table-wrap"><table><thead><tr><th>Query ID</th><th>Mean</th><th>Min</th><th>Max</th><th>Blocks read</th><th>Query</th></tr></thead>
            <tbody>{slow.map((q) => <tr key={`${q.query_id}-${q.id}`}><td>{q.query_id}</td><td>{formatMs(q.mean_exec_time_ms)}</td><td>{formatMs(q.min_exec_time_ms)}</td><td>{formatMs(q.max_exec_time_ms)}</td><td>{q.shared_blks_read.toLocaleString()}</td><td className="query-cell">{shortQuery(q.normalized_query)}</td></tr>)}</tbody>
          </table></div>
        ) : <p className="muted">No slow queries above the configured threshold.</p>}
      </article>
    </section>
  )
}
