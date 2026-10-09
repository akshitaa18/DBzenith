import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { seedDemoWorkload } from '../lib/api'

interface NavSection {
  title: string
  items: Array<{
    path: string
    label: string
    icon: string
    hint: string
  }>
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'OBSERVE',
    items: [
      { path: '/', label: 'Overview', icon: '📊', hint: 'Workload KPIs & timeline' },
      { path: '/slow-queries', label: 'Slow Queries', icon: '⏱️', hint: 'Latency bottleneck telemetry' },
      { path: '/queries', label: 'Query Details', icon: '🔍', hint: 'Deep query metrics & traces' },
      { path: '/plans', label: 'Plan Viewer', icon: '🌲', hint: 'EXPLAIN visual tree & AST' },
    ],
  },
  {
    title: 'ANALYZE & ADVISE',
    items: [
      { path: '/gnn', label: 'GNN Model', icon: '🧠', hint: 'Graph Neural Network & RL' },
      { path: '/recommendations', label: 'Recommendations', icon: '💡', hint: 'Autonomous advisor engine' },
    ],
  },
  {
    title: 'SIMULATE & VALIDATE',
    items: [
      { path: '/simulations', label: 'Sandbox Simulations', icon: '🧪', hint: 'HypoPG virtual index sandbox' },
      { path: '/approvals', label: 'Approval Center', icon: '🛡️', hint: 'Human DBA sign-off gate' },
    ],
  },
  {
    title: 'GOVERN & OPERATE',
    items: [
      { path: '/assistant', label: 'DBA Assistant', icon: '🤖', hint: 'Autonomous conversational copilot' },
      { path: '/health', label: 'System Health', icon: '💓', hint: 'PostgreSQL cache & connection gauges' },
      { path: '/audit', label: 'Audit Logs', icon: '📜', hint: 'Immutable cryptographic ledger' },
    ],
  },
]

export function Layout() {
  const [seeding, setSeeding] = useState(false)
  const [seedNotice, setSeedNotice] = useState<string | null>(null)
  const navigate = useNavigate()

  const handleGlobalSeedWorkload = async () => {
    setSeeding(true)
    setSeedNotice(null)
    try {
      const res = await seedDemoWorkload()
      setSeedNotice(`Workload loaded! ${res.total_calls.toLocaleString()} calls across 24h timeline.`)
      setTimeout(() => setSeedNotice(null), 6000)
      navigate('/')
    } catch (err: any) {
      setSeedNotice(`Seed failed: ${err.message}`)
      setTimeout(() => setSeedNotice(null), 6000)
    } finally {
      setSeeding(false)
    }
  }

  return (
    <div className="app-shell">
      {/* Platform Header */}
      <header className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div className="brand" style={{ fontSize: '1.25rem', fontWeight: 800, color: '#f8fafc', letterSpacing: '0.02em' }}>
            <span style={{ fontSize: '1.4rem' }}>⚡</span>
            <span>DBZenith</span>
          </div>
          <span
            style={{
              fontSize: '0.72rem',
              fontWeight: 700,
              background: '#1e293b',
              color: '#38bdf8',
              padding: '2px 8px',
              borderRadius: '4px',
              letterSpacing: '0.04em',
              border: '1px solid #334155',
            }}
          >
            v0.7 AUTONOMOUS DBA
          </span>
        </div>

        {/* Global Live Engine Badges */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="badge badge-observed" title="Observes PostgreSQL telemetry via pg_stat_statements">
            <span>●</span> TELEMETRY ACTIVE
          </span>
          <span className="badge badge-ai-analysis" title="GNN graph representation & RL policy">
            <span>●</span> GNN INFERENCE
          </span>
          <span className="badge badge-simulation" title="HypoPG virtual index sandbox with zero table locks">
            <span>●</span> HYPOPG SANDBOX
          </span>
          <span className="badge badge-approval-required" title="Mandatory Human Approval Gate enforced">
            <span>●</span> HUMAN GATE ACTIVE
          </span>

          <button
            onClick={handleGlobalSeedWorkload}
            disabled={seeding}
            className="btn btn-sm"
            style={{
              background: '#059669',
              borderColor: '#047857',
              color: '#fff',
              fontSize: '11px',
              fontWeight: 700,
              marginLeft: '8px',
            }}
            title="Re-seed large enterprise workload with extended 7-day timeline and sandbox simulations"
          >
            {seeding ? '⚡ Seeding Workload...' : '⚡ Load Enterprise Workload'}
          </button>
        </div>
      </header>

      {/* Global Seed Notification Banner */}
      {seedNotice && (
        <div
          style={{
            background: 'rgba(5, 150, 105, 0.2)',
            borderBottom: '1px solid rgba(5, 150, 105, 0.4)',
            padding: '8px 24px',
            fontSize: '12px',
            color: '#34d399',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>✓ {seedNotice}</span>
          <button
            onClick={() => setSeedNotice(null)}
            style={{ background: 'transparent', border: 'none', color: '#34d399', cursor: 'pointer', fontSize: '14px' }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Categorized Primary Navigation */}
      <nav
        aria-label="Primary navigation"
        style={{
          display: 'flex',
          overflowX: 'auto',
          background: '#0c1427',
          padding: '6px 20px',
          gap: '16px',
          borderBottom: '1px solid #1e293b',
          alignItems: 'center',
        }}
      >
        {NAV_SECTIONS.map((sec, idx) => (
          <div key={sec.title} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span
              style={{
                fontSize: '10px',
                fontWeight: 800,
                color: '#64748b',
                letterSpacing: '0.08em',
                marginRight: '2px',
                userSelect: 'none',
              }}
            >
              {sec.title}
            </span>

            {sec.items.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                title={item.hint}
                className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
                style={({ isActive }) => ({
                  padding: '5px 10px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: isActive ? 700 : 500,
                  color: isActive ? '#38bdf8' : '#cbd5e1',
                  background: isActive ? '#1e293b' : 'transparent',
                  textDecoration: 'none',
                  whiteSpace: 'nowrap',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '5px',
                  border: isActive ? '1px solid rgba(56, 189, 248, 0.3)' : '1px solid transparent',
                  transition: 'all 0.15s ease',
                })}
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </NavLink>
            ))}

            {idx < NAV_SECTIONS.length - 1 && (
              <span style={{ color: '#1e293b', margin: '0 4px', fontSize: '14px' }}>|</span>
            )}
          </div>
        ))}
      </nav>

      {/* Main Content Area */}
      <main className="content" style={{ maxWidth: '1360px', margin: '0 auto', padding: '24px 20px', flex: 1 }}>
        <Outlet />
      </main>

      {/* Platform Footer */}
      <footer
        style={{
          borderTop: '1px solid #1e293b',
          padding: '14px 24px',
          background: '#070c18',
          fontSize: '11px',
          color: '#64748b',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
          <span>DBZenith v0.7 — Self-Driving PostgreSQL Optimization</span>
          <span>•</span>
          <span>Target DB: PostgreSQL 16 (localhost:5432/dbzenith)</span>
          <span>•</span>
          <span>HypoPG Virtual Index Engine: Active</span>
        </div>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <span className="badge badge-observed" style={{ fontSize: '10px' }}>READ-ONLY TELEMETRY</span>
          <span className="badge badge-approval-required" style={{ fontSize: '10px' }}>HUMAN-IN-THE-LOOP INVARIANT</span>
        </div>
      </footer>
    </div>
  )
}
