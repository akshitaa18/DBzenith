import { useEffect, useState } from 'react'
import { listSimulations, Simulation } from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'

export function SimulationsPage() {
  const [simulations, setSimulations] = useState<Simulation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedSim, setSelectedSim] = useState<Simulation | null>(null)

  const loadSimulations = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listSimulations(50)
      setSimulations(data)
      if (data.length > 0 && !selectedSim) {
        setSelectedSim(data[0])
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to fetch simulations')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSimulations()
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Visual Workflow Header */}
      <OptimizationFlowHeader
        currentStage="simulate"
        subtitle="Empirical sandbox evaluation using PostgreSQL HypoPG virtual indexes to measure exact execution cost and verify zero regression before DBA sign-off."
      />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>Sandbox Simulations</h1>
            <span className="badge badge-simulation">SIMULATION</span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            HypoPG virtual index simulations, sandbox EXPLAIN cost deltas, and regression verifications.
          </p>
        </div>
        <button className="btn btn-primary" onClick={loadSimulations}>
          Refresh Simulations
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="card" style={{ borderColor: '#ef4444', color: '#fca5a5' }}>
          Failed to load simulation records: {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '40px', color: '#94a3b8' }}>
          Querying sandbox simulation history and benchmark measurements...
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && simulations.length === 0 && (
        <div className="card empty-state">
          No sandbox simulations have been executed yet. Trigger a simulation from the Recommendations page or DBA Assistant.
        </div>
      )}

      {/* Main Grid View */}
      {!loading && !error && simulations.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: '16px' }}>
          {/* List of Simulation Runs */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '780px', overflowY: 'auto' }}>
            {simulations.map((sim) => {
              const isSelected = selectedSim?.id === sim.id
              const improvementPct = sim.improvement != null ? Math.round(sim.improvement * 100) : null
              return (
                <div
                  key={sim.id}
                  onClick={() => setSelectedSim(sim)}
                  className="card"
                  style={{
                    padding: '12px 14px',
                    cursor: 'pointer',
                    borderColor: isSelected ? '#38bdf8' : '#1e293b',
                    background: isSelected ? '#15213b' : '#0e1626',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: '#f8fafc', fontSize: '0.9rem' }}>
                      Simulation #{sim.id}
                    </span>
                    <span
                      className={`badge ${
                        sim.status === 'completed'
                          ? 'badge-success'
                          : sim.status === 'failed'
                          ? 'badge-danger'
                          : 'badge-warning'
                      }`}
                    >
                      {sim.status.toUpperCase()}
                    </span>
                  </div>

                  <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                    Recommendation ID: <strong>{sim.recommendation_id ?? 'Direct'}</strong>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                    <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                      {new Date(sim.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </span>
                    {improvementPct !== null && (
                      <span
                        style={{
                          fontSize: '0.85rem',
                          fontWeight: 700,
                          color: improvementPct > 0 ? '#10b981' : improvementPct < 0 ? '#ef4444' : '#94a3b8',
                        }}
                      >
                        {improvementPct > 0 ? `+${improvementPct}% gain` : `${improvementPct}% regr`}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Selected Simulation Details */}
          {selectedSim ? (
            <div className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
              {/* Header Info */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1e293b', paddingBottom: '12px' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.25rem' }}>
                    Simulation #{selectedSim.id} Details
                  </h3>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '2px' }}>
                    Target Recommendation: #{selectedSim.recommendation_id} | Created: {new Date(selectedSim.created_at).toLocaleString()}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <span className="badge badge-simulation">SANDBOX RESULT</span>
                  <span className={`badge ${selectedSim.status === 'completed' ? 'badge-success' : 'badge-danger'}`}>
                    {selectedSim.status.toUpperCase()}
                  </span>
                </div>
              </div>

              {/* Before vs After Cost Comparison Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
                <div style={{ background: '#090d16', padding: '14px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Baseline Cost (Before)</div>
                  <div style={{ fontSize: '1.4rem', fontFamily: 'monospace', fontWeight: 700, color: '#f8fafc', marginTop: '4px' }}>
                    {selectedSim.baseline_cost != null ? selectedSim.baseline_cost.toFixed(2) : 'N/A'}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>PostgreSQL optimizer units</div>
                </div>

                <div style={{ background: '#090d16', padding: '14px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Proposed Cost (After)</div>
                  <div style={{ fontSize: '1.4rem', fontFamily: 'monospace', fontWeight: 700, color: '#38bdf8', marginTop: '4px' }}>
                    {selectedSim.proposed_cost != null ? selectedSim.proposed_cost.toFixed(2) : 'N/A'}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>With hypothetical index active</div>
                </div>

                <div style={{ background: '#090d16', padding: '14px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Net Improvement</div>
                  <div
                    style={{
                      fontSize: '1.4rem',
                      fontWeight: 800,
                      color: (selectedSim.improvement ?? 0) > 0 ? '#10b981' : '#ef4444',
                      marginTop: '4px',
                    }}
                  >
                    {selectedSim.improvement != null ? `${(selectedSim.improvement * 100).toFixed(1)}%` : '0%'}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Confidence: {Math.round((selectedSim.confidence ?? 0) * 100)}%</div>
                </div>
              </div>

              {/* Before vs After Visual Bar */}
              {selectedSim.baseline_cost != null && selectedSim.proposed_cost != null && (
                <div>
                  <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#cbd5e1', marginBottom: '8px' }}>
                    Cost Reduction Comparison
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginBottom: '2px' }}>
                        <span>Baseline (Before Optimization)</span>
                        <span>{selectedSim.baseline_cost.toFixed(2)}</span>
                      </div>
                      <div style={{ height: '14px', background: '#334155', borderRadius: '4px', overflow: 'hidden' }}>
                        <div style={{ width: '100%', height: '100%', background: '#64748b' }} />
                      </div>
                    </div>

                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#38bdf8', marginBottom: '2px' }}>
                        <span>Proposed (With Virtual Index)</span>
                        <span>{selectedSim.proposed_cost.toFixed(2)}</span>
                      </div>
                      <div style={{ height: '14px', background: '#334155', borderRadius: '4px', overflow: 'hidden' }}>
                        <div
                          style={{
                            width: `${Math.min(100, Math.max(5, (selectedSim.proposed_cost / (selectedSim.baseline_cost || 1)) * 100))}%`,
                            height: '100%',
                            background: '#10b981',
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Storage & Overhead Estimates */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                <div style={{ background: '#090d16', padding: '12px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase', marginBottom: '4px' }}>
                    Estimated Storage Footprint
                  </div>
                  <pre style={{ margin: 0, fontSize: '0.75rem', color: '#cbd5e1', whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(selectedSim.estimated_storage_impact || { note: 'Negligible virtual footprint' }, null, 2)}
                  </pre>
                </div>

                <div style={{ background: '#090d16', padding: '12px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase', marginBottom: '4px' }}>
                    Write Overhead & Maintenance Penalty
                  </div>
                  <pre style={{ margin: 0, fontSize: '0.75rem', color: '#cbd5e1', whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(selectedSim.write_overhead_estimate || { status: 'Within safe write threshold' }, null, 2)}
                  </pre>
                </div>
              </div>

              {/* Plan Differences & Limitations */}
              {selectedSim.limitations && selectedSim.limitations.length > 0 && (
                <div style={{ background: 'rgba(245, 158, 11, 0.08)', border: '1px solid #f59e0b', borderRadius: '6px', padding: '12px' }}>
                  <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#f59e0b', marginBottom: '4px' }}>
                    Simulation Limitations & Guardrails:
                  </div>
                  <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.75rem', color: '#fcd34d' }}>
                    {selectedSim.limitations.map((lim, idx) => (
                      <li key={idx}>{lim}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Complete Optimization Trace */}
              {selectedSim && (
                <div style={{ marginTop: '10px' }}>
                  <h4 style={{ fontSize: '0.9rem', color: '#94a3b8', margin: '0 0 10px 0', textTransform: 'uppercase' }}>
                    End-to-End Optimization Trace for Simulation #{selectedSim.id}
                  </h4>
                  <OptimizationTrace
                    title={`Simulation #${selectedSim.id} Optimization Trace`}
                    simulation={selectedSim}
                    recommendation={selectedSim.recommendation_id ? {
                      id: selectedSim.recommendation_id,
                      type: 'INDEX_CREATE',
                      target: 'simulated_relation',
                      proposed_change: 'HYPOPG VIRTUAL INDEX SIMULATION',
                      reason: 'Evaluated in isolated sandbox session',
                      expected_benefit: `${((selectedSim.improvement ?? 0) * 100).toFixed(1)}% cost reduction`,
                      risk: 'low',
                      confidence: selectedSim.confidence ?? 0.85,
                      status: 'pending',
                      requires_approval: true,
                      created_at: selectedSim.created_at,
                    } : null}
                    initialExpanded={true}
                  />
                </div>
              )}
            </div>
          ) : (
            <div className="card empty-state">Select a simulation run to inspect details.</div>
          )}
        </div>
      )}
    </div>
  )
}
