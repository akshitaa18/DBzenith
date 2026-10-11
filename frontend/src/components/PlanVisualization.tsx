import type { PlanAnalysis } from '../lib/api'

type Props = { analysis: PlanAnalysis }

export function PlanVisualization({ analysis }: Props) {
  const nodes = analysis.graph.nodes as Array<{
    node_id: string
    node_type: string
    relation?: string | null
    index_name?: string | null
    startup_cost?: number
    total_cost: number
    plan_rows: number
    plan_width?: number
    actual_rows?: number | null
    actual_loops?: number | null
    actual_total_time_ms?: number | null
    shared_hit_blocks?: number
    shared_read_blocks?: number
    filter?: string | null
  }>
  const edges = analysis.graph.edges as Array<{ from: string; to: string }>
  const childIds = new Set(edges.map((e) => e.to))
  const roots = nodes.filter((n) => !childIds.has(n.node_id))
  const rootTotalCost = Math.max(Number(analysis.features.total_cost || 0), 1e-6)
  const hasActualTiming = nodes.some((n) => n.actual_total_time_ms != null) || Number(analysis.features.total_actual_time_ms || 0) > 0

  return (
    <div className="plan-visualization">
      <div className="plan-summary" style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center' }}>
        <span>Nodes: <strong>{analysis.features.node_count}</strong></span>
        <span title="PostgreSQL planner cost units (arbitrary relative units, NOT milliseconds)">
          Est. Planner Cost: <strong>{Number(analysis.features.total_cost || 0).toFixed(2)} cost units (not ms)</strong>
        </span>
        {hasActualTiming ? (
          <span>Measured Time: <strong>{Number(analysis.features.total_actual_time_ms || 0).toFixed(2)} ms</strong></span>
        ) : (
          <span style={{ color: '#94a3b8' }}>Measured Time: <strong>Not measured (EXPLAIN estimate only)</strong></span>
        )}
        <span>Bottlenecks: <strong>{analysis.bottlenecks.length}</strong></span>
      </div>
      <div className="plan-tree">
        {roots.map((root) => (
          <PlanNodeView
            key={root.node_id}
            node={root}
            nodes={nodes}
            edges={edges}
            depth={0}
            rootTotalCost={rootTotalCost}
          />
        ))}
      </div>
    </div>
  )
}

function PlanNodeView({
  node,
  nodes,
  edges,
  depth,
  rootTotalCost,
}: {
  node: any
  nodes: any[]
  edges: Array<{ from: string; to: string }>
  depth: number
  rootTotalCost: number
}) {
  const children = edges
    .filter((e) => e.from === node.node_id)
    .map((e) => nodes.find((n) => n.node_id === e.to))
    .filter(Boolean)

  const childrenCost = children.reduce((acc, c) => acc + Number(c?.total_cost || 0), 0)
  const exclusiveCost = Math.max(0, Number(node.total_cost || 0) - childrenCost)
  const costSharePct = Math.min(100, (exclusiveCost / rootTotalCost) * 100)
  const isHotspot = costSharePct >= 35

  return (
    <div className="plan-node-wrap" style={{ marginLeft: `${depth * 22}px`, marginTop: 8 }}>
      <div
        className="plan-node"
        style={{
          border: isHotspot ? '1px solid rgba(245, 158, 11, 0.45)' : '1px solid rgba(148, 163, 184, 0.2)',
          background: isHotspot ? 'rgba(245, 158, 11, 0.08)' : 'rgba(15, 23, 42, 0.55)',
          borderRadius: 8,
          padding: '8px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <strong style={{ color: '#e2e8f0' }}>{node.node_type}</strong>
          {node.relation && (
            <span style={{ fontSize: '0.78rem', color: '#38bdf8', fontFamily: 'monospace' }}>
              on {node.relation}
            </span>
          )}
          {node.index_name && (
            <span style={{ fontSize: '0.75rem', color: '#4ade80', fontFamily: 'monospace' }}>
              using {node.index_name}
            </span>
          )}
          {isHotspot && (
            <span
              style={{
                fontSize: '0.68rem',
                padding: '1px 6px',
                borderRadius: 4,
                background: 'rgba(245, 158, 11, 0.2)',
                color: '#fbbf24',
                fontWeight: 700,
              }}
            >
              COST HOTSPOT ({costSharePct.toFixed(0)}%)
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: '0.78rem', color: '#cbd5e1' }}>
          <span>
            Est. Cost: <strong>{Number(node.total_cost || 0).toFixed(2)}</strong> (self: {exclusiveCost.toFixed(2)} units · {costSharePct.toFixed(1)}%)
          </span>
          <span>
            Est. Rows: <strong>{Number(node.plan_rows || 0).toLocaleString()}</strong>
          </span>
          {node.actual_rows != null && (
            <span style={{ color: '#a5b4fc' }}>
              Actual Rows: <strong>{Number(node.actual_rows).toLocaleString()}</strong>
              {node.actual_loops != null ? ` (loops: ${Number(node.actual_loops).toLocaleString()})` : ''}
            </span>
          )}
          {node.actual_total_time_ms != null && (
            <span style={{ color: '#34d399' }}>
              Actual Time: <strong>{Number(node.actual_total_time_ms).toFixed(2)} ms</strong>
            </span>
          )}
          {(Number(node.shared_hit_blocks || 0) > 0 || Number(node.shared_read_blocks || 0) > 0) && (
            <span style={{ color: '#94a3b8' }}>
              Buffers: hit={Number(node.shared_hit_blocks || 0)} read={Number(node.shared_read_blocks || 0)}
            </span>
          )}
        </div>
      </div>
      {children.map((child) => (
        <PlanNodeView
          key={child.node_id}
          node={child}
          nodes={nodes}
          edges={edges}
          depth={depth + 1}
          rootTotalCost={rootTotalCost}
        />
      ))}
    </div>
  )
}
