import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { formatNumber, formatSignedPercent } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
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
  const locale = useLocale()
  return {
    revenue: (stock: RankedStock) => t('times', { value: formatNumber(locale, stock.revenue_acceleration, 2) }),
    high: (stock: RankedStock) => {
      const nearness = nearnessOf(stock)
      return nearness.atHigh ? t('factor.atHigh') : formatSignedPercent(locale, -nearness.below, 1)
    },
    /** The same as a phrase that stands without its column header. */
    highLine: (stock: RankedStock) => {
      const nearness = nearnessOf(stock)
      return nearness.atHigh ? t('factor.atHigh') : t('factor.below', { value: formatSignedPercent(locale, -nearness.below, 1) })
    },
    beats: (rank: number) => t('factor.beats', { share: formatNumber(locale, rank * 100, 1) }),
  }
}

/** A ranking's stocks, best first: each links to its page and reads its two factors, where each places it, and the score. */
export function RankedStocksTable({ rows, label, id }: { rows: readonly RankedRow[]; label: string; id?: string }) {
  const { t } = useTranslation('ranking')
  const locale = useLocale()
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
        <Link to={paths.stock(stock.stock_id)} className="stretched-link flex min-h-11 min-w-0 flex-col justify-center hover:text-brand focus-visible:text-brand md:min-h-0">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate font-medium">{stock.stock_name ?? stock.stock_id}</span>
            {stock.stock_name !== null && <span className="shrink-0 font-mono text-xs text-muted-foreground">{stock.stock_id}</span>}
            {mark && (
              <Badge variant="outline" className={MARK_TONE[mark]}>
                {t(`mark.${mark}`)}
              </Badge>
            )}
          </span>
          <span className="tabular truncate text-xs text-muted-foreground sm:hidden">{t('table.line', { revenue: words.revenue(stock), high: words.highLine(stock) })}</span>
        </Link>
      ),
    },
    { key: 'revenue', header: t('table.revenue'), numeric: true, from: 'sm', cell: ({ stock }) => factor(words.revenue(stock), stock.acceleration_rank) },
    { key: 'high', header: t('table.high'), numeric: true, from: 'sm', cell: ({ stock }) => factor(words.high(stock), stock.nearness_rank) },
    { key: 'score', header: t('table.score'), numeric: true, from: 'lg', cell: ({ stock }) => formatNumber(locale, stock.score, 2) },
  ]

  return <DataTable id={id} rows={rows} columns={columns} rowKey={(row) => row.stock.stock_id} rowClassName={(row) => row.className} label={label} />
}
