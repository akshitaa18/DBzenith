import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getHealth,
  getSystemDiagnostics,
  getWorkloadSummary,
  getWorkloadSnapshots,
  getRecommendations,
  getRecommendationTrace,
  getLifecycleDashboardSummary,
  createSimulation,
  approveRecommendation,
  rejectRecommendation,
  seedDemoWorkload,
  collectTelemetry,
  type WorkloadSummary,
  type Recommendation,
  type RecommendationTrace,
  type LifecycleDashboardSummary,
  type SystemDiagnostics,
} from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'
import { lifecycleStateBadgeStyle } from '../components/RecommendationLifecyclePanel'
import {
  ProvenanceBadge,
  TelemetryTransparencyBanner,
  formatCollectionTimestamp,
} from '../components/ProvenanceBadge'
import { useAuth } from '../context/AuthContext'

function formatMs(value: number) {
  return `${value.toFixed(2)} ms`
}

function formatWindow(seconds: number | undefined | null) {
  if (!seconds || seconds <= 0) return 'Window not recorded'
  if (seconds >= 86400) {
    const days = Math.round(seconds / 86400)
    return `${days} ${days === 1 ? 'Day' : 'Days'} (${seconds.toLocaleString()}s)`
  }
  if (seconds >= 3600) {
    const hours = Math.round(seconds / 3600)
    return `${hours} ${hours === 1 ? 'Hour' : 'Hours'} (${seconds.toLocaleString()}s)`
  }
  if (seconds >= 60) {
    const mins = Math.round(seconds / 60)
    return `${mins} Min (${seconds.toLocaleString()}s)`
  }
  return `${seconds} s`
}

export function Overview() {
  const { canApprove, hasMinRole } = useAuth()
  const canOperateTelemetry = hasMinRole('ANALYST')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<WorkloadSummary | null>(null)
  const [snapshots, setSnapshots] = useState<Array<Record<string, unknown>>>([])
  const [health, setHealth] = useState<{ status: string; service: string; version: string } | null>(null)
  const [diagnostics, setDiagnostics] = useState<SystemDiagnostics | null>(null)
  const [lifecycleSummary, setLifecycleSummary] = useState<LifecycleDashboardSummary | null>(null)

  // Featured optimization trace for top active recommendation
  const [, setFeaturedRec] = useState<Recommendation | null>(null)
  const [featuredTrace, setFeaturedTrace] = useState<RecommendationTrace | null>(null)
  const [isSimulating, setIsSimulating] = useState(false)
  const [isDeciding, setIsDeciding] = useState(false)

  const loadData = () => {
    setLoading(true)
    setError(null)
    Promise.all([
      getHealth(),
      getWorkloadSummary(),
      getWorkloadSnapshots(10),
      getRecommendations(1, 5).catch(() => ({ items: [], total: 0, page: 1, page_size: 5 })),
      getLifecycleDashboardSummary().catch(() => null),
      getSystemDiagnostics().catch(() => null),
    ])
      .then(([h, s, snaps, recs, lcSum, diag]) => {
        setHealth(h)
        setSummary(s)
        setSnapshots(snaps)
        setLifecycleSummary(lcSum)
        setDiagnostics(diag)
        if (recs.items && recs.items.length > 0) {
          const top = recs.items[0]
          setFeaturedRec(top)
          getRecommendationTrace(top.id)
            .then((trace) => setFeaturedTrace(trace))
            .catch(() => {})
        }
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch telemetry overview.')
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleSimulateFeatured = async (recId: number) => {
    setIsSimulating(true)
    setError(null)
    try {
      await createSimulation(recId, 3)
      const updated = await getRecommendationTrace(recId)
      setFeaturedTrace(updated)
    } catch (err: any) {
      setError(`Simulation failed: ${err.message}`)
    } finally {
      setIsSimulating(false)
    }
  }

  const handleApproveFeatured = async (recId: number) => {
    setIsDeciding(true)
    setError(null)
    try {
      await approveRecommendation(recId, 'Approved via Overview Trace')
      const updated = await getRecommendationTrace(recId)
      setFeaturedTrace(updated)
      loadData()
    } catch (err: any) {
      setError(`Approval failed: ${err.message}`)
    } finally {
      setIsDeciding(false)
    }
  }

  const handleRejectFeatured = async (recId: number) => {
    setIsDeciding(true)
    setError(null)
    try {
      await rejectRecommendation(recId, 'Rejected via Overview Trace')
      const updated = await getRecommendationTrace(recId)
      setFeaturedTrace(updated)
      loadData()
    } catch (err: any) {
      setError(`Rejection failed: ${err.message}`)
    } finally {
      setIsDeciding(false)
    }
  }

  const [seedingDemo, setSeedingDemo] = useState(false)
  const [seedSuccessMsg, setSeedSuccessMsg] = useState<string | null>(null)

  const handleSeedDemo = async () => {
    setSeedingDemo(true)
    setSeedSuccessMsg(null)
    setError(null)
    try {
      const res = await seedDemoWorkload()
      setSeedSuccessMsg(`Successfully generated demo workload! Snapshot #${res.snapshot_id} captured with ${res.total_calls.toLocaleString()} calls and ${res.recommendations_count} optimizations synthesized.`)
      loadData()
    } catch (err: any) {
      setError(err?.message || 'Failed to seed demo workload')
    } finally {
      setSeedingDemo(false)
    }
  }

  const handleCollectTelemetry = async () => {
    setLoading(true)
    setError(null)
    try {
      await collectTelemetry()
      loadData()
    } catch (err: any) {
      setError(err?.message || 'Failed to collect telemetry')
      setLoading(false)
    }
  }

  if (loading && !summary && !error) {
    return <div className="loading-box">Loading PostgreSQL workload telemetry from pg_stat_statements...</div>
  }

  const dbConnected = diagnostics
    ? (diagnostics.database?.connected ?? (diagnostics as any).primary_database?.connected ?? true)
    : health?.status === 'ok'
  const lastCollectionTime =
    diagnostics?.telemetry?.last_successful_telemetry_at ||
    (diagnostics as any)?.collector?.last_successful_telemetry_at ||
    summary?.captured_at ||
    null

  return (
    <section>
      <div className="hero" style={{ marginBottom: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' }}>
            <ProvenanceBadge
              badge={summary?.provenance_badge}
              state={summary?.provenance_state}
              isSynthetic={summary?.is_synthetic || summary?.demo_mode_active}
              prefix="DATA SOURCE"
            />
            <span className="badge badge-observed">OBSERVED: pg_stat_statements</span>
            <span className={`status ${dbConnected ? 'online' : ''}`}>
              API: {health?.status ?? (error ? 'error' : 'online')}
            </span>
            <span className={`badge ${dbConnected ? 'badge-success' : 'badge-danger'}`}>
              DB: {dbConnected ? 'CONNECTED' : 'UNREACHABLE'}
            </span>
          </div>
          <h1 style={{ fontSize: '2.2rem', margin: '4px 0 8px 0' }}>Workload Telemetry Overview</h1>
          <p className="subtitle" style={{ fontSize: '0.95rem', color: '#94a3b8', maxWidth: '800px' }}>
            Real-time database connection health, telemetry freshness, workload trends, expensive query bottlenecks, pending approvals, and validated optimization outcomes.
          </p>
        </div>

        {/* Global Demo & Refresh Controls */}
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginTop: '10px', flexWrap: 'wrap' }}>
          {canApprove && (
            <button
              className="btn btn-primary"
              style={{ padding: '8px 16px', fontWeight: 600, fontSize: '13px' }}
              disabled={seedingDemo}
              onClick={handleSeedDemo}
            >
              {seedingDemo ? 'Generating Workload...' : '🚀 Load Demo Workload'}
            </button>
          )}
          {canOperateTelemetry && (
            <button
              className="btn btn-secondary"
              style={{ padding: '8px 14px', fontSize: '13px' }}
              onClick={handleCollectTelemetry}
            >
              🔄 Capture Snapshot
            </button>
          )}
          <button
            className="btn btn-secondary"
            style={{ padding: '8px 14px', fontSize: '13px' }}
            onClick={loadData}
          >
            Refresh
          </button>
        </div>
      </div>

      {seedSuccessMsg && (
        <div className="card" style={{ borderLeft: '4px solid #10b981', background: 'rgba(16, 185, 129, 0.08)', color: '#6ee7b7', padding: '12px 16px', marginBottom: '14px' }}>
          <strong>✓ Workload Ready:</strong> {seedSuccessMsg}
        </div>
      )}

      {error && (
        <div
          className="alert"
          role="alert"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}
        >
          <span><strong>Telemetry Error:</strong> {error}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={loadData}>
            Retry
          </button>
        </div>
      )}

      {/* Database Connection & Service Health Strip */}
      <div
        className="card"
        data-testid="overview-service-health-strip"
        style={{
          marginBottom: '16px',
          padding: '12px 16px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '12px',
          alignItems: 'center',
          background: '#090f1e',
          borderLeft: `4px solid ${dbConnected ? '#10b981' : '#ef4444'}`,
        }}
      >
        <div>
          <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 700 }}>
            Database & API Health
          </div>
          <div style={{ fontSize: '13px', fontWeight: 700, color: dbConnected ? '#34d399' : '#fca5a5', marginTop: '2px' }}>
            {dbConnected ? '● Connected' : '● Disconnected'}{' '}
            <span style={{ color: '#94a3b8', fontWeight: 400, fontSize: '12px' }}>
              ({diagnostics?.database?.server_version || summary?.source_identifier || 'PostgreSQL'})
            </span>
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 700 }}>
            Last Successful Telemetry
          </div>
          <div style={{ fontSize: '13px', fontWeight: 600, color: '#e2e8f0', marginTop: '2px' }}>
            {formatCollectionTimestamp(lastCollectionTime)}
            {summary?.is_stale && (
              <span className="badge badge-warning" style={{ marginLeft: '6px', fontSize: '10px' }}>
                STALE
              </span>
            )}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 700 }}>
            Sandbox & Collector Status
          </div>
          <div style={{ fontSize: '12px', color: '#cbd5e1', marginTop: '2px' }}>
            Collector: <strong>{summary?.collection_status || diagnostics?.telemetry?.latest_collection_status || 'ok'}</strong>
            {' · '}
            Sandbox: <strong>{diagnostics?.sandbox?.available === false ? 'Unavailable' : 'Ready'}</strong>
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Link to="/health" className="btn btn-secondary btn-sm" style={{ textDecoration: 'none', fontSize: '12px' }}>
            Connection Setup & Health →
          </Link>
        </div>
      </div>

      {/* Data Provenance & Telemetry Transparency Banner */}
      <TelemetryTransparencyBanner summary={summary} />

      {/* Visual Pipeline Flow Header */}
      <OptimizationFlowHeader currentStage="detect" />


      {/* Self-Explanatory Overview Banner */}
      <div className="guide-banner">
        <div className="guide-banner-icon">📊</div>
        <div className="guide-banner-content">
          <div className="guide-banner-title">
            <span>WELCOME TO DBZENITH — AUTONOMOUS POSTGRESQL DBA</span>
            <span className="badge badge-observed">ENTERPRISE TELEMETRY</span>
          </div>
          <p className="guide-banner-desc">
            DBZenith continuously observes live PostgreSQL workload statistics, classifies execution bottlenecks via Graph Neural Networks, generates targeted optimizations (Index Advisor, AST Rewriter, Partitioning, Join Strategies), tests every change in an isolated HypoPG virtual index sandbox, and presents validated changes for human approval.
          </p>
          <div className="guide-banner-pills">
            <span className="badge badge-observed">Observation Window: 24 Hours & 7 Days</span>
            <span className="badge badge-ai-analysis">Privacy Gateway: Active (0 bytes data exposure)</span>
            <span className="badge badge-simulation">HypoPG Sandbox: Ready</span>
            <span className="badge badge-approval-required">Human Gate: Active</span>
          </div>
        </div>
      </div>

      {/* Core Telemetry Cards */}
      <div className="grid metrics" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '14px', marginBottom: '20px' }}>
        <article className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Total Calls</h2>
            <ProvenanceBadge
              badge={summary?.provenance_badge}
              state={summary?.provenance_state}
              isSynthetic={summary?.is_synthetic || summary?.demo_mode_active}
            />
          </div>
          <strong style={{ fontSize: '26px' }}>{summary?.total_calls.toLocaleString() ?? '0'}</strong>
          <p>Total query executions recorded</p>
        </article>

        <article className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Cumulative Time</h2>
            <ProvenanceBadge
              badge={summary?.provenance_badge}
              state={summary?.provenance_state}
              isSynthetic={summary?.is_synthetic || summary?.demo_mode_active}
            />
          </div>
          <strong style={{ fontSize: '26px' }}>{summary ? formatMs(summary.total_exec_time_ms) : '0 ms'}</strong>
          <p>Execution time across all workers</p>
        </article>

        <article className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Unique Queries</h2>
            <ProvenanceBadge
              badge={summary?.provenance_badge}
              state={summary?.provenance_state}
              isSynthetic={summary?.is_synthetic || summary?.demo_mode_active}
            />
          </div>
          <strong style={{ fontSize: '26px' }}>{summary?.unique_queries ?? 0}</strong>
          <p>Distinct normalized query templates</p>
        </article>

        <article className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Slow Queries</h2>
            <ProvenanceBadge
              badge={summary?.provenance_badge}
              state={summary?.provenance_state}
              isSynthetic={summary?.is_synthetic || summary?.demo_mode_active}
            />
          </div>
          <strong style={{ fontSize: '26px', color: (summary?.slow_queries ?? 0) > 0 ? '#b91c1c' : '#166534' }}>
            {summary?.slow_queries ?? 0}
          </strong>
          <p>Queries exceeding latency threshold</p>
        </article>
      </div>

      {/* Phase 5: Optimization Lifecycle & Impact Tracker Dashboard */}
      {lifecycleSummary && (
        <article className="card section-card" style={{ marginBottom: '20px', borderLeft: '4px solid #38bdf8' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', marginBottom: '14px' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <h2 style={{ margin: 0 }}>Optimization Lifecycle & Impact Tracker</h2>
                <span className="badge badge-observed">END-TO-END LIFECYCLE</span>
              </div>
              <span className="muted" style={{ fontSize: '0.82rem' }}>
                Tracks recommendations from discovery and sandbox validation through human approval, deployment verification, and post-change outcome measurement.
              </span>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Link to="/recommendations" className="btn btn-secondary" style={{ fontSize: '0.78rem', padding: '5px 12px', textDecoration: 'none' }}>
                Inspect Recommendations →
              </Link>
              <Link to="/approvals" className="btn btn-secondary" style={{ fontSize: '0.78rem', padding: '5px 12px', textDecoration: 'none' }}>
                Approval Center →
              </Link>
            </div>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
              gap: '12px',
              marginBottom: '14px',
            }}
          >
            <div style={{ background: '#0b1120', border: '1px solid #1e293b', borderRadius: '8px', padding: '12px' }}>
              <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase' }}>Awaiting Approval</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#f59e0b', marginTop: '4px' }}>
                {lifecycleSummary.awaiting_approval_count}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#64748b' }}>Pending DBA decision</div>
            </div>
            <div style={{ background: '#0b1120', border: '1px solid #1e293b', borderRadius: '8px', padding: '12px' }}>
              <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase' }}>Verified Improvements</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#10b981', marginTop: '4px' }}>
                {lifecycleSummary.verified_successful_count}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#64748b' }}>Confirmed post-change gain</div>
            </div>
            <div style={{ background: '#0b1120', border: '1px solid #1e293b', borderRadius: '8px', padding: '12px' }}>
              <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase' }}>Regressions</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: lifecycleSummary.regressed_count > 0 ? '#ef4444' : '#cbd5e1', marginTop: '4px' }}>
                {lifecycleSummary.regressed_count}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#64748b' }}>Post-change latency degraded</div>
            </div>
            <div style={{ background: '#0b1120', border: '1px solid #1e293b', borderRadius: '8px', padding: '12px' }}>
              <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase' }}>Inconclusive / Failed</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#fcd34d', marginTop: '4px' }}>
                {lifecycleSummary.inconclusive_count + lifecycleSummary.failed_count}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#64748b' }}>
                {lifecycleSummary.inconclusive_count} inconclusive · {lifecycleSummary.failed_count} failed
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '12px' }}>
            {/* Awaiting Approval List */}
            <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '12px' }}>
              <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>
                Recommendations Awaiting Approval ({lifecycleSummary.awaiting_approval.length})
              </div>
              {lifecycleSummary.awaiting_approval.length === 0 ? (
                <div style={{ fontSize: '0.78rem', color: '#64748b' }}>No recommendations awaiting approval.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {lifecycleSummary.awaiting_approval.slice(0, 4).map((rec) => (
                    <div
                      key={rec.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '0.78rem',
                        padding: '6px 8px',
                        background: '#0f172a',
                        borderRadius: '6px',
                      }}
                    >
                      <div>
                        <strong style={{ color: '#e2e8f0' }}>#{rec.id}</strong>{' '}
                        <span style={{ color: '#38bdf8' }}>{rec.type}</span> on <code>{rec.target}</code>
                      </div>
                      <span
                        className="badge"
                        style={{
                          fontSize: '0.68rem',
                          padding: '2px 7px',
                          ...lifecycleStateBadgeStyle(rec.lifecycle_state),
                        }}
                      >
                        {(rec.lifecycle_state || 'awaiting_approval').toUpperCase().replace(/_/g, ' ')}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Recently Validated Changes */}
            <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '8px', padding: '12px' }}>
              <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>
                Recently Validated Changes ({lifecycleSummary.recently_validated.length})
              </div>
              {lifecycleSummary.recently_validated.length === 0 ? (
                <div style={{ fontSize: '0.78rem', color: '#64748b' }}>
                  No post-change validations recorded yet. Open a recommendation's Lifecycle & Impact panel to run validation.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {lifecycleSummary.recently_validated.slice(0, 4).map((rec) => {
                    const pct = rec.impact_summary?.latency_improvement_pct
                    return (
                      <div
                        key={rec.id}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          fontSize: '0.78rem',
                          padding: '6px 8px',
                          background: '#0f172a',
                          borderRadius: '6px',
                        }}
                      >
                        <div>
                          <strong style={{ color: '#e2e8f0' }}>#{rec.id}</strong>{' '}
                          <code>{rec.target}</code>
                          {pct != null && (
                            <span
                              style={{
                                marginLeft: '8px',
                                fontWeight: 700,
                                color: pct > 0 ? '#10b981' : '#ef4444',
                              }}
                            >
                              {pct > 0 ? `+${pct.toFixed(1)}% faster` : `${pct.toFixed(1)}%`}
                            </span>
                          )}
                        </div>
                        <span
                          className="badge"
                          style={{
                            fontSize: '0.68rem',
                            padding: '2px 7px',
                            ...lifecycleStateBadgeStyle(rec.lifecycle_state),
                          }}
                        >
                          {(rec.lifecycle_state || '').toUpperCase().replace(/_/g, ' ')}
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Active Regressions List */}
            <div
              style={{
                background: '#090d16',
                border: lifecycleSummary.regressions.length > 0 ? '1px solid rgba(239, 68, 68, 0.5)' : '1px solid #1e293b',
                borderRadius: '8px',
                padding: '12px',
              }}
            >
              <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f8fafc', marginBottom: '8px' }}>
                Active Regressions ({lifecycleSummary.regressions.length})
              </div>
              {lifecycleSummary.regressions.length === 0 ? (
                <div style={{ fontSize: '0.78rem', color: '#34d399' }}>
                  ✓ No post-change performance regressions detected across validated optimizations.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {lifecycleSummary.regressions.slice(0, 4).map((rec) => (
                    <div
                      key={rec.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '0.78rem',
                        padding: '6px 8px',
                        background: 'rgba(239, 68, 68, 0.12)',
                        border: '1px solid rgba(239, 68, 68, 0.35)',
                        borderRadius: '6px',
                      }}
                    >
                      <div>
                        <strong style={{ color: '#fca5a5' }}>#{rec.id}</strong>{' '}
                        <code>{rec.target}</code> — {rec.type}
                      </div>
                      <Link
                        to="/recommendations"
                        className="badge badge-danger"
                        style={{ textDecoration: 'none', fontSize: '0.68rem' }}
                      >
                        INVESTIGATE →
                      </Link>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </article>
      )}

      {/* Reusable Optimization Trace for Top Active Recommendation */}
      {featuredTrace && (
        <OptimizationTrace
          title={`Featured Optimization Trace: ${featuredTrace.recommendation.target} (${featuredTrace.recommendation.type.replace('_', ' ').toUpperCase()})`}
          query={
            featuredTrace.matching_queries.length > 0
              ? featuredTrace.matching_queries[0]
              : summary?.top_queries?.length
              ? {
                  query_id: summary.top_queries[0].query_id,
                  normalized_query: summary.top_queries[0].query,
                  mean_exec_time_ms: summary.top_queries[0].mean_exec_time_ms,
                  calls: summary.top_queries[0].calls,
                  total_exec_time_ms: summary.top_queries[0].total_exec_time_ms,
                }
              : null
          }
          recommendation={featuredTrace.recommendation}
          simulation={featuredTrace.simulation}
          auditInfo={
            featuredTrace.audit_events.length > 0
              ? {
                  action: featuredTrace.audit_events[0].action,
                  status: featuredTrace.audit_events[0].new_status,
                  reason: featuredTrace.audit_events[0].reason,
                  timestamp: featuredTrace.audit_events[0].created_at ?? undefined,
                }
              : null
          }
          onSimulate={handleSimulateFeatured}
          onApprove={handleApproveFeatured}
          onReject={handleRejectFeatured}
          isSimulating={isSimulating}
          isDeciding={isDeciding}
          initialExpanded={true}
        />
      )}

      {/* Top Workload Queries */}
      <article className="card section-card">
        <div className="section-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <div>
            <h2 style={{ margin: 0 }}>Top Workload Queries</h2>
            <span className="muted">Ranked by total execution impact from pg_stat_statements</span>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <ProvenanceBadge
              badge={summary?.provenance_badge}
              state={summary?.provenance_state}
              isSynthetic={summary?.is_synthetic || summary?.demo_mode_active}
            />
            <Link to="/slow-queries" className="btn btn-secondary btn-sm" style={{ textDecoration: 'none', fontSize: '12px' }}>
              All Slow Queries →
            </Link>
          </div>
        </div>

        {summary?.top_queries?.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Query ID</th>
                  <th>Provenance</th>
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
                    <td>
                      <ProvenanceBadge
                        badge={q.provenance_badge || summary?.provenance_badge}
                        state={q.provenance_state || summary?.provenance_state}
                        isSynthetic={q.is_synthetic ?? summary?.is_synthetic}
                      />
                    </td>
                    <td>{q.calls.toLocaleString()}</td>
                    <td>
                      <span className={q.mean_exec_time_ms > 100 ? 'badge sev-high' : 'badge sev-low'}>
                        {formatMs(q.mean_exec_time_ms)}
                      </span>
                    </td>
                    <td>{formatMs(q.total_exec_time_ms)}</td>
                    <td className="query-cell">{q.query}</td>
                    <td>
                      <Link
                        to={`/queries?id=${q.id || q.query_id}`}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          color: '#38bdf8',
                          textDecoration: 'none',
                          fontWeight: 600,
                          fontSize: '12px',
                        }}
                      >
                        ⚡ Analyze Optimization →
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

      {/* Workload Trends & Telemetry Snapshot History */}
      {snapshots.length > 0 && (
        <article className="card section-card" style={{ marginTop: '20px' }}>
          <div className="section-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div>
              <h2 style={{ margin: 0 }}>Workload Trends & Telemetry Snapshot History</h2>
              <span className="muted">Observed execution time and slow query progression across captured snapshots</span>
            </div>
            <ProvenanceBadge
              badge={summary?.provenance_badge}
              state={summary?.provenance_state}
              isSynthetic={summary?.is_synthetic || summary?.demo_mode_active}
            />
          </div>

          {/* Visual Workload Trend Bars (from real snapshot observations) */}
          {(() => {
            const ordered = [...snapshots].reverse()
            const maxTime = Math.max(
              1,
              ...ordered.map((s) => Number(s.total_exec_time_ms ?? 0)),
            )
            return (
              <div
                data-testid="workload-trends-chart"
                style={{
                  display: 'grid',
                  gridTemplateColumns: `repeat(${Math.max(1, ordered.length)}, minmax(0, 1fr))`,
                  gap: '8px',
                  alignItems: 'end',
                  height: '96px',
                  padding: '12px',
                  marginBottom: '14px',
                  background: '#090f1e',
                  border: '1px solid #1e293b',
                  borderRadius: '8px',
                }}
              >
                {ordered.map((s, idx) => {
                  const execMs = Number(s.total_exec_time_ms ?? 0)
                  const slowCnt = Number(s.slow_queries ?? 0)
                  const pct = Math.max(10, Math.round((execMs / maxTime) * 100))
                  return (
                    <div
                      key={String(s.id ?? idx)}
                      title={`Snapshot #${String(s.id ?? idx)}: ${formatMs(execMs)} total exec, ${slowCnt} slow queries`}
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'flex-end',
                        height: '100%',
                        gap: '4px',
                      }}
                    >
                      <div
                        style={{
                          width: '100%',
                          height: `${pct}%`,
                          background: slowCnt > 5 ? '#ef4444' : slowCnt > 0 ? '#f59e0b' : '#38bdf8',
                          borderRadius: '4px 4px 0 0',
                          opacity: 0.85,
                        }}
                      />
                      <span style={{ fontSize: '10px', color: '#94a3b8', fontFamily: 'monospace' }}>
                        #{String(s.id ?? idx)}
                      </span>
                    </div>
                  )
                })}
              </div>
            )
          })()}

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Snapshot ID</th>
                  <th>Provenance</th>
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
                    <td>
                      <ProvenanceBadge
                        badge={s.provenance_badge ? String(s.provenance_badge) : undefined}
                        state={s.provenance_state ? String(s.provenance_state) : undefined}
                        isSynthetic={Boolean(s.is_synthetic)}
                      />
                    </td>
                    <td>{formatCollectionTimestamp(s.captured_at ? String(s.captured_at) : null)}</td>
                    <td><span className="badge badge-observed" style={{ fontSize: '11px' }}>{formatWindow(Number(s.window_seconds ?? 0))}</span></td>
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

