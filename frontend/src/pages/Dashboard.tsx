import { useEffect, useState } from 'react'
import { analyzePlan, approveRecommendation, createSimulation, getHealth, getRecommendations, getSlowQueries, getWorkloadSummary, rejectRecommendation, type PlanAnalysis, type QueryDetail, type Recommendation, type Simulation, type WorkloadSummary } from '../lib/api'
import { PlanVisualization } from '../components/PlanVisualization'

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
  const [planSql, setPlanSql] = useState('SELECT * FROM telemetry_demo_orders WHERE customer_id = 42 ORDER BY created_at DESC LIMIT 20')
  const [planAnalysis, setPlanAnalysis] = useState<PlanAnalysis | null>(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [recommendationError, setRecommendationError] = useState<string | null>(null)
  const [simulationByRecommendation, setSimulationByRecommendation] = useState<Record<number, Simulation>>({})
  const [simulationLoading, setSimulationLoading] = useState<number | null>(null)

  useEffect(() => {
    Promise.all([getHealth(), getWorkloadSummary(), getSlowQueries(1, 8), getRecommendations(1, 8, 'pending')])
      .then(([, workload, slowQueries, recommendationPage]) => {
        setStatus('online')
        setSummary(workload)
        setSlow(slowQueries.items)
        setRecommendations(recommendationPage.items)
      })
      .catch(() => {
        setStatus('offline')
        setError('Telemetry is unavailable. Make sure PostgreSQL and the backend are running.')
      })
  }, [])


  const decideRecommendation = async (recommendation: Recommendation, action: 'approve' | 'reject') => {
    setRecommendationError(null)
    try {
      const updated = action === 'approve'
        ? await approveRecommendation(recommendation.id)
        : await rejectRecommendation(recommendation.id)
      setRecommendations((items) => items.filter((item) => item.id !== updated.id))
    } catch {
      setRecommendationError(`Could not ${action} recommendation.`)
    }
  }

  const runSimulation = async (recommendation: Recommendation) => {
    setRecommendationError(null)
    setSimulationLoading(recommendation.id)
    try {
      const simulation = await createSimulation(recommendation.id)
      setSimulationByRecommendation((items) => ({ ...items, [recommendation.id]: simulation }))
    } catch {
      setRecommendationError('Simulation failed. Make sure the isolated sandbox database is running and healthy.')
    } finally {
      setSimulationLoading(null)
    }
  }

  const runPlanAnalysis = async () => {
    setPlanLoading(true)
    setPlanError(null)
    try {
      setPlanAnalysis(await analyzePlan(planSql))
    } catch {
      setPlanError('Plan analysis failed. Use a read-only SELECT/WITH/VALUES statement and make sure PostgreSQL is running.')
    } finally {
      setPlanLoading(false)
    }
  }

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


      <article className="card section-card">
        <div className="section-heading"><h2>Optimization recommendations</h2><span>Deterministic analysis · approval required</span></div>
        {recommendationError && <div className="alert">{recommendationError}</div>}
        {recommendations.length ? recommendations.map((r) => (
          <div className="recommendation" key={r.id}>
            <div className="section-heading"><strong>{r.type.replaceAll('_', ' ')}</strong><span>Confidence {(r.confidence * 100).toFixed(0)}%</span></div>
            <p><strong>Target:</strong> {r.target}</p>
            <p><strong>Proposed change:</strong> <code>{r.proposed_change}</code></p>
            <p>{r.reason}</p>
            <p><strong>Expected benefit:</strong> {r.expected_benefit}</p>
            <p><strong>Risk:</strong> {r.risk}</p>
            <div className="recommendation-actions">
              <button className="primary-button" onClick={() => runSimulation(r)} disabled={simulationLoading === r.id}>
                {simulationLoading === r.id ? 'Simulating…' : 'Simulate impact'}
              </button>
              <button className="primary-button" onClick={() => decideRecommendation(r, 'approve')}>Approve</button>
              <button className="secondary-button" onClick={() => decideRecommendation(r, 'reject')}>Reject</button>
            </div>
            {simulationByRecommendation[r.id] && (() => {
              const sim = simulationByRecommendation[r.id]
              return <div className="simulation-result">
                <div className="section-heading"><strong>Sandbox simulation #{sim.id}</strong><span>{sim.status}</span></div>
                {sim.error ? <div className="alert">{sim.error}</div> : <>
                  <div className="simulation-metrics">
                    <span>Baseline cost <strong>{sim.baseline_cost?.toFixed(2) ?? '—'}</strong></span>
                    <span>Proposed cost <strong>{sim.proposed_cost?.toFixed(2) ?? '—'}</strong></span>
                    <span>Estimated improvement <strong>{sim.improvement?.toFixed(2) ?? '—'}%</strong></span>
                    <span>Confidence <strong>{(sim.confidence * 100).toFixed(0)}%</strong></span>
                  </div>
                  <p><strong>Storage:</strong> {String(sim.estimated_storage_impact.method ?? 'See simulation details')}</p>
                  <p><strong>Write overhead:</strong> {String(sim.write_overhead_estimate.estimated_relative_overhead ?? 'unknown')}</p>
                  {sim.plan_differences.length ? <p><strong>Plan change:</strong> {sim.plan_differences.map((d) => `${String(d.baseline_node ?? '—')} → ${String(d.proposed_node ?? '—')}`).join(', ')}</p> : null}
                  {sim.limitations.length ? <details><summary>Limitations</summary><ul>{sim.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details> : null}
                </>}
              </div>
            })()}
          </div>
        )) : <p className="muted">No pending recommendations. Generate real telemetry first.</p>}
      </article>

      <article className="card section-card">
        <div className="section-heading"><h2>Execution-plan analysis</h2><span>Real EXPLAIN (FORMAT JSON)</span></div>
        <textarea className="plan-input" value={planSql} onChange={(e) => setPlanSql(e.target.value)} aria-label="SQL for plan analysis" />
        <button className="primary-button" onClick={runPlanAnalysis} disabled={planLoading}>{planLoading ? 'Analyzing…' : 'Analyze plan'}</button>
        {planError && <div className="alert">{planError}</div>}
        {planAnalysis && <PlanVisualization analysis={planAnalysis} />}
        {planAnalysis?.explanation?.gnn && <div className="simulation-result">
          <div className="section-heading"><strong>GNN bottleneck prediction</strong><span>{String(planAnalysis.explanation.gnn.model_version)}</span></div>
          <p><strong>Validation accuracy:</strong> {(Number(planAnalysis.explanation.gnn.validation_metrics.accuracy) * 100).toFixed(1)}% · <strong>Macro F1:</strong> {(Number(planAnalysis.explanation.gnn.validation_metrics.macro_f1) * 100).toFixed(1)}%</p>
          {planAnalysis.explanation.gnn.predictions.map((item: any) => <div className="bottleneck" key={item.node_id}><strong>{item.node_id} · {item.prediction}</strong><p>Confidence {(Number(item.confidence) * 100).toFixed(1)}%</p><small>{item.evidence.join('; ')}</small></div>)}
        </div>}

        {planAnalysis?.bottlenecks.length ? (
          <div className="bottleneck-list">
            {planAnalysis.bottlenecks.map((b, i) => <div className="bottleneck" key={`${b.affected_node}-${b.type}-${i}`}><strong>{b.severity.toUpperCase()} · {b.type}</strong><p>{b.explanation}</p><small>{b.possible_remediation}</small></div>)}
          </div>
        ) : planAnalysis ? <p className="muted">No major rule-based bottlenecks detected.</p> : null}
      </article>
    </section>
  )
}
