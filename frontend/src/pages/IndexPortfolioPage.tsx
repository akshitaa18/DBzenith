import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  analyzeIndexPortfolio,
  exportIndexPortfolio,
  getIndexPortfolio,
  type IndexPortfolioResponse,
} from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { ProvenanceBadge } from '../components/ProvenanceBadge'

type PortfolioTab = 'overlapping' | 'low_usage' | 'proposals' | 'catalog'

export function IndexPortfolioPage() {
  const { user, hasMinRole } = useAuth()
  const userRole = user?.role ?? 'VIEWER'
  const canExportOrAnalyze = hasMinRole('ANALYST')

  const [portfolio, setPortfolio] = useState<IndexPortfolioResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<PortfolioTab>('overlapping')

  // Filters & Pagination for Catalog
  const [tableFilter, setTableFilter] = useState<string>('')
  const [usageFilter, setUsageFilter] = useState<string>('')
  const [amFilter, setAmFilter] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [page, setPage] = useState<number>(1)
  const pageSize = 20

  const [syncing, setSyncing] = useState<boolean>(false)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [exporting, setExporting] = useState<boolean>(false)

  const fetchPortfolio = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getIndexPortfolio({
        table_name: tableFilter || undefined,
        usage_classification: usageFilter || undefined,
        access_method: amFilter || undefined,
        search: searchQuery || undefined,
        page,
        page_size: pageSize,
      })
      setPortfolio(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load index portfolio analysis')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchPortfolio()
  }, [tableFilter, usageFilter, amFilter, page])

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    void fetchPortfolio()
  }

  const handleSyncToLifecycle = async () => {
    if (!canExportOrAnalyze) return
    setSyncing(true)
    setSyncMessage(null)
    setError(null)
    try {
      const res = await analyzeIndexPortfolio(true)
      setPortfolio(res.portfolio)
      setSyncMessage(
        res.persisted_count > 0
          ? `Synced ${res.persisted_count} new index candidate(s) into the Optimization Lifecycle Tracker.`
          : 'All high-confidence index candidates are already tracked in the Optimization Lifecycle Tracker.',
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to sync index candidates')
    } finally {
      setSyncing(false)
    }
  }

  const handleExport = async (format: 'json' | 'csv') => {
    if (!canExportOrAnalyze) return
    setExporting(true)
    setError(null)
    try {
      const content = await exportIndexPortfolio(format)
      const blob = new Blob([content], {
        type: format === 'csv' ? 'text/csv;charset=utf-8;' : 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `dbzenith-index-portfolio.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setExporting(false)
    }
  }

  const statsStatus = portfolio?.statistics_status
  const summary = portfolio?.summary

  return (
    <div className="space-y-6" data-testid="index-portfolio-page">
      {/* Header */}
      <div className="card" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '16px', alignItems: 'center' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <h1 style={{ fontSize: '22px', fontWeight: 700, margin: 0 }}>
                PostgreSQL Index Portfolio Advisor
              </h1>
              {portfolio && (
                <ProvenanceBadge
                  state={portfolio.provenance_state}
                  isSynthetic={portfolio.is_synthetic}
                />
              )}
            </div>
            <p style={{ margin: '6px 0 0', fontSize: '13px', color: '#94a3b8' }}>
              Read-only catalog inspection for duplicate/overlapping B-tree indexes, low-usage overhead, and workload-driven composite or partial index candidates.
            </p>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <button
              type="button"
              onClick={() => void fetchPortfolio()}
              disabled={loading}
              className="btn"
            >
              {loading ? 'Refreshing...' : 'Refresh Catalog'}
            </button>

            <button
              type="button"
              onClick={() => void handleSyncToLifecycle()}
              disabled={!canExportOrAnalyze || syncing}
              title={
                canExportOrAnalyze
                  ? 'Sync index proposals to the Optimization Lifecycle Tracker'
                  : `Requires ANALYST, DBA, or ADMIN role (current: ${userRole})`
              }
              className="btn btn-primary"
            >
              {syncing ? 'Syncing Candidates...' : 'Sync Candidates to Lifecycle'}
            </button>

            <button
              type="button"
              onClick={() => void handleExport('csv')}
              disabled={!canExportOrAnalyze || exporting}
              title={canExportOrAnalyze ? 'Export Index Catalog CSV' : 'Requires ANALYST, DBA, or ADMIN role'}
              className="btn"
            >
              Export CSV
            </button>
            <button
              type="button"
              onClick={() => void handleExport('json')}
              disabled={!canExportOrAnalyze || exporting}
              title={canExportOrAnalyze ? 'Export Portfolio Report JSON' : 'Requires ANALYST, DBA, or ADMIN role'}
              className="btn"
            >
              Export JSON
            </button>
          </div>
        </div>
      </div>

      {/* Governance & Safety Notice */}
      <div
        className="card"
        style={{
          padding: '14px 18px',
          borderLeft: '4px solid #06b6d4',
          background: 'rgba(8, 145, 178, 0.12)',
        }}
        data-testid="portfolio-governance-notice"
      >
        <div style={{ fontSize: '13px', lineHeight: 1.5 }}>
          <strong style={{ color: '#67e8f9' }}>
            Candidate Requiring DBA Review (Read-Only Catalog Analysis):
          </strong>{' '}
          {portfolio?.governance_notice ??
            'All index recommendations are advisory candidates requiring human DBA review. DBZenith never automatically drops or creates indexes in production.'}
        </div>
      </div>

      {/* Statistics Completeness & Reset Warning Banner */}
      {statsStatus && (statsStatus.stats_recently_reset || statsStatus.incomplete_statistics || statsStatus.warnings.length > 0) && (
        <div
          className="card"
          style={{
            padding: '14px 18px',
            borderLeft: '4px solid #f59e0b',
            background: 'rgba(245, 158, 11, 0.12)',
          }}
          data-testid="stats-completeness-banner"
        >
          <div style={{ fontSize: '13px', fontWeight: 700, color: '#fbbf24', marginBottom: '4px' }}>
            Incomplete or Recently Reset PostgreSQL Catalog Statistics Detected
          </div>
          <div style={{ fontSize: '12px', color: '#fde68a', marginBottom: '6px' }}>
            {statsStatus.stats_age_hours != null
              ? `pg_stat_database statistics window age: ${statsStatus.stats_age_hours} hours`
              : 'pg_stat_database.stats_reset timestamp is unavailable (statistics window age unknown).'}
            {statsStatus.stats_recently_reset && ' — Low scan counters do NOT prove an index is unused.'}
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: '#fef3c7' }}>
            {statsStatus.warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {syncMessage && (
        <div
          className="card"
          style={{
            padding: '12px 16px',
            borderLeft: '4px solid #10b981',
            background: 'rgba(16, 185, 129, 0.12)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: '13px',
          }}
        >
          <span>{syncMessage}</span>
          <Link to="/recommendations" style={{ color: '#34d399', fontWeight: 600 }}>
            View Recommendations →
          </Link>
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

      {/* Summary Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '14px',
        }}
      >
        <div className="card" style={{ padding: '16px' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Catalog Indexes</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px' }}>
            {summary?.total_indexes ?? 0}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Total footprint: <strong>{summary?.total_index_size_pretty ?? '0 B'}</strong>
          </div>
        </div>

        <div className="card" style={{ padding: '16px' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Overlapping / Duplicate</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px', color: '#fbbf24' }}>
            {summary?.duplicate_or_overlapping_count ?? 0}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Exact or B-tree left-prefix overlap
          </div>
        </div>

        <div className="card" style={{ padding: '16px' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Low-Usage Candidates</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px', color: '#fb923c' }}>
            {summary?.low_usage_candidate_count ?? 0}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Non-unique indexes with low scan activity
          </div>
        </div>

        <div className="card" style={{ padding: '16px' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Composite / Partial Proposals</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px', color: '#34d399' }}>
            {summary?.missing_or_composite_proposals_count ?? 0}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Backed by observed query predicates
          </div>
        </div>

        <div className="card" style={{ padding: '16px' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>Est. Reclaimable Space</div>
          <div style={{ fontSize: '26px', fontWeight: 700, marginTop: '6px', color: '#818cf8' }}>
            {summary?.reclaimable_pretty_estimate ?? '0 B'}
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
            Pending DBA verification & staging check
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', borderBottom: '1px solid #1e293b', paddingBottom: '12px' }}>
        <button
          type="button"
          onClick={() => setActiveTab('overlapping')}
          className={activeTab === 'overlapping' ? 'btn btn-primary' : 'btn'}
        >
          Overlapping & Duplicate Candidates ({portfolio?.overlapping_candidates.length ?? 0})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('low_usage')}
          className={activeTab === 'low_usage' ? 'btn btn-primary' : 'btn'}
        >
          Low-Usage Review Candidates ({portfolio?.low_usage_candidates.length ?? 0})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('proposals')}
          className={activeTab === 'proposals' ? 'btn btn-primary' : 'btn'}
        >
          Composite & Partial Proposals ({portfolio?.missing_index_proposals.length ?? 0})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('catalog')}
          className={activeTab === 'catalog' ? 'btn btn-primary' : 'btn'}
        >
          Full Index Catalog ({portfolio?.pagination.total_indexes ?? 0})
        </button>
      </div>

      {/* Tab 1: Overlapping & Duplicate Candidates */}
      {activeTab === 'overlapping' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {!portfolio?.overlapping_candidates.length ? (
            <div className="card" style={{ padding: '28px', textAlign: 'center', color: '#94a3b8' }}>
              No duplicate or left-prefix overlapping B-tree indexes detected in the current catalog.
            </div>
          ) : (
            portfolio.overlapping_candidates.map((cand) => (
              <div
                key={`${cand.index_name}-${cand.overlapping_with_index}`}
                className="card"
                style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '12px' }}
              >
                <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px' }}>
                    <span className="badge" style={{ background: 'rgba(245, 158, 11, 0.2)', color: '#fbbf24' }}>
                      {cand.label}
                    </span>
                    <code style={{ fontSize: '12px', color: '#67e8f9' }}>
                      {cand.schema_name}.{cand.table_name}
                    </code>
                    <strong style={{ fontSize: '15px' }}>{cand.index_name}</strong>
                    <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                      covered by <code style={{ color: '#34d399' }}>{cand.overlapping_with_index}</code>
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', fontSize: '12px' }}>
                    <span className="badge">Size: {cand.index_size_pretty}</span>
                    <span className="badge">Confidence: {Math.round(cand.confidence * 100)}%</span>
                    <span className="badge" style={{ background: 'rgba(239, 68, 68, 0.2)', color: '#fca5a5' }}>
                      Auto-Drop: Forbidden
                    </span>
                  </div>
                </div>

                <p style={{ margin: 0, fontSize: '13px', color: '#cbd5e1', lineHeight: 1.5 }}>
                  {cand.rationale}
                </p>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                    gap: '12px',
                    padding: '12px',
                    background: 'rgba(15, 23, 42, 0.6)',
                    borderRadius: '8px',
                    fontSize: '12px',
                  }}
                >
                  <div>
                    <div style={{ color: '#94a3b8' }}>Narrow Key Columns:</div>
                    <code style={{ color: '#fbbf24' }}>({cand.narrow_columns.join(', ')})</code>
                    <div style={{ color: '#94a3b8', marginTop: '4px' }}>
                      Scans: {cand.idx_scan.toLocaleString()}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: '#94a3b8' }}>Covering Index Columns:</div>
                    <code style={{ color: '#34d399' }}>({cand.covering_columns.join(', ')})</code>
                    <div style={{ color: '#94a3b8', marginTop: '4px' }}>
                      Covering Scans: {cand.covering_idx_scan.toLocaleString()}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: '#94a3b8' }}>Table Write Overhead:</div>
                    <strong>{cand.table_writes_total.toLocaleString()} tuple writes</strong>
                    <div style={{ color: '#94a3b8', marginTop: '4px' }}>
                      Risk Level: <strong style={{ textTransform: 'uppercase' }}>{cand.risk_level}</strong>
                    </div>
                  </div>
                </div>

                <div style={{ fontSize: '12px', color: '#fde68a' }}>
                  <strong>Risk & Safety Notes:</strong> {cand.risk_notes}
                </div>

                <pre
                  style={{
                    margin: 0,
                    padding: '12px',
                    background: '#090d16',
                    borderRadius: '8px',
                    fontSize: '12px',
                    overflowX: 'auto',
                    color: '#a5f3fc',
                  }}
                >
                  {cand.review_sql}
                </pre>
              </div>
            ))
          )}
        </div>
      )}

      {/* Tab 2: Low-Usage Review Candidates */}
      {activeTab === 'low_usage' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {!portfolio?.low_usage_candidates.length ? (
            <div className="card" style={{ padding: '28px', textAlign: 'center', color: '#94a3b8' }}>
              No low-usage non-constraint indexes identified.
            </div>
          ) : (
            portfolio.low_usage_candidates.map((item) => (
              <div
                key={item.index_name}
                className="card"
                style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '12px' }}
              >
                <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px' }}>
                    <span className="badge" style={{ background: 'rgba(249, 115, 22, 0.2)', color: '#fdba74' }}>
                      {item.label}
                    </span>
                    <strong style={{ fontSize: '15px' }}>{item.index_name}</strong>
                    <code style={{ fontSize: '12px', color: '#94a3b8' }}>
                      {item.table_name} ({item.key_columns.join(', ')})
                    </code>
                    {item.stats_recently_reset && (
                      <span className="badge" style={{ background: 'rgba(245, 158, 11, 0.25)', color: '#fde68a' }}>
                        Stats Recently Reset / Incomplete
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: '8px', fontSize: '12px' }}>
                    <span className="badge">idx_scan: {item.idx_scan}</span>
                    <span className="badge">Size: {item.index_size_pretty}</span>
                    <span className="badge">Table Writes: {item.table_writes_total.toLocaleString()}</span>
                  </div>
                </div>

                <p style={{ margin: 0, fontSize: '13px', color: '#cbd5e1', lineHeight: 1.5 }}>
                  {item.rationale}
                </p>

                <div style={{ fontSize: '12px', color: '#fde68a' }}>
                  <strong>Why Automatic Drop Is Prohibited:</strong> {item.risk_notes}
                </div>

                <pre
                  style={{
                    margin: 0,
                    padding: '12px',
                    background: '#090d16',
                    borderRadius: '8px',
                    fontSize: '12px',
                    overflowX: 'auto',
                    color: '#a5f3fc',
                  }}
                >
                  {item.review_sql}
                </pre>
              </div>
            ))
          )}
        </div>
      )}

      {/* Tab 3: Composite & Partial Proposals */}
      {activeTab === 'proposals' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {!portfolio?.missing_index_proposals.length ? (
            <div className="card" style={{ padding: '28px', textAlign: 'center', color: '#94a3b8' }}>
              All hot query filter, join, and sort patterns are covered by existing catalog indexes.
            </div>
          ) : (
            portfolio.missing_index_proposals.map((prop) => (
              <div
                key={prop.index_name}
                className="card"
                style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '12px' }}
              >
                <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px' }}>
                    <span className="badge" style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#6ee7b7' }}>
                      {prop.label}
                    </span>
                    <code style={{ fontSize: '12px', color: '#67e8f9' }}>{prop.candidate_type}</code>
                    <strong style={{ fontSize: '15px' }}>{prop.index_name}</strong>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', fontSize: '12px' }}>
                    <span className="badge" style={{ color: '#6ee7b7' }}>
                      Est. Benefit (Unverified): ~{prop.expected_benefit_pct}%
                    </span>
                    <span className="badge">Confidence: {Math.round(prop.confidence * 100)}%</span>
                    <span className="badge">Risk: {prop.risk_level.toUpperCase()}</span>
                  </div>
                </div>

                <p style={{ margin: 0, fontSize: '13px', color: '#cbd5e1', lineHeight: 1.5 }}>
                  {prop.rationale}
                </p>

                <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                  <strong>Write Overhead Assessment:</strong> {prop.write_overhead_assessment}
                </div>

                {prop.supporting_queries.length > 0 && (
                  <div style={{ fontSize: '12px' }}>
                    <strong>Supporting Query Fingerprints ({prop.supporting_query_count}):</strong>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '6px' }}>
                      {prop.supporting_queries.map((sq) => (
                        <Link
                          key={`${sq.query_id}-${sq.query_fingerprint}`}
                          to={`/queries?queryId=${sq.query_id}`}
                          className="badge"
                          style={{ color: '#38bdf8', textDecoration: 'none' }}
                        >
                          {sq.query_fingerprint} (Query #{sq.query_id} · {sq.mean_exec_time_ms.toFixed(1)} ms)
                        </Link>
                      ))}
                    </div>
                  </div>
                )}

                <pre
                  style={{
                    margin: 0,
                    padding: '12px',
                    background: '#090d16',
                    borderRadius: '8px',
                    fontSize: '12px',
                    overflowX: 'auto',
                    color: '#6ee7b7',
                  }}
                >
                  {prop.proposed_sql}
                </pre>
              </div>
            ))
          )}

          {/* Column Access Analysis Table */}
          {portfolio?.column_access_analysis && portfolio.column_access_analysis.length > 0 && (
            <div className="card" style={{ padding: '18px' }}>
              <h3 style={{ marginTop: 0, fontSize: '14px', fontWeight: 700 }}>
                Frequently Filtered, Joined & Ordered Columns (Workload Evidence)
              </h3>
              <div style={{ overflowX: 'auto' }}>
                <table className="table" style={{ width: '100%', fontSize: '12px' }}>
                  <thead>
                    <tr>
                      <th>Table.Column</th>
                      <th>Equality (=)</th>
                      <th>Range (&lt;/&gt;)</th>
                      <th>Joins</th>
                      <th>Order / Group</th>
                      <th>Weighted Exec Time</th>
                      <th>Selectivity (pg_stats)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {portfolio.column_access_analysis.slice(0, 12).map((col) => (
                      <tr key={`${col.table_name}.${col.column_name}`}>
                        <td>
                          <code>
                            {col.table_name}.{col.column_name}
                          </code>
                        </td>
                        <td>{col.equality_filter_count}</td>
                        <td>{col.range_filter_count}</td>
                        <td>{col.join_count}</td>
                        <td>{col.order_by_count + col.group_by_count}</td>
                        <td>
                          {col.total_weighted_exec_ms.toFixed(1)} ms ({col.total_weighted_calls} calls)
                        </td>
                        <td>
                          {col.selectivity
                            ? `${col.selectivity.estimated_selectivity_class ?? 'known'} (n_distinct=${col.selectivity.n_distinct ?? 'n/a'})`
                            : 'pg_stats unavailable'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab 4: Full Index Catalog */}
      {activeTab === 'catalog' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {/* Filter Bar */}
          <form
            onSubmit={handleSearchSubmit}
            className="card"
            style={{ padding: '14px', display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center' }}
          >
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search index name, table, column, or SQL..."
              style={{ flex: 1, minWidth: '200px', padding: '6px 10px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
            />
            <input
              type="text"
              value={tableFilter}
              onChange={(e) => {
                setTableFilter(e.target.value)
                setPage(1)
              }}
              placeholder="Table name..."
              style={{ width: '140px', padding: '6px 10px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
            />
            <select
              aria-label="Filter by usage classification"
              value={usageFilter}
              onChange={(e) => {
                setUsageFilter(e.target.value)
                setPage(1)
              }}
              style={{ padding: '6px 10px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
            >
              <option value="">All Usage States</option>
              <option value="active">Active</option>
              <option value="unused">Unused (0 scans)</option>
              <option value="low_usage">Low Usage (&lt;10 scans)</option>
              <option value="constraint_enforcing">Constraint / Primary Key</option>
            </select>
            <select
              aria-label="Filter by access method"
              value={amFilter}
              onChange={(e) => {
                setAmFilter(e.target.value)
                setPage(1)
              }}
              style={{ padding: '6px 10px', borderRadius: '6px', background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', fontSize: '12px' }}
            >
              <option value="">All Access Methods</option>
              <option value="btree">btree</option>
              <option value="gin">gin</option>
              <option value="gist">gist</option>
              <option value="brin">brin</option>
              <option value="hash">hash</option>
            </select>
            <button type="submit" className="btn">
              Apply
            </button>
          </form>

          {/* Unsupported Index Type Notices */}
          {portfolio?.unsupported_index_notices && portfolio.unsupported_index_notices.length > 0 && (
            <div className="card" style={{ padding: '14px', borderLeft: '4px solid #6366f1' }}>
              <div style={{ fontSize: '12px', fontWeight: 700, color: '#a5b4fc', marginBottom: '6px' }}>
                Non-B-tree Access Method Notices ({portfolio.unsupported_index_notices.length})
              </div>
              {portfolio.unsupported_index_notices.map((n) => (
                <div key={n.index_name} style={{ fontSize: '12px', color: '#cbd5e1' }}>
                  • <code>{n.index_name}</code> ({n.access_method.toUpperCase()} on <code>{n.table_name}</code>): {n.notice}
                </div>
              ))}
            </div>
          )}

          {/* Catalog Table */}
          <div className="card" style={{ padding: '0', overflowX: 'auto' }}>
            <table className="table" style={{ width: '100%', fontSize: '12px' }}>
              <thead>
                <tr>
                  <th>Index Name</th>
                  <th>Table</th>
                  <th>Method</th>
                  <th>Key Columns / Predicate</th>
                  <th>Size</th>
                  <th>Scans (idx_scan)</th>
                  <th>Table Writes</th>
                  <th>Classification</th>
                </tr>
              </thead>
              <tbody>
                {portfolio?.indexes.map((idx) => (
                  <tr key={`${idx.schema_name}.${idx.index_name}`}>
                    <td>
                      <code>{idx.index_name}</code>
                      {idx.is_primary && (
                        <span className="badge" style={{ marginLeft: '6px', fontSize: '10px' }}>
                          PK
                        </span>
                      )}
                      {!idx.is_primary && idx.is_unique && (
                        <span className="badge" style={{ marginLeft: '6px', fontSize: '10px' }}>
                          UNIQUE
                        </span>
                      )}
                    </td>
                    <td>
                      <code>
                        {idx.schema_name}.{idx.table_name}
                      </code>
                    </td>
                    <td style={{ textTransform: 'uppercase' }}>{idx.access_method}</td>
                    <td>
                      <code>({idx.key_columns.join(', ')})</code>
                      {idx.where_predicate && (
                        <div style={{ fontSize: '11px', color: '#34d399' }}>
                          WHERE {idx.where_predicate}
                        </div>
                      )}
                    </td>
                    <td>{idx.index_size_pretty}</td>
                    <td>
                      {idx.idx_scan.toLocaleString()}
                      {!idx.stats_available && (
                        <div style={{ fontSize: '10px', color: '#fbbf24' }}>stats missing</div>
                      )}
                    </td>
                    <td>{idx.table_writes_total.toLocaleString()}</td>
                    <td>
                      <span className="badge">{idx.usage_classification}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
