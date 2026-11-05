import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

/** The width from which a column shows; below it the column steps aside and its row says what matters in one cell. */
type ShownFrom = 'sm' | 'md' | 'lg' | 'xl'

const SHOWN_FROM: Record<ShownFrom, string> = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
  lg: 'hidden lg:table-cell',
  xl: 'hidden xl:table-cell',
}

export interface Column<Row> {
  key: string
  header: ReactNode
  cell: (row: Row, index: number) => ReactNode
  /** Right-aligned tabular figures. */
  numeric?: boolean
  from?: ShownFrom
  /** A header read by screen readers only, such as a rank or an actions column. */
  quietHeader?: boolean
  className?: string
}

interface DataTableProps<Row> {
  rows: readonly Row[]
  columns: readonly Column<Row>[]
  rowKey: (row: Row) => string
  /** The table's accessible name. */
  label: string
  id?: string
  /** A link with `stretched-link` in one cell makes the whole row its target. */
  rowClassName?: (row: Row) => string | undefined
  className?: string
}

/**
 * Every table of the app: real column headers for screen readers, rows at least 44 px tall, tabular figures, and
 * columns that step aside on narrow screens. On a phone a row reads as two lines: the first cell carries what the
 * hidden columns said. Sorting, filtering and paging stay with the page that owns the rows.
 */
export function DataTable<Row>({ rows, columns, rowKey, label, id, rowClassName, className }: DataTableProps<Row>) {
  const cellClass = (column: Column<Row>) =>
    cn('px-2 first:pl-4 last:pr-4 md:first:pl-5 md:last:pr-5', column.numeric && 'tabular text-right whitespace-nowrap', column.from && SHOWN_FROM[column.from], column.className)
  return (
    <div className={cn('w-full overflow-x-auto', className)}>
      <table id={id} aria-label={label} className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b bg-surface-sunken/70">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(cellClass(column), 'h-9 text-xs font-medium whitespace-nowrap text-muted-foreground', !column.numeric && 'text-left')}
              >
                {column.quietHeader ? <span className="sr-only">{column.header}</span> : column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={rowKey(row)}
              className={cn('relative border-b transition-colors last:border-0 hover:bg-muted/60 has-[a:focus-visible]:bg-muted/60', rowClassName?.(row))}
            >
              {columns.map((column) => (
                <td key={column.key} className={cn(cellClass(column), 'h-12 py-2 md:h-11')}>
                  {column.cell(row, index)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
