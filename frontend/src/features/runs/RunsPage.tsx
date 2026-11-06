import { Activity, ArrowRight, ClipboardList, Megaphone, Play, Radar, ScanSearch, ShieldAlert, UserRound } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { isApiError, useSession } from '@/shared/api'
import { formatDateTime } from '@/shared/lib/format'
import { isAcceptedList, parseStockIds } from '@/shared/lib/stock-ids'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { StockIdsProblem } from '@/shared/ui/stock-ids-problem'
import { SignInActions } from '@/shared/ui/require-sign-in'
import { PAGE_SIZE, useRunSignals, useRunsPage, useStartRun, type Run, type RunKind, type Signal } from './api'
import { RunStateBadge } from './RunStateBadge'

const KINDS: { kind: RunKind; icon: typeof Play; orders: boolean }[] = [
  { kind: 'full-cycle', icon: Radar, orders: false },
  { kind: 'specific-stocks', icon: ScanSearch, orders: false },
  { kind: 'buzz-scan', icon: Megaphone, orders: true },
  { kind: 'intraday', icon: Activity, orders: true },
]

/** The home page: start a run, read the latest result and the history; a visitor reads what the analyses do. */
export function RunsPage() {
  const { t } = useTranslation('runs')
  const current = useSession()
  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader eyebrow={t('common:nav.section.analysis')} title={t('title')} description={t('description')} />
      {current.status === 'checking' && <Skeleton className="h-40 rounded-2xl" />}
      {current.status === 'signedOut' && <Intro ended={current.ended} />}
      {current.status === 'signedIn' && (
        <div className="space-y-4 lg:space-y-5">
          <StartPanel />
          <LatestResult />
          <History />
        </div>
      )}
    </div>
  )
}

function Intro({ ended }: { ended: boolean }) {
  const { t } = useTranslation('runs')
  return (
    <section className="grid overflow-hidden rounded-2xl border bg-card shadow-card md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <StateBlock
        icon={UserRound}
        title={ended ? t('common:auth.ended.title') : t('signIn')}
        description={ended ? t('common:auth.ended.description') : t('common:auth.prompt.description')}
        className="py-10 md:items-start md:px-10 md:text-left [&>div]:md:justify-start"
        action={
          <>
            <SignInActions />
            <Button asChild variant="ghost">
              <Link to={paths.market}>
                {t('common:nav.overview')}
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          </>
        }
      />
      <div className="border-t bg-muted/40 px-6 py-8 md:border-t-0 md:border-l md:px-10">
        <p className="eyebrow mb-4">{t('startQuestion')}</p>
        <ul className="grid gap-4">
          {KINDS.map(({ kind, icon: Icon }) => (
            <li key={kind} className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
                <Icon aria-hidden className="size-4.5" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{t(`kind.${kind}.title`)}</span>
                <span className="block text-xs text-pretty text-muted-foreground">{t(`kind.${kind}.description`)}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function StartPanel() {
  const { t } = useTranslation('runs')
  const navigate = useNavigate()
  const start = useStartRun()
  const [confirming, setConfirming] = useState<RunKind | null>(null)
  const [stockText, setStockText] = useState('')
  const stocks = parseStockIds(stockText)

  const launch = () => {
    if (!confirming) return
    const kind = confirming
    setConfirming(null)
    start.mutate(
      { kind, stockIds: stocks.ids },
      {
        onSuccess: (accepted) => {
          toast.success(t('started', { kind: t(`kind.${kind}.title`) }))
          navigate(paths.run(accepted.run_id))
        },
        onError: (error) => {
          const code = isApiError(error) ? error.code : null
          if (code === 'run_in_progress') toast.error(t('busy'))
          else if (code === 'mock_broker_only') toast.error(t('mockOnly'), { description: error.message })
          else toast.error(t('startFailed', { reason: error.message }))
        },
      },
    )
  }

  const onSpecific = (event: FormEvent) => {
    event.preventDefault()
    if (isAcceptedList(stocks)) setConfirming('specific-stocks')
  }

  return (
    <Panel title={t('startTitle')} description={t('startQuestion')}>
      <ul className="grid gap-3 @2xl:grid-cols-2">
        {KINDS.map(({ kind, icon: Icon, orders }) => (
          <li key={kind} className="flex flex-col gap-3 rounded-xl border bg-background/60 p-4">
            <div className="min-w-0 flex-1 space-y-1">
              <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand">
                  <Icon aria-hidden className="size-4" />
                </span>
                {t(`kind.${kind}.title`)}
                {orders ? (
                  <Badge variant="outline" className="gap-1 border-gold/40 font-normal text-gold">
                    <ShieldAlert aria-hidden className="size-3" />
                    {t('mockOrders')}
                  </Badge>
                ) : (
                  <Badge variant="outline" className="font-normal">
                    {t('neverOrders')}
                  </Badge>
                )}
              </h3>
              <p className="text-sm text-muted-foreground">{t(`kind.${kind}.description`)}</p>
              <p className="text-xs text-muted-foreground">{t(`kind.${kind}.cost`)}</p>
            </div>
            {kind === 'specific-stocks' ? (
              <form onSubmit={onSpecific} className="flex flex-wrap items-start gap-2">
                <Input
                  value={stockText}
                  onChange={(event) => setStockText(event.target.value)}
                  placeholder={t('stocksPlaceholder')}
                  aria-label={t('stocksLabel')}
                  aria-describedby="specific-stocks-problem"
                  className="min-w-0 flex-1 font-mono md:h-8"
                />
                <Button type="submit" size="sm" className="md:h-8" disabled={!isAcceptedList(stocks) || start.isPending}>
                  <Play aria-hidden />
                  {t('start')}
                </Button>
                <StockIdsProblem id="specific-stocks-problem" list={stocks} />
              </form>
            ) : (
              <Button type="button" size="sm" variant="outline" className="self-start" onClick={() => setConfirming(kind)} disabled={start.isPending}>
                <Play aria-hidden />
                {t('start')}
              </Button>
            )}
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={confirming && t('confirm.title', { kind: t(`kind.${confirming}.title`) })}
        description={
          <>
            {confirming && t(`kind.${confirming}.cost`)} {confirming === 'specific-stocks' && t('confirm.stocks', { ids: stocks.ids.join(', ') })}{' '}
            {confirming && KINDS.find((item) => item.kind === confirming)?.orders && t('confirm.mock')}
          </>
        }
        cancel={t('confirm.cancel')}
        confirm={t('confirm.start')}
        onConfirm={launch}
      />
    </Panel>
  )
}

/** The newest run that ended, if any; a running run has no decisions yet. */
function LatestResult() {
  const latest = useRunsPage(0).data?.runs.find((run) => run.state !== 'running')
  return latest ? <LatestRun run={latest} /> : null
}

const LATEST_SHOWN = 5
const buyFirstThenScore = (a: Signal, b: Signal) => Number(b.action === 'buy') - Number(a.action === 'buy') || b.score - a.score

function LatestRun({ run }: { run: Run }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  const signals = useRunSignals(run.run_id, true)
  const summary = run.summary
  const strongest = signals.data ? [...signals.data].sort(buyFirstThenScore).slice(0, LATEST_SHOWN) : []
  const timing = summary && t('timing', { start: formatDateTime(locale, summary.start_time), end: summary.end_time ? formatDateTime(locale, summary.end_time) : '—' })
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
    {
      key: 'action',
      header: t('column.action'),
      cell: (signal) => <Badge variant={signal.action === 'buy' ? 'default' : 'outline'}>{t(`action.${signal.action}`)}</Badge>,
    },
    { key: 'score', header: t('column.score'), numeric: true, cell: (signal) => signal.score },
    { key: 'reason', header: t('column.reason'), from: 'md', className: 'w-full min-w-48 whitespace-normal text-xs text-muted-foreground', cell: (signal) => signal.reason },
  ]
  return (
    <Panel
      title={t('latest.title')}
      description={summary ? `${t(`workflow.${summary.workflow}`)} · ${timing}` : t('unrecorded')}
      aside={
        <>
          <RunStateBadge state={run.state} />
          <Button asChild variant="ghost" size="sm" className="-my-1">
            <Link to={paths.run(run.run_id)}>
              {t('latest.open')}
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        </>
      }
      flush={strongest.length > 0}
    >
      {signals.isPending && <Skeleton className="h-24 rounded-lg" />}
      {signals.isError && <ErrorState error={signals.error} title={t('signalsFailed')} onRetry={() => void signals.refetch()} />}
      {signals.data && strongest.length === 0 && <StateBlock icon={ClipboardList} title={t('noSignals')} className="py-4" />}
      {strongest.length > 0 && <DataTable rows={strongest} columns={columns} rowKey={(signal) => signal.decision_id} label={t('latest.title')} />}
    </Panel>
  )
}

function History() {
  const { t } = useTranslation('runs')
  const [offset, setOffset] = useState(0)
  const page = useRunsPage(offset)
  const shown = page.data?.runs.length ?? 0
  return (
    <Panel
      title={t('historyTitle')}
      aside={
        <>
          <span className="tabular">{shown > 0 && t('pageOf', { from: offset + 1, to: offset + shown })}</span>
          <Button type="button" variant="outline" size="xs" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            {t('previous')}
          </Button>
          <Button type="button" variant="outline" size="xs" disabled={!page.data?.hasNext} onClick={() => setOffset(offset + PAGE_SIZE)}>
            {t('next')}
          </Button>
        </>
      }
      flush
    >
      {page.isPending && <Skeleton className="m-4 h-40 rounded-lg" />}
      {page.isError && <ErrorState error={page.error} title={t('loadFailed')} onRetry={() => void page.refetch()} />}
      {page.data && page.data.runs.length === 0 && <StateBlock icon={Activity} title={t('empty.title')} description={t('empty.description')} />}
      {page.data && page.data.runs.length > 0 && <RunsTable runs={page.data.runs} />}
    </Panel>
  )
}

/** Every run, newest first; a row opens the run. On a phone a row reads as the run and its state. */
function RunsTable({ runs }: { runs: Run[] }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  const started = (run: Run) => (run.summary ? formatDateTime(locale, run.summary.start_time) : '—')
  const columns: Column<Run>[] = [
    {
      key: 'started',
      header: t('column.started'),
      className: 'whitespace-nowrap',
      cell: (run) => (
        <Link to={paths.run(run.run_id)} aria-label={t('openRun', { time: started(run) })} className="stretched-link block min-w-0 hover:text-brand focus-visible:text-brand">
          <span className="tabular block font-medium">{started(run)}</span>
          <span className="block truncate text-xs text-muted-foreground md:hidden">{run.summary ? t(`workflow.${run.summary.workflow}`) : t('unrecorded')}</span>
        </Link>
      ),
    },
    { key: 'workflow', header: t('column.workflow'), from: 'md', className: 'w-full whitespace-nowrap', cell: (run) => (run.summary ? t(`workflow.${run.summary.workflow}`) : t('unrecorded')) },
    { key: 'state', header: t('column.state'), className: 'whitespace-nowrap', cell: (run) => <RunStateBadge state={run.state} /> },
    { key: 'signals', header: t('column.signals'), numeric: true, from: 'md', cell: (run) => run.summary?.signals_generated ?? '—' },
    { key: 'orders', header: t('column.orders'), numeric: true, from: 'md', cell: (run) => run.summary?.orders_submitted ?? '—' },
    { key: 'errors', header: t('column.errors'), numeric: true, from: 'sm', cell: (run) => run.summary?.errors.length ?? (run.error ? 1 : 0) },
  ]
  return <DataTable rows={runs} columns={columns} rowKey={(run) => run.run_id} label={t('historyTitle')} />
}
