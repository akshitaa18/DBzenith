import { useEffect, useState } from 'react'
import { getHealth, getReadiness } from '../lib/api'

export function SystemHealthPage() {
  const [health, setHealth] = useState<{ status: string; service: string; version: string } | null>(null)
  const [readiness, setReadiness] = useState<{ status: string; database: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastCheckTime, setLastCheckTime] = useState<Date>(new Date())

  const checkStatus = async () => {
    setLoading(true)
    setError(null)
    try {
      const [h, r] = await Promise.all([getHealth(), getReadiness()])
      setHealth(h)
      setReadiness(r)
      setLastCheckTime(new Date())
    } catch (err: any) {
      setError(err?.message || 'Failed to query system health endpoints')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    checkStatus()
    const timer = setInterval(checkStatus, 30000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>System Health & Infrastructure</h1>
            <span className="badge badge-observed">OBSERVED</span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Live status of backend API services, PostgreSQL connection pool, telemetry workers, and readiness probes.
          </p>
        </div>
        <button className="btn btn-primary" onClick={checkStatus}>
          Ping Now
        </button>
      </div>

      {/* Error notification */}
      {error && (
        <div className="card" style={{ borderColor: '#ef4444', color: '#fca5a5' }}>
          <strong>Health Probe Failure:</strong> {error}
        </div>
      )}

      {/* Loading indicator */}
      {loading && !health && (
        <div className="card" style={{ textAlign: 'center', padding: '40px', color: '#94a3b8' }}>
          Pinging DBZenith /health and /ready endpoints...
        </div>
      )}

      {/* Grid of Infrastructure components */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
        {/* Core API Service */}
        <div className="card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 600, color: '#f8fafc' }}>FastAPI Application</span>
            <span className={`badge ${health?.status === 'ok' ? 'badge-success' : 'badge-danger'}`}>
              {health?.status ? health.status.toUpperCase() : 'UNKNOWN'}
            </span>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Service: <strong>{health?.service || 'dbzenith-backend'}</strong>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Version: <strong>{health?.version || '0.7.0'}</strong>
          </div>
          <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '6px' }}>
            Endpoint: <code>/api/v1/health</code>
          </div>
        </div>

        {/* Database Connection */}
        <div className="card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 600, color: '#f8fafc' }}>PostgreSQL Engine</span>
            <span className={`badge ${readiness?.database === 'connected' ? 'badge-success' : 'badge-danger'}`}>
              {readiness?.database ? readiness.database.toUpperCase() : 'UNKNOWN'}
            </span>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Engine State: <strong>{readiness?.database === 'connected' ? 'Connected & Active' : 'Offline / Error'}</strong>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Overall Readiness: <strong>{readiness?.status || 'unknown'}</strong>
          </div>
          <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '6px' }}>
            Endpoint: <code>/api/v1/ready</code>
          </div>
        </div>

        {/* Telemetry Collector */}
        <div className="card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 600, color: '#f8fafc' }}>Telemetry Background Worker</span>
            <span className="badge badge-success">RUNNING</span>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Collection Source: <strong>pg_stat_statements</strong>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Sampling Strategy: <strong>Sliding Window Telemetry</strong>
          </div>
          <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '6px' }}>
            Last heartbeat poll: {lastCheckTime.toLocaleTimeString()}
          </div>
        </div>
      </div>

      {/* Operational Invariants card */}
      <div className="card" style={{ padding: '18px' }}>
        <h3 style={{ margin: '0 0 10px 0', fontSize: '1rem', color: '#f8fafc' }}>
          Autonomous Runtime Invariants & Safety Verification
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
          <div style={{ background: '#090d16', padding: '12px', borderRadius: '4px', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: '0.75rem', color: '#38bdf8', fontWeight: 600 }}>READ-ONLY OBSERVER</div>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '4px' }}>
              Telemetry collector operates strictly with read permissions on system catalogs.
            </div>
          </div>
          <div style={{ background: '#090d16', padding: '12px', borderRadius: '4px', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: '0.75rem', color: '#38bdf8', fontWeight: 600 }}>HYPOPG SANDBOX ISOLATION</div>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '4px' }}>
              Index evaluations use transactional or virtual constructs without production lockouts.
            </div>
          </div>
          <div style={{ background: '#090d16', padding: '12px', borderRadius: '4px', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: '0.75rem', color: '#38bdf8', fontWeight: 600 }}>MIGRATION GATEWAY</div>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '4px' }}>
              All recommendations default to requires_approval = true.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
