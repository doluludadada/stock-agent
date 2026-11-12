import type { UseQueryResult } from '@tanstack/react-query'
import { CalendarX, DatabaseZap } from 'lucide-react'
import { lazy, Suspense, useMemo, useState, type FormEvent } from 'react'
import { useLocale, useTranslation } from '@/i18n'
import { isApiError } from '@/shared/api'
import { formatNumber, formatSigned, formatSignedPercent, useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Field } from '@/shared/ui/field'
import { Input } from '@/shared/ui/input'
import { Panel } from '@/shared/ui/panel'
import { ProgressNote } from '@/shared/ui/progress-note'
import { Segmented } from '@/shared/ui/segmented'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { BackfillCommand } from './LatestRanking'
import {
  DEFAULT_CHOICE,
  defaultScale,
  growthCurve,
  idleDecisions,
  logAxis,
  parsePeriod,
  PRESET_KEYS,
  spanOf,
  yearRows,
  type Period,
  type PeriodChoice,
  type RankingBacktest,
  type Scale,
  type YearRow,
} from './model'

const ComparisonChart = lazy(() => import('@/shared/ui/comparison-chart').then((module) => ({ default: module.ComparisonChart })))

interface RankingRecordProps {
  choice: PeriodChoice
  today: string
  onChoose: (choice: PeriodChoice) => void
  query: UseQueryResult<RankingBacktest>
}

/** Would following the ranking have beaten the benchmark: the period, the answer in a sentence and a small table, both curves, and every year. */
export function RankingRecord({ choice, today, onChoose, query }: RankingRecordProps) {
  const { t } = useTranslation('ranking')
  const backtest = query.data
  /** The period before stays on screen, dimmed, while the one chosen is computed. */
  const replacing = query.isPlaceholderData
  return (
    <div className="min-w-0 space-y-4 lg:space-y-5">
      <Panel title={backtest ? t('record.title', { benchmark: backtest.benchmark_id }) : t('record.titlePending')} description={t('record.question')}>
        <div className="space-y-4">
          <PeriodChooser key={JSON.stringify(choice)} choice={choice} today={today} shown={backtest && !replacing ? spanOf(backtest) : null} onChoose={onChoose} />
          {(query.isPending || replacing) && <Waiting />}
          {backtest ? (
            <div className={cn(replacing && 'opacity-50')} aria-busy={replacing}>
              <Verdict backtest={backtest} />
            </div>
          ) : query.isError ? (
            <Refusal error={query.error} onRetry={() => void query.refetch()} onAll={() => onChoose(DEFAULT_CHOICE)} />
          ) : (
            <Skeleton className="h-56 rounded-xl" />
          )}
        </div>
      </Panel>
      {backtest && (
        <div className={cn('space-y-4 lg:space-y-5', replacing && 'opacity-50')} aria-busy={replacing}>
          <CurvePanel key={`${backtest.first}:${backtest.last}`} backtest={backtest} />
          <YearsPanel backtest={backtest} />
        </div>
      )}
    </div>
  )
}

/** A replay takes seconds, and the first one after the server starts close to a minute: the seconds so far and why. */
export function Waiting() {
  const { t } = useTranslation('ranking')
  const [since] = useState(() => Date.now())
  return <ProgressNote since={since} title={(seconds) => t('waiting.title', { seconds })} hint={t('waiting.hint')} />
}

function Refusal({ error, onRetry, onAll }: { error: unknown; onRetry: () => void; onAll: () => void }) {
  const { t } = useTranslation('ranking')
  const code = isApiError(error) ? error.code : null
  if (code === 'backtest_period_unavailable') {
    return (
      <StateBlock
        icon={CalendarX}
        title={t('refusal.period.title')}
        description={t('refusal.period.description')}
        action={
          <Button type="button" variant="outline" size="sm" onClick={onAll}>
            {t('refusal.period.all')}
          </Button>
        }
      />
    )
  }
  if (code === 'ranking_unavailable') return <NoHistory />
  return <ErrorState error={error} title={t('record.loadFailed')} onRetry={onRetry} />
}

/** The daily history holds nothing to rank yet: what that means and the command that fills it. */
export function NoHistory({ className }: { className?: string }) {
  const { t } = useTranslation('ranking')
  return <StateBlock icon={DatabaseZap} title={t('noHistory.title')} description={t('noHistory.description')} action={<BackfillCommand />} className={className} />
}

interface PeriodChooserProps {
  choice: PeriodChoice
  today: string
  /** The sessions the backtest on screen covers, which start the custom fields; null while none shows. */
  shown: Period | null
  onChoose: (choice: PeriodChoice) => void
}

/** The quick periods, and two days of the reader's own: typing asks nothing, the button does. */
function PeriodChooser({ choice, today, shown, onChoose }: PeriodChooserProps) {
  const { t } = useTranslation('ranking')
  const [typed, setTyped] = useState<Period | null>(choice.kind === 'custom' ? choice.period : null)
  const [attempted, setAttempted] = useState(false)
  const draft = typed ?? { first: '', last: '' }
  const parsed = parsePeriod(draft, today)
  const problem = (field: keyof Period) => (attempted && !parsed.ok && parsed.problems[field] ? t(`problem.${parsed.problems[field]}`) : null)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setAttempted(true)
    if (parsed.ok) onChoose({ kind: 'custom', period: parsed.period })
  }
  return (
    <div className="space-y-3">
      <fieldset className="flex flex-wrap gap-1.5">
        <legend className="sr-only">{t('period.label')}</legend>
        {PRESET_KEYS.map((key) => {
          const chosen = choice.kind === 'preset' && choice.key === key
          return (
            <Button key={key} type="button" size="sm" variant={chosen ? 'secondary' : 'outline'} aria-pressed={chosen} onClick={() => (chosen ? setTyped(null) : onChoose({ kind: 'preset', key }))}>
              {t(`preset.${key}`)}
            </Button>
          )
        })}
        <Button
          type="button"
          size="sm"
          variant={choice.kind === 'custom' ? 'secondary' : 'outline'}
          aria-pressed={choice.kind === 'custom'}
          aria-expanded={typed !== null}
          onClick={() => setTyped(typed === null ? (shown ?? { first: '', last: today }) : choice.kind === 'custom' ? typed : null)}
        >
          {t('period.custom')}
        </Button>
      </fieldset>
      {typed !== null && (
        <form onSubmit={submit} noValidate className="grid grid-cols-2 items-start gap-3 @lg:grid-cols-[1fr_1fr_auto]">
          <Field label={t('period.first')} error={problem('first')}>
            <Input type="date" max={today} value={draft.first} onChange={(event) => setTyped({ ...draft, first: event.target.value })} />
          </Field>
          <Field label={t('period.last')} error={problem('last')}>
            <Input type="date" value={draft.last} onChange={(event) => setTyped({ ...draft, last: event.target.value })} />
          </Field>
          <Button type="submit" className="col-span-2 @lg:col-span-1 @lg:mt-[1.625rem]">
            {t('period.apply')}
          </Button>
        </form>
      )}
    </div>
  )
}

/** The answer first as a sentence, then the same three figures of both side by side, then what the figures leave out. */
function Verdict({ backtest }: { backtest: RankingBacktest }) {
  const { t } = useTranslation('ranking')
  const locale = useLocale()
  const format = useFormat()
  const span = spanOf(backtest)
  const idle = idleDecisions(backtest)
  const benchmark = backtest.benchmark_id
  const period = t('span', { first: format.date(span.first), last: format.date(span.last) })
  const percent = (ratio: number) => formatSignedPercent(locale, ratio, 1)
  const worth = (total: number) => t('record.worth', { value: formatNumber(locale, 1 + total, 1) })
  const rate = (fraction: number) => `${Number((fraction * 100).toFixed(4))}%`
  const [annual, benchmarkAnnual] = [backtest.annual_return, backtest.benchmark_annual_return]

  const side = annual === null || benchmarkAnnual === null ? null : annual > benchmarkAnnual ? 'ahead' : annual < benchmarkAnnual ? 'behind' : 'level'
  const headline =
    annual === null
      ? t('record.headline.short', { period })
      : benchmarkAnnual === null || side === null
        ? t('record.headline.alone', { period, annual: percent(annual) })
        : t(`record.headline.${side}`, { period, annual: percent(annual), benchmarkAnnual: percent(benchmarkAnnual), benchmark })

  const rows: { key: string; label: string; ranking: string; benchmark: string | null }[] = [
    { key: 'annual', label: t('record.row.annual'), ranking: annual === null ? '—' : percent(annual), benchmark: benchmarkAnnual === null ? null : percent(benchmarkAnnual) },
    { key: 'worth', label: t('record.row.worth'), ranking: worth(backtest.total_return), benchmark: backtest.benchmark_total_return === null ? null : worth(backtest.benchmark_total_return) },
    { key: 'drawdown', label: t('record.row.drawdown'), ranking: percent(-backtest.max_drawdown), benchmark: backtest.benchmark_max_drawdown === null ? null : percent(-backtest.benchmark_max_drawdown) },
  ]

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-title font-medium text-pretty" data-testid="headline">
        {headline}
      </p>
      <table aria-label={t('record.compare', { benchmark })} className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th scope="col">
              <span className="sr-only">{t('record.figure')}</span>
            </th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">
              {t('series.ranking')}
            </th>
            <th scope="col" className="py-1.5 pl-2 text-right font-medium">
              {benchmark}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b last:border-0">
              <th scope="row" className="py-2.5 pr-2 text-left font-normal text-muted-foreground">
                {row.label}
              </th>
              <td className="tabular px-2 py-2.5 text-right text-figure-sm font-semibold whitespace-nowrap">{row.ranking}</td>
              <td className="tabular py-2.5 pl-2 text-right text-figure-sm font-semibold whitespace-nowrap text-muted-foreground">{row.benchmark ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="space-y-1 text-xs text-pretty text-muted-foreground">
        <li>{t('record.costs', { costs: formatNumber(locale, backtest.costs * 100, 1), fee: rate(backtest.fee_rate), tax: rate(backtest.tax_rate) })}</li>
        {backtest.benchmark_total_return === null && <li>{t('record.noBenchmark', { benchmark })}</li>}
        {idle > 0 && <li>{t('record.idle', { count: idle })}</li>}
        <li>
          {t('record.caveat')}{' '}
          <a href="#ranking-caveats" className="text-brand underline-offset-4 hover:underline">
            {t('record.caveatLink')}
          </a>
        </li>
      </ul>
    </div>
  )
}

function CurvePanel({ backtest }: { backtest: RankingBacktest }) {
  const { t } = useTranslation('ranking')
  const locale = useLocale()
  const format = useFormat()
  const points = useMemo(() => growthCurve(backtest), [backtest])
  const [scale, setScale] = useState<Scale>(() => defaultScale(points))
  const axis = useMemo(() => logAxis(points), [points])
  const longSpan = points.length > 300
  const times = (value: number, digits: number) => t('times', { value: formatNumber(locale, value, digits) })
  return (
    <Panel
      title={t('curve.title', { benchmark: backtest.benchmark_id })}
      description={t('curve.question')}
      aside={
        <Segmented
          label={t('curve.scale')}
          value={scale}
          onChange={setScale}
          options={[
            { value: 'log', label: t('curve.log') },
            { value: 'linear', label: t('curve.linear') },
          ]}
        />
      }
    >
      <Suspense fallback={<Skeleton className="h-(--chart-price-height) rounded-xl" />}>
        <ComparisonChart
          data={points}
          valueLabel={t('series.ranking')}
          benchmarkLabel={backtest.benchmark_id}
          baseline={1}
          logAxis={scale === 'log' ? axis : undefined}
          formatValue={(value) => times(value, 2)}
          formatAxisValue={(value) => times(value, value < 10 && !Number.isInteger(value) ? 1 : 0)}
          formatAxisDate={longSpan ? (date) => date.slice(0, 7) : format.monthDay}
          formatTooltipDate={(date) => format.date(date, 'long')}
        />
      </Suspense>
      <p className="mt-3 text-xs text-pretty text-muted-foreground">{t(`curve.reading.${scale}`)}</p>
    </Panel>
  )
}

function YearsPanel({ backtest }: { backtest: RankingBacktest }) {
  const { t } = useTranslation('ranking')
  const locale = useLocale()
  const format = useFormat()
  const rows = useMemo(() => yearRows(backtest).reverse(), [backtest])
  const lostYears = rows.filter((row) => row.lost).length
  const behindYears = rows.filter((row) => row.behind).length
  const partial = (row: YearRow) => [row.from && t('years.from', { date: format.monthDay(row.from) }), row.to && t('years.to', { date: format.monthDay(row.to) })].filter(Boolean).join(' · ')

  const columns: Column<YearRow>[] = [
    {
      key: 'year',
      header: t('years.column.year'),
      className: 'w-full',
      cell: (row) => (
        <div className="min-w-0">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="tabular font-medium">{row.year}</span>
            {row.lost && (
              <Badge variant="outline" className="border-gold/50 text-gold">
                {t('years.lost')}
              </Badge>
            )}
            {row.behind && (
              <Badge variant="outline" className="font-normal">
                {t('years.behind', { benchmark: backtest.benchmark_id })}
              </Badge>
            )}
          </span>
          {(row.from || row.to) && <span className="block text-xs text-muted-foreground">{partial(row)}</span>}
        </div>
      ),
    },
    { key: 'ranking', header: t('series.ranking'), numeric: true, cell: (row) => <ChangeValue value={row.ranking} format="percent" fractionDigits={1} /> },
    { key: 'benchmark', header: backtest.benchmark_id, numeric: true, cell: (row) => (row.benchmark === null ? '—' : <ChangeValue value={row.benchmark} format="percent" fractionDigits={1} />) },
    {
      key: 'gap',
      header: t('years.column.gap'),
      numeric: true,
      from: 'sm',
      cell: (row) => (row.benchmark === null ? '—' : t('years.points', { value: formatSigned(locale, (row.ranking - row.benchmark) * 100, 1) })),
    },
  ]

  return (
    <Panel flush title={t('years.title')} description={t('years.question', { benchmark: backtest.benchmark_id })} aside={<span>{t('years.tally', { years: rows.length, lost: lostYears, behind: behindYears })}</span>}>
      <DataTable rows={rows} columns={columns} rowKey={(row) => String(row.year)} label={t('years.title')} />
    </Panel>
  )
}
