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
import { formatCompact, formatMonthDay, formatNumber, formatPrice, useFormat } from '@/shared/lib/format'
import { isStockId } from '@/shared/lib/stock-ids'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { PriceTrend } from '@/shared/ui/price-trend'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { StockPicker } from '@/shared/ui/stock-picker'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { breadthShares, DEFAULT_INDEX, rankIndustries, type TrendTarget } from './model'

interface MarketOverviewPageProps {
  /** The owner's strategies, from the strategies feature. */
  strategy: ReactNode
}

const MOST_TRADED_SHOWN = 10
/** Collapsed, the industry list shows this many of the strongest and as many of the weakest. */
const INDUSTRY_ENDS_SHOWN = 4

/**
 * The research target is part of the address (`/?target=2330`), so it survives a reload and can be shared. Without
 * one, the trend is the TAIEX.
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
    <div className="space-y-4">
      <PageHeader title={t('title')} description={session && t('session', { date: format.date(session, 'long') })} />
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <TrendPanel target={target} history={history} onTarget={(id) => setParams({ target: id })} />
        <div className="grid items-start gap-4 lg:grid-cols-2 xl:grid-cols-1">
          <MostTradedPanel mostTraded={mostTraded} />
          <BreadthPanel breadth={breadth} />
        </div>
      </div>
      {strategy}
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
        <Badge variant="outline" className="font-normal">
          {t('target.index')} · {t('target.default')}
        </Badge>
      </>
    ) : (
      <>
        <Link to={paths.stock(target.id)} className="hover:text-primary">
          {name}
        </Link>
        {listedName && <span className="font-mono text-xs font-normal text-muted-foreground">{target.id}</span>}
      </>
    )

  return (
    <Panel
      title={title}
      aside={
        <>
          {target.kind === 'stock' && (
            <Button asChild variant="ghost" size="sm">
              <Link to={paths.overview}>{t('target.reset', { name: t('index.taiex') })}</Link>
            </Button>
          )}
          <StockPicker label={t('target.change')} onSelect={onTarget} />
        </>
      }
    >
      {history.isPending ? (
        <Skeleton className="h-[444px] rounded-lg" />
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

/** The listing's latest session: how many stocks rose, fell and held, and the same per industry. */
function BreadthPanel({ breadth }: { breadth: UseQueryResult<MarketBreadth> }) {
  const { t } = useTranslation('overview')
  const locale = useLocale()
  const data = breadth.data

  return (
    <Panel title={t('breadth.title')} aside={data && <span className="tabular">{formatMonthDay(locale, data.session_close)}</span>} flush>
      {breadth.isPending ? (
        <div className="space-y-2 p-4" aria-hidden>
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-6 rounded" />
          ))}
        </div>
      ) : !data ? (
        <ErrorState error={breadth.error} title={t('breadth.failed')} onRetry={() => void breadth.refetch()} />
      ) : (
        <>
          <MarketCounts breadth={data} />
          <IndustryTable industries={data.industries} />
        </>
      )}
    </Panel>
  )
}

function MarketCounts({ breadth }: { breadth: MarketBreadth }) {
  const { t } = useTranslation('overview')
  const locale = useLocale()
  const { advancers, decliners, unchanged, average_change_percent } = breadth.market
  const shares = breadthShares(breadth.market)

  return (
    <div className="space-y-3 border-b p-4">
      <dl className="grid grid-cols-4 gap-3">
        <Stat label={t('breadth.advancers')}>
          <span className="text-up">{formatNumber(locale, advancers)}</span>
        </Stat>
        <Stat label={t('breadth.decliners')}>
          <span className="text-down">{formatNumber(locale, decliners)}</span>
        </Stat>
        <Stat label={t('breadth.unchanged')}>
          <span className="text-flat">{formatNumber(locale, unchanged)}</span>
        </Stat>
        <Stat label={t('breadth.average')}>
          <ChangeValue value={average_change_percent / 100} format="percent" />
        </Stat>
      </dl>
      <div aria-hidden className="flex h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="bg-up" style={{ width: `${shares.up}%` }} />
        <div className="bg-flat" style={{ width: `${shares.flat}%` }} />
        <div className="bg-down" style={{ width: `${shares.down}%` }} />
      </div>
    </div>
  )
}

function IndustryTable({ industries }: { industries: MarketBreadth['industries'] }) {
  const { t } = useTranslation('overview')
  const locale = useLocale()
  const [expanded, setExpanded] = useState(false)
  const ranked = useMemo(() => rankIndustries(industries), [industries])
  const collapsed = !expanded && ranked.length > INDUSTRY_ENDS_SHOWN * 2
  const rows = collapsed ? [...ranked.slice(0, INDUSTRY_ENDS_SHOWN), null, ...ranked.slice(-INDUSTRY_ENDS_SHOWN)] : ranked

  if (ranked.length === 0) return <StateBlock icon={LineChart} title={t('noData')} description={t('breadth.noIndustries')} />

  return (
    <>
      <Table id="industry-breadth" aria-label={t('breadth.sectors')}>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>{t('breadth.column.industry')}</TableHead>
            <TableHead className="text-right">{t('breadth.column.moves')}</TableHead>
            <TableHead className="text-right">{t('breadth.column.average')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) =>
            row === null ? (
              <TableRow key="gap" aria-hidden className="hover:bg-transparent">
                <TableCell colSpan={3} className="py-0 text-center text-xs text-muted-foreground">
                  ⋯
                </TableCell>
              </TableRow>
            ) : (
              <TableRow key={row.industry}>
                <TableCell className="max-w-0 w-full truncate py-1.5">{row.industry}</TableCell>
                <TableCell className="tabular py-1.5 text-right text-xs">
                  <span className="text-up">{formatNumber(locale, row.advancers)}</span>
                  <span className="text-muted-foreground"> / </span>
                  <span className="text-down">{formatNumber(locale, row.decliners)}</span>
                </TableCell>
                <TableCell className="py-1.5 text-right">
                  <ChangeValue value={row.average_change_percent / 100} format="percent" />
                </TableCell>
              </TableRow>
            ),
          )}
        </TableBody>
      </Table>
      {ranked.length > INDUSTRY_ENDS_SHOWN * 2 && (
        <div className="border-t p-1">
          <Button type="button" variant="ghost" size="sm" className="w-full" aria-expanded={expanded} aria-controls="industry-breadth" onClick={() => setExpanded(!expanded)}>
            {expanded ? t('breadth.showLess') : t('breadth.showAll', { count: ranked.length })}
          </Button>
        </div>
      )}
    </>
  )
}

function MostTradedPanel({ mostTraded }: { mostTraded: UseQueryResult<ListedStock[]> }) {
  const { t } = useTranslation('overview')
  const locale = useLocale()
  const [expanded, setExpanded] = useState(false)
  const stocks = mostTraded.data ?? []
  const shown = expanded ? stocks : stocks.slice(0, MOST_TRADED_SHOWN)
  const session = stocks[0]?.today?.ts
  const row = 'grid grid-cols-[1.25rem_3rem_minmax(0,1fr)_4.25rem_4.75rem] items-center gap-2 px-4'

  return (
    <Panel title={t('mostTraded.title')} aside={session && <span className="tabular">{formatMonthDay(locale, session)}</span>} flush>
      {mostTraded.isPending ? (
        <div className="space-y-2 p-4" aria-hidden>
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-6 rounded" />
          ))}
        </div>
      ) : stocks.length === 0 ? (
        mostTraded.error ? (
          <ErrorState error={mostTraded.error} title={t('mostTraded.failed')} onRetry={() => void mostTraded.refetch()} />
        ) : (
          <StateBlock icon={LineChart} title={t('noData')} description={t('mostTraded.empty')} />
        )
      ) : (
        <>
          <div aria-hidden className={`${row} h-8 border-b text-xs text-muted-foreground`}>
            <span />
            <span className="col-span-2">{t('mostTraded.column.stock')}</span>
            <span className="text-right">{t('mostTraded.column.close')}</span>
            <span className="text-right">{t('mostTraded.column.volume')}</span>
          </div>
          <ol id="most-traded-list" className="py-1">
            {shown.map((stock, index) => (
              <li key={stock.stock_id}>
                <Link to={paths.stock(stock.stock_id)} className={`${row} group h-9 text-sm outline-none hover:bg-muted/50 focus-visible:bg-muted/50`}>
                  <span className="tabular text-right text-xs text-muted-foreground">{index + 1}</span>
                  <span className="font-mono text-xs text-muted-foreground">{stock.stock_id}</span>
                  <span className="truncate group-hover:text-primary">{stock.name ?? stock.stock_id}</span>
                  <span className="tabular text-right">{stock.today ? formatPrice(locale, stock.today.close) : '—'}</span>
                  <span className="tabular text-right text-xs text-muted-foreground">{stock.today ? formatCompact(locale, stock.today.volume) : '—'}</span>
                </Link>
              </li>
            ))}
          </ol>
          {stocks.length > MOST_TRADED_SHOWN && (
            <div className="border-t p-1">
              <Button type="button" variant="ghost" size="sm" className="w-full" aria-expanded={expanded} aria-controls="most-traded-list" onClick={() => setExpanded(!expanded)}>
                {expanded ? t('mostTraded.showLess') : t('mostTraded.showAll', { count: stocks.length })}
              </Button>
            </div>
          )}
        </>
      )}
    </Panel>
  )
}
