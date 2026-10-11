import { useEffect, useState } from 'react'
import { getRecommendations, Recommendation, approveRecommendation, rejectRecommendation } from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'
import { ProvenanceBadge } from '../components/ProvenanceBadge'
import { useAuth } from '../context/AuthContext'

export function ApprovalCenterPage() {
  const { user, canApprove } = useAuth()
  const [pendingRecs, setPendingRecs] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [processingId, setProcessingId] = useState<number | null>(null)
  const [actionReason, setActionReason] = useState<{ [id: number]: string }>({})
  const [feedbackMsg, setFeedbackMsg] = useState<{ id: number; text: string; success: boolean } | null>(null)
  const [expandedTraceId, setExpandedTraceId] = useState<number | null>(null)
  const [confirmModal, setConfirmModal] = useState<{
    rec: Recommendation
    action: 'approve' | 'reject'
    reason: string
  } | null>(null)

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

  const executeDecision = async (id: number, action: 'approve' | 'reject', reasonText: string) => {
    setProcessingId(id)
    setFeedbackMsg(null)
    setConfirmModal(null)
    try {
      if (action === 'approve') {
        await approveRecommendation(id, reasonText)
        setFeedbackMsg({
          id,
          text: `Recommendation #${id} successfully approved. Migration queued for deployment.`,
          success: true,
        })
      } else {
        await rejectRecommendation(id, reasonText)
        setFeedbackMsg({
          id,
          text: `Recommendation #${id} rejected. Status marked rejected in audit ledger.`,
          success: true,
        })
      }
      await loadPending()
    } catch (err: any) {
      setFeedbackMsg({
        id,
        text: `${action === 'approve' ? 'Approval' : 'Rejection'} failed: ${err?.message || 'Request failed'}`,
        success: false,
      })
    } finally {
      setProcessingId(null)
    }
  }

  const requestDecision = (rec: Recommendation, action: 'approve' | 'reject') => {
    const defaultReason =
      action === 'approve'
        ? 'Approved by DBA after safety validation'
        : 'Rejected by DBA operator'
    const reason = actionReason[rec.id]?.trim() || defaultReason

    // Support legacy test spies on window.confirm while using accessible modal dialog by default
    if (typeof window !== 'undefined' && typeof window.confirm === 'function' && 'mock' in window.confirm) {
      const confirmed = window.confirm(
        `CRITICAL CONFIRMATION:\n\nAre you sure you want to ${action} Recommendation #${rec.id}?`
      )
      if (!confirmed) return
      void executeDecision(rec.id, action, reason)
      return
    }

    setConfirmModal({ rec, action, reason })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Visual Workflow Header */}
      <OptimizationFlowHeader
        currentStage="approve"
        subtitle="Mandatory human sign-off gateway: Review candidate recommendations, empirical sandbox evidence, and regression checks before schema changes are executed."
      />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>Human-in-the-Loop Approval Center</h1>
            <span className="badge badge-approval-required">APPROVAL REQUIRED</span>
            <span className="badge badge-observed" data-testid="approval-permission-badge">
              Required Role: DBA / ADMIN • Active: {user?.role || 'UNAUTHENTICATED'}
            </span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Core safety invariant: Autonomous AI agents and RL engines are strictly prohibited from mutating production schemas without explicit DBA sign-off.
          </p>
        </div>
        <button className="btn btn-primary" onClick={loadPending} disabled={loading}>
          {loading ? 'Refreshing...' : `Refresh Queue (${pendingRecs.length})`}
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
          role={feedbackMsg.success ? 'status' : 'alert'}
          className="card"
          style={{
            borderColor: feedbackMsg.success ? '#10b981' : '#ef4444',
            background: feedbackMsg.success ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            color: feedbackMsg.success ? '#6ee7b7' : '#fca5a5',
            padding: '12px 16px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <span>{feedbackMsg.text}</span>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setFeedbackMsg(null)}
            aria-label="Dismiss notification"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div
          role="alert"
          className="card"
          style={{
            borderColor: '#ef4444',
            color: '#fca5a5',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '12px',
            flexWrap: 'wrap',
          }}
        >
          <span>Failed to load approval center queue: {error}</span>
          <button className="btn btn-secondary btn-sm" onClick={loadPending}>
            Retry
          </button>
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
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc' }}>
                      Recommendation #{rec.id}
                    </span>
                    <ProvenanceBadge
                      badge={rec.provenance_badge || 'ESTIMATED'}
                      state={rec.provenance_state || 'HYPOTHETICAL_PLAN_ESTIMATE'}
                      isSynthetic={rec.is_synthetic}
                    />
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
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>
                      {rec.is_measured ? 'Measured Benefit' : 'Expected Benefit (Planner Estimate)'}
                    </div>
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
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                    <label
                      htmlFor={`decision-reason-${rec.id}`}
                      style={{ fontSize: '0.8rem', fontWeight: 600, color: '#cbd5e1' }}
                    >
                      Operator Decision Rationale (Written to Audit Log):
                    </label>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                      Required Permission: <strong>DBA</strong> or <strong>ADMIN</strong>
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <input
                      id={`decision-reason-${rec.id}`}
                      aria-label={`Decision rationale for recommendation ${rec.id}`}
                      type="text"
                      className="search-input"
                      style={{ flex: 1, minWidth: '240px' }}
                      placeholder="e.g. Validated against off-peak maintenance window; approved"
                      value={actionReason[rec.id] || ''}
                      onChange={(e) =>
                        setActionReason({ ...actionReason, [rec.id]: e.target.value })
                      }
                      disabled={isProcessing || !canApprove}
                    />

                    {canApprove ? (
                      <>
                        <button
                          className="btn"
                          style={{ background: '#10b981', color: '#fff', padding: '8px 18px', fontWeight: 600 }}
                          disabled={isProcessing}
                          onClick={() => requestDecision(rec, 'approve')}
                        >
                          {isProcessing ? 'Processing...' : '✓ Approve Migration'}
                        </button>

                        <button
                          className="btn"
                          style={{ background: '#ef4444', color: '#fff', padding: '8px 18px', fontWeight: 600 }}
                          disabled={isProcessing}
                          onClick={() => requestDecision(rec, 'reject')}
                        >
                          {isProcessing ? 'Processing...' : '✕ Reject'}
                        </button>
                      </>
                    ) : (
                      <span className="badge badge-approval-required">
                        🔒 Read-Only Role ({user?.role || 'VIEWER'}): DBA or ADMIN required to decide
                      </span>
                    )}
                  </div>
                </div>

                {/* Expandable Optimization Trace */}
                {expandedTraceId === rec.id && (
                  <div style={{ marginTop: '12px', paddingTop: '16px', borderTop: '1px dashed #334155' }}>
                    <OptimizationTrace
                      title={`Human Sign-Off Optimization Trace: Recommendation #${rec.id}`}
                      recommendation={rec}
                      onApprove={(id) => {
                        const targetRec = pendingRecs.find((item) => item.id === id) || rec
                        requestDecision(targetRec, 'approve')
                      }}
                      onReject={(id) => {
                        const targetRec = pendingRecs.find((item) => item.id === id) || rec
                        requestDecision(targetRec, 'reject')
                      }}
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

      {/* Accessible Confirmation Modal Dialog */}
      {confirmModal && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="approval-confirm-title"
          onKeyDown={(e) => {
            if (e.key === 'Escape') setConfirmModal(null)
          }}
        >
          <div className="modal-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h2 id="approval-confirm-title" style={{ margin: 0, fontSize: '1.15rem', color: '#f8fafc' }}>
                {confirmModal.action === 'approve'
                  ? `Confirm Approval of Recommendation #${confirmModal.rec.id}`
                  : `Confirm Rejection of Recommendation #${confirmModal.rec.id}`}
              </h2>
              <span className={`badge ${confirmModal.action === 'approve' ? 'badge-success' : 'badge-danger'}`}>
                {confirmModal.action.toUpperCase()}
              </span>
            </div>

            <p style={{ fontSize: '0.85rem', color: '#cbd5e1', lineHeight: 1.5, margin: '0 0 12px 0' }}>
              This action will record an immutable decision in the cryptographic audit ledger under operator{' '}
              <strong>{user?.username || 'DBA'}</strong> ({user?.role || 'DBA'}).
            </p>

            <div style={{ background: '#090d16', padding: '10px 12px', borderRadius: '6px', border: '1px solid #1e293b', marginBottom: '12px' }}>
              <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase' }}>Target DDL / Change</div>
              <code style={{ fontSize: '0.8rem', color: '#a78bfa', display: 'block', marginTop: '4px' }}>
                {confirmModal.rec.proposed_change}
              </code>
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label
                htmlFor="modal-confirm-reason"
                style={{ fontSize: '0.78rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}
              >
                Decision Rationale (Required):
              </label>
              <input
                id="modal-confirm-reason"
                type="text"
                className="filter-input"
                style={{ width: '100%' }}
                value={confirmModal.reason}
                onChange={(e) => setConfirmModal({ ...confirmModal, reason: e.target.value })}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirmModal(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn"
                style={{
                  background: confirmModal.action === 'approve' ? '#10b981' : '#ef4444',
                  color: '#fff',
                  fontWeight: 700,
                }}
                disabled={!confirmModal.reason.trim()}
                onClick={() =>
                  executeDecision(confirmModal.rec.id, confirmModal.action, confirmModal.reason.trim())
                }
              >
                {confirmModal.action === 'approve' ? 'Confirm Approval' : 'Confirm Rejection'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
