import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  acknowledgeWorkloadAlert,
  createAlertRule,
  evaluateWorkloadAlerts,
  exportWorkloadAlerts,
  getAlertAuditHistory,
  getAlertRules,
  getWorkloadAlertDetail,
  getWorkloadAlerts,
  resolveWorkloadAlert,
  updateAlertRule,
  type AlertAuditEventItem,
  type SupportedAlertMetricInfo,
  type WorkloadAlertItem,
  type WorkloadAlertRuleItem,
  type WorkloadAlertsListResponse,
} from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { ProvenanceBadge } from '../components/ProvenanceBadge'

type AlertsTab = 'alerts' | 'rules' | 'diagnostics' | 'audit'

export function WorkloadAlertsPage() {
  const { user, hasMinRole } = useAuth()
  const userRole = user?.role ?? 'VIEWER'
  const canAckOrResolveOrExport = hasMinRole('ANALYST')
  const canConfigureRules = hasMinRole('DBA')

  const [activeTab, setActiveTab] = useState<AlertsTab>('alerts')
  const [alertsData, setAlertsData] = useState<WorkloadAlertsListResponse | null>(null)
  const [rules, setRules] = useState<WorkloadAlertRuleItem[]>([])
  const [supportedMetrics, setSupportedMetrics] = useState<Record<string, SupportedAlertMetricInfo>>({})
  const [auditEvents, setAuditEvents] = useState<AlertAuditEventItem[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [severityFilter, setSeverityFilter] = useState<string>('')
  const [metricFilter, setMetricFilter] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [page, setPage] = useState<number>(1)
  const pageSize = 15

  // Selected Alert Drawer/Detail
  const [selectedAlert, setSelectedAlert] = useState<WorkloadAlertItem | null>(null)
  const [actionNote, setActionNote] = useState<string>('')
  const [submittingAction, setSubmittingAction] = useState<boolean>(false)

  // New Rule Form
  const [showNewRuleForm, setShowNewRuleForm] = useState<boolean>(false)
  const [newRuleName, setNewRuleName] = useState<string>('')
  const [newRuleMetric, setNewRuleMetric] = useState<string>('mean_exec_time_ms')
  const [newRuleScope, setNewRuleScope] = useState<string>('query')
  const [newRuleOperator, setNewRuleOperator] = useState<string>('pct_increase')
  const [newRuleThreshold, setNewRuleThreshold] = useState<number>(40)
  const [newRuleMinAbs, setNewRuleMinAbs] = useState<number>(20)
  const [newRuleMinSamples, setNewRuleMinSamples] = useState<number>(3)
  const [newRuleConsecutive, setNewRuleConsecutive] = useState<number>(2)
  const [newRuleAllowSingle, setNewRuleAllowSingle] = useState<boolean>(false)
  const [newRuleCooldown, setNewRuleCooldown] = useState<number>(1800)
  const [newRuleSeverity, setNewRuleSeverity] = useState<string>('high')

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [alertsRes, rulesRes, auditRes] = await Promise.all([
        getWorkloadAlerts({
          status: statusFilter || undefined,
          severity: severityFilter || undefined,
          metric_name: metricFilter || undefined,
          search: searchQuery || undefined,
          page,
          page_size: pageSize,
          evaluate_now: true,
        }),
        getAlertRules(false),
        getAlertAuditHistory({ page: 1, page_size: 40 }),
      ])
      setAlertsData(alertsRes)
      setRules(rulesRes.items)
      setSupportedMetrics(rulesRes.supported_metrics || alertsRes.diagnostics.supported_metrics || {})
      setAuditEvents(auditRes.items)

      if (selectedAlert) {
        try {
          const refreshed = await getWorkloadAlertDetail(selectedAlert.id)
          setSelectedAlert(refreshed)
        } catch {
          // ignore if alert no longer matches
        }
      } else if (alertsRes.items.length > 0) {
        const firstDetail = await getWorkloadAlertDetail(alertsRes.items[0].id)
        setSelectedAlert(firstDetail)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workload regression alerts')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [statusFilter, severityFilter, metricFilter, page])

  const handleSelectAlert = async (alertId: number) => {
    try {
      const detail = await getWorkloadAlertDetail(alertId)
      setSelectedAlert(detail)
      setActionNote('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load alert details')
    }
  }

  const handleEvaluateNow = async () => {
    if (!canAckOrResolveOrExport) return
    setLoading(true)
    setFeedback(null)
    setError(null)
    try {
      const res = await evaluateWorkloadAlerts()
      setFeedback(
        `Evaluated ${res.rules_evaluated} deterministic rules: ${res.triggered_count} triggered, ${res.deduplicated_count} deduplicated, ${res.auto_resolved_count} auto-resolved.`,
      )
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rule evaluation failed')
    } finally {
      setLoading(false)
    }
  }

  const handleAcknowledge = async () => {
    if (!selectedAlert || !canAckOrResolveOrExport) return
    const note = actionNote.trim() || 'Acknowledged by operator for investigation.'
    setSubmittingAction(true)
    setError(null)
    try {
      const updated = await acknowledgeWorkloadAlert(selectedAlert.id, note)
      setSelectedAlert(updated)
      setActionNote('')
      setFeedback(`Alert #${updated.id} acknowledged.`)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to acknowledge alert')
    } finally {
      setSubmittingAction(false)
    }
  }

  const handleResolve = async () => {
    if (!selectedAlert || !canAckOrResolveOrExport) return
    const note = actionNote.trim() || 'Resolved after root-cause verification.'
    setSubmittingAction(true)
    setError(null)
    try {
      const updated = await resolveWorkloadAlert(selectedAlert.id, note)
      setSelectedAlert(updated)
      setActionNote('')
      setFeedback(`Alert #${updated.id} marked resolved.`)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resolve alert')
    } finally {
      setSubmittingAction(false)
    }
  }

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canConfigureRules) return
    setError(null)
    try {
      await createAlertRule({
        name: newRuleName.trim(),
        metric_name: newRuleMetric,
        scope: newRuleScope,
        comparison_operator: newRuleOperator,
        threshold_value: Number(newRuleThreshold),
        min_absolute_value: Number(newRuleMinAbs),
        min_baseline_samples: Number(newRuleMinSamples),
        min_comparison_samples: newRuleAllowSingle ? 1 : Number(newRuleConsecutive),
        consecutive_breaches_required: newRuleAllowSingle ? 1 : Number(newRuleConsecutive),
        allow_single_measurement: newRuleAllowSingle,
        cooldown_seconds: Number(newRuleCooldown),
        severity: newRuleSeverity,
        enabled: true,
      })
      setShowNewRuleForm(false)
      setNewRuleName('')
      setFeedback('Created deterministic regression alert rule.')
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create alert rule')
    }
  }

  const handleToggleRule = async (rule: WorkloadAlertRuleItem) => {
    if (!canConfigureRules) return
    try {
      await updateAlertRule(rule.id, { enabled: !rule.enabled })
      setFeedback(`Rule "${rule.name}" ${!rule.enabled ? 'enabled' : 'disabled'}.`)
      await loadData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update rule state')
    }
  }

  const handleExport = async (format: 'json' | 'csv') => {
    if (!canAckOrResolveOrExport) return
    try {
      const content = await exportWorkloadAlerts(format, statusFilter || undefined)
      const blob = new Blob([content], {
        type: format === 'csv' ? 'text/csv;charset=utf-8;' : 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `dbzenith-workload-alerts.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed')
    }
  }

  const counts = alertsData?.status_counts ?? { active: 0, acknowledged: 0, resolved: 0, total: 0 }
  const diag = alertsData?.diagnostics

  return (
    <div className="space-y-6" data-testid="workload-alerts-page">
      {/* Header */}
      <div className="card" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '16px', alignItems: 'center' }}>
          <div>
            <h1 style={{ fontSize: '22px', fontWeight: 700, margin: 0 }}>
              Configurable Workload Regression Alerts
            </h1>
            <p style={{ margin: '6px 0 0', fontSize: '13px', color: '#94a3b8' }}>
              Deterministic baseline-versus-comparison regression monitoring with multi-sample noise suppression, deduplication, cooldowns, and automatic recovery.
            </p>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <button
              type="button"
              onClick={() => void loadData()}
              disabled={loading}
              className="btn"
            >
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>

            <button
              type="button"
              onClick={() => void handleEvaluateNow()}
              disabled={!canAckOrResolveOrExport || loading}
              title={
                canAckOrResolveOrExport
                  ? 'Evaluate all active deterministic rules now'
                  : 'Requires ANALYST, DBA, or ADMIN role'
              }
              className="btn btn-primary"
            >
              Evaluate Rules Now
            </button>

            <button
              type="button"
              onClick={() => void handleExport('csv')}
              disabled={!canAckOrResolveOrExport}
              className="btn"
            >
              Export CSV
            </button>
            <button
              type="button"
              onClick={() => void handleExport('json')}
              disabled={!canAckOrResolveOrExport}
              className="btn"
            >
              Export JSON
            </button>
          </div>
        </div>
      </div>

      {/* Deterministic Policy Banner */}
      <div
        className="card"
        style={{
          padding: '12px 16px',
          borderLeft: '4px solid #38bdf8',
          fontSize: '12px',
          color: '#cbd5e1',
        }}
      >
        <strong>Deterministic Rule Engine:</strong> Alerts require a minimum historical baseline sample count and consecutive breach verification (unless single-sample triggering is explicitly enabled) with automatic deduplication and post-resolution cooldown windows.
      </div>

      {feedback && (
        <div
          className="card"
          style={{
            padding: '12px 16px',
            borderLeft: '4px solid #10b981',
            background: 'rgba(16, 185, 129, 0.12)',
            fontSize: '13px',
            color: '#6ee7b7',
          }}
        >
          {feedback}
        </div>
      )}

      {error && (
        <div
          className="card"
          style={{
            padding: '12px 16px',
            borderLeft: '4px solid #ef4444',
            background: 'rgba(239, 68, 68, 0.12)',
            fontSize: '13px',
            color: '#fca5a5',
          }}
        >
          {error}
        </div>
      )}

      {/* Status Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '14px',
        }}
      >
        <button
          type="button"
          onClick={() => {
            setStatusFilter('active')
            setActiveTab('alerts')
            setPage(1)
          }}
          className="card"
          style={{ padding: '16px', textAlign: 'left', cursor: 'pointer' }}
        >
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Active Regressions</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px', color: '#f87171' }}>
            {counts.active}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Unacknowledged threshold breaches
          </div>
        </button>

        <button
          type="button"
          onClick={() => {
            setStatusFilter('acknowledged')
            setActiveTab('alerts')
            setPage(1)
          }}
          className="card"
          style={{ padding: '16px', textAlign: 'left', cursor: 'pointer' }}
        >
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Acknowledged</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px', color: '#fbbf24' }}>
            {counts.acknowledged}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Under DBA / Analyst investigation
          </div>
        </button>

        <button
          type="button"
          onClick={() => {
            setStatusFilter('resolved')
            setActiveTab('alerts')
            setPage(1)
          }}
          className="card"
          style={{ padding: '16px', textAlign: 'left', cursor: 'pointer' }}
        >
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Resolved / Recovered</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px', color: '#34d399' }}>
            {counts.resolved}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Auto-recovered or manually closed
          </div>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('rules')}
          className="card"
          style={{ padding: '16px', textAlign: 'left', cursor: 'pointer' }}
        >
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Configured Alert Rules</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px', color: '#38bdf8' }}>
            {rules.length}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            {rules.filter((r) => r.enabled).length} enabled · {Object.keys(supportedMetrics).length} supported metrics
          </div>
        </button>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', borderBottom: '1px solid #1e293b', paddingBottom: '12px' }}>
        <button
          type="button"
          onClick={() => setActiveTab('alerts')}
          className={activeTab === 'alerts' ? 'btn btn-primary' : 'btn'}
        >
          Regression Alerts ({counts.total})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('rules')}
          className={activeTab === 'rules' ? 'btn btn-primary' : 'btn'}
        >
          Configured Threshold Rules ({rules.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('diagnostics')}
          className={activeTab === 'diagnostics' ? 'btn btn-primary' : 'btn'}
        >
          Insufficient History & Noise Suppression (
          {(diag?.insufficient_history.length ?? 0) + (diag?.suppressed_evaluations.length ?? 0)})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('audit')}
          className={activeTab === 'audit' ? 'btn btn-primary' : 'btn'}
        >
          Alert Audit History ({auditEvents.length})
        </button>
      </div>

      {/* Tab 1: Alerts List + Detail Panel */}
      {activeTab === 'alerts' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Filter Bar */}
          <div
            className="card"
            style={{ padding: '14px', display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center' }}
          >
            <select
              aria-label="Filter alerts by status"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value)
                setPage(1)
              }}
              style={{ padding: '6px 10px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
            >
              <option value="">All States (Active / Ack / Resolved)</option>
              <option value="active">Active</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
            </select>
            <select
              aria-label="Filter alerts by severity"
              value={severityFilter}
              onChange={(e) => {
                setSeverityFilter(e.target.value)
                setPage(1)
              }}
              style={{ padding: '6px 10px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
            >
              <option value="">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
            <select
              aria-label="Filter alerts by metric"
              value={metricFilter}
              onChange={(e) => {
                setMetricFilter(e.target.value)
                setPage(1)
              }}
              style={{ padding: '6px 10px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
            >
              <option value="">All Supported Metrics</option>
              {Object.keys(supportedMetrics).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  setPage(1)
                  void loadData()
                }
              }}
              placeholder="Search query fingerprint, title, or summary..."
              style={{ flex: 1, minWidth: '200px', padding: '6px 10px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
            />
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
              gap: '16px',
            }}
          >
            {/* Left Column: Alert List */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {!alertsData?.items.length ? (
                <div className="card" style={{ padding: '28px', textAlign: 'center', color: '#94a3b8' }}>
                  No workload regression alerts match the current filter criteria.
                </div>
              ) : (
                alertsData.items.map((alert) => (
                  <button
                    key={alert.id}
                    type="button"
                    onClick={() => void handleSelectAlert(alert.id)}
                    className="card"
                    style={{
                      padding: '16px',
                      textAlign: 'left',
                      cursor: 'pointer',
                      border:
                        selectedAlert?.id === alert.id
                          ? '1px solid #38bdf8'
                          : '1px solid rgba(148, 163, 184, 0.15)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
                      <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <span
                          className="badge"
                          style={{
                            textTransform: 'uppercase',
                            background:
                              alert.status === 'active'
                                ? 'rgba(239, 68, 68, 0.2)'
                                : alert.status === 'acknowledged'
                                ? 'rgba(245, 158, 11, 0.2)'
                                : 'rgba(16, 185, 129, 0.2)',
                            color:
                              alert.status === 'active'
                                ? '#fca5a5'
                                : alert.status === 'acknowledged'
                                ? '#fde68a'
                                : '#6ee7b7',
                          }}
                        >
                          {alert.status}
                        </span>
                        <span className="badge" style={{ textTransform: 'uppercase' }}>
                          {alert.severity}
                        </span>
                        <code style={{ fontSize: '12px', color: '#38bdf8' }}>{alert.metric_name}</code>
                      </div>
                      <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                        Occurrences: <strong>{alert.occurrence_count}</strong> · Consecutive: <strong>{alert.consecutive_breaches}</strong>
                      </span>
                    </div>

                    <div style={{ fontWeight: 700, fontSize: '14px', marginBottom: '4px' }}>
                      {alert.title}
                    </div>
                    <p style={{ margin: 0, fontSize: '12px', color: '#94a3b8' }}>{alert.summary}</p>

                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px', fontSize: '11px', color: '#94a3b8' }}>
                      <span>
                        Baseline: <strong>{alert.baseline_value}</strong> → Current: <strong style={{ color: '#fca5a5' }}>{alert.current_value}</strong>
                        {alert.deviation_pct != null && ` (${alert.deviation_pct >= 0 ? '+' : ''}${alert.deviation_pct}%)`}
                      </span>
                      <span>
                        Last observed: {alert.last_observed_at ? new Date(alert.last_observed_at).toLocaleString() : 'N/A'}
                      </span>
                    </div>
                  </button>
                ))
              )}
            </div>

            {/* Right Column: Selected Alert Detail & Lifecycle Actions */}
            <div>
              {selectedAlert ? (
                <div className="card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <code style={{ fontSize: '12px', color: '#94a3b8' }}>Alert #{selectedAlert.id}</code>
                      <ProvenanceBadge
                        state={selectedAlert.provenance_state}
                        isSynthetic={selectedAlert.is_synthetic}
                      />
                    </div>
                    <h2 style={{ margin: '6px 0 0', fontSize: '16px', fontWeight: 700 }}>
                      {selectedAlert.title}
                    </h2>
                  </div>

                  <p style={{ margin: 0, fontSize: '12px', color: '#cbd5e1', lineHeight: 1.5 }}>
                    {selectedAlert.summary}
                  </p>

                  {/* Evidence Metrics Grid */}
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1fr 1fr',
                      gap: '10px',
                      padding: '12px',
                      background: 'rgba(15, 23, 42, 0.6)',
                      borderRadius: '8px',
                      fontSize: '12px',
                    }}
                  >
                    <div>
                      <div style={{ color: '#94a3b8' }}>Started At:</div>
                      <strong>
                        {selectedAlert.started_at ? new Date(selectedAlert.started_at).toLocaleString() : 'N/A'}
                      </strong>
                    </div>
                    <div>
                      <div style={{ color: '#94a3b8' }}>Last Observed At:</div>
                      <strong>
                        {selectedAlert.last_observed_at ? new Date(selectedAlert.last_observed_at).toLocaleString() : 'N/A'}
                      </strong>
                    </div>
                    <div>
                      <div style={{ color: '#94a3b8' }}>Baseline vs Current:</div>
                      <strong>
                        {selectedAlert.baseline_value} → <span style={{ color: '#fca5a5' }}>{selectedAlert.current_value}</span>
                      </strong>
                    </div>
                    <div>
                      <div style={{ color: '#94a3b8' }}>Samples (Base / Breach):</div>
                      <strong>
                        {selectedAlert.baseline_sample_count} baseline / {selectedAlert.consecutive_breaches} consecutive
                      </strong>
                    </div>
                  </div>

                  {/* Affected Query Fingerprints */}
                  {selectedAlert.affected_query_fingerprints.length > 0 && (
                    <div style={{ fontSize: '12px' }}>
                      <strong>Affected Query Fingerprints:</strong>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                        {selectedAlert.affected_query_fingerprints.map((qf, idx) => (
                          <div
                            key={idx}
                            style={{ padding: '8px', background: '#090d16', borderRadius: '6px' }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              {qf.query_id ? (
                                <Link
                                  to={`/queries?queryId=${qf.query_id}`}
                                  style={{ color: '#38bdf8', fontFamily: 'monospace', fontWeight: 600 }}
                                >
                                  {qf.query_fingerprint} (Query #{qf.query_id})
                                </Link>
                              ) : (
                                <code>{qf.query_fingerprint}</code>
                              )}
                              {qf.mean_exec_time_ms != null && (
                                <span style={{ color: '#94a3b8' }}>{qf.mean_exec_time_ms} ms mean</span>
                              )}
                            </div>
                            {qf.normalized_query && (
                              <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                                <code>{qf.normalized_query}</code>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Acknowledge / Resolve Actions */}
                  {selectedAlert.status !== 'resolved' && (
                    <div style={{ borderTop: '1px solid #1e293b', paddingTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <label style={{ fontSize: '12px', fontWeight: 600 }}>
                        Acknowledgment / Resolution Reason:
                      </label>
                      <textarea
                        rows={2}
                        value={actionNote}
                        onChange={(e) => setActionNote(e.target.value)}
                        placeholder="Document investigation note or resolution root cause..."
                        style={{ width: '100%', padding: '8px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
                      />
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {selectedAlert.status === 'active' && (
                          <button
                            type="button"
                            disabled={!canAckOrResolveOrExport || submittingAction}
                            onClick={() => void handleAcknowledge()}
                            className="btn"
                          >
                            Acknowledge Alert
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={!canAckOrResolveOrExport || submittingAction}
                          onClick={() => void handleResolve()}
                          className="btn btn-primary"
                        >
                          Resolve Alert
                        </button>
                      </div>
                      {!canAckOrResolveOrExport && (
                        <div style={{ fontSize: '11px', color: '#fde68a' }}>
                          Your current role ({userRole}) is read-only. ANALYST, DBA, or ADMIN role is required to acknowledge or resolve alerts.
                        </div>
                      )}
                    </div>
                  )}

                  {/* Audit Trail for Selected Alert */}
                  {selectedAlert.audit_history && selectedAlert.audit_history.length > 0 && (
                    <div style={{ borderTop: '1px solid #1e293b', paddingTop: '12px' }}>
                      <div style={{ fontSize: '12px', fontWeight: 700, marginBottom: '8px' }}>
                        Alert Lifecycle History ({selectedAlert.audit_history.length})
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {selectedAlert.audit_history.map((ev) => (
                          <div
                            key={ev.id}
                            style={{ padding: '8px', background: '#090d16', borderRadius: '6px', fontSize: '11px' }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <strong style={{ color: '#38bdf8', textTransform: 'uppercase' }}>{ev.action}</strong>
                              <span>
                                {ev.actor_username} ({ev.actor_role})
                              </span>
                            </div>
                            {ev.reason && <div style={{ color: '#94a3b8', marginTop: '2px' }}>{ev.reason}</div>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="card" style={{ padding: '28px', textAlign: 'center', color: '#94a3b8', fontSize: '12px' }}>
                  Select an alert on the left to inspect its baseline evidence, affected query fingerprints, and acknowledgment/resolution history.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Deterministic Alert Rules */}
      {activeTab === 'rules' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 700 }}>
              Configured Deterministic Regression Threshold Rules
            </h2>
            <button
              type="button"
              disabled={!canConfigureRules}
              onClick={() => setShowNewRuleForm((v) => !v)}
              title={canConfigureRules ? 'Create new alert rule' : 'Requires DBA or ADMIN role'}
              className="btn btn-primary"
            >
              New Threshold Rule
            </button>
          </div>

          {!canConfigureRules && (
            <div className="card" style={{ padding: '12px 16px', borderLeft: '4px solid #f59e0b', fontSize: '12px', color: '#fde68a' }}>
              Configuring or modifying alert threshold rules requires <strong>DBA</strong> or <strong>ADMIN</strong> privileges (current role: {userRole}).
            </div>
          )}

          {showNewRuleForm && canConfigureRules && (
            <form
              onSubmit={handleCreateRule}
              className="card"
              style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '12px' }}
            >
              <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 700 }}>
                Create Deterministic Regression Alert Rule
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px' }}>
                <div>
                  <label>Rule Name</label>
                  <input
                    type="text"
                    required
                    value={newRuleName}
                    onChange={(e) => setNewRuleName(e.target.value)}
                    placeholder="e.g., Critical Query Mean Latency Spike"
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  />
                </div>
                <div>
                  <label>Supported Metric</label>
                  <select
                    value={newRuleMetric}
                    onChange={(e) => setNewRuleMetric(e.target.value)}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  >
                    {Object.entries(supportedMetrics).map(([k, info]) => (
                      <option key={k} value={k}>
                        {k} ({info.unit})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label>Comparison Operator</label>
                  <select
                    value={newRuleOperator}
                    onChange={(e) => setNewRuleOperator(e.target.value)}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  >
                    <option value="pct_increase">pct_increase (% above baseline)</option>
                    <option value="abs_above">abs_above (absolute value &gt;= threshold)</option>
                    <option value="pct_decrease">pct_decrease (% drop below baseline)</option>
                  </select>
                </div>
                <div>
                  <label>Threshold Value</label>
                  <input
                    type="number"
                    step="0.1"
                    required
                    value={newRuleThreshold}
                    onChange={(e) => setNewRuleThreshold(Number(e.target.value))}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  />
                </div>
                <div>
                  <label>Min Baseline Samples</label>
                  <input
                    type="number"
                    min={1}
                    required
                    value={newRuleMinSamples}
                    onChange={(e) => setNewRuleMinSamples(Number(e.target.value))}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  />
                </div>
                <div>
                  <label>Consecutive Breaches Required</label>
                  <input
                    type="number"
                    min={1}
                    required
                    value={newRuleConsecutive}
                    onChange={(e) => setNewRuleConsecutive(Number(e.target.value))}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  />
                </div>
                <div>
                  <label>Cooldown Window (seconds)</label>
                  <input
                    type="number"
                    min={0}
                    required
                    value={newRuleCooldown}
                    onChange={(e) => setNewRuleCooldown(Number(e.target.value))}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  />
                </div>
                <div>
                  <label>Scope</label>
                  <select
                    value={newRuleScope}
                    onChange={(e) => setNewRuleScope(e.target.value)}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  >
                    <option value="query">query</option>
                    <option value="workload">workload</option>
                  </select>
                </div>
                <div>
                  <label>Severity</label>
                  <select
                    value={newRuleSeverity}
                    onChange={(e) => setNewRuleSeverity(e.target.value)}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  >
                    <option value="critical">critical</option>
                    <option value="high">high</option>
                    <option value="warning">warning</option>
                    <option value="info">info</option>
                  </select>
                </div>
                <div>
                  <label>Min Absolute Value</label>
                  <input
                    type="number"
                    step="0.1"
                    value={newRuleMinAbs}
                    onChange={(e) => setNewRuleMinAbs(Number(e.target.value))}
                    style={{ width: '100%', padding: '6px', marginTop: '4px' }}
                  />
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  id="allow-single"
                  type="checkbox"
                  checked={newRuleAllowSingle}
                  onChange={(e) => setNewRuleAllowSingle(e.target.checked)}
                />
                <label htmlFor="allow-single">
                  Explicitly allow single-measurement alert trigger
                </label>
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button type="button" onClick={() => setShowNewRuleForm(false)} className="btn">
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Save Rule
                </button>
              </div>
            </form>
          )}

          {rules.map((rule) => (
            <div
              key={rule.id}
              className="card"
              style={{ padding: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}
            >
              <div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <strong style={{ fontSize: '14px' }}>{rule.name}</strong>
                  <code style={{ fontSize: '12px', color: '#38bdf8' }}>{rule.metric_name}</code>
                  <span className="badge" style={{ textTransform: 'uppercase' }}>{rule.severity}</span>
                  <span className="badge">{rule.enabled ? 'ENABLED' : 'DISABLED'}</span>
                </div>
                <p style={{ margin: '4px 0', fontSize: '12px', color: '#94a3b8' }}>{rule.description}</p>
                <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                  <span>Operator: <strong>{rule.comparison_operator}</strong> (&gt;= {rule.threshold_value})</span>
                  <span>Min Baseline Samples: <strong>{rule.min_baseline_samples}</strong></span>
                  <span>Consecutive Breaches: <strong>{rule.consecutive_breaches_required}</strong></span>
                  <span>Cooldown: <strong>{rule.cooldown_seconds}s</strong></span>
                </div>
              </div>
              <button
                type="button"
                disabled={!canConfigureRules}
                onClick={() => void handleToggleRule(rule)}
                className="btn"
              >
                {rule.enabled ? 'Disable' : 'Enable'}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Tab 3: Diagnostics & Insufficient History */}
      {activeTab === 'diagnostics' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="card" style={{ padding: '18px' }} data-testid="insufficient-history-section">
            <h3 style={{ marginTop: 0, fontSize: '14px', fontWeight: 700, color: '#fbbf24' }}>
              Explicit Insufficient Baseline / Sample History ({diag?.insufficient_history.length ?? 0})
            </h3>
            {!diag?.insufficient_history.length ? (
              <p style={{ margin: 0, fontSize: '12px', color: '#94a3b8' }}>
                All evaluated query fingerprints and workload series meet their minimum baseline sample requirements.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {diag.insufficient_history.map((item, i) => (
                  <div key={i} style={{ padding: '10px', background: '#090d16', borderRadius: '6px', fontSize: '12px' }}>
                    <code style={{ color: '#fbbf24' }}>{String(item.reason_code)}</code> —{' '}
                    <strong>{String(item.rule_name)}</strong>: {String(item.detail)}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card" style={{ padding: '18px' }}>
            <h3 style={{ marginTop: 0, fontSize: '14px', fontWeight: 700, color: '#38bdf8' }}>
              Single Noisy Measurement & Cooldown Suppressions ({diag?.suppressed_evaluations.length ?? 0})
            </h3>
            {!diag?.suppressed_evaluations.length ? (
              <p style={{ margin: 0, fontSize: '12px', color: '#94a3b8' }}>
                No single-sample transient spikes or cooldown suppressions occurred in the latest evaluation cycle.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {diag.suppressed_evaluations.map((item, i) => (
                  <div key={i} style={{ padding: '10px', background: '#090d16', borderRadius: '6px', fontSize: '12px' }}>
                    <code style={{ color: '#38bdf8' }}>{String(item.reason_code)}</code> —{' '}
                    <strong>{String(item.rule_name)}</strong>: {String(item.detail)}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card" style={{ padding: '18px' }}>
            <h3 style={{ marginTop: 0, fontSize: '14px', fontWeight: 700 }}>
              Supported Deterministic Alert Metrics
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '10px', fontSize: '12px' }}>
              {Object.entries(supportedMetrics).map(([key, info]) => (
                <div key={key} style={{ padding: '10px', background: '#090d16', borderRadius: '6px' }}>
                  <code style={{ color: '#38bdf8', fontWeight: 700 }}>
                    {key} ({info.unit})
                  </code>
                  <div style={{ fontWeight: 600, marginTop: '4px' }}>{info.label}</div>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>{info.description}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Alert Audit History */}
      {activeTab === 'audit' && (
        <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
          <table className="table" style={{ width: '100%', fontSize: '12px' }}>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Action</th>
                <th>Alert / Rule</th>
                <th>State Transition</th>
                <th>Actor</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {auditEvents.map((ev) => (
                <tr key={ev.id}>
                  <td>{ev.created_at ? new Date(ev.created_at).toLocaleString() : 'N/A'}</td>
                  <td>
                    <code style={{ textTransform: 'uppercase', color: '#38bdf8' }}>{ev.action}</code>
                  </td>
                  <td>
                    {ev.alert_id ? `Alert #${ev.alert_id}` : ''} {ev.rule_id ? `(Rule #${ev.rule_id})` : ''}
                  </td>
                  <td>
                    {ev.previous_status ?? 'none'} → <strong>{ev.new_status ?? 'n/a'}</strong>
                  </td>
                  <td>
                    {ev.actor_username} ({ev.actor_role})
                  </td>
                  <td>{ev.reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
