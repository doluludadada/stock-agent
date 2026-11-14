import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { StockLink } from '@/shared/ui/stock-name'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { nearnessOf, type RankedStock } from './model'

export type StockMark = 'entered' | 'notBought'

export interface RankedRow {
  stock: RankedStock
  mark?: StockMark
  /** The row's own classes, such as hiding it on a narrow screen. */
  className?: string
}

const MARK_TONE: Record<StockMark, string> = { entered: 'border-primary/40 text-primary', notBought: 'border-gold/50 text-gold' }

/** The two factors in the reader's words: how many times the recent revenue is of its year's average, and how far the price is from its year's high. */
function useFactorWords() {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  return {
    revenue: (stock: RankedStock) => t('times', { value: format.number(stock.revenue_acceleration, 2) }),
    high: (stock: RankedStock) => {
      const nearness = nearnessOf(stock)
      return nearness.atHigh ? t('factor.atHigh') : format.signedPercent(-nearness.below, 1)
    },
    /** The same as a phrase that stands without its column header. */
    highLine: (stock: RankedStock) => {
      const nearness = nearnessOf(stock)
      return nearness.atHigh ? t('factor.atHigh') : t('factor.below', { value: format.signedPercent(-nearness.below, 1) })
    },
    beats: (rank: number) => t('factor.beats', { share: format.number(rank * 100, 1) }),
  }
}

/** A ranking's stocks, best first: each links to its page and reads its two factors, where each places it, and the score. */
export function RankedStocksTable({ rows, label, id }: { rows: readonly RankedRow[]; label: string; id?: string }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const words = useFactorWords()
  const factor = (value: string, rank: number) => (
    <>
      {value}
      <span className="block text-xs font-normal text-muted-foreground">{words.beats(rank)}</span>
    </>
  )

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
          <span className="tabular truncate text-xs text-muted-foreground sm:hidden">{t('table.line', { revenue: words.revenue(stock), high: words.highLine(stock) })}</span>
        </StockLink>
      ),
    },
    { key: 'revenue', header: t('table.revenue'), numeric: true, from: 'sm', cell: ({ stock }) => factor(words.revenue(stock), stock.acceleration_rank) },
    { key: 'high', header: t('table.high'), numeric: true, from: 'sm', cell: ({ stock }) => factor(words.high(stock), stock.nearness_rank) },
    { key: 'score', header: t('table.score'), numeric: true, from: 'lg', cell: ({ stock }) => format.number(stock.score, 2) },
  ]

  return <DataTable id={id} rows={rows} columns={columns} rowKey={(row) => row.stock.stock_id} rowClassName={(row) => row.className} label={label} />
}
