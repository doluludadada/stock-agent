import { ReceiptText } from 'lucide-react'
import { useTranslation } from '@/i18n'
import type { Order } from '@/shared/api'
import { DASH, useFormat } from '@/shared/lib/format'
import { DataTable, type Column } from './data-table'
import { StateBlock } from './state-block'

interface OrdersTableProps {
  orders: readonly Order[]
  /** The table's accessible name. */
  label: string
  /** For a narrow card: the stock, the side, the status with the reason under it, and the quantity filled. */
  compact?: boolean
}

/** A run's orders as the journal keeps them: each with the status the broker gave it and the reason; one line when it placed none. */
export function OrdersTable({ orders, label, compact = false }: OrdersTableProps) {
  const { t } = useTranslation('runs')
  const format = useFormat()
  if (orders.length === 0) return <StateBlock icon={ReceiptText} title={t('noOrders')} className="py-4" />
  const stock: Column<Order> = { key: 'stock', header: t('column.stock'), className: 'font-mono', cell: (order) => order.stock_id }
  const action: Column<Order> = { key: 'action', header: t('column.action'), cell: (order) => t(`action.${order.action}`) }
  const quantity: Column<Order> = {
    key: 'quantity',
    header: t('column.quantity'),
    numeric: true,
    cell: (order) => `${format.number(order.filled_quantity)} / ${format.number(order.quantity)}`,
  }
  const columns: Column<Order>[] = compact
    ? [
        stock,
        action,
        {
          key: 'status',
          header: t('column.status'),
          className: 'w-full whitespace-normal',
          cell: (order) => (
            <>
              {t(`orderStatus.${order.status}`)}
              {order.reason && <span className="block text-xs text-muted-foreground">{order.reason}</span>}
            </>
          ),
        },
        quantity,
      ]
    : [
        stock,
        action,
        { key: 'status', header: t('column.status'), cell: (order) => t(`orderStatus.${order.status}`) },
        quantity,
        { key: 'price', header: t('column.price'), numeric: true, from: 'sm', cell: (order) => (order.limit_price !== null ? format.price(order.limit_price) : DASH) },
        { key: 'costs', header: t('column.costs'), numeric: true, from: 'md', cell: (order) => format.number(order.fee + order.tax) },
        { key: 'reason', header: t('column.reason'), from: 'lg', className: 'w-full min-w-48 whitespace-normal text-xs text-muted-foreground', cell: (order) => order.reason ?? '' },
      ]
  return <DataTable rows={orders} columns={columns} rowKey={(order) => order.id} label={label} />
}
