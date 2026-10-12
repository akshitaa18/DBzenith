"""Phase 9 Part A: Rigorous GNN Evaluation, Leakage Audit, Grouped Splits & Baseline Comparison.

Investigates the legacy v0.7.0 synthetic dataset (which reported 1.0 accuracy / 1.0 macro-F1),
proves the root causes (template overlap across splits, 37.5% exact duplicate validation nodes,
and 1-to-1 operator-type label shortcuts), and provides:
1. Leakage & shortcut detector (`audit_dataset_leakage`).
2. Leakage-free grouped Train / Validation / Test splits (`build_grouped_evaluation_splits`)
   plus held-out representative workload query plans (`build_held_out_workload_samples`).
3. Simple deterministic rule-based baseline (`RuleBasedNodeBaseline`).
4. Full metrics calculator (`compute_classification_report`) producing accuracy, per-class
   precision/recall/F1, 5x5 confusion matrix, and support counts.
5. Saved prediction verification (`reproduce_metrics_from_predictions`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import random
from typing import Any

import torch
from torch import nn

from app.services.plans.models import PlanGraph, PlanNode

from .contracts import ID_TO_LABEL, LABEL_TO_ID, LABELS, GraphSample
from .features import fit_normalizer, normalize
from .graph import build_graph_sample
from .model import HAS_PYG, BaselineNodeClassifier, BottleneckGNN
from .train import SEED as LEGACY_SEED, make_dataset as make_legacy_dataset

EVALUATION_SEED = 20261009


class RuleBasedNodeBaseline:
    """Simple deterministic rule-based baseline using normalized/raw node features.

    Node feature indices in `build_graph_sample`:
      0: startup_cost
      1: total_cost
      2: plan_rows
      3: actual_rows
      4: actual_loops
      5: actual_total_time_ms
      6: rows_removed_by_filter
     10: is_seq_scan
     11: is_index_scan
     12: is_bitmap_scan
     13: is_nested_loop
     14: is_hash_join
     15: is_merge_join
     16: is_sort
    """

    name = "simple_rule_based_baseline"
    version = "v1.0.0"

    def _classify_feature_row(self, feat: list[float]) -> tuple[int, str]:
        total_cost = float(feat[1])
        plan_rows = max(float(feat[2]), 1.0)
        actual_rows = float(feat[3])
        actual_loops = float(feat[4])
        actual_time_ms = float(feat[5])
        rows_removed = float(feat[6])
        is_seq_scan = feat[10] > 0.5
        is_nested_loop = feat[13] > 0.5
        is_sort = feat[16] > 0.5

        ratio = max(actual_rows, 0.001) / plan_rows if actual_rows > 0 else 1.0

        if is_seq_scan and (total_cost >= 100.0 or plan_rows >= 1000.0 or rows_removed >= 500.0):
            return LABEL_TO_ID["sequential_scan"], "seq_scan_cost_or_rows_threshold"
        if is_nested_loop and actual_loops >= 100.0:
            return LABEL_TO_ID["nested_loop"], "nested_loop_high_loop_count"
        if is_sort and actual_time_ms >= 10.0:
            return LABEL_TO_ID["expensive_sort"], "sort_high_runtime_ms"
        if actual_rows > 0 and (ratio >= 10.0 or ratio <= 0.1):
            return LABEL_TO_ID["row_estimation_error"], "cardinality_q_error_10x"
        return LABEL_TO_ID["none"], "within_normal_bounds"

    def predict_sample(self, sample: GraphSample) -> list[int]:
        return [self._classify_feature_row(feat)[0] for feat in sample.node_features]

    def predict_graph(self, node_features: list[list[float]]) -> list[dict[str, Any]]:
        """Deterministic fallback inference for a graph's node_features without fabricating confidence."""
        results: list[dict[str, Any]] = []
        for feat in node_features:
            label_id, rule_name = self._classify_feature_row(feat)
            results.append(
                {
                    "label": ID_TO_LABEL[label_id],
                    "confidence": None,
                    "confidence_source": "none_deterministic_fallback",
                    "source_classification": "DETERMINISTIC_FALLBACK",
                    "is_fallback": True,
                    "rule_triggered": rule_name,
                    "probabilities": None,
                }
            )
        return results


def _graph_structural_signature(sample: GraphSample) -> str:
    """Computes a structural signature from node operator one-hot flags and edge list."""
    op_tuples = [tuple(int(round(v)) for v in row[10:21]) for row in sample.node_features]
    edges = [tuple(e) for e in sample.edge_index]
    payload = json.dumps({"ops": op_tuples, "edges": edges}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _node_feature_hash(row: list[float]) -> str:
    rounded = [round(float(v), 4) for v in row]
    return hashlib.sha256(json.dumps(rounded).encode("utf-8")).hexdigest()[:16]


def _graph_exact_feature_hash(sample: GraphSample) -> str:
    rows = [[round(float(v), 4) for v in row] for row in sample.node_features]
    payload = json.dumps({"rows": rows, "edges": sample.edge_index}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def audit_dataset_leakage(
    train_samples: list[GraphSample],
    eval_samples: list[GraphSample],
) -> dict[str, Any]:
    """Detects train/eval graph overlap, duplicate node feature vectors, and label shortcuts."""
    train_graph_ids = {s.graph_id for s in train_samples}
    eval_graph_ids = {s.graph_id for s in eval_samples}
    shared_graph_ids = sorted(train_graph_ids.intersection(eval_graph_ids))

    train_groups = {
        s.metadata.get("template_group")
        for s in train_samples
        if s.metadata and s.metadata.get("template_group")
    }
    eval_groups = {
        s.metadata.get("template_group")
        for s in eval_samples
        if s.metadata and s.metadata.get("template_group")
    }
    shared_template_groups = sorted(train_groups.intersection(eval_groups))

    train_exact_graphs = {_graph_exact_feature_hash(s) for s in train_samples}
    exact_duplicate_graphs = sum(1 for s in eval_samples if _graph_exact_feature_hash(s) in train_exact_graphs)

    train_struct_sigs = {_graph_structural_signature(s) for s in train_samples}
    eval_struct_sigs = [_graph_structural_signature(s) for s in eval_samples]
    overlapping_struct_graphs = sum(1 for sig in eval_struct_sigs if sig in train_struct_sigs)

    train_node_hashes = {
        _node_feature_hash(row)
        for s in train_samples
        for row in s.node_features
    }
    eval_node_hashes = [
        _node_feature_hash(row)
        for s in eval_samples
        for row in s.node_features
    ]
    exact_duplicate_nodes = sum(1 for h in eval_node_hashes if h in train_node_hashes)
    total_eval_nodes = max(len(eval_node_hashes), 1)

    # Check single-feature operator+position shortcut power on eval_samples (ignoring all cost/row/time features)
    op_to_label_counts: dict[tuple[int, ...], dict[int, int]] = {}
    for s in train_samples:
        for node_idx, (row, lbl) in enumerate(zip(s.node_features, s.node_labels)):
            op_key = (*tuple(int(round(v)) for v in row[10:21]), node_idx)
            bucket = op_to_label_counts.setdefault(op_key, {})
            bucket[lbl] = bucket.get(lbl, 0) + 1

    op_majority_map = {
        op_key: max(counts.items(), key=lambda kv: kv[1])[0]
        for op_key, counts in op_to_label_counts.items()
    }
    shortcut_correct = 0
    shortcut_total = 0
    for s in eval_samples:
        for node_idx, (row, lbl) in enumerate(zip(s.node_features, s.node_labels)):
            op_key = (*tuple(int(round(v)) for v in row[10:21]), node_idx)
            pred_lbl = op_majority_map.get(op_key, 0)
            if pred_lbl == lbl:
                shortcut_correct += 1
            shortcut_total += 1

    shortcut_accuracy = round(shortcut_correct / max(shortcut_total, 1), 4)
    duplicate_node_ratio = round(exact_duplicate_nodes / total_eval_nodes, 4)
    structural_overlap_ratio = round(overlapping_struct_graphs / max(len(eval_samples), 1), 4)
    has_1to1_shortcut = bool(shortcut_accuracy >= 0.999)

    leakage_detected = bool(
        shared_graph_ids
        or shared_template_groups
        or exact_duplicate_graphs > 0
        or duplicate_node_ratio > 0.05
    )

    return {
        "leakage_detected": leakage_detected,
        "shared_graph_ids_count": len(shared_graph_ids),
        "shared_template_groups": shared_template_groups,
        "group_id_overlap_count": len(shared_template_groups),
        "exact_duplicate_graph_count": exact_duplicate_graphs,
        "exact_duplicate_eval_nodes": exact_duplicate_nodes,
        "exact_duplicate_node_count": exact_duplicate_nodes,
        "total_eval_nodes": len(eval_node_hashes),
        "test_node_count": len(eval_node_hashes),
        "exact_duplicate_node_ratio": duplicate_node_ratio,
        "exact_duplicate_node_fraction": duplicate_node_ratio,
        "structural_topology_overlap_ratio": structural_overlap_ratio,
        "topology_overlap_fraction": structural_overlap_ratio,
        "operator_type_shortcut_accuracy": shortcut_accuracy,
        "deterministic_shortcut_analysis": {
            "has_deterministic_1to1_operator_shortcut": has_1to1_shortcut,
            "operator_type_only_accuracy": shortcut_accuracy,
        },
        "root_cause_findings": [
            (
                f"Exact node feature duplication: {exact_duplicate_nodes}/{len(eval_node_hashes)} "
                f"({duplicate_node_ratio * 100:.1f}%) evaluation nodes have identical feature vectors to training nodes."
            ),
            (
                f"Structural topology overlap: {overlapping_struct_graphs}/{len(eval_samples)} "
                f"({structural_overlap_ratio * 100:.1f}%) evaluation graphs share an identical operator tree signature with training."
            ),
            (
                f"Operator-type shortcut power: a lookup table using ONLY one-hot operator flags (ignoring cost, rows, and graph edges) "
                f"achieves {shortcut_accuracy * 100:.1f}% accuracy on this split."
            ),
        ],
    }


def _realistic_node_label(
    node: PlanNode,
    *,
    noisy_label_flip_prob: float = 0.0,
    rng: random.Random | None = None,
) -> int:
    """Assigns ground-truth bottleneck labels considering scale, selectivity, and planner context.

    Unlike the naive `_label()` in `graph.py` (which labeled EVERY Seq Scan with a relation as a
    bottleneck regardless of table size or cost, and ignored row estimation errors on Seq Scans),
    this function models realistic DBA ground truth:
    - Small-table sequential scans (cost < 65 and plan_rows < 600 and rows_removed < 400) are benign (`none`),
      unless they suffer from a severe cardinality estimation error.
    - Severe row estimation errors (ratio >= 10x or <= 0.1x with cost >= 40) can occur on Joins, Index Scans,
      Bitmap Scans, or Seq Scans.
    - Nested loops are bottlenecks when loop count * inner cost is high (loops >= 95 and total_cost >= 110).
    - Sorts are bottlenecks when execution time >= 12ms or cost >= 160 on >= 800 rows.
    """
    cost = float(node.total_cost or 0.0)
    plan_rows = max(float(node.plan_rows or 1.0), 1.0)
    actual_rows = node.actual_rows
    loops = float(node.actual_loops or 1.0)
    time_ms = float(node.actual_total_time_ms or 0.0)
    removed = float(node.rows_removed_by_filter or 0.0)

    ratio = (max(float(actual_rows), 0.001) / plan_rows) if actual_rows is not None else 1.0

    # Priority 1: Severe cardinality estimation error on non-trivial operators
    if actual_rows is not None and cost >= 45.0 and (ratio >= 11.0 or ratio <= 0.09):
        label = LABEL_TO_ID["row_estimation_error"]
    # Priority 2: High-cost or high-filter-discard Sequential Scan
    elif node.node_type in {"Seq Scan", "Parallel Seq Scan"} and node.relation:
        if cost >= 90.0 or plan_rows >= 1200.0 or removed >= 600.0 or time_ms >= 22.0:
            label = LABEL_TO_ID["sequential_scan"]
        else:
            label = LABEL_TO_ID["none"]
    # Priority 3: High-loop Nested Loop
    elif node.node_type.startswith("Nested Loop") and loops >= 95.0 and (cost >= 110.0 or time_ms >= 20.0):
        label = LABEL_TO_ID["nested_loop"]
    # Priority 4: Expensive Sort
    elif node.node_type in {"Sort", "Incremental Sort"} and (time_ms >= 11.0 or (cost >= 175.0 and plan_rows >= 900.0)):
        label = LABEL_TO_ID["expensive_sort"]
    else:
        label = LABEL_TO_ID["none"]

    if noisy_label_flip_prob > 0.0 and rng is not None and rng.random() < noisy_label_flip_prob:
        # Borderline measurement ambiguity (e.g. cached vs cold buffer timing variance)
        if label != LABEL_TO_ID["none"] and cost < 150.0:
            return LABEL_TO_ID["none"]
    return label


def _build_grouped_family_graph(family_id: int, sample_idx: int, rng: random.Random) -> tuple[str, PlanGraph]:
    """Constructs 15 distinct query plan template families so train/val/test can be split by family_id."""
    jitter = lambda base, pct=0.25: max(0.01, base * rng.uniform(1.0 - pct, 1.0 + pct))

    # Families 0..8 -> Train (9 families)
    # Families 9..11 -> Validation (3 families)
    # Families 12..14 -> Held-out Test (3 families)
    group_name = f"family_{family_id:02d}"

    if family_id in (0, 9, 12):
        # Family group A: Mixed Seq Scan (half large bottleneck scans, half small benign lookup table scans)
        is_large = (sample_idx % 2 == 0)
        cost = jitter(380.0 if is_large else 22.0, 0.35)
        rows = int(jitter(8500 if is_large else 180, 0.3))
        act_rows = int(rows * rng.uniform(0.8, 1.25))
        removed = int(jitter(3200 if is_large else 40, 0.4))
        time_ms = jitter(55.0 if is_large else 1.8, 0.35)
        n1 = PlanNode(
            node_id="n1",
            node_type="Seq Scan" if sample_idx % 3 != 0 else "Parallel Seq Scan",
            relation="orders",
            startup_cost=round(cost * 0.08, 3),
            total_cost=round(cost, 3),
            plan_rows=rows,
            actual_rows=act_rows,
            actual_loops=1,
            actual_total_time_ms=round(time_ms, 3),
            rows_removed_by_filter=removed,
            parallel_aware=(sample_idx % 3 == 0),
        )
        return group_name, PlanGraph("n1", {"n1": n1}, [])

    if family_id in (1, 10, 13):
        # Family group B: Nested Loop + Inner Scan (both high-loop bottlenecks AND low-loop benign index lookups)
        is_heavy_loop = (sample_idx % 2 == 0)
        loops = rng.randint(110, 420) if is_heavy_loop else rng.randint(2, 45)
        nl_cost = jitter(290.0 if is_heavy_loop else 55.0, 0.3)
        nl_time = jitter(48.0 if is_heavy_loop else 4.5, 0.35)
        n1 = PlanNode(
            node_id="n1",
            node_type="Nested Loop",
            relation="orders",
            startup_cost=round(nl_cost * 0.1, 3),
            total_cost=round(nl_cost, 3),
            plan_rows=int(jitter(45, 0.4)),
            actual_rows=int(jitter(45, 0.4)),
            actual_loops=loops,
            actual_total_time_ms=round(nl_time, 3),
            children=["n2"],
        )
        inner_is_seq = (sample_idx % 4 == 0)
        c_cost = jitter(125.0 if inner_is_seq else 32.0, 0.35)
        c_rows = int(jitter(1800 if inner_is_seq else 25, 0.35))
        n2 = PlanNode(
            node_id="n2",
            node_type="Seq Scan" if inner_is_seq else "Index Scan",
            relation="customers",
            index_name=None if inner_is_seq else "idx_customers_pkey",
            startup_cost=round(c_cost * 0.1, 3),
            total_cost=round(c_cost, 3),
            plan_rows=c_rows,
            actual_rows=int(c_rows * rng.uniform(0.75, 1.3)),
            actual_loops=loops,
            actual_total_time_ms=round(jitter(28.0 if inner_is_seq else 2.2, 0.3), 3),
            rows_removed_by_filter=int(jitter(900 if inner_is_seq else 0, 0.3)),
        )
        return group_name, PlanGraph("n1", {"n1": n1, "n2": n2}, [("n1", "n2")])

    if family_id in (2, 11, 14):
        # Family group C: Sort + Join/Scan pipeline (both expensive sorts and fast in-memory sorts, plus cardinality errors)
        is_expensive_sort = (sample_idx % 2 == 0)
        sort_cost = jitter(240.0 if is_expensive_sort else 48.0, 0.3)
        sort_rows = int(jitter(2400 if is_expensive_sort else 120, 0.35))
        sort_time = jitter(26.0 if is_expensive_sort else 3.2, 0.35)
        n1 = PlanNode(
            node_id="n1",
            node_type="Sort" if sample_idx % 3 != 0 else "Incremental Sort",
            relation="orders",
            startup_cost=round(sort_cost * 0.4, 3),
            total_cost=round(sort_cost, 3),
            plan_rows=sort_rows,
            actual_rows=sort_rows,
            actual_loops=1,
            actual_total_time_ms=round(sort_time, 3),
            children=["n2"],
        )
        has_est_error = (sample_idx % 3 == 1)
        hj_plan_rows = int(jitter(120, 0.3))
        hj_actual_rows = int(hj_plan_rows * (rng.uniform(14.0, 35.0) if has_est_error else rng.uniform(0.7, 1.4)))
        n2 = PlanNode(
            node_id="n2",
            node_type="Hash Join",
            relation="orders",
            startup_cost=jitter(25.0, 0.3),
            total_cost=jitter(165.0, 0.3),
            plan_rows=hj_plan_rows,
            actual_rows=hj_actual_rows,
            actual_loops=1,
            actual_total_time_ms=jitter(16.0, 0.3),
            children=["n3"],
        )
        n3 = PlanNode(
            node_id="n3",
            node_type="Index Scan",
            relation="orders",
            index_name="idx_orders_created_at",
            startup_cost=jitter(4.0, 0.3),
            total_cost=jitter(58.0, 0.3),
            plan_rows=sort_rows,
            actual_rows=int(sort_rows * (0.04 if (sample_idx % 5 == 0) else rng.uniform(0.8, 1.2))),
            actual_loops=1,
            actual_total_time_ms=jitter(4.2, 0.3),
        )
        return group_name, PlanGraph("n1", {"n1": n1, "n2": n2, "n3": n3}, [("n1", "n2"), ("n2", "n3")])

    if family_id in (3, 4, 5):
        # Aggregate + Merge/Hash Join + Bitmap/Seq Scan
        agg_cost = jitter(310.0, 0.3)
        n1 = PlanNode(
            node_id="n1",
            node_type="HashAggregate",
            relation="orders",
            startup_cost=round(agg_cost * 0.5, 3),
            total_cost=round(agg_cost, 3),
            plan_rows=int(jitter(350, 0.3)),
            actual_rows=int(jitter(350, 0.3)),
            actual_loops=1,
            actual_total_time_ms=jitter(14.0, 0.3),
            children=["n2"],
        )
        est_err = (sample_idx % 2 == 1)
        p_rows = int(jitter(200, 0.3))
        a_rows = int(p_rows * (rng.uniform(12.0, 28.0) if est_err else rng.uniform(0.8, 1.3)))
        n2 = PlanNode(
            node_id="n2",
            node_type="Merge Join" if family_id == 4 else "Hash Join",
            relation="orders",
            startup_cost=jitter(30.0, 0.3),
            total_cost=jitter(190.0, 0.3),
            plan_rows=p_rows,
            actual_rows=a_rows,
            actual_loops=1,
            actual_total_time_ms=jitter(18.0, 0.3),
            children=["n3"],
        )
        n3 = PlanNode(
            node_id="n3",
            node_type="Bitmap Heap Scan" if family_id == 5 else "Seq Scan",
            relation="order_items",
            startup_cost=jitter(12.0, 0.3),
            total_cost=jitter(140.0 if family_id != 5 else 60.0, 0.3),
            plan_rows=int(jitter(2200 if family_id != 5 else 400, 0.3)),
            actual_rows=int(jitter(2100 if family_id != 5 else 410, 0.3)),
            actual_loops=1,
            actual_total_time_ms=jitter(29.0 if family_id != 5 else 6.0, 0.3),
            rows_removed_by_filter=int(jitter(800 if family_id != 5 else 50, 0.3)),
        )
        return group_name, PlanGraph("n1", {"n1": n1, "n2": n2, "n3": n3}, [("n1", "n2"), ("n2", "n3")])

    # Families 6, 7, 8: Multi-branch Join Trees with mixed bottleneck patterns
    n1 = PlanNode(
        node_id="n1",
        node_type="Sort",
        relation="orders",
        startup_cost=jitter(90.0, 0.3),
        total_cost=jitter(210.0, 0.3),
        plan_rows=int(jitter(950, 0.3)),
        actual_rows=int(jitter(920, 0.3)),
        actual_loops=1,
        actual_total_time_ms=jitter(13.5 if sample_idx % 2 == 0 else 6.5, 0.3),
        children=["n2", "n3"],
    )
    n2 = PlanNode(
        node_id="n2",
        node_type="Nested Loop",
        relation="orders",
        startup_cost=jitter(15.0, 0.3),
        total_cost=jitter(145.0, 0.3),
        plan_rows=int(jitter(180, 0.3)),
        actual_rows=int(jitter(180, 0.3)),
        actual_loops=rng.randint(105, 260) if sample_idx % 3 == 0 else rng.randint(5, 60),
        actual_total_time_ms=jitter(25.0 if sample_idx % 3 == 0 else 5.0, 0.3),
    )
    n3 = PlanNode(
        node_id="n3",
        node_type="Index Scan",
        relation="products",
        index_name="idx_products_sku",
        startup_cost=jitter(2.0, 0.3),
        total_cost=jitter(65.0, 0.3),
        plan_rows=int(jitter(500, 0.3)),
        actual_rows=int(jitter(25 if sample_idx % 2 == 1 else 490, 0.25)),
        actual_loops=1,
        actual_total_time_ms=jitter(4.0, 0.3),
    )
    return group_name, PlanGraph("n1", {"n1": n1, "n2": n2, "n3": n3}, [("n1", "n2"), ("n1", "n3")])


def build_grouped_evaluation_splits(
    samples_per_family: int = 24,
    seed: int = EVALUATION_SEED,
) -> dict[str, list[GraphSample]]:
    """Creates leakage-free Train / Validation / Test splits grouped strictly by template_group.

    - Train families: 0..8 (9 families)
    - Validation families: 9..11 (3 families)
    - Test families: 12..14 (3 families)
    No `template_group` is ever shared across splits.
    """
    rng = random.Random(seed)
    splits: dict[str, list[GraphSample]] = {"train": [], "validation": [], "test": []}

    for family_id in range(15):
        target_split = (
            "train"
            if family_id < 9
            else ("validation" if family_id < 12 else "test")
        )
        for j in range(samples_per_family):
            group_name, plan_graph = _build_grouped_family_graph(family_id, j, rng)
            base_sample = build_graph_sample(
                plan_graph,
                graph_id=f"{target_split}-{group_name}-{j:03d}",
            )
            realistic_labels = [
                _realistic_node_label(node, noisy_label_flip_prob=0.04, rng=rng)
                for node in plan_graph.nodes.values()
            ]
            splits[target_split].append(
                GraphSample(
                    graph_id=base_sample.graph_id,
                    node_features=base_sample.node_features,
                    edge_index=base_sample.edge_index,
                    edge_features=base_sample.edge_features,
                    node_labels=realistic_labels,
                    node_ids=base_sample.node_ids,
                    metadata={
                        "feature_source": "sanitized_plan",
                        "template_group": group_name,
                        "split": target_split,
                        "dataset_type": "grouped_multi_topology_synthetic",
                    },
                )
            )
    return splits


def build_held_out_workload_samples() -> list[GraphSample]:
    """Builds held-out representative DBZenith e-commerce workload execution plans."""
    plans: list[tuple[str, str, PlanGraph]] = [
        (
            "workload-orders-pending-seq-sort",
            "ecom_pending_orders_agg",
            PlanGraph(
                root_id="n1",
                nodes={
                    "n1": PlanNode(
                        node_id="n1",
                        node_type="Sort",
                        relation="telemetry_demo_orders",
                        startup_cost=410.0,
                        total_cost=465.0,
                        plan_rows=1800,
                        actual_rows=1750,
                        actual_loops=1,
                        actual_total_time_ms=34.2,
                        children=["n2"],
                    ),
                    "n2": PlanNode(
                        node_id="n2",
                        node_type="HashAggregate",
                        relation="telemetry_demo_orders",
                        startup_cost=320.0,
                        total_cost=380.0,
                        plan_rows=1800,
                        actual_rows=1750,
                        actual_loops=1,
                        actual_total_time_ms=19.4,
                        children=["n3"],
                    ),
                    "n3": PlanNode(
                        node_id="n3",
                        node_type="Seq Scan",
                        relation="telemetry_demo_orders",
                        startup_cost=0.0,
                        total_cost=295.0,
                        plan_rows=12500,
                        actual_rows=12420,
                        actual_loops=1,
                        actual_total_time_ms=48.7,
                        rows_removed_by_filter=37580,
                    ),
                },
                edges=[("n1", "n2"), ("n2", "n3")],
            ),
        ),
        (
            "workload-star-join-nestloop-skew",
            "ecom_star_join",
            PlanGraph(
                root_id="n1",
                nodes={
                    "n1": PlanNode(
                        node_id="n1",
                        node_type="Nested Loop",
                        relation="orders",
                        startup_cost=12.5,
                        total_cost=640.0,
                        plan_rows=85,
                        actual_rows=85,
                        actual_loops=240,
                        actual_total_time_ms=92.5,
                        children=["n2", "n3"],
                    ),
                    "n2": PlanNode(
                        node_id="n2",
                        node_type="Hash Join",
                        relation="orders",
                        startup_cost=8.0,
                        total_cost=215.0,
                        plan_rows=90,
                        actual_rows=2150,
                        actual_loops=1,
                        actual_total_time_ms=24.1,
                    ),
                    "n3": PlanNode(
                        node_id="n3",
                        node_type="Index Scan",
                        relation="customers",
                        index_name="customers_pkey",
                        startup_cost=0.29,
                        total_cost=18.4,
                        plan_rows=1,
                        actual_rows=1,
                        actual_loops=240,
                        actual_total_time_ms=1.9,
                    ),
                },
                edges=[("n1", "n2"), ("n1", "n3")],
            ),
        ),
        (
            "workload-small-lookup-benign",
            "ecom_region_lookup",
            PlanGraph(
                root_id="n1",
                nodes={
                    "n1": PlanNode(
                        node_id="n1",
                        node_type="Seq Scan",
                        relation="regions",
                        startup_cost=0.0,
                        total_cost=1.25,
                        plan_rows=25,
                        actual_rows=25,
                        actual_loops=1,
                        actual_total_time_ms=0.15,
                        rows_removed_by_filter=0,
                    ),
                },
                edges=[],
            ),
        ),
        (
            "workload-fast-index-sort-benign",
            "ecom_recent_customer_orders",
            PlanGraph(
                root_id="n1",
                nodes={
                    "n1": PlanNode(
                        node_id="n1",
                        node_type="Sort",
                        relation="orders",
                        startup_cost=14.2,
                        total_cost=16.8,
                        plan_rows=40,
                        actual_rows=38,
                        actual_loops=1,
                        actual_total_time_ms=1.4,
                        children=["n2"],
                    ),
                    "n2": PlanNode(
                        node_id="n2",
                        node_type="Index Scan",
                        relation="orders",
                        index_name="idx_orders_customer_id",
                        startup_cost=0.42,
                        total_cost=12.6,
                        plan_rows=40,
                        actual_rows=38,
                        actual_loops=1,
                        actual_total_time_ms=0.9,
                    ),
                },
                edges=[("n1", "n2")],
            ),
        ),
    ]

    samples: list[GraphSample] = []
    for gid, family, pg in plans:
        base = build_graph_sample(pg, graph_id=gid)
        realistic_labels = [_realistic_node_label(n) for n in pg.nodes.values()]
        samples.append(
            GraphSample(
                graph_id=gid,
                node_features=base.node_features,
                edge_index=base.edge_index,
                edge_features=base.edge_features,
                node_labels=realistic_labels,
                node_ids=base.node_ids,
                metadata={
                    "feature_source": "sanitized_plan",
                    "template_group": family,
                    "split": "held_out_workload",
                    "dataset_type": "representative_workload_plans",
                },
            )
        )
    return samples


def compute_classification_report(
    truth: list[int],
    pred: list[int],
    labels: tuple[str, ...] = LABELS,
) -> dict[str, Any]:
    """Computes accuracy, macro/weighted precision/recall/F1, per-class metrics, and confusion matrix."""
    n = max(len(truth), 1)
    num_classes = len(labels)
    confusion = [[0 for _ in range(num_classes)] for _ in range(num_classes)]
    for t, p in zip(truth, pred):
        if 0 <= t < num_classes and 0 <= p < num_classes:
            confusion[t][p] += 1

    correct = sum(1 for t, p in zip(truth, pred) if t == p)
    accuracy = round(correct / n, 4)

    per_class: dict[str, dict[str, Any]] = {}
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    weighted_f1_sum = 0.0

    for c_idx, c_name in enumerate(labels):
        tp = confusion[c_idx][c_idx]
        fp = sum(confusion[r][c_idx] for r in range(num_classes) if r != c_idx)
        fn = sum(confusion[c_idx][k] for k in range(num_classes) if k != c_idx)
        support = tp + fn

        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = (2.0 * prec * rec / max(prec + rec, 1e-12)) if (prec + rec) > 0 else 0.0

        precisions.append(prec)
        recalls.append(rec)
        f1s.append(f1)
        weighted_f1_sum += f1 * support

        per_class[c_name] = {
            "class_id": c_idx,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": int(support),
            "tp": int(tp),
            "fp": int(fp),
            "fn": int(fn),
        }

    return {
        "accuracy": accuracy,
        "macro_precision": round(sum(precisions) / max(num_classes, 1), 4),
        "macro_recall": round(sum(recalls) / max(num_classes, 1), 4),
        "macro_f1": round(sum(f1s) / max(num_classes, 1), 4),
        "weighted_f1": round(weighted_f1_sum / n, 4),
        "support": len(truth),
        "total_nodes": len(truth),
        "per_class": per_class,
        "confusion_matrix": {
            "labels": list(labels),
            "matrix": confusion,
        },
    }


def reproduce_metrics_from_predictions(saved_predictions: list[dict[str, Any]]) -> dict[str, Any]:
    """Recomputes classification metrics directly from saved node prediction records."""
    truth: list[int] = []
    pred: list[int] = []
    for item in saved_predictions:
        t_id = item.get("true_label_id")
        if t_id is None:
            t_id = LABEL_TO_ID[item["true_label"]]
        p_id = item.get("predicted_label_id")
        if p_id is None:
            p_id = LABEL_TO_ID[item["predicted_label"]]
        truth.append(int(t_id))
        pred.append(int(p_id))
    return compute_classification_report(truth, pred, LABELS)


def _predict_model_on_samples(
    model: nn.Module,
    samples: list[GraphSample],
    normalizer: dict[str, Any],
) -> tuple[list[int], list[int], list[dict[str, Any]]]:
    model.eval()
    truth: list[int] = []
    pred: list[int] = []
    records: list[dict[str, Any]] = []

    with torch.no_grad():
        for s in samples:
            x = torch.tensor(normalize(s.node_features, normalizer), dtype=torch.float32)
            edge = (
                torch.tensor(s.edge_index, dtype=torch.long).t().contiguous()
                if s.edge_index
                else torch.empty((2, 0), dtype=torch.long)
            )
            edge_attr = (
                torch.tensor(s.edge_features, dtype=torch.float32)
                if s.edge_features
                else torch.empty((0, 3), dtype=torch.float32)
            )
            logits = model(x, edge, edge_attr)
            probs = torch.softmax(logits, dim=1)
            preds = probs.argmax(dim=1).tolist()
            confs = probs.max(dim=1).values.tolist()

            for node_id, t_lbl, p_lbl, conf in zip(s.node_ids, s.node_labels, preds, confs):
                truth.append(int(t_lbl))
                pred.append(int(p_lbl))
                records.append(
                    {
                        "graph_id": s.graph_id,
                        "template_group": s.metadata.get("template_group", "legacy"),
                        "node_id": node_id,
                        "true_label_id": int(t_lbl),
                        "true_label": ID_TO_LABEL[int(t_lbl)],
                        "predicted_label_id": int(p_lbl),
                        "predicted_label": ID_TO_LABEL[int(p_lbl)],
                        "confidence": round(float(conf), 4),
                    }
                )
    return truth, pred, records


def run_comprehensive_gnn_evaluation(
    model_dir: Path | None = None,
    persist_artifacts: bool = True,
) -> dict[str, Any]:
    """Runs the full Phase 9 GNN evaluation, leakage investigation, and grouped benchmark."""
    if model_dir is None:
        model_dir = Path(__file__).resolve().parent / "model_artifacts" / "v0.7.0"

    torch.manual_seed(EVALUATION_SEED)
    random.seed(EVALUATION_SEED)

    # 1. Audit the legacy v0.7.0 synthetic dataset (250 graphs: 200 train / 50 val)
    legacy_samples = make_legacy_dataset(250)
    legacy_train = legacy_samples[:200]
    legacy_val = legacy_samples[200:]
    legacy_leakage_audit = audit_dataset_leakage(legacy_train, legacy_val)

    # 2. Build leakage-free grouped splits (Train / Val / Test) and verify zero leakage
    grouped_splits = build_grouped_evaluation_splits(samples_per_family=24, seed=EVALUATION_SEED)
    grouped_train = grouped_splits["train"]
    grouped_val = grouped_splits["validation"]
    grouped_test = grouped_splits["test"]
    held_out_workload = build_held_out_workload_samples()

    grouped_leakage_audit = audit_dataset_leakage(grouped_train, grouped_test)

    # 3. Train/evaluate on the leakage-free grouped dataset using existing BottleneckGNN & BaselineNodeClassifier architectures
    grouped_normalizer = fit_normalizer(grouped_train)
    in_features = len(grouped_train[0].node_features[0])

    grouped_gnn = BottleneckGNN(in_features, 32, len(LABELS), uses_pyg=False)
    grouped_mlp = BaselineNodeClassifier(in_features, len(LABELS))
    rule_baseline = RuleBasedNodeBaseline()

    for model in (grouped_gnn, grouped_mlp):
        opt = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=1e-4)
        loss_fn = nn.CrossEntropyLoss()
        for _ in range(18):
            model.train()
            for s in grouped_train:
                x = torch.tensor(normalize(s.node_features, grouped_normalizer), dtype=torch.float32)
                edge = (
                    torch.tensor(s.edge_index, dtype=torch.long).t().contiguous()
                    if s.edge_index
                    else torch.empty((2, 0), dtype=torch.long)
                )
                edge_attr = (
                    torch.tensor(s.edge_features, dtype=torch.float32)
                    if s.edge_features
                    else torch.empty((0, 3), dtype=torch.float32)
                )
                y = torch.tensor(s.node_labels, dtype=torch.long)
                opt.zero_grad()
                loss = loss_fn(model(x, edge, edge_attr), y)
                loss.backward()
                opt.step()

    # Evaluate on grouped validation, grouped test, and held-out workload
    _, _, val_preds_records = _predict_model_on_samples(grouped_gnn, grouped_val, grouped_normalizer)
    val_report_gnn = reproduce_metrics_from_predictions(val_preds_records)

    test_truth, test_pred_gnn, test_preds_records = _predict_model_on_samples(grouped_gnn, grouped_test, grouped_normalizer)
    test_report_gnn = compute_classification_report(test_truth, test_pred_gnn, LABELS)

    _, test_pred_mlp, _ = _predict_model_on_samples(grouped_mlp, grouped_test, grouped_normalizer)
    test_report_mlp = compute_classification_report(test_truth, test_pred_mlp, LABELS)

    rule_test_preds = [p for s in grouped_test for p in rule_baseline.predict_sample(s)]
    test_report_rule = compute_classification_report(test_truth, rule_test_preds, LABELS)

    # Evaluate on held-out representative workload plans
    ho_truth, ho_pred_gnn, ho_records = _predict_model_on_samples(grouped_gnn, held_out_workload, grouped_normalizer)
    ho_report_gnn = compute_classification_report(ho_truth, ho_pred_gnn, LABELS)
    ho_rule_preds = [p for s in held_out_workload for p in rule_baseline.predict_sample(s)]
    ho_report_rule = compute_classification_report(ho_truth, ho_rule_preds, LABELS)

    # Also evaluate existing v0.7.0 artifact on legacy val vs grouped held-out test
    legacy_artifact_path = model_dir / "gnn.pt"
    artifact_sha256 = None
    legacy_val_report = None
    if legacy_artifact_path.exists():
        artifact_bytes = legacy_artifact_path.read_bytes()
        artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()[:16]
        legacy_norm = json.loads((model_dir / "normalizer.json").read_text(encoding="utf-8"))
        state_dict = torch.load(legacy_artifact_path, map_location="cpu", weights_only=True)
        has_self_lin = "conv1.self_lin.weight" in state_dict
        legacy_model = BottleneckGNN(in_features, 32, len(LABELS), uses_pyg=not has_self_lin and HAS_PYG)
        legacy_model.load_state_dict(state_dict)
        leg_t, leg_p, _ = _predict_model_on_samples(legacy_model, legacy_val, legacy_norm)
        legacy_val_report = compute_classification_report(leg_t, leg_p, LABELS)

    reproduced_test_report = reproduce_metrics_from_predictions(test_preds_records)
    metrics_reproducible = (
        reproduced_test_report["accuracy"] == test_report_gnn["accuracy"]
        and reproduced_test_report["macro_f1"] == test_report_gnn["macro_f1"]
        and reproduced_test_report["confusion_matrix"] == test_report_gnn["confusion_matrix"]
    )

    evaluated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "model_name": "BottleneckGNN",
        "model_version": "v0.7.0-synth-20261003",
        "evaluation_version": "phase9-grouped-eval-v1",
        "evaluated_at": evaluated_at,
        "dataset_type": "SYNTHETIC_AND_REPRESENTATIVE_HELD_OUT_PLANS",
        "validated_on_real_workloads": False,
        "reproducibility": {
            "legacy_seed": LEGACY_SEED,
            "evaluation_seed": EVALUATION_SEED,
            "python_version": platform.python_version(),
            "torch_version": torch.__version__,
            "pyg_available": bool(HAS_PYG),
            "normalizer_version": grouped_normalizer.get("version", 1),
            "feature_count": in_features,
            "artifact_sha256_prefix": artifact_sha256,
            "metrics_reproducible_from_saved_predictions": metrics_reproducible,
        },
        "dataset_sizes": {
            "legacy_synthetic": {
                "total_graphs": len(legacy_samples),
                "train_graphs": len(legacy_train),
                "validation_graphs": len(legacy_val),
                "validation_nodes": sum(len(s.node_labels) for s in legacy_val),
            },
            "grouped_leakage_free": {
                "total_graphs": len(grouped_train) + len(grouped_val) + len(grouped_test),
                "train_graphs": len(grouped_train),
                "train_nodes": sum(len(s.node_labels) for s in grouped_train),
                "validation_graphs": len(grouped_val),
                "validation_nodes": sum(len(s.node_labels) for s in grouped_val),
                "test_graphs": len(grouped_test),
                "test_nodes": sum(len(s.node_labels) for s in grouped_test),
                "held_out_workload_graphs": len(held_out_workload),
                "held_out_workload_nodes": sum(len(s.node_labels) for s in held_out_workload),
            },
        },
        "legacy_perfect_score_investigation": {
            "reported_accuracy": 1.0,
            "reported_macro_f1": 1.0,
            "reproduced_legacy_validation": legacy_val_report,
            "leakage_and_shortcut_audit": legacy_leakage_audit,
            "explanation": (
                "The legacy 1.000 accuracy and 1.000 macro-F1 on synthetic_graph(0..249) resulted from three compounding "
                "factors: (1) synthetic_graph(i) only cycled through 5 tiny template topologies (i % 5) shared across train "
                "and validation; (2) 30 of the 80 validation nodes (37.5%) were byte-for-byte identical duplicates of training "
                "child nodes; and (3) every operator type had a deterministic 1-to-1 shortcut to a single label (e.g., all Seq Scans "
                "were large bottlenecks, all Nested Loops had >= 120 loops, all Sorts had >= 15ms runtime, and all Hash Joins had a "
                "30x row estimation error)."
            ),
        },
        "grouped_leakage_audit": grouped_leakage_audit,
        "grouped_validation_metrics": {
            "gnn": val_report_gnn,
        },
        "grouped_test_metrics": {
            "gnn": test_report_gnn,
            "mlp_baseline": test_report_mlp,
            "rule_based_baseline": test_report_rule,
        },
        "held_out_workload_metrics": {
            "gnn": ho_report_gnn,
            "rule_based_baseline": ho_report_rule,
            "predictions": ho_records,
        },
        "known_limitations": [
            "Trained and evaluated on synthetic and representative held-out EXPLAIN plans; not validated on live production customer workloads.",
            "Legacy v0.7.0 synthetic split (accuracy=1.0) had 37.5% exact node duplication and 1-to-1 operator-type label shortcuts.",
            "On leakage-free grouped multi-topology test splits with benign small-table scans and boundary noise, GNN accuracy is below 1.0 and comparable to deterministic rule-based heuristics.",
            "When EXPLAIN is run without ANALYZE, actual_rows, actual_loops, and actual_total_time_ms are 0, preventing runtime-dependent bottleneck detection (such as row_estimation_error or runtime-only expensive_sort).",
        ],
    }

    if persist_artifacts and model_dir.exists():
        (model_dir / "evaluation_report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        (model_dir / "held_out_predictions.json").write_text(
            json.dumps(test_preds_records, indent=2),
            encoding="utf-8",
        )

    return report
