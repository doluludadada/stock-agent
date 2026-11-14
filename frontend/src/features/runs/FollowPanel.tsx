import type { UseQueryResult } from '@tanstack/react-query'
import { CopyCheck } from 'lucide-react'
import { useId, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError, useAudience, type Schemas } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { useErrorReason } from '@/shared/lib/error-reason'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { useFollowRun, type Follow, type FollowItem, type Order, type Signal } from './api'
import { openDecisions } from './model'

type OrderPricing = Schemas['OrderPricing']

interface FollowPanelProps {
  runId: string
  follow: UseQueryResult<Follow>
  /** The run's decisions, which the confirmation lists; undefined until they load. */
  decisions: Signal[] | undefined
  names: ReadonlyMap<string, string>
}

/**
 * Follows a finished analysis into the user's mock account: what a follow takes now and at which price, or why it
 * cannot, and every follow so far with its outcome.
 */
export function FollowPanel({ runId, follow, decisions, names }: FollowPanelProps) {
  const { t } = useTranslation('runs')
  const audience = useAudience()
  if (follow.isError) return <ErrorState error={follow.error} title={t('follow.loadFailed')} onRetry={() => void follow.refetch()} className="rounded-2xl border bg-card" />
  if (audience.isError) return <ErrorState error={audience.error} title={t('common:audience.failed')} onRetry={() => void audience.refetch()} className="rounded-2xl border bg-card" />
  if (follow.isPending || audience.isPending) return <Skeleton className="h-32 rounded-2xl" />
  return (
    <Panel title={t('follow.title')} flush>
      <FollowAction
        runId={runId}
        follow={follow.data}
        pricing={audience.data.order_pricing}
        quoted={audience.data.order_pricing !== 'realtime_quote' || audience.data.realtime_quotes}
        decisions={decisions}
        names={names}
      />
      {follow.data.follows.length > 0 && <Follows items={follow.data.follows} names={names} />}
    </Panel>
  )
}

function useLead(follow: Follow, pricing: OrderPricing, quoted: boolean): string {
  const { t } = useTranslation('runs')
  if (!quoted && follow.refusal !== 'nothing_to_follow') return t('follow.noQuotes')
  switch (follow.refusal) {
    case null:
      return t(`follow.ready.${pricing}`, { count: follow.open_decision_ids.length })
    case 'outside_follow_window':
      return t(`follow.window.${pricing}`)
    case 'nothing_to_follow':
      return follow.follows.some(({ order }) => order.filled_quantity > 0) ? t('follow.allFollowed') : t('follow.noDecisions')
  }
}

interface FollowActionProps extends Omit<FollowPanelProps, 'follow'> {
  follow: Follow
  pricing: OrderPricing
  /** Whether the site has the price it follows at now: a site that follows at a realtime quote needs its Shioaji login. */
  quoted: boolean
}

function FollowAction({ runId, follow, pricing, quoted, decisions, names }: FollowActionProps) {
  const { t } = useTranslation('runs')
  const reason = useErrorReason()
  const format = useFormat()
  const navigate = useNavigate()
  const start = useFollowRun(runId)
  const [confirming, setConfirming] = useState(false)
  const leadId = useId()
  const lead = useLead(follow, pricing, quoted)
  const open = decisions ? openDecisions(follow, decisions) : []
  const ready = quoted && follow.refusal === null && open.length > 0

  const refusalText = (error: Error): string => {
    const code = isApiError(error) ? error.code : null
    if (code === 'nothing_to_follow') return t('follow.refused.nothing')
    if (code === 'outside_follow_window') return t('follow.refused.window')
    if (code === 'realtime_quotes_unavailable') return t('follow.refused.quotes')
    if (code === 'run_in_progress') return t('busy')
    return t('follow.failed', { reason: reason(error) })
  }
  const confirm = () => {
    setConfirming(false)
    start.mutate(undefined, {
      onSuccess: (accepted) => {
        toast.success(t('follow.started'))
        navigate(paths.run(accepted.run_id))
      },
      onError: (error) => toast.error(refusalText(error)),
    })
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-4 md:px-5 @2xl:flex-row @2xl:items-center @2xl:justify-between">
      <p id={leadId} className={cn('text-sm text-pretty', (follow.refusal !== null || !quoted) && 'text-muted-foreground')}>
        {lead}
      </p>
      <Button type="button" className="shrink-0 self-start @2xl:self-auto" disabled={!ready || start.isPending} aria-describedby={leadId} onClick={() => setConfirming(true)}>
        <CopyCheck aria-hidden />
        {t('follow.button')}
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t('follow.confirm.title')}
        description={t(`follow.confirm.${pricing}`)}
        cancel={t('confirm.cancel')}
        confirm={t('follow.confirm.go')}
        onConfirm={confirm}
      >
        <ul aria-label={t('follow.confirm.list')} className="max-h-64 divide-y overflow-y-auto rounded-lg border text-sm">
          {open.map((decision) => (
            <li key={decision.decision_id} className="flex items-baseline justify-between gap-3 px-3 py-2">
              <span className="min-w-0 truncate">
                <span className="font-mono">{decision.stock_id}</span> {names.get(decision.stock_id)}
              </span>
              <span className="tabular shrink-0">
                {t(`action.${decision.action}`)} · {t('follow.shares', { count: format.number(decision.quantity) })}
              </span>
            </li>
          ))}
        </ul>
        {open.some((decision) => decision.action === 'sell') && <p className="text-xs text-muted-foreground">{t('follow.confirm.sellNote')}</p>}
      </ConfirmDialog>
    </div>
  )
}

/** Every follow of the run so far, each with what became of its order and a link to the follow's own run. */
function Follows({ items, names }: { items: FollowItem[]; names: ReadonlyMap<string, string> }) {
  const { t } = useTranslation('runs')
  const format = useFormat()
  const stock = (item: FollowItem) => [item.decision.stock_id, names.get(item.decision.stock_id)].filter(Boolean).join(' ')
  const columns: Column<FollowItem>[] = [
    {
      key: 'followedAt',
      header: t('follow.column.followedAt'),
      className: 'whitespace-nowrap',
      cell: (item) => {
        const time = format.monthDayTime(item.order.created_at)
        return (
          <Link to={paths.run(item.order.run_id)} aria-label={t('follow.openFollow', { time })} className="stretched-link block min-w-0 hover:text-brand focus-visible:text-brand">
            <span className="tabular block font-medium">{time}</span>
            <span className="block truncate text-xs text-muted-foreground sm:hidden">
              {t(`action.${item.decision.action}`)} {stock(item)}
            </span>
          </Link>
        )
      },
    },
    { key: 'stock', header: t('column.stock'), from: 'sm', cell: (item) => stock(item) },
    { key: 'action', header: t('column.action'), from: 'sm', className: 'whitespace-nowrap', cell: ({ decision }) => t(`action.${decision.action}`) },
    { key: 'outcome', header: t('follow.column.outcome'), className: 'w-full min-w-40 whitespace-normal', cell: ({ order }) => <Outcome order={order} /> },
  ]
  return (
    <div className="border-t">
      <DataTable rows={items} columns={columns} rowKey={({ order }) => order.id} label={t('follow.followsLabel')} />
    </div>
  )
}

function Outcome({ order }: { order: Order }) {
  const { t } = useTranslation('runs')
  const format = useFormat()
  if (order.filled_quantity > 0 && order.average_filled_price !== null) {
    const figures = { shares: format.number(order.filled_quantity), ordered: format.number(order.quantity), price: format.price(order.average_filled_price) }
    return t(order.filled_quantity < order.quantity ? 'follow.filledPart' : 'follow.filled', figures)
  }
  const status = t(`orderStatus.${order.status}`)
  return <span className="text-muted-foreground">{order.reason ? t('follow.unfilled', { status, reason: order.reason }) : status}</span>
}
