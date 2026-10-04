import React from 'react'

export type OptimizationStage =
  | 'detect'
  | 'analyze'
  | 'recommend'
  | 'simulate'
  | 'compare'
  | 'approve'
  | 'audit'

interface OptimizationFlowHeaderProps {
  currentStage?: OptimizationStage
  compact?: boolean
  subtitle?: string
}

const STAGES: Array<{ id: OptimizationStage; label: string; desc: string; icon: string }> = [
  { id: 'detect', label: '1. Detect', desc: 'Workload & Telemetry', icon: '🔍' },
  { id: 'analyze', label: '2. Analyze', desc: 'AST & GNN Model', icon: '🧠' },
  { id: 'recommend', label: '3. Recommend', desc: 'Index / Rewrite / RL', icon: '💡' },
  { id: 'simulate', label: '4. Simulate', desc: 'HypoPG Sandbox', icon: '🧪' },
  { id: 'compare', label: '5. Compare', desc: 'Before vs After Cost', icon: '⚖️' },
  { id: 'approve', label: '6. Approve', desc: 'Human DBA Sign-off', icon: '🛡️' },
  { id: 'audit', label: '7. Audit', desc: 'Immutable Ledger', icon: '📜' },
]

export function OptimizationFlowHeader({ currentStage, compact = false, subtitle }: OptimizationFlowHeaderProps) {
  return (
    <div
      style={{
        background: '#0f172a',
        border: '1px solid #1e293b',
        borderRadius: '10px',
        padding: compact ? '10px 14px' : '14px 18px',
        margin: '12px 0 16px 0',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: compact ? '6px' : '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc', letterSpacing: '0.02em' }}>
            HOW DBZENITH OPTIMIZES EVERY QUERY
          </span>
          <span className="badge badge-ai-analysis" style={{ fontSize: '10px' }}>
            AUTONOMOUS PIPELINE
          </span>
        </div>
        <span style={{ fontSize: '11px', color: '#94a3b8' }}>
          {subtitle || 'Deterministic Sandbox Gate • Zero Production Risk'}
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
          gap: '6px',
          alignItems: 'center',
        }}
      >
        {STAGES.map((st, idx) => {
          const isActive = currentStage === st.id
          return (
            <div
              key={st.id}
              style={{
                position: 'relative',
                background: isActive ? '#1e293b' : '#090d16',
                border: isActive ? '1px solid #38bdf8' : '1px solid #1e293b',
                borderRadius: '6px',
                padding: compact ? '6px 8px' : '8px 10px',
                textAlign: 'center',
                transition: 'all 0.2s ease',
              }}
            >
              <div style={{ fontSize: compact ? '11px' : '12px', fontWeight: 700, color: isActive ? '#38bdf8' : '#e2e8f0' }}>
                <span style={{ marginRight: '4px' }}>{st.icon}</span>
                {st.label}
              </div>
              {!compact && (
                <div style={{ fontSize: '10px', color: isActive ? '#93c5fd' : '#64748b', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {st.desc}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
