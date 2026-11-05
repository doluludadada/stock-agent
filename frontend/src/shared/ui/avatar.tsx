import { cn } from '@/shared/lib/utils'

/** A person's initial in a circle; the name next to it or in its label carries the meaning. */
export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span aria-hidden className={cn('grid size-8 shrink-0 place-items-center rounded-full bg-brand-soft text-sm font-semibold text-brand uppercase', className)}>
      {name.trim().charAt(0) || '?'}
    </span>
  )
}
