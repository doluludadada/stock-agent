import { ChevronDown, ListX, Wallet } from 'lucide-react'
import { useId, useState } from 'react'
import { useTranslation } from '@/i18n'
import { useHasPermission } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { FormulaLine } from '@/shared/ui/formula-line'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { Panel } from '@/shared/ui/panel'
import { StateBlock } from '@/shared/ui/state-block'
import { StockChip } from '@/shared/ui/stock-name'
import { nextDecision, turnover, type Ranking, type Turnover } from './model'
import { RankedStocksTable } from './RankedStocksTable'

/** The ranking of the month before: still asked for, not answered, or answered; null when the history holds none before. */
export type PreviousRanking = { status: 'loading' } | { status: 'failed' } | { status: 'ready'; ranking: Ranking | null }

interface LatestRankingProps {
  ranking: Ranking
  previous: PreviousRanking
  /** The day of the month the ranking decides on or after. */
  decisionDay: number
  today: string
  className?: string
}

/** The month's stocks in order, under the decision they come from; what changed and when the next one is due sit below them. */
export function LatestRanking({ ranking, previous, decisionDay, today, className }: LatestRankingProps) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const next = nextDecision(ranking.decided_on, decisionDay, today)
  const changed = previous.status === 'ready' && previous.ranking ? turnover(previous.ranking, ranking) : null
  const entered = new Set(changed?.entered.map((stock) => stock.stock_id))
  const [year, month] = ranking.revenue_month.split('-').map(Number) as [number, number]
  const revenueMonth = format.yearMonth(year, month)

  return (
    <Panel
      flush
      className={className}
      title={t('latest.title')}
      description={<FormulaLine formula={ranking.formula} />}
      aside={<span className="tabular">{t('latest.decided', { date: format.date(ranking.decided_on), month: revenueMonth })}</span>}
      footer={
        (ranking.stocks.length > 0 || ranking.holds_cash) && (
          <div className="space-y-1 px-2.5 py-1.5 text-xs text-muted-foreground">
            <div className="flex flex-wrap items-center justify-between gap-x-4">
              <span>{next.due ? t('latest.nextDue') : t('latest.nextAbout', { date: format.monthDay(next.on) })}</span>
              {changed && <LeftStocks changed={changed} />}
            </div>
            <NotAdviceNote />
          </div>
        )
      }
    >
      {ranking.holds_cash ? (
        <HoldsCash ranking={ranking} />
      ) : ranking.stocks.length === 0 ? (
        <StateBlock icon={ListX} title={t('latest.none.title')} description={t('latest.none.description', { month: revenueMonth })} action={<BackfillCommand />} />
      ) : (
        <RankedStocksTable
          label={t('latest.title')}
          formula={ranking.formula}
          rows={ranking.stocks.map((stock) => ({ stock, mark: entered.has(stock.stock_id) ? ('entered' as const) : undefined }))}
        />
      )}
    </Panel>
  )
}

/** The formula's market filter is on: it holds no stock this month, said plainly where the list would be. */
export function HoldsCash({ ranking }: { ranking: Ranking }) {
  const { t } = useTranslation('ranking')
  return (
    <StateBlock icon={Wallet} title={t('latest.cash.title')} description={t('latest.cash.description', { sessions: ranking.formula.cash_under_average_sessions, scored: ranking.scored })} />
  )
}

/** How many stocks the decision brought in and dropped; the dropped ones, which the list no longer shows, open on a tap. */
function LeftStocks({ changed }: { changed: Turnover }) {
  const { t } = useTranslation('ranking')
  const [open, setOpen] = useState(false)
  const listId = useId()
  const summary = t('changes.summary', { entered: changed.entered.length, left: changed.left.length })
  if (changed.left.length === 0) return <span data-testid="turnover">{summary}</span>
  return (
    <>
      <button type="button" data-testid="turnover" aria-expanded={open} aria-controls={listId} onClick={() => setOpen(!open)} className="tap gap-1 rounded-md hover:text-foreground">
        {summary}
        <ChevronDown aria-hidden className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
      </button>
      <ul id={listId} hidden={!open} aria-label={t('changes.left')} className="flex w-full flex-wrap gap-1.5 pb-1">
        {changed.left.map((stock) => (
          <li key={stock.stock_id}>
            <StockChip stockId={stock.stock_id} name={stock.stock_name} />
          </li>
        ))}
      </ul>
    </>
  )
}

/** The command that brings the history back, as the operator types it on the server. Anyone else can do nothing with it. */
export function BackfillCommand() {
  const { t } = useTranslation('ranking')
  if (!useHasPermission('see_administrator_features')) return <p className="text-sm text-muted-foreground">{t('backfill.visitor')}</p>
  return <code className="inline-block rounded-md bg-muted px-2 py-1 font-mono text-xs text-foreground">just backfill-history</code>
}
