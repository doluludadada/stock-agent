import { PencilLine, Search, Star, Trash2 } from 'lucide-react'
import { useId, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError, useAllows, useStockQuotes, type Loadable, type StockQuote } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { directionOf } from '@/shared/lib/direction'
import { useFormat } from '@/shared/lib/format'
import { useErrorReason } from '@/shared/lib/error-reason'
import { Badge } from '@/shared/ui/badge'
import { StockLink } from '@/shared/ui/stock-name'
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
import { QuoteTime } from '@/shared/ui/quote-time'
import { PageSkeleton, Skeleton } from '@/shared/ui/skeleton'
import { Sparkline } from '@/shared/ui/sparkline'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { StockPicker } from '@/shared/ui/stock-picker'
import { useWatchlistChange, useWatchlistEntries, type WatchlistEntry } from './api'
import { byStock, daySummary, latestSession, shownRows, SORT_KEYS, watchlistSources, type Mover, type Quotes, type SortKey, type SourceFilter, type WatchRow } from './model'

export function WatchlistPage() {
  const { t } = useTranslation('watchlist')
  const reason = useErrorReason()
  const entries = useWatchlistEntries()
  const change = useWatchlistChange()
  const rows = useMemo(() => byStock(entries.data ?? []), [entries.data])

  const add = (stockId: string) =>
    change.mutate(
      { action: 'add', stockIds: [stockId] },
      {
        onSuccess: () => toast.success(t('toast.added', { name: stockId })),
        onError: (error) => toast.error(isApiError(error, 'invalid') ? t('toast.unlisted', { code: stockId }) : t('toast.failed', { reason: reason(error) })),
      },
    )
  const addControl = <StockPicker label={t('action.addStock')} onSelect={add} />

  return (
    <div className="page-stack">
      <PageHeader
        title={t('title')}
        actions={entries.data && rows.length > 0 && addControl}
      />
      <RequireSignIn reason={t('signIn')} layout="page">
        {entries.isPending ? (
          <PageSkeleton />
        ) : entries.isError ? (
          <ErrorState error={entries.error} title={t('loadFailed')} onRetry={() => void entries.refetch()} framed />
        ) : rows.length === 0 ? (
          <StateBlock icon={Star} title={t('empty.title')} description={t('empty.description')} framed action={addControl} />
        ) : (
          <Watchlist rows={rows} />
        )}
      </RequireSignIn>
    </div>
  )
}

/** The list, then how it did in the latest session, beside it from 1280 px. */
function Watchlist({ rows }: { rows: WatchRow[] }) {
  const codes = useMemo(() => rows.map((row) => row.stockId), [rows])
  const { quotes, trends, live } = useStockQuotes(codes)
  return (
    <div className="card-grid xl:grid-cols-[minmax(0,1fr)_22rem]">
      <StockList rows={rows} quotes={quotes} trends={trends} live={live} />
      <DayPanel rows={rows} quotes={quotes} />
    </div>
  )
}

interface DayPanelProps {
  rows: WatchRow[]
  quotes: Quotes
  /** The card's name where it stands outside the watchlist, and its way to the list. */
  title?: string
  aside?: ReactNode
  className?: string
}

/**
 * "How did my stocks do": in the latest session, never mixing in a stock whose close is older. The watchlist and the
 * home page show the same card.
 */
export function DayPanel({ rows, quotes, title, aside, className }: DayPanelProps) {
  const { t } = useTranslation('watchlist')
  const format = useFormat()
  const summary = daySummary(rows, quotes)
  const pending = rows.filter((row) => (quotes.get(row.stockId)?.status ?? 'loading') === 'loading').length
  const main = summary.session ? t('summary.question', { date: format.monthDay(summary.session) }) : t('summary.waiting')
  const note = pending > 0 ? t('summary.pending', { count: pending }) : summary.earlier > 0 ? t('summary.earlier', { count: summary.earlier }) : null
  return (
    <Panel className={className} title={title ?? t('summary.title')} description={note ? t('summary.withNote', { main, note }) : main} aside={aside}>
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
  /** A session trades, so today's quotes among them still change. */
  live: boolean
  className?: string
}

function StockList({ rows, quotes, trends, live, className }: StockListProps) {
  const { t } = useTranslation('watchlist')
  const reason = useErrorReason()
  const format = useFormat()
  const change = useWatchlistChange()
  const listId = useId()
  const [filter, setFilter] = useState<SourceFilter>('all')
  const [sort, setSort] = useState<SortKey>('change')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState(false)
  const shown = shownRows(rows, quotes, filter, query, sort)
  const latest = latestSession(quotes)
  const filters: readonly SourceFilter[] = ['all', ...watchlistSources(useAllows('realtime_quotes'))]
  const counts = Object.fromEntries(filters.map((key) => [key, key === 'all' ? rows.length : rows.filter((row) => row.entries.some((entry) => entry.watchlist_type === key)).length]))

  const remove = (row: WatchRow) =>
    change.mutate(
      { action: 'remove', stockIds: [row.stockId] },
      {
        onSuccess: () => toast.success(t('toast.removed', { name: row.name ?? row.stockId })),
        onError: (error) => toast.error(t('toast.failed', { reason: reason(error) })),
      },
    )

  const columns: Column<WatchRow>[] = [
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <StockLink stockId={row.stockId} name={row.name} unnamed={t('unknownName')}>
          <span className="truncate text-xs text-muted-foreground lg:hidden">{sourceText(row.entries, t, format)}</span>
        </StockLink>
      ),
    },
    { key: 'trend', header: t('column.trend'), from: 'md', cell: (row) => <Trend state={trends.get(row.stockId)} /> },
    { key: 'close', header: t('column.close'), numeric: true, cell: (row) => <Close state={quotes.get(row.stockId)} latest={latest} live={live} /> },
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
          options={filters.map((key) => ({ value: key, label: t(key === 'all' ? 'filter.all' : `type.${key}`), count: counts[key] }))}
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

/** The close, with its session when it is older than the list's latest one, or today's quote with its last trade's time. */
function Close({ state, latest, live }: { state: Loadable<StockQuote> | undefined; latest: string | null; live: boolean }) {
  const format = useFormat()
  if (!state || state.status === 'loading') return <Skeleton className="ml-auto h-4 w-14" />
  if (state.status === 'failed') return <span className="text-muted-foreground">—</span>
  const older = latest !== null && state.value.session < latest
  return (
    <span className="inline-flex flex-col items-end">
      <span className="font-semibold">{format.price(state.value.close)}</span>
      {older && <span className="text-xs font-normal text-gold">{format.closeOn(state.value.session)}</span>}
      {state.value.tradedAt && <QuoteTime tradedAt={state.value.tradedAt} live={live} className="text-xs font-normal text-muted-foreground" />}
    </span>
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
