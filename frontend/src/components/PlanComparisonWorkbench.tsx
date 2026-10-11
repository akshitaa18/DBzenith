import { useEffect, useRef, useState } from 'react'
import {
  cancelBenchmarkRun,
  comparePlans,
  exportPlanComparison,
  runSafeBenchmark,
  type DetailedPlanNode,
  type ParsedPlanTree,
  type PlanComparisonExportResult,
  type PlanComparisonResult,
  type SafeBenchmarkResult,
} from '../lib/api'
import { ProvenanceBadge } from './ProvenanceBadge'

type Props = {
  initialQueryId?: string | number | null
  initialBaselineSql?: string
  initialCandidateSql?: string
  initialCandidateIndexDdl?: string
  initialRecommendationId?: number | null
  initialSimulationId?: number | null
  initialBaselinePlan?: unknown
  initialCandidatePlan?: unknown
  canRunBenchmark?: boolean
}

const DEFAULT_BASELINE_SQL =
  "SELECT id, customer_id, amount, status, created_at FROM orders WHERE amount > 250 AND status = 'PENDING' ORDER BY created_at DESC LIMIT 100"
const DEFAULT_INDEX_DDL =
  'CREATE INDEX idx_orders_status_amount ON orders (status, amount)'

export function PlanComparisonWorkbench({
  initialQueryId,
  initialBaselineSql,
  initialCandidateSql,
  initialCandidateIndexDdl,
  initialRecommendationId,
  initialSimulationId,
  initialBaselinePlan,
  initialCandidatePlan,
  canRunBenchmark = true,
}: Props) {
  const [baselineSql, setBaselineSql] = useState(initialBaselineSql || DEFAULT_BASELINE_SQL)
  const [candidateMode, setCandidateMode] = useState<'index' | 'rewrite'>(
    initialCandidateSql && !initialCandidateIndexDdl ? 'rewrite' : 'index',
  )
  const [candidateIndexDdl, setCandidateIndexDdl] = useState(
    initialCandidateIndexDdl || DEFAULT_INDEX_DDL,
  )
  const [candidateSql, setCandidateSql] = useState(initialCandidateSql || '')

  const [warmupRuns, setWarmupRuns] = useState(1)
  const [benchmarkRuns, setBenchmarkRuns] = useState(3)
  const [timeoutMs, setTimeoutMs] = useState(3000)

  const [comparison, setComparison] = useState<PlanComparisonResult | null>(null)
  const [benchmarkResult, setBenchmarkResult] = useState<SafeBenchmarkResult | null>(null)
  const [exportPreview, setExportPreview] = useState<PlanComparisonExportResult | null>(null)

  const [loadingCompare, setLoadingCompare] = useState(false)
  const [runningBenchmark, setRunningBenchmark] = useState(false)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [exportingFormat, setExportingFormat] = useState<'json' | 'csv' | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (initialBaselineSql) setBaselineSql(initialBaselineSql)
    if (initialCandidateIndexDdl) {
      setCandidateIndexDdl(initialCandidateIndexDdl)
      setCandidateMode('index')
    }
    if (initialCandidateSql) {
      setCandidateSql(initialCandidateSql)
      if (!initialCandidateIndexDdl) setCandidateMode('rewrite')
    }
  }, [initialBaselineSql, initialCandidateIndexDdl, initialCandidateSql])

  useEffect(() => {
    // Load initial plan comparison automatically if plans, simulation, recommendation, or query context is provided
    void handleComparePlans()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQueryId, initialRecommendationId, initialSimulationId])

  async function handleComparePlans() {
    setLoadingCompare(true)
    setErrorMessage(null)
    try {
      const res = await comparePlans({
        query_id: initialQueryId ?? undefined,
        simulation_id: initialSimulationId ?? undefined,
        recommendation_id: initialRecommendationId ?? undefined,
        baseline_plan: initialBaselinePlan ?? undefined,
        candidate_plan: initialCandidatePlan ?? undefined,
        baseline_sql: baselineSql.trim() || undefined,
        candidate_sql: candidateMode === 'rewrite' && candidateSql.trim() ? candidateSql.trim() : undefined,
        candidate_index_ddl:
          candidateMode === 'index' && candidateIndexDdl.trim() ? candidateIndexDdl.trim() : undefined,
      })
      setComparison(res)
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to compare execution plans.')
    } finally {
      setLoadingCompare(false)
    }
  }

  async function handleRunBenchmark() {
    if (!canRunBenchmark) return
    const runId = `bench-${Date.now().toString(36)}`
    setActiveRunId(runId)
    setRunningBenchmark(true)
    setErrorMessage(null)
    setExportPreview(null)

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const res = await runSafeBenchmark(
        {
          run_id: runId,
          query_id: initialQueryId ?? undefined,
          recommendation_id: initialRecommendationId ?? undefined,
          baseline_sql: baselineSql.trim() || undefined,
          candidate_sql:
            candidateMode === 'rewrite' && candidateSql.trim() ? candidateSql.trim() : undefined,
          candidate_index_ddl:
            candidateMode === 'index' && candidateIndexDdl.trim()
              ? candidateIndexDdl.trim()
              : undefined,
          baseline_plan: comparison?.baseline_plan ?? initialBaselinePlan ?? undefined,
          candidate_plan: comparison?.candidate_plan ?? initialCandidatePlan ?? undefined,
          warmup_runs: warmupRuns,
          benchmark_runs: benchmarkRuns,
          statement_timeout_ms: timeoutMs,
        },
        controller.signal,
      )
      setBenchmarkResult(res)
      if (res.plan_comparison && res.plan_comparison.baseline_plan?.has_plan) {
        setComparison(res.plan_comparison)
      }
    } catch (err) {
      if ((err as any)?.name === 'AbortError') {
        setBenchmarkResult({
          run_id: runId,
          status: 'cancelled',
          comparison_verdict: 'cancelled',
          verdict_explanation: 'Benchmark cancelled by operator; sandbox transaction rolled back.',
          cancelled: true,
          is_comparable: false,
          incomparability_reasons: ['Cancelled by operator.'],
          cost_unit: 'planner_cost_units',
          cost_disclaimer:
            'PostgreSQL planner costs are arbitrary relative page/CPU cost units, NOT milliseconds.',
          safeguards: { isolated_sandbox_only: true, read_only_transaction: true },
          environment: {},
          baseline_metrics: {
            unit: 'ms',
            is_measured: false,
            warmup_runs_requested: warmupRuns,
            warmup_runs_completed: 0,
            measured_runs_requested: benchmarkRuns,
            sample_count: 0,
            failed_runs: 0,
            samples_ms: [],
            cold_first_run_ms: null,
            median_ms: null,
            p95_ms: null,
            p95_note: 'Cancelled',
            mean_ms: null,
            min_ms: null,
            max_ms: null,
            stddev_ms: null,
            coefficient_of_variation: null,
            shared_hit_blocks_median: 0,
            shared_read_blocks_median: 0,
            cache_hit_ratio: null,
            cache_state: 'unmeasured',
            actual_rows: null,
          },
          candidate_metrics: {
            unit: 'ms',
            is_measured: false,
            warmup_runs_requested: warmupRuns,
            warmup_runs_completed: 0,
            measured_runs_requested: benchmarkRuns,
            sample_count: 0,
            failed_runs: 0,
            samples_ms: [],
            cold_first_run_ms: null,
            median_ms: null,
            p95_ms: null,
            p95_note: 'Cancelled',
            mean_ms: null,
            min_ms: null,
            max_ms: null,
            stddev_ms: null,
            coefficient_of_variation: null,
            shared_hit_blocks_median: 0,
            shared_read_blocks_median: 0,
            cache_hit_ratio: null,
            cache_state: 'unmeasured',
            actual_rows: null,
          },
          measured_comparison: {
            unit: 'ms',
            is_measured: false,
            baseline_median_ms: null,
            candidate_median_ms: null,
            baseline_p95_ms: null,
            candidate_p95_ms: null,
            median_delta_ms: null,
            measured_speedup_pct: null,
            p95_speedup_pct: null,
            note: 'Cancelled by user.',
          },
          estimated_cost_comparison: comparison?.cost_comparison || {
            unit: 'planner_cost_units',
            is_measured_latency: false,
            baseline_startup_cost: 0,
            baseline_total_cost: 0,
            candidate_startup_cost: 0,
            candidate_total_cost: 0,
            cost_delta: 0,
            cost_reduction_pct: 0,
            baseline_estimated_rows: 0,
            candidate_estimated_rows: 0,
            disclaimer: '',
          },
          plan_comparison: comparison as PlanComparisonResult,
        })
      } else {
        setErrorMessage(err instanceof Error ? err.message : 'Sandbox benchmark request failed.')
      }
    } finally {
      setRunningBenchmark(false)
      setActiveRunId(null)
      abortControllerRef.current = null
    }
  }

  async function handleCancelBenchmark() {
    if (activeRunId) {
      try {
        await cancelBenchmarkRun(activeRunId)
      } catch {
        // Ignore network errors during cancel signal
      }
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
  }

  async function handleExport(format: 'json' | 'csv') {
    setExportingFormat(format)
    setErrorMessage(null)
    try {
      const payloadToExport = benchmarkResult ?? comparison ?? undefined
      const exported = await exportPlanComparison({
        format,
        comparison: payloadToExport,
        baseline_sql: baselineSql.trim() || undefined,
        candidate_sql:
          candidateMode === 'rewrite' && candidateSql.trim() ? candidateSql.trim() : undefined,
        candidate_index_ddl:
          candidateMode === 'index' && candidateIndexDdl.trim()
            ? candidateIndexDdl.trim()
            : undefined,
        recommendation_id: initialRecommendationId ?? undefined,
      })
      setExportPreview(exported)
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to export plan comparison.')
    } finally {
      setExportingFormat(null)
    }
  }

  const activePlanComp =
    (benchmarkResult?.plan_comparison?.baseline_plan?.has_plan
      ? benchmarkResult.plan_comparison
      : comparison) ?? benchmarkResult?.plan_comparison ?? null

  const activeVerdict = benchmarkResult?.comparison_verdict || activePlanComp?.verdict || 'unchanged'
  const activeStatus = benchmarkResult?.status || 'ready'

  return (
    <div className="plan-comparison-workbench" data-testid="plan-comparison-workbench" style={{ marginTop: 20 }}>
      {/* Header & Controls Card */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.15rem' }}>
              Execution-Plan Diff &amp; Safe Sandbox Benchmarking Workbench
            </h2>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: '0.85rem' }}>
              Compare baseline vs. candidate PostgreSQL execution plans side-by-side and run bounded, read-only benchmarks in the isolated sandbox.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {benchmarkResult?.provenance_state ? (
              <ProvenanceBadge
                state={benchmarkResult.provenance_state}
                badge={benchmarkResult.provenance_badge}
                isSynthetic={benchmarkResult.is_synthetic}
              />
            ) : (
              <ProvenanceBadge
                state="HYPOTHETICAL_PLAN_ESTIMATE"
                badge="ESTIMATED"
              />
            )}
            <button
              type="button"
              className="secondary"
              disabled={exportingFormat !== null}
              onClick={() => void handleExport('json')}
              data-testid="export-plan-json-btn"
            >
              {exportingFormat === 'json' ? 'Exporting...' : 'Export JSON (Sanitized)'}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={exportingFormat !== null}
              onClick={() => void handleExport('csv')}
              data-testid="export-plan-csv-btn"
            >
              {exportingFormat === 'csv' ? 'Exporting...' : 'Export CSV (Sanitized)'}
            </button>
          </div>
        </div>

        {/* Query & Candidate Change Inputs */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 14,
            marginTop: 14,
          }}
        >
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: 4 }}>
              Baseline SQL Query (Read-Only SELECT / WITH)
            </label>
            <textarea
              rows={3}
              value={baselineSql}
              onChange={(e) => setBaselineSql(e.target.value)}
              placeholder="SELECT ... FROM ..."
              data-testid="workbench-baseline-sql"
              style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.82rem' }}
            />
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <label style={{ fontSize: '0.8rem', fontWeight: 600 }}>
                Candidate Optimization ({candidateMode === 'index' ? 'Sandbox Index DDL' : 'Candidate SQL Rewrite'})
              </label>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  type="button"
                  className={candidateMode === 'index' ? '' : 'secondary'}
                  style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                  onClick={() => setCandidateMode('index')}
                >
                  Candidate Index
                </button>
                <button
                  type="button"
                  className={candidateMode === 'rewrite' ? '' : 'secondary'}
                  style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                  onClick={() => setCandidateMode('rewrite')}
                >
                  SQL Rewrite
                </button>
              </div>
            </div>
            {candidateMode === 'index' ? (
              <textarea
                rows={3}
                value={candidateIndexDdl}
                onChange={(e) => setCandidateIndexDdl(e.target.value)}
                placeholder="CREATE INDEX idx_name ON table (col1, col2)"
                data-testid="workbench-candidate-index"
                style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.82rem' }}
              />
            ) : (
              <textarea
                rows={3}
                value={candidateSql}
                onChange={(e) => setCandidateSql(e.target.value)}
                placeholder="SELECT ... (rewritten candidate query)"
                data-testid="workbench-candidate-sql"
                style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.82rem' }}
              />
            )}
          </div>
        </div>

        {/* Benchmark Parameters & Execution Buttons */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 12,
            marginTop: 12,
            paddingTop: 12,
            borderTop: '1px solid rgba(148, 163, 184, 0.15)',
          }}
        >
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', fontSize: '0.82rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Warm-up Runs:
              <input
                type="number"
                min={0}
                max={5}
                value={warmupRuns}
                onChange={(e) => setWarmupRuns(Number(e.target.value))}
                style={{ width: 58, padding: '3px 6px' }}
                data-testid="workbench-warmup-input"
              />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Measured Runs:
              <input
                type="number"
                min={1}
                max={10}
                value={benchmarkRuns}
                onChange={(e) => setBenchmarkRuns(Number(e.target.value))}
                style={{ width: 58, padding: '3px 6px' }}
                data-testid="workbench-runs-input"
              />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Timeout (ms):
              <input
                type="number"
                min={100}
                max={15000}
                step={100}
                value={timeoutMs}
                onChange={(e) => setTimeoutMs(Number(e.target.value))}
                style={{ width: 78, padding: '3px 6px' }}
                data-testid="workbench-timeout-input"
              />
            </label>
            <span className="muted" style={{ fontSize: '0.76rem' }}>
              Safeguards: Isolated Sandbox · Read-Only Tx · Rollback Guaranteed · No Production SQL
            </span>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              type="button"
              className="secondary"
              disabled={loadingCompare || runningBenchmark}
              onClick={() => void handleComparePlans()}
              data-testid="compare-plans-btn"
            >
              {loadingCompare ? 'Comparing Plans...' : 'Compare Plans (Estimate)'}
            </button>

            {canRunBenchmark && !runningBenchmark && (
              <button
                type="button"
                disabled={loadingCompare}
                onClick={() => void handleRunBenchmark()}
                data-testid="run-safe-benchmark-btn"
              >
                Run Safe Sandbox Benchmark
              </button>
            )}

            {runningBenchmark && (
              <button
                type="button"
                onClick={() => void handleCancelBenchmark()}
                data-testid="cancel-benchmark-btn"
                style={{ background: '#dc2626', color: '#fff', borderColor: '#dc2626' }}
              >
                Cancel Benchmark ({activeRunId})
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Explicit Loading / Running State */}
      {runningBenchmark && (
        <div
          className="card"
          data-testid="benchmark-loading-state"
          style={{
            marginBottom: 16,
            border: '1px solid rgba(56, 189, 248, 0.45)',
            background: 'rgba(14, 116, 144, 0.14)',
          }}
        >
          <strong>Running Bounded Sandbox Benchmark ({activeRunId})...</strong>
          <p style={{ margin: '4px 0 0', fontSize: '0.85rem' }}>
            Executing {warmupRuns} warm-up run(s) and {benchmarkRuns} measured run(s) in isolated sandbox with{' '}
            <code>statement_timeout = {timeoutMs}ms</code> and <code>default_transaction_read_only = on</code>.
          </p>
        </div>
      )}

      {/* Error Banner */}
      {errorMessage && (
        <div className="error" data-testid="workbench-error-state" style={{ marginBottom: 16 }}>
          <strong>Workbench Error:</strong> {errorMessage}
        </div>
      )}

      {/* Explicit Unsupported / Timeout / Cancelled / Failed State Banners */}
      {benchmarkResult &&
        ['unsupported', 'invalid_sql', 'timeout', 'cancelled', 'failed', 'busy'].includes(activeStatus) && (
          <div
            className="card"
            data-testid={`benchmark-status-${activeStatus}`}
            style={{
              marginBottom: 16,
              border:
                activeStatus === 'timeout' || activeStatus === 'failed'
                  ? '1px solid rgba(239, 68, 68, 0.5)'
                  : '1px solid rgba(245, 158, 11, 0.5)',
              background:
                activeStatus === 'timeout' || activeStatus === 'failed'
                  ? 'rgba(127, 29, 29, 0.2)'
                  : 'rgba(120, 53, 15, 0.2)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span
                style={{
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontWeight: 700,
                  fontSize: '0.75rem',
                  textTransform: 'uppercase',
                  background: 'rgba(245, 158, 11, 0.25)',
                  color: '#fde68a',
                }}
              >
                {activeStatus.replace('_', ' ')}
              </span>
              <strong>
                {activeStatus === 'unsupported' && 'Query Not Supported for Safe Sandbox Execution'}
                {activeStatus === 'invalid_sql' && 'SQL Parsing Failed — Invalid Statement'}
                {activeStatus === 'timeout' && 'Sandbox Benchmark Timed Out'}
                {activeStatus === 'cancelled' && 'Sandbox Benchmark Cancelled'}
                {activeStatus === 'busy' && 'Sandbox Concurrency Limit Reached'}
                {activeStatus === 'failed' && 'Sandbox Benchmark Failed'}
              </strong>
            </div>
            <p style={{ margin: '6px 0 0', fontSize: '0.86rem' }}>
              {benchmarkResult.unsupported_reason ||
                benchmarkResult.error_reason ||
                benchmarkResult.verdict_explanation}
            </p>
          </div>
        )}

      {/* Sanitized Export Preview Drawer */}
      {exportPreview && (
        <div
          className="card"
          data-testid="export-preview-card"
          style={{ marginBottom: 16, border: '1px solid rgba(74, 222, 128, 0.35)' }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <strong>
                Authorized Export Ready: <code>{exportPreview.filename}</code>
              </strong>
              <span
                style={{
                  marginLeft: 10,
                  fontSize: '0.75rem',
                  padding: '2px 8px',
                  borderRadius: 4,
                  background: 'rgba(34, 197, 94, 0.2)',
                  color: '#4ade80',
                }}
              >
                Literals Scrubbed: {exportPreview.literals_scrubbed ? 'YES (<STR> / <NUM>)' : 'NO'}
              </span>
            </div>
            <button type="button" className="secondary" onClick={() => setExportPreview(null)}>
              Close Preview
            </button>
          </div>
          <pre
            data-testid="export-preview-content"
            style={{
              marginTop: 8,
              maxHeight: 200,
              overflow: 'auto',
              fontSize: '0.76rem',
              background: 'rgba(15, 23, 42, 0.8)',
              padding: 10,
              borderRadius: 6,
            }}
          >
            {exportPreview.content}
          </pre>
        </div>
      )}

      {/* Main Comparison Content */}
      {activePlanComp && (
        <>
          {/* Verdict & Candidate Responsibility Banner */}
          <div
            className="card"
            data-testid="plan-verdict-banner"
            style={{
              marginBottom: 16,
              borderLeft:
                activeVerdict.includes('improved')
                  ? '4px solid #22c55e'
                  : activeVerdict.includes('regressed')
                    ? '4px solid #ef4444'
                    : '4px solid #f59e0b',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span
                  data-testid="plan-verdict-badge"
                  style={{
                    padding: '3px 10px',
                    borderRadius: 6,
                    fontWeight: 700,
                    fontSize: '0.78rem',
                    textTransform: 'uppercase',
                    background: activeVerdict.includes('improved')
                      ? 'rgba(34, 197, 94, 0.2)'
                      : activeVerdict.includes('regressed')
                        ? 'rgba(239, 68, 68, 0.2)'
                        : 'rgba(245, 158, 11, 0.2)',
                    color: activeVerdict.includes('improved')
                      ? '#4ade80'
                      : activeVerdict.includes('regressed')
                        ? '#f87171'
                        : '#fbbf24',
                  }}
                >
                  Verdict: {activeVerdict.replace(/_/g, ' ')}
                </span>
                <strong>
                  {benchmarkResult?.verdict_explanation || activePlanComp.narrative_explanation}
                </strong>
              </div>
            </div>

            {/* Candidate SQL / Index Context */}
            <div
              style={{
                marginTop: 10,
                padding: '8px 12px',
                background: 'rgba(15, 23, 42, 0.55)',
                borderRadius: 6,
                fontSize: '0.8rem',
                display: 'grid',
                gap: 4,
              }}
            >
              <div>
                <span className="muted">Sanitized Baseline SQL: </span>
                <code>{activePlanComp.candidate_change_context?.sanitized_baseline_sql || scrubPreview(baselineSql)}</code>
              </div>
              {activePlanComp.candidate_change_context?.candidate_index_ddl && (
                <div>
                  <span className="muted">Candidate Index DDL: </span>
                  <code style={{ color: '#38bdf8' }}>
                    {activePlanComp.candidate_change_context.candidate_index_ddl}
                  </code>
                </div>
              )}
              {activePlanComp.candidate_change_context?.sanitized_candidate_sql &&
                activePlanComp.candidate_change_context.sanitized_candidate_sql !==
                  activePlanComp.candidate_change_context.sanitized_baseline_sql && (
                  <div>
                    <span className="muted">Sanitized Candidate Rewrite SQL: </span>
                    <code style={{ color: '#4ade80' }}>
                      {activePlanComp.candidate_change_context.sanitized_candidate_sql}
                    </code>
                  </div>
                )}
            </div>

            {benchmarkResult && !benchmarkResult.is_comparable && benchmarkResult.incomparability_reasons.length > 0 && (
              <div style={{ marginTop: 8, fontSize: '0.8rem', color: '#fbbf24' }}>
                <strong>Comparability Notice:</strong> {benchmarkResult.incomparability_reasons.join(' · ')}
              </div>
            )}
          </div>

          {/* Strictly Separated Panels: (1) Planner Cost Units vs (2) Measured Execution Time (ms) */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
              gap: 16,
              marginBottom: 16,
            }}
          >
            {/* Panel 1: Planner Cost Estimates (Arbitrary Units — NOT ms) */}
            <div className="card" data-testid="planner-cost-panel">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <h3 style={{ margin: 0, fontSize: '0.98rem' }}>
                  1. Estimated Planner Cost (Arbitrary Cost Units — NOT ms)
                </h3>
                <span
                  style={{
                    fontSize: '0.7rem',
                    padding: '2px 7px',
                    borderRadius: 4,
                    background: 'rgba(148, 163, 184, 0.18)',
                    color: '#cbd5e1',
                  }}
                >
                  Unit: {activePlanComp.cost_comparison.unit}
                </span>
              </div>
              <p className="muted" style={{ fontSize: '0.76rem', margin: '0 0 10px' }}>
                {activePlanComp.cost_disclaimer}
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                  <div className="muted" style={{ fontSize: '0.74rem' }}>Baseline Total Cost</div>
                  <div style={{ fontSize: '1.05rem', fontWeight: 700 }}>
                    {activePlanComp.cost_comparison.baseline_total_cost.toFixed(2)}{' '}
                    <small style={{ fontSize: '0.7rem', fontWeight: 400 }}>units</small>
                  </div>
                  <div className="muted" style={{ fontSize: '0.72rem' }}>
                    Est. rows: {activePlanComp.cost_comparison.baseline_estimated_rows.toLocaleString()}
                  </div>
                </div>
                <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                  <div className="muted" style={{ fontSize: '0.74rem' }}>Candidate Total Cost</div>
                  <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#38bdf8' }}>
                    {activePlanComp.cost_comparison.candidate_total_cost.toFixed(2)}{' '}
                    <small style={{ fontSize: '0.7rem', fontWeight: 400 }}>units</small>
                  </div>
                  <div className="muted" style={{ fontSize: '0.72rem' }}>
                    Est. rows: {activePlanComp.cost_comparison.candidate_estimated_rows.toLocaleString()}
                  </div>
                </div>
                <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                  <div className="muted" style={{ fontSize: '0.74rem' }}>Cost Reduction</div>
                  <div
                    style={{
                      fontSize: '1.05rem',
                      fontWeight: 700,
                      color:
                        activePlanComp.cost_comparison.cost_reduction_pct >= 0 ? '#4ade80' : '#f87171',
                    }}
                  >
                    {activePlanComp.cost_comparison.cost_reduction_pct >= 0 ? '-' : '+'}
                    {Math.abs(activePlanComp.cost_comparison.cost_reduction_pct).toFixed(2)}%
                  </div>
                  <div className="muted" style={{ fontSize: '0.72rem' }}>
                    Delta: {activePlanComp.cost_comparison.cost_delta.toFixed(2)} units
                  </div>
                </div>
              </div>
            </div>

            {/* Panel 2: Measured Execution Time (Milliseconds — Only when measured!) */}
            <div className="card" data-testid="measured-latency-panel">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <h3 style={{ margin: 0, fontSize: '0.98rem' }}>
                  2. Measured Sandbox Execution Time (Milliseconds)
                </h3>
                <span
                  style={{
                    fontSize: '0.7rem',
                    padding: '2px 7px',
                    borderRadius: 4,
                    background: benchmarkResult?.measured_comparison?.is_measured
                      ? 'rgba(34, 197, 94, 0.2)'
                      : 'rgba(148, 163, 184, 0.18)',
                    color: benchmarkResult?.measured_comparison?.is_measured ? '#4ade80' : '#cbd5e1',
                  }}
                >
                  {benchmarkResult?.measured_comparison?.is_measured
                    ? 'MEASURED (ms)'
                    : activePlanComp.actual_execution_comparison.is_measured_latency
                      ? 'PLAN ACTUALS (ms)'
                      : 'UNMEASURED'}
                </span>
              </div>

              {benchmarkResult?.measured_comparison?.is_measured ? (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                    <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                      <div className="muted" style={{ fontSize: '0.74rem' }}>Baseline Median (p50)</div>
                      <div style={{ fontSize: '1.05rem', fontWeight: 700 }}>
                        {benchmarkResult.measured_comparison.baseline_median_ms?.toFixed(2)} ms
                      </div>
                      <div className="muted" style={{ fontSize: '0.72rem' }}>
                        p95: {benchmarkResult.measured_comparison.baseline_p95_ms?.toFixed(2)} ms · n=
                        {benchmarkResult.baseline_metrics.sample_count}
                      </div>
                    </div>
                    <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                      <div className="muted" style={{ fontSize: '0.74rem' }}>Candidate Median (p50)</div>
                      <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#34d399' }}>
                        {benchmarkResult.measured_comparison.candidate_median_ms?.toFixed(2)} ms
                      </div>
                      <div className="muted" style={{ fontSize: '0.72rem' }}>
                        p95: {benchmarkResult.measured_comparison.candidate_p95_ms?.toFixed(2)} ms · n=
                        {benchmarkResult.candidate_metrics.sample_count}
                      </div>
                    </div>
                    <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                      <div className="muted" style={{ fontSize: '0.74rem' }}>Measured Speedup</div>
                      <div
                        style={{
                          fontSize: '1.05rem',
                          fontWeight: 700,
                          color:
                            (benchmarkResult.measured_comparison.measured_speedup_pct || 0) >= 0
                              ? '#4ade80'
                              : '#f87171',
                        }}
                      >
                        {(benchmarkResult.measured_comparison.measured_speedup_pct || 0) >= 0 ? '+' : ''}
                        {benchmarkResult.measured_comparison.measured_speedup_pct?.toFixed(2)}%
                      </div>
                      <div className="muted" style={{ fontSize: '0.72rem' }}>
                        CV: {((benchmarkResult.candidate_metrics.coefficient_of_variation || 0) * 100).toFixed(1)}%
                      </div>
                    </div>
                  </div>
                  <div className="muted" style={{ marginTop: 8, fontSize: '0.75rem' }}>
                    Warm-up: {benchmarkResult.candidate_metrics.warmup_runs_completed} run(s) · Cache:{' '}
                    {benchmarkResult.candidate_metrics.cache_state} · Buffer Hits (med):{' '}
                    {benchmarkResult.candidate_metrics.shared_hit_blocks_median} · Disk Reads (med):{' '}
                    {benchmarkResult.candidate_metrics.shared_read_blocks_median}
                  </div>
                </>
              ) : activePlanComp.actual_execution_comparison.is_measured_latency ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                  <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                    <div className="muted" style={{ fontSize: '0.74rem' }}>Baseline Execution Time</div>
                    <div style={{ fontSize: '1.05rem', fontWeight: 700 }}>
                      {activePlanComp.actual_execution_comparison.baseline_execution_time_ms?.toFixed(2)} ms
                    </div>
                  </div>
                  <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                    <div className="muted" style={{ fontSize: '0.74rem' }}>Candidate Execution Time</div>
                    <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#34d399' }}>
                      {activePlanComp.actual_execution_comparison.candidate_execution_time_ms?.toFixed(2)} ms
                    </div>
                  </div>
                  <div style={{ padding: 8, background: 'rgba(15, 23, 42, 0.5)', borderRadius: 6 }}>
                    <div className="muted" style={{ fontSize: '0.74rem' }}>Observed Speedup</div>
                    <div style={{ fontSize: '1.05rem', fontWeight: 700 }}>
                      {activePlanComp.actual_execution_comparison.measured_speedup_pct?.toFixed(2)}%
                    </div>
                  </div>
                </div>
              ) : (
                <div
                  data-testid="unmeasured-latency-notice"
                  style={{
                    padding: 12,
                    background: 'rgba(15, 23, 42, 0.55)',
                    borderRadius: 6,
                    fontSize: '0.83rem',
                    color: '#cbd5e1',
                  }}
                >
                  <strong>No Measured Execution Time Available:</strong> Current comparison is based on{' '}
                  <code>EXPLAIN</code> planner cost estimates only. Click{' '}
                  <strong>Run Safe Sandbox Benchmark</strong> to measure real wall-clock median (p50) and p95 latency in milliseconds.
                </div>
              )}
            </div>
          </div>

          {/* Side-by-Side Execution Plan Tree Viewer */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
              gap: 16,
              marginBottom: 16,
            }}
          >
            <div className="card" data-testid="baseline-plan-tree-card">
              <h3 style={{ marginTop: 0, fontSize: '0.96rem' }}>
                Baseline Plan Tree ({activePlanComp.baseline_plan.node_count} node(s))
              </h3>
              <ReadablePlanTree tree={activePlanComp.baseline_plan} variant="baseline" />
            </div>

            <div className="card" data-testid="candidate-plan-tree-card">
              <h3 style={{ marginTop: 0, fontSize: '0.96rem' }}>
                Candidate Plan Tree ({activePlanComp.candidate_plan.node_count} node(s))
              </h3>
              <ReadablePlanTree tree={activePlanComp.candidate_plan} variant="candidate" />
            </div>
          </div>

          {/* Top Cost & Time Contributors */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
              gap: 16,
              marginBottom: 16,
            }}
          >
            <div className="card" data-testid="cost-contributors-card">
              <h3 style={{ marginTop: 0, fontSize: '0.95rem' }}>
                Top Planner Cost Contributors ({activePlanComp.cost_contributors.unit})
              </h3>
              <div style={{ display: 'grid', gap: 8 }}>
                {activePlanComp.cost_contributors.baseline.map((c) => (
                  <div
                    key={`base-cost-${c.node_id}`}
                    style={{
                      padding: '6px 10px',
                      background: 'rgba(15, 23, 42, 0.5)',
                      borderRadius: 6,
                      fontSize: '0.8rem',
                    }}
                  >
                    <strong>Baseline #{c.rank}:</strong> {c.explanation}
                  </div>
                ))}
                {activePlanComp.cost_contributors.candidate.map((c) => (
                  <div
                    key={`cand-cost-${c.node_id}`}
                    style={{
                      padding: '6px 10px',
                      background: 'rgba(14, 116, 144, 0.15)',
                      borderRadius: 6,
                      fontSize: '0.8rem',
                    }}
                  >
                    <strong>Candidate #{c.rank}:</strong> {c.explanation}
                  </div>
                ))}
              </div>
            </div>

            <div className="card" data-testid="node-diff-breakdown-card">
              <h3 style={{ marginTop: 0, fontSize: '0.95rem' }}>
                Node-by-Node Plan Diff ({activePlanComp.node_diffs.length} aligned step(s))
              </h3>
              <div style={{ display: 'grid', gap: 8 }}>
                {activePlanComp.node_diffs.map((diff) => (
                  <div
                    key={diff.diff_id}
                    data-testid={`plan-node-diff-${diff.change_type}`}
                    style={{
                      padding: '8px 10px',
                      background: 'rgba(15, 23, 42, 0.55)',
                      borderRadius: 6,
                      borderLeft:
                        diff.severity === 'improvement'
                          ? '3px solid #22c55e'
                          : diff.severity === 'regression'
                            ? '3px solid #ef4444'
                            : '3px solid #64748b',
                      fontSize: '0.8rem',
                    }}
                  >
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
                      <span
                        style={{
                          fontSize: '0.68rem',
                          fontWeight: 700,
                          padding: '1px 6px',
                          borderRadius: 4,
                          textTransform: 'uppercase',
                          background: 'rgba(148, 163, 184, 0.2)',
                        }}
                      >
                        {diff.change_type.replace(/_/g, ' ')}
                      </span>
                      {diff.badges.map((b, i) => (
                        <span
                          key={i}
                          style={{
                            fontSize: '0.68rem',
                            fontWeight: 600,
                            padding: '1px 6px',
                            borderRadius: 4,
                            background: 'rgba(56, 189, 248, 0.16)',
                            color: '#7dd3fc',
                          }}
                        >
                          {b}
                        </span>
                      ))}
                    </div>
                    <div>{diff.explanation}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function ReadablePlanTree({ tree, variant }: { tree: ParsedPlanTree; variant: 'baseline' | 'candidate' }) {
  if (!tree.has_plan || tree.nodes.length === 0) {
    return <p className="muted">No execution plan nodes available.</p>
  }

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {tree.nodes.map((node: DetailedPlanNode) => (
        <div
          key={`${variant}-${node.node_id}`}
          style={{
            marginLeft: `${Math.min(node.depth, 6) * 16}px`,
            padding: '8px 10px',
            borderRadius: 6,
            background: 'rgba(15, 23, 42, 0.6)',
            border:
              node.cost_share_pct >= 40
                ? '1px solid rgba(245, 158, 11, 0.45)'
                : '1px solid rgba(148, 163, 184, 0.18)',
            fontSize: '0.8rem',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
            <div>
              <strong>{node.node_type}</strong>
              {node.relation_name && (
                <span style={{ marginLeft: 6, color: '#38bdf8', fontFamily: 'monospace' }}>
                  on {node.relation_name}
                </span>
              )}
              {node.index_name && (
                <span style={{ marginLeft: 6, color: '#4ade80', fontFamily: 'monospace' }}>
                  [{node.index_name}]
                </span>
              )}
            </div>
            <span style={{ fontSize: '0.72rem', color: '#fbbf24', fontWeight: 600 }}>
              Self Cost: {node.exclusive_cost.toFixed(2)} units ({node.cost_share_pct.toFixed(1)}%)
            </span>
          </div>

          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 4, color: '#cbd5e1', fontSize: '0.76rem' }}>
            <span>Total Cost: {node.total_cost.toFixed(2)} units</span>
            <span>Est. Rows: {node.plan_rows.toLocaleString()}</span>
            {node.actual_rows != null && <span>Actual Rows: {node.actual_rows.toLocaleString()}</span>}
            {node.inclusive_actual_time_ms != null && (
              <span style={{ color: '#34d399' }}>
                Actual Time: {node.inclusive_actual_time_ms.toFixed(2)} ms (self: {node.exclusive_actual_time_ms?.toFixed(2)} ms)
              </span>
            )}
            {(node.shared_hit_blocks > 0 || node.shared_read_blocks > 0) && (
              <span>
                Buffers: hit={node.shared_hit_blocks} read={node.shared_read_blocks}
              </span>
            )}
          </div>

          {(node.index_condition || node.filter_condition || node.join_condition) && (
            <div style={{ marginTop: 4, fontSize: '0.73rem', color: '#94a3b8', fontFamily: 'monospace' }}>
              {node.index_condition && <div>Index Cond: {node.index_condition}</div>}
              {node.filter_condition && <div>Filter: {node.filter_condition}</div>}
              {node.join_condition && <div>Join Cond: {node.join_condition}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function scrubPreview(sql: string): string {
  return sql.replace(/'([^']|'')*'/g, '<STR>').replace(/\b\d+(?:\.\d+)?\b/g, '<NUM>')
}
