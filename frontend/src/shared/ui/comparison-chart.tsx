import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'

/** One session of the two lines; the benchmark is null on a session it has no value for. */
export interface ComparisonPoint {
  date: string
  value: number
  benchmark: number | null
}

interface ComparisonChartProps {
  data: readonly ComparisonPoint[]
  valueLabel: string
  benchmarkLabel: string
  /** The value both lines start from, drawn as a line: 0 for returns, 1 for what 1 put in is worth. */
  baseline: number
  /** A log axis with its bounds and ticks; a linear axis that fits the values without it. */
  logAxis?: { domain: [number, number]; ticks: number[] }
  formatValue: (value: number) => string
  formatAxisValue: (value: number) => string
  formatAxisDate: (date: string) => string
  formatTooltipDate: (date: string) => string
}

const VALUE = 'var(--chart-price)'
const BENCHMARK = 'var(--chart-benchmark)'
/** The benchmark is also dashed, so the two lines differ by more than their color. */
const BENCHMARK_DASH = '5 4'

function Swatch({ color, dashed = false }: { color: string; dashed?: boolean }) {
  return (
    <svg aria-hidden viewBox="0 0 18 4" className="h-1 w-4.5 shrink-0">
      <line x1="0" x2="18" y1="2" y2="2" stroke={color} strokeWidth="2" strokeDasharray={dashed ? BENCHMARK_DASH : undefined} />
    </svg>
  )
}

/**
 * A result and its benchmark from the same start on one axis, never two. The legend carries each line's last value,
 * and the crosshair reads any session.
 */
export function ComparisonChart({ data, valueLabel, benchmarkLabel, baseline, logAxis, formatValue, formatAxisValue, formatAxisDate, formatTooltipDate }: ComparisonChartProps) {
  const last = data.at(-1)
  const lastBenchmark = data.findLast((point) => point.benchmark !== null)?.benchmark ?? null

  const tooltip = (props: TooltipContentProps<ValueType, NameType>) => {
    const point = props.payload?.[0]?.payload as ComparisonPoint | undefined
    if (!props.active || !point) return null
    return (
      <div className="min-w-44 space-y-1 rounded-lg border bg-popover px-3 py-2 text-xs shadow-pop">
        <div className="font-medium text-foreground">{formatTooltipDate(point.date)}</div>
        <div className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <Swatch color={VALUE} />
            {valueLabel}
          </span>
          <span className="tabular font-medium text-foreground">{formatValue(point.value)}</span>
        </div>
        {point.benchmark !== null && (
          <div className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Swatch color={BENCHMARK} dashed />
              {benchmarkLabel}
            </span>
            <span className="tabular font-medium text-foreground">{formatValue(point.benchmark)}</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
        <li className="flex items-center gap-1.5">
          <Swatch color={VALUE} />
          <span className="text-muted-foreground">{valueLabel}</span>
          {last && <span className="tabular font-medium">{formatValue(last.value)}</span>}
        </li>
        {lastBenchmark !== null && (
          <li className="flex items-center gap-1.5">
            <Swatch color={BENCHMARK} dashed />
            <span className="text-muted-foreground">{benchmarkLabel}</span>
            <span className="tabular font-medium">{formatValue(lastBenchmark)}</span>
          </li>
        )}
      </ul>
      <div aria-hidden className="h-(--chart-price-height) w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data as ComparisonPoint[]} margin={{ top: 8, right: 0, bottom: 0, left: 16 }}>
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey="date" tickFormatter={formatAxisDate} tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={32} />
            <YAxis
              orientation="right"
              scale={logAxis ? 'log' : 'auto'}
              domain={logAxis?.domain ?? ['auto', 'auto']}
              ticks={logAxis?.ticks}
              tickFormatter={formatAxisValue}
              tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={56}
              tickCount={5}
            />
            <ReferenceLine y={baseline} stroke="var(--chart-axis)" strokeOpacity={0.6} />
            <Tooltip content={tooltip} cursor={{ stroke: 'var(--chart-axis)', strokeDasharray: '3 3' }} isAnimationActive={false} />
            <Line type="monotone" dataKey="benchmark" stroke={BENCHMARK} strokeWidth={2} strokeDasharray={BENCHMARK_DASH} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} connectNulls isAnimationActive={false} />
            <Line type="monotone" dataKey="value" stroke={VALUE} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
