import type { UseQueryResult } from '@tanstack/react-query'
import { useTranslation } from '@/i18n'
import { DASH, useFormat } from '@/shared/lib/format'
import type { RankingFormula } from '@/shared/lib/ranking-formula'
import { Badge } from '@/shared/ui/badge'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { FormulaLine } from '@/shared/ui/formula-line'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import type { FormulaEvidence } from './model'

interface EvidenceRow {
  key: string
  formula: RankingFormula
  active: boolean
  /** The floor the replay ranked above in place of the formula's own; null for the formula as defined. */
  floor: number | null
  record: FormulaEvidence['record']
}

/**
 * The evidence beside the choice of a formula: every formula the settings hold, replayed over the same period and
 * costs as the backtest above, as defined and again among the stocks that trade the comparison's floor a day.
 */
export function FormulaComparison({ query }: { query: UseQueryResult<FormulaEvidence[]> }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const percent = (ratio: number | null) => (ratio === null ? DASH : format.signedPercent(ratio, 1))
  const rows: EvidenceRow[] = (query.data ?? []).flatMap(({ formula, active, record, liquid_floor, liquid_record }) => [
    { key: formula.name, formula, active, floor: null, record },
    { key: `${formula.name}:liquid`, formula, active, floor: liquid_floor, record: liquid_record },
  ])
  const benchmark = query.data?.[0]?.record
  const ahead = ({ record }: EvidenceRow) => (record.years_ahead === null ? DASH : t('formulas.aheadOf', { ahead: record.years_ahead, years: Object.keys(record.yearly_returns).length }))
  const turnover = ({ record }: EvidenceRow) => (record.turnover === null ? DASH : format.percent(record.turnover, 0))

  const columns: Column<EvidenceRow>[] = [
    {
      key: 'formula',
      header: t('formulas.column.formula'),
      className: 'w-full min-w-40 py-2 whitespace-normal',
      cell: (row) =>
        row.floor === null ? (
          <span className="flex flex-col gap-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 font-medium text-pretty">
              <FormulaLine formula={row.formula} />
              {row.active && <Badge variant="outline">{t('formulas.active')}</Badge>}
            </span>
            <span className="text-xs text-muted-foreground sm:hidden">{t('formulas.phoneLine', { ahead: ahead(row), turnover: turnover(row) })}</span>
          </span>
        ) : (
          <span className="block pl-3 text-xs text-pretty text-muted-foreground">
            {t('formulas.liquid', { floor: format.compact(row.floor) })}
            <span className="sm:hidden"> · {t('formulas.phoneLine', { ahead: ahead(row), turnover: turnover(row) })}</span>
          </span>
        ),
    },
    { key: 'annual', header: t('formulas.column.annual'), numeric: true, cell: (row) => percent(row.record.annual_return) },
    { key: 'fall', header: t('formulas.column.fall'), numeric: true, cell: (row) => percent(-row.record.max_drawdown) },
    { key: 'ahead', header: t('formulas.column.ahead'), numeric: true, from: 'sm', cell: ahead },
    { key: 'turnover', header: t('formulas.column.turnover'), numeric: true, from: 'sm', cell: turnover },
  ]

  return (
    <Panel
      flush
      title={
        <>
          {t('formulas.title')}
          <Badge variant="outline" className="border-gold/50 font-normal text-gold">
            {t('record.simulated')}
          </Badge>
        </>
      }
      footer={
        <p className="px-2.5 py-1.5 text-xs text-pretty text-muted-foreground">
          {benchmark &&
            benchmark.benchmark_annual_return !== null &&
            benchmark.benchmark_max_drawdown !== null &&
            `${t('formulas.benchmark', { benchmark: benchmark.benchmark_id, annual: percent(benchmark.benchmark_annual_return), fall: percent(-benchmark.benchmark_max_drawdown) })} `}
          {t('formulas.note')}
        </p>
      }
    >
      {query.isError ? (
        <div className="p-4 md:p-5">
          <ErrorState error={query.error} title={t('formulas.loadFailed')} onRetry={() => void query.refetch()} />
        </div>
      ) : query.data ? (
        <DataTable rows={rows} columns={columns} rowKey={(row) => row.key} label={t('formulas.title')} className={query.isPlaceholderData ? 'opacity-50' : undefined} />
      ) : (
        <div className="p-4 md:p-5">
          <Skeleton className="h-40 rounded-xl" />
        </div>
      )}
    </Panel>
  )
}
