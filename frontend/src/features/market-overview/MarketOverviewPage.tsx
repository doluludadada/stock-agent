import type { UseQueryResult } from '@tanstack/react-query'
import { LineChart, SearchX } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import {
  isApiError,
  useIndexHistory,
  useMarketBreadth,
  useMostTraded,
  useStockHistory,
  type IndexHistory,
  type ListedStock,
  type MarketBreadth,
  type StockHistory,
} from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { HISTORY_BARS } from '@/shared/lib/chart-range'
import { directionOf } from '@/shared/lib/direction'
import { formatNumber, formatSignedPercent, useFormat } from '@/shared/lib/format'
import { isStockId } from '@/shared/lib/stock-ids'
import { cn } from '@/shared/lib/utils'
import { ArchiveWarmUp } from '@/shared/ui/archive-warm-up'
import { Badge } from '@/shared/ui/badge'
import { BreadthBar } from '@/shared/ui/breadth-bar'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { PriceTrend } from '@/shared/ui/price-trend'
import { ShowMore } from '@/shared/ui/show-more'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { StockPicker } from '@/shared/ui/stock-picker'
import { breadthMood, DEFAULT_INDEX, heatLevel, industryEnds, listedChange, rankIndustries, type HeatLevel, type IndustryBreadth, type TrendTarget } from './model'

interface MarketOverviewPageProps {
  /** The user's strategies, from the strategies feature. */
  strategy: ReactNode
}

/** Below 1280 px the most traded list opens with this many rows; from 1280 px, beside the heat map, it shows all. */
const MOST_TRADED_SHOWN = 5
/** The industries' narrow layout shows this many of the strongest and as many of the weakest. */
const INDUSTRY_ENDS_SHOWN = 3

/**
 * Two stacks from 1280 px, whose heights end together: the trend over the industries' heat map, and the session's
 * breadth, the most traded stocks and the strategy in use beside them. Narrower, the stacks dissolve into one grid in
 * reading order: the trend and the breadth across, the industries beside the most traded stocks from 768 px, then the
 * strategy. The panels that move out of DOM order hold no control, so the keyboard order still matches the screen.
 * The research target is part of the address (`/?target=2330`); without one, the trend is the TAIEX.
 */
export function MarketOverviewPage({ strategy }: MarketOverviewPageProps) {
  const { t } = useTranslation('overview')
  const format = useFormat()
  const [params, setParams] = useSearchParams()
  const asked = params.get('target')?.toUpperCase() ?? ''
  const target: TrendTarget = isStockId(asked) ? { kind: 'stock', id: asked } : { kind: 'index', index: DEFAULT_INDEX }
  const mostTraded = useMostTraded()
  const breadth = useMarketBreadth()
  const indexHistory = useIndexHistory(DEFAULT_INDEX, HISTORY_BARS, target.kind === 'index')
  const stockHistory = useStockHistory(asked, HISTORY_BARS, target.kind === 'stock')
  const history: UseQueryResult<IndexHistory | StockHistory> = target.kind === 'index' ? indexHistory : stockHistory
  const session = mostTraded.data?.[0]?.today?.ts ?? breadth.data?.session_close ?? history.data?.bars.at(-1)?.ts
  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader title={t('title')} description={session && t('session', { date: format.date(session, 'long') })} />
      <ArchiveWarmUp />
      <div className="grid gap-4 md:grid-cols-2 lg:gap-5 xl:grid-cols-[minmax(0,1fr)_26rem] xl:items-start">
        <div className="contents xl:flex xl:min-w-0 xl:flex-col xl:gap-5">
          <TrendPanel target={target} history={history} onTarget={(id) => setParams({ target: id })} />
          <IndustryPanel breadth={breadth} />
        </div>
        <div className="contents xl:flex xl:min-w-0 xl:flex-col xl:gap-5">
          <BreadthPanel breadth={breadth} />
          <MostTradedPanel mostTraded={mostTraded} />
          <div className="order-5 min-w-0 md:col-span-2">{strategy}</div>
        </div>
      </div>
    </div>
  )
}

function TrendPanel({ target, history, onTarget }: { target: TrendTarget; history: UseQueryResult<IndexHistory | StockHistory>; onTarget: (id: string) => void }) {
  const { t } = useTranslation('overview')
  const listedName = history.data && 'stock' in history.data ? history.data.stock.name : null
  const name = target.kind === 'index' ? t(`index.${target.index}`) : (listedName ?? target.id)

  const title =
    target.kind === 'index' ? (
      <>
        {name}
        <Badge variant="outline" className="font-normal text-muted-foreground">
          {t('target.index')} · {t('target.default')}
        </Badge>
      </>
    ) : (
      <>
        <Link to={paths.stock(target.id)} className="hover:text-brand">
          {name}
        </Link>
        {listedName && <span className="font-mono text-xs font-normal text-muted-foreground">{target.id}</span>}
      </>
    )

  return (
    <Panel
      className="order-1 md:col-span-2"
      title={title}
      description={t('trend.question')}
      aside={
        <>
          {target.kind === 'stock' && (
            <Button asChild variant="ghost" size="sm">
              <Link to={paths.market}>{t('target.reset', { name: t('index.taiex') })}</Link>
            </Button>
          )}
          <StockPicker label={t('target.change')} onSelect={onTarget} />
        </>
      }
    >
      {history.isPending ? (
        <Skeleton className="h-[calc(var(--chart-price-height)+var(--chart-volume-height)+9rem)] rounded-xl" />
      ) : target.kind === 'stock' && isApiError(history.error, 'notFound') ? (
        <StateBlock icon={SearchX} title={t('target.notFound', { id: target.id })} />
      ) : !history.data ? (
        <ErrorState error={history.error} title={t('trend.failed')} onRetry={() => void history.refetch()} />
      ) : (
        <PriceTrend key={target.kind === 'index' ? target.index : target.id} bars={history.data.bars} name={name} kind={target.kind === 'index' ? 'index' : 'price'} />
      )}
    </Panel>
  )
}

const MOOD_TONE = { broadUp: 'text-up', leaningUp: 'text-up', mixed: 'text-foreground', leaningDown: 'text-down', broadDown: 'text-down' } as const

/** How broad the session's move was: one phrase for it, the split as a bar, and the counts. */
function BreadthPanel({ breadth }: { breadth: UseQueryResult<MarketBreadth> }) {
  const { t } = useTranslation('overview')
  const locale = useLocale()
  const format = useFormat()
  const market = breadth.data?.market
  const total = market ? market.advancers + market.decliners + market.unchanged : 0

  return (
    <Panel
      className="order-2 md:col-span-2"
      title={t('breadth.title')}
      description={breadth.data && t('breadth.question', { total: formatNumber(locale, total), date: format.monthDay(breadth.data.session_close) })}
    >
      {breadth.isPending ? (
        <Skeleton className="h-28 rounded-xl" />
      ) : !market ? (
        <ErrorState error={breadth.error} title={t('breadth.failed')} onRetry={() => void breadth.refetch()} />
      ) : (
        <div className="grid items-center gap-x-8 gap-y-4 @xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 @xl:flex-col @xl:gap-1">
            <p className={cn('text-figure-sm font-semibold', MOOD_TONE[breadthMood(market)])}>{t(`breadth.mood.${breadthMood(market)}`)}</p>
            <p className="text-xs text-muted-foreground">
              {t('breadth.average')} <ChangeValue value={market.average_change_percent / 100} format="percent" className="text-sm" />
            </p>
          </div>
          <div className="space-y-4">
          <BreadthBar up={market.advancers} flat={market.unchanged} down={market.decliners} />
          <dl className="grid grid-cols-3 gap-3">
            <Stat label={t('breadth.advancers')}>
              <span className="text-up">{formatNumber(locale, market.advancers)}</span>
            </Stat>
            <Stat label={t('breadth.unchanged')} className="text-center">
              <span className="text-flat">{formatNumber(locale, market.unchanged)}</span>
            </Stat>
            <Stat label={t('breadth.decliners')} className="text-right">
              <span className="text-down">{formatNumber(locale, market.decliners)}</span>
            </Stat>
          </dl>
          </div>
        </div>
      )}
    </Panel>
  )
}

/**
 * Which industries moved most. A wide card shows every industry as a heat map, strongest first; a narrow one names
 * both ends of the ranking by their sign, with all of them on request.
 */
function IndustryPanel({ breadth }: { breadth: UseQueryResult<MarketBreadth> }) {
  const { t } = useTranslation('overview')
  const ranked = useMemo(() => rankIndustries(breadth.data?.industries ?? {}), [breadth.data])
  return (
    <Panel className="order-3" title={t('industries.title')} description={ranked.length > 0 ? t('industries.question', { count: ranked.length }) : undefined}>
      {breadth.isPending ? (
        <Skeleton className="h-56 rounded-xl" />
      ) : !breadth.data ? (
        <ErrorState error={breadth.error} title={t('breadth.failed')} onRetry={() => void breadth.refetch()} />
      ) : ranked.length === 0 ? (
        <StateBlock icon={LineChart} title={t('noData')} description={t('industries.none')} />
      ) : (
        <>
          <HeatMap ranked={ranked} />
          <IndustryEnds ranked={ranked} />
        </>
      )}
    </Panel>
  )
}

/** Each step's tint of the market color; the strongest stays readable under ink text (tokens.test.ts). */
const HEAT: Record<'up' | 'down' | 'flat', Record<HeatLevel, string>> = {
  up: { 0: 'bg-up/6', 1: 'bg-up/12', 2: 'bg-up/20', 3: 'bg-up/30', 4: 'bg-up/40' },
  down: { 0: 'bg-down/6', 1: 'bg-down/12', 2: 'bg-down/20', 3: 'bg-down/30', 4: 'bg-down/40' },
  flat: { 0: 'bg-muted', 1: 'bg-muted', 2: 'bg-muted', 3: 'bg-muted', 4: 'bg-muted' },
}

function HeatMap({ ranked }: { ranked: IndustryBreadth[] }) {
  const { t } = useTranslation('overview')
  const locale = useLocale()
  return (
    <ol aria-label={t('industries.title')} className="hidden grid-cols-3 gap-1.5 @xl:grid @2xl:grid-cols-4 @5xl:grid-cols-5">
      {ranked.map((industry) => {
        const direction = directionOf(industry.average_change_percent)
        return (
          <li key={industry.industry} className={cn('min-w-0 rounded-lg px-2.5 py-2', HEAT[direction][heatLevel(industry.average_change_percent)])}>
            <p className="truncate text-xs font-medium" title={industry.industry}>
              {industry.industry}
            </p>
            <p className="tabular mt-0.5 flex items-baseline justify-between gap-2">
              <span className="text-sm font-semibold">
                <span className="sr-only">{t(`common:direction.${direction}`)} </span>
                {formatSignedPercent(locale, industry.average_change_percent / 100)}
              </span>
              <span className="truncate text-[0.6875rem] text-muted-foreground">
                {t('industries.moves', { up: formatNumber(locale, industry.advancers), down: formatNumber(locale, industry.decliners) })}
              </span>
            </p>
          </li>
        )
      })}
    </ol>
  )
}

/** Both ends of the ranking, each named by its sign, and every industry on request. */
function IndustryEnds({ ranked }: { ranked: IndustryBreadth[] }) {
  const { t } = useTranslation('overview')
  const [expanded, setExpanded] = useState(false)
  const collapsible = ranked.length > INDUSTRY_ENDS_SHOWN * 2
  const ends = industryEnds(ranked, INDUSTRY_ENDS_SHOWN)
  const groups = !expanded && collapsible ? [ends.top, ends.bottom] : [{ label: null, rows: ranked }]
  const widest = Math.max(...ranked.map((row) => Math.abs(row.average_change_percent)), 0.01)

  return (
    <div className="-mx-4 -mb-4 @xl:hidden md:-mx-5 md:-mb-5">
      <table id="industry-ranking" aria-label={t('industries.title')} className="w-full text-sm">
        <thead className="sr-only">
          <tr>
            <th scope="col">{t('industries.column.industry')}</th>
            <th scope="col">{t('industries.column.moves')}</th>
            <th scope="col">{t('industries.column.average')}</th>
          </tr>
        </thead>
        {groups.map((group) => (
          <tbody key={group.label ?? 'all'} className="[&_tr+tr]:border-t">
            {group.label && (
              <tr>
                <th scope="rowgroup" colSpan={3} className="eyebrow border-y bg-muted/60 px-4 py-1.5 text-left md:px-5">
                  {t(`industries.ends.${group.label}`)}
                </th>
              </tr>
            )}
            {group.rows.map((row) => (
              <IndustryRow key={row.industry} row={row} widest={widest} />
            ))}
          </tbody>
        ))}
      </table>
      {collapsible && (
        <div className="border-t p-1.5">
          <ShowMore
            expanded={expanded}
            onToggle={() => setExpanded(!expanded)}
            controls="industry-ranking"
            moreLabel={t('industries.showAll', { count: ranked.length })}
            lessLabel={t('industries.showLess')}
          />
        </div>
      )}
    </div>
  )
}

function IndustryRow({ row, widest }: { row: IndustryBreadth; widest: number }) {
  const locale = useLocale()
  const direction = directionOf(row.average_change_percent)
  return (
    <tr className="h-11">
      <td className="max-w-0 truncate pl-4 md:pl-5" title={row.industry}>
        {row.industry}
      </td>
      <td className="tabular w-20 pr-3 text-right text-xs whitespace-nowrap">
        <span className="text-up">{formatNumber(locale, row.advancers)}</span>
        <span className="text-muted-foreground"> / </span>
        <span className="text-down">{formatNumber(locale, row.decliners)}</span>
      </td>
      <td className="w-32 pr-4 md:pr-5">
        <span className="flex items-center justify-end gap-3">
          <span aria-hidden className="hidden h-1.5 w-10 overflow-hidden rounded-full bg-muted sm:block">
            <span
              className={cn('block h-full min-w-1 rounded-full', direction === 'up' ? 'bg-up' : direction === 'down' ? 'bg-down' : 'bg-flat')}
              style={{ width: `${(Math.abs(row.average_change_percent) / widest) * 100}%` }}
            />
          </span>
          <ChangeValue value={row.average_change_percent / 100} format="percent" className="w-16 justify-end" />
        </span>
      </td>
    </tr>
  )
}

/** Where the volume went in the latest session: each stock's close, its change against the reference and its lots. */
function MostTradedPanel({ mostTraded }: { mostTraded: UseQueryResult<ListedStock[]> }) {
  const { t } = useTranslation('overview')
  const format = useFormat()
  const [expanded, setExpanded] = useState(false)
  const stocks = mostTraded.data ?? []
  const session = stocks[0]?.today?.ts
  const folded = new Set(expanded ? [] : stocks.slice(MOST_TRADED_SHOWN).map((stock) => stock.stock_id))
  const columns: Column<ListedStock>[] = [
    {
      key: 'rank',
      header: t('mostTraded.column.rank'),
      quietHeader: true,
      numeric: true,
      className: 'w-8 pr-0 text-xs text-muted-foreground',
      cell: (_, index) => index + 1,
    },
    {
      key: 'stock',
      header: t('mostTraded.column.stock'),
      className: 'w-full max-w-0',
      cell: (stock) => (
        <Link to={paths.stock(stock.stock_id)} className="stretched-link block min-w-0 hover:text-brand focus-visible:text-brand">
          <span className="block truncate font-medium" title={stock.name ?? undefined}>
            {stock.name ?? stock.stock_id}
          </span>
          <span className="block font-mono text-xs text-muted-foreground">{stock.stock_id}</span>
        </Link>
      ),
    },
    { key: 'close', header: t('mostTraded.column.close'), numeric: true, cell: (stock) => (stock.today ? format.price(stock.today.close) : '—') },
    {
      key: 'change',
      header: t('mostTraded.column.change'),
      numeric: true,
      cell: (stock) => {
        const change = listedChange(stock.today)
        return change ? <ChangeValue value={change.ratio} format="percent" /> : '—'
      },
    },
    {
      key: 'volume',
      header: t('mostTraded.column.volume'),
      numeric: true,
      from: 'xl',
      className: 'text-muted-foreground',
      cell: (stock) => (stock.today ? format.lots(stock.today.volume) : '—'),
    },
  ]

  return (
    <Panel
      className="order-4"
      title={t('mostTraded.title')}
      description={session && t('mostTraded.question', { date: format.monthDay(session) })}
      flush
      footerClassName="xl:hidden"
      footer={
        stocks.length > MOST_TRADED_SHOWN && (
          <ShowMore
            expanded={expanded}
            onToggle={() => setExpanded(!expanded)}
            controls="most-traded"
            moreLabel={t('mostTraded.showAll', { count: stocks.length })}
            lessLabel={t('mostTraded.showLess')}
          />
        )
      }
    >
      {mostTraded.isPending ? (
        <Skeleton className="m-4 h-64 rounded-xl" />
      ) : stocks.length === 0 ? (
        mostTraded.error ? (
          <ErrorState error={mostTraded.error} title={t('mostTraded.failed')} onRetry={() => void mostTraded.refetch()} />
        ) : (
          <StateBlock icon={LineChart} title={t('noData')} description={t('mostTraded.empty')} />
        )
      ) : (
        <DataTable
          id="most-traded"
          rows={stocks}
          columns={columns}
          rowKey={(stock) => stock.stock_id}
          label={t('mostTraded.title')}
          rowClassName={(stock) => (folded.has(stock.stock_id) ? 'hidden xl:table-row' : undefined)}
        />
      )}
    </Panel>
  )
}
