import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { analyzePlan, type PlanAnalysis } from '../lib/api'
import { PlanVisualization } from '../components/PlanVisualization'

export function PlanViewer() {
  const [searchParams] = useSearchParams()
  const [sql, setSql] = useState("SELECT id, customer_id, amount FROM telemetry_demo_orders WHERE status = 'pending' ORDER BY created_at DESC LIMIT 50")
  const [analysis, setAnalysis] = useState<PlanAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleAnalyze = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await analyzePlan(sql)
      setAnalysis(res)
    } catch (err: any) {
      setError(err.message || 'Plan analysis failed. Only read-only SELECT / WITH queries are supported.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    handleAnalyze()
  }, [])

  return (
    <section>
      <div className="section-head" style={{ marginBottom: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
          <span className="badge badge-observed">OBSERVED: PostgreSQL EXPLAIN</span>
          <span className="badge badge-ai-analysis">AI ANALYSIS: AST & Node Parser</span>
        </div>
        <h1 style={{ fontSize: '2.2rem', margin: 0 }}>Execution Plan Viewer</h1>
        <p className="subtitle" style={{ fontSize: '0.95rem', color: '#64748b' }}>
          Interactive planner cost evaluation. Plans queries safely without ANALYZE execution side-effects.
        </p>
      </div>

      <article className="card section-card" style={{ marginBottom: '20px' }}>
        <label style={{ fontSize: '12px', fontWeight: 700, display: 'block', marginBottom: '8px' }}>
          SQL Statement (Read-only SELECT / WITH):
        </label>
        <textarea
          className="plan-input"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          rows={3}
          placeholder="Enter SELECT query to explain..."
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <button
            className="primary-button"
            onClick={handleAnalyze}
            disabled={loading || !sql.trim()}
          >
            {loading ? 'Evaluating EXPLAIN Plan...' : 'Explain & Visualize Plan'}
          </button>
          <small className="muted">Read-only constraint enforced: DDL/DML statements are rejected.</small>
        </div>
      </article>

      {error && <div className="alert">{error}</div>}

      {analysis && (
        <>
          <div className="grid metrics" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '14px', marginBottom: '20px' }}>
            <article className="card">
              <span className="badge badge-observed">OBSERVED</span>
              <h2 style={{ marginTop: '8px' }}>Total Cost</h2>
              <strong style={{ fontSize: '24px' }}>
                {analysis.features?.total_cost?.toFixed(2) ?? '—'}
              </strong>
              <p>Planner arbitrary cost units</p>
            </article>

            <article className="card">
              <span className="badge badge-observed">OBSERVED</span>
              <h2 style={{ marginTop: '8px' }}>Estimated Rows</h2>
              <strong style={{ fontSize: '24px' }}>
                {analysis.features?.total_rows?.toLocaleString() ?? '—'}
              </strong>
              <p>Cardinality estimation</p>
            </article>

            <article className="card">
              <span className="badge badge-ai-analysis">AI ANALYSIS</span>
              <h2 style={{ marginTop: '8px' }}>Seq Scan Fraction</h2>
              <strong style={{ fontSize: '24px', color: (analysis.features?.seq_scan_fraction ?? 0) > 0.4 ? '#b91c1c' : '#166534' }}>
                {((analysis.features?.seq_scan_fraction ?? 0) * 100).toFixed(1)}%
              </strong>
              <p>Unindexed table scan ratio</p>
            </article>

            <article className="card">
              <span className="badge badge-ai-analysis">AI ANALYSIS</span>
              <h2 style={{ marginTop: '8px' }}>Structural Hash</h2>
              <strong style={{ fontSize: '14px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                {analysis.structural_hash.slice(0, 16)}…
              </strong>
              <p>Invariant AST graph topology ID</p>
            </article>
          </div>

          <article className="card section-card">
            <div className="section-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <h2 style={{ margin: 0 }}>Visual Execution Plan Tree</h2>
                <span className="muted">Hierarchical representation of operator nodes and child pipelines</span>
              </div>
              <span className="badge badge-observed">OBSERVED</span>
            </div>

            <PlanVisualization analysis={analysis} />
          </article>
        </>
      )}
    </section>
  )
}
