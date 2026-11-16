import { useTranslation } from '@/i18n'
import type { Loadable, StockQuote } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { ChangeValue } from '@/shared/ui/change-value'
import { QuoteTime } from '@/shared/ui/quote-time'
import { StockLink } from '@/shared/ui/stock-name'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { useFormulaWords, type RankingFormula } from '@/shared/lib/ranking-formula'
import type { RankedStock } from './model'

export type StockMark = 'entered' | 'notBought'

export interface RankedRow {
  stock: RankedStock
  mark?: StockMark
  /** The row's own classes, such as hiding it on a narrow screen. */
  className?: string
}

const MARK_TONE: Record<StockMark, string> = { entered: 'border-primary/40 text-primary', notBought: 'border-gold/50 text-gold' }

interface RankedStocksTableProps {
  rows: readonly RankedRow[]
  formula: RankingFormula
  label: string
  id?: string
  /** Each stock's latest price, where the list is the one to hold now: a past decision's list shows none. */
  quotes?: ReadonlyMap<string, Loadable<StockQuote>>
  /** A session trades, so the quotes among them still change. */
  live?: boolean
}

/** The price with the day's change beside it and, under them, when it is from; nothing until it has loaded. */
function Price({ state, live, className }: { state: Loadable<StockQuote> | undefined; live: boolean; className?: string }) {
  const format = useFormat()
  if (state?.status !== 'ready') return null
  const quote = state.value
  return (
    <span className={className}>
      <span className="inline-flex items-baseline gap-1.5">
        <span className="font-semibold text-foreground">{format.price(quote.close)}</span>
        {quote.changeRatio !== null && <ChangeValue value={quote.changeRatio} format="percent" />}
      </span>
      <QuoteTime session={quote.session} tradedAt={quote.tradedAt} live={live} className="block text-xs font-normal text-muted-foreground" />
    </span>
  )
}

/**
 * A ranking's stocks, best first: each links to its page and reads the formula's factors, where each places it, and
 * the score; with `quotes`, also its latest price and the day's change, today's quote while a session trades.
 */
export function RankedStocksTable({ rows, formula, label, id, quotes, live = false }: RankedStocksTableProps) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const words = useFormulaWords()

  const columns: Column<RankedRow>[] = [
    { key: 'place', header: t('table.place'), quietHeader: true, numeric: true, className: 'w-8 text-muted-foreground', cell: (_, index) => index + 1 },
    {
      key: 'stock',
      header: t('table.stock'),
      className: 'w-full max-w-0 min-w-36',
      cell: ({ stock, mark }) => (
        <StockLink
          stockId={stock.stock_id}
          name={stock.stock_name}
          badge={
            mark && (
              <Badge variant="outline" className={MARK_TONE[mark]}>
                {t(`mark.${mark}`)}
              </Badge>
            )
          }
        >
          <span className="tabular truncate text-xs text-muted-foreground sm:hidden">
            {formula.factors.map((factor, index) => words.phrase(factor, stock.factors[index]!.value)).join(' · ')}
          </span>
          {quotes && <Price state={quotes.get(stock.stock_id)} live={live} className="tabular flex flex-wrap items-baseline gap-x-2 text-xs md:hidden [&>span:last-child]:inline" />}
        </StockLink>
      ),
    },
    ...(quotes
      ? [{ key: 'price', header: t('table.price'), numeric: true, from: 'md', cell: ({ stock }) => <Price state={quotes.get(stock.stock_id)} live={live} /> } satisfies Column<RankedRow>]
      : []),
    ...formula.factors.map(
      (factor, index): Column<RankedRow> => ({
        key: `factor-${index}`,
        header: words.label(factor),
        numeric: true,
        from: 'sm',
        cell: ({ stock }) => (
          <>
            {words.value(factor, stock.factors[index]!.value)}
            <span className="block text-xs font-normal text-muted-foreground">{t('factor.beats', { share: format.number(stock.factors[index]!.rank * 100, 1) })}</span>
          </>
        ),
      }),
    ),
    { key: 'score', header: t('table.score'), numeric: true, from: 'lg', cell: ({ stock }) => format.number(stock.score, 2) },
  ]

  return <DataTable id={id} rows={rows} columns={columns} rowKey={(row) => row.stock.stock_id} rowClassName={(row) => row.className} label={label} />
}
