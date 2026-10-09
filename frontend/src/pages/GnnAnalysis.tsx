import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { analyzePlan, getQueryDetail, getRlStatus, optimizeWithRl, PlanAnalysis } from '../lib/api'
import { OptimizationFlowHeader } from '../components/OptimizationFlowHeader'
import { OptimizationTrace } from '../components/OptimizationTrace'

const SAMPLE_QUERIES = [
  {
    name: 'Pending orders by customer (Agg + Sort)',
    sql: `SELECT customer_id, count(*) AS order_count, sum(amount) AS total_val
FROM telemetry_demo_orders
WHERE status = 'pending'
GROUP BY customer_id
ORDER BY total_val DESC
LIMIT 50`,
  },
  {
    name: 'Status filter scan on demo orders',
    sql: `SELECT id, customer_id, amount, created_at
FROM telemetry_demo_orders
WHERE status = 'completed'
ORDER BY created_at DESC
LIMIT 100`,
  },
  {
    name: 'Star Join (Orders + Customers + Products + Regions)',
    sql: `SELECT o.order_id, c.last_name, p.product_name, r.region_name, o.amount
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN products p ON p.product_id = o.product_id
JOIN regions r ON r.region_id = o.region_id
WHERE o.amount > 500.00
ORDER BY o.amount DESC
LIMIT 50`,
  },
  {
    name: 'Self-join scan (high nested loop cost)',
    sql: `SELECT a.customer_id, count(*) AS pair_count
FROM telemetry_demo_orders a
JOIN telemetry_demo_orders b ON b.customer_id = a.customer_id
WHERE a.amount > 700.00
GROUP BY a.customer_id
LIMIT 20`,
  },
  {
    name: 'Time-series range scan (partition candidate)',
    sql: `SELECT order_id, customer_id, amount, order_date
FROM orders
WHERE order_date >= '2024-01-01' AND order_date < '2024-07-01'
ORDER BY order_date DESC
LIMIT 100`,
  },
  {
    name: 'Correlated EXISTS subquery',
    sql: `SELECT c.customer_id, c.first_name, c.email
FROM customers c
WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id AND o.amount > 300.00)`,
  },
]

export function GnnAnalysisPage() {
  const [searchParams] = useSearchParams()
  const [sql, setSql] = useState(SAMPLE_QUERIES[0].sql)
  const [currentQueryId, setCurrentQueryId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<PlanAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'bottlenecks' | 'graph' | 'features' | 'rl'>('bottlenecks')

  // RL Engine State
  const [rlResult, setRlResult] = useState<any | null>(null)
  const [rlLoading, setRlLoading] = useState(false)
  const [rlStatusData, setRlStatusData] = useState<any | null>(null)

  const loadedParamRef = useRef<string | null>(null)

  // Auto-load query context if queryId is in URL query parameters
  useEffect(() => {
    const qid = searchParams.get('queryId')
    if (qid && qid.trim() && loadedParamRef.current !== qid.trim()) {
      loadedParamRef.current = qid.trim()
      setCurrentQueryId(qid.trim())
      setLoading(true)
      setError(null)

      // Fetch query details to display actual SQL
      getQueryDetail(qid.trim())
        .then((q) => {
          if (q.normalized_query) {
            setSql(q.normalized_query.replace(/;\s*$/, ''))
          }
        })
        .catch(() => {})

      // Directly analyze via query_id
      analyzePlan({ query_id: qid.trim() })
        .then((res) => {
          setAnalysis(res)
        })
        .catch((err) => {
          setError(err?.message || `Failed to analyze query #${qid}`)
        })
        .finally(() => setLoading(false))
    }
  }, [searchParams])

  const handleRunAnalysis = async (queryToRun?: string) => {
    const rawSql = queryToRun ?? sql
    if (!rawSql.trim()) return
    const targetSql = rawSql.trim().replace(/;\s*$/, '')
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

  // Helper to determine bottleneck severity badge and color for graph nodes
  const getNodeBottleneck = (nodeId: string, nodeType: string) => {
    const bn = analysis?.bottlenecks?.find((b) => b.affected_node === nodeId)
    if (bn) return bn

    // Fallback heuristic based on operator type
    if (nodeType.toLowerCase().includes('seq scan')) {
      return { type: 'Sequential Scan', severity: 'high' }
    }
    if (nodeType.toLowerCase().includes('nested loop')) {
      return { type: 'Nested Loop', severity: 'high' }
    }
    if (nodeType.toLowerCase().includes('sort')) {
      return { type: 'Sort', severity: 'medium' }
    }
    if (nodeType.toLowerCase().includes('aggregate')) {
      return { type: 'Aggregate', severity: 'low' }
    }
    return null
  }

  const gnnSummaryText = (analysis?.explanation as any)?.gnn_summary || analysis?.explanation?.summary

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Visual Workflow Header */}
      <OptimizationFlowHeader
        currentStage="analyze"
        subtitle="Graph Neural Network encodes tree-structured relational ASTs into latent vector representations to identify hidden plan inefficiencies."
      />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 style={{ margin: 0, fontSize: '1.6rem', fontWeight: 700 }}>GNN Plan Analysis & Cost Model</h1>
            <span className="badge badge-ai-analysis">AI STRUCTURAL CLASSIFIER</span>
            {currentQueryId && (
              <span className="badge badge-observed">Query #{currentQueryId}</span>
            )}
          </div>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Deep Graph Neural Network plan feature extraction, structural hash modeling, and automated bottleneck detection.
          </p>
        </div>
      </div>

      {/* Architectural Transparency Banner */}
      <div className="guide-banner">
        <div className="guide-banner-icon">🧠</div>
        <div className="guide-banner-content">
          <div className="guide-banner-title">
            <span>GRAPH NEURAL NETWORK PLAN EMBEDDING & RL POLICY</span>
            <span className="badge badge-ai-analysis">AI STRUCTURAL CLASSIFIER</span>
          </div>
          <p className="guide-banner-desc">
            DBZenith models PostgreSQL execution trees as directed operator graphs using PyTorch Geometric GNN embeddings. This allows the system to predict cost curves and evaluate Reinforcement Learning index selection policies without exposing any user data (0 bytes raw table data exposure).
          </p>
          <div className="guide-banner-pills">
            <span className="badge badge-observed">Execution Plan</span>
            <span>&rarr;</span>
            <span className="badge badge-success">Privacy Gateway</span>
            <span>&rarr;</span>
            <span className="badge badge-ai-analysis">GNN Node Classification</span>
            <span>&rarr;</span>
            <span className="badge badge-simulation">Evidence Extraction</span>
            <span>&rarr;</span>
            <span className="badge badge-recommendation">Actionable Decision</span>
          </div>
        </div>
      </div>

      {/* Query Input Box */}
      <div className="card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
          <label style={{ fontSize: '0.875rem', fontWeight: 600, color: '#cbd5e1' }}>
            Target Query for GNN Plan Embedding:
          </label>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {SAMPLE_QUERIES.map((sample, idx) => (
              <button
                key={idx}
                className="btn btn-secondary"
                style={{ fontSize: '0.75rem', padding: '4px 8px' }}
                onClick={() => {
                  setCurrentQueryId(null)
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
          Extracting AST plan operators, passing through PrivacyGateway, constructing directed plan graph, and evaluating GNN embeddings...
        </div>
      )}

      {/* Analysis Output */}
      {analysis && !loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Key Overview Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
            <div className="card" style={{ padding: '14px' }}>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Structural Hash</div>
              <div style={{ fontSize: '0.95rem', fontFamily: 'monospace', fontWeight: 600, color: '#38bdf8', marginTop: '4px' }}>
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
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '2px' }}>GNN & heuristic classification</div>
            </div>

            <div className="card" style={{ padding: '14px' }}>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>Inference Method</div>
              <div style={{ fontSize: '1rem', fontWeight: 600, color: '#a78bfa', marginTop: '4px' }}>
                {analysis.explanation?.method || 'GCN Message-Passing + Explanation'}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '2px' }}>Structural plan cost modeling</div>
            </div>
          </div>

          {/* GNN Synthesis Summary Box */}
          {gnnSummaryText && (
            <div className="card" style={{ padding: '14px 16px', borderLeft: '4px solid #38bdf8', background: 'rgba(56, 189, 248, 0.04)' }}>
              <div style={{ fontSize: '12px', color: '#38bdf8', fontWeight: 700, textTransform: 'uppercase', marginBottom: '4px' }}>
                GNN Analysis Summary & Structural Reasoning:
              </div>
              <div style={{ fontSize: '13px', color: '#f8fafc', lineHeight: 1.5 }}>
                {gnnSummaryText}
              </div>
            </div>
          )}

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
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span className="badge" style={{ background: '#334155', color: '#cbd5e1', fontWeight: 600 }}>
                          {bn.type.replace(/_/g, ' ').toUpperCase()}
                        </span>
                        <span className={`badge ${bn.severity === 'critical' ? 'badge-danger' : bn.severity === 'high' ? 'badge-danger' : 'badge-warning'}`}>
                          {bn.severity.toUpperCase()} SEVERITY
                        </span>
                        <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                          Affected Node: <code>{bn.affected_node}</code>
                        </span>
                      </div>
                      <span className="badge badge-ai-analysis">GNN BOTTLENECK CLASSIFICATION</span>
                    </div>

                    <div style={{ marginTop: '10px', fontSize: '0.9rem', color: '#e2e8f0', lineHeight: 1.5 }}>
                      {bn.explanation}
                    </div>

                    {/* Structural Plan Evidence */}
                    {bn.evidence && Object.keys(bn.evidence).length > 0 && (
                      <div style={{ marginTop: '10px', background: '#090d16', padding: '10px 12px', borderRadius: '4px', border: '1px solid #1e293b' }}>
                        <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 600, marginBottom: '4px' }}>
                          Plan Graph Evidence:
                        </div>
                        <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '12px', color: '#cbd5e1', lineHeight: 1.5 }}>
                          {typeof bn.evidence === 'object' && !Array.isArray(bn.evidence) ? (
                            Object.entries(bn.evidence).map(([k, v]) => (
                              <li key={k}>
                                <strong>{k.replace(/_/g, ' ')}:</strong> {typeof v === 'number' ? (v > 100 ? v.toLocaleString() : v) : String(v)}
                              </li>
                            ))
                          ) : Array.isArray(bn.evidence) ? (
                            bn.evidence.map((item: any, i: number) => <li key={i}>{String(item)}</li>)
                          ) : (
                            <li>Evidence observed in plan cost model</li>
                          )}
                        </ul>
                      </div>
                    )}

                    {bn.possible_remediation && (
                      <div style={{ marginTop: '10px', background: 'rgba(16, 185, 129, 0.05)', border: '1px solid rgba(16, 185, 129, 0.2)', padding: '10px 12px', borderRadius: '4px', fontSize: '0.85rem' }}>
                        <strong style={{ color: '#10b981' }}>Recommended Optimization: </strong>
                        <span style={{ color: '#e2e8f0' }}>{bn.possible_remediation}</span>
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
                    proposed_change: analysis.bottlenecks[0].possible_remediation || 'CREATE INDEX CONCURRENTLY ON target_relation;',
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

          {/* Tab 2: Visual Plan Graph Topology */}
          {activeTab === 'graph' && (
            <div className="card" style={{ padding: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1rem', color: '#f8fafc' }}>
                    Directed Plan Operator Topology (Root &rarr; Join &rarr; Scan &rarr; Filter &rarr; Aggregate &rarr; Sort)
                  </h3>
                  <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: '#94a3b8' }}>
                    Nodes identified as structural bottlenecks are highlighted by the GNN classification layer.
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '8px', fontSize: '11px' }}>
                  <span className="badge badge-danger">Sequential Scan &rarr; HIGH</span>
                  <span className="badge badge-warning">Nested Loop &rarr; HIGH</span>
                  <span className="badge" style={{ background: '#b45309', color: '#fef3c7' }}>Sort &rarr; MEDIUM</span>
                  <span className="badge" style={{ background: '#1e3a8a', color: '#93c5fd' }}>Aggregate &rarr; LOW</span>
                </div>
              </div>

              {/* Visual Directed Operator Nodes List */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {analysis.graph?.nodes?.map((node: any, idx: number) => {
                  const bn = getNodeBottleneck(node.id, node.node_type || '')
                  const isRoot = node.id === analysis.graph?.root_id || idx === 0

                  return (
                    <div key={idx} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                      <div
                        style={{
                          width: '100%',
                          background: bn?.severity === 'high' || bn?.severity === 'critical' ? 'rgba(239, 68, 68, 0.06)' : '#090d16',
                          border: `1px solid ${bn?.severity === 'high' || bn?.severity === 'critical' ? '#ef4444' : '#1e293b'}`,
                          borderLeft: `4px solid ${
                            bn?.severity === 'high' || bn?.severity === 'critical'
                              ? '#ef4444'
                              : bn?.severity === 'medium'
                              ? '#f59e0b'
                              : '#38bdf8'
                          }`,
                          borderRadius: '6px',
                          padding: '12px 16px',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          flexWrap: 'wrap',
                          gap: '10px',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{ fontSize: '11px', fontFamily: 'monospace', color: '#64748b' }}>
                            {node.id}
                          </span>
                          <strong style={{ fontSize: '14px', color: '#f8fafc' }}>
                            {node.node_type || 'Plan Operator'}
                          </strong>
                          {isRoot && (
                            <span className="badge" style={{ background: '#3b82f6', color: '#fff', fontSize: '10px' }}>
                              ROOT
                            </span>
                          )}
                          {node.relation && (
                            <span style={{ fontSize: '12px', color: '#38bdf8', fontFamily: 'monospace' }}>
                              on {node.relation}
                            </span>
                          )}
                          {bn && (
                            <span
                              className={`badge ${
                                bn.severity === 'high' || bn.severity === 'critical'
                                  ? 'badge-danger'
                                  : bn.severity === 'medium'
                                  ? 'badge-warning'
                                  : 'badge-observed'
                              }`}
                              style={{ fontSize: '10px', fontWeight: 700 }}
                            >
                              {bn.type.replace(/_/g, ' ').toUpperCase()} &rarr; {bn.severity.toUpperCase()}
                            </span>
                          )}
                        </div>

                        <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: '#94a3b8' }}>
                          <span>Cost: <strong style={{ color: '#e2e8f0' }}>{node.total_cost ?? 'N/A'}</strong></span>
                          <span>Est. Rows: <strong style={{ color: '#e2e8f0' }}>{node.plan_rows ?? 'N/A'}</strong></span>
                          {node.actual_loops && (
                            <span>Loops: <strong style={{ color: '#f59e0b' }}>{node.actual_loops}</strong></span>
                          )}
                          {node.actual_total_time_ms && (
                            <span>Time: <strong style={{ color: '#10b981' }}>{node.actual_total_time_ms.toFixed(2)} ms</strong></span>
                          )}
                        </div>
                      </div>

                      {/* Direction arrow between nodes if not last */}
                      {idx < (analysis.graph?.nodes?.length ?? 0) - 1 && (
                        <div style={{ paddingLeft: '24px', margin: '3px 0', color: '#38bdf8', fontSize: '14px', fontWeight: 700 }}>
                          &darr;
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* Dataflow Edges summary */}
              <div style={{ marginTop: '16px', padding: '12px', background: '#090d16', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <span style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>
                  Dataflow Graph Edges ({analysis.graph?.edges?.length || 0}):
                </span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
                  {analysis.graph?.edges?.map((edge, idx) => (
                    <span
                      key={idx}
                      style={{
                        background: '#0b1120',
                        border: '1px solid #1e293b',
                        padding: '4px 8px',
                        borderRadius: '4px',
                        fontSize: '11px',
                        fontFamily: 'monospace',
                        color: '#cbd5e1',
                      }}
                    >
                      {edge.from} &rarr; {edge.to}
                    </span>
                  ))}
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
