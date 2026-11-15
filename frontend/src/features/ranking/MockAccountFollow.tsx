import { CopyCheck } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError, useAudience, type Audience } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useErrorReason } from '@/shared/lib/error-reason'
import { DASH, useFormat } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { FormulaLine } from '@/shared/ui/formula-line'
import { Panel, PanelLink } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { useFollowRanking, useRankingFollow } from './api'
import { clockTime, type Ranking, type RankingFollow } from './model'

/** The ranking in the viewer's mock account: what it holds, lacks and still holds, its return against the benchmark, and the one action. */
export function MockAccountFollow({ ranking, nextFollow, className }: { ranking: Ranking; nextFollow: string; className?: string }) {
  const { t } = useTranslation('ranking')
  const follow = useRankingFollow()
  const audience = useAudience()
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
          <Follows follows={follow.data.follows} />
          <Action follow={follow.data} ranking={ranking} audience={audience.data} />
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

/** The schedule's state in one line, and who started the last follow; the way to change it is My settings. */
function Schedule({ follow, nextFollow }: { follow: RankingFollow; nextFollow: string }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const { schedule, follows } = follow
  const last = follows.at(-1)
  const time = schedule.time && clockTime(schedule.time)
  return (
    <p className="text-sm text-pretty text-muted-foreground" data-testid="follow-schedule">
      {!time
        ? t('schedule.off')
        : schedule.pending
          ? t('schedule.pending', { date: format.monthDay(schedule.pending), time })
          : t('schedule.next', { date: format.monthDay(nextFollow), time })}{' '}
      {last && `${t(last.scheduled ? 'schedule.lastScheduled' : 'schedule.lastByHand', { date: format.monthDay(last.start_time.slice(0, 10)) })} `}
      <Link to={paths.mySettings} className="tap text-brand underline-offset-4 hover:underline">
        {t('schedule.change')}
      </Link>
    </p>
  )
}

/** How many of the account's follows the block lists; the rest are counted. */
const FOLLOWS_SHOWN = 3

/** The formula each follow used, newest first, so the return above is never read as one formula's when several made it. */
function Follows({ follows }: { follows: RankingFollow['follows'] }) {
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
            <span className="tabular">{format.date(run.start_time)}</span> {t(run.scheduled ? 'schedule.byScheduleMark' : 'schedule.byHandMark')}{' '}
            <FormulaLine formula={run.ranking_formula} />
          </li>
        ))}
      </ul>
      {newest.length > FOLLOWS_SHOWN && <p>{t('follow.earlier', { count: newest.length - FOLLOWS_SHOWN })}</p>}
    </div>
  )
}

function StockLine({ label, stockIds }: { label: string; stockIds: string[] }) {
  return (
    <p className="text-sm text-pretty">
      <span className="text-muted-foreground">{label}</span> <span className="font-mono">{stockIds.join(' ')}</span>
    </p>
  )
}

const REFUSALS: Record<string, 'follow.upToDate' | 'runs:follow.refused.window' | 'runs:follow.refused.quotes' | 'runs:busy'> = {
  nothing_to_follow: 'follow.upToDate',
  outside_follow_window: 'runs:follow.refused.window',
  realtime_quotes_unavailable: 'runs:follow.refused.quotes',
  run_in_progress: 'runs:busy',
}

interface ActionProps {
  follow: RankingFollow
  ranking: Ranking
  audience: Audience
}

/** Why the account cannot follow now, or the button; an account that holds the ranking shows neither. */
function Action({ follow, ranking, audience }: ActionProps) {
  const { t } = useTranslation('ranking')
  const reason = useErrorReason()
  const start = useFollowRanking()
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
    start.mutate(undefined, {
      onSuccess: () => toast.success(t('runs:follow.started')),
      onError: (error) => {
        const own = isApiError(error) && error.code ? REFUSALS[error.code] : undefined
        toast.error(own ? t(own) : t('runs:follow.failed', { reason: reason(error) }))
      },
    })
  }

  if (lead === null) return null
  return (
    <div className="flex flex-col gap-3 @lg:flex-row @lg:items-center @lg:justify-between">
      <p id={leadId} className="text-sm text-pretty text-muted-foreground">
        {lead}
      </p>
      {!upToDate && (
        <Button type="button" className="shrink-0 self-start @lg:self-auto" disabled={!ready || start.isPending} aria-describedby={leadId} onClick={() => setConfirming(true)}>
          <CopyCheck aria-hidden />
          {t('follow.button')}
        </Button>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t('follow.confirm.title')}
        description={t(`runs:follow.confirm.${pricing}`)}
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
        <p className="text-xs text-muted-foreground">{t('follow.confirm.sizing')}</p>
      </ConfirmDialog>
    </div>
  )
}
