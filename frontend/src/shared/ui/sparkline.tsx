import { useId } from 'react'
import { cn } from '@/shared/lib/utils'

interface SparklineProps {
  values: readonly number[]
  direction: 'up' | 'down' | 'flat'
  className?: string
  width?: number
  height?: number
}

const strokeClass = { up: 'stroke-up', down: 'stroke-down', flat: 'stroke-flat' } as const
const stopClass = { up: 'text-up', down: 'text-down', flat: 'text-flat' } as const

/** A decorative trend line; the adjacent numbers carry the information. */
export function Sparkline({ values, direction, className, width = 96, height = 28 }: SparklineProps) {
  const gradientId = useId()
  if (values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = width / (values.length - 1)
  const points = values.map((value, index) => [index * step, height - 2 - ((value - min) / span) * (height - 4)] as const)
  const line = points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `${line} L${width},${height} L0,${height} Z`
  return (
    <svg
      aria-hidden
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn('overflow-visible', stopClass[direction], className)}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.22" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path d={line} fill="none" strokeWidth={1.4} strokeLinejoin="round" strokeLinecap="round" className={strokeClass[direction]} />
    </svg>
  )
}
