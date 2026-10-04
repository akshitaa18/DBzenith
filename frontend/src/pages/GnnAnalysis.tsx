import { useState } from 'react'
import { analyzePlan, getRlStatus, optimizeWithRl, PlanAnalysis } from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'

const SAMPLE_QUERIES = [
  {
    name: 'Pending orders by customer',
    sql: `SELECT customer_id, count(*) AS order_count, sum(amount) AS total_val
FROM telemetry_demo_orders
WHERE status = 'pending'
GROUP BY customer_id
ORDER BY total_val DESC
LIMIT 50;`,
  },
  {
    name: 'Status filter on demo orders',
    sql: `SELECT id, customer_id, amount, created_at
FROM telemetry_demo_orders
WHERE status = 'completed'
ORDER BY created_at DESC
LIMIT 100;`,
  },
  {
    name: 'Self-join scan (high cost)',
    sql: `SELECT a.customer_id, count(*) AS pair_count
FROM telemetry_demo_orders a
JOIN telemetry_demo_orders b ON b.customer_id = a.customer_id
WHERE a.amount > 700.00
GROUP BY a.customer_id
LIMIT 20;`,
  },
]

export function GnnAnalysisPage() {
  const [sql, setSql] = useState(SAMPLE_QUERIES[0].sql)
  const [analysis, setAnalysis] = useState<PlanAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'bottlenecks' | 'graph' | 'features' | 'rl'>('bottlenecks')

  // RL Engine State
  const [rlResult, setRlResult] = useState<any | null>(null)
  const [rlLoading, setRlLoading] = useState(false)
  const [rlStatusData, setRlStatusData] = useState<any | null>(null)

  const handleRunAnalysis = async (queryToRun?: string) => {
    const targetSql = queryToRun ?? sql
    if (!targetSql.trim()) return
    setLoading(true)
    setError(null)
    try {
      const res = await analyzePlan(targetSql)
      setAnalysis(res)
    } catch (err: any) {
      setError(err?.message || 'Failed to perform GNN plan analysis')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Visual Workflow Header */}
      <OptimizationFlowHeader
        currentStage="analyze"
        subtitle="Graph Neural Network encodes tree-structured relational ASTs into latent vector representations to identify hidden plan inefficiencies."
      />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700 }}>GNN Plan Analysis & Cost Model</h1>
            <span className="badge badge-ai-analysis">AI ANALYSIS</span>
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Deep Graph Neural Network plan feature extraction, structural hash modeling, and automatic bottleneck detection.
          </p>
        </div>
      </div>

      {/* Query Input Box */}
      <div className="card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <label style={{ fontSize: '0.875rem', fontWeight: 600, color: '#cbd5e1' }}>
            Query for GNN Plan Embedding:
          </label>
          <div style={{ display: 'flex', gap: '8px' }}>
            {SAMPLE_QUERIES.map((sample, idx) => (
              <button
                key={idx}
                className="btn btn-secondary"
                style={{ fontSize: '0.75rem', padding: '4px 8px' }}
                onClick={() => {
                  setSql(sample.sql)
                  handleRunAnalysis(sample.sql)
                }}
              >
                {sample.name}
              </button>
            ))}
          </div>
        </div>

        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          rows={5}
          style={{
            width: '100%',
            background: '#090d16',
            color: '#e2e8f0',
            fontFamily: 'monospace',
            fontSize: '0.85rem',
            padding: '12px',
            borderRadius: '6px',
            border: '1px solid #334155',
            resize: 'vertical',
            boxSizing: 'border-box',
          }}
          placeholder="Enter PostgreSQL SQL query to analyze with GNN..."
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button
            className="btn btn-primary"
            onClick={() => handleRunAnalysis()}
            disabled={loading || !sql.trim()}
          >
            {loading ? 'Analyzing Graph...' : 'Analyze with GNN'}
          </button>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="card" style={{ borderColor: '#ef4444', background: 'rgba(239, 68, 68, 0.05)', color: '#fca5a5' }}>
          <strong>GNN Analysis Error:</strong> {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="card" style={{ textAlign: 'center', padding: '40px', color: '#94a3b8' }}>
          Extracting AST plan operators, constructing directed plan graph, and computing GNN embeddings...
        </div>
      )}

      {/* Analysis Output */}
      {analysis && !loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Key Overview Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
            <div className="card" style={{ padding: '14px' }}>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Structural Hash</div>
              <div style={{ fontSize: '1rem', fontFamily: 'monospace', fontWeight: 600, color: '#38bdf8', marginTop: '4px' }}>
                {analysis.structural_hash || 'N/A'}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '2px' }}>Isomorphic plan signature</div>
            </div>

            <div className="card" style={{ padding: '14px' }}>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Graph Size</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#f8fafc', marginTop: '4px' }}>
                {analysis.graph?.nodes?.length ?? 0} Nodes / {analysis.graph?.edges?.length ?? 0} Edges
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '2px' }}>Root Node: {analysis.graph?.root_id || 'node_0'}</div>
            </div>

            <div className="card" style={{ padding: '14px' }}>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Identified Bottlenecks</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 700, color: analysis.bottlenecks?.length ? '#f59e0b' : '#10b981', marginTop: '4px' }}>
                {analysis.bottlenecks?.length ?? 0} Detected
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '2px' }}>Rules & AI heuristic fusion</div>
            </div>

            <div className="card" style={{ padding: '14px' }}>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Inference Method</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 600, color: '#a78bfa', marginTop: '4px' }}>
                {analysis.explanation?.method || 'gnn_surrogate_v1'}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '2px' }}>Graph cost modeling</div>
            </div>
          </div>

          {/* Sub Navigation Tabs */}
          <div className="subnav-tabs">
            <button
              className={`subnav-tab ${activeTab === 'bottlenecks' ? 'active' : ''}`}
              onClick={() => setActiveTab('bottlenecks')}
            >
              Bottleneck Detections ({analysis.bottlenecks?.length || 0})
            </button>
            <button
              className={`subnav-tab ${activeTab === 'graph' ? 'active' : ''}`}
              onClick={() => setActiveTab('graph')}
            >
              Plan Graph Topology ({analysis.graph?.nodes?.length || 0} nodes)
            </button>
            <button
              className={`subnav-tab ${activeTab === 'features' ? 'active' : ''}`}
              onClick={() => setActiveTab('features')}
            >
              Extracted Feature Vector ({Object.keys(analysis.features || {}).length})
            </button>
            <button
              className={`subnav-tab ${activeTab === 'rl' ? 'active' : ''}`}
              onClick={async () => {
                setActiveTab('rl')
                if (!rlStatusData) {
                  try {
                    const st = await getRlStatus()
                    setRlStatusData(st)
                  } catch (e) {}
                }
              }}
            >
              RL Optimization Policy 🤖
            </button>
          </div>

          {/* Tab 1: Bottlenecks */}
          {activeTab === 'bottlenecks' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {(!analysis.bottlenecks || analysis.bottlenecks.length === 0) ? (
                <div className="card empty-state">
                  No critical bottlenecks detected by GNN for this execution plan.
                </div>
              ) : (
                analysis.bottlenecks.map((bn, idx) => (
                  <div key={idx} className="card" style={{ padding: '16px', borderLeft: '4px solid #f59e0b' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span className="badge" style={{ background: '#334155', color: '#cbd5e1' }}>
                          {bn.type}
                        </span>
                        <span className={`badge ${bn.severity === 'high' ? 'badge-danger' : 'badge-warning'}`}>
                          {bn.severity.toUpperCase()} SEVERITY
                        </span>
                        <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                          Node: <code>{bn.affected_node}</code>
                        </span>
                      </div>
                      <span className="badge badge-ai-analysis">AI DIAGNOSIS</span>
                    </div>

                    <div style={{ marginTop: '10px', fontSize: '0.9rem', color: '#e2e8f0' }}>
                      {bn.explanation}
                    </div>

                    {bn.possible_remediation && (
                      <div style={{ marginTop: '10px', background: '#090d16', padding: '10px', borderRadius: '4px', fontSize: '0.85rem' }}>
                        <strong style={{ color: '#10b981' }}>Remediation: </strong>
                        <span style={{ color: '#94a3b8' }}>{bn.possible_remediation}</span>
                      </div>
                    )}

                    {bn.evidence && Object.keys(bn.evidence).length > 0 && (
                      <div style={{ marginTop: '8px', fontSize: '0.75rem', color: '#64748b' }}>
                        Evidence: {JSON.stringify(bn.evidence)}
                      </div>
                    )}
                  </div>
                ))
              )}

              {/* Optimization Trace Section */}
              <div style={{ marginTop: '12px' }}>
                <OptimizationTrace
                  title="GNN-Guided Optimization Analysis & Bottleneck Trace"
                  query={{
                    normalized_query: sql,
                    mean_exec_time_ms: 60.0,
                    calls: 1,
                  }}
                  planAnalysis={analysis}
                  recommendation={analysis.bottlenecks && analysis.bottlenecks.length > 0 ? {
                    id: 101,
                    type: analysis.bottlenecks[0].type || 'INDEX_CREATE',
                    target: analysis.bottlenecks[0].affected_node || 'telemetry_demo_orders',
                    proposed_change: analysis.bottlenecks[0].possible_remediation || 'ANALYZE telemetry_demo_orders;',
                    reason: analysis.bottlenecks[0].explanation || 'GNN structural cost surrogate detected high-cost plan node',
                    expected_benefit: 'Cost reduction indicated by graph surrogate model',
                    risk: analysis.bottlenecks[0].severity === 'high' ? 'medium' : 'low',
                    confidence: 0.91,
                    status: 'pending',
                    requires_approval: true,
                    created_at: new Date().toISOString(),
                  } : null}
                  initialExpanded={true}
                />
              </div>
            </div>
          )}

          {/* Tab 2: Plan Graph Topology */}
          {activeTab === 'graph' && (
            <div className="card" style={{ padding: '16px' }}>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: '#f8fafc' }}>
                Plan Node Topology & Edge Connections
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div>
                  <h4 style={{ fontSize: '0.85rem', color: '#94a3b8', margin: '0 0 8px 0' }}>Plan Nodes</h4>
                  <div style={{ maxHeight: '360px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {analysis.graph?.nodes?.map((node: any, idx: number) => (
                      <div
                        key={idx}
                        style={{
                          background: '#090d16',
                          border: '1px solid #1e293b',
                          borderRadius: '4px',
                          padding: '8px 12px',
                          fontSize: '0.8rem',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600, color: '#38bdf8' }}>
                          <span>{node.node_type || node.id}</span>
                          <span style={{ color: '#64748b' }}>{node.id}</span>
                        </div>
                        <div style={{ color: '#94a3b8', marginTop: '4px', fontSize: '0.75rem' }}>
                          Cost: {node.total_cost ?? 'N/A'} | Rows: {node.plan_rows ?? 'N/A'}
                          {node.relation_name && ` | Table: ${node.relation_name}`}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h4 style={{ fontSize: '0.85rem', color: '#94a3b8', margin: '0 0 8px 0' }}>Dataflow Edges</h4>
                  <div style={{ maxHeight: '360px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {analysis.graph?.edges?.map((edge, idx) => (
                      <div
                        key={idx}
                        style={{
                          background: '#090d16',
                          border: '1px solid #1e293b',
                          borderRadius: '4px',
                          padding: '8px 12px',
                          fontSize: '0.8rem',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                        }}
                      >
                        <span style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>{edge.from}</span>
                        <span style={{ color: '#38bdf8' }}>&rarr;</span>
                        <span style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>{edge.to}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Tab 3: Extracted Feature Vector */}
          {activeTab === 'features' && (
            <div className="card" style={{ padding: '16px' }}>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: '#f8fafc' }}>
                Normalized GNN Plan Feature Embeddings
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '8px' }}>
                {Object.entries(analysis.features || {}).map(([key, value]) => (
                  <div
                    key={key}
                    style={{
                      background: '#090d16',
                      border: '1px solid #1e293b',
                      borderRadius: '4px',
                      padding: '8px 12px',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <span style={{ fontSize: '0.75rem', color: '#94a3b8', fontFamily: 'monospace' }}>{key}</span>
                    <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#f8fafc', fontFamily: 'monospace' }}>
                      {typeof value === 'number' ? value.toFixed(4) : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab 4: RL Policy Optimization */}
          {activeTab === 'rl' && (
            <div className="card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#f8fafc' }}>
                    Reinforcement Learning Optimization Engine (PPO / DQN Policy)
                  </h3>
                  <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.8rem' }}>
                    Agent formulates discrete optimization actions (Index, Rewrite, Partition, Join) based on GNN plan state representations.
                  </p>
                </div>
                <button
                  className="btn btn-primary"
                  style={{ fontSize: '13px', padding: '6px 14px' }}
                  disabled={rlLoading}
                  onClick={async () => {
                    setRlLoading(true)
                    try {
                      const res = await optimizeWithRl({
                        workload_metrics: {
                          total_cost: analysis.features?.total_cost || 100,
                          seq_scan_fraction: analysis.features?.seq_scan_fraction || 0.4,
                        },
                      })
                      setRlResult(res)
                    } catch (e: any) {
                      alert('RL optimization failed: ' + e.message)
                    } finally {
                      setRlLoading(false)
                    }
                  }}
                >
                  {rlLoading ? 'Evaluating RL Policy...' : 'Run RL Policy Action 🚀'}
                </button>
              </div>

              {/* Invariant badge */}
              <div style={{ background: '#090d16', border: '1px solid #1e293b', borderRadius: '6px', padding: '10px 14px', fontSize: '0.8rem', color: '#38bdf8' }}>
                🛡️ <strong>RL Safety Boundary:</strong> State representation &rarr; Candidate actions &rarr; Policy selection &rarr; Sandbox validation &rarr; Human sign-off. The RL model is strictly isolated from production catalogs.
              </div>

              {/* Status and Action space */}
              {rlStatusData && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '10px' }}>
                  <div style={{ background: '#090d16', padding: '10px', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Agent Readiness:</div>
                    <div style={{ fontWeight: 600, color: '#10b981', marginTop: '2px' }}>
                      {rlStatusData.status.toUpperCase()} ({rlStatusData.trained_agent_available ? 'Pretrained weights loaded' : 'Rule-guided fallback active'})
                    </div>
                  </div>
                  <div style={{ background: '#090d16', padding: '10px', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Supported Action Space:</div>
                    <div style={{ fontSize: '0.8rem', color: '#e2e8f0', marginTop: '2px' }}>
                      {rlStatusData.actions_supported?.join(', ')}
                    </div>
                  </div>
                </div>
              )}

              {/* RL Execution Result */}
              {rlResult && (
                <div style={{ marginTop: '10px', background: '#0d1527', border: '1px solid #2563eb', borderRadius: '6px', padding: '14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className="badge badge-ai-analysis">SELECTED ACTION</span>
                      <strong style={{ color: '#38bdf8', fontSize: '1rem' }}>
                        {rlResult.action_type}
                      </strong>
                    </div>
                    <span className="badge badge-success">
                      Predicted Reward: +{rlResult.predicted_reward?.toFixed(2)}
                    </span>
                  </div>

                  <p style={{ margin: '0 0 10px 0', fontSize: '0.85rem', color: '#cbd5e1' }}>
                    {rlResult.explanation}
                  </p>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px', fontSize: '0.8rem' }}>
                    <div>
                      <span style={{ color: '#94a3b8' }}>Policy Version: </span>
                      <span style={{ color: '#f8fafc', fontWeight: 600 }}>{rlResult.policy_version}</span>
                    </div>
                    <div>
                      <span style={{ color: '#94a3b8' }}>Model Architecture: </span>
                      <span style={{ color: '#f8fafc', fontWeight: 600 }}>{rlResult.model_type}</span>
                    </div>
                    <div>
                      <span style={{ color: '#94a3b8' }}>Confidence: </span>
                      <span style={{ color: '#38bdf8', fontWeight: 600 }}>{Math.round((rlResult.confidence || 0) * 100)}%</span>
                    </div>
                    <div>
                      <span style={{ color: '#94a3b8' }}>Simulated Cost Reduction: </span>
                      <span style={{ color: '#10b981', fontWeight: 700 }}>{rlResult.simulated_cost_reduction_pct?.toFixed(1)}%</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
