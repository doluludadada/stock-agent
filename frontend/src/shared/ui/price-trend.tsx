import { LineChart } from 'lucide-react'
import { lazy, Suspense, useMemo, useState } from 'react'
import { useTranslation } from '@/i18n'
import type { DailyBar } from '@/shared/api'
import { DEFAULT_RANGE, pricePoints, summarize, type ChartRange } from '@/shared/lib/chart-range'
import { directionOf } from '@/shared/lib/direction'
import { useFormat } from '@/shared/lib/format'
import { ChangeValue } from './change-value'
import type { ChartOverlay } from './price-volume-chart'
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
  chartHeight?: { price: number; volume: number }
}

/** A daily series over a chosen range: the latest close and change, the price and volume charts, and the range's figures. */
export function PriceTrend({ bars, name, kind, overlays = [], chartHeight = { price: 260, volume: 64 } }: PriceTrendProps) {
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
  const rangeName = t(`range.${range}`)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="tabular text-3xl font-semibold tracking-tight">{level(summary.close)}</span>
          {summary.dayChange && (
            <span className="flex items-center gap-2">
              <ChangeValue value={summary.dayChange.value} format="absolute" arrow />
              <ChangeValue value={summary.dayChange.ratio} format="percent" pill />
              {summary.dayChange.basis === 'previousClose' && <span className="text-xs text-muted-foreground">{t('trend.vsPreviousClose')}</span>}
            </span>
          )}
          <span className="text-xs text-muted-foreground">{t('trend.asOf', { date: format.date(summary.date) })}</span>
        </div>
        <RangeTabs value={range} onChange={setRange} label={t('trend.range')} />
      </div>
      <Suspense fallback={<Skeleton className="rounded-lg" style={{ height: chartHeight.price + chartHeight.volume }} />}>
        <PriceVolumeChart
          data={data}
          direction={directionOf(summary.rangeChangeRatio)}
          valueLabel={t('trend.close', { name })}
          volumeLabel={kind === 'price' ? t('trend.volume') : t('trend.lastVolume')}
          overlays={overlays}
          formatValue={level}
          formatAxisValue={kind === 'price' ? (value) => format.number(value, value >= 100 ? 0 : 2) : level}
          priceHeight={chartHeight.price}
          volumeHeight={chartHeight.volume}
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
        <Stat label={t('trend.lastVolume')}>
          {kind === 'price' ? t('trend.volumeShares', { value: format.compact(summary.volume) }) : format.compact(summary.volume)}
        </Stat>
      </dl>
    </div>
  )
}
