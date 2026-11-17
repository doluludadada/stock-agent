import { useTranslation } from '@/i18n'
import { useIndexHistory, useIndexQuote, useMarketBreadth, withQuote } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { CHART_RANGES, HISTORY_BARS, sessionDate, summarize } from '@/shared/lib/chart-range'
import { directionOf } from '@/shared/lib/direction'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { BreadthBar } from '@/shared/ui/breadth-bar'
import { ChangeValue } from '@/shared/ui/change-value'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel, PanelLink } from '@/shared/ui/panel'
import { QuoteHeadline } from '@/shared/ui/quote-headline'
import { QuoteTime } from '@/shared/ui/quote-time'
import { Skeleton } from '@/shared/ui/skeleton'
import { Sparkline } from '@/shared/ui/sparkline'
import { breadthMood, DEFAULT_INDEX, MOOD_TONE } from './model'

/**
 * The market in one row for the home page: the index's last close and its month, and how the last settled session
 * split. Once a session opened, a signed-in viewer of a site with realtime quotes sees the index at its quote.
 */
export function MarketToday({ className }: { className?: string }) {
  const { t } = useTranslation('overview')
  const format = useFormat()
  const history = useIndexHistory(DEFAULT_INDEX, HISTORY_BARS)
  const breadth = useMarketBreadth()
  const quoted = useIndexQuote(DEFAULT_INDEX)
  const { bars, tradedAt } = withQuote(history.data?.bars ?? [], quoted.quote)
  const last = bars.at(-1)
  const change = summarize(bars, '1M')?.dayChange ?? null
  const market = breadth.data?.market
  const breadthSession = breadth.data?.session_close

  return (
    <Panel className={className} title={t(`index.${DEFAULT_INDEX}`)} aside={<PanelLink to={paths.market}>{t('title')}</PanelLink>}>
      {history.isPending ? (
        <Skeleton className="h-16 rounded-lg" />
      ) : !last ? (
        <ErrorState error={history.error} title={t('trend.failed')} onRetry={() => void history.refetch()} />
      ) : (
        <div className="grid items-center gap-x-8 gap-y-4 @3xl:grid-cols-[auto_auto_minmax(0,1fr)]">
          <QuoteHeadline
            value={format.number(last.close, 2)}
            change={change?.value ?? null}
            changeRatio={change?.ratio ?? null}
            asOf={<QuoteTime session={sessionDate(last.ts)} tradedAt={tradedAt} live={quoted.live} />}
          />
          <Sparkline values={bars.slice(-CHART_RANGES['1M']).map((bar) => bar.close)} direction={directionOf(change?.value ?? 0)} className="hidden @3xl:block" />
          {market && (
            <div className="min-w-0 space-y-2">
              <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
                <span>
                  <span className={cn('font-semibold', MOOD_TONE[breadthMood(market)])}>{t(`breadth.mood.${breadthMood(market)}`)}</span>{' '}
                  {breadthSession && <span className="text-xs text-muted-foreground">{format.closeOn(breadthSession)}</span>}
                </span>
                <span className="tabular text-xs text-muted-foreground">
                  <span className="text-up">{t('breadth.advancers')} {format.number(market.advancers)}</span>
                  {' · '}
                  <span className="text-down">{t('breadth.decliners')} {format.number(market.decliners)}</span>
                  {' · '}
                  {t('breadth.average')} <ChangeValue value={market.average_change_percent / 100} format="percent" />
                </span>
              </p>
              <BreadthBar up={market.advancers} flat={market.unchanged} down={market.decliners} />
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
