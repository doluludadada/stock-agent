import { cn } from '@/shared/lib/utils'

interface BreadthBarProps {
  up: number
  flat: number
  down: number
  className?: string
}

/** How a group of stocks split into risers, unchanged and fallers, as one bar; the counts next to it carry the numbers. */
export function BreadthBar({ up, flat, down, className }: BreadthBarProps) {
  const total = up + flat + down
  const share = (count: number) => (total === 0 ? 0 : (count / total) * 100)
  return (
    <div aria-hidden className={cn('flex h-2 gap-0.5 overflow-hidden rounded-full bg-muted', className)}>
      {up > 0 && <span className="rounded-full bg-up" style={{ width: `${share(up)}%` }} />}
      {flat > 0 && <span className="rounded-full bg-flat/50" style={{ width: `${share(flat)}%` }} />}
      {down > 0 && <span className="rounded-full bg-down" style={{ width: `${share(down)}%` }} />}
    </div>
  )
}
