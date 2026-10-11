import { FormEvent, useEffect, useState } from 'react'
import {
  DatabaseConfigSettings,
  DatabaseValidationResponse,
  getDatabaseConfig,
  getHealth,
  getReadiness,
  getSystemDiagnostics,
  SystemDiagnostics,
  updateDatabaseConfig,
  validateDatabaseConnection,
} from '../lib/api'
import { formatCollectionTimestamp, ProvenanceBadge } from '../components/ProvenanceBadge'
import { useAuth } from '../context/AuthContext'

export function SystemHealthPage() {
  const { user, canApprove } = useAuth()
  const [health, setHealth] = useState<{ status: string; service: string; version: string } | null>(null)
  const [readiness, setReadiness] = useState<{ status: string; database: string } | null>(null)
  const [diagnostics, setDiagnostics] = useState<SystemDiagnostics | null>(null)
  const [dbConfig, setDbConfig] = useState<DatabaseConfigSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastCheckTime, setLastCheckTime] = useState<Date>(new Date())

  // Guided Database Connection Setup / Validation state
  const [valTarget, setValTarget] = useState<'primary' | 'sandbox'>('primary')
  const [valHost, setValHost] = useState('')
  const [valPort, setValPort] = useState<number>(5432)
  const [valDatabase, setValDatabase] = useState('')
  const [valUsername, setValUsername] = useState('')
  const [valSslMode, setValSslMode] = useState<'disable' | 'allow' | 'prefer' | 'require' | 'verify-ca' | 'verify-full'>('prefer')
  const [verifyExtensions, setVerifyExtensions] = useState(true)
  const [validating, setValidating] = useState(false)
  const [validationResult, setValidationResult] = useState<DatabaseValidationResponse | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)

  // Runtime Telemetry Config Form state
  const [thresholdMs, setThresholdMs] = useState<number>(80)
  const [pollSeconds, setPollSeconds] = useState<number>(30)
  const [savingConfig, setSavingConfig] = useState(false)
  const [configMsg, setConfigMsg] = useState<{ text: string; ok: boolean } | null>(null)

  const checkStatus = async () => {
    setLoading(true)
    setError(null)
    try {
      const [h, r, diag, cfg] = await Promise.all([
        getHealth(),
        getReadiness(),
        getSystemDiagnostics().catch(() => null),
        getDatabaseConfig().catch(() => null),
      ])
      setHealth(h)
      setReadiness(r)
      if (diag) setDiagnostics(diag)
      if (cfg) {
        setDbConfig(cfg)
        setThresholdMs(cfg.slow_query_threshold_ms)
        setPollSeconds(cfg.telemetry_poll_seconds ?? cfg.telemetry_interval_seconds ?? 30)
      }
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

  const handleRunValidation = async (e: FormEvent) => {
    e.preventDefault()
    setValidating(true)
    setValidationError(null)
    try {
      const res = await validateDatabaseConnection({
        target: valTarget,
        host: valHost.trim() || undefined,
        port: valPort || 5432,
        database: valDatabase.trim() || undefined,
        username: valUsername.trim() || undefined,
        ssl_mode: valSslMode,
        verify_extensions: verifyExtensions,
      })
      setValidationResult(res)
    } catch (err: any) {
      setValidationError(err?.message || 'Database connection validation failed')
    } finally {
      setValidating(false)
    }
  }

  const handleSaveConfig = async (e: FormEvent) => {
    e.preventDefault()
    setSavingConfig(true)
    setConfigMsg(null)
    try {
      const updated = await updateDatabaseConfig({
        slow_query_threshold_ms: Number(thresholdMs),
        telemetry_poll_seconds: Number(pollSeconds),
      })
      const nextCfg = updated.config ?? (updated as unknown as DatabaseConfigSettings)
      setDbConfig(nextCfg)
      const nextThreshold = updated.slow_query_threshold_ms ?? nextCfg.slow_query_threshold_ms
      const nextPoll = updated.telemetry_poll_seconds ?? nextCfg.telemetry_poll_seconds ?? nextCfg.telemetry_interval_seconds ?? pollSeconds
      setConfigMsg({
        text: `Runtime telemetry settings updated (slow query threshold: ${nextThreshold}ms, poll interval: ${nextPoll}s).`,
        ok: true,
      })
    } catch (err: any) {
      setConfigMsg({
        text: `Failed to update configuration: ${err?.message || 'Permission or validation error'}`,
        ok: false,
      })
    } finally {
      setSavingConfig(false)
    }
  }

  const overallStatus = diagnostics?.status || (readiness?.status === 'ready' ? 'healthy' : 'degraded')
  const pgStatExt = diagnostics?.extensions?.pg_stat_statements
  const hypopgExt = diagnostics?.extensions?.hypopg
  const collector = diagnostics?.collector

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>
              System Health, Extensions & Connection Setup
            </h1>
            <span className="badge badge-observed">OBSERVED</span>
            <span
              className={`badge ${
                overallStatus === 'healthy' ? 'badge-success' : 'badge-warning'
              }`}
              data-testid="system-overall-status"
            >
              {overallStatus.toUpperCase()}
            </span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Live diagnostics for API services, PostgreSQL primary & sandbox engines, telemetry collector freshness, required extensions (<code>pg_stat_statements</code>, <code>hypopg</code>), and guided connection validation.
          </p>
        </div>
        <button className="btn btn-primary" onClick={checkStatus} disabled={loading}>
          {loading ? 'Checking...' : 'Ping Now'}
        </button>
      </div>

      {/* Self-Explanatory Infrastructure Banner */}
      <div className="guide-banner">
        <div className="guide-banner-icon">💓</div>
        <div className="guide-banner-content">
          <div className="guide-banner-title">
            <span>POSTGRESQL INFRASTRUCTURE HEALTH & EXTENSION DIAGNOSTICS</span>
            <span className="badge badge-observed">LIVE PROBES</span>
          </div>
          <p className="guide-banner-desc">
            Inspects live PostgreSQL connectivity, catalog permissions, extension readiness (<code>pg_stat_statements</code> for telemetry and <code>hypopg</code> for virtual index simulations), and collector staleness. Passwords and raw connection strings are masked server-side and never exposed in the browser.
          </p>
          <div className="guide-banner-pills">
            <span className={`badge ${health?.status === 'ok' ? 'badge-success' : 'badge-danger'}`}>
              {health?.status === 'ok' ? '✓ Backend API Online' : '⚠ API Degraded'}
            </span>
            <span className={`badge ${readiness?.database === 'ok' || diagnostics?.primary_database?.connected ? 'badge-observed' : 'badge-danger'}`}>
              {readiness?.database === 'ok' || diagnostics?.primary_database?.connected
                ? '✓ Primary DB Connected'
                : '✕ Primary DB Offline'}
            </span>
            <span className={`badge ${collector?.status === 'error' ? 'badge-danger' : 'badge-ai-analysis'}`}>
              {collector?.status === 'error'
                ? `⚠ Collector Errors (${collector.failure_count})`
                : '✓ Collector Monitored'}
            </span>
          </div>
        </div>
      </div>

      {/* Error notification */}
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
          <span>
            <strong>Health Probe Failure:</strong> {error}
          </span>
          <button className="btn btn-secondary btn-sm" onClick={checkStatus}>
            Retry
          </button>
        </div>
      )}

      {/* Collector Error Banner if collector reported failures */}
      {collector?.last_collection_error && (
        <div
          role="alert"
          data-testid="collector-error-alert"
          className="card"
          style={{
            borderColor: '#f59e0b',
            background: 'rgba(245, 158, 11, 0.08)',
            color: '#fde68a',
            padding: '12px 16px',
          }}
        >
          <strong>Telemetry Collector Diagnostic Warning:</strong> {collector.last_collection_error}
          {collector.staleness_warning && (
            <div style={{ fontSize: '0.8rem', color: '#cbd5e1', marginTop: '4px' }}>
              {collector.staleness_warning}
            </div>
          )}
        </div>
      )}

      {/* Loading indicator */}
      {loading && !health && (
        <div className="card" style={{ textAlign: 'center', padding: '40px', color: '#94a3b8' }}>
          Pinging DBZenith /health, /ready, and /health/diagnostics endpoints...
        </div>
      )}

      {/* Grid of Infrastructure & Extension Components */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
        {/* 1. Core API Service */}
        <div className="card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 600, color: '#f8fafc' }}>FastAPI Application</span>
            <span className={`badge ${health?.status === 'ok' ? 'badge-success' : 'badge-danger'}`}>
              {health?.status ? health.status.toUpperCase() : 'UNKNOWN'}
            </span>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Service: <strong>{health?.service || diagnostics?.api?.service || 'dbzenith-backend'}</strong>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Version: <strong>{health?.version || diagnostics?.api?.version || '0.7.0'}</strong>
          </div>
          <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '6px' }}>
            Endpoint: <code>/api/v1/health</code> • Checked: {lastCheckTime.toLocaleTimeString()}
          </div>
        </div>

        {/* 2. Primary PostgreSQL Engine */}
        <div className="card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 600, color: '#f8fafc' }}>PostgreSQL Primary Engine</span>
            <span
              className={`badge ${
                diagnostics?.primary_database?.connected ?? (readiness?.database === 'ok' || readiness?.database === 'connected')
                  ? 'badge-success'
                  : 'badge-danger'
              }`}
            >
              {diagnostics?.primary_database?.connected ?? (readiness?.database === 'ok' || readiness?.database === 'connected')
                ? 'CONNECTED'
                : 'OFFLINE'}
            </span>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Engine State:{' '}
            <strong>
              {diagnostics?.primary_database?.version ||
                (readiness?.database === 'ok' || readiness?.database === 'connected'
                  ? 'Connected & Active'
                  : 'Offline / Error')}
            </strong>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Target (Masked):{' '}
            <code>{diagnostics?.primary_database?.dsn_masked || dbConfig?.database_url_masked || 'postgresql://***'}</code>
          </div>
          {diagnostics?.primary_database?.role && (
            <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
              DB Role: <code>{diagnostics.primary_database.role}</code> (Read-Only Guard:{' '}
              {diagnostics.primary_database.read_only_capable ? 'Yes' : 'No'})
            </div>
          )}
          {diagnostics?.primary_database?.error && (
            <div style={{ fontSize: '0.75rem', color: '#fca5a5' }}>
              Error: {diagnostics.primary_database.error}
            </div>
          )}
        </div>

        {/* 3. Telemetry Collector & Freshness */}
        <div className="card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 600, color: '#f8fafc' }}>Telemetry Background Worker</span>
            <span
              className={`badge ${
                collector?.status === 'error'
                  ? 'badge-danger'
                  : collector?.is_stale
                  ? 'badge-warning'
                  : 'badge-success'
              }`}
            >
              {collector?.status ? collector.status.toUpperCase() : 'RUNNING'}
            </span>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Last Successful Collection:{' '}
            <strong data-testid="health-last-telemetry">
              {collector?.last_successful_telemetry_at
                ? formatCollectionTimestamp(collector.last_successful_telemetry_at)
                : 'No live snapshot recorded'}
            </strong>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span>Snapshots: <strong>{collector?.snapshot_count ?? '—'}</strong></span>
            <span>•</span>
            <span>Failures: <strong style={{ color: (collector?.failure_count ?? 0) > 0 ? '#f87171' : '#34d399' }}>{collector?.failure_count ?? 0}</strong></span>
            {collector?.provenance_badge && (
              <ProvenanceBadge
                badge={collector.provenance_badge}
                state={collector.provenance_state}
                style={{ fontSize: '9px', padding: '1px 6px' }}
              />
            )}
          </div>
          <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px' }}>
            Poll Interval: {collector?.poll_interval_seconds ?? dbConfig?.telemetry_poll_seconds ?? 30}s • Slow Query Threshold: {collector?.slow_query_threshold_ms ?? dbConfig?.slow_query_threshold_ms ?? 80}ms
          </div>
        </div>

        {/* 4. Sandbox Database */}
        <div className="card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 600, color: '#f8fafc' }}>Isolated Sandbox Database</span>
            <span
              className={`badge ${
                diagnostics ? (diagnostics.sandbox_database?.connected ? 'badge-success' : 'badge-danger') : 'badge-observed'
              }`}
            >
              {diagnostics
                ? diagnostics.sandbox_database?.connected
                  ? 'CONNECTED'
                  : 'UNAVAILABLE'
                : 'STANDBY'}
            </span>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Target (Masked):{' '}
            <code>{diagnostics?.sandbox_database?.dsn_masked || dbConfig?.sandbox_database_url_masked || 'postgresql://***'}</code>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            HypoPG Virtual Indexes:{' '}
            <strong style={{ color: diagnostics?.sandbox_database?.hypopg_available ? '#34d399' : '#fbbf24' }}>
              {diagnostics
                ? diagnostics.sandbox_database?.hypopg_available
                  ? 'Available & Ready'
                  : 'Extension Not Loaded (Fallback Cost Mode)'
                : 'Probing...'}
            </strong>
          </div>
          {diagnostics?.sandbox_database?.error && (
            <div style={{ fontSize: '0.75rem', color: '#fca5a5' }}>
              Error: {diagnostics.sandbox_database.error}
            </div>
          )}
        </div>
      </div>

      {/* PostgreSQL Extension Checks (pg_stat_statements & hypopg) */}
      <div className="card" style={{ padding: '18px' }} data-testid="extension-checks-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
          <h2 style={{ margin: 0, fontSize: '1.05rem', color: '#f8fafc' }}>
            PostgreSQL Extension Checks (<code>pg_stat_statements</code> &amp; <code>hypopg</code>)
          </h2>
          <span className="badge badge-observed">CATALOG EXTENSION PROBES</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '14px' }}>
          <div style={{ background: '#090d16', padding: '14px', borderRadius: '6px', border: '1px solid #1e293b' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <code style={{ fontSize: '0.9rem', fontWeight: 700, color: '#38bdf8' }}>pg_stat_statements</code>
              <span
                className={`badge ${
                  pgStatExt
                    ? pgStatExt.operational
                      ? 'badge-success'
                      : pgStatExt.installed
                      ? 'badge-warning'
                      : 'badge-danger'
                    : 'badge-observed'
                }`}
              >
                {pgStatExt
                  ? pgStatExt.operational
                    ? `OPERATIONAL (v${pgStatExt.version || '1.x'})`
                    : pgStatExt.installed
                    ? 'INSTALLED (NOT PRELOADED)'
                    : 'NOT INSTALLED'
                  : 'CHECK VIA DIAGNOSTICS'}
              </span>
            </div>
            <div style={{ fontSize: '0.8rem', color: '#cbd5e1', lineHeight: 1.5 }}>
              {pgStatExt?.detail ||
                'Required for live workload telemetry collection of normalized query digests, execution counts, and buffer I/O.'}
            </div>
          </div>

          <div style={{ background: '#090d16', padding: '14px', borderRadius: '6px', border: '1px solid #1e293b' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <code style={{ fontSize: '0.9rem', fontWeight: 700, color: '#c084fc' }}>hypopg</code>
              <span
                className={`badge ${
                  hypopgExt
                    ? hypopgExt.operational
                      ? 'badge-success'
                      : hypopgExt.installed
                      ? 'badge-warning'
                      : 'badge-danger'
                    : 'badge-observed'
                }`}
              >
                {hypopgExt
                  ? hypopgExt.operational
                    ? `OPERATIONAL (v${hypopgExt.version || '1.x'})`
                    : hypopgExt.installed
                    ? 'INSTALLED (INACTIVE)'
                    : 'NOT INSTALLED'
                  : 'CHECK VIA DIAGNOSTICS'}
              </span>
            </div>
            <div style={{ fontSize: '0.8rem', color: '#cbd5e1', lineHeight: 1.5 }}>
              {hypopgExt?.detail ||
                'Required for zero-disk, zero-lock virtual B-Tree index simulations inside the PostgreSQL query planner.'}
            </div>
          </div>
        </div>
      </div>

      {/* Page 9 Requirement: Guided Database Connection Setup & Validation Workflow */}
      <div className="card" style={{ padding: '20px', borderColor: '#0284c7' }} data-testid="connection-validation-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <h2 style={{ margin: 0, fontSize: '1.15rem', color: '#f8fafc' }}>
                Guided Database Connection Setup &amp; Readiness Validation
              </h2>
              <span className="badge badge-info">6-STEP READINESS WIZARD</span>
            </div>
            <p style={{ margin: '4px 0 0 0', fontSize: '0.82rem', color: '#94a3b8' }}>
              Validate PostgreSQL connectivity, engine version compatibility, catalog monitoring permissions, and required extensions (<code>pg_stat_statements</code>, <code>hypopg</code>) without exposing credentials or raw connection strings in the browser.
            </p>
          </div>
        </div>

        <form onSubmit={handleRunValidation} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '10px' }}>
            <div>
              <label htmlFor="val-target" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                Connection Profile
              </label>
              <select
                id="val-target"
                className="filter-select"
                style={{ width: '100%' }}
                value={valTarget}
                onChange={(e) => setValTarget(e.target.value as 'primary' | 'sandbox')}
              >
                <option value="primary">Primary Telemetry Database</option>
                <option value="sandbox">Isolated Sandbox Database</option>
              </select>
            </div>

            <div>
              <label htmlFor="val-host" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                Host Label (Optional)
              </label>
              <input
                id="val-host"
                type="text"
                className="filter-input"
                style={{ width: '100%' }}
                placeholder="Configured server host"
                value={valHost}
                onChange={(e) => setValHost(e.target.value)}
              />
            </div>

            <div>
              <label htmlFor="val-port" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                Port
              </label>
              <input
                id="val-port"
                type="number"
                min={1}
                max={65535}
                className="filter-input"
                style={{ width: '100%' }}
                value={valPort}
                onChange={(e) => setValPort(Number(e.target.value))}
              />
            </div>

            <div>
              <label htmlFor="val-database" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                Database Name (Optional)
              </label>
              <input
                id="val-database"
                type="text"
                className="filter-input"
                style={{ width: '100%' }}
                placeholder="e.g. dbzenith"
                value={valDatabase}
                onChange={(e) => setValDatabase(e.target.value)}
              />
            </div>

            <div>
              <label htmlFor="val-ssl" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
                SSL Mode
              </label>
              <select
                id="val-ssl"
                className="filter-select"
                style={{ width: '100%' }}
                value={valSslMode}
                onChange={(e) => setValSslMode(e.target.value as any)}
              >
                <option value="prefer">prefer</option>
                <option value="require">require</option>
                <option value="verify-ca">verify-ca</option>
                <option value="verify-full">verify-full</option>
                <option value="disable">disable</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: '#cbd5e1', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={verifyExtensions}
                onChange={(e) => setVerifyExtensions(e.target.checked)}
              />
              Verify <code>pg_stat_statements</code> &amp; <code>hypopg</code> extension operational status
            </label>

            <button type="submit" className="btn btn-primary" disabled={validating}>
              {validating ? 'Running 6-Step Validation...' : '🔍 Validate Connection & Extensions'}
            </button>
          </div>
        </form>

        {validationError && (
          <div
            role="alert"
            style={{
              marginTop: '14px',
              padding: '10px 14px',
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid #ef4444',
              borderRadius: '6px',
              color: '#fca5a5',
              fontSize: '0.85rem',
            }}
          >
            <strong>Validation Error:</strong> {validationError}
          </div>
        )}

        {validationResult && (
          <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }} data-testid="validation-results-panel">
            <div
              style={{
                padding: '12px 14px',
                borderRadius: '6px',
                background:
                  validationResult.overall_status === 'ready'
                    ? 'rgba(16, 185, 129, 0.1)'
                    : validationResult.overall_status === 'degraded'
                    ? 'rgba(245, 158, 11, 0.1)'
                    : 'rgba(239, 68, 68, 0.1)',
                border:
                  validationResult.overall_status === 'ready'
                    ? '1px solid rgba(16, 185, 129, 0.35)'
                    : validationResult.overall_status === 'degraded'
                    ? '1px solid rgba(245, 158, 11, 0.35)'
                    : '1px solid rgba(239, 68, 68, 0.35)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '8px',
              }}
            >
              <div>
                <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#f8fafc' }}>
                  Validation Verdict: {(validationResult.overall_status ?? validationResult.overall_verdict ?? 'ready').toUpperCase()} ({validationResult.target_label ?? validationResult.target})
                </div>
                <div style={{ fontSize: '0.8rem', color: '#cbd5e1', marginTop: '2px' }}>
                  {validationResult.summary}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                <span className={`badge ${validationResult.feature_availability?.live_telemetry ? 'badge-success' : 'badge-warning'}`}>
                  Live Telemetry: {validationResult.feature_availability?.live_telemetry ? 'Enabled' : 'Unavailable'}
                </span>
                <span className={`badge ${validationResult.feature_availability?.hypothetical_indexing ? 'badge-success' : 'badge-warning'}`}>
                  HypoPG Sandbox: {validationResult.feature_availability?.hypothetical_indexing ? 'Enabled' : 'Fallback'}
                </span>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '10px' }}>
              {validationResult.steps.map((step, idx) => (
                <div
                  key={step.step}
                  style={{
                    background: '#090d16',
                    padding: '12px',
                    borderRadius: '6px',
                    border:
                      step.status === 'passed'
                        ? '1px solid rgba(16, 185, 129, 0.3)'
                        : step.status === 'warning'
                        ? '1px solid rgba(245, 158, 11, 0.35)'
                        : '1px solid rgba(239, 68, 68, 0.4)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#f8fafc' }}>
                      {idx + 1}. {step.title}
                    </span>
                    <span
                      className={`badge ${
                        step.status === 'passed'
                          ? 'badge-success'
                          : step.status === 'warning'
                          ? 'badge-warning'
                          : 'badge-danger'
                      }`}
                      style={{ fontSize: '0.68rem' }}
                    >
                      {step.status.toUpperCase()}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.78rem', color: '#cbd5e1', lineHeight: 1.4 }}>
                    {step.detail}
                  </div>
                  {step.remediation && (
                    <div
                      style={{
                        marginTop: '6px',
                        padding: '6px 8px',
                        background: 'rgba(245, 158, 11, 0.08)',
                        borderRadius: '4px',
                        fontSize: '0.74rem',
                        color: '#fcd34d',
                      }}
                    >
                      <strong>How to resolve:</strong> {step.remediation}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Runtime Telemetry Thresholds Configuration */}
      <div className="card" style={{ padding: '18px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1rem', color: '#f8fafc' }}>
              Runtime Telemetry Collector Thresholds
            </h3>
            <p style={{ margin: '2px 0 0 0', fontSize: '0.78rem', color: '#94a3b8' }}>
              Configure the slow query latency threshold and background telemetry sampling interval.
            </p>
          </div>
          <span className="badge badge-observed">
            {canApprove ? `Editable (${user?.role})` : `Read-Only (${user?.role || 'VIEWER'})`}
          </span>
        </div>

        <form onSubmit={handleSaveConfig} style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div>
            <label htmlFor="cfg-threshold-ms" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
              Slow Query Threshold (ms)
            </label>
            <input
              id="cfg-threshold-ms"
              type="number"
              min={5}
              max={60000}
              className="filter-input"
              disabled={!canApprove || savingConfig}
              value={thresholdMs}
              onChange={(e) => setThresholdMs(Number(e.target.value))}
            />
          </div>

          <div>
            <label htmlFor="cfg-poll-sec" style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', marginBottom: '4px' }}>
              Poll Interval (seconds)
            </label>
            <input
              id="cfg-poll-sec"
              type="number"
              min={5}
              max={3600}
              className="filter-input"
              disabled={!canApprove || savingConfig}
              value={pollSeconds}
              onChange={(e) => setPollSeconds(Number(e.target.value))}
            />
          </div>

          {canApprove && (
            <button type="submit" className="btn btn-primary" disabled={savingConfig}>
              {savingConfig ? 'Saving...' : 'Save Runtime Settings'}
            </button>
          )}
        </form>

        {configMsg && (
          <div
            role={configMsg.ok ? 'status' : 'alert'}
            style={{
              marginTop: '10px',
              fontSize: '0.8rem',
              color: configMsg.ok ? '#34d399' : '#fca5a5',
            }}
          >
            {configMsg.text}
          </div>
        )}
      </div>

      {/* Operational Invariants card */}
      <div className="card" style={{ padding: '18px' }}>
        <h3 style={{ margin: '0 0 10px 0', fontSize: '1rem', color: '#f8fafc' }}>
          Autonomous Runtime Invariants &amp; Safety Verification
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
