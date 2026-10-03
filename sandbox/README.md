# Isolated PostgreSQL Optimization Sandbox

DBZenith v0.6 uses a dedicated PostgreSQL 17 sandbox container for optimization simulations.

- The sandbox has its own database, user, volume, and internal Docker network.
- HypoPG is installed only in the sandbox database.
- Simulation queries and benchmarks execute only against sandbox data.
- Production credentials are never passed to the sandbox container.
- Production is read only from the backend during schema/data replication; simulation DDL and
  HypoPG state are confined to the sandbox and are cleaned up after every run.
- Per-simulation statement, lock, temp-file, row-copy, and benchmark limits are enforced.

The normal index simulation flow is:

1. replicate the affected table(s) into the sandbox
2. run a baseline EXPLAIN
3. create a HypoPG hypothetical index
4. run the proposed EXPLAIN
5. compare plan costs and node changes
6. optionally benchmark baseline and a real sandbox-only copy of the index
7. estimate storage/write overhead from production catalog statistics
8. drop the sandbox index and clean all sandbox objects
