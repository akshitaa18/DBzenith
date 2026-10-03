from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanNode:
    node_id: str
    node_type: str
    relation: str | None = None
    index_name: str | None = None
    parent_relationship: str | None = None
    startup_cost: float = 0.0
    total_cost: float = 0.0
    plan_rows: float = 0.0
    actual_rows: float | None = None
    actual_loops: float | None = None
    actual_total_time_ms: float | None = None
    actual_startup_time_ms: float | None = None
    rows_removed_by_filter: float = 0.0
    parallel_aware: bool = False
    workers_planned: int = 0
    workers_launched: int = 0
    filter: str | None = None
    children: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanGraph:
    root_id: str
    nodes: dict[str, PlanNode]
    edges: list[tuple[str, str]]


@dataclass(frozen=True)
class PlanFeatureVector:
    node_count: int
    total_cost: float
    total_actual_time_ms: float
    max_depth: int
    seq_scans: int
    index_scans: int
    bitmap_scans: int
    nested_loops: int
    hash_joins: int
    merge_joins: int
    sorts: int
    aggregates: int
    parallel_nodes: int
    row_estimation_errors: int
    high_loop_nodes: int
    expensive_nodes: int
    filtering_inefficiencies: int


@dataclass(frozen=True)
class Bottleneck:
    type: str
    severity: str
    evidence: dict[str, Any]
    affected_node: str
    explanation: str
    possible_remediation: str
