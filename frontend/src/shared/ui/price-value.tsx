import { directionOf, PRICE_TONE } from '@/shared/lib/direction'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'

/** A price in its market color against a reference, such as the day's high against the close before it. */
export function PriceValue({ value, reference, className }: { value: number; reference: number | null; className?: string }) {
  const format = useFormat()
  return <span className={cn('tabular', reference !== null && PRICE_TONE[directionOf(value - reference)], className)}>{format.price(value)}</span>
}
