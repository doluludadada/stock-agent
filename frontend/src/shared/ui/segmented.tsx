import { ToggleGroup } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

export interface SegmentedOption<T extends string> {
  value: T
  label: ReactNode
  /** A count shown after the label, such as the rows a filter keeps. */
  count?: number
}

interface SegmentedProps<T extends string> {
  value: T
  onChange: (value: T) => void
  options: readonly SegmentedOption<T>[]
  label: string
  className?: string
}

/** One choice out of a few: chart ranges, list filters, the theme. Arrow keys move between the options. */
export function Segmented<T extends string>({ value, onChange, options, label, className }: SegmentedProps<T>) {
  return (
    <ToggleGroup.Root
      type="single"
      role="radiogroup"
      value={value}
      onValueChange={(next) => next && onChange(next as T)}
      aria-label={label}
      className={cn('inline-flex h-12 w-full max-w-full items-stretch gap-0.5 overflow-x-auto rounded-lg bg-muted p-0.5 md:h-8 md:w-fit', className)}
    >
      {options.map((option) => (
        <ToggleGroup.Item
          key={option.value}
          value={option.value}
          className="tabular inline-flex flex-1 shrink-0 items-center justify-center gap-1.5 rounded-md px-2.5 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[state=on]:bg-card data-[state=on]:text-foreground data-[state=on]:shadow-card md:text-xs dark:data-[state=on]:bg-surface-raised"
        >
          {option.label}
          {option.count !== undefined && <span className="text-xs font-normal text-muted-foreground">{option.count}</span>}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  )
}
