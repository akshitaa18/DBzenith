import { useNavigate } from 'react-router-dom'

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

const STAGES: Array<{ id: OptimizationStage; label: string; desc: string; icon: string; path: string }> = [
  { id: 'detect', label: '1. Detect', desc: 'Workload & Telemetry', icon: '🔍', path: '/slow-queries' },
  { id: 'analyze', label: '2. Analyze', desc: 'AST & GNN Model', icon: '🧠', path: '/plans' },
  { id: 'recommend', label: '3. Recommend', desc: 'Index / Rewrite / RL', icon: '💡', path: '/recommendations' },
  { id: 'simulate', label: '4. Simulate', desc: 'HypoPG Sandbox', icon: '🧪', path: '/simulations' },
  { id: 'compare', label: '5. Compare', desc: 'Before vs After Cost', icon: '⚡', path: '/queries' },
  { id: 'approve', label: '6. Approve', desc: 'Human DBA Sign-off', icon: '🛡️', path: '/approvals' },
  { id: 'audit', label: '7. Audit', desc: 'Immutable Ledger', icon: '📜', path: '/audit' },
]

export function OptimizationFlowHeader({ currentStage, compact = false, subtitle }: OptimizationFlowHeaderProps) {
  const navigate = useNavigate()

  return (
    <div
      style={{
        background: '#0c1427',
        border: '1px solid #1e293b',
        borderRadius: '12px',
        padding: compact ? '10px 14px' : '14px 18px',
        margin: '12px 0 18px 0',
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.25)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: compact ? '6px' : '10px', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 800, color: '#f8fafc', letterSpacing: '0.04em' }}>
            HOW DBZENITH OPTIMIZES EVERY QUERY
          </span>
          <span className="badge badge-ai-analysis" style={{ fontSize: '10px' }}>
            7-STAGE AUTONOMOUS PIPELINE
          </span>
        </div>
        <span style={{ fontSize: '11px', color: '#94a3b8' }}>
          {subtitle || 'Click any stage to inspect • Deterministic Sandbox Gate • Zero Production Risk'}
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
        {STAGES.map((st) => {
          const isActive = currentStage === st.id
          return (
            <div
              key={st.id}
              onClick={() => navigate(st.path)}
              role="button"
              tabIndex={0}
              title={`Jump to ${st.label}: ${st.desc}`}
              style={{
                position: 'relative',
                background: isActive ? '#1e293b' : '#070c18',
                border: isActive ? '1px solid #38bdf8' : '1px solid #1e293b',
                borderRadius: '8px',
                padding: compact ? '6px 6px' : '8px 10px',
                textAlign: 'center',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                boxShadow: isActive ? '0 0 10px rgba(56, 189, 248, 0.2)' : 'none',
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
