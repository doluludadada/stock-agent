import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { paths } from '@/shared/config/paths'
import { cn } from '@/shared/lib/utils'

interface StockNameProps {
  stockId: string
  /** The listing's name; a stock it does not name shows `unnamed`, or its code alone. */
  name: string | null | undefined
  unnamed?: string
  /** What follows the code on the same line, such as a badge. */
  children?: ReactNode
  className?: string
}

/** A stock's name with its code beside it. */
export function StockName({ stockId, name, unnamed, children, className }: StockNameProps) {
  const label = name ?? unnamed ?? stockId
  return (
    <span className={cn('flex min-w-0 items-baseline gap-2', className)}>
      <span className="truncate font-medium" title={name ?? undefined}>
        {label}
      </span>
      {label !== stockId && <span className="shrink-0 font-mono text-xs font-normal text-muted-foreground">{stockId}</span>}
      {children}
    </span>
  )
}

interface StockLinkProps extends Omit<StockNameProps, 'children'> {
  badge?: ReactNode
  /** A second line under the name, such as what a phone's hidden columns said. */
  children?: ReactNode
  /** False where the row holds other controls, so the link covers only itself. */
  stretched?: boolean
}

/** A stock in a table row or a list: its name and code as the link to its page, the whole row by default. */
export function StockLink({ stockId, name, unnamed, badge, children, stretched = true, className }: StockLinkProps) {
  return (
    <Link to={paths.stock(stockId)} className={cn('flex min-h-11 min-w-0 flex-col justify-center hover:text-brand focus-visible:text-brand md:min-h-0', stretched && 'stretched-link', className)}>
      <StockName stockId={stockId} name={name} unnamed={unnamed}>
        {badge}
      </StockName>
      {children}
    </Link>
  )
}

/** A stock as a small pill that links to its page, for a run of stocks inside text. */
export function StockChip({ stockId, name }: Pick<StockNameProps, 'stockId' | 'name'>) {
  return (
    <Link
      to={paths.stock(stockId)}
      className="inline-flex min-h-11 items-center gap-1 rounded-full border px-2.5 text-xs whitespace-nowrap hover:border-primary/40 hover:text-brand focus-visible:text-brand md:min-h-6"
    >
      {name ?? stockId}
      {name != null && <span className="font-mono text-muted-foreground">{stockId}</span>}
    </Link>
  )
}
