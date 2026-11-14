import { History, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useErrorReason } from '@/shared/lib/error-reason'
import { DASH, useFormat } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useBacktests, useDeleteBacktest } from './api'
import type { BacktestSummary } from './model'

interface SavedBacktestsProps {
  /** The backtest on screen, marked in the list. */
  shownId: string | null
  onDeleted: (backtestId: string) => void
  className?: string
}

/** The earlier backtests side by side, newest first: each opens its result, and one can be deleted after a yes. */
export function SavedBacktests({ shownId, onDeleted, className }: SavedBacktestsProps) {
  const { t } = useTranslation('backtest')
  const format = useFormat()
  const saved = useBacktests()
  const reason = useErrorReason()
  const remove = useDeleteBacktest()
  const [deleting, setDeleting] = useState<BacktestSummary | null>(null)
  const when = (backtest: BacktestSummary) => format.monthDayTime(backtest.created_at)
  const period = (backtest: BacktestSummary) => t('period', { first: format.date(backtest.first_session), last: format.date(backtest.last_session) })

  const confirmDelete = () => {
    if (!deleting) return
    const id = deleting.backtest_id
    setDeleting(null)
    remove.mutate(id, {
      onSuccess: () => {
        toast.success(t('saved.deleted'))
        onDeleted(id)
      },
      onError: (error) => {
        if (isApiError(error, 'notFound')) return onDeleted(id)
        toast.error(t('saved.deleteFailed', { reason: reason(error) }))
      },
    })
  }

  const columns: Column<BacktestSummary>[] = [
    {
      key: 'when',
      header: t('saved.column.when'),
      className: 'w-full max-w-0',
      cell: (backtest) => (
        <Link
          to={paths.savedBacktest(backtest.backtest_id)}
          aria-current={backtest.backtest_id === shownId ? 'true' : undefined}
          aria-label={t('saved.open', { time: when(backtest) })}
          className="flex min-h-11 min-w-0 flex-col justify-center hover:text-brand focus-visible:text-brand md:min-h-0"
        >
          <span className="tabular font-medium whitespace-nowrap">{when(backtest)}</span>
          <span className="truncate text-xs text-muted-foreground">
            <span className="lg:hidden">{t('saved.line', { strategy: backtest.strategy_name, period: period(backtest), buy: backtest.inputs.buy_score, sell: backtest.inputs.sell_score })}</span>
            <span className="hidden lg:inline">{backtest.strategy_name}</span>
          </span>
        </Link>
      ),
    },
    { key: 'period', header: t('saved.column.period'), from: 'lg', className: 'tabular whitespace-nowrap', cell: period },
    { key: 'scores', header: t('saved.column.scores'), numeric: true, from: 'lg', cell: (backtest) => t('stat.buySell', { buy: backtest.inputs.buy_score, sell: backtest.inputs.sell_score }) },
    { key: 'return', header: t('saved.column.return'), numeric: true, cell: (backtest) => <ChangeValue value={backtest.total_return_pct} format="percent" /> },
    {
      key: 'benchmark',
      header: t('saved.column.benchmark'),
      numeric: true,
      from: 'sm',
      cell: (backtest) => (backtest.benchmark_return_pct === null ? DASH : <ChangeValue value={backtest.benchmark_return_pct} format="percent" />),
    },
    { key: 'trades', header: t('saved.column.trades'), numeric: true, from: 'md', cell: (backtest) => format.number(backtest.trade_count) },
    {
      key: 'delete',
      header: t('saved.column.delete'),
      quietHeader: true,
      cell: (backtest) => (
        <Button type="button" variant="ghost" size="icon-sm" aria-label={t('saved.delete', { time: when(backtest) })} disabled={remove.isPending} onClick={() => setDeleting(backtest)}>
          <Trash2 aria-hidden />
        </Button>
      ),
    },
  ]

  return (
    <Panel className={className} flush title={t('saved.title')}>
      {saved.isPending ? (
        <Skeleton className="m-4 h-24 rounded-xl" />
      ) : saved.isError ? (
        <ErrorState error={saved.error} title={t('saved.loadFailed')} onRetry={() => void saved.refetch()} />
      ) : saved.data.length === 0 ? (
        <StateBlock icon={History} title={t('saved.none')} description={t('saved.noneHint')} />
      ) : (
        <DataTable
          rows={saved.data}
          columns={columns}
          rowKey={(backtest) => backtest.backtest_id}
          label={t('saved.title')}
          className="rounded-b-2xl"
          rowClassName={(backtest) => (backtest.backtest_id === shownId ? 'bg-brand-soft hover:bg-brand-soft' : undefined)}
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t('saved.confirm.title')}
        description={deleting ? t('saved.confirm.description', { time: when(deleting), strategy: deleting.strategy_name, period: period(deleting) }) : ''}
        cancel={t('saved.confirm.cancel')}
        confirm={t('saved.confirm.go')}
        onConfirm={confirmDelete}
        destructive
      />
    </Panel>
  )
}
