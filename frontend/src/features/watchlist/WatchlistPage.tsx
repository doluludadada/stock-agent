import { PencilLine, Search, Star, Trash2 } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError, useStockQuotes, type Loadable, type StockQuote } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { directionOf } from '@/shared/lib/direction'
import { useFormat } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { BreadthBar } from '@/shared/ui/breadth-bar'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Segmented } from '@/shared/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Skeleton } from '@/shared/ui/skeleton'
import { Sparkline } from '@/shared/ui/sparkline'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { StockPicker } from '@/shared/ui/stock-picker'
import { useWatchlistChange, useWatchlistEntries, type WatchlistEntry } from './api'
import { byStock, daySummary, latestSession, shownRows, SORT_KEYS, SOURCE_FILTERS, type Mover, type Quotes, type SortKey, type SourceFilter, type WatchRow } from './model'

export function WatchlistPage() {
  const { t } = useTranslation('watchlist')
  const entries = useWatchlistEntries()
  const change = useWatchlistChange()
  const rows = useMemo(() => byStock(entries.data ?? []), [entries.data])

  const add = (stockId: string) =>
    change.mutate(
      { action: 'add', stockIds: [stockId] },
      {
        onSuccess: () => toast.success(t('toast.added', { name: stockId })),
        onError: (error) => toast.error(isApiError(error, 'invalid') ? t('toast.unlisted', { code: stockId }) : t('toast.failed', { reason: error.message })),
      },
    )
  const addControl = <StockPicker label={t('action.addStock')} onSelect={add} />

  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader
        eyebrow={t('common:nav.section.mine')}
        title={t('title')}
        description={entries.data ? t('description', { count: rows.length }) : t('lead')}
        actions={entries.data && rows.length > 0 && addControl}
      />
      <RequireSignIn reason={t('signIn')} layout="page">
        {entries.isPending ? (
          <Skeleton className="h-96 rounded-2xl" />
        ) : entries.isError ? (
          <ErrorState error={entries.error} title={t('loadFailed')} onRetry={() => void entries.refetch()} className="rounded-2xl border bg-card py-12" />
        ) : rows.length === 0 ? (
          <StateBlock icon={Star} title={t('empty.title')} description={t('empty.description')} className="rounded-2xl border bg-card py-12" action={addControl} />
        ) : (
          <Watchlist rows={rows} />
        )}
      </RequireSignIn>
    </div>
  )
}

/**
 * The list beside its summary from 1280 px; above it, narrower. Each stock's quote comes from the shared market data,
 * so a stock opened from the list is already loaded.
 */
function Watchlist({ rows }: { rows: WatchRow[] }) {
  const codes = useMemo(() => rows.map((row) => row.stockId), [rows])
  const { quotes, trends } = useStockQuotes(codes)
  return (
    <div className="grid items-start gap-4 lg:gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <SummaryPanel rows={rows} quotes={quotes} className="xl:col-start-2 xl:row-start-1" />
      <StockList rows={rows} quotes={quotes} trends={trends} className="xl:col-start-1 xl:row-span-2 xl:row-start-1" />
      <SourcesPanel className="hidden xl:col-start-2 xl:row-start-2 xl:flex" />
    </div>
  )
}

/** "How did my stocks do": in the latest session, never mixing in a stock whose close is older. */
function SummaryPanel({ rows, quotes, className }: { rows: WatchRow[]; quotes: Quotes; className?: string }) {
  const { t } = useTranslation('watchlist')
  const format = useFormat()
  const summary = daySummary(rows, quotes)
  const pending = rows.filter((row) => (quotes.get(row.stockId)?.status ?? 'loading') === 'loading').length
  const main = summary.session ? t('summary.question', { date: format.monthDay(summary.session) }) : t('summary.waiting')
  const note = pending > 0 ? t('summary.pending', { count: pending }) : summary.earlier > 0 ? t('summary.earlier', { count: summary.earlier }) : null
  const description = note ? t('summary.withNote', { main, note }) : main
  return (
    <Panel className={className} title={t('summary.title')} description={description}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-5 @2xl:grid-cols-4 @2xl:gap-x-6">
        <div className="col-span-2 space-y-2.5 @2xl:col-span-1">
          <Stat label={t('summary.moves')}>
            <span className="flex items-baseline gap-3 text-base font-semibold">
              <span className="text-up">{t('summary.up', { count: summary.up })}</span>
              <span className="text-down">{t('summary.down', { count: summary.down })}</span>
              <span className="text-flat">{t('summary.flat', { count: summary.flat })}</span>
            </span>
          </Stat>
          <BreadthBar up={summary.up} flat={summary.flat} down={summary.down} />
        </div>
        <Stat label={t('summary.average')} className="col-span-2 @2xl:col-span-1">
          {summary.average === null ? <span className="text-base text-muted-foreground">—</span> : <ChangeValue value={summary.average} format="percent" className="text-base font-semibold" />}
        </Stat>
        <MoverStat label={t('summary.best')} mover={summary.best} />
        <MoverStat label={t('summary.worst')} mover={summary.worst} />
      </dl>
    </Panel>
  )
}

function MoverStat({ label, mover }: { label: string; mover: Mover | null }) {
  const { t } = useTranslation('watchlist')
  return (
    <Stat label={label}>
      {mover ? (
        <Link to={paths.stock(mover.row.stockId)} className="flex min-h-11 flex-col items-start hover:text-brand md:min-h-0">
          <span className="max-w-full truncate text-base font-semibold">{mover.row.name ?? t('unknownName')}</span>
          <ChangeValue value={mover.changeRatio} format="percent" />
        </Link>
      ) : (
        <span className="text-base text-muted-foreground">—</span>
      )}
    </Stat>
  )
}

interface StockListProps {
  rows: WatchRow[]
  quotes: Quotes
  trends: ReadonlyMap<string, Loadable<readonly number[]>>
  className?: string
}

function StockList({ rows, quotes, trends, className }: StockListProps) {
  const { t } = useTranslation('watchlist')
  const format = useFormat()
  const change = useWatchlistChange()
  const listId = useId()
  const [filter, setFilter] = useState<SourceFilter>('all')
  const [sort, setSort] = useState<SortKey>('change')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState(false)
  const shown = shownRows(rows, quotes, filter, query, sort)
  const latest = latestSession(quotes)
  const counts = Object.fromEntries(SOURCE_FILTERS.map((key) => [key, key === 'all' ? rows.length : rows.filter((row) => row.entries.some((entry) => entry.watchlist_type === key)).length]))

  const remove = (row: WatchRow) =>
    change.mutate(
      { action: 'remove', stockIds: [row.stockId] },
      {
        onSuccess: () => toast.success(t('toast.removed', { name: row.name ?? row.stockId })),
        onError: (error) => toast.error(t('toast.failed', { reason: error.message })),
      },
    )

  const columns: Column<WatchRow>[] = [
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <div className="min-w-0 py-1">
          <Link to={paths.stock(row.stockId)} className="stretched-link flex min-w-0 items-baseline gap-2 hover:text-brand focus-visible:text-brand">
            <span className="truncate font-medium" title={row.name ?? undefined}>
              {row.name ?? t('unknownName')}
            </span>
            <span className="shrink-0 font-mono text-xs text-muted-foreground">{row.stockId}</span>
          </Link>
          <p className="mt-0.5 truncate text-xs text-muted-foreground lg:hidden">{sourceText(row.entries, t, format)}</p>
        </div>
      ),
    },
    { key: 'trend', header: t('column.trend'), from: 'md', cell: (row) => <Trend state={trends.get(row.stockId)} /> },
    { key: 'close', header: t('column.close'), numeric: true, cell: (row) => <Close state={quotes.get(row.stockId)} latest={latest} /> },
    {
      key: 'change',
      header: t('column.change'),
      numeric: true,
      cell: (row) => {
        const state = quotes.get(row.stockId)
        return state?.status === 'ready' && state.value.changeRatio !== null ? <ChangeValue value={state.value.changeRatio} format="percent" pill /> : <span className="text-muted-foreground">—</span>
      },
    },
    {
      key: 'source',
      header: t('column.source'),
      from: 'lg',
      cell: (row) => (
        <span className="flex flex-wrap gap-1.5">
          {row.entries.map((entry) => (
            <Badge key={entry.watchlist_type} variant="outline" className="gap-1 font-normal">
              {t(`type.${entry.watchlist_type}`)}
              <span className="tabular text-muted-foreground">{entryDate(entry, t, format)}</span>
            </Badge>
          ))}
        </span>
      ),
    },
    ...(editing
      ? [
          {
            key: 'remove',
            header: t('column.actions'),
            quietHeader: true,
            className: 'w-14 text-right',
            cell: (row: WatchRow) =>
              row.entries.some((entry) => entry.watchlist_type === 'manual') ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => remove(row)}
                  disabled={change.isPending}
                  aria-label={t('action.removeNamed', { name: row.name ?? row.stockId })}
                  className="relative z-10 text-muted-foreground hover:text-destructive"
                >
                  <Trash2 aria-hidden />
                </Button>
              ) : (
                <span className="block w-20 text-right text-xs whitespace-normal text-muted-foreground">{t('automaticOnly')}</span>
              ),
          },
        ]
      : []),
  ]

  return (
    <Panel
      className={className}
      flush
      title={t('list.title')}
      description={t('count', { count: shown.length, total: rows.length })}
      aside={
        <Button type="button" variant={editing ? 'secondary' : 'ghost'} size="sm" aria-pressed={editing} aria-controls={listId} onClick={() => setEditing(!editing)}>
          <PencilLine aria-hidden />
          {t(editing ? 'action.doneEditing' : 'action.edit')}
        </Button>
      }
    >
      <div className="flex flex-col gap-2 border-b px-4 py-3 md:px-5 @2xl:flex-row @2xl:items-center">
        <Segmented
          value={filter}
          onChange={setFilter}
          label={t('filter.label')}
          options={SOURCE_FILTERS.map((key) => ({ value: key, label: t(key === 'all' ? 'filter.all' : `type.${key}`), count: counts[key] }))}
        />
        <div className="flex gap-2 @2xl:ml-auto">
          <span className="relative min-w-0 flex-1 @2xl:w-48 @2xl:flex-none">
            <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('search.placeholder')} aria-label={t('search.label')} className="pl-9" />
          </span>
          <Select value={sort} onValueChange={(value) => setSort(value as SortKey)}>
            <SelectTrigger aria-label={t('sort.label')} className="w-32 shrink-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              {SORT_KEYS.map((key) => (
                <SelectItem key={key} value={key}>
                  {t(`sort.${key}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {shown.length === 0 ? (
        <StateBlock icon={Search} title={t('search.noMatch')} description={t('search.noMatchHint')} />
      ) : (
        <DataTable id={listId} rows={shown} columns={columns} rowKey={(row) => row.stockId} label={t('list.title')} />
      )}
    </Panel>
  )
}

/** The month's closes; a stock with no history says so in one dash. */
function Trend({ state }: { state: Loadable<readonly number[]> | undefined }) {
  if (!state || state.status === 'loading') return <Skeleton className="h-7 w-24 rounded" />
  if (state.status === 'failed' || state.value.length < 2) return <span className="text-muted-foreground">—</span>
  return <Sparkline values={state.value} direction={directionOf((state.value.at(-1) ?? 0) - (state.value[0] ?? 0))} width={96} height={28} className="h-7 w-24" />
}

/** The close, with its session when it is older than the list's latest one. */
function Close({ state, latest }: { state: Loadable<StockQuote> | undefined; latest: string | null }) {
  const format = useFormat()
  if (!state || state.status === 'loading') return <Skeleton className="ml-auto h-4 w-14" />
  if (state.status === 'failed') return <span className="text-muted-foreground">—</span>
  const older = latest !== null && state.value.session < latest
  return (
    <span className="inline-flex flex-col items-end">
      <span className="font-semibold">{format.price(state.value.close)}</span>
      {older && <span className="text-xs font-normal text-gold">{format.closeOn(state.value.session)}</span>}
    </span>
  )
}

/** Where the list comes from, beside it on a wide screen. */
function SourcesPanel({ className }: { className?: string }) {
  const { t } = useTranslation('watchlist')
  return (
    <Panel className={className} title={t('sources.title')} description={t('sources.question')}>
      <dl className="space-y-3.5 text-sm">
        {(['manual', 'technical', 'buzz'] as const).map((type) => (
          <div key={type} className="space-y-1">
            <dt>
              <Badge variant="outline" className="font-normal">
                {t(`type.${type}`)}
              </Badge>
            </dt>
            <dd className="text-pretty text-muted-foreground">{t(`sources.${type}`)}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  )
}

type Translate = ReturnType<typeof useTranslation>['t']
type Format = ReturnType<typeof useFormat>

function entryDate(entry: WatchlistEntry, t: Translate, format: Format): string {
  return entry.expires_at ? t('expires', { date: format.monthDay(entry.expires_at) }) : t('addedAt', { date: format.monthDay(entry.created_at) })
}

function sourceText(entries: readonly WatchlistEntry[], t: Translate, format: Format): string {
  return entries.map((entry) => `${t(`type.${entry.watchlist_type}`)} · ${entryDate(entry, t, format)}`).join('，')
}
