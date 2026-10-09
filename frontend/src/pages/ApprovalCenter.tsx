import { useEffect, useState } from 'react'
import { getRecommendations, Recommendation, approveRecommendation, rejectRecommendation } from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'

export function ApprovalCenterPage() {
  const [pendingRecs, setPendingRecs] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [processingId, setProcessingId] = useState<number | null>(null)
  const [actionReason, setActionReason] = useState<{ [id: number]: string }>({})
  const [feedbackMsg, setFeedbackMsg] = useState<{ id: number; text: string; success: boolean } | null>(null)
  const [expandedTraceId, setExpandedTraceId] = useState<number | null>(null)

  const loadPending = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getRecommendations(1, 100, 'pending')
      // Only keep recommendations requiring approval
      const gated = (res.items || []).filter((r) => r.requires_approval)
      setPendingRecs(gated)
    } catch (err: any) {
      setError(err?.message || 'Failed to load approval queue')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPending()
  }, [])

  const handleApprove = async (id: number) => {
    const reason = actionReason[id]?.trim() || 'Approved by DBA after safety validation'
    const confirmed = window.confirm(
      `CRITICAL CONFIRMATION:\n\nAre you sure you want to approve Recommendation #${id}?\n\nThis will validate the migration queue and log an immutable audit event under your operator ID.`
    )
    if (!confirmed) return

    setProcessingId(id)
    setFeedbackMsg(null)
    try {
      await approveRecommendation(id, reason)
      setFeedbackMsg({ id, text: `Recommendation #${id} successfully approved. Migration queued for deployment.`, success: true })
      await loadPending()
    } catch (err: any) {
      setFeedbackMsg({ id, text: `Approval failed: ${err?.message}`, success: false })
    } finally {
      setProcessingId(null)
    }
  }

  const handleReject = async (id: number) => {
    const reason = actionReason[id]?.trim() || 'Rejected by DBA operator'
    const confirmed = window.confirm(
      `CONFIRMATION:\n\nAre you sure you want to reject Recommendation #${id}?\n\nStatus will be permanently marked as rejected in the audit trail.`
    )
    if (!confirmed) return

    setProcessingId(id)
    setFeedbackMsg(null)
    try {
      await rejectRecommendation(id, reason)
      setFeedbackMsg({ id, text: `Recommendation #${id} rejected. Status marked rejected.`, success: true })
      await loadPending()
    } catch (err: any) {
      setFeedbackMsg({ id, text: `Rejection failed: ${err?.message}`, success: false })
    } finally {
      setProcessingId(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Visual Workflow Header */}
      <OptimizationFlowHeader
        currentStage="approve"
        subtitle="Mandatory human sign-off gateway: Review candidate recommendations, empirical sandbox evidence, and regression checks before schema changes are executed."
      />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>Human-in-the-Loop Approval Center</h1>
            <span className="badge badge-approval-required">APPROVAL REQUIRED</span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Core safety invariant: Autonomous AI agents and RL engines are strictly prohibited from mutating production schemas without explicit DBA sign-off.
          </p>
        </div>
        <button className="btn btn-primary" onClick={loadPending}>
          Refresh Queue ({pendingRecs.length})
        </button>
      </div>

      {/* Human Gate Invariant Guide Banner */}
      <div className="guide-banner">
        <div className="guide-banner-icon">🛡️</div>
        <div className="guide-banner-content">
          <div className="guide-banner-title">
            <span>MANDATORY HUMAN APPROVAL GATEWAY & AUDIT LEDGER</span>
            <span className="badge badge-approval-required">HARD SAFETY INVARIANT</span>
          </div>
          <p className="guide-banner-desc">
            DBZenith strictly enforces that <strong>no autonomous AI agent or advisor may mutate production schemas without explicit DBA sign-off</strong>. Every approval requires an operator justification and is permanently stamped into the immutable cryptographic audit ledger.
          </p>
          <div className="guide-banner-pills">
            <span className="badge badge-success">✓ Zero Unattended DDL</span>
            <span className="badge badge-simulation">✓ Sandbox Evidence Checked</span>
            <span className="badge badge-ai-analysis">✓ Tamper-Evident Audit Logging</span>
          </div>
        </div>
      </div>

      {/* Action feedback message */}
      {feedbackMsg && (
        <div
          className="card"
          style={{
            borderColor: feedbackMsg.success ? '#10b981' : '#ef4444',
            background: feedbackMsg.success ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            color: feedbackMsg.success ? '#6ee7b7' : '#fca5a5',
            padding: '12px 16px',
          }}
        >
          {feedbackMsg.text}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="card" style={{ borderColor: '#ef4444', color: '#fca5a5' }}>
          Failed to load approval center queue: {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '40px', color: '#94a3b8' }}>
          Checking pending recommendations awaiting DBA operator sign-off...
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && pendingRecs.length === 0 && (
        <div className="card empty-state" style={{ padding: '48px', textAlign: 'center' }}>
          <div style={{ fontSize: '2rem', marginBottom: '8px' }}>✓</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 600, color: '#f8fafc' }}>Approval Queue Clear</div>
          <div style={{ color: '#94a3b8', marginTop: '4px', fontSize: '0.875rem' }}>
            There are currently no schema migrations or index changes awaiting DBA approval.
          </div>
        </div>
      )}

      {/* Pending Items Queue */}
      {!loading && !error && pendingRecs.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {pendingRecs.map((rec) => {
            const isProcessing = processingId === rec.id
            return (
              <div
                key={rec.id}
                className="card"
                style={{
                  padding: '20px',
                  borderLeft: '4px solid #f59e0b',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '14px',
                }}
              >
                {/* Header row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc' }}>
                      Recommendation #{rec.id}
                    </span>
                    <span className="badge" style={{ background: '#1e293b', color: '#38bdf8' }}>
                      {rec.type}
                    </span>
                    <span className="badge" style={{ background: '#090d16', border: '1px solid #334155', color: '#cbd5e1' }}>
                      Target: {rec.target}
                    </span>
                    <span className="badge badge-warning">AWAITING DBA DECISION</span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <button
                      className="btn btn-secondary"
                      style={{ fontSize: '0.75rem', padding: '4px 10px' }}
                      onClick={() => setExpandedTraceId(expandedTraceId === rec.id ? null : rec.id)}
                    >
                      {expandedTraceId === rec.id ? 'Hide Trace' : '🔍 Inspect Full Trace'}
                    </button>
                    <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                      Created: {new Date(rec.created_at).toLocaleString()}
                    </div>
                  </div>
                </div>

                {/* Proposed Change SQL */}
                <div>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase', marginBottom: '4px' }}>
                    Proposed Schema / Index Action
                  </div>
                  <pre
                    style={{
                      margin: 0,
                      background: '#090d16',
                      padding: '12px 16px',
                      borderRadius: '6px',
                      border: '1px solid #1e293b',
                      fontSize: '0.85rem',
                      fontFamily: 'monospace',
                      color: '#a78bfa',
                      overflowX: 'auto',
                    }}
                  >
                    {rec.proposed_change}
                  </pre>
                </div>

                {/* Details Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px' }}>
                  <div style={{ background: '#090d16', padding: '10px 14px', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Rationale</div>
                    <div style={{ fontSize: '0.85rem', color: '#e2e8f0', marginTop: '4px' }}>{rec.reason}</div>
                  </div>

                  <div style={{ background: '#090d16', padding: '10px 14px', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Expected Benefit</div>
                    <div style={{ fontSize: '0.85rem', color: '#34d399', marginTop: '4px', fontWeight: 500 }}>
                      {rec.expected_benefit}
                    </div>
                  </div>

                  <div style={{ background: '#090d16', padding: '10px 14px', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Risk & Confidence</div>
                    <div style={{ fontSize: '0.85rem', marginTop: '4px' }}>
                      <span style={{ color: rec.risk === 'low' ? '#10b981' : '#f59e0b', fontWeight: 600 }}>
                        {rec.risk.toUpperCase()} RISK
                      </span>
                      {' / '}
                      <span style={{ color: '#38bdf8' }}>{Math.round(rec.confidence * 100)}% Confidence</span>
                    </div>
                  </div>
                </div>

                {/* DBA Decision Input & Controls */}
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px',
                    paddingTop: '12px',
                    borderTop: '1px solid #1e293b',
                  }}
                >
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: '#cbd5e1' }}>
                    Operator Decision Rationale (Written to Audit Log):
                  </label>
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <input
                      type="text"
                      className="search-input"
                      style={{ flex: 1 }}
                      placeholder="e.g. Validated against off-peak maintenance window; approved"
                      value={actionReason[rec.id] || ''}
                      onChange={(e) =>
                        setActionReason({ ...actionReason, [rec.id]: e.target.value })
                      }
                      disabled={isProcessing}
                    />

                    <button
                      className="btn"
                      style={{ background: '#10b981', color: '#fff', padding: '8px 18px', fontWeight: 600 }}
                      disabled={isProcessing}
                      onClick={() => handleApprove(rec.id)}
                    >
                      {isProcessing ? 'Processing...' : '✓ Approve Migration'}
                    </button>

                    <button
                      className="btn"
                      style={{ background: '#ef4444', color: '#fff', padding: '8px 18px', fontWeight: 600 }}
                      disabled={isProcessing}
                      onClick={() => handleReject(rec.id)}
                    >
                      {isProcessing ? 'Processing...' : '✕ Reject'}
                    </button>
                  </div>
                </div>

                {/* Expandable Optimization Trace */}
                {expandedTraceId === rec.id && (
                  <div style={{ marginTop: '12px', paddingTop: '16px', borderTop: '1px dashed #334155' }}>
                    <OptimizationTrace
                      title={`Human Sign-Off Optimization Trace: Recommendation #${rec.id}`}
                      recommendation={rec}
                      onApprove={(id) => handleApprove(id)}
                      onReject={(id) => handleReject(id)}
                      isDeciding={processingId === rec.id}
                      initialExpanded={true}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
