import React from 'react'
import type { ProvenanceBadgeLabel, ProvenanceState, WorkloadSummary } from '../lib/api'

export function resolveBadgeLabel(
  badge?: ProvenanceBadgeLabel | string | null,
  state?: ProvenanceState | string | null,
  isSynthetic?: boolean,
): ProvenanceBadgeLabel {
  if (isSynthetic || badge === 'DEMO' || state === 'SYNTHETIC_DEMO') return 'DEMO'
  if (badge === 'LIVE' || state === 'LIVE_TELEMETRY') return 'LIVE'
  if (badge === 'HISTORICAL' || state === 'HISTORICAL_OBSERVATION') return 'HISTORICAL'
  if (badge === 'ESTIMATED' || state === 'HYPOTHETICAL_PLAN_ESTIMATE') return 'ESTIMATED'
  if (badge === 'SIMULATED' || state === 'SANDBOX_BENCHMARK') return 'SIMULATED'
  if (badge === 'VERIFIED' || state === 'VERIFIED_POST_CHANGE') return 'VERIFIED'
  return 'HISTORICAL'
}

export function formatCollectionTimestamp(capturedAt?: string | null): string {
  if (!capturedAt) {
    return 'Timestamp unavailable (not current)'
  }
  const parsed = new Date(capturedAt)
  if (Number.isNaN(parsed.getTime())) {
    return 'Timestamp unavailable (not current)'
  }
  return parsed.toLocaleString()
}

const BADGE_STYLES: Record<
  ProvenanceBadgeLabel,
  { bg: string; border: string; color: string; description: string }
> = {
  LIVE: {
    bg: 'rgba(16, 185, 129, 0.16)',
    border: '#10b981',
    color: '#34d399',
    description: 'Live PostgreSQL telemetry collected directly from pg_stat_statements.',
  },
  DEMO: {
    bg: 'rgba(245, 158, 11, 0.18)',
    border: '#f59e0b',
    color: '#fbbf24',
    description: 'Synthetic demo data generated for evaluation; not live database traffic.',
  },
  HISTORICAL: {
    bg: 'rgba(148, 163, 184, 0.16)',
    border: '#64748b',
    color: '#cbd5e1',
    description: 'Historical stored observation; not a current live telemetry capture.',
  },
  ESTIMATED: {
    bg: 'rgba(168, 85, 247, 0.18)',
    border: '#a855f7',
    color: '#d8b4fe',
    description: 'Hypothetical execution-plan cost estimate (EXPLAIN / HypoPG); not a measured runtime benchmark.',
  },
  SIMULATED: {
    bg: 'rgba(56, 189, 248, 0.18)',
    border: '#0284c7',
    color: '#38bdf8',
    description: 'Measured execution timing from an isolated sandbox benchmark; not applied to production.',
  },
  VERIFIED: {
    bg: 'rgba(5, 150, 105, 0.22)',
    border: '#059669',
    color: '#6ee7b7',
    description: 'Verified post-change production observation.',
  },
}

export interface ProvenanceBadgeProps {
  badge?: ProvenanceBadgeLabel | string | null
  state?: ProvenanceState | string | null
  isSynthetic?: boolean
  prefix?: string
  style?: React.CSSProperties
}

export function ProvenanceBadge({
  badge,
  state,
  isSynthetic,
  prefix,
  style,
}: ProvenanceBadgeProps) {
  const label = resolveBadgeLabel(badge, state, isSynthetic)
  const theme = BADGE_STYLES[label]

  return (
    <span
      data-testid={`provenance-badge-${label.toLowerCase()}`}
      className="badge"
      title={theme.description}
      style={{
        background: theme.bg,
        border: `1px solid ${theme.border}`,
        color: theme.color,
        fontWeight: 700,
        fontSize: '11px',
        padding: '3px 8px',
        borderRadius: '999px',
        letterSpacing: '0.03em',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        ...style,
      }}
    >
      {prefix ? `${prefix}: ${label}` : label}
    </span>
  )
}

export interface TelemetryTransparencyBannerProps {
  summary: WorkloadSummary | null
}

export function TelemetryTransparencyBanner({ summary }: TelemetryTransparencyBannerProps) {
  if (!summary) return null

  const badgeLabel = resolveBadgeLabel(
    summary.provenance_badge,
    summary.provenance_state,
    summary.is_synthetic || summary.demo_mode_active,
  )
  const isDemo = Boolean(summary.demo_mode_active || summary.is_synthetic || badgeLabel === 'DEMO')
  const isStale = Boolean(!isDemo && (summary.is_stale || summary.staleness_warning))
  const hasError = Boolean(summary.collection_error || summary.collection_status === 'error')
  const formattedTime = formatCollectionTimestamp(summary.captured_at)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px' }}>
      {/* Primary Data Provenance Metadata Strip */}
      <div
        data-testid="telemetry-provenance-strip"
        className="card"
        style={{
          padding: '10px 16px',
          background: '#0b1120',
          border: '1px solid #1e293b',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          fontSize: '12px',
          color: '#cbd5e1',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', fontSize: '11px' }}>
            Data Source Provenance:
          </span>
          <ProvenanceBadge
            badge={summary.provenance_badge}
            state={summary.provenance_state}
            isSynthetic={isDemo}
          />
          {summary.source_identifier && (
            <span style={{ fontFamily: 'monospace', color: '#94a3b8', fontSize: '11px' }}>
              Source: <strong>{summary.source_identifier}</strong>
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap', color: '#94a3b8' }}>
          <span>
            Last Collection:{' '}
            <strong data-testid="telemetry-captured-at" style={{ color: summary.captured_at ? '#f8fafc' : '#fbbf24' }}>
              {formattedTime}
            </strong>
          </span>
          <span>
            Status:{' '}
            <strong style={{ color: hasError ? '#f87171' : '#34d399', textTransform: 'uppercase' }}>
              {summary.collection_status || 'unknown'}
            </strong>
          </span>
        </div>
      </div>

      {/* Explicit Demo Mode Banner */}
      {isDemo && (
        <div
          data-testid="demo-provenance-banner"
          className="card"
          style={{
            borderLeft: '4px solid #f59e0b',
            background: 'rgba(245, 158, 11, 0.1)',
            color: '#fde68a',
            padding: '12px 16px',
            fontSize: '13px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <ProvenanceBadge badge="DEMO" />
            <strong>Synthetic Demo Workload Active</strong>
          </div>
          <div>
            The displayed metrics, query statistics, recommendations, and simulations are generated synthetic samples (
            <code>SYNTHETIC_DEMO</code>). They do not represent live production observations. Click{' '}
            <strong>Capture Snapshot</strong> to ingest live <code>pg_stat_statements</code> telemetry.
          </div>
        </div>
      )}

      {/* Telemetry Staleness Warning Banner */}
      {isStale && (
        <div
          data-testid="staleness-warning-banner"
          className="card"
          style={{
            borderLeft: '4px solid #94a3b8',
            background: 'rgba(148, 163, 184, 0.1)',
            color: '#e2e8f0',
            padding: '12px 16px',
            fontSize: '13px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <ProvenanceBadge badge="HISTORICAL" />
            <strong>Stale or Historical Telemetry Warning</strong>
          </div>
          <div>
            {summary.staleness_warning ||
              'Stored telemetry exceeds the freshness threshold or is missing a collection timestamp. Displaying as a historical observation rather than live telemetry.'}
          </div>
        </div>
      )}

      {/* Collection Error Banner */}
      {hasError && summary.collection_error && (
        <div
          data-testid="collection-error-banner"
          className="card"
          style={{
            borderLeft: '4px solid #ef4444',
            background: 'rgba(239, 68, 68, 0.1)',
            color: '#fca5a5',
            padding: '12px 16px',
            fontSize: '13px',
          }}
        >
          <strong>Telemetry Collection Error:</strong> {summary.collection_error}
        </div>
      )}
    </div>
  )
}

export interface EstimateVsMeasuredNoticeProps {
  isMeasured?: boolean
  isSynthetic?: boolean
  isVerifiedSpeedup?: boolean
  explanation?: string | null
  simulationMethod?: string | null
  modelVersion?: string | null
}

export function EstimateVsMeasuredNotice({
  isMeasured,
  isSynthetic,
  isVerifiedSpeedup,
  explanation,
  simulationMethod,
  modelVersion,
}: EstimateVsMeasuredNoticeProps) {
  const badge: ProvenanceBadgeLabel = isSynthetic
    ? 'DEMO'
    : isVerifiedSpeedup
    ? 'VERIFIED'
    : isMeasured
    ? 'SIMULATED'
    : 'ESTIMATED'

  const defaultText = isSynthetic
    ? 'Synthetic demo estimate generated for evaluation; not a measured benchmark or verified production speedup.'
    : isVerifiedSpeedup
    ? 'Verified post-change production observation.'
    : isMeasured
    ? 'Measured execution timing from an isolated sandbox benchmark; not yet verified in production.'
    : 'Estimated from PostgreSQL planner cost model (EXPLAIN / HypoPG). This is a hypothetical plan estimate, NOT a measured runtime benchmark or verified production speedup.'

  return (
    <div
      data-testid="estimate-vs-measured-notice"
      style={{
        background: isMeasured && !isSynthetic ? 'rgba(56, 189, 248, 0.08)' : 'rgba(168, 85, 247, 0.08)',
        border: `1px solid ${isMeasured && !isSynthetic ? 'rgba(56, 189, 248, 0.3)' : 'rgba(168, 85, 247, 0.3)'}`,
        borderRadius: '6px',
        padding: '8px 12px',
        marginTop: '8px',
        fontSize: '12px',
        color: '#e2e8f0',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '8px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1 }}>
        <ProvenanceBadge badge={badge} />
        <span>{explanation || defaultText}</span>
      </div>
      {(simulationMethod || modelVersion) && (
        <span style={{ fontSize: '11px', color: '#94a3b8', fontFamily: 'monospace' }}>
          {simulationMethod ? `method=${simulationMethod}` : ''}
          {simulationMethod && modelVersion ? ' • ' : ''}
          {modelVersion ? `model=${modelVersion}` : ''}
        </span>
      )}
    </div>
  )
}
