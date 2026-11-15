import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
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

/** A ranking's stocks, best first: each links to its page and reads the formula's factors, where each places it, and the score. */
export function RankedStocksTable({ rows, formula, label, id }: { rows: readonly RankedRow[]; formula: RankingFormula; label: string; id?: string }) {
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
        </StockLink>
      ),
    },
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
