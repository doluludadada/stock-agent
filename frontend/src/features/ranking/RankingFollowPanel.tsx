import { CopyCheck } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { useAccountLabel, useAudience, type Audience, type Broker } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useFollowRefusal } from '@/shared/lib/error-reason'
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
import { LEAD_BUTTON, leadOf, unfinishedReason, type FollowLead, type Ranking, type RankingFollow } from './model'

/**
 * The ranking in the viewer's follow account, the one account the button and the schedule follow on, which the title
 * names as the server answered it: what it holds, lacks and still holds, the mock account's return against the
 * benchmark or the way to SinoPac's own page, the schedule, the follows so far, and the one action, or why the account
 * cannot follow now. The account is changed on My settings.
 */
export function RankingFollowPanel({ ranking, nextFollow, className }: { ranking: Ranking; nextFollow: string; className?: string }) {
  const { t } = useTranslation('ranking')
  const label = useAccountLabel()
  const follow = useRankingFollow()
  const audience = useAudience()
  const account = follow.data?.account
  return (
    <Panel
      className={className}
      title={account ? label(account.broker, account.server) : undefined}
      aside={<PanelLink to={paths.mySettings}>{t('follow.change')}</PanelLink>}
    >
      {follow.isError ? (
        <ErrorState error={follow.error} title={t('follow.loadFailed')} onRetry={() => void follow.refetch()} />
      ) : audience.isError ? (
        <ErrorState error={audience.error} title={t('common:audience.failed')} onRetry={() => void audience.refetch()} />
      ) : follow.isPending || audience.isPending ? (
        <Skeleton className="h-16" />
      ) : (
        <div className="flex flex-col gap-3">
          {(follow.data.performance || follow.data.holdings.held.length > 0) && <Standing follow={follow.data} count={ranking.stocks.length} />}
          <AccountPage follow={follow.data} />
          <Schedule follow={follow.data} nextFollow={nextFollow} />
          <Follows follows={follow.data.follows} running={follow.data.running} />
          <Action follow={follow.data} ranking={ranking} audience={audience.data} />
        </div>
      )}
    </Panel>
  )
}

/** Each account's own page: the mock account's, or SinoPac's, whose history the site does not keep. */
const ACCOUNT_PAGES: Readonly<Record<Broker, string>> = { mock: paths.account, shioaji: paths.brokerage }

/** Where the account's own figures are. */
function AccountPage({ follow }: { follow: RankingFollow }) {
  const { t } = useTranslation('ranking')
  const broker = follow.account.broker
  return (
    <p className="text-sm">
      <Link to={ACCOUNT_PAGES[broker]} className="tap text-brand underline-offset-4 hover:underline">
        {t(`follow.on.${broker}.page`)}
      </Link>
    </p>
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
 * that is on while the server refuses the account says it follows on no account. One whose last follow left the
 * decision pending says so, with why and the run, in place of what it follows next. It follows on the account the
 * title names.
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
      ) : follow.account.refusal !== null ? (
        t('schedule.refused')
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
            <span className="tabular">{format.date(run.start_time)}</span> {t(run.scheduled ? 'schedule.byScheduleMark' : 'schedule.byHandMark')} · {t(`common:broker.name.${run.execution_provider}`)} ·{' '}
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

/** The lead's words; an account that holds the ranking has none. */
function useLeadText(lead: FollowLead): string | null {
  const { t } = useTranslation('ranking')
  switch (lead.kind) {
    case 'running':
      return t('follow.running')
    case 'refused':
      return t(`common:refusal.${lead.refusal}`)
    case 'held':
      return null
    case 'inCash':
      return t('follow.inCash')
    case 'nothing':
      return t('follow.nothing')
    case 'noQuotes':
      return t('runs:follow.noQuotes')
    case 'window':
      return t(`runs:follow.window.${lead.pricing}`)
    case 'toCash':
      return t('follow.toCash', { sells: lead.sells })
    case 'behind':
      return t('follow.behind', { sells: lead.sells, buys: lead.buys })
    case 'never':
      return t('follow.never')
  }
}

interface ActionProps {
  follow: RankingFollow
  ranking: Ranking
  audience: Audience
}

/**
 * Why the account cannot follow now, or the button; an account that holds the ranking shows neither. A refusal of the
 * account itself is said in place of what a follow would do, and the button stays, disabled, so the viewer sees where
 * the follow would happen. The follow names the account the dialog showed, so a change on My settings meanwhile is
 * refused rather than followed elsewhere.
 */
function Action({ follow, ranking, audience }: ActionProps) {
  const { t } = useTranslation('ranking')
  const refusal = useFollowRefusal()
  const start = useFollowRanking()
  const [confirming, setConfirming] = useState(false)
  const leadId = useId()
  const lead = leadOf(follow, ranking, audience)
  const text = useLeadText(lead)
  const button = LEAD_BUTTON[lead.kind]
  const { holdings } = follow
  const broker = follow.account.broker
  const pricing = audience.order_pricing
  const names = new Map(ranking.stocks.map((stock) => [stock.stock_id, stock.stock_name]))
  const trades = [...holdings.left.map((stockId) => ({ stockId, action: 'sell' as const })), ...holdings.lacking.map((stockId) => ({ stockId, action: 'buy' as const }))]

  const confirm = () => {
    setConfirming(false)
    start.mutate(broker, {
      onSuccess: () => toast.success(t('runs:follow.started')),
      onError: (error) => toast.error(refusal(error, t(`follow.on.${broker}.upToDate`))),
    })
  }

  if (text === null) return null
  return (
    <div className="flex flex-col gap-3 @lg:flex-row @lg:items-center @lg:justify-between">
      <p id={leadId} className="text-sm text-pretty text-muted-foreground">
        {text}
      </p>
      {button !== 'none' && (
        <Button type="button" className="shrink-0 self-start @lg:self-auto" disabled={button !== 'ready' || start.isPending} aria-describedby={leadId} onClick={() => setConfirming(true)}>
          <CopyCheck aria-hidden />
          {t('follow.button')}
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
