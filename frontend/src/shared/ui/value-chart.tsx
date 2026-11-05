import { useId } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'
import type { Direction } from '@/shared/lib/direction'
import { cn } from '@/shared/lib/utils'

export interface ValuePoint {
  date: string
  value: number
}

interface ValueChartProps {
  data: readonly ValuePoint[]
  direction: Direction
  /** The series' name in the tooltip; the panel's title names the chart. */
  label: string
  formatValue: (value: number) => string
  formatAxisValue?: (value: number) => string
  formatAxisDate: (date: string) => string
  formatTooltipDate: (date: string) => string
  className?: string
}

const STROKE = { up: 'var(--chart-up)', down: 'var(--chart-down)', flat: 'var(--chart-price)' } as const

/** One series over time, such as an account's daily equity, with a crosshair that reads any day; its height is a token. */
export function ValueChart({ data, direction, label, formatValue, formatAxisValue = formatValue, formatAxisDate, formatTooltipDate, className }: ValueChartProps) {
  const gradientId = `${useId()}-fill`.replaceAll(':', '')
  const stroke = STROKE[direction]
  const rows = data as ValuePoint[]

  const tooltip = (props: TooltipContentProps<ValueType, NameType>) => {
    const point = props.payload?.[0]?.payload as ValuePoint | undefined
    if (!props.active || !point) return null
    return (
      <div className="min-w-40 rounded-lg border bg-popover px-3 py-2 text-xs shadow-pop">
        <div className="mb-1 font-medium text-foreground">{formatTooltipDate(point.date)}</div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">{label}</span>
          <span className="tabular font-medium text-foreground">{formatValue(point.value)}</span>
        </div>
      </div>
    )
  }

  return (
    <div aria-hidden className={cn('h-(--chart-price-height) w-full', className)}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 8, right: 0, bottom: 0, left: 16 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis
            dataKey="date"
            tickFormatter={formatAxisDate}
            tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={32}
          />
          <YAxis orientation="right" domain={['auto', 'auto']} tickFormatter={formatAxisValue} tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} axisLine={false} tickLine={false} width={56} tickCount={4} />
          <Tooltip content={tooltip} cursor={{ stroke: 'var(--chart-axis)', strokeDasharray: '3 3' }} isAnimationActive={false} />
          <Area type="monotone" dataKey="value" stroke={stroke} strokeWidth={2} fill={`url(#${gradientId})`} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
