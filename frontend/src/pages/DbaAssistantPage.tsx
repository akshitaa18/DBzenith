import { useEffect, useState } from 'react'
import { ConversationalDBA } from '../components/ConversationalDBA'
import { getAssistantTools } from '../lib/api'

export function DbaAssistantPage() {
  const [tools, setTools] = useState<Array<{ name: string; description: string }>>([])
  const [loadingTools, setLoadingTools] = useState(true)

  useEffect(() => {
    getAssistantTools()
      .then((data) => setTools(data || []))
      .catch((err) => console.error('Failed to load assistant tools', err))
      .finally(() => setLoadingTools(false))
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>Autonomous DBA Assistant</h1>
            <span className="badge badge-ai-analysis">AI ASSISTANT</span>
            <span className="badge badge-approval-required">GATED ACTIONS</span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            LangGraph conversational agent equipped with 10 strictly authorized DBA tools, privacy gateway sanitization, and prompt-injection barriers.
          </p>
        </div>
      </div>

      {/* Main Container: Chat + Controlled Tools Sidebar */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: '16px', alignItems: 'start' }}>
        {/* Chat UI */}
        <div>
          <ConversationalDBA />
        </div>

        {/* Authorized Tools Inspector Sidebar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div className="card" style={{ padding: '16px' }}>
            <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: '#f8fafc' }}>
              Authorized Tools Registry
            </h3>
            <p style={{ margin: '0 0 12px 0', fontSize: '0.75rem', color: '#94a3b8' }}>
              The agent may only call these 10 verified sandbox tools. Arbitrary SQL execution is strictly forbidden.
            </p>

            {loadingTools ? (
              <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Loading tool definitions...</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '500px', overflowY: 'auto' }}>
                {tools.map((tool) => (
                  <div
                    key={tool.name}
                    style={{
                      background: '#090d16',
                      border: '1px solid #1e293b',
                      borderRadius: '4px',
                      padding: '8px 10px',
                      fontSize: '0.75rem',
                    }}
                  >
                    <div style={{ fontWeight: 600, color: '#38bdf8', fontFamily: 'monospace' }}>
                      {tool.name}
                    </div>
                    <div style={{ color: '#94a3b8', marginTop: '3px', fontSize: '0.75rem' }}>
                      {tool.description}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div
            className="card"
            style={{
              padding: '16px',
              borderLeft: '4px solid #ef4444',
              background: 'rgba(239, 68, 68, 0.05)',
            }}
          >
            <h4 style={{ margin: '0 0 6px 0', fontSize: '0.85rem', color: '#fca5a5' }}>
              Hard Guardrail Policies
            </h4>
            <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '0.75rem', color: '#cbd5e1', lineHeight: '1.4' }}>
              <li>No arbitrary SQL execution or raw production access</li>
              <li>Privacy gateway sanitization of PII / table literals</li>
              <li>Prompt injection defense triggers auto-rejection</li>
              <li>Agent cannot approve its own recommendations</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
