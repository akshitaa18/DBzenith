import { useEffect, useState } from 'react'
import { getRecommendations, Recommendation, createSimulation, Simulation } from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'

export function RecommendationsPage() {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(10)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedTraceId, setExpandedTraceId] = useState<number | null>(null)

  // Side-by-side comparison state
  const [selectedForCompare, setSelectedForCompare] = useState<number[]>([])
  const [compareModalOpen, setCompareModalOpen] = useState(false)

  // Simulation execution state
  const [simulatingId, setSimulatingId] = useState<number | null>(null)
  const [simulationResult, setSimulationResult] = useState<Simulation | null>(null)
  const [simError, setSimError] = useState<string | null>(null)

  const loadRecommendations = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getRecommendations(page, pageSize, statusFilter || undefined)
      setRecommendations(res.items || [])
      setTotal(res.total || 0)
    } catch (err: any) {
      setError(err?.message || 'Failed to load recommendations')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRecommendations()
  }, [page, statusFilter])

  const handleSimulate = async (recId: number) => {
    setSimulatingId(recId)
    setSimError(null)
    setSimulationResult(null)
    try {
      const sim = await createSimulation(recId, 3)
      setSimulationResult(sim)
    } catch (err: any) {
      setSimError(err?.message || 'Sandbox simulation failed')
    } finally {
      setSimulatingId(null)
    }
  }

  const toggleSelectForCompare = (id: number) => {
    if (selectedForCompare.includes(id)) {
      setSelectedForCompare(selectedForCompare.filter((i) => i !== id))
    } else {
      if (selectedForCompare.length >= 2) {
        setSelectedForCompare([selectedForCompare[1], id])
      } else {
        setSelectedForCompare([...selectedForCompare, id])
      }
    }
  }

  const filteredRecs = recommendations.filter((r) => {
    if (typeFilter !== 'all' && r.type !== typeFilter) return false
    if (search.trim()) {
      const q = search.toLowerCase()
      return (
        r.target.toLowerCase().includes(q) ||
        r.proposed_change.toLowerCase().includes(q) ||
        r.reason.toLowerCase().includes(q) ||
        r.type.toLowerCase().includes(q)
      )
    }
    return true
  })

  const distinctTypes = Array.from(new Set(recommendations.map((r) => r.type)))
  const compareItems = recommendations.filter((r) => selectedForCompare.includes(r.id))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Visual Workflow Header */}
      <OptimizationFlowHeader
        currentStage="recommend"
        subtitle="Optimization candidates synthesized from EXPLAIN bottlenecks, table bloat statistics, and RL policy scoring. Click 'Inspect Full Optimization Trace' on any card to evaluate."
      />

      {/* Self-Explanatory Advisor Engine Banner */}
      <div className="guide-banner">
        <div className="guide-banner-icon">💡</div>
        <div className="guide-banner-content">
          <div className="guide-banner-title">
            <span>AUTONOMOUS OPTIMIZATION ADVISORS & AI POLICIES</span>
            <span className="badge badge-recommendation">STAGE 3: RECOMMEND</span>
          </div>
          <p className="guide-banner-desc">
            Candidate optimizations synthesized across 4 advisory engines: <strong>Index Advisor</strong> (B-Trees and composite indexes), <strong>AST SQL Rewriter</strong> (eliminates redundant operations), <strong>Partition Advisor</strong>, and <strong>Join Reordering</strong>. Click <strong>"Simulate in Sandbox"</strong> on any recommendation to test in HypoPG before approving.
          </p>
          <div className="guide-banner-pills">
            <span className="badge badge-observed">4 Advisor Engines</span>
            <span className="badge badge-simulation">HypoPG Sandbox Gated</span>
            <span className="badge badge-approval-required">Human Approval Mandatory</span>
          </div>
        </div>
      </div>

      {/* Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>Index & Query Recommendations</h1>
            <span className="badge badge-recommendation">RECOMMENDATION</span>
            <span className="badge badge-approval-required">APPROVAL REQUIRED</span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            RL policies & heuristic engine candidate optimizations. All actions require DBA validation before execution.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button
            className="btn btn-secondary"
            disabled={selectedForCompare.length < 2}
            onClick={() => setCompareModalOpen(true)}
          >
            Compare Selected ({selectedForCompare.length}/2)
          </button>
          <button className="btn btn-primary" onClick={loadRecommendations}>
            Refresh
          </button>
        </div>
      </div>

      {/* Filter / Search Bar */}
      <div className="card" style={{ padding: '14px', display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="text"
          className="search-input"
          style={{ flex: 1, minWidth: '220px' }}
          placeholder="Search by target table, index name, or rationale..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Status:</label>
          <select
            className="filter-select"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value)
              setPage(1)
            }}
          >
            <option value="">All Statuses</option>
            <option value="pending">Pending Approval</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Type:</label>
          <select
            className="filter-select"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="all">All Types</option>
            {distinctTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Simulation Result Notification */}
      {simulationResult && (
        <div className="card" style={{ borderLeft: '4px solid #10b981', background: '#091512' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="badge badge-simulation">SIMULATION COMPLETED</span>
              <span style={{ fontWeight: 600, color: '#34d399' }}>
                Recommendation #{simulationResult.recommendation_id} Tested
              </span>
            </div>
            <button className="btn btn-secondary" style={{ fontSize: '0.75rem' }} onClick={() => setSimulationResult(null)}>
              Dismiss
            </button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px', marginTop: '12px' }}>
            <div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Baseline Cost:</div>
              <div style={{ fontFamily: 'monospace', color: '#f8fafc' }}>{simulationResult.baseline_cost?.toFixed(2) ?? 'N/A'}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Proposed Cost:</div>
              <div style={{ fontFamily: 'monospace', color: '#f8fafc' }}>{simulationResult.proposed_cost?.toFixed(2) ?? 'N/A'}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Improvement:</div>
              <div style={{ fontWeight: 700, color: (simulationResult.improvement ?? 0) > 0 ? '#10b981' : '#ef4444' }}>
                {simulationResult.improvement != null ? `${(simulationResult.improvement * 100).toFixed(1)}%` : '0%'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Confidence:</div>
              <div style={{ color: '#38bdf8' }}>{Math.round((simulationResult.confidence ?? 0) * 100)}%</div>
            </div>
          </div>
        </div>
      )}

      {simError && (
        <div className="card" style={{ borderColor: '#ef4444', background: 'rgba(239, 68, 68, 0.05)', color: '#fca5a5' }}>
          <strong>Sandbox Error:</strong> {simError}
        </div>
      )}

      {/* Loading & Error States */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '40px', color: '#94a3b8' }}>
          Querying optimization engine for active recommendations...
        </div>
      )}

      {error && (
        <div className="card" style={{ borderColor: '#ef4444', color: '#fca5a5' }}>
          Failed to load recommendations: {error}
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && filteredRecs.length === 0 && (
        <div className="card empty-state">
          No recommendations match the current search/status criteria.
        </div>
      )}

      {/* Recommendation Cards */}
      {!loading && !error && filteredRecs.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {filteredRecs.map((rec) => {
            const isComparing = selectedForCompare.includes(rec.id)
            return (
              <div
                key={rec.id}
                className="card"
                style={{
                  padding: '18px',
                  borderLeft:
                    rec.status === 'approved'
                      ? '4px solid #10b981'
                      : rec.status === 'rejected'
                      ? '4px solid #ef4444'
                      : '4px solid #f59e0b',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc' }}>
                      #{rec.id}
                    </span>
                    <span className="badge" style={{ background: '#1e293b', color: '#38bdf8', fontWeight: 600 }}>
                      {rec.type}
                    </span>
                    <span className="badge" style={{ background: '#090d16', border: '1px solid #334155', color: '#94a3b8' }}>
                      Target: {rec.target}
                    </span>
                    <span
                      className={`badge ${
                        rec.status === 'approved'
                          ? 'badge-success'
                          : rec.status === 'rejected'
                          ? 'badge-danger'
                          : 'badge-warning'
                      }`}
                    >
                      {rec.status.toUpperCase()}
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button
                      className="btn btn-secondary"
                      style={{ fontSize: '0.75rem', padding: '4px 10px' }}
                      onClick={() => setExpandedTraceId(expandedTraceId === rec.id ? null : rec.id)}
                    >
                      {expandedTraceId === rec.id ? 'Hide Trace' : '🔍 Inspect Trace'}
                    </button>
                    <button
                      className="btn btn-secondary"
                      style={{ fontSize: '0.75rem', padding: '4px 10px' }}
                      onClick={() => toggleSelectForCompare(rec.id)}
                    >
                      {isComparing ? '✓ Selected' : '+ Compare'}
                    </button>
                    {rec.requires_approval && rec.status === 'pending' && (
                      <button
                        className="btn btn-primary"
                        style={{ fontSize: '0.75rem', padding: '4px 10px' }}
                        disabled={simulatingId === rec.id}
                        onClick={() => handleSimulate(rec.id)}
                      >
                        {simulatingId === rec.id ? 'Simulating...' : 'Sandbox Simulate'}
                      </button>
                    )}
                  </div>
                </div>

                {/* Proposed Change SQL / Action */}
                <div style={{ marginTop: '14px' }}>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '4px', textTransform: 'uppercase' }}>
                    Proposed DDL / Change
                  </div>
                  <pre
                    style={{
                      margin: 0,
                      background: '#090d16',
                      padding: '10px 14px',
                      borderRadius: '6px',
                      border: '1px solid #1e293b',
                      fontSize: '0.85rem',
                      fontFamily: 'monospace',
                      color: '#a78bfa',
                      overflowX: 'auto',
                    }}
                  >
                    {rec.proposed_change}
                  </pre>
                </div>

                {/* Rationale & Expected Benefit */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px', marginTop: '14px' }}>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Rationale</div>
                    <div style={{ fontSize: '0.875rem', color: '#cbd5e1', marginTop: '4px' }}>{rec.reason}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Expected Benefit</div>
                    <div style={{ fontSize: '0.875rem', color: '#34d399', marginTop: '4px', fontWeight: 500 }}>
                      {rec.expected_benefit}
                    </div>
                  </div>
                </div>

                {/* Metric Footer */}
                <div
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: '16px',
                    marginTop: '14px',
                    paddingTop: '12px',
                    borderTop: '1px solid #1e293b',
                    fontSize: '0.8rem',
                    color: '#64748b',
                  }}
                >
                  <div>
                    Risk Rating: <strong style={{ color: rec.risk === 'low' ? '#10b981' : '#f59e0b' }}>{rec.risk.toUpperCase()}</strong>
                  </div>
                  <div>
                    Confidence: <strong style={{ color: '#38bdf8' }}>{Math.round(rec.confidence * 100)}%</strong>
                  </div>
                  <div>
                    Affected Queries: <strong style={{ color: '#cbd5e1' }}>{rec.affected_queries?.length ?? 0}</strong>
                  </div>
                  <div>
                    Created: <span style={{ color: '#94a3b8' }}>{new Date(rec.created_at).toLocaleString()}</span>
                  </div>
                </div>

                {/* Expandable Optimization Trace */}
                {expandedTraceId === rec.id && (
                  <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px dashed #334155' }}>
                    <OptimizationTrace
                      title={`End-to-End Optimization Trace: Recommendation #${rec.id}`}
                      recommendation={rec}
                      simulation={simulationResult?.recommendation_id === rec.id ? simulationResult : undefined}
                      onSimulate={(id) => handleSimulate(id)}
                      isSimulating={simulatingId === rec.id}
                      initialExpanded={true}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {!loading && total > pageSize && (
        <div className="pagination">
          <button
            className="btn btn-secondary"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <span style={{ fontSize: '0.875rem', color: '#94a3b8' }}>
            Page {page} of {Math.ceil(total / pageSize)} ({total} total)
          </span>
          <button
            className="btn btn-secondary"
            disabled={page >= Math.ceil(total / pageSize)}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      )}

      {/* Side-by-Side Comparison Modal */}
      {compareModalOpen && compareItems.length === 2 && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '20px',
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: '900px',
              width: '100%',
              maxHeight: '85vh',
              overflowY: 'auto',
              padding: '24px',
              border: '1px solid #38bdf8',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <h3 style={{ margin: 0, fontSize: '1.25rem' }}>Recommendation Side-by-Side Comparison</h3>
                <span className="badge badge-recommendation">RECOMMENDATION</span>
              </div>
              <button className="btn btn-secondary" onClick={() => setCompareModalOpen(false)}>
                Close
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              {compareItems.map((item, idx) => (
                <div
                  key={item.id}
                  style={{
                    background: '#090d16',
                    border: '1px solid #1e293b',
                    borderRadius: '6px',
                    padding: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px',
                  }}
                >
                  <div style={{ fontWeight: 700, color: '#38bdf8', fontSize: '1.1rem' }}>
                    Option {idx + 1}: Recommendation #{item.id}
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Type / Target:</span>
                    <div style={{ fontWeight: 600, color: '#f8fafc' }}>{item.type} on {item.target}</div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Proposed Action:</span>
                    <pre
                      style={{
                        margin: '4px 0 0 0',
                        padding: '8px',
                        background: '#151f32',
                        borderRadius: '4px',
                        fontSize: '0.75rem',
                        color: '#a78bfa',
                      }}
                    >
                      {item.proposed_change}
                    </pre>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Expected Benefit:</span>
                    <div style={{ color: '#34d399', fontSize: '0.85rem' }}>{item.expected_benefit}</div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Risk Rating:</span>
                    <div style={{ fontWeight: 600, color: item.risk === 'low' ? '#10b981' : '#f59e0b' }}>
                      {item.risk.toUpperCase()}
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Confidence:</span>
                    <div style={{ color: '#38bdf8', fontWeight: 600 }}>{Math.round(item.confidence * 100)}%</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
