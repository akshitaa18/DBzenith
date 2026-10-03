# DBZenith GNN subsystem

DBZenith v0.7 adds a learned bottleneck-prediction path while retaining deterministic plan analysis as the safety fallback.

## Privacy boundary

Only the sanitized `PlanGraph` is passed to the learned subsystem. Node features are numeric plan properties such as costs, estimated/actual row counts, loop counts, operator flags, and parallelism. Edge features contain graph topology metadata only. Raw SQL literals, row values, emails, phone numbers, and other production values are not included.

## Pipeline

`sanitized PostgreSQL EXPLAIN JSON -> PlanGraph -> numeric node/edge features -> GCN -> node bottleneck predictions -> evidence-based explanation`

PyTorch Geometric's `GCNConv` is the primary implementation when installed. The project also contains a pure-PyTorch message-passing compatibility fallback so constrained build environments can execute the same model contract. PyG is the production dependency.

## Dataset format

The reproducible synthetic dataset is JSONL. Each row contains:

- `graph_id`
- `node_features`
- `edge_index`
- `edge_features`
- `node_labels`
- `node_ids`
- `metadata.feature_source`

No production query text or row values are present.

## Model and baseline

The baseline is a per-node MLP that receives node features but does not use graph connectivity. The learned model is a two-layer GCN/message-passing classifier with a five-class bottleneck vocabulary:

- none
- sequential_scan
- nested_loop
- expensive_sort
- row_estimation_error

Model artifacts are versioned under `ai/gnn/models/v0.7.0/`.

## Reproducible evaluation

Training uses seed `20261003`, 250 synthetic graphs, an 80/20 train/validation split, 21 numeric node features, Adam, and 20 epochs.

Recorded held-out metrics from the generated dataset:

| Model | Accuracy | Macro F1 | Support |
|---|---:|---:|---:|
| Baseline MLP | 100.0% | 1.000 | 80 |
| GNN | 100.0% | 1.000 | 80 |

These are metrics on the synthetic validation set only; they are not a claim of production accuracy. The synthetic labels are rule-generated from sanitized plan signals, so the benchmark measures pipeline correctness rather than real-world generalization.

## Inference and fallback

Plan analysis attempts GNN inference only when a versioned model artifact is present and loadable. If inference is unavailable or fails, deterministic bottleneck detection remains authoritative. The API persists the learned result inside the plan-analysis explanation payload without exposing raw data.
