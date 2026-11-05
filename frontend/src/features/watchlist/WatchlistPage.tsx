import { Plus, Search, Star, Trash2 } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { isApiError } from '@/shared/api'
import { formatDate } from '@/shared/lib/format'
import { isStockId } from '@/shared/lib/stock-ids'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { RequireUnlock } from '@/shared/ui/unlock'
import { useWatchlistChange, useWatchlistEntries, type WatchlistEntry } from './api'

export function WatchlistPage() {
  const { t } = useTranslation('watchlist')
  return (
    <div className="space-y-4">
      <PageHeader title={t('title')} description={t('description')} />
      <RequireUnlock scope="owner" className="rounded-xl border">
        <Watchlist />
      </RequireUnlock>
    </div>
  )
}

interface Row {
  stockId: string
  name: string | null
  entries: WatchlistEntry[]
}

function byStock(entries: readonly WatchlistEntry[]): Row[] {
  const rows = new Map<string, Row>()
  for (const entry of entries) {
    const row = rows.get(entry.stock_id) ?? { stockId: entry.stock_id, name: entry.name ?? null, entries: [] }
    row.entries.push(entry)
    rows.set(entry.stock_id, row)
  }
  return [...rows.values()]
}

function Watchlist() {
  const { t } = useTranslation('watchlist')
  const entries = useWatchlistEntries()
  const change = useWatchlistChange()
  const [query, setQuery] = useState('')
  const rows = useMemo(() => byStock(entries.data ?? []), [entries.data])
  const needle = query.trim().toLowerCase()
  const shown = rows.filter((row) => !needle || row.stockId.toLowerCase().startsWith(needle) || (row.name ?? '').toLowerCase().includes(needle))

  const remove = (row: Row) =>
    change.mutate(
      { action: 'remove', stockIds: [row.stockId] },
      {
        onSuccess: () => toast.success(t('toast.removed', { name: row.name ?? row.stockId })),
        onError: (error) => toast.error(t('toast.failed', { reason: error.message })),
      },
    )

  if (entries.isPending) return <Skeleton className="h-64 rounded-xl" />
  if (entries.isError) return <ErrorState error={entries.error} title={t('loadFailed')} onRetry={() => void entries.refetch()} className="rounded-xl border" />

  return (
    <div className="space-y-4">
      <Panel
        title={
          <span className="relative w-full max-w-60 font-normal">
            <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('search.placeholder')} aria-label={t('search.label')} className="h-8 pl-8" />
          </span>
        }
        aside={<AddStock />}
        flush
      >
        {rows.length === 0 ? (
          <StateBlock icon={Star} title={t('empty.title')} description={t('empty.description')} />
        ) : shown.length === 0 ? (
          <StateBlock icon={Search} title={t('search.noMatch')} description={t('search.noMatchHint')} />
        ) : (
          <ul className="divide-y">
            {shown.map((row) => (
              <WatchRow key={row.stockId} row={row} onRemove={() => remove(row)} busy={change.isPending} />
            ))}
          </ul>
        )}
        <p className="tabular border-t px-4 py-2 text-xs text-muted-foreground">{t('count', { count: shown.length, total: rows.length })}</p>
      </Panel>
    </div>
  )
}

function WatchRow({ row, onRemove, busy }: { row: Row; onRemove: () => void; busy: boolean }) {
  const { t } = useTranslation('watchlist')
  const locale = useLocale()
  const manual = row.entries.find((entry) => entry.watchlist_type === 'manual')
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-2.5">
      <Link to={paths.stock(row.stockId)} className="flex min-w-0 items-baseline gap-2.5 hover:text-primary">
        <span className="w-14 shrink-0 font-mono text-xs text-muted-foreground">{row.stockId}</span>
        <span className="truncate text-sm font-medium">{row.name ?? t('unknownName')}</span>
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        {row.entries.map((entry) => (
          <Badge key={entry.watchlist_type} variant="outline" className="gap-1 font-normal">
            {t(`type.${entry.watchlist_type}`)}
            <span className="tabular text-muted-foreground">
              {entry.expires_at ? t('expires', { date: formatDate(locale, entry.expires_at) }) : t('addedAt', { date: formatDate(locale, entry.created_at) })}
            </span>
          </Badge>
        ))}
        {manual ? (
          <Button type="button" variant="ghost" size="icon-sm" onClick={onRemove} disabled={busy} aria-label={t('action.removeNamed', { name: row.name ?? row.stockId })} title={t('action.remove')}>
            <Trash2 aria-hidden />
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">{t('automaticOnly')}</span>
        )}
      </div>
    </li>
  )
}

function AddStock() {
  const { t } = useTranslation('watchlist')
  const change = useWatchlistChange()
  const [code, setCode] = useState('')
  const stockId = code.trim().toUpperCase()
  const valid = isStockId(stockId)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!valid) return
    change.mutate(
      { action: 'add', stockIds: [stockId] },
      {
        onSuccess: () => {
          setCode('')
          toast.success(t('toast.added', { name: stockId }))
        },
        onError: (error) => toast.error(isApiError(error, 'invalid') ? t('toast.unlisted', { code: stockId }) : t('toast.failed', { reason: error.message })),
      },
    )
  }

  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <Input value={code} onChange={(event) => setCode(event.target.value)} placeholder={t('add.placeholder')} aria-label={t('add.label')} className="h-8 w-40 font-mono" maxLength={10} />
      <Button type="submit" size="sm" disabled={!valid || change.isPending}>
        <Plus aria-hidden />
        {t('action.addStock')}
      </Button>
    </form>
  )
}
