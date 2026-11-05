import { ArrowLeft, SearchX } from 'lucide-react'
import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { isApiError } from '@/shared/api'
import { formatDateTime, formatNumber, formatPrice } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { RequireUnlock } from '@/shared/ui/unlock'
import { useRun, useRunOrders, useRunSignals, type Order, type Run, type Signal } from './api'
import { RunStateBadge } from './RunStateBadge'

interface RunDetailPageProps {
  runId: string
  renderWatch?: (code: string, label: string) => ReactNode
}

export function RunDetailPage(props: RunDetailPageProps) {
  return (
    <RequireUnlock scope="owner" className="rounded-xl border">
      <RunDetail {...props} />
    </RequireUnlock>
  )
}

function RunDetail({ runId, renderWatch }: RunDetailPageProps) {
  const { t } = useTranslation('runs')
  const run = useRun(runId)
  const ended = run.data !== undefined && run.data.state !== 'running'
  const signals = useRunSignals(runId, ended)
  const orders = useRunOrders(runId, ended)

  if (run.isPending) return <Skeleton className="h-96 rounded-xl" />
  if (isApiError(run.error, 'notFound')) return <StateBlock icon={SearchX} title={t('notFound')} className="rounded-xl border" />
  if (run.isError) return <ErrorState error={run.error} title={t('loadFailed')} onRetry={() => void run.refetch()} className="rounded-xl border" />

  return (
    <div className="space-y-4">
      <Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground">
        <Link to={paths.runs}>
          <ArrowLeft aria-hidden />
          {t('back')}
        </Link>
      </Button>
      <Header run={run.data} />
      {run.data.state === 'running' && <p className="rounded-lg border border-primary/30 bg-accent px-3 py-2 text-sm">{t('runningNote')}</p>}
      {run.data.state === 'unfinished' && <p className="rounded-lg border border-gold/35 bg-gold-soft px-3 py-2 text-sm">{t('unfinishedNote')}</p>}
      {run.data.error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm" role="alert">
          {run.data.error}
        </p>
      )}
      {run.data.summary && <Summary summary={run.data.summary} />}
      {(run.data.reports ?? []).length > 0 && <Reports reports={run.data.reports ?? []} renderWatch={renderWatch} />}
      {ended && <Signals query={signals} />}
      {ended && <Orders query={orders} />}
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
    <Panel title={t('summaryTitle')}>
      <dl className="grid grid-cols-3 gap-x-6 gap-y-3 sm:grid-cols-4 lg:grid-cols-7">
        {counters.map(([key, value]) => (
          <Stat key={key} label={t(`counter.${key}`)}>
            {value}
          </Stat>
        ))}
      </dl>
      {summary.errors.length > 0 && <Log lines={summary.errors} title={t('errorsTitle', { count: summary.errors.length })} tone="danger" />}
    </Panel>
  )
}

function Reports({ reports, renderWatch }: { reports: NonNullable<Run['reports']>; renderWatch?: RunDetailPageProps['renderWatch'] }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  return (
    <Panel title={t('reportsTitle')} flush>
      <ul className="divide-y">
        {reports.map((report) => (
          <li key={report.stock_id} className="space-y-2 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <Link to={paths.stock(report.stock_id)} className="flex items-baseline gap-2 text-sm font-medium hover:text-primary">
                <span className="font-mono text-xs text-muted-foreground">{report.stock_id}</span>
                {report.name}
              </Link>
              {renderWatch?.(report.stock_id, report.name ?? report.stock_id)}
            </div>
            <dl className="grid max-w-md grid-cols-3 gap-x-6">
              <Stat label={t('score.technical')}>{report.technical_report?.score ?? '—'}</Stat>
              <Stat label={t('score.ai')}>{report.ai_report?.score ?? '—'}</Stat>
              <Stat label={t('score.composite')}>{report.composite_score ?? '—'}</Stat>
            </dl>
            <p className="tabular text-xs text-muted-foreground">
              {report.current_price !== null ? formatPrice(locale, report.current_price) : '—'}
              {report.latest_market_data_at && ` · ${formatDateTime(locale, report.latest_market_data_at)}`}
            </p>
            {report.technical_report && report.technical_report.hard_failures.length > 0 && (
              <p className="text-xs text-destructive">{t('hardFailures', { list: report.technical_report.hard_failures.join(', ') })}</p>
            )}
            {report.ai_report && <p className="text-sm text-muted-foreground">{report.ai_report.summary}</p>}
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function Signals({ query }: { query: UseQueryResult<Signal[]> }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  if (query.isPending) return <Skeleton className="h-32 rounded-xl" />
  if (query.isError) return <ErrorState error={query.error} title={t('signalsFailed')} onRetry={() => void query.refetch()} className="rounded-xl border" />
  const signals = query.data
  return (
    <Panel title={t('signalsTitle', { count: signals.length })} flush>
      {signals.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('column.stock')}</TableHead>
              <TableHead>{t('column.action')}</TableHead>
              <TableHead className="text-right">{t('column.score')}</TableHead>
              <TableHead className="text-right">{t('column.quantity')}</TableHead>
              <TableHead className="text-right">{t('column.price')}</TableHead>
              <TableHead>{t('column.reason')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {signals.map((signal) => (
              <TableRow key={signal.decision_id}>
                <TableCell>
                  <Link to={paths.stock(signal.stock_id)} className="font-mono hover:text-primary">
                    {signal.stock_id}
                  </Link>
                </TableCell>
                <TableCell>{t(`action.${signal.action}`)}</TableCell>
                <TableCell className="tabular text-right">{signal.score}</TableCell>
                <TableCell className="tabular text-right">{formatNumber(locale, signal.quantity)}</TableCell>
                <TableCell className="tabular text-right">{formatPrice(locale, signal.price_at_signal)}</TableCell>
                <TableCell className="max-w-md text-xs text-muted-foreground">{signal.reason}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <p className="px-4 py-3 text-sm text-muted-foreground">{t('noSignals')}</p>
      )}
    </Panel>
  )
}

function Orders({ query }: { query: UseQueryResult<Order[]> }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  if (query.isPending) return <Skeleton className="h-24 rounded-xl" />
  if (query.isError) return <ErrorState error={query.error} title={t('ordersFailed')} onRetry={() => void query.refetch()} className="rounded-xl border" />
  const orders = query.data
  if (orders.length === 0) {
    return (
      <Panel title={t('ordersTitle', { count: 0 })}>
        <p className="text-sm text-muted-foreground">{t('noOrders')}</p>
      </Panel>
    )
  }
  return (
    <Panel title={t('ordersTitle', { count: orders.length })} flush>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('column.stock')}</TableHead>
            <TableHead>{t('column.action')}</TableHead>
            <TableHead>{t('column.status')}</TableHead>
            <TableHead className="text-right">{t('column.quantity')}</TableHead>
            <TableHead className="text-right">{t('column.price')}</TableHead>
            <TableHead className="text-right">{t('column.costs')}</TableHead>
            <TableHead>{t('column.reason')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((order) => (
            <TableRow key={order.id}>
              <TableCell className="font-mono">{order.stock_id}</TableCell>
              <TableCell>{t(`action.${order.action}`)}</TableCell>
              <TableCell>{t(`orderStatus.${order.status}`)}</TableCell>
              <TableCell className="tabular text-right">{formatNumber(locale, order.filled_quantity)} / {formatNumber(locale, order.quantity)}</TableCell>
              <TableCell className="tabular text-right">{order.limit_price !== null ? formatPrice(locale, order.limit_price) : '—'}</TableCell>
              <TableCell className="tabular text-right">{formatNumber(locale, order.fee + order.tax)}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{order.reason ?? ''}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Panel>
  )
}

function Log({ lines, title, tone = 'neutral' }: { lines: string[]; title: string; tone?: 'neutral' | 'danger' }) {
  return (
    <details className={tone === 'danger' ? 'mt-3 rounded-lg border border-destructive/30 px-3 py-2' : 'rounded-xl border bg-card px-4 py-2.5'}>
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <ul className="mt-2 max-h-72 space-y-1 overflow-y-auto font-mono text-xs text-muted-foreground">
        {lines.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ul>
    </details>
  )
}
