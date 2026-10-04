import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  getQueryDetail,
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

export function QueryDetails() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [queryIdInput, setQueryIdInput] = useState('')
  const [detail, setDetail] = useState<QueryDetail | null>(null)
  const [traceData, setTraceData] = useState<QueryOptimizationTrace | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [isSimulating, setIsSimulating] = useState(false)
  const [isDeciding, setIsDeciding] = useState(false)

  const loadQuery = (id: string | number) => {
    const idStr = String(id).trim()
    if (!idStr) return
    setLoading(true)
    setError(null)
    Promise.all([
      getQueryDetail(idStr),
      getQueryOptimizationTrace(idStr).catch(() => null),
    ])
      .then(([qData, tData]) => {
        setDetail(qData)
        setTraceData(tData)
      })
      .catch((err) => {
        setError(err.message || `Query ID ${idStr} not found in telemetry store.`)
        setDetail(null)
        setTraceData(null)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    const idParam = searchParams.get('id')
    if (idParam && idParam.trim()) {
      const cleanId = idParam.trim()
      setQueryIdInput(cleanId)
      loadQuery(cleanId)
      return
    }
    setLoading(true)
    getSlowQueries(1, 1)
      .then((data) => {
        if (data.items && data.items.length > 0) {
          const top = data.items[0]
          const chosenId = String(top.query_id || top.id)
          setQueryIdInput(chosenId)
          loadQuery(chosenId)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [searchParams])

  const handleLookup = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = queryIdInput.trim()
    if (trimmed) {
      setSearchParams({ id: trimmed })
    }
  }

  const handleSimulate = async (recId: number) => {
    setIsSimulating(true)
    try {
      await createSimulation(recId, 3)
      if (detail) {
        const refreshed = await getQueryOptimizationTrace(detail.query_id)
        setTraceData(refreshed)
      }
    } catch (err: any) {
      alert(`Simulation failed: ${err.message}`)
    } finally {
      setIsSimulating(false)
    }
  }

  const handleApprove = async (recId: number) => {
    setIsDeciding(true)
    try {
      await approveRecommendation(recId, 'Approved via Query Details')
      if (detail) {
        const refreshed = await getQueryOptimizationTrace(detail.query_id)
        setTraceData(refreshed)
      }
    } catch (err: any) {
      alert(`Approval failed: ${err.message}`)
    } finally {
      setIsDeciding(false)
    }
  }

  const handleReject = async (recId: number) => {
    setIsDeciding(true)
    try {
      await rejectRecommendation(recId, 'Rejected via Query Details')
      if (detail) {
        const refreshed = await getQueryOptimizationTrace(detail.query_id)
        setTraceData(refreshed)
      }
    } catch (err: any) {
      alert(`Rejection failed: ${err.message}`)
    } finally {
      setIsDeciding(false)
    }
  }

  const copySql = () => {
    if (detail?.normalized_query) {
      navigator.clipboard.writeText(detail.normalized_query)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const hitRatio = detail
    ? detail.shared_blks_hit + detail.shared_blks_read > 0
      ? (detail.shared_blks_hit / (detail.shared_blks_hit + detail.shared_blks_read)) * 100
      : 100
    : 0

  return (
    <section>
      <div className="section-head" style={{ marginBottom: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
          <span className="badge badge-observed">OBSERVED: pg_stat_statements</span>
          <span className="badge badge-observed">Telemetry Inspector</span>
          <span className="badge badge-ai-analysis">End-to-End Optimization Flow</span>
        </div>
        <h1 style={{ fontSize: '2.2rem', margin: 0 }}>Query Performance Details</h1>
        <p className="subtitle" style={{ fontSize: '0.95rem', color: '#64748b' }}>
          Detailed telemetry, memory buffer hit ratios, and autonomous before → analysis → optimization → after trace.
        </p>
      </div>

      <OptimizationFlowHeader currentStage="analyze" />

      <form onSubmit={handleLookup} className="card filter-bar" style={{ display: 'flex', gap: '10px', alignItems: 'center', marginBottom: '16px' }}>
        <label style={{ fontSize: '12px', fontWeight: 600 }}>Query ID:</label>
        <input
          type="text"
          className="filter-input"
          style={{ width: '240px', fontFamily: 'monospace' }}
          value={queryIdInput}
          onChange={(e) => setQueryIdInput(e.target.value)}
          placeholder="e.g. -4180483195914191103 or row ID"
        />
        <button type="submit" className="primary-button" style={{ padding: '8px 16px' }} disabled={loading}>
          {loading ? 'Inspecting...' : 'Inspect Query'}
        </button>
      </form>

      {error && <div className="alert">{error}</div>}

      {detail && (
        <>
          <div className="grid metrics" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '14px', marginBottom: '20px' }}>
            <article className="card">
              <span className="badge badge-observed">OBSERVED</span>
              <h2 style={{ marginTop: '8px' }}>Mean Latency</h2>
              <strong style={{ fontSize: '24px', color: detail.mean_exec_time_ms > 100 ? '#b91c1c' : '#166534' }}>
                {formatMs(detail.mean_exec_time_ms)}
              </strong>
              <p>Min: {formatMs(detail.min_exec_time_ms)} | Max: {formatMs(detail.max_exec_time_ms)}</p>
            </article>

            <article className="card">
              <span className="badge badge-observed">OBSERVED</span>
              <h2 style={{ marginTop: '8px' }}>Execution Calls</h2>
              <strong style={{ fontSize: '24px' }}>{detail.calls.toLocaleString()}</strong>
              <p>Frequency: {detail.query_frequency_per_minute.toFixed(1)} calls/min</p>
            </article>

            <article className="card">
              <span className="badge badge-observed">OBSERVED</span>
              <h2 style={{ marginTop: '8px' }}>Buffer Cache Hit</h2>
              <strong style={{ fontSize: '24px', color: hitRatio >= 95 ? '#166534' : '#b45309' }}>
                {hitRatio.toFixed(1)}%
              </strong>
              <p>Hits: {detail.shared_blks_hit.toLocaleString()} | Reads: {detail.shared_blks_read.toLocaleString()}</p>
            </article>

            <article className="card">
              <span className="badge badge-observed">OBSERVED</span>
              <h2 style={{ marginTop: '8px' }}>Temp Disk Activity</h2>
              <strong style={{ fontSize: '24px', color: detail.temp_blks_written > 0 ? '#b91c1c' : '#475467' }}>
                {detail.temp_blks_written.toLocaleString()} blks
              </strong>
              <p>WorkMem overflow spill indicator</p>
            </article>
          </div>

          <article className="card section-card" style={{ marginBottom: '20px' }}>
            <div className="section-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <div>
                <h2 style={{ margin: 0 }}>Normalized Query Statement (Privacy Preserved)</h2>
                <span className="muted">Parameterized query template; client literals and secrets are scrubbed</span>
              </div>
              <button className="btn-secondary" onClick={copySql} style={{ fontSize: '12px', padding: '6px 12px' }}>
                {copied ? '✓ Copied!' : 'Copy SQL'}
              </button>
            </div>

            <pre className="sql-box">{detail.normalized_query}</pre>

            <div style={{ display: 'flex', gap: '10px', marginTop: '16px', flexWrap: 'wrap' }}>
              <Link to={`/plans?queryId=${detail.query_id}`} className="primary-button" style={{ textDecoration: 'none', fontSize: '13px', padding: '8px 14px' }}>
                View EXPLAIN Execution Plan →
              </Link>
              <Link to={`/gnn?queryId=${detail.query_id}`} className="secondary-button" style={{ textDecoration: 'none', fontSize: '13px', padding: '8px 14px' }}>
                Run GNN Bottleneck Analysis →
              </Link>
              <Link to={`/recommendations`} className="secondary-button" style={{ textDecoration: 'none', fontSize: '13px', padding: '8px 14px' }}>
                View All Recommendations →
              </Link>
            </div>
          </article>

          {/* Full Reusable Optimization Trace for this query */}
          <OptimizationTrace
            title={`Autonomous Optimization Trace: Query #${detail.query_id}`}
            query={detail}
            recommendation={
              traceData?.matching_recommendations && traceData.matching_recommendations.length > 0
                ? traceData.matching_recommendations[0]
                : null
            }
            simulation={traceData?.latest_simulation}
            auditInfo={
              traceData?.audit_events && traceData.audit_events.length > 0
                ? {
                    action: traceData.audit_events[0].action,
                    status: traceData.audit_events[0].new_status,
                    reason: traceData.audit_events[0].reason,
                    timestamp: traceData.audit_events[0].created_at ?? undefined,
                  }
                : null
            }
            onSimulate={handleSimulate}
            onApprove={handleApprove}
            onReject={handleReject}
            isSimulating={isSimulating}
            isDeciding={isDeciding}
            initialExpanded={true}
          />
        </>
      )}
    </section>
  )
}
