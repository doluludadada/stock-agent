import { LineChart } from 'lucide-react'
import { lazy, Suspense, useMemo, useState } from 'react'
import { useTranslation } from '@/i18n'
import type { DailyBar } from '@/shared/api'
import { DEFAULT_RANGE, pricePoints, summarize, type ChartRange } from '@/shared/lib/chart-range'
import { directionOf, type Direction } from '@/shared/lib/direction'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { ChangeValue } from './change-value'
import type { ChartOverlay } from './price-volume-chart'
import { QuoteHeadline } from './quote-headline'
import { RangeTabs } from './range-tabs'
import { Skeleton } from './skeleton'
import { Stat } from './stat'
import { StateBlock } from './state-block'

const PriceVolumeChart = lazy(() => import('./price-volume-chart').then((module) => ({ default: module.PriceVolumeChart })))

/** A line drawn over the price, with its value at each session (YYYY-MM-DD in Taipei). */
export interface TrendOverlay extends ChartOverlay {
  values: ReadonlyMap<string, number | null>
}

interface PriceTrendProps {
  bars: readonly DailyBar[]
  /** The series' name, for the tooltip and the screen-reader summary. */
  name: string
  /** An index level keeps two decimals at any size, and its volume is not counted in shares. */
  kind: 'price' | 'index'
  overlays?: readonly TrendOverlay[]
  /** The close and its change above the chart; a page that shows them in its header turns them off. */
  quote?: boolean
}

/** A daily series over a chosen range: the latest close and change, the price and volume charts, and the range's figures. */
export function PriceTrend({ bars, name, kind, overlays = [], quote = true }: PriceTrendProps) {
  const { t } = useTranslation()
  const format = useFormat()
  const [range, setRange] = useState<ChartRange>(DEFAULT_RANGE)
  const summary = useMemo(() => summarize(bars, range), [bars, range])
  const data = useMemo(
    () => pricePoints(bars, range).map((point) => ({ ...point, ...Object.fromEntries(overlays.map((overlay) => [overlay.key, overlay.values.get(point.date) ?? null])) })),
    [bars, range, overlays],
  )
  if (!summary) return <StateBlock icon={LineChart} title={t('trend.empty')} />

  const level = (value: number) => (kind === 'index' ? format.number(value, 2) : format.price(value))
  const volume = kind === 'index' ? format.compact : format.lots
  const rangeName = t(`range.${range}`)
  const asOf = summary.dayChange?.basis === 'previousClose' ? `${format.closeOn(summary.date)} · ${t('trend.vsPreviousClose')}` : format.closeOn(summary.date)
  const direction = directionOf(summary.rangeChangeRatio)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        {quote ? (
          <QuoteHeadline value={level(summary.close)} change={summary.dayChange?.value ?? null} changeRatio={summary.dayChange?.ratio ?? null} asOf={asOf} />
        ) : (
          <Legend direction={direction} close={t('trend.close', { name })} overlays={overlays} />
        )}
        <RangeTabs value={range} onChange={setRange} label={t('trend.range')} />
      </div>
      {quote && overlays.length > 0 && <Legend direction={direction} close={t('trend.close', { name })} overlays={overlays} />}
      <Suspense fallback={<Skeleton className="h-[calc(var(--chart-price-height)+var(--chart-volume-height))] rounded-lg" />}>
        <PriceVolumeChart
          data={data}
          direction={direction}
          valueLabel={t('trend.close', { name })}
          volumeLabel={t('trend.lastVolume')}
          overlays={overlays}
          formatValue={level}
          formatAxisValue={(value) => format.number(value, value >= 100 ? 0 : 2)}
          formatVolume={volume}
        />
      </Suspense>
      <p className="sr-only" aria-live="polite">
        {t('trend.summary', { name, range: rangeName, change: format.number(summary.rangeChangeRatio * 100, 2) })}
      </p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t pt-3 sm:grid-cols-4">
        <Stat label={t('trend.rangeChange', { range: rangeName })}>
          <ChangeValue value={summary.rangeChangeRatio} format="percent" />
        </Stat>
        <Stat label={t('trend.rangeHigh')}>{level(summary.rangeHigh)}</Stat>
        <Stat label={t('trend.rangeLow')}>{level(summary.rangeLow)}</Stat>
        <Stat label={t('trend.lastVolume')}>{volume(summary.volume)}</Stat>
      </dl>
    </div>
  )
}

const LINE_COLOR: Record<Direction, string> = { up: 'bg-up', down: 'bg-down', flat: 'bg-chart-1' }

/** What each line is: the close in the range's market color, and each moving average in its own color. */
function Legend({ direction, close, overlays }: { direction: Direction; close: string; overlays: readonly TrendOverlay[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <li className="flex items-center gap-1.5">
        <span aria-hidden className={cn('h-0.5 w-4 rounded-full', LINE_COLOR[direction])} />
        {close}
      </li>
      {overlays.map((overlay) => (
        <li key={overlay.key} className="flex items-center gap-1.5">
          <span aria-hidden className="h-0.5 w-4 rounded-full" style={{ background: `var(${overlay.colorVar})` }} />
          {overlay.label}
        </li>
      ))}
    </ul>
  )
}
