from app.services.sandbox.simulator import SandboxSimulator, _INDEX_CHANGE


def test_index_recommendation_parser_supports_concurrent_anonymous_index():
    match = _INDEX_CHANGE.match("CREATE INDEX CONCURRENTLY ON telemetry_demo_orders (customer_id, created_at);")
    assert match is not None
    assert match.group("index") is None
    assert match.group("table") == "telemetry_demo_orders"
    assert match.group("columns") == "customer_id, created_at"


def test_index_recommendation_parser_supports_named_index():
    match = _INDEX_CHANGE.match("CREATE INDEX idx_demo ON public.telemetry_demo_orders (customer_id);")
    assert match is not None
    assert match.group("index") == "idx_demo"
    assert match.group("schema") == "public"


def test_simulation_readonly_guard():
    assert SandboxSimulator._readonly_sql("SELECT 1") == "SELECT 1"
    assert SandboxSimulator._readonly_sql("WITH x AS (SELECT 1) SELECT * FROM x")
    for sql in ("UPDATE t SET x=1", "DROP TABLE t", "CREATE INDEX x ON t (a)"):
        try:
            SandboxSimulator._readonly_sql(sql)
        except ValueError:
            pass
        else:
            raise AssertionError("non-read-only SQL was accepted")
