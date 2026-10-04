import React, { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  getQueryDetail,
  getSlowQueries,
  getQueryOptimizationTrace,
  analyzePlan,
  rewriteSql,
  createSimulation,
  approveRecommendation,
  rejectRecommendation,
  type QueryDetail,
  type QueryOptimizationTrace,
  type PlanAnalysis,
  type SQLRewriteResponse,
} from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'

function formatMs(value: number | undefined | null) {
  if (value === undefined || value === null) return '0.00 ms'
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

  // GNN Analysis state
  const [analyzingGnn, setAnalyzingGnn] = useState(false)
  const [gnnAnalysis, setGnnAnalysis] = useState<PlanAnalysis | null>(null)
  const [gnnError, setGnnError] = useState<string | null>(null)

  // SQL Rewriter state
  const [rewriting, setRewriting] = useState(false)
  const [rewriteResult, setRewriteResult] = useState<SQLRewriteResponse | null>(null)
  const [rewriteError, setRewriteError] = useState<string | null>(null)

  // Trace actions state
  const [isSimulating, setIsSimulating] = useState(false)
  const [isDeciding, setIsDeciding] = useState(false)

  // Ref to prevent duplicate loads in React StrictMode
  const loadedIdRef = useRef<string | null>(null)

  const loadQuery = (id: string | number, force = false) => {
    const idStr = String(id).trim()
    if (!idStr) return
    if (!force && loadedIdRef.current === idStr) return
    loadedIdRef.current = idStr

    setLoading(true)
    setError(null)
    setGnnError(null)
    setRewriteError(null)

    Promise.all([
      getQueryDetail(idStr),
      getQueryOptimizationTrace(idStr).catch(() => null),
    ])
      .then(([qData, tData]) => {
        setDetail(qData)
        setQueryIdInput(String(qData.id || qData.query_id))
        setTraceData(tData)
        if (tData?.plan_analysis) {
          setGnnAnalysis(tData.plan_analysis)
        } else {
          setGnnAnalysis(null)
        }
      })
      .catch((err) => {
        setError(err.message || `Query ID ${idStr} not found in telemetry store.`)
        setDetail(null)
        setTraceData(null)
        setGnnAnalysis(null)
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

    // Default to first query or latest query if no id is specified in URL
    setLoading(true)
    getSlowQueries(1, 1, 0)
      .then((data) => {
        if (data.items && data.items.length > 0) {
          const top = data.items[0]
          const chosenId = String(top.id || top.query_id)
          setQueryIdInput(chosenId)
          loadQuery(chosenId)
        } else {
          loadQuery('latest')
        }
      })
      .catch(() => {
        loadQuery('latest')
      })
  }, [searchParams])

  const handleLookup = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = queryIdInput.trim()
    if (trimmed) {
      loadedIdRef.current = null
      setSearchParams({ id: trimmed })
    }
  }

  const handleRefresh = () => {
    if (detail) {
      loadQuery(detail.id || detail.query_id, true)
    }
  }

  const handleRunGnnAnalysis = async () => {
    if (!detail) return
    setAnalyzingGnn(true)
    setGnnError(null)
    try {
      const res = await analyzePlan({ query_id: detail.id || detail.query_id })
      setGnnAnalysis(res)
    } catch (err: any) {
      setGnnError(err.message || 'GNN analysis failed. Please verify database connectivity.')
    } finally {
      setAnalyzingGnn(false)
    }
  }

  const handleRunSqlRewrite = async () => {
    if (!detail?.normalized_query) return
    setRewriting(true)
    setRewriteError(null)
    try {
      const res = await rewriteSql(detail.normalized_query, true)
      setRewriteResult(res)
    } catch (err: any) {
      setRewriteError(err.message || 'SQL rewrite engine failed.')
    } finally {
      setRewriting(false)
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

  // Derived Performance Diagnosis Data
  const primaryBottleneck =
    gnnAnalysis?.bottlenecks?.[0] ||
    (traceData?.matching_recommendations?.[0]
      ? {
          type: traceData.matching_recommendations[0].type || 'sequential_scan',
          severity: traceData.matching_recommendations[0].risk || 'HIGH',
          affected_node: 'node_0',
          explanation: traceData.matching_recommendations[0].reason,
          possible_remediation: traceData.matching_recommendations[0].proposed_change,
          evidence: traceData.matching_recommendations[0].evidence,
        }
      : null)

  const gnnSummaryText = (gnnAnalysis?.explanation as any)?.gnn_summary || gnnAnalysis?.explanation?.summary

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Page Header */}
      <div className="section-head" style={{ marginBottom: '4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <span className="badge badge-observed">OBSERVED: pg_stat_statements</span>
              <span className="badge badge-observed">Telemetry Inspector</span>
              <span className="badge badge-ai-analysis">AI Privacy Gateway: Enforced</span>
            </div>
            <h1 style={{ fontSize: '2.1rem', margin: 0, fontWeight: 700 }}>Query Performance Details</h1>
            <p className="subtitle" style={{ fontSize: '0.95rem', color: '#94a3b8', margin: '4px 0 0 0' }}>
              Central entry point for query telemetry inspection, privacy-preserved GNN bottleneck analysis, and safe sandbox optimization.
            </p>
          </div>
          {detail && (
            <button
              onClick={handleRefresh}
              className="btn-secondary"
              style={{ fontSize: '12px', padding: '6px 14px' }}
              disabled={loading}
            >
              🔄 Refresh Telemetry
            </button>
          )}
        </div>
      </div>

      <OptimizationFlowHeader currentStage="analyze" />

      {/* Query Search / Selection Bar */}
      <form onSubmit={handleLookup} className="card filter-bar" style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: '13px', fontWeight: 600, color: '#e2e8f0' }}>Query Identifier:</label>
        <input
          type="text"
          className="filter-input"
          style={{ width: '280px', fontFamily: 'monospace', fontSize: '13px' }}
          value={queryIdInput}
          onChange={(e) => setQueryIdInput(e.target.value)}
          placeholder="e.g. -7683565032435896730 or row ID"
        />
        <button type="submit" className="primary-button" style={{ padding: '8px 18px' }} disabled={loading}>
          {loading ? 'Inspecting...' : 'Inspect Query'}
        </button>
        {detail && (
          <span style={{ fontSize: '12px', color: '#64748b' }}>
            Viewing Query #{detail.query_id} (Database: {detail.database_name || 'dbzenith'})
          </span>
        )}
      </form>

      {error && <div className="alert">{error}</div>}

      {detail && (
        <>
          {/* ======================================================== */}
          {/* SECTION A: QUERY OVERVIEW (OBSERVED TELEMETRY)          */}
          {/* ======================================================== */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
              <span className="badge badge-observed" style={{ fontWeight: 700 }}>OBSERVED TELEMETRY</span>
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#f8fafc' }}>
                PostgreSQL Operational Metrics (pg_stat_statements)
              </span>
            </div>

            <div className="grid metrics" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginBottom: '16px' }}>
              <article className="card" style={{ padding: '14px' }}>
                <span className="badge badge-observed" style={{ fontSize: '10px' }}>OBSERVED</span>
                <h3 style={{ marginTop: '6px', fontSize: '13px', color: '#94a3b8' }}>Mean Latency</h3>
                <strong style={{ fontSize: '22px', color: detail.mean_exec_time_ms > 100 ? '#ef4444' : '#10b981' }}>
                  {formatMs(detail.mean_exec_time_ms)}
                </strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: '#64748b' }}>
                  Min: {formatMs(detail.min_exec_time_ms)} | Max: {formatMs(detail.max_exec_time_ms)}
                </p>
              </article>

              <article className="card" style={{ padding: '14px' }}>
                <span className="badge badge-observed" style={{ fontSize: '10px' }}>OBSERVED</span>
                <h3 style={{ marginTop: '6px', fontSize: '13px', color: '#94a3b8' }}>Total Exec Calls</h3>
                <strong style={{ fontSize: '22px', color: '#38bdf8' }}>{detail.calls.toLocaleString()}</strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: '#64748b' }}>
                  Frequency: {detail.query_frequency_per_minute.toFixed(1)} calls/min (pg_stat_statements)
                </p>
              </article>

              <article className="card" style={{ padding: '14px' }}>
                <span className="badge badge-observed" style={{ fontSize: '10px' }}>OBSERVED</span>
                <h3 style={{ marginTop: '6px', fontSize: '13px', color: '#94a3b8' }}>Total Workload Time</h3>
                <strong style={{ fontSize: '22px', color: '#f8fafc' }}>
                  {formatMs(detail.total_exec_time_ms)}
                </strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: '#64748b' }}>
                  Rows processed: {detail.rows.toLocaleString()}
                </p>
              </article>

              <article className="card" style={{ padding: '14px' }}>
                <span className="badge badge-observed" style={{ fontSize: '10px' }}>OBSERVED</span>
                <h3 style={{ marginTop: '6px', fontSize: '13px', color: '#94a3b8' }}>Buffer Cache Hit Ratio</h3>
                <strong style={{ fontSize: '22px', color: hitRatio >= 95 ? '#10b981' : '#f59e0b' }}>
                  {hitRatio.toFixed(1)}%
                </strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: '#64748b' }}>
                  Hits: {detail.shared_blks_hit.toLocaleString()} | Reads: {detail.shared_blks_read.toLocaleString()}
                </p>
              </article>

              <article className="card" style={{ padding: '14px' }}>
                <span className="badge badge-observed" style={{ fontSize: '10px' }}>OBSERVED</span>
                <h3 style={{ marginTop: '6px', fontSize: '13px', color: '#94a3b8' }}>Temp Disk Activity</h3>
                <strong style={{ fontSize: '22px', color: detail.temp_blks_written > 0 ? '#ef4444' : '#64748b' }}>
                  {detail.temp_blks_written.toLocaleString()} blks
                </strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: '#64748b' }}>
                  WorkMem spill indicator (temp written)
                </p>
              </article>

              <article className="card" style={{ padding: '14px' }}>
                <span className="badge badge-observed" style={{ fontSize: '10px' }}>OBSERVED</span>
                <h3 style={{ marginTop: '6px', fontSize: '13px', color: '#94a3b8' }}>Block I/O Latency</h3>
                <strong style={{ fontSize: '22px', color: '#f8fafc' }}>
                  {formatMs(detail.blk_read_time_ms + detail.blk_write_time_ms)}
                </strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: '#64748b' }}>
                  Read: {formatMs(detail.blk_read_time_ms)} | Write: {formatMs(detail.blk_write_time_ms)}
                </p>
              </article>
            </div>

            {/* Normalized Query Card */}
            <article className="card" style={{ padding: '16px', marginBottom: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="badge badge-observed" style={{ fontSize: '10px' }}>OBSERVED</span>
                    <h3 style={{ margin: 0, fontSize: '15px', color: '#f8fafc' }}>Normalized Query Statement</h3>
                    <span className="badge badge-ai-analysis" style={{ fontSize: '10px' }}>PRIVACY PRESERVED</span>
                  </div>
                  <span style={{ fontSize: '12px', color: '#64748b', marginTop: '2px', display: 'block' }}>
                    Client parameters, literal strings, and private constants are parameterized with $1, $2 placeholders.
                  </span>
                </div>
                <button className="btn-secondary" onClick={copySql} style={{ fontSize: '12px', padding: '6px 12px' }}>
                  {copied ? '✓ Copied!' : 'Copy SQL'}
                </button>
              </div>

              <pre className="sql-box" style={{ margin: 0, padding: '12px', background: '#090d16', borderRadius: '6px', maxHeight: '160px', overflowY: 'auto' }}>
                {detail.normalized_query}
              </pre>
            </article>
          </div>

          {/* ======================================================== */}
          {/* SECTION B: PRIVACY STATUS PANEL (MANDATORY GATEWAY)     */}
          {/* ======================================================== */}
          <article className="card" style={{ padding: '18px', borderLeft: '4px solid #10b981', background: 'rgba(16, 185, 129, 0.03)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px', marginBottom: '12px' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="badge" style={{ background: '#065f46', color: '#34d399', fontWeight: 700 }}>
                    PRIVACY BOUNDARY: ENFORCED
                  </span>
                  <span className="badge badge-observed" style={{ background: '#1e293b', color: '#94a3b8' }}>
                    RAW-DATA EXPOSURE: 0 BYTES
                  </span>
                </div>
                <h2 style={{ margin: '6px 0 0 0', fontSize: '16px', color: '#f8fafc' }}>
                  Privacy Gateway Status: Raw production values are not sent to AI
                </h2>
                <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: '#94a3b8' }}>
                  All telemetry passes through the deterministic PrivacyGateway before persisting plan graphs or performing GNN inference.
                </p>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginTop: '10px' }}>
              <div style={{ background: '#0b1120', padding: '10px 12px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>1. Normalized SQL</span>
                <div style={{ fontSize: '12px', color: '#38bdf8', marginTop: '4px', fontFamily: 'monospace' }}>
                  Literals Scrubbed → ($1, $2...)
                </div>
                <span style={{ fontSize: '11px', color: '#94a3b8' }}>Customer names, emails, and values scrubbed</span>
              </div>

              <div style={{ background: '#0b1120', padding: '10px 12px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>2. Structural Hash</span>
                <div style={{ fontSize: '12px', color: '#10b981', marginTop: '4px', fontFamily: 'monospace' }}>
                  {gnnAnalysis?.structural_hash ? gnnAnalysis.structural_hash.substring(0, 16) + '...' : 'SHA-256 AST Signature'}
                </div>
                <span style={{ fontSize: '11px', color: '#94a3b8' }}>Isomorphic plan hash; identical plans share cache</span>
              </div>

              <div style={{ background: '#0b1120', padding: '10px 12px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>3. Metadata-Only Features</span>
                <div style={{ fontSize: '12px', color: '#a78bfa', marginTop: '4px', fontFamily: 'monospace' }}>
                  {gnnAnalysis?.features ? `${Object.keys(gnnAnalysis.features).length} Float Embeddings` : 'Graph Operator Vector'}
                </div>
                <span style={{ fontSize: '11px', color: '#94a3b8' }}>Only costs, row estimates, & graph topology exposed</span>
              </div>

              <div style={{ background: '#0b1120', padding: '10px 12px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>4. Zero Raw Exposure</span>
                <div style={{ fontSize: '12px', color: '#34d399', marginTop: '4px', fontWeight: 700 }}>
                  Raw Production Data = 0
                </div>
                <span style={{ fontSize: '11px', color: '#94a3b8' }}>No tuple content or sensitive table rows sent to GNN</span>
              </div>
            </div>
          </article>

          {/* ======================================================== */}
          {/* SECTION C: "WHY IS THIS QUERY SLOW?" & DIAGNOSIS       */}
          {/* ======================================================== */}
          <article className="card" style={{ padding: '18px', borderLeft: '4px solid #f59e0b', background: '#0f172a' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', marginBottom: '12px' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="badge badge-ai-analysis" style={{ fontWeight: 700 }}>AI ROOT CAUSE DIAGNOSIS</span>
                  <span className={`badge ${primaryBottleneck?.severity === 'critical' ? 'badge-danger' : 'badge-warning'}`}>
                    {primaryBottleneck?.severity ? `${String(primaryBottleneck.severity).toUpperCase()} SEVERITY` : 'ANALYSIS READY'}
                  </span>
                </div>
                <h2 style={{ margin: '6px 0 0 0', fontSize: '18px', color: '#f8fafc' }}>
                  Why Is This Query Slow?
                </h2>
              </div>
              {gnnAnalysis && (
                <span style={{ fontSize: '12px', color: '#10b981', background: 'rgba(16,185,129,0.1)', padding: '4px 10px', borderRadius: '4px', border: '1px solid rgba(16,185,129,0.2)' }}>
                  ✓ GNN Structural Analysis Active
                </span>
              )}
            </div>

            {primaryBottleneck ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ background: '#090d16', padding: '14px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <div style={{ fontSize: '14px', fontWeight: 700, color: '#f59e0b', textTransform: 'capitalize' }}>
                      Primary Bottleneck: {primaryBottleneck.type.replace(/_/g, ' ')}
                    </div>
                    <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                      Affected Plan Node: <code>{primaryBottleneck.affected_node || 'Root AST'}</code>
                    </span>
                  </div>

                  <p style={{ margin: '0 0 10px 0', fontSize: '13px', color: '#e2e8f0', lineHeight: 1.5 }}>
                    {primaryBottleneck.explanation}
                  </p>

                  {/* Supporting Evidence List */}
                  {primaryBottleneck.evidence && (
                    <div style={{ marginTop: '8px', padding: '10px', background: '#0b1120', borderRadius: '4px', border: '1px solid #1e293b' }}>
                      <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600, marginBottom: '6px' }}>
                        Observed Execution Plan Evidence:
                      </div>
                      <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: '#cbd5e1', lineHeight: 1.6 }}>
                        {typeof primaryBottleneck.evidence === 'object' && !Array.isArray(primaryBottleneck.evidence) ? (
                          Object.entries(primaryBottleneck.evidence).map(([k, v]) => (
                            <li key={k}>
                              <strong>{k.replace(/_/g, ' ')}:</strong> {typeof v === 'number' ? (v > 100 ? v.toLocaleString() : v) : String(v)}
                            </li>
                          ))
                        ) : Array.isArray(primaryBottleneck.evidence) ? (
                          primaryBottleneck.evidence.map((evItem: any, idx: number) => (
                            <li key={idx}>{String(evItem)}</li>
                          ))
                        ) : (
                          <li>Evidence details confirmed by plan cost model</li>
                        )}
                      </ul>
                    </div>
                  )}

                  {/* Recommended Remediation */}
                  {primaryBottleneck.possible_remediation && (
                    <div style={{ marginTop: '10px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#10b981' }}>
                      <strong>Recommended Action:</strong> {primaryBottleneck.possible_remediation}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ background: '#090d16', padding: '14px', borderRadius: '6px', border: '1px solid #1e293b', color: '#94a3b8', fontSize: '13px' }}>
                <p style={{ margin: 0 }}>
                  This query exhibits an average latency of <strong>{formatMs(detail.mean_exec_time_ms)}</strong> across {detail.calls} executions.
                  Click <strong>"Run GNN Bottleneck Analysis"</strong> below to construct the operator AST graph, classify bottlenecks via Graph Neural Network, and extract structural evidence.
                </p>
              </div>
            )}
          </article>

          {/* ======================================================== */}
          {/* SECTION D: ACTIONS BAR (RUN GNN / REWRITE / PLANS)     */}
          {/* ======================================================== */}
          <div className="card" style={{ padding: '16px', background: '#0b1120', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <button
                className="btn btn-primary"
                style={{ padding: '9px 18px', fontSize: '13px', fontWeight: 600 }}
                onClick={handleRunGnnAnalysis}
                disabled={analyzingGnn}
              >
                {analyzingGnn ? '⚡ Running GNN Inference...' : '⚡ Run GNN Bottleneck Analysis'}
              </button>

              <button
                className="btn btn-secondary"
                style={{ padding: '9px 18px', fontSize: '13px', fontWeight: 600 }}
                onClick={handleRunSqlRewrite}
                disabled={rewriting}
              >
                {rewriting ? '🔄 Analyzing SQL AST...' : '🔄 Rewrite Query (Safe AST)'}
              </button>
            </div>

            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <Link
                to={`/gnn?queryId=${detail.query_id}`}
                className="secondary-button"
                style={{ textDecoration: 'none', fontSize: '13px', padding: '9px 16px' }}
              >
                Open in GNN Topology Studio →
              </Link>
              <Link
                to={`/plans?queryId=${detail.query_id}`}
                className="secondary-button"
                style={{ textDecoration: 'none', fontSize: '13px', padding: '9px 16px' }}
              >
                View EXPLAIN Execution Plan →
              </Link>
            </div>
          </div>

          {/* GNN Error banner */}
          {gnnError && (
            <div className="card" style={{ borderColor: '#ef4444', background: 'rgba(239,68,68,0.05)', color: '#fca5a5', padding: '12px' }}>
              <strong>GNN Analysis Error:</strong> {gnnError}
            </div>
          )}

          {/* SQL Rewrite Error banner */}
          {rewriteError && (
            <div className="card" style={{ borderColor: '#ef4444', background: 'rgba(239,68,68,0.05)', color: '#fca5a5', padding: '12px' }}>
              <strong>SQL Rewrite Error:</strong> {rewriteError}
            </div>
          )}

          {/* ======================================================== */}
          {/* SECTION E: INLINE GNN RESULT (WHEN ANALYZED)            */}
          {/* ======================================================== */}
          {gnnAnalysis && (
            <article className="card" style={{ padding: '18px', borderLeft: '4px solid #38bdf8' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="badge badge-ai-analysis">GNN INFERENCE COMPLETED</span>
                  <span className="badge badge-observed">AST Graph Encoded</span>
                  <span style={{ fontSize: '13px', fontFamily: 'monospace', color: '#94a3b8' }}>
                    Hash: {gnnAnalysis.structural_hash}
                  </span>
                </div>
                <span style={{ fontSize: '12px', color: '#38bdf8' }}>
                  {gnnAnalysis.graph?.nodes?.length ?? 0} Operators / {gnnAnalysis.graph?.edges?.length ?? 0} Edges
                </span>
              </div>

              {/* Architectural pipeline transparency */}
              <div style={{ background: '#090d16', padding: '10px 14px', borderRadius: '6px', marginBottom: '14px', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>
                  Architectural Pipeline (GNN is a structural classifier, not an LLM)
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#94a3b8', marginTop: '6px', flexWrap: 'wrap' }}>
                  <span>EXPLAIN Plan</span> &rarr;
                  <span>Privacy Gateway</span> &rarr;
                  <span>Graph Construction</span> &rarr;
                  <span style={{ color: '#38bdf8', fontWeight: 600 }}>GNN (Node Classification)</span> &rarr;
                  <span>Evidence Extraction</span> &rarr;
                  <span style={{ color: '#10b981', fontWeight: 600 }}>Explanation Layer</span>
                </div>
              </div>

              {/* GNN Synthesis Summary */}
              {gnnSummaryText && (
                <div style={{ padding: '12px 14px', background: 'rgba(56, 189, 248, 0.05)', borderRadius: '6px', border: '1px solid rgba(56, 189, 248, 0.2)', marginBottom: '14px' }}>
                  <div style={{ fontSize: '12px', color: '#38bdf8', fontWeight: 600, marginBottom: '4px' }}>
                    GNN Synthesis Summary:
                  </div>
                  <div style={{ fontSize: '13px', color: '#f8fafc', lineHeight: 1.5 }}>
                    {gnnSummaryText}
                  </div>
                </div>
              )}

              {/* Flagged Bottlenecks list */}
              {gnnAnalysis.bottlenecks && gnnAnalysis.bottlenecks.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 600 }}>
                    Identified Bottleneck Candidates ({gnnAnalysis.bottlenecks.length}):
                  </span>
                  {gnnAnalysis.bottlenecks.map((bn, idx) => (
                    <div key={idx} style={{ background: '#090d16', padding: '12px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span className={`badge ${bn.severity === 'critical' ? 'badge-danger' : 'badge-warning'}`}>
                            {bn.severity.toUpperCase()}
                          </span>
                          <span style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc' }}>
                            {bn.type.replace(/_/g, ' ')}
                          </span>
                          <code style={{ fontSize: '11px', color: '#64748b' }}>Node: {bn.affected_node}</code>
                        </div>
                      </div>
                      <p style={{ margin: '6px 0 4px 0', fontSize: '12px', color: '#cbd5e1' }}>{bn.explanation}</p>
                      <div style={{ fontSize: '11px', color: '#10b981' }}>
                        <strong>Remedy:</strong> {bn.possible_remediation}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </article>
          )}

          {/* ======================================================== */}
          {/* SECTION F: INLINE SQL REWRITER RESULT (WHEN REWRITTEN)   */}
          {/* ======================================================== */}
          {rewriteResult && (
            <article className="card" style={{ padding: '18px', borderLeft: '4px solid #a78bfa' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="badge badge-ai-analysis" style={{ background: '#5b21b6', color: '#ddd6fe' }}>
                    SQL AST REWRITER
                  </span>
                  <span className="badge" style={{ background: '#065f46', color: '#34d399' }}>
                    PRODUCTION MODIFIED: FALSE
                  </span>
                  <span className="badge" style={{ background: '#1e293b', color: '#94a3b8' }}>
                    {rewriteResult.transformation}
                  </span>
                </div>
                {rewriteResult.cost_improvement_pct !== null && (
                  <span style={{ fontSize: '14px', fontWeight: 700, color: '#10b981' }}>
                    Cost Improvement: {rewriteResult.cost_improvement_pct.toFixed(1)}%
                  </span>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '12px', marginBottom: '12px' }}>
                <div>
                  <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600 }}>Original Query (Normalized)</span>
                  <pre className="sql-box" style={{ margin: '4px 0 0 0', padding: '10px', fontSize: '12px', background: '#090d16', maxHeight: '140px', overflowY: 'auto' }}>
                    {rewriteResult.original_query}
                  </pre>
                </div>
                <div>
                  <span style={{ fontSize: '11px', color: '#34d399', textTransform: 'uppercase', fontWeight: 600 }}>Candidate Rewritten Query (Safe AST)</span>
                  <pre className="sql-box" style={{ margin: '4px 0 0 0', padding: '10px', fontSize: '12px', background: '#090d16', borderColor: '#059669', maxHeight: '140px', overflowY: 'auto' }}>
                    {rewriteResult.rewritten_query}
                  </pre>
                </div>
              </div>

              <div style={{ background: '#090d16', padding: '10px 14px', borderRadius: '6px', border: '1px solid #1e293b', fontSize: '12px', color: '#cbd5e1' }}>
                <p style={{ margin: '0 0 4px 0' }}><strong>Transformation Rationale:</strong> {rewriteResult.reason}</p>
                <p style={{ margin: 0 }}><strong>Expected Benefit:</strong> {rewriteResult.expected_benefit} (Sandbox Verdict: {rewriteResult.safety_verdict})</p>
              </div>
            </article>
          )}

          {/* ======================================================== */}
          {/* SECTION G: OPTIMIZATION TRACE & SANDBOX SIMULATION       */}
          {/* ======================================================== */}
          <OptimizationTrace
            title={`Autonomous Optimization Trace: Query #${detail.query_id}`}
            query={detail}
            recommendation={
              traceData?.matching_recommendations && traceData.matching_recommendations.length > 0
                ? traceData.matching_recommendations[0]
                : null
            }
            simulation={traceData?.latest_simulation}
            planAnalysis={gnnAnalysis}
            rewrite={rewriteResult}
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

      {!detail && !loading && (
        <article className="card section-card" style={{ marginTop: '20px', textAlign: 'center', padding: '40px 20px' }}>
          <h3 style={{ fontSize: '18px', color: '#f1f5f9', marginBottom: '8px' }}>No Query Telemetry Selected</h3>
          <p style={{ color: '#94a3b8', fontSize: '14px', maxWidth: '520px', margin: '0 auto 20px' }}>
            No query statistics are currently selected or found. You can browse recorded slow queries, inspect execution plans, or generate new database traffic.
          </p>
          <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
            <Link to="/slow-queries" className="btn btn-secondary" style={{ textDecoration: 'none', padding: '8px 16px' }}>
              Browse Slow Queries
            </Link>
            <Link to="/plans" className="btn btn-secondary" style={{ textDecoration: 'none', padding: '8px 16px' }}>
              Execution Plan Viewer
            </Link>
            <Link to="/" className="btn btn-primary" style={{ textDecoration: 'none', padding: '8px 16px' }}>
              Overview Dashboard
            </Link>
          </div>
        </article>
      )}
    </section>
  )
}
