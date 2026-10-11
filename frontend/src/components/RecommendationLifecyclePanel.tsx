import React, { useEffect, useState } from 'react'
import {
  Recommendation,
  RecommendationTrace,
  approveRecommendation,
  rejectRecommendation,
  captureRecommendationBaseline,
  transitionRecommendationLifecycle,
  applyRecommendation,
  validateRecommendationOutcome,
  exportRecommendationLifecycle,
  getRecommendationTrace,
  createSimulation,
} from '../lib/api'
import { ProvenanceBadge, formatCollectionTimestamp } from './ProvenanceBadge'
import { useAuth } from '../context/AuthContext'

export interface RecommendationLifecyclePanelProps {
  recommendationId: number
  initialRecommendation?: Recommendation
  onUpdated?: (updated: Recommendation) => void
  onClose?: () => void
}

const LIFECYCLE_STEPS = [
  { key: 'detected', label: '1. Detected' },
  { key: 'analyzed', label: '2. Analyzed' },
  { key: 'proposed', label: '3. Proposed' },
  { key: 'simulated', label: '4. Simulated' },
  { key: 'awaiting_approval', label: '5. Awaiting Approval' },
  { key: 'approved', label: '6. Approved / Rejected' },
  { key: 'ready_for_deployment', label: '7. Ready for Deploy' },
  { key: 'applied', label: '8. Applied (Verified)' },
  { key: 'validation_pending', label: '9. Validation' },
  { key: 'outcome', label: '10. Measured Outcome' },
]

function getStepIndex(lifecycleState: string | undefined): number {
  const st = (lifecycleState || 'awaiting_approval').toLowerCase()
  if (st === 'detected') return 0
  if (st === 'analyzed') return 1
  if (st === 'proposed') return 2
  if (st === 'simulated') return 3
  if (st === 'awaiting_approval') return 4
  if (st === 'approved' || st === 'rejected') return 5
  if (st === 'ready_for_deployment') return 6
  if (st === 'applied') return 7
  if (st === 'validation_pending') return 8
  if (['verified_successful', 'regressed', 'failed', 'inconclusive'].includes(st)) return 9
  return 4
}

export function lifecycleStateBadgeStyle(state: string | undefined): React.CSSProperties {
  const st = (state || 'awaiting_approval').toLowerCase()
  if (st === 'verified_successful') {
    return { background: 'rgba(16, 185, 129, 0.18)', color: '#34d399', border: '1px solid rgba(16, 185, 129, 0.45)' }
  }
  if (st === 'regressed' || st === 'failed' || st === 'rejected') {
    return { background: 'rgba(239, 68, 68, 0.18)', color: '#fca5a5', border: '1px solid rgba(239, 68, 68, 0.45)' }
  }
  if (st === 'inconclusive') {
    return { background: 'rgba(245, 158, 11, 0.18)', color: '#fcd34d', border: '1px solid rgba(245, 158, 11, 0.45)' }
  }
  if (st === 'applied' || st === 'ready_for_deployment' || st === 'approved') {
    return { background: 'rgba(56, 189, 248, 0.18)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.45)' }
  }
  return { background: 'rgba(168, 85, 247, 0.16)', color: '#c084fc', border: '1px solid rgba(168, 85, 247, 0.4)' }
}

function fmtNum(val: any, decimals = 2, suffix = ''): string {
  if (val === null || val === undefined || val === '') return 'N/A'
  const num = Number(val)
  if (!Number.isFinite(num)) return 'N/A'
  return `${num.toFixed(decimals)}${suffix}`
}

export function RecommendationLifecyclePanel({
  recommendationId,
  initialRecommendation,
  onUpdated,
  onClose,
}: RecommendationLifecyclePanelProps) {
  const { canSimulate, canApprove } = useAuth()
  const [trace, setTrace] = useState<RecommendationTrace | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  // Operator inputs
  const [decisionReason, setDecisionReason] = useState('Approved after reviewing sandbox and baseline evidence')
  const [deploymentRef, setDeploymentRef] = useState('')
  const [verifyCatalog, setVerifyCatalog] = useState(false)
  const [postObsLatency, setPostObsLatency] = useState('')
  const [postObsCalls, setPostObsCalls] = useState('150')
  const [exportPreview, setExportPreview] = useState<{ format: string; content: string } | null>(null)

  const loadTrace = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getRecommendationTrace(recommendationId)
      setTrace(data)
    } catch (err: any) {
      setError(err?.message || 'Failed to load recommendation lifecycle trace')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTrace()
  }, [recommendationId])

  const rec = trace?.recommendation || initialRecommendation
  if (!rec && loading) {
    return (
      <div className="card" style={{ padding: '24px', color: '#94a3b8' }}>
        Loading optimization lifecycle & impact tracker for Recommendation #{recommendationId}...
      </div>
    )
  }
  if (!rec) {
    return (
      <div className="card" style={{ padding: '24px', borderColor: '#ef4444', color: '#fca5a5' }}>
        {error || `Recommendation #${recommendationId} not found.`}
      </div>
    )
  }

  const lifecycleState = rec.lifecycle_state || (rec.status === 'approved' ? 'approved' : rec.status === 'rejected' ? 'rejected' : 'awaiting_approval')
  const activeStepIdx = getStepIndex(lifecycleState)
  const baseline = rec.baseline_metrics || null
  const postChange = rec.post_change_metrics || null
  const impact = rec.impact_summary || null
  const deployDetails = rec.deployment_details || null
  const candidateSim = trace?.simulation || null
  const simHistory = trace?.simulation_history || (candidateSim ? [candidateSim] : [])
  const auditEvents = trace?.audit_events || []

  const handleAction = async (label: string, fn: () => Promise<Recommendation | any>) => {
    setBusyAction(label)
    setError(null)
    setFeedback(null)
    try {
      const res = await fn()
      await loadTrace()
      if (res && typeof res === 'object' && 'id' in res && onUpdated) {
        onUpdated(res as Recommendation)
      }
      setFeedback(`${label} completed.`)
    } catch (err: any) {
      setError(err?.message || `${label} failed`)
    } finally {
      setBusyAction(null)
    }
  }

  const handleExport = async (format: 'json' | 'csv') => {
    setBusyAction(`Export ${format.toUpperCase()}`)
    setError(null)
    try {
      const exported = await exportRecommendationLifecycle(rec.id, format)
      setExportPreview({ format: format.toUpperCase(), content: exported.content })
      try {
        const blob = new Blob([exported.content], { type: exported.mimeType })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = exported.filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      } catch {
        // Fallback preview in test/non-DOM environments
      }
      setFeedback(`Exported recommendation #${rec.id} lifecycle as ${format.toUpperCase()}.`)
    } catch (err: any) {
      setError(err?.message || 'Export failed')
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <div
      data-testid={`lifecycle-panel-${rec.id}`}
      className="card"
      style={{
        background: '#090d16',
        border: '1px solid #334155',
        borderRadius: '12px',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '18px',
      }}
    >
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0, fontSize: '1.2rem', color: '#f8fafc', fontWeight: 700 }}>
              Recommendation #{rec.id} — End-to-End Optimization Lifecycle & Impact Tracker
            </h3>
            <span
              data-testid="lifecycle-state-badge"
              style={{
                ...lifecycleStateBadgeStyle(lifecycleState),
                padding: '3px 10px',
                borderRadius: '999px',
                fontSize: '0.75rem',
                fontWeight: 700,
                textTransform: 'uppercase',
              }}
            >
              {lifecycleState.replace(/_/g, ' ')}
            </span>
            <ProvenanceBadge
              badge={rec.provenance_badge || 'ESTIMATED'}
              state={rec.provenance_state}
              isSynthetic={rec.is_synthetic}
            />
          </div>
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginTop: '6px', fontSize: '0.8rem', color: '#94a3b8' }}>
            <span>
              Target: <strong style={{ color: '#e2e8f0' }}>{rec.target}</strong>
            </span>
            <span>
              Query Fingerprint:{' '}
              <code data-testid="recommendation-fingerprint" style={{ color: '#38bdf8' }}>
                {rec.query_fingerprint || baseline?.query_fingerprint || 'N/A'}
              </code>
            </span>
            <span>
              Source: <code>{rec.source_identifier || baseline?.source_identifier || 'N/A'}</code>
            </span>
            <span>
              Risk: <strong style={{ color: rec.risk === 'low' ? '#10b981' : '#f59e0b' }}>{rec.risk.toUpperCase()}</strong>
            </span>
            <span>
              Confidence: <strong style={{ color: '#38bdf8' }}>{Math.round((rec.confidence || 0) * 100)}%</strong>
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '5px 10px' }}
            disabled={busyAction !== null}
            onClick={() => handleExport('json')}
          >
            ⬇ Export JSON
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '5px 10px' }}
            disabled={busyAction !== null}
            onClick={() => handleExport('csv')}
          >
            ⬇ Export CSV
          </button>
          {onClose && (
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.75rem', padding: '5px 10px' }}
              onClick={onClose}
            >
              Close ✕
            </button>
          )}
        </div>
      </div>

      {/* Visual Lifecycle Stepper */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(115px, 1fr))',
          gap: '6px',
          background: '#0f172a',
          padding: '12px',
          borderRadius: '8px',
          border: '1px solid #1e293b',
        }}
      >
        {LIFECYCLE_STEPS.map((step, idx) => {
          const isCompleted = idx < activeStepIdx && lifecycleState !== 'rejected'
          const isCurrent = idx === activeStepIdx
          return (
            <div
              key={step.key}
              style={{
                padding: '6px 8px',
                borderRadius: '6px',
                fontSize: '0.72rem',
                fontWeight: isCurrent ? 700 : 500,
                background: isCurrent
                  ? 'rgba(56, 189, 248, 0.18)'
                  : isCompleted
                  ? 'rgba(16, 185, 129, 0.12)'
                  : '#090d16',
                color: isCurrent ? '#38bdf8' : isCompleted ? '#34d399' : '#64748b',
                border: isCurrent
                  ? '1px solid rgba(56, 189, 248, 0.5)'
                  : isCompleted
                  ? '1px solid rgba(16, 185, 129, 0.3)'
                  : '1px solid #1e293b',
              }}
            >
              {isCompleted ? '✓ ' : isCurrent ? '● ' : ''}
              {step.key === 'outcome' && idx === activeStepIdx
                ? `10. ${lifecycleState.replace(/_/g, ' ').toUpperCase()}`
                : step.label}
            </div>
          )
        })}
      </div>

      {/* Feedback & Errors */}
      {feedback && (
        <div style={{ padding: '10px 14px', borderRadius: '6px', background: 'rgba(16, 185, 129, 0.12)', border: '1px solid rgba(16, 185, 129, 0.4)', color: '#6ee7b7', fontSize: '0.82rem' }}>
          ✓ {feedback}
        </div>
      )}
      {error && (
        <div style={{ padding: '10px 14px', borderRadius: '6px', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.4)', color: '#fca5a5', fontSize: '0.82rem' }}>
          ⚠ {error}
        </div>
      )}

      {/* Export Preview Drawer if triggered */}
      {exportPreview && (
        <div style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: '8px', padding: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <strong style={{ fontSize: '0.8rem', color: '#38bdf8' }}>
              Exported Lifecycle Payload ({exportPreview.format})
            </strong>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '2px 8px' }}
              onClick={() => setExportPreview(null)}
            >
              Dismiss Preview
            </button>
          </div>
          <pre
            data-testid="lifecycle-export-preview"
            style={{
              margin: 0,
              maxHeight: '180px',
              overflow: 'auto',
              fontSize: '0.75rem',
              background: '#090d16',
              padding: '10px',
              borderRadius: '6px',
              color: '#cbd5e1',
            }}
          >
            {exportPreview.content}
          </pre>
        </div>
      )}

      {/* Root Cause Evidence & Proposed SQL Change */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '14px' }}>
        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px' }}>
          <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 700 }}>
            Root Cause & Diagnostic Evidence
          </div>
          <p style={{ margin: '6px 0 10px 0', fontSize: '0.85rem', color: '#e2e8f0', lineHeight: 1.5 }}>
            {rec.reason}
          </p>
          <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
            <div>Expected Benefit: <strong style={{ color: '#34d399' }}>{rec.expected_benefit}</strong></div>
            <div style={{ marginTop: '4px' }}>
              Evidence Snapshot: <code>{JSON.stringify(rec.evidence || {})}</code>
            </div>
          </div>
        </div>

        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px' }}>
          <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 700 }}>
            Suggested SQL / Index Change
          </div>
          <pre
            style={{
              margin: '8px 0',
              background: '#090d16',
              padding: '10px 12px',
              borderRadius: '6px',
              border: '1px solid #1e293b',
              fontSize: '0.82rem',
              color: '#a78bfa',
              overflowX: 'auto',
            }}
          >
            {rec.proposed_change}
          </pre>
          <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
            Safety Invariant: <strong>Never automatically executed against production without DBA approval & deployment confirmation.</strong>
          </div>
        </div>
      </div>

      {/* Baseline Capture & Candidate Validation Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '14px' }}>
        {/* Baseline Capture Card */}
        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f8fafc', textTransform: 'uppercase' }}>
                Pre-Change Baseline Capture
              </span>
              {baseline && (
                <ProvenanceBadge
                  badge={baseline.provenance_badge}
                  state={baseline.provenance_state}
                  isSynthetic={baseline.is_synthetic}
                />
              )}
            </div>
            {canSimulate && !rec.applied_at && (
              <button
                type="button"
                className="btn btn-secondary"
                style={{ fontSize: '0.72rem', padding: '3px 8px' }}
                disabled={busyAction !== null}
                onClick={() => handleAction('Baseline Capture', () => captureRecommendationBaseline(rec.id))}
              >
                ↻ Capture Baseline
              </button>
            )}
          </div>

          {baseline ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', fontSize: '0.78rem' }}>
              <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>Mean / P50 Latency</div>
                <strong style={{ color: '#f8fafc' }}>
                  {fmtNum(baseline.mean_latency_ms, 2, ' ms')} / {fmtNum(baseline.p50_latency_ms, 2, ' ms')}
                </strong>
              </div>
              <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>P95 / P99 Latency</div>
                <strong style={{ color: '#f8fafc' }}>
                  {fmtNum(baseline.p95_latency_ms, 2, ' ms')} / {fmtNum(baseline.p99_latency_ms, 2, ' ms')}
                </strong>
              </div>
              <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>Sample Count (Calls)</div>
                <strong style={{ color: '#38bdf8' }}>{baseline.sample_size ?? 0}</strong>
              </div>
              <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>Throughput / Window</div>
                <strong style={{ color: '#cbd5e1' }}>
                  {fmtNum(baseline.throughput_qps, 3, ' QPS')} ({fmtNum(baseline.window_seconds, 0, 's')})
                </strong>
              </div>
              <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>Shared Blks Read / Hit</div>
                <strong style={{ color: '#cbd5e1' }}>
                  {baseline.resource_indicators?.shared_blks_read ?? 0} / {baseline.resource_indicators?.shared_blks_hit ?? 0}
                </strong>
              </div>
              <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>Variability (CV) / Errors</div>
                <strong style={{ color: '#cbd5e1' }}>
                  CV={fmtNum(baseline.variability?.coefficient_of_variation, 2)} | Err={baseline.error_count ?? 0}
                </strong>
              </div>
              <div style={{ gridColumn: '1 / -1', fontSize: '0.72rem', color: '#64748b' }}>
                Collected: {formatCollectionTimestamp(baseline.captured_at)} • Source: <code>{baseline.source_identifier || 'N/A'}</code>
              </div>
            </div>
          ) : (
            <div style={{ fontSize: '0.8rem', color: '#94a3b8', padding: '12px 0' }}>
              No baseline observation window captured yet. Click "Capture Baseline" to record pre-change metrics.
            </div>
          )}
        </div>

        {/* Candidate Simulation & Validation Link Card */}
        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f8fafc', textTransform: 'uppercase' }}>
                Candidate Sandbox Validation
              </span>
              {candidateSim && (
                <ProvenanceBadge
                  badge={candidateSim.provenance_badge}
                  state={candidateSim.provenance_state}
                  isSynthetic={candidateSim.is_synthetic}
                />
              )}
            </div>
            {canSimulate && rec.requires_approval && (
              <button
                type="button"
                className="btn btn-primary"
                style={{ fontSize: '0.72rem', padding: '3px 8px' }}
                disabled={busyAction !== null}
                onClick={() => handleAction('Sandbox Simulation', () => createSimulation(rec.id, 3))}
              >
                🧪 Run Sandbox Validation
              </button>
            )}
          </div>

          {candidateSim ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.78rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>Linked Simulation ID</div>
                  <strong style={{ color: '#38bdf8' }}>#{candidateSim.id}</strong>
                </div>
                <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>Baseline → Proposed Cost</div>
                  <strong style={{ color: '#f8fafc' }}>
                    {fmtNum(candidateSim.baseline_cost, 1)} → {fmtNum(candidateSim.proposed_cost, 1)}
                  </strong>
                </div>
                <div style={{ background: '#090d16', padding: '8px', borderRadius: '6px' }}>
                  <div style={{ color: '#94a3b8', fontSize: '0.7rem' }}>Estimated Cost Reduction</div>
                  <strong style={{ color: '#34d399' }}>{fmtNum(candidateSim.improvement, 1, '%')}</strong>
                </div>
              </div>
              <div style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
                Method: <code>{candidateSim.simulation_method || 'hypopg_plan_estimate'}</code> • Runs Recorded: {simHistory.length}
              </div>
            </div>
          ) : (
            <div style={{ fontSize: '0.8rem', color: '#94a3b8', padding: '12px 0' }}>
              No candidate simulation linked yet. Run a sandbox validation to assess before approval.
            </div>
          )}
        </div>
      </div>

      {/* Post-Change Impact & Uncertainty Assessment */}
      <div
        data-testid="impact-assessment-section"
        style={{
          background: '#0f172a',
          border: '1px solid #334155',
          borderRadius: '8px',
          padding: '14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: '#f8fafc', textTransform: 'uppercase' }}>
              Post-Change Validation, Impact & Confidence Assessment
            </span>
            {impact && (
              <>
                <span
                  data-testid="impact-outcome-badge"
                  style={{
                    ...lifecycleStateBadgeStyle(impact.outcome_classification),
                    padding: '2px 8px',
                    borderRadius: '999px',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                  }}
                >
                  OUTCOME: {String(impact.outcome_classification || 'inconclusive').replace(/_/g, ' ')}
                </span>
                <span
                  className="badge"
                  style={{
                    background: '#1e293b',
                    color: impact.environment === 'production' ? '#34d399' : '#fbbf24',
                    fontSize: '0.7rem',
                  }}
                >
                  ENV: {String(impact.environment || 'unvalidated').toUpperCase()}
                </span>
                <span
                  className="badge"
                  style={{
                    background: impact.is_comparable ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                    color: impact.is_comparable ? '#34d399' : '#fcd34d',
                    fontSize: '0.7rem',
                  }}
                >
                  {impact.is_comparable ? '✓ COMPARABLE WINDOWS' : '⚠ INCOMPARABLE / INCOMPLETE DATA'}
                </span>
              </>
            )}
          </div>

          {canSimulate && rec.status !== 'rejected' && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ fontSize: '0.72rem', padding: '4px 10px' }}
                disabled={busyAction !== null}
                onClick={() =>
                  handleAction('Sandbox Benchmark Validation', () =>
                    validateRecommendationOutcome(rec.id, {
                      use_sandbox_benchmark: true,
                      reason: 'Validated candidate impact using sandbox benchmark (local demo mode)',
                    }),
                  )
                }
              >
                🧪 Validate via Sandbox Benchmark
              </button>
            </div>
          )}
        </div>

        {impact ? (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '10px', fontSize: '0.8rem' }}>
              <div style={{ background: '#090d16', padding: '10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.72rem' }}>Mean Latency (Before → After)</div>
                <strong style={{ color: '#f8fafc' }}>
                  {fmtNum(baseline?.mean_latency_ms, 2, ' ms')} → {fmtNum(postChange?.mean_latency_ms, 2, ' ms')}
                </strong>
                <div style={{ fontSize: '0.75rem', marginTop: '4px', color: (impact.latency_improvement_pct ?? 0) > 0 ? '#34d399' : (impact.latency_improvement_pct ?? 0) < 0 ? '#ef4444' : '#94a3b8' }}>
                  {impact.latency_improvement_pct != null
                    ? `${impact.latency_improvement_pct > 0 ? '-' : '+'}${Math.abs(impact.latency_improvement_pct).toFixed(2)}% latency (${fmtNum(impact.latency_delta_ms, 2, ' ms')})`
                    : 'Percentage N/A (not comparable)'}
                </div>
              </div>

              <div style={{ background: '#090d16', padding: '10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.72rem' }}>P95 Latency Improvement</div>
                <strong style={{ color: '#38bdf8' }}>
                  {impact.p95_latency_improvement_pct != null ? `${impact.p95_latency_improvement_pct.toFixed(2)}%` : 'N/A'}
                </strong>
                <div style={{ fontSize: '0.72rem', color: '#64748b', marginTop: '4px' }}>
                  {fmtNum(baseline?.p95_latency_ms, 2, ' ms')} → {fmtNum(postChange?.p95_latency_ms, 2, ' ms')}
                </div>
              </div>

              <div style={{ background: '#090d16', padding: '10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.72rem' }}>Throughput / I/O Read Delta</div>
                <strong style={{ color: '#cbd5e1' }}>
                  QPS: {impact.throughput_change_pct != null ? `${impact.throughput_change_pct > 0 ? '+' : ''}${impact.throughput_change_pct.toFixed(1)}%` : 'N/A'}
                </strong>
                <div style={{ fontSize: '0.72rem', color: '#64748b', marginTop: '4px' }}>
                  I/O Read Reduction: {impact.io_read_reduction_pct != null ? `${impact.io_read_reduction_pct.toFixed(1)}%` : 'N/A'}
                </div>
              </div>

              <div style={{ background: '#090d16', padding: '10px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.72rem' }}>Sample Count & Variability</div>
                <strong style={{ color: '#cbd5e1' }}>
                  n={impact.confidence_assessment?.sample_count_before ?? 0} → n={impact.confidence_assessment?.sample_count_after ?? 0}
                </strong>
                <div style={{ fontSize: '0.72rem', color: '#64748b', marginTop: '4px' }}>
                  CV: {fmtNum(impact.confidence_assessment?.variability_before_cv, 2)} → {fmtNum(impact.confidence_assessment?.variability_after_cv, 2)}
                </div>
              </div>
            </div>

            {impact.incomparability_reasons && impact.incomparability_reasons.length > 0 && (
              <div style={{ padding: '8px 12px', borderRadius: '6px', background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.35)', color: '#fcd34d', fontSize: '0.76rem' }}>
                <strong>Incomparability Safeguard Triggered:</strong>{' '}
                {impact.incomparability_reasons.join(', ')} — Percentage changes are suppressed when baseline/comparison metrics are missing, zero, or mismatched.
              </div>
            )}

            <div data-testid="causality-disclaimer" style={{ padding: '8px 12px', borderRadius: '6px', background: '#090d16', border: '1px solid #1e293b', fontSize: '0.74rem', color: '#94a3b8' }}>
              <div>
                <strong>Attribution & Uncertainty Note:</strong>{' '}
                {impact.confidence_assessment?.causality_disclaimer}
              </div>
              {impact.confidence_assessment?.uncertainty_notes?.length > 1 && (
                <div style={{ marginTop: '4px', color: '#cbd5e1' }}>
                  • {impact.confidence_assessment.uncertainty_notes.slice(1).join(' • ')}
                </div>
              )}
            </div>
          </>
        ) : (
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            No post-change validation has been executed yet. After approval or deployment (or via Sandbox Benchmark for local demos), run validation to compute before/after impact and confidence intervals.
          </div>
        )}

        {/* Record Post-Change Observation Window Form (for ANALYST/DBA) */}
        {canSimulate && rec.status === 'approved' && (
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', paddingTop: '8px', borderTop: '1px solid #1e293b' }}>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>
              Validate Observed Post-Change Window:
            </span>
            <input
              type="number"
              step="0.1"
              placeholder="Observed Mean Latency (ms)"
              className="filter-input"
              style={{ width: '190px', fontSize: '0.75rem', padding: '4px 8px' }}
              value={postObsLatency}
              onChange={(e) => setPostObsLatency(e.target.value)}
            />
            <input
              type="number"
              placeholder="Sample Calls"
              className="filter-input"
              style={{ width: '120px', fontSize: '0.75rem', padding: '4px 8px' }}
              value={postObsCalls}
              onChange={(e) => setPostObsCalls(e.target.value)}
            />
            <button
              type="button"
              className="btn btn-primary"
              style={{ fontSize: '0.72rem', padding: '4px 10px' }}
              disabled={busyAction !== null || !postObsLatency.trim()}
              onClick={() =>
                handleAction('Post-Change Telemetry Validation', () =>
                  validateRecommendationOutcome(rec.id, {
                    post_change_observation: {
                      mean_exec_time_ms: Number(postObsLatency),
                      calls: Number(postObsCalls) || 100,
                      window_seconds: baseline?.window_seconds || 60,
                      query_fingerprint: rec.query_fingerprint || baseline?.query_fingerprint,
                      is_synthetic: Boolean(rec.is_synthetic),
                      is_measured: !rec.is_synthetic,
                      environment: rec.is_synthetic ? 'synthetic_demo' : 'production',
                    },
                    reason: 'Validated against observed post-change telemetry window',
                  }),
                )
              }
            >
              ✓ Evaluate Post-Change Observation
            </button>
          </div>
        )}
      </div>

      {/* Governance Decision & Deployment Confirmation Controls (DBA / ADMIN) */}
      {canApprove && (
        <div
          style={{
            background: '#0f172a',
            border: '1px solid #1e293b',
            borderRadius: '8px',
            padding: '14px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
          }}
        >
          <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f8fafc', textTransform: 'uppercase' }}>
            DBA Governance, Deployment Readiness & Confirmed Application
          </div>

          {rec.status === 'pending' && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                type="text"
                className="filter-input"
                style={{ flex: 1, minWidth: '220px', fontSize: '0.78rem' }}
                value={decisionReason}
                onChange={(e) => setDecisionReason(e.target.value)}
                placeholder="Decision rationale (written to immutable audit log)..."
              />
              <button
                type="button"
                className="btn btn-primary"
                style={{ background: '#059669', borderColor: '#059669', fontSize: '0.75rem', padding: '5px 12px' }}
                disabled={busyAction !== null}
                onClick={() => handleAction('Approve Recommendation', () => approveRecommendation(rec.id, decisionReason))}
              >
                ✓ Approve
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ color: '#fca5a5', borderColor: '#ef4444', fontSize: '0.75rem', padding: '5px 12px' }}
                disabled={busyAction !== null}
                onClick={() => handleAction('Reject Recommendation', () => rejectRecommendation(rec.id, decisionReason))}
              >
                ✕ Reject
              </button>
            </div>
          )}

          {rec.status === 'approved' && lifecycleState === 'approved' && (
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ fontSize: '0.75rem', padding: '5px 12px' }}
                disabled={busyAction !== null}
                onClick={() =>
                  handleAction('Mark Ready for Deployment', () =>
                    transitionRecommendationLifecycle(
                      rec.id,
                      'ready_for_deployment',
                      'Change window scheduled; marked ready for deployment',
                    ),
                  )
                }
              >
                🚀 Mark Ready for Deployment
              </button>
            </div>
          )}

          {rec.status === 'approved' && (lifecycleState === 'approved' || lifecycleState === 'ready_for_deployment') && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', paddingTop: '6px' }}>
              <input
                type="text"
                className="filter-input"
                style={{ flex: 1, minWidth: '220px', fontSize: '0.76rem' }}
                placeholder="Deployment ticket / DDL execution reference (e.g. CHG-2026-104)"
                value={deploymentRef}
                onChange={(e) => setDeploymentRef(e.target.value)}
              />
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: '#cbd5e1' }}>
                <input
                  type="checkbox"
                  checked={verifyCatalog}
                  onChange={(e) => setVerifyCatalog(e.target.checked)}
                />
                Verify in DB Catalog
              </label>
              <button
                type="button"
                className="btn btn-primary"
                style={{ fontSize: '0.75rem', padding: '5px 12px' }}
                disabled={busyAction !== null || (!verifyCatalog && deploymentRef.trim().length < 3)}
                onClick={() =>
                  handleAction('Confirm Applied', () =>
                    applyRecommendation(rec.id, {
                      confirm_applied: true,
                      verify_catalog: verifyCatalog,
                      deployment_reference: deploymentRef.trim() || undefined,
                      reason: `Confirmed applied (${verifyCatalog ? 'catalog verified' : deploymentRef.trim()})`,
                    }),
                  )
                }
              >
                ✓ Confirm Applied with Evidence
              </button>
            </div>
          )}

          {deployDetails && (
            <div style={{ fontSize: '0.75rem', color: '#38bdf8', background: '#090d16', padding: '8px 10px', borderRadius: '6px' }}>
              <strong>Deployment Evidence Confirmed:</strong> {deployDetails.verification_note} by{' '}
              <strong>{deployDetails.applied_by}</strong> ({deployDetails.applied_by_role}) at{' '}
              {formatCollectionTimestamp(deployDetails.applied_at)}
            </div>
          )}
        </div>
      )}

      {/* Decision & Lifecycle History Audit Table */}
      <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px' }}>
        <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#f8fafc', textTransform: 'uppercase', marginBottom: '8px' }}>
          Decision & Lifecycle Audit Trail ({auditEvents.length} Events)
        </div>
        {rec.decided_by && (
          <div style={{ fontSize: '0.76rem', color: '#34d399', marginBottom: '8px' }}>
            Latest Decision: <strong>{rec.status.toUpperCase()}</strong> by <strong>{rec.decided_by}</strong> at{' '}
            {formatCollectionTimestamp(rec.decided_at)} — Reason: <em>"{rec.decision_reason}"</em>
          </div>
        )}
        {auditEvents.length === 0 ? (
          <div style={{ fontSize: '0.78rem', color: '#64748b' }}>No lifecycle transitions recorded yet.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table" style={{ width: '100%', fontSize: '0.76rem' }}>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Action</th>
                  <th>State Transition</th>
                  <th>Authenticated Actor</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {auditEvents.map((ev) => (
                  <tr key={ev.id}>
                    <td style={{ whiteSpace: 'nowrap', color: '#94a3b8' }}>
                      {formatCollectionTimestamp(ev.created_at)}
                    </td>
                    <td>
                      <code style={{ color: '#38bdf8' }}>{ev.action}</code>
                    </td>
                    <td>
                      {(ev.previous_lifecycle_state || ev.previous_status || 'initial')} →{' '}
                      <strong>{ev.new_lifecycle_state || ev.new_status}</strong>
                    </td>
                    <td>
                      {ev.actor_username ? (
                        <span>
                          <strong>{ev.actor_username}</strong> ({ev.actor_role || 'OPERATOR'})
                        </span>
                      ) : (
                        <span style={{ color: '#64748b' }}>system</span>
                      )}
                    </td>
                    <td style={{ color: '#cbd5e1' }}>{ev.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
