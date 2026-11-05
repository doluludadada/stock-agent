import { cn } from '@/shared/lib/utils'

export interface Segment {
  key: string
  value: number
  /** A background role, such as `bg-up`. */
  className: string
}

/** Parts of a whole as one bar; `label` says in words what the bar shows. */
export function StackedBar({ segments, label, className }: { segments: readonly Segment[]; label: string; className?: string }) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0)
  return (
    <div role="img" aria-label={label} className={cn('flex h-2 gap-px overflow-hidden rounded-full bg-muted', className)}>
      {total > 0 && segments.map((segment) => <div key={segment.key} className={segment.className} style={{ width: `${(segment.value / total) * 100}%` }} />)}
    </div>
  )
}
