import { ArrowLeft, ArrowRight, ClipboardList, SearchX } from 'lucide-react'
import type { UseQueryResult } from '@tanstack/react-query'
import { useMemo, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { usePageTitle } from '@/shared/lib/page-title'
import { paths } from '@/shared/config/paths'
import { isApiError, useAllows, useRunOrders, useShows, type Order } from '@/shared/api'
import { DASH, useFormat } from '@/shared/lib/format'
import { ArchiveWarmUp } from '@/shared/ui/archive-warm-up'
import { StockLink } from '@/shared/ui/stock-name'
import { Badge } from '@/shared/ui/badge'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { OrdersTable } from '@/shared/ui/orders-table'
import { Panel } from '@/shared/ui/panel'
import { PageSkeleton, Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { useRun, useRunFollow, useRunSignals, type Run, type Signal } from './api'
import { FollowPanel } from './FollowPanel'
import { ManualBuy } from './ManualBuy'
import { followMarks, type FollowMark } from './model'
import { RunStateBadge } from './RunStateBadge'

interface RunDetailPageProps {
  runId: string
  renderWatch?: (code: string, label: string) => ReactNode
  /** A rule's name in the reader's language; the report's name stays the key. */
  ruleName: (name: string) => string
}

export function RunDetailPage(props: RunDetailPageProps) {
  const { t } = useTranslation('runs')
  return (
    <RequireSignIn layout="page" reason={t('detailSignIn')}>
      <RunDetail {...props} />
    </RequireSignIn>
  )
}

function RunDetail({ runId, renderWatch, ruleName }: RunDetailPageProps) {
  const { t } = useTranslation('runs')
  const run = useRun(runId)
  const ended = run.data !== undefined && run.data.state !== 'running'
  const signals = useRunSignals(runId, ended)
  const orders = useRunOrders(runId, ended)
  /** Only a finished analysis records decisions it never ordered, which a user may follow into the mock account. */
  const followable = useShows('mock_account') && run.data?.state === 'finished' && run.data.summary?.workflow === 'full_cycle'
  const follow = useRunFollow(runId, followable)
  const quoted = useAllows('realtime_quotes')
  /** A finished specific-stock analysis offers a BUY of each stock it reported, priced on a realtime quote. */
  const buyable = quoted && run.data?.state === 'finished' && run.data.summary?.workflow === 'specific_stocks'
  const marks = useMemo(() => follow.data && followMarks(follow.data), [follow.data])
  const reports = run.data?.reports
  const names = useMemo(() => new Map((reports ?? []).flatMap((report) => (report.name ? [[report.stock_id, report.name] as const] : []))), [reports])

  const back = (
    <Link to={paths.runs} className="-ml-1 inline-flex min-h-11 items-center gap-1.5 rounded-md px-1 text-sm text-muted-foreground hover:text-foreground md:min-h-8">
      <ArrowLeft aria-hidden className="size-4" />
      {t('back')}
    </Link>
  )
  if (run.isPending) return <PageSkeleton />
  if (isApiError(run.error, 'notFound')) {
    return (
      <div className="space-y-3">
        {back}
        <StateBlock icon={SearchX} title={t('notFound')} framed />
      </div>
    )
  }
  // A poll that fails once keeps the run on screen; the next poll asks again.
  if (run.data === undefined) return <ErrorState error={run.error} title={t('loadFailed')} onRetry={() => void run.refetch()} framed />

  return (
    <div className="page-stack">
      <div className="space-y-3">
        {back}
        <Header run={run.data} />
        <NotAdviceNote />
      </div>
      <ArchiveWarmUp />
      {run.data.state === 'running' && <p className="rounded-xl border border-brand/30 bg-brand-soft px-4 py-2.5 text-sm">{t('runningNote')}</p>}
      {run.data.state === 'unfinished' && <p className="rounded-xl border border-gold/35 bg-gold-soft px-4 py-2.5 text-sm">{t('unfinishedNote')}</p>}
      {run.data.error && (
        <p className="rounded-xl border border-destructive/30 bg-danger-soft px-4 py-2.5 text-sm" role="alert">
          {run.data.error}
        </p>
      )}
      {run.data.summary && <Summary summary={run.data.summary} />}
      {followable && <FollowPanel runId={runId} follow={follow} decisions={signals.data} names={names} />}
      {(run.data.reports ?? []).length > 0 && <Reports reports={run.data.reports ?? []} buyFrom={buyable ? runId : null} renderWatch={renderWatch} ruleName={ruleName} />}
      {ended && (
        <div className="card-grid xl:grid-cols-2">
          <Signals query={signals} marks={marks} />
          <Orders query={orders} />
        </div>
      )}
      {run.data.summary && run.data.summary.execution_log.length > 0 && <Log lines={run.data.summary.execution_log} title={t('logTitle')} />}
    </div>
  )
}

function Header({ run }: { run: Run }) {
  const { t } = useTranslation('runs')
  const format = useFormat()
  const summary = run.summary
  const title = summary ? t(`workflow.${summary.workflow}`) : t('unrecorded')
  usePageTitle(title)
  return (
    <header className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2.5">
        <h1 className="display">{title}</h1>
        <RunStateBadge state={run.state} />
        {summary && (
          <Badge variant="outline" className="font-normal">
            {t(`common:broker.name.${summary.execution_provider}`)}
          </Badge>
        )}
      </div>
      <p className="tabular flex flex-wrap gap-x-3 text-xs text-muted-foreground">
        {summary && <span>{t('timing', { start: format.dateTime(summary.start_time), end: summary.end_time ? format.dateTime(summary.end_time) : DASH })}</span>}
        <span className="font-mono">{run.run_id}</span>
      </p>
      {summary?.followed_run_id && (
        <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
          {t('followOf')}
          <Link to={paths.run(summary.followed_run_id)} className="inline-flex min-h-11 items-center gap-1 font-medium text-brand hover:underline md:min-h-0">
            {t('followOfLink')}
            <ArrowRight aria-hidden className="size-3.5" />
          </Link>
        </p>
      )}
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

interface ReportsProps extends Pick<RunDetailPageProps, 'renderWatch' | 'ruleName'> {
  reports: NonNullable<Run['reports']>
  /** The run whose reported stocks each offer a BUY; null where the run offers none. */
  buyFrom: string | null
}

/** One card per stock: its scores, the price the run read, the rules that excluded it and the AI's summary. */
function Reports({ reports, buyFrom, renderWatch, ruleName }: ReportsProps) {
  const { t } = useTranslation('runs')
  const format = useFormat()
  return (
    <Panel title={t('reportsTitle')}>
      <ul className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))] gap-3">
        {reports.map((report) => (
          <li key={report.stock_id} className="flex flex-col gap-3 rounded-xl border bg-background/60 p-4">
            <div className="flex items-start justify-between gap-3">
              <StockLink stockId={report.stock_id} name={report.name} stretched={false} />
              <div className="flex shrink-0 items-center gap-1">
                {buyFrom && <ManualBuy runId={buyFrom} stockId={report.stock_id} name={report.name} />}
                {renderWatch?.(report.stock_id, report.name ?? report.stock_id)}
              </div>
            </div>
            <dl className="grid grid-cols-3 gap-3 rounded-lg bg-muted/60 px-3 py-2.5">
              <Stat label={t('score.technical')}>{report.technical_report?.score ?? DASH}</Stat>
              <Stat label={t('score.ai')}>{report.ai_report?.score ?? DASH}</Stat>
              <Stat label={t('score.composite')}>{report.composite_score ?? DASH}</Stat>
            </dl>
            <p className="tabular text-xs text-muted-foreground">
              {report.current_price !== null ? format.price(report.current_price) : DASH}
              {report.latest_market_data_at && ` · ${format.dateTime(report.latest_market_data_at)}`}
            </p>
            {report.technical_report && report.technical_report.hard_failures.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-destructive">{t('hardFailuresTitle', { count: report.technical_report.hard_failures.length })}</p>
                <ul className="flex flex-wrap gap-1.5">
                  {report.technical_report.hard_failures.map((rule) => (
                    <li key={rule} className="rounded-md border border-destructive/25 bg-danger-soft px-2 py-0.5 text-xs">
                      {ruleName(rule)}
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

function Signals({ query, marks }: { query: UseQueryResult<Signal[]>; marks: ReadonlyMap<string, FollowMark> | undefined }) {
  const { t } = useTranslation('runs')
  const format = useFormat()
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
    ...(marks ? [{ key: 'follow', header: t('column.follow'), cell: (signal: Signal) => <FollowBadge mark={marks.get(signal.decision_id)} /> }] : []),
    { key: 'score', header: t('column.score'), numeric: true, cell: (signal) => signal.score },
    { key: 'quantity', header: t('column.quantity'), numeric: true, from: 'sm', cell: (signal) => format.number(signal.quantity) },
    { key: 'price', header: t('column.price'), numeric: true, from: 'sm', cell: (signal) => format.price(signal.price_at_signal) },
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

function FollowBadge({ mark }: { mark: FollowMark | undefined }) {
  const { t } = useTranslation('runs')
  if (!mark) return null
  return (
    <Badge variant={mark === 'followed' ? 'secondary' : 'outline'} className="font-normal">
      {t(`followMark.${mark}`)}
    </Badge>
  )
}

function Orders({ query }: { query: UseQueryResult<Order[]> }) {
  const { t } = useTranslation('runs')
  if (query.isPending) return <Skeleton className="h-24 rounded-2xl" />
  if (query.isError) return <ErrorState error={query.error} title={t('ordersFailed')} onRetry={() => void query.refetch()} className="rounded-2xl border bg-card" />
  const orders = query.data
  return (
    <Panel title={t('ordersTitle', { count: orders.length })} flush={orders.length > 0}>
      <OrdersTable orders={orders} label={t('ordersTitle', { count: orders.length })} />
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
