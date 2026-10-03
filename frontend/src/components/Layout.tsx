import { NavLink, Outlet } from 'react-router-dom'

const NAV_ITEMS = [
  { path: '/', label: 'Overview' },
  { path: '/slow-queries', label: 'Slow Queries' },
  { path: '/queries', label: 'Query Details' },
  { path: '/plans', label: 'Plan Viewer' },
  { path: '/gnn', label: 'GNN Analysis' },
  { path: '/recommendations', label: 'Recommendations' },
  { path: '/simulations', label: 'Simulations' },
  { path: '/approvals', label: 'Approval Center' },
  { path: '/assistant', label: 'DBA Assistant' },
  { path: '/health', label: 'System Health' },
  { path: '/audit', label: 'Audit Logs' },
]

export function Layout() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div className="brand" style={{ fontSize: '1.25rem', fontWeight: 800 }}>DBZenith</div>
          <span style={{ fontSize: '0.75rem', opacity: 0.7, background: '#1e293b', padding: '2px 8px', borderRadius: '4px' }}>
            v0.7 Autonomous DBA
          </span>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span className="badge badge-observed" title="Real telemetry from pg_stat_statements">OBSERVED</span>
          <span className="badge badge-ai-analysis" title="GNN model inference">AI ANALYSIS</span>
          <span className="badge badge-recommendation" title="Advisory engines">RECOMMENDATION</span>
          <span className="badge badge-simulation" title="Sandbox HypoPG execution">SIMULATION</span>
          <span className="badge badge-approval-required" title="Human gate invariant">APPROVAL REQUIRED</span>
        </div>
      </header>

      <nav
        aria-label="Primary navigation"
        style={{
          display: 'flex',
          overflowX: 'auto',
          background: '#151f32',
          padding: '8px 24px',
          gap: '8px',
          borderBottom: '1px solid #1e293b',
        }}
      >
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            style={({ isActive }) => ({
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '13px',
              fontWeight: isActive ? 600 : 400,
              color: isActive ? '#38bdf8' : '#94a3b8',
              background: isActive ? '#0f172a' : 'transparent',
              textDecoration: 'none',
              whiteSpace: 'nowrap',
            })}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="content" style={{ maxWidth: '1280px', margin: '0 auto', padding: '28px 20px' }}>
        <Outlet />
      </main>
    </div>
  )
}
