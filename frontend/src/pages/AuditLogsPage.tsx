import { useEffect, useState } from 'react'
import {
  getAssistantAuditLogs,
  getRecommendationAuditEvents,
  RecommendationAuditEvent,
} from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'

type AssistantAuditItem = {
  timestamp: string
  session_id: string
  event_type: string
  tool_name?: string
  input_payload?: Record<string, unknown>
  output_summary?: string
  authorized: boolean
  security_flag?: string | null
}

export function AuditLogsPage() {
  const [tab, setTab] = useState<'recommendations' | 'assistant'>('recommendations')
  const [recEvents, setRecEvents] = useState<RecommendationAuditEvent[]>([])
  const [assistantEvents, setAssistantEvents] = useState<AssistantAuditItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterText, setFilterText] = useState('')

  const loadLogs = async () => {
    setLoading(true)
    setError(null)
    try {
      const [recs, asst] = await Promise.all([
        getRecommendationAuditEvents(),
        getAssistantAuditLogs(),
      ])
      setRecEvents(recs || [])
      setAssistantEvents(asst || [])
    } catch (err: any) {
      setError(err?.message || 'Failed to load audit logs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadLogs()
  }, [])

  const filteredRecEvents = recEvents.filter((r) => {
    if (!filterText.trim()) return true
    const q = filterText.toLowerCase()
    return (
      r.action.toLowerCase().includes(q) ||
      r.reason.toLowerCase().includes(q) ||
      String(r.recommendation_id).includes(q) ||
      r.new_status.toLowerCase().includes(q)
    )
  })

  const filteredAssistantEvents = assistantEvents.filter((a) => {
    if (!filterText.trim()) return true
    const q = filterText.toLowerCase()
    return (
      a.event_type.toLowerCase().includes(q) ||
      (a.tool_name && a.tool_name.toLowerCase().includes(q)) ||
      (a.output_summary && a.output_summary.toLowerCase().includes(q)) ||
      a.session_id.toLowerCase().includes(q)
    )
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Visual Workflow Header */}
      <OptimizationFlowHeader
        currentStage="audit"
        subtitle="Final verification step of the optimization lifecycle. Every recommendation change, sandbox test, approval decision, and assistant action is cryptographically and immutably recorded."
      />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>Security & Execution Audit Logs</h1>
            <span className="badge badge-observed">OBSERVED</span>
            <span className="badge badge-approval-required">AUDIT TRAIL</span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Immutable chronological ledger of recommendation approvals, rejections, tool calls, and security events.
          </p>
        </div>
        <button className="btn btn-primary" onClick={loadLogs}>
          Refresh Ledger
        </button>
      </div>

      {/* Filter / Search Bar */}
      <div className="card" style={{ padding: '14px', display: 'flex', gap: '12px', alignItems: 'center' }}>
        <input
          type="text"
          className="search-input"
          style={{ flex: 1 }}
          placeholder="Filter audit entries by action, tool name, recommendation ID, or reason..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
        />
        {filterText && (
          <button className="btn btn-secondary" style={{ fontSize: '0.75rem' }} onClick={() => setFilterText('')}>
            Clear
          </button>
        )}
      </div>

      {/* Tab Switcher */}
      <div className="subnav-tabs">
        <button
          className={`subnav-tab ${tab === 'recommendations' ? 'active' : ''}`}
          onClick={() => setTab('recommendations')}
        >
          Recommendation Decisions ({recEvents.length})
        </button>
        <button
          className={`subnav-tab ${tab === 'assistant' ? 'active' : ''}`}
          onClick={() => setTab('assistant')}
        >
          Assistant Tool Invocations & Security ({assistantEvents.length})
        </button>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '40px', color: '#94a3b8' }}>
          Querying audit database for decision and tool logs...
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="card" style={{ borderColor: '#ef4444', color: '#fca5a5' }}>
          Failed to load audit trail: {error}
        </div>
      )}

      {/* Table: Recommendation Decisions */}
      {!loading && !error && tab === 'recommendations' && (
        <div>
          {filteredRecEvents.length === 0 ? (
            <div className="card empty-state">No recommendation audit events match your filter.</div>
          ) : (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Rec ID</th>
                    <th>Action</th>
                    <th>Status Transition</th>
                    <th>Operator Reason</th>
                    <th>Metadata</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRecEvents.map((event) => (
                    <tr key={event.id}>
                      <td style={{ fontSize: '0.75rem', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                        {event.created_at ? new Date(event.created_at).toLocaleString() : 'N/A'}
                      </td>
                      <td style={{ fontWeight: 600, color: '#38bdf8' }}>#{event.recommendation_id}</td>
                      <td>
                        <span
                          className={`badge ${
                            event.action === 'approve'
                              ? 'badge-success'
                              : event.action === 'reject'
                              ? 'badge-danger'
                              : 'badge-warning'
                          }`}
                        >
                          {event.action.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ fontSize: '0.8rem' }}>
                        <span style={{ color: '#94a3b8' }}>{event.previous_status || 'none'}</span>
                        <span style={{ color: '#64748b', margin: '0 4px' }}>&rarr;</span>
                        <span style={{ fontWeight: 600, color: '#f8fafc' }}>{event.new_status}</span>
                      </td>
                      <td style={{ fontSize: '0.85rem', color: '#cbd5e1' }}>{event.reason}</td>
                      <td style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: '#64748b' }}>
                        {JSON.stringify(event.metadata)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Table: Assistant Tool Invocations */}
      {!loading && !error && tab === 'assistant' && (
        <div>
          {filteredAssistantEvents.length === 0 ? (
            <div className="card empty-state">No assistant tool audit logs match your filter.</div>
          ) : (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Session ID</th>
                    <th>Event Type</th>
                    <th>Tool Executed</th>
                    <th>Authorized</th>
                    <th>Security Flag</th>
                    <th>Output Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAssistantEvents.map((item, idx) => (
                    <tr key={idx}>
                      <td style={{ fontSize: '0.75rem', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                        {new Date(item.timestamp).toLocaleString()}
                      </td>
                      <td style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: '#64748b' }}>
                        {item.session_id.slice(0, 8)}...
                      </td>
                      <td>
                        <span className="badge" style={{ background: '#1e293b', color: '#cbd5e1' }}>
                          {item.event_type}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'monospace', color: '#38bdf8', fontSize: '0.8rem' }}>
                        {item.tool_name || '—'}
                      </td>
                      <td>
                        <span className={`badge ${item.authorized ? 'badge-success' : 'badge-danger'}`}>
                          {item.authorized ? 'AUTHORIZED' : 'DENIED'}
                        </span>
                      </td>
                      <td>
                        {item.security_flag ? (
                          <span className="badge badge-danger">{item.security_flag}</span>
                        ) : (
                          <span style={{ color: '#10b981', fontSize: '0.75rem' }}>CLEAR</span>
                        )}
                      </td>
                      <td style={{ fontSize: '0.8rem', color: '#94a3b8', maxWidth: '320px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.output_summary || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
