import { Activity, Megaphone, Play, Radar, ScanSearch, ShieldAlert } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { isApiError } from '@/shared/api'
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
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { PAGE_SIZE, useRunsPage, useStartRun, type Run, type RunKind } from './api'
import { RunStateBadge } from './RunStateBadge'

const KINDS: { kind: RunKind; icon: typeof Play; orders: boolean }[] = [
  { kind: 'full-cycle', icon: Radar, orders: false },
  { kind: 'specific-stocks', icon: ScanSearch, orders: false },
  { kind: 'buzz-scan', icon: Megaphone, orders: true },
  { kind: 'intraday', icon: Activity, orders: true },
]

export function RunsPage() {
  const { t } = useTranslation('runs')
  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader eyebrow={t('common:nav.section.mine')} title={t('title')} description={t('description')} />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <div className="space-y-4 lg:space-y-5">
          <StartPanel />
          <History />
        </div>
      </RequireSignIn>
    </div>
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
