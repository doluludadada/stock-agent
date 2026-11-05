import { ArrowLeft, ClipboardList, ReceiptText, SearchX } from 'lucide-react'
import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { isApiError } from '@/shared/api'
import { formatDateTime, formatNumber, formatPrice } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { useRun, useRunOrders, useRunSignals, type Order, type Run, type Signal } from './api'
import { RunStateBadge } from './RunStateBadge'

interface RunDetailPageProps {
  runId: string
  renderWatch?: (code: string, label: string) => ReactNode
}

export function RunDetailPage(props: RunDetailPageProps) {
  const { t } = useTranslation('runs')
  return (
    <RequireSignIn layout="page" reason={t('detailSignIn')}>
      <RunDetail {...props} />
    </RequireSignIn>
  )
}

function RunDetail({ runId, renderWatch }: RunDetailPageProps) {
  const { t } = useTranslation('runs')
  const run = useRun(runId)
  const ended = run.data !== undefined && run.data.state !== 'running'
  const signals = useRunSignals(runId, ended)
  const orders = useRunOrders(runId, ended)

  const back = (
    <Link to={paths.runs} className="-ml-1 inline-flex min-h-11 items-center gap-1.5 rounded-md px-1 text-sm text-muted-foreground hover:text-foreground md:min-h-8">
      <ArrowLeft aria-hidden className="size-4" />
      {t('back')}
    </Link>
  )
  if (run.isPending) return <Skeleton className="h-96 rounded-2xl" />
  if (isApiError(run.error, 'notFound')) {
    return (
      <div className="space-y-3">
        {back}
        <StateBlock icon={SearchX} title={t('notFound')} className="rounded-2xl border bg-card py-12" />
      </div>
    )
  }
  if (run.isError) return <ErrorState error={run.error} title={t('loadFailed')} onRetry={() => void run.refetch()} className="rounded-2xl border bg-card py-12" />

  return (
    <div className="space-y-5 lg:space-y-6">
      <div className="space-y-3">
        {back}
        <Header run={run.data} />
      </div>
      {run.data.state === 'running' && <p className="rounded-xl border border-brand/30 bg-brand-soft px-4 py-2.5 text-sm">{t('runningNote')}</p>}
      {run.data.state === 'unfinished' && <p className="rounded-xl border border-gold/35 bg-gold-soft px-4 py-2.5 text-sm">{t('unfinishedNote')}</p>}
      {run.data.error && (
        <p className="rounded-xl border border-destructive/30 bg-danger-soft px-4 py-2.5 text-sm" role="alert">
          {run.data.error}
        </p>
      )}
      {run.data.summary && <Summary summary={run.data.summary} />}
      {(run.data.reports ?? []).length > 0 && <Reports reports={run.data.reports ?? []} renderWatch={renderWatch} />}
      {ended && (
        <div className="grid items-start gap-4 lg:gap-5 xl:grid-cols-2">
          <Signals query={signals} />
          <Orders query={orders} />
        </div>
      )}
      {run.data.summary && run.data.summary.execution_log.length > 0 && <Log lines={run.data.summary.execution_log} title={t('logTitle')} />}
    </div>
  )
}

function Header({ run }: { run: Run }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  const summary = run.summary
  return (
    <header className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2.5">
        <h1 className="display">{summary ? t(`workflow.${summary.workflow}`) : t('unrecorded')}</h1>
        <RunStateBadge state={run.state} />
        {summary && (
          <Badge variant="outline" className="font-normal">
            {t('broker', { provider: t(`provider.${summary.execution_provider}`), mode: t(`orderMode.${summary.order_mode}`) })}
          </Badge>
        )}
      </div>
      <p className="tabular flex flex-wrap gap-x-3 text-xs text-muted-foreground">
        {summary && <span>{t('timing', { start: formatDateTime(locale, summary.start_time), end: summary.end_time ? formatDateTime(locale, summary.end_time) : '—' })}</span>}
        <span className="font-mono">{run.run_id}</span>
      </p>
    </header>
  )
}

function Summary({ summary }: { summary: NonNullable<Run['summary']> }) {
  const { t } = useTranslation('runs')
  const counters = [
    ['scanned', summary.total_scanned],
    ['passedTechnical', summary.passed_technical],
    ['aiAnalysed', summary.ai_analysed],
    ['signals', summary.signals_generated],
    ['ordersSubmitted', summary.orders_submitted],
    ['ordersRefused', summary.orders_refused],
    ['stale', summary.stale_market_data_count],
  ] as const
  return (
    <Panel title={t('summaryTitle')} description={t('summaryQuestion')}>
      <dl className="grid grid-cols-3 gap-x-6 gap-y-4 @xl:grid-cols-4 @4xl:grid-cols-7">
        {counters.map(([key, value]) => (
          <Stat key={key} label={t(`counter.${key}`)} size="lg">
            {value}
          </Stat>
        ))}
      </dl>
      {summary.errors.length > 0 && <Log lines={summary.errors} title={t('errorsTitle', { count: summary.errors.length })} tone="danger" />}
    </Panel>
  )
}

/** One card per stock: its scores, the price the run read, the rules that excluded it and the AI's summary. */
function Reports({ reports, renderWatch }: { reports: NonNullable<Run['reports']>; renderWatch?: RunDetailPageProps['renderWatch'] }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  return (
    <Panel title={t('reportsTitle')} description={t('reportsQuestion', { count: reports.length })}>
      <ul className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))] gap-3">
        {reports.map((report) => (
          <li key={report.stock_id} className="flex flex-col gap-3 rounded-xl border bg-background/60 p-4">
            <div className="flex items-start justify-between gap-3">
              <Link to={paths.stock(report.stock_id)} className="flex min-h-11 min-w-0 flex-col justify-center hover:text-brand md:min-h-0">
                <span className="truncate font-semibold">{report.name ?? report.stock_id}</span>
                <span className="font-mono text-xs text-muted-foreground">{report.stock_id}</span>
              </Link>
              {renderWatch?.(report.stock_id, report.name ?? report.stock_id)}
            </div>
            <dl className="grid grid-cols-3 gap-3 rounded-lg bg-muted/60 px-3 py-2.5">
              <Stat label={t('score.technical')}>{report.technical_report?.score ?? '—'}</Stat>
              <Stat label={t('score.ai')}>{report.ai_report?.score ?? '—'}</Stat>
              <Stat label={t('score.composite')}>{report.composite_score ?? '—'}</Stat>
            </dl>
            <p className="tabular text-xs text-muted-foreground">
              {report.current_price !== null ? formatPrice(locale, report.current_price) : '—'}
              {report.latest_market_data_at && ` · ${formatDateTime(locale, report.latest_market_data_at)}`}
            </p>
            {report.technical_report && report.technical_report.hard_failures.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-destructive">{t('hardFailuresTitle', { count: report.technical_report.hard_failures.length })}</p>
                <ul className="flex flex-wrap gap-1.5">
                  {report.technical_report.hard_failures.map((rule) => (
                    <li key={rule} className="rounded-md border border-destructive/25 bg-danger-soft px-2 py-0.5 text-xs">
                      {rule}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {report.ai_report && <p className="text-sm text-pretty text-muted-foreground">{report.ai_report.summary}</p>}
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function Signals({ query }: { query: UseQueryResult<Signal[]> }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  if (query.isPending) return <Skeleton className="h-32 rounded-2xl" />
  if (query.isError) return <ErrorState error={query.error} title={t('signalsFailed')} onRetry={() => void query.refetch()} className="rounded-2xl border bg-card" />
  const signals = query.data
  const columns: Column<Signal>[] = [
    {
      key: 'stock',
      header: t('column.stock'),
      cell: (signal) => (
        <Link to={paths.stock(signal.stock_id)} className="stretched-link font-mono hover:text-brand focus-visible:text-brand">
          {signal.stock_id}
        </Link>
      ),
    },
    { key: 'action', header: t('column.action'), cell: (signal) => t(`action.${signal.action}`) },
    { key: 'score', header: t('column.score'), numeric: true, cell: (signal) => signal.score },
    { key: 'quantity', header: t('column.quantity'), numeric: true, from: 'sm', cell: (signal) => formatNumber(locale, signal.quantity) },
    { key: 'price', header: t('column.price'), numeric: true, from: 'sm', cell: (signal) => formatPrice(locale, signal.price_at_signal) },
    { key: 'reason', header: t('column.reason'), from: 'lg', className: 'w-full min-w-48 whitespace-normal text-xs text-muted-foreground', cell: (signal) => signal.reason },
  ]
  return (
    <Panel title={t('signalsTitle', { count: signals.length })} flush={signals.length > 0}>
      {signals.length > 0 ? (
        <DataTable rows={signals} columns={columns} rowKey={(signal) => signal.decision_id} label={t('signalsTitle', { count: signals.length })} />
      ) : (
        <StateBlock icon={ClipboardList} title={t('noSignals')} className="py-4" />
      )}
    </Panel>
  )
}

function Orders({ query }: { query: UseQueryResult<Order[]> }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  if (query.isPending) return <Skeleton className="h-24 rounded-2xl" />
  if (query.isError) return <ErrorState error={query.error} title={t('ordersFailed')} onRetry={() => void query.refetch()} className="rounded-2xl border bg-card" />
  const orders = query.data
  const columns: Column<Order>[] = [
    { key: 'stock', header: t('column.stock'), className: 'font-mono', cell: (order) => order.stock_id },
    { key: 'action', header: t('column.action'), cell: (order) => t(`action.${order.action}`) },
    { key: 'status', header: t('column.status'), cell: (order) => t(`orderStatus.${order.status}`) },
    { key: 'quantity', header: t('column.quantity'), numeric: true, cell: (order) => `${formatNumber(locale, order.filled_quantity)} / ${formatNumber(locale, order.quantity)}` },
    { key: 'price', header: t('column.price'), numeric: true, from: 'sm', cell: (order) => (order.limit_price !== null ? formatPrice(locale, order.limit_price) : '—') },
    { key: 'costs', header: t('column.costs'), numeric: true, from: 'md', cell: (order) => formatNumber(locale, order.fee + order.tax) },
    { key: 'reason', header: t('column.reason'), from: 'lg', className: 'w-full min-w-48 whitespace-normal text-xs text-muted-foreground', cell: (order) => order.reason ?? '' },
  ]
  return (
    <Panel title={t('ordersTitle', { count: orders.length })} flush={orders.length > 0}>
      {orders.length > 0 ? (
        <DataTable rows={orders} columns={columns} rowKey={(order) => order.id} label={t('ordersTitle', { count: orders.length })} />
      ) : (
        <StateBlock icon={ReceiptText} title={t('noOrders')} className="py-4" />
      )}
    </Panel>
  )
}

function Log({ lines, title, tone = 'neutral' }: { lines: string[]; title: string; tone?: 'neutral' | 'danger' }) {
  return (
    <details className={tone === 'danger' ? 'mt-4 rounded-xl border border-destructive/30 bg-danger-soft px-4 py-2.5' : 'rounded-2xl border bg-card px-5 py-3 shadow-card'}>
      <summary className="flex min-h-11 cursor-pointer items-center text-sm font-medium md:min-h-8">{title}</summary>
      <ul className="mt-2 max-h-72 space-y-1 overflow-y-auto font-mono text-xs text-muted-foreground">
        {lines.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ul>
    </details>
  )
}
