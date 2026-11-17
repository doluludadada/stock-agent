import { CopyCheck } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError, useAudience, type Audience, type Broker } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useErrorReason } from '@/shared/lib/error-reason'
import { clockTime, DASH, useFormat } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { FormulaLine } from '@/shared/ui/formula-line'
import { OrdersTable } from '@/shared/ui/orders-table'
import { Panel, PanelLink } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { useFollowOrders, useFollowRanking, useRankingFollow } from './api'
import { offeredBrokers, unfinishedReason, type Ranking, type RankingFollow } from './model'

/**
 * The ranking in the viewer's mock account: what it holds, lacks and still holds, its return against the benchmark, and
 * the one action. The block's own action follows on the first account the server lists, the one its holdings are read
 * from; every other account the server lists gets one button, and each follow says the account it ran on.
 */
export function MockAccountFollow({ ranking, nextFollow, className }: { ranking: Ranking; nextFollow: string; className?: string }) {
  const { t } = useTranslation('ranking')
  const follow = useRankingFollow()
  const audience = useAudience()
  const [own, ...others] = follow.data?.schedule.brokers ?? []
  return (
    <Panel className={className} title={t('follow.title')} aside={<PanelLink to={paths.account}>{t('follow.account')}</PanelLink>}>
      {follow.isError ? (
        <ErrorState error={follow.error} title={t('follow.loadFailed')} onRetry={() => void follow.refetch()} />
      ) : audience.isError ? (
        <ErrorState error={audience.error} title={t('common:audience.failed')} onRetry={() => void audience.refetch()} />
      ) : follow.isPending || audience.isPending ? (
        <Skeleton className="h-16" />
      ) : (
        <div className="flex flex-col gap-3">
          {(follow.data.performance || follow.data.holdings.held.length > 0) && <Standing follow={follow.data} count={ranking.stocks.length} />}
          <Schedule follow={follow.data} nextFollow={nextFollow} />
          <Follows follows={follow.data.follows} running={follow.data.running} />
          {own && <Action broker={own} follow={follow.data} ranking={ranking} audience={audience.data} />}
          {others.map((broker) => (
            <AccountFollow key={broker} broker={broker} running={follow.data.running} audience={audience.data} />
          ))}
        </div>
      )}
    </Panel>
  )
}

function Return({ value }: { value: number | null | undefined }) {
  return value == null ? DASH : <ChangeValue value={value} format="percent" />
}

function Standing({ follow, count }: { follow: RankingFollow; count: number }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const { holdings, performance } = follow
  return (
    <>
      <dl className="grid grid-cols-3 gap-3">
        {count > 0 && (
          <Stat label={t('follow.holds')} size="lg">
            {t('follow.heldOf', { held: holdings.held.length, count })}
          </Stat>
        )}
        {/* An account that holds the ranking's stocks without a follow since it opened has no return to compare. */}
        {performance && (
          <>
            <Stat label={t('follow.since', { since: format.monthDay(performance.since) })} size="lg">
              <Return value={performance.account_return} />
            </Stat>
            <Stat label={performance.benchmark_id} size="lg">
              <Return value={performance.benchmark_return} />
            </Stat>
          </>
        )}
      </dl>
      {holdings.lacking.length > 0 && <StockLine label={t('follow.lacking')} stockIds={holdings.lacking} />}
      {holdings.left.length > 0 && <StockLine label={t('follow.left')} stockIds={holdings.left} />}
    </>
  )
}

/**
 * The schedule's state in one line, and who started the last follow; the way to change it is My settings. A schedule
 * that is on and whose last follow left the decision pending says so, with why and the run, in place of what it
 * follows next. With more than one account in play it says the account, or that the site does not offer the saved one.
 */
function Schedule({ follow, nextFollow }: { follow: RankingFollow; nextFollow: string }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const { schedule, follows } = follow
  const time = schedule.time && clockTime(schedule.time)
  const unfinished = time && !follow.running ? schedule.unfinished : null
  // A follow that left stocks to trade is listed among the follows too, and the line already says its day.
  const last = follows.findLast((run) => run.run_id !== unfinished?.run_id)
  return (
    <p className="text-sm text-pretty text-muted-foreground" data-testid="follow-schedule">
      {!time ? (
        t('schedule.off')
      ) : unfinished ? (
        <>
          {t('schedule.unfinished', {
            date: format.monthDay(unfinished.start_time),
            why: t(`schedule.why.${unfinishedReason(unfinished)}`, { count: unfinished.ranking_open ?? 0 }),
            time,
          })}{' '}
          <Link to={paths.run(unfinished.run_id)} className="tap text-brand underline-offset-4 hover:underline">
            {t('schedule.run')}
          </Link>
        </>
      ) : schedule.pending ? (
        t('schedule.pending', { date: format.monthDay(schedule.pending), time })
      ) : (
        t('schedule.next', { date: format.monthDay(nextFollow), time })
      )}{' '}
      {time && offeredBrokers(schedule).length > 1 && `${t(schedule.broker_offered ? `schedule.on.${schedule.broker}` : `schedule.notOffered.${schedule.broker}`)} `}
      {last && `${t(last.scheduled ? 'schedule.lastScheduled' : 'schedule.lastByHand', { date: format.monthDay(last.start_time) })} `}
      <Link to={paths.mySettings} className="tap text-brand underline-offset-4 hover:underline">
        {t('schedule.change')}
      </Link>
    </p>
  )
}

/** How many of the account's follows the block lists; the rest are counted. */
const FOLLOWS_SHOWN = 3

/**
 * The account and the formula each follow used, newest first, so the return above is never read as one formula's when
 * several made it. Each follow opens its orders, with the status its account gave each, and links to its run, whose
 * log says what the follow left for a later one and why.
 */
function Follows({ follows, running }: { follows: RankingFollow['follows']; running: boolean }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  if (follows.length === 0) return null
  const newest = follows.toReversed()
  return (
    <div className="text-xs text-pretty text-muted-foreground">
      <p>{t('follow.used')}</p>
      <ul aria-label={t('follow.used')}>
        {newest.slice(0, FOLLOWS_SHOWN).map((run) => (
          <li key={run.run_id}>
            <span className="tabular">{format.date(run.start_time)}</span> {t(run.scheduled ? 'schedule.byScheduleMark' : 'schedule.byHandMark')} · {t(`account.${run.execution_provider}`)} ·{' '}
            <FormulaLine formula={run.ranking_formula} />
            <FollowOrders runId={run.run_id} date={format.monthDay(run.start_time)} running={running} />{' '}
            <Link to={paths.run(run.run_id)} className="tap text-brand underline-offset-4 hover:underline">
              {t('follow.run', { date: format.monthDay(run.start_time) })}
            </Link>
          </li>
        ))}
      </ul>
      {newest.length > FOLLOWS_SHOWN && <p>{t('follow.earlier', { count: newest.length - FOLLOWS_SHOWN })}</p>}
    </div>
  )
}

/** A follow's orders, asked for when the reader opens them. */
function FollowOrders({ runId, date, running }: { runId: string; date: string; running: boolean }) {
  const { t } = useTranslation('ranking')
  const [open, setOpen] = useState(false)
  const orders = useFollowOrders(runId, open, running)
  return (
    <>
      {' '}
      <button type="button" className="tap text-brand underline-offset-4 hover:underline" aria-expanded={open} onClick={() => setOpen(!open)}>
        {t('follow.orders', { date })}
      </button>
      {open && (
        <div className="mt-1 mb-2 overflow-hidden rounded-lg border text-foreground">
          {orders.isPending ? (
            <Skeleton className="h-12" />
          ) : orders.isError ? (
            <ErrorState error={orders.error} title={t('runs:ordersFailed')} onRetry={() => void orders.refetch()} />
          ) : (
            <OrdersTable compact orders={orders.data} label={t('follow.orders', { date })} />
          )}
        </div>
      )}
    </>
  )
}

function StockLine({ label, stockIds }: { label: string; stockIds: string[] }) {
  return (
    <p className="text-sm text-pretty">
      <span className="text-muted-foreground">{label}</span> <span className="font-mono">{stockIds.join(' ')}</span>
    </p>
  )
}

const REFUSALS: Record<string, 'runs:follow.refused.window' | 'runs:follow.refused.quotes' | 'runs:busy'> = {
  outside_follow_window: 'runs:follow.refused.window',
  realtime_quotes_unavailable: 'runs:follow.refused.quotes',
  run_in_progress: 'runs:busy',
}

/** Starts a follow on an account and says how it went: the block's own words for a refusal it has them for, else the reason by its code. */
function useStartFollow() {
  const { t } = useTranslation('ranking')
  const reason = useErrorReason()
  const start = useFollowRanking()
  const follow = (broker: Broker) =>
    start.mutate(broker, {
      onSuccess: () => toast.success(t('runs:follow.started')),
      onError: (error) => {
        const code = isApiError(error) ? error.code : null
        const own = code === 'nothing_to_follow' ? t(`follow.on.${broker}.upToDate`) : code && REFUSALS[code] ? t(REFUSALS[code]) : null
        toast.error(own ?? t('runs:follow.failed', { reason: reason(error) }))
      },
    })
  return { follow, pending: start.isPending }
}

interface ActionProps {
  /** The account the block's holdings are read from, which this action follows on. */
  broker: Broker
  follow: RankingFollow
  ranking: Ranking
  audience: Audience
}

/** Why the account cannot follow now, or the button; an account that holds the ranking shows neither. */
function Action({ broker, follow, ranking, audience }: ActionProps) {
  const { t } = useTranslation('ranking')
  const start = useStartFollow()
  const [confirming, setConfirming] = useState(false)
  const leadId = useId()
  const { holdings, refusal } = follow
  const ranked = ranking.stocks
  const pricing = audience.order_pricing
  // A site that follows at a realtime quote needs its Shioaji login for the price.
  const quoted = pricing !== 'realtime_quote' || audience.realtime_quotes
  const upToDate = refusal === 'nothing_to_follow'
  const ready = quoted && refusal === null && !follow.running
  const lead = follow.running
    ? t('follow.running')
    : upToDate
      ? ranked.length > 0
        ? null
        : t(ranking.holds_cash ? 'follow.inCash' : 'follow.nothing')
      : !quoted
        ? t('runs:follow.noQuotes')
        : refusal === 'outside_follow_window'
          ? t(`runs:follow.window.${pricing}`)
          : ranking.holds_cash
            ? t('follow.toCash', { sells: holdings.left.length })
            : holdings.held.length > 0
              ? t('follow.behind', { sells: holdings.left.length, buys: holdings.lacking.length })
              : t('follow.never')
  const names = new Map(ranked.map((stock) => [stock.stock_id, stock.stock_name]))
  const trades = [...holdings.left.map((stockId) => ({ stockId, action: 'sell' as const })), ...holdings.lacking.map((stockId) => ({ stockId, action: 'buy' as const }))]

  const confirm = () => {
    setConfirming(false)
    start.follow(broker)
  }

  if (lead === null) return null
  return (
    <div className="flex flex-col gap-3 @lg:flex-row @lg:items-center @lg:justify-between">
      <p id={leadId} className="text-sm text-pretty text-muted-foreground">
        {lead}
      </p>
      {!upToDate && (
        <Button type="button" className="shrink-0 self-start @lg:self-auto" disabled={!ready || start.pending} aria-describedby={leadId} onClick={() => setConfirming(true)}>
          <CopyCheck aria-hidden />
          {t(`follow.on.${broker}.button`)}
        </Button>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t(`follow.on.${broker}.confirm.title`)}
        description={t(`follow.on.${broker}.confirm.${pricing}`)}
        cancel={t('runs:confirm.cancel')}
        confirm={t('runs:follow.confirm.go')}
        onConfirm={confirm}
      >
        <ul aria-label={t('follow.confirm.list')} className="max-h-64 divide-y overflow-y-auto rounded-lg border text-sm">
          {trades.map(({ stockId, action }) => (
            <li key={stockId} className="flex items-baseline justify-between gap-3 px-3 py-2">
              <span className="min-w-0 truncate">
                <span className="font-mono">{stockId}</span> {names.get(stockId)}
              </span>
              <span className="shrink-0">{t(`runs:action.${action}`)}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">{t(`follow.on.${broker}.confirm.sizing`)}</p>
      </ConfirmDialog>
    </div>
  )
}

/**
 * A follow by hand on an account the block reads nothing of, so the yes lists no order. The button knows only the
 * site's facts, a run of the user in progress and the quotes the site prices on: whether that account can follow now is
 * the server's answer to the start.
 */
function AccountFollow({ broker, running, audience }: { broker: Broker; running: boolean; audience: Audience }) {
  const { t } = useTranslation('ranking')
  const start = useStartFollow()
  const [confirming, setConfirming] = useState(false)
  const leadId = useId()
  const pricing = audience.order_pricing
  const quoted = pricing !== 'realtime_quote' || audience.realtime_quotes

  const confirm = () => {
    setConfirming(false)
    start.follow(broker)
  }

  return (
    <div className="flex flex-col gap-3 border-t pt-3 @lg:flex-row @lg:items-center @lg:justify-between">
      <p id={leadId} className="text-sm text-pretty text-muted-foreground">
        {quoted ? t(`follow.on.${broker}.lead`) : t('runs:follow.noQuotes')}
      </p>
      <Button type="button" variant="outline" className="shrink-0 self-start @lg:self-auto" disabled={!quoted || running || start.pending} aria-describedby={leadId} onClick={() => setConfirming(true)}>
        <CopyCheck aria-hidden />
        {t(`follow.on.${broker}.button`)}
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t(`follow.on.${broker}.confirm.title`)}
        description={t(`follow.on.${broker}.confirm.${pricing}`)}
        cancel={t('runs:confirm.cancel')}
        confirm={t('runs:follow.confirm.go')}
        onConfirm={confirm}
      >
        <p className="text-xs text-muted-foreground">{t(`follow.on.${broker}.confirm.sizing`)}</p>
      </ConfirmDialog>
    </div>
  )
}
