import { ListX } from 'lucide-react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { useFormat } from '@/shared/lib/format'
import { Panel } from '@/shared/ui/panel'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { nextDecision, turnover, type Ranking } from './model'
import { RankedStocksTable } from './RankedStocksTable'

/** The ranking of the month before: still asked for, not answered, or answered; null when the history holds none before. */
export type PreviousRanking = { status: 'loading' } | { status: 'failed' } | { status: 'ready'; ranking: Ranking | null }

interface LatestRankingProps {
  ranking: Ranking
  previous: PreviousRanking
  /** The day of the month the ranking decides on or after. */
  decisionDay: number
  today: string
}

/** Which stocks the formula picks now: the decision it comes from, when the next one is due, what changed, and the stocks in order. */
export function LatestRanking({ ranking, previous, decisionDay, today }: LatestRankingProps) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const next = nextDecision(ranking.decided_on, decisionDay, today)
  const changed = previous.status === 'ready' && previous.ranking ? turnover(previous.ranking, ranking) : null
  const entered = new Set(changed?.entered.map((stock) => stock.stock_id))
  const [year, month] = ranking.revenue_month.split('-').map(Number) as [number, number]

  return (
    <Panel flush title={t('latest.title')} description={t('latest.question')} aside={ranking.stocks.length > 0 && <span className="tabular">{t('latest.top', { count: ranking.stocks.length })}</span>}>
      <div className="space-y-4 px-4 py-4 md:px-5">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 @xl:grid-cols-4">
          <Stat label={t('latest.decidedOn')}>{format.date(ranking.decided_on)}</Stat>
          <Stat label={t('latest.revenueMonth')}>{format.yearMonth(year, month)}</Stat>
          <Stat label={t('latest.next')}>
            {next.due ? t('latest.nextDue') : t('latest.nextAbout', { date: format.monthDay(next.on) })}
            <span className="block text-xs font-normal text-pretty whitespace-normal text-muted-foreground">
              {next.due ? t('latest.nextDueHint', { date: format.monthDay(next.on) }) : t('latest.nextRule', { day: decisionDay })}
            </span>
          </Stat>
          <Stat label={t('latest.scored')}>
            {t('stocks', { count: ranking.scored })}
            <span className="block text-xs font-normal text-muted-foreground">{t('latest.universe', { count: ranking.universe })}</span>
          </Stat>
        </dl>

        {ranking.stocks.length > 0 && (
          <div className="space-y-2 border-t pt-3 text-sm" data-testid="turnover">
            {previous.status === 'loading' && <p className="text-muted-foreground">{t('changes.loading')}</p>}
            {previous.status === 'failed' && <p className="text-muted-foreground">{t('changes.failed')}</p>}
            {previous.status === 'ready' && previous.ranking === null && <p className="text-muted-foreground">{t('changes.first')}</p>}
            {changed && previous.status === 'ready' && previous.ranking && (
              <>
                <p className="text-pretty">
                  {changed.entered.length + changed.left.length === 0
                    ? t('changes.same', { date: format.monthDay(previous.ranking.decided_on) })
                    : t('changes.summary', { date: format.monthDay(previous.ranking.decided_on), entered: changed.entered.length, left: changed.left.length, stayed: changed.stayed })}
                </p>
                {changed.left.length > 0 && (
                  <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                    <span className="text-xs text-muted-foreground">{t('changes.left')}</span>
                    <ul aria-label={t('changes.left')} className="contents">
                      {changed.left.map((stock) => (
                        <li key={stock.stock_id}>
                          <Link
                            to={paths.stock(stock.stock_id)}
                            className="inline-flex min-h-11 items-center gap-1 rounded-full border px-2.5 text-xs hover:border-primary/40 hover:text-brand focus-visible:text-brand md:min-h-6"
                          >
                            {stock.stock_name ?? stock.stock_id}
                            {stock.stock_name !== null && <span className="font-mono text-muted-foreground">{stock.stock_id}</span>}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div className="border-t">
        {ranking.stocks.length === 0 ? (
          <StateBlock icon={ListX} title={t('latest.none.title')} description={t('latest.none.description', { month: format.yearMonth(year, month) })} action={<BackfillCommand />} />
        ) : (
          <RankedStocksTable
            label={t('latest.title')}
            rows={ranking.stocks.map((stock) => ({ stock, mark: entered.has(stock.stock_id) ? ('entered' as const) : undefined }))}
          />
        )}
      </div>
    </Panel>
  )
}

/** The command that brings the daily history and the monthly revenue back, as the owner types it. */
export function BackfillCommand() {
  return <code className="rounded-md bg-muted px-2 py-1 font-mono text-xs">just backfill-history</code>
}
