import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'
import type { ReturnPoint } from './model'

interface ReturnChartProps {
  data: readonly ReturnPoint[]
  strategyLabel: string
  benchmarkLabel: string
  formatReturn: (ratio: number) => string
  formatAxisReturn: (ratio: number) => string
  formatAxisDate: (date: string) => string
  formatTooltipDate: (date: string) => string
}

const STRATEGY = 'var(--chart-price)'
const BENCHMARK = 'var(--chart-benchmark)'
/** The index is also dashed, so the two lines differ by more than their color. */
const BENCHMARK_DASH = '5 4'

function Swatch({ color, dashed = false }: { color: string; dashed?: boolean }) {
  return (
    <svg aria-hidden viewBox="0 0 18 4" className="h-1 w-4.5 shrink-0">
      <line x1="0" x2="18" y1="2" y2="2" stroke={color} strokeWidth="2" strokeDasharray={dashed ? BENCHMARK_DASH : undefined} />
    </svg>
  )
}

/**
 * The strategy's account and the TAIEX as returns since the first session, on one axis that crosses zero. The legend
 * carries each line's final return, and the crosshair reads any session.
 */
export function ReturnChart({ data, strategyLabel, benchmarkLabel, formatReturn, formatAxisReturn, formatAxisDate, formatTooltipDate }: ReturnChartProps) {
  const last = data.at(-1)
  const lastBenchmark = data.findLast((point) => point.benchmark !== null)?.benchmark ?? null

  const tooltip = (props: TooltipContentProps<ValueType, NameType>) => {
    const point = props.payload?.[0]?.payload as ReturnPoint | undefined
    if (!props.active || !point) return null
    return (
      <div className="min-w-44 space-y-1 rounded-lg border bg-popover px-3 py-2 text-xs shadow-pop">
        <div className="font-medium text-foreground">{formatTooltipDate(point.date)}</div>
        <div className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <Swatch color={STRATEGY} />
            {strategyLabel}
          </span>
          <span className="tabular font-medium text-foreground">{formatReturn(point.strategy)}</span>
        </div>
        {point.benchmark !== null && (
          <div className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Swatch color={BENCHMARK} dashed />
              {benchmarkLabel}
            </span>
            <span className="tabular font-medium text-foreground">{formatReturn(point.benchmark)}</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
        <li className="flex items-center gap-1.5">
          <Swatch color={STRATEGY} />
          <span className="text-muted-foreground">{strategyLabel}</span>
          {last && <span className="tabular font-medium">{formatReturn(last.strategy)}</span>}
        </li>
        {lastBenchmark !== null && (
          <li className="flex items-center gap-1.5">
            <Swatch color={BENCHMARK} dashed />
            <span className="text-muted-foreground">{benchmarkLabel}</span>
            <span className="tabular font-medium">{formatReturn(lastBenchmark)}</span>
          </li>
        )}
      </ul>
      <div aria-hidden className="h-(--chart-price-height) w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data as ReturnPoint[]} margin={{ top: 8, right: 0, bottom: 0, left: 16 }}>
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey="date" tickFormatter={formatAxisDate} tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={32} />
            <YAxis orientation="right" domain={['auto', 'auto']} tickFormatter={formatAxisReturn} tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} axisLine={false} tickLine={false} width={56} tickCount={5} />
            <ReferenceLine y={0} stroke="var(--chart-axis)" strokeOpacity={0.6} />
            <Tooltip content={tooltip} cursor={{ stroke: 'var(--chart-axis)', strokeDasharray: '3 3' }} isAnimationActive={false} />
            <Line type="monotone" dataKey="benchmark" stroke={BENCHMARK} strokeWidth={2} strokeDasharray={BENCHMARK_DASH} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} connectNulls isAnimationActive={false} />
            <Line type="monotone" dataKey="strategy" stroke={STRATEGY} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)' }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
