import React, { useState } from 'react'
import { sendAssistantMessage, type AssistantChatResponse } from '../lib/api'

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  safetyCheckPassed?: boolean
  evidence?: Record<string, unknown>
  recommendations?: Array<Record<string, unknown>>
  simulations?: Array<Record<string, unknown>>
  approvalRequest?: Record<string, unknown> | null
  auditTrail?: Array<{ timestamp: string; event_type: string; tool_name?: string; output_summary?: string }>
}

export function ConversationalDBA() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        'Hello DBA! I am DBZenith\'s Conversational Assistant powered by LangGraph. I can analyze slow queries, evaluate execution plans, recommend optimizations, and run isolated sandbox simulations. How can I assist with your database workload today?',
      timestamp: new Date().toLocaleTimeString(),
      safetyCheckPassed: true,
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [showAudit, setShowAudit] = useState(false)

  const quickPrompts = [
    'Analyze top slow queries and explain bottlenecks',
    'Recommend optimizations for high latency queries',
    'Simulate pending recommendations in sandbox',
    'Stage migration approval request for human DBA review',
  ]

  const handleSend = async (textToSend?: string) => {
    const query = textToSend || input
    if (!query.trim() || loading) return

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date().toLocaleTimeString(),
    }

    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const data: AssistantChatResponse = await sendAssistantMessage(query, sessionId, 'dba')
      setSessionId(data.session_id)

      const assistantMsg: ChatMessage = {
        id: `asst-${Date.now()}`,
        role: 'assistant',
        content: data.response,
        timestamp: new Date().toLocaleTimeString(),
        safetyCheckPassed: data.safety_check_passed,
        evidence: data.evidence,
        recommendations: data.recommendations,
        simulations: data.simulations,
        approvalRequest: data.approval_request,
        auditTrail: data.audit_trail,
      }

      setMessages((prev) => [...prev, assistantMsg])
    } catch {
      const errorMsg: ChatMessage = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: 'Assistant communication error. Please ensure the DBZenith backend is running.',
        timestamp: new Date().toLocaleTimeString(),
        safetyCheckPassed: false,
      }
      setMessages((prev) => [...prev, errorMsg])
    } finally {
      setLoading(false)
    }
  }

  const latestAuditTrail = messages[messages.length - 1]?.auditTrail || []

  return (
    <article className="card section-card conversational-dba">
      <div className="section-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2>Conversational DBA Assistant (LangGraph)</h2>
          <p>
            Autonomous reasoning agent with controlled tools: inspects telemetry, GNN plan features,
            recommends indexes/rewrites, and measures sandbox performance.
          </p>
        </div>
        <button
          className="btn-secondary"
          style={{ fontSize: '0.82rem', padding: '0.35rem 0.75rem' }}
          onClick={() => setShowAudit(!showAudit)}
        >
          {showAudit ? 'Hide Audit Ledger' : 'Show Audit Ledger'}
        </button>
      </div>

      <div
        className="tool-badges"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.4rem',
          margin: '0.5rem 0 1rem 0',
          padding: '0.5rem',
          background: 'rgba(255, 255, 255, 0.03)',
          borderRadius: '6px',
        }}
      >
        <span style={{ fontSize: '0.75rem', opacity: 0.7, marginRight: '0.2rem' }}>Authorized Tools:</span>
        {[
          'get_slow_queries',
          'get_query_details',
          'get_execution_plan',
          'analyze_plan',
          'get_recommendations',
          'simulate_recommendation',
          'compare_simulations',
          'explain_bottleneck',
          'get_workload_summary',
          'request_migration_approval',
        ].map((t) => (
          <code
            key={t}
            style={{
              fontSize: '0.72rem',
              padding: '0.15rem 0.4rem',
              background: '#242b35',
              borderRadius: '4px',
              color: '#60a5fa',
            }}
          >
            {t}
          </code>
        ))}
      </div>

      {showAudit && latestAuditTrail.length > 0 && (
        <div
          className="audit-drawer"
          style={{
            margin: '0 0 1rem 0',
            padding: '0.75rem',
            background: '#151922',
            border: '1px solid #2d3748',
            borderRadius: '6px',
            fontSize: '0.8rem',
            maxHeight: '160px',
            overflowY: 'auto',
          }}
        >
          <strong style={{ color: '#93c5fd' }}>Active Session Audit Ledger ({latestAuditTrail.length} events):</strong>
          <ul style={{ margin: '0.4rem 0 0 0', paddingLeft: '1.2rem' }}>
            {latestAuditTrail.map((ev, i) => (
              <li key={i} style={{ marginBottom: '0.2rem' }}>
                <span style={{ opacity: 0.6 }}>{ev.timestamp.slice(11, 19)}</span> —{' '}
                <strong style={{ color: '#e2e8f0' }}>[{ev.event_type}]</strong> {ev.output_summary || ev.tool_name || ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div
        className="chat-window"
        style={{
          minHeight: '260px',
          maxHeight: '440px',
          overflowY: 'auto',
          border: '1px solid #242b35',
          borderRadius: '8px',
          padding: '1rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.85rem',
          background: '#0d1117',
        }}
      >
        {messages.map((m) => {
          const isUser = m.role === 'user'
          const isSecurityAlert = m.safetyCheckPassed === false

          return (
            <div
              key={m.id}
              style={{
                alignSelf: isUser ? 'flex-end' : 'flex-start',
                maxWidth: '85%',
                padding: '0.75rem 1rem',
                borderRadius: isUser ? '10px 10px 0 10px' : '10px 10px 10px 0',
                background: isSecurityAlert
                  ? 'rgba(239, 68, 68, 0.15)'
                  : isUser
                  ? '#1e3a5f'
                  : '#161e2a',
                border: isSecurityAlert
                  ? '1px solid #ef4444'
                  : isUser
                  ? '1px solid #2563eb'
                  : '1px solid #283344',
                color: isSecurityAlert ? '#fca5a5' : '#f1f5f9',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '0.72rem',
                  opacity: 0.65,
                  marginBottom: '0.35rem',
                }}
              >
                <span>{isUser ? 'You (DBA)' : 'DBZenith Assistant'}</span>
                <span>{m.timestamp}</span>
              </div>
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.45, fontSize: '0.9rem' }}>
                {m.content}
              </div>

              {m.approvalRequest && (
                <div
                  style={{
                    marginTop: '0.6rem',
                    padding: '0.5rem',
                    background: 'rgba(245, 158, 11, 0.12)',
                    border: '1px solid #f59e0b',
                    borderRadius: '5px',
                    fontSize: '0.8rem',
                  }}
                >
                  <strong style={{ color: '#fbbf24' }}>Human Approval Gate Required</strong>
                  <p style={{ margin: '0.2rem 0 0 0', opacity: 0.9 }}>
                    Status: <code>pending_dba_review</code>. Invariant enforced: Agent cannot self-approve.
                  </p>
                </div>
              )}
            </div>
          )
        })}
        {loading && (
          <div style={{ alignSelf: 'flex-start', fontSize: '0.85rem', color: '#93c5fd', fontStyle: 'italic' }}>
            Assistant is reasoning through LangGraph nodes (understand → retrieve → analyze → recommend → simulate)...
          </div>
        )}
      </div>

      <div className="quick-prompts" style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginTop: '0.65rem' }}>
        {quickPrompts.map((qp, i) => (
          <button
            key={i}
            className="btn-secondary"
            style={{ fontSize: '0.76rem', padding: '0.25rem 0.5rem' }}
            disabled={loading}
            onClick={() => handleSend(qp)}
          >
            {qp}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
        <input
          type="text"
          placeholder="Ask DBA assistant (e.g., 'Analyze query 101 and simulate recommendations')..."
          value={input}
          disabled={loading}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          style={{
            flex: 1,
            padding: '0.6rem 0.9rem',
            background: '#161b22',
            border: '1px solid #30363d',
            borderRadius: '6px',
            color: '#f0f6fc',
          }}
        />
        <button
          className="btn-primary"
          disabled={loading || !input.trim()}
          onClick={() => handleSend()}
          style={{ padding: '0.6rem 1.2rem' }}
        >
          {loading ? 'Processing...' : 'Send'}
        </button>
      </div>
    </article>
  )
}
