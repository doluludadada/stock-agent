import { CopyCheck } from 'lucide-react'
import { useId, useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError, useAudience } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useErrorReason } from '@/shared/lib/error-reason'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel, PanelLink } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { useFollowRanking, useRankingFollow } from './api'
import type { Ranking, RankingFollow } from './model'

/**
 * The ranking in the viewer's mock account: which of this month's stocks it holds, what it made since it first
 * followed against the benchmark, and the one action that brings it to the ranking.
 */
export function MockAccountFollow({ ranking, className }: { ranking: Ranking; className?: string }) {
  const { t } = useTranslation('ranking')
  const follow = useRankingFollow()
  const audience = useAudience()
  const content = () => {
    if (follow.isError) return <ErrorState error={follow.error} title={t('follow.loadFailed')} onRetry={() => void follow.refetch()} />
    if (audience.isError) return <ErrorState error={audience.error} title={t('common:audience.failed')} onRetry={() => void audience.refetch()} />
    if (follow.isPending || audience.isPending) return <Skeleton className="h-24" />
    return (
      <div className="flex flex-col gap-4">
        {follow.data.performance && <Standing follow={follow.data} count={ranking.stocks.length} />}
        <Action
          follow={follow.data}
          names={new Map(ranking.stocks.map((stock) => [stock.stock_id, stock.stock_name]))}
          pricing={audience.data.order_pricing}
          quoted={audience.data.order_pricing !== 'realtime_quote' || audience.data.realtime_quotes}
        />
      </div>
    )
  }
  return (
    <Panel className={className} title={t('follow.title')} description={t('follow.question')} aside={<PanelLink to={paths.account}>{t('follow.account')}</PanelLink>}>
      {content()}
    </Panel>
  )
}

function Standing({ follow, count }: { follow: RankingFollow; count: number }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const { holdings } = follow
  const performance = follow.performance!
  const figure = (value: number | null | undefined) => (value == null ? '—' : <ChangeValue value={value} format="percent" />)
  return (
    <>
      <dl className="grid grid-cols-3 gap-3">
        <Stat label={t('follow.holds')} size="lg">
          {t('follow.heldOf', { held: holdings.held.length, count })}
        </Stat>
        <Stat label={t('follow.accountReturn')} size="lg">
          {figure(performance.account_return)}
        </Stat>
        <Stat label={t('follow.benchmarkReturn', { benchmark: performance.benchmark_id })} size="lg">
          {figure(performance.benchmark_return)}
        </Stat>
      </dl>
      <p className="text-xs text-pretty text-muted-foreground">
        {performance.until ? t('follow.span', { since: format.date(performance.since), until: format.date(performance.until) }) : t('follow.spanPending', { since: format.date(performance.since) })}
      </p>
      {holdings.lacking.length > 0 && <StockLine label={t('follow.lacking')} stockIds={holdings.lacking} />}
      {holdings.left.length > 0 && <StockLine label={t('follow.left')} stockIds={holdings.left} />}
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

interface ActionProps {
  follow: RankingFollow
  names: ReadonlyMap<string, string | null | undefined>
  pricing: 'realtime_quote' | 'official_close'
  /** Whether the site has the price it follows at now: a site that follows at a realtime quote needs its Shioaji login. */
  quoted: boolean
}

/** One sentence that says where the account stands, and the button while a follow has something to trade. */
function Action({ follow, names, pricing, quoted }: ActionProps) {
  const { t } = useTranslation('ranking')
  const reason = useErrorReason()
  const start = useFollowRanking()
  const [confirming, setConfirming] = useState(false)
  const leadId = useId()
  const { holdings, refusal } = follow
  const upToDate = refusal === 'nothing_to_follow'
  const ready = quoted && refusal === null && !follow.running
  const lead = follow.running
    ? t('follow.running')
    : upToDate
      ? t(follow.performance ? 'follow.upToDate' : 'follow.nothing')
      : !quoted
        ? t('runs:follow.noQuotes')
        : refusal === 'outside_follow_window'
          ? t(`runs:follow.window.${pricing}`)
          : follow.performance
            ? t('follow.behind', { sells: holdings.left.length, buys: holdings.lacking.length })
            : t('follow.never')
  const trades = [...holdings.left.map((stockId) => ({ stockId, action: 'sell' as const })), ...holdings.lacking.map((stockId) => ({ stockId, action: 'buy' as const }))]

  const refusalText = (error: Error): string => {
    const code = isApiError(error) ? error.code : null
    if (code === 'nothing_to_follow') return t('follow.upToDate')
    if (code === 'outside_follow_window') return t('runs:follow.refused.window')
    if (code === 'realtime_quotes_unavailable') return t('runs:follow.refused.quotes')
    if (code === 'run_in_progress') return t('runs:busy')
    return t('runs:follow.failed', { reason: reason(error) })
  }
  const confirm = () => {
    setConfirming(false)
    start.mutate(undefined, { onSuccess: () => toast.success(t('runs:follow.started')), onError: (error) => toast.error(refusalText(error)) })
  }

  return (
    <div className="flex flex-col gap-3 @2xl:flex-row @2xl:items-center @2xl:justify-between">
      <p id={leadId} className={cn('text-sm text-pretty', !ready && 'text-muted-foreground')}>
        {lead}
      </p>
      {!upToDate && (
        <Button type="button" className="shrink-0 self-start @2xl:self-auto" disabled={!ready || start.isPending} aria-describedby={leadId} onClick={() => setConfirming(true)}>
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
