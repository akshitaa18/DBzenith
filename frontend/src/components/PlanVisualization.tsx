import type { PlanAnalysis } from '../lib/api'

type Props = { analysis: PlanAnalysis }

export function PlanVisualization({ analysis }: Props) {
  const nodes = analysis.graph.nodes as Array<{
    node_id: string
    node_type: string
    relation?: string | null
    index_name?: string | null
    total_cost: number
    plan_rows: number
    actual_rows?: number | null
    actual_loops?: number | null
    actual_total_time_ms?: number | null
  }>
  const edges = analysis.graph.edges as Array<{ from: string; to: string }>
  const childIds = new Set(edges.map((e) => e.to))
  const roots = nodes.filter((n) => !childIds.has(n.node_id))

  return (
    <div className="plan-visualization">
      <div className="plan-summary">
        <span>Nodes: {analysis.features.node_count}</span>
        <span>Cost: {analysis.features.total_cost.toFixed(2)}</span>
        <span>Actual: {analysis.features.total_actual_time_ms.toFixed(2)} ms</span>
        <span>Bottlenecks: {analysis.bottlenecks.length}</span>
      </div>
      <div className="plan-tree">
        {roots.map((root) => (
          <PlanNodeView key={root.node_id} node={root} nodes={nodes} edges={edges} depth={0} />
        ))}
      </div>
    </div>
  )
}

function PlanNodeView({ node, nodes, edges, depth }: {
  node: any
  nodes: any[]
  edges: Array<{ from: string; to: string }>
  depth: number
}) {
  const children = edges.filter((e) => e.from === node.node_id).map((e) => nodes.find((n) => n.node_id === e.to)).filter(Boolean)
  return (
    <div className="plan-node-wrap" style={{ marginLeft: `${depth * 24}px` }}>
      <div className="plan-node">
        <strong>{node.node_type}</strong>
        {node.relation && <span>{node.relation}</span>}
        <small>cost {Number(node.total_cost).toFixed(2)} · rows {Number(node.plan_rows).toLocaleString()}</small>
        {node.actual_rows != null && <small>actual {Number(node.actual_rows).toLocaleString()} · loops {Number(node.actual_loops ?? 0).toLocaleString()} · {Number(node.actual_total_time_ms ?? 0).toFixed(2)} ms</small>}
      </div>
      {children.map((child) => <PlanNodeView key={child.node_id} node={child} nodes={nodes} edges={edges} depth={depth + 1} />)}
    </div>
  )
}
