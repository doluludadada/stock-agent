import { Activity, ArrowRight, Megaphone, Play, Radar, ScanSearch, ShieldAlert } from 'lucide-react'
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
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { StockIdsProblem } from '@/shared/ui/stock-ids-problem'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { RequireUnlock } from '@/shared/ui/unlock'
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
    <div className="space-y-4">
      <PageHeader title={t('title')} description={t('description')} />
      <RequireUnlock scope="owner" className="rounded-xl border">
        <StartPanel />
        <History />
      </RequireUnlock>
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
          if (isApiError(error, 'conflict')) toast.error(t('busy'))
          else if (isApiError(error, 'forbidden')) toast.error(t('mockOnly'), { description: error.message })
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
    <Panel title={t('startTitle')} flush>
      <ul className="divide-y">
        {KINDS.map(({ kind, icon: Icon, orders }) => (
          <li key={kind} className="grid gap-x-4 gap-y-2 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
            <div className="min-w-0 space-y-0.5">
              <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium">
                <Icon aria-hidden className="size-4 text-muted-foreground" />
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
              <form onSubmit={onSpecific} className="flex flex-wrap items-start gap-2 md:w-80">
                <Input
                  value={stockText}
                  onChange={(event) => setStockText(event.target.value)}
                  placeholder={t('stocksPlaceholder')}
                  aria-label={t('stocksLabel')}
                  aria-describedby="specific-stocks-problem"
                  className="h-8 min-w-0 flex-1 font-mono"
                />
                <Button type="submit" size="sm" className="h-8" disabled={!isAcceptedList(stocks) || start.isPending}>
                  <Play aria-hidden />
                  {t('start')}
                </Button>
                <StockIdsProblem id="specific-stocks-problem" list={stocks} />
              </form>
            ) : (
              <Button type="button" size="sm" variant="outline" className="justify-self-start" onClick={() => setConfirming(kind)} disabled={start.isPending}>
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

function RunsTable({ runs }: { runs: Run[] }) {
  const { t } = useTranslation('runs')
  const locale = useLocale()
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('column.started')}</TableHead>
          <TableHead>{t('column.workflow')}</TableHead>
          <TableHead>{t('column.state')}</TableHead>
          <TableHead className="text-right">{t('column.signals')}</TableHead>
          <TableHead className="text-right">{t('column.orders')}</TableHead>
          <TableHead className="text-right">{t('column.errors')}</TableHead>
          <TableHead>
            <span className="sr-only">{t('open')}</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.run_id}>
            <TableCell className="tabular whitespace-nowrap">{run.summary ? formatDateTime(locale, run.summary.start_time) : '—'}</TableCell>
            <TableCell>{run.summary ? t(`workflow.${run.summary.workflow}`) : '—'}</TableCell>
            <TableCell>
              <RunStateBadge state={run.state} />
            </TableCell>
            <TableCell className="tabular text-right">{run.summary?.signals_generated ?? '—'}</TableCell>
            <TableCell className="tabular text-right">{run.summary?.orders_submitted ?? '—'}</TableCell>
            <TableCell className="tabular text-right">{run.summary?.errors.length ?? (run.error ? 1 : 0)}</TableCell>
            <TableCell className="text-right">
              <Button asChild size="sm" variant="ghost">
                <Link to={paths.run(run.run_id)} aria-label={t('openRun', { time: run.summary ? formatDateTime(locale, run.summary.start_time) : run.run_id })}>
                  <ArrowRight aria-hidden className="size-4" />
                </Link>
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
