# AI

AI functionality is intentionally not implemented in DBZenith v0.3.

When GNN, reinforcement-learning, or agent components are added, they must consume `AIWorkloadRecord` only through the privacy boundary. `RawQuery` and `RawPlan` are never valid AI inputs.
