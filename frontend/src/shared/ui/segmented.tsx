import { ToggleGroup } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

export interface SegmentedOption<T extends string> {
  value: T
  label: ReactNode
  /** A count shown after the label, such as the rows a filter keeps. */
  count?: number
}

/** The characters a phone's row holds at the control's text size, and what one button's padding takes of them. */
const ROW_CHARACTERS = 40
const BUTTON_CHARACTERS = 3

/**
 * Whether options show whole as one row of buttons on a phone, the narrowest place a control is in: a control whose
 * options do not fit lists them instead, so none is cut off.
 */
export function fitsSegmented(labels: readonly string[]): boolean {
  return labels.join('').length + labels.length * BUTTON_CHARACTERS <= ROW_CHARACTERS
}

interface SegmentedProps<T extends string> {
  value: T
  onChange: (value: T) => void
  options: readonly SegmentedOption<T>[]
  label: string
  /** The ids of the texts that describe the choice, such as a form field's help. */
  describedBy?: string
  className?: string
}

/** One choice out of a few: chart ranges, list filters, the theme. Arrow keys move between the options. */
export function Segmented<T extends string>({ value, onChange, options, label, describedBy, className }: SegmentedProps<T>) {
  return (
    <ToggleGroup.Root
      type="single"
      role="radiogroup"
      value={value}
      onValueChange={(next) => next && onChange(next as T)}
      aria-label={label}
      aria-describedby={describedBy}
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
