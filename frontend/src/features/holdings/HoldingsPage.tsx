import { Briefcase, CalendarClock, Ellipsis, Pencil, Plus, Trash2 } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { isApiError, useIsSignedIn } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useErrorReason } from '@/shared/lib/error-reason'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { Checkbox } from '@/shared/ui/checkbox'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/shared/ui/dropdown-menu'
import { ErrorState } from '@/shared/ui/error-state'
import { Label } from '@/shared/ui/label'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { RankingScoreLine, RankingScoreNote } from '@/shared/ui/ranking-score'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { PageSkeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { useHoldings, useRemoveHolding } from './api'
import { HoldingDialog, type EntrySeed } from './HoldingDialog'
import {
  draftOf,
  EMPTY_DRAFT,
  holdingKey,
  offeredSources,
  sourcesToAsk,
  toggledSources,
  unreadSources,
  watchedWithoutEntry,
  type Holding,
  type Holdings,
  type HoldingSource,
  type WatchedStock,
} from './model'

const DASH = '—'

const NEW_ENTRY: EntrySeed = { draft: EMPTY_DRAFT, replaces: false }

interface HoldingsPageProps {
  /** The stocks on the user's watchlist, where the site shows it: each can be entered as a holding from here. */
  watched?: readonly WatchedStock[]
}

/**
 * What the user holds, read as one portfolio from held data: the SinoPac account's holdings, the mock account's and
 * the ones entered by hand, each under its source. It shows figures and scores and says nothing to do with them.
 */
export function HoldingsPage({ watched }: HoldingsPageProps) {
  const { t } = useTranslation('holdings')
  const signedIn = useIsSignedIn()
  const [entering, setEntering] = useState<EntrySeed | null>(null)
  // An empty page leads to the entry form from its own message, so the header offers it only beside a portfolio.
  const listed = (useHoldings(null).data?.holdings.length ?? 0) > 0
  return (
    <div className="page-stack">
      <PageHeader
        title={t('title')}
        description={t('description')}
        actions={
          signedIn &&
          listed && (
            <Button type="button" onClick={() => setEntering(NEW_ENTRY)}>
              <Plus aria-hidden />
              {t('action.add')}
            </Button>
          )
        }
      />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <Portfolio watched={watched} onEnter={setEntering} />
        <HoldingDialog seed={entering} onClose={() => setEntering(null)} />
      </RequireSignIn>
    </div>
  )
}

function Portfolio({ watched, onEnter }: { watched: readonly WatchedStock[] | undefined; onEnter: (seed: EntrySeed) => void }) {
  const { t } = useTranslation('holdings')
  const [chosen, setChosen] = useState<readonly HoldingSource[] | null>(null)
  const offered = useHoldings(null)
  const sources = offered.data ? offeredSources(offered.data.asked) : []
  const shown = useHoldings(sourcesToAsk(sources, chosen))
  const add = (
    <Button type="button" onClick={() => onEnter(NEW_ENTRY)}>
      <Plus aria-hidden />
      {t('action.add')}
    </Button>
  )

  if (offered.isPending) return <PageSkeleton />
  if (offered.isError) {
    if (isApiError(offered.error) && offered.error.code === 'ranking_unavailable') {
      return <StateBlock icon={CalendarClock} title={t('noDecision.title')} description={t('noDecision.description')} action={add} framed />
    }
    return <ErrorState error={offered.error} title={t('loadFailed')} onRetry={() => void offered.refetch()} framed />
  }

  const toEnter = watched ? watchedWithoutEntry(watched, offered.data.holdings) : []
  const watchedPanel = toEnter.length > 0 && <WatchedPanel stocks={toEnter} onEnter={onEnter} />
  if (offered.data.holdings.length === 0) {
    return (
      <div className="card-stack">
        <div className="rounded-2xl border bg-card shadow-card">
          <StateBlock icon={Briefcase} title={t('empty.title')} description={t('empty.description')} action={add} className="py-12" />
          <UnreadNote holdings={offered.data} className="border-t" />
        </div>
        {watchedPanel}
      </div>
    )
  }

  const filter = sources.length > 1 && <SourceFilter offered={sources} chosen={chosen ?? sources} onToggle={(source) => setChosen(toggledSources(sources, chosen, source))} />
  if (shown.isError) {
    return (
      <Panel flush title={t('list.title')}>
        {filter}
        <ErrorState error={shown.error} title={t('loadFailed')} onRetry={() => void shown.refetch()} />
      </Panel>
    )
  }
  const data = shown.data ?? offered.data
  return (
    <div className="card-stack">
      <div className={cn('card-stack', shown.isPlaceholderData && 'opacity-60')} aria-busy={shown.isPlaceholderData}>
        <SummaryPanel holdings={data} />
        <HoldingsPanel holdings={data} filter={filter} onEnter={onEnter} />
      </div>
      {watchedPanel}
      <footer className="space-y-2">
        {data.scored_share !== null && <RankingScoreNote />}
        <NotAdviceNote />
      </footer>
    </div>
  )
}

/** Said once where the brokerage was asked and could not be read: the portfolio on screen goes without it. */
function UnreadNote({ holdings, className }: { holdings: Holdings; className?: string }) {
  const { t } = useTranslation('holdings')
  if (!unreadSources(holdings).includes('brokerage')) return null
  return (
    <p className={cn('px-4 py-3 text-sm text-pretty text-muted-foreground md:px-5', className)}>
      {t('loginDown')}
    </p>
  )
}

/** Which sources make the portfolio. Each box is one source the site shows the user; the last one stays checked. */
function SourceFilter({ offered, chosen, onToggle }: { offered: readonly HoldingSource[]; chosen: readonly HoldingSource[]; onToggle: (source: HoldingSource) => void }) {
  const { t } = useTranslation('holdings')
  const id = useId()
  return (
    <fieldset className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b px-4 py-2 md:px-5 md:py-3">
      <legend className="sr-only">{t('filter.label')}</legend>
      <span aria-hidden className="text-xs text-muted-foreground">
        {t('filter.label')}
      </span>
      {offered.map((source) => {
        const checked = chosen.includes(source)
        return (
          <div key={source} className="flex min-h-11 items-center gap-2.5 md:min-h-0">
            <Checkbox id={`${id}-${source}`} checked={checked} disabled={checked && chosen.length === 1} onCheckedChange={() => onToggle(source)} />
            <Label htmlFor={`${id}-${source}`} className="font-normal">
              {t(`source.${source}`)}
            </Label>
          </div>
        )
      })}
    </fieldset>
  )
}

/**
 * The portfolio in figures, in the order they are asked: what it is worth and its gain or loss, how concentrated it
 * is, then how it stands in the ranking. The ranking's figures leave where the site hides the ranking from the viewer.
 */
function SummaryPanel({ holdings }: { holdings: Holdings }) {
  const { t } = useTranslation('holdings')
  return (
    <Panel title={t('summary.title')} description={t('summary.question')}>
      <PortfolioFigures holdings={holdings} />
    </Panel>
  )
}

/** The portfolio's figures without a card of their own: My holdings and the home page both show them. */
export function PortfolioFigures({ holdings }: { holdings: Holdings }) {
  const { t } = useTranslation('holdings')
  const format = useFormat()
  const share = (ratio: number) => `${format.number(ratio * 100, 1)}%`
  return (
      <div className="grid gap-x-8 gap-y-5 @4xl:grid-cols-[auto_minmax(0,1fr)] @4xl:items-end">
        <div className="min-w-0 space-y-1.5">
          <p className="text-xs text-muted-foreground">{t('summary.marketValue')}</p>
          <p className="figure">{format.number(holdings.market_value)}</p>
          <p className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">{t('summary.unrealized')}</span>
            <ChangeValue value={holdings.unrealized_pnl} format="absolute" fractionDigits={0} arrow />
            {holdings.unrealized_return !== null && <ChangeValue value={holdings.unrealized_return} format="percent" pill />}
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 @xl:grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] @4xl:border-l @4xl:pl-8">
          <Stat size="lg" label={t('summary.cost')}>
            {format.number(holdings.cost)}
          </Stat>
          <Stat size="lg" label={t('summary.concentration', { count: holdings.concentration_positions })}>
            {share(holdings.concentration)}
          </Stat>
          {holdings.top_share !== null && (
            <Stat size="lg" label={t('summary.topShare')}>
              {share(holdings.top_share)}
            </Stat>
          )}
          {holdings.scored_share !== null && (
            <Stat size="lg" label={t('summary.weightedScore')}>
              {holdings.weighted_score === null ? DASH : format.number(holdings.weighted_score)}
              <span className="block text-xs font-normal text-muted-foreground">{t('summary.unscored', { share: share(1 - holdings.scored_share) })}</span>
            </Stat>
          )}
          {holdings.lowest && <ScoredStat label={t('summary.lowest')} holding={holdings.lowest} />}
          {holdings.highest && <ScoredStat label={t('summary.highest')} holding={holdings.highest} />}
        </dl>
      </div>
  )
}

function ScoredStat({ label, holding }: { label: string; holding: Holding }) {
  const { t } = useTranslation('holdings')
  const format = useFormat()
  const score = holding.standing?.score
  return (
    <Stat size="lg" label={label}>
      {score === null || score === undefined ? DASH : format.number(score)}
      <Link to={paths.stock(holding.position.stock_id)} className="flex min-h-11 items-center truncate text-xs font-normal text-muted-foreground hover:text-brand focus-visible:text-brand md:min-h-0">
        {holding.stock_name ?? t('unknownName')} {holding.position.stock_id}
      </Link>
    </Stat>
  )
}

interface HoldingsPanelProps {
  holdings: Holdings
  filter: ReactNode
  onEnter: (seed: EntrySeed) => void
}

function HoldingsPanel({ holdings, filter, onEnter }: HoldingsPanelProps) {
  const { t } = useTranslation('holdings')
  const format = useFormat()
  const remove = useRemoveHolding()
  const reason = useErrorReason()
  const [removing, setRemoving] = useState<Holding | null>(null)
  const rows = holdings.holdings
  const name = (row: Holding) => row.stock_name ?? t('unknownName')
  const shares = (row: Holding) => format.number(row.position.quantity)
  const weight = (row: Holding) => `${format.number(row.weight * 100, 1)}%`
  const closed = (row: Holding) => (row.position.marked_at ? format.closeOn(row.position.marked_at) : t('noClose'))
  const revenue = (row: Holding) => {
    const { figure, line } = revenueReading(row, t, format)
    return line ? t('row.revenueRun', { figure, line }) : t('row.revenue', { figure })
  }

  const confirmRemoval = () => {
    if (!removing) return
    const label = name(removing)
    setRemoving(null)
    remove.mutate(removing.position.stock_id, {
      onSuccess: () => toast.success(t('remove.done', { name: label })),
      onError: (error) => toast.error(t('remove.failed', { reason: reason(error) })),
    })
  }

  const columns: Column<Holding>[] = [
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0 min-w-40',
      cell: (row) => (
        <div className="min-w-0 space-y-1 py-1">
          <Link to={paths.stock(row.position.stock_id)} className="stretched-link flex min-w-0 items-baseline gap-2 hover:text-brand focus-visible:text-brand">
            <span className="truncate font-medium" title={row.stock_name ?? undefined}>
              {name(row)}
            </span>
            <span className="shrink-0 font-mono text-xs text-muted-foreground">{row.position.stock_id}</span>
          </Link>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <Badge variant="outline" className="font-normal">
              {t(`source.${row.source}`)}
            </Badge>
            <span className="tabular lg:hidden">{t('row.held', { shares: shares(row), cost: format.price(row.position.average_cost) })}</span>
          </p>
          <p className="tabular text-xs text-muted-foreground md:hidden">{t('row.valued', { value: format.number(row.position.market_value), weight: weight(row) })}</p>
          <p className="flex flex-wrap items-center gap-x-1.5 text-xs sm:hidden">
            <span className="text-muted-foreground">{t('column.unrealized')}</span>
            <ChangeValue value={row.position.unrealized_pnl} format="absolute" fractionDigits={0} />
            {row.position.unrealized_return !== null && <ChangeValue value={row.position.unrealized_return} format="percent" />}
          </p>
          <p className="tabular text-xs text-pretty whitespace-normal text-muted-foreground xl:hidden">
            {t('row.closed', { price: format.price(row.position.mark_price), close: closed(row) })} · {revenue(row)}
          </p>
          {row.standing && <RankingScoreLine standing={row.standing} className="text-xs md:hidden" />}
        </div>
      ),
    },
    {
      key: 'held',
      header: t('column.held'),
      numeric: true,
      from: 'lg',
      cell: (row) => (
        <span className="inline-flex flex-col items-end leading-tight">
          <span>{shares(row)}</span>
          <span className="text-xs text-muted-foreground">{format.price(row.position.average_cost)}</span>
        </span>
      ),
    },
    {
      key: 'close',
      header: t('column.close'),
      numeric: true,
      from: 'xl',
      cell: (row) => (
        <span className="inline-flex flex-col items-end leading-tight">
          <span>{format.price(row.position.mark_price)}</span>
          <span className="text-xs text-muted-foreground">{closed(row)}</span>
        </span>
      ),
    },
    {
      key: 'value',
      header: t('column.value'),
      numeric: true,
      from: 'md',
      cell: (row) => (
        <span className="inline-flex flex-col items-end leading-tight">
          <span>{format.number(row.position.market_value)}</span>
          <span className="text-xs text-muted-foreground">{weight(row)}</span>
        </span>
      ),
    },
    {
      key: 'pnl',
      header: t('column.unrealized'),
      numeric: true,
      from: 'sm',
      cell: (row) => (
        <span className="flex flex-col items-end leading-tight">
          <ChangeValue value={row.position.unrealized_pnl} format="absolute" fractionDigits={0} />
          {row.position.unrealized_return !== null && <ChangeValue value={row.position.unrealized_return} format="percent" className="text-xs" />}
        </span>
      ),
    },
    ...(holdings.scored_share === null
      ? []
      : [{ key: 'score', header: t('column.score'), from: 'md', className: 'min-w-44', cell: (row) => (row.standing ? <RankingScoreLine standing={row.standing} /> : DASH) } satisfies Column<Holding>]),
    {
      key: 'revenue',
      header: t('column.revenue'),
      numeric: true,
      from: 'xl',
      cell: (row) => {
        const { figure, line } = revenueReading(row, t, format)
        return (
          <span className="inline-flex flex-col items-end leading-tight">
            <span>{figure}</span>
            {line && <span className="max-w-36 text-xs text-pretty whitespace-normal text-muted-foreground">{line}</span>}
          </span>
        )
      },
    },
    ...(rows.some((row) => row.source === 'manual')
      ? [
          {
            key: 'actions',
            header: t('column.actions'),
            quietHeader: true,
            className: 'w-11 text-right',
            cell: (row) =>
              row.source === 'manual' && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button" variant="ghost" size="icon" aria-label={t('action.manage', { name: name(row) })} className="relative z-10 text-muted-foreground">
                      <Ellipsis aria-hidden />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem className="min-h-11 md:min-h-0" onSelect={() => onEnter({ draft: draftOf(row), replaces: true })}>
                      <Pencil aria-hidden />
                      {t('action.change')}
                    </DropdownMenuItem>
                    <DropdownMenuItem className="min-h-11 md:min-h-0" variant="destructive" onSelect={() => setRemoving(row)}>
                      <Trash2 aria-hidden />
                      {t('action.remove')}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ),
          } satisfies Column<Holding>,
        ]
      : []),
  ]

  return (
    <Panel flush title={t('list.title')} description={t('list.question', { count: rows.length })}>
      {filter}
      <UnreadNote holdings={holdings} className="border-b" />
      {rows.length === 0 ? <StateBlock icon={Briefcase} title={t('list.none')} /> : <DataTable rows={rows} columns={columns} rowKey={holdingKey} label={t('list.title')} />}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t('remove.title', { name: removing ? name(removing) : '' })}
        description={t('remove.description')}
        cancel={t('form.cancel')}
        confirm={t('action.remove')}
        onConfirm={confirmRemoval}
        destructive
      />
    </Panel>
  )
}

type Translate = ReturnType<typeof useTranslation>['t']
type Format = ReturnType<typeof useFormat>

/**
 * The latest held month's revenue acceleration and how many months it has run above or below 1; a dash and one line
 * where there is none: a stock with no revenue held, such as an ETF, or too few months for the averages.
 */
function revenueReading(holding: Holding, t: Translate, format: Format): { figure: string; line: string | null } {
  const acceleration = holding.revenue?.acceleration ?? null
  if (acceleration === null) return { figure: DASH, line: t(holding.revenue ? 'revenue.short' : 'revenue.none') }
  const run = holding.accelerating_months ?? 0
  return { figure: `×${format.number(acceleration, 2)}`, line: run > 0 ? t('revenue.accelerating', { count: run }) : run < 0 ? t('revenue.slowing', { count: -run }) : null }
}

/** How many watched stocks the panel offers before it says how many more there are. */
const WATCHED_SHOWN = 12

/** The watched stocks not entered as a holding. Choosing one opens the entry form on that stock; it adds nothing by itself. */
function WatchedPanel({ stocks, onEnter }: { stocks: readonly WatchedStock[]; onEnter: (seed: EntrySeed) => void }) {
  const { t } = useTranslation('holdings')
  const [all, setAll] = useState(false)
  const shown = all ? stocks : stocks.slice(0, WATCHED_SHOWN)
  return (
    <Panel title={t('watched.title')} description={t('watched.question')}>
      <ul className="flex flex-wrap gap-2">
        {shown.map((stock) => (
          <li key={stock.stockId}>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label={t('watched.enter', { name: stock.name ?? stock.stockId })}
              onClick={() => onEnter({ draft: { ...EMPTY_DRAFT, stockId: stock.stockId }, replaces: false })}
            >
              <Plus aria-hidden />
              {stock.name ?? t('unknownName')}
              <span className="font-mono text-xs text-muted-foreground">{stock.stockId}</span>
            </Button>
          </li>
        ))}
        {!all && stocks.length > WATCHED_SHOWN && (
          <li>
            <Button type="button" variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setAll(true)}>
              {t('watched.more', { count: stocks.length - WATCHED_SHOWN })}
            </Button>
          </li>
        )}
      </ul>
    </Panel>
  )
}
