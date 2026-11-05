import { useId } from 'react'
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'
import type { PricePoint } from '@/shared/lib/chart-range'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'

export interface ChartOverlay {
  key: string
  label: string
  /** A chart role from globals.css, e.g. `--chart-ma-fast`. */
  colorVar: `--chart-${string}`
}

interface PriceVolumeChartProps {
  data: readonly PricePoint[]
  direction: 'up' | 'down' | 'flat'
  valueLabel: string
  volumeLabel: string
  overlays?: readonly ChartOverlay[]
  formatValue: (value: number) => string
  /** Axis ticks are coarser than tooltip values; defaults to formatValue. */
  formatAxisValue?: (value: number) => string
  /** A stock's volume reads in lots; an index's as the source gives it. */
  formatVolume: (value: number) => string
  className?: string
}

const directionColor = { up: 'var(--chart-up)', down: 'var(--chart-down)', flat: 'var(--chart-price)' } as const

/**
 * Price on top and volume underneath as two synced charts sharing the date axis, never one chart
 * with two y-scales. Colors come from the chart roles in globals.css; heights from the chart sizes in tokens.css.
 */
export function PriceVolumeChart({
  data,
  direction,
  valueLabel,
  volumeLabel,
  overlays = [],
  formatValue,
  formatAxisValue = formatValue,
  formatVolume,
  className,
}: PriceVolumeChartProps) {
  const format = useFormat()
  const syncId = useId()
  const gradientId = `${syncId}-fill`.replaceAll(':', '')
  const stroke = directionColor[direction]
  const rows = data as PricePoint[]

  const tooltip = (props: TooltipContentProps<ValueType, NameType>) => {
    const point = props.payload?.[0]?.payload as PricePoint | undefined
    if (!props.active || !point) return null
    return (
      <div className="min-w-44 rounded-lg border bg-popover px-3 py-2 text-xs shadow-pop">
        <div className="mb-1.5 font-medium text-foreground">{format.date(point.date, 'long')}</div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt className="text-muted-foreground">{valueLabel}</dt>
          <dd className="tabular text-right font-medium text-foreground">{formatValue(point.value)}</dd>
          {overlays.map((overlay) => {
            const value = point[overlay.key]
            return (
              <div key={overlay.key} className="contents">
                <dt className="flex items-center gap-1.5 text-muted-foreground">
                  <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: `var(${overlay.colorVar})` }} />
                  {overlay.label}
                </dt>
                <dd className="tabular text-right text-foreground">{typeof value === 'number' ? formatValue(value) : '—'}</dd>
              </div>
            )
          })}
          <dt className="text-muted-foreground">{volumeLabel}</dt>
          <dd className="tabular text-right text-foreground">{formatVolume(point.volume)}</dd>
        </dl>
      </div>
    )
  }

  const tickInterval = Math.max(1, Math.floor(rows.length / 6))

  return (
    <div className={cn('w-full', className)}>
      <div className="h-(--chart-price-height)" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} syncId={syncId} margin={{ top: 8, right: 0, bottom: 0, left: 16 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.24} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey="date" hide />
            <YAxis
              orientation="right"
              domain={['auto', 'auto']}
              tickFormatter={formatAxisValue}
              tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={56}
              tickCount={5}
            />
            <Tooltip
              content={tooltip}
              cursor={{ stroke: 'var(--chart-axis)', strokeDasharray: '3 3' }}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke={stroke}
              strokeWidth={2}
              fill={`url(#${gradientId})`}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }}
              isAnimationActive={false}
            />
            {overlays.map((overlay) => (
              <Line
                key={overlay.key}
                type="monotone"
                dataKey={overlay.key}
                stroke={`var(${overlay.colorVar})`}
                strokeWidth={1.5}
                dot={false}
                activeDot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 h-(--chart-volume-height)" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} syncId={syncId} margin={{ top: 4, right: 0, bottom: 0, left: 16 }} barCategoryGap={1}>
            <XAxis
              dataKey="date"
              tickFormatter={format.monthDay}
              tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              interval={tickInterval}
              minTickGap={24}
            />
            <YAxis
              orientation="right"
              tickFormatter={(value: number) => (value === 0 ? '' : formatVolume(value))}
              tick={{ fill: 'var(--chart-axis)', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={56}
              tickCount={2}
            />
            <Tooltip content={() => null} cursor={{ fill: 'var(--chart-grid)' }} isAnimationActive={false} />
            <Bar dataKey="volume" radius={[1, 1, 0, 0]} isAnimationActive={false}>
              {rows.map((point) => (
                <Cell key={point.date} fill={point.up ? 'var(--chart-up)' : 'var(--chart-down)'} fillOpacity={0.45} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
