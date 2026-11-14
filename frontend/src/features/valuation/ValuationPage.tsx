import { Calculator, Info, Radar, Sparkles, TriangleAlert } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { useErrorReason } from '@/shared/lib/error-reason'
import { DASH, useFormat } from '@/shared/lib/format'
import { isAcceptedList, parseStockIds } from '@/shared/lib/stock-ids'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { StockIdsProblem } from '@/shared/ui/stock-ids-problem'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Segmented } from '@/shared/ui/segmented'
import { useExplaining, useExplanation, useMarketValuation, useValuationScan, useValuedStocks, type ValuationReport } from './api'
import { DEFAULT_MIN_UNDERVALUATION_PERCENT, DEFAULT_TARGET_PE, parseMinUndervaluation, parseTargetPe } from './model'

const TABS = ['stocks', 'scan'] as const

export function ValuationPage() {
  const { t } = useTranslation('valuation')
  const [tab, setTab] = useState<(typeof TABS)[number]>('stocks')
  return (
    <div className="page-stack">
      <div className="space-y-3">
        <PageHeader title={t('title')} />
        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <Info aria-hidden className="mt-px size-3.5 shrink-0 text-gold" />
          {t('notAdvice')}
        </p>
      </div>
      <RequireSignIn layout="page" reason={t('signIn')}>
        <div className="card-grid xl:grid-cols-[minmax(0,1fr)_22rem]">
          <MarketReference className="xl:col-start-2 xl:row-start-1" />
          <Panel className="xl:col-start-1 xl:row-span-2 xl:row-start-1" title={t('toolTitle')}>
            <div className="space-y-4">
              <Segmented value={tab} onChange={setTab} label={t('toolTitle')} options={TABS.map((value) => ({ value, label: t(`tab.${value}`) }))} />
              {/* Both stay mounted, so what was typed and found in one is still there after a look at the other. */}
              <section aria-label={t('tab.stocks')} hidden={tab !== 'stocks'}>
                <SpecificStocks />
              </section>
              <section aria-label={t('tab.scan')} hidden={tab !== 'scan'}>
                <Scan />
              </section>
            </div>
          </Panel>
          <HowPanel className="xl:col-start-2 xl:row-start-2" />
        </div>
      </RequireSignIn>
    </div>
  )
}

/** How the page's figures are made, beside the tool on a wide screen and under it on a phone. */
function HowPanel({ className }: { className?: string }) {
  const { t } = useTranslation('valuation')
  return (
    <Panel fold="always" className={className} title={t('how.title')}>
      <ul className="space-y-3 text-sm text-pretty text-muted-foreground">
        <li>{t('how.fair')}</li>
        <li>{t('formula')}</li>
        <li>{t('how.scenarios')}</li>
        <li>{t('lowPeCaveat')}</li>
        <li>{t('how.ai')}</li>
      </ul>
    </Panel>
  )
}

function MarketReference({ className }: { className?: string }) {
  const { t } = useTranslation('valuation')
  const format = useFormat()
  const market = useMarketValuation()
  return (
    <Panel className={className} title={t('marketTitle')} description={market.data && t('lastSession', { date: format.date(market.data.last_closed_session) })}>
      {market.isPending ? (
        <p className="text-sm text-muted-foreground">{t('loadingMarket')}</p>
      ) : market.isError ? (
        <ErrorState error={market.error} title={t('marketFailed')} onRetry={() => void market.refetch()} />
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-4 @md:grid-cols-3 @lg:gap-x-6">
            <Stat label={t('valued')} size="lg">
              {format.number(market.data.valued_stocks)}
            </Stat>
            <Stat label={t('medianPe')} size="lg">
              {market.data.median_pe ? format.number(market.data.median_pe.value, 2) : DASH}
            </Stat>
            <Stat label={t('medianSample')} size="lg">
              {market.data.median_pe ? format.number(market.data.median_pe.sample_size) : DASH}
            </Stat>
          </dl>
          {market.data.source_warnings.length > 0 && (
            <p className="mt-3 flex items-start gap-1.5 text-xs text-gold">
              <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
              {market.data.source_warnings.join(' · ')}
            </p>
          )}
        </>
      )}
    </Panel>
  )
}

function SpecificStocks() {
  const { t } = useTranslation('valuation')
  const [ids, setIds] = useState('')
  const [pe, setPe] = useState(DEFAULT_TARGET_PE)
  const [request, setRequest] = useState<{ stockIds: string[]; targetPe: number | null } | null>(null)
  const result = useValuedStocks(request)
  const list = parseStockIds(ids)
  const targetPe = pe.trim() === '' ? null : parseTargetPe(pe)
  const valid = isAcceptedList(list) && (pe.trim() === '' || targetPe !== null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (valid) setRequest({ stockIds: list.ids, targetPe })
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div className="grid w-full gap-1.5 sm:w-auto">
          <Label htmlFor="valuation-ids">{t('stockIds')}</Label>
          <Input id="valuation-ids" value={ids} onChange={(event) => setIds(event.target.value)} placeholder="2330, 2317" className="w-full font-mono sm:w-60" aria-describedby="valuation-ids-problem" />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="valuation-pe">{t('targetPe')}</Label>
          <Input id="valuation-pe" inputMode="decimal" value={pe} onChange={(event) => setPe(event.target.value)} className="w-24" />
        </div>
        <Button type="submit" disabled={!valid || result.isFetching}>
          <Calculator aria-hidden />
          {t('value')}
        </Button>
        <StockIdsProblem id="valuation-ids-problem" list={list} />
      </form>
      {!request && <StateBlock icon={Calculator} title={t('start.stocks.title')} description={t('start.stocks.description')} className="rounded-xl bg-muted/50 py-10" />}
      {result.isFetching && <p className="text-sm text-muted-foreground">{t('loadingValuation')}</p>}
      {result.isError && <ErrorState error={result.error} title={t('valueFailed')} onRetry={() => void result.refetch()} className="rounded-xl border" />}
      {result.data && result.data.reports.length === 0 && <StateBlock icon={Calculator} title={t('noneFound')} className="rounded-xl border" />}
      {result.data && result.data.reports.length > 0 && (
        <div className="grid items-start gap-4 @3xl:grid-cols-2">
          {result.data.reports.map((report) => (
            <ReportCard key={report.valuation.stock.stock_id} report={report} />
          ))}
        </div>
      )}
    </div>
  )
}

function Scan() {
  const { t } = useTranslation('valuation')
  const format = useFormat()
  const [pe, setPe] = useState(DEFAULT_TARGET_PE)
  const [minimum, setMinimum] = useState(DEFAULT_MIN_UNDERVALUATION_PERCENT)
  const [request, setRequest] = useState<{ targetPe: number; minUndervaluation: number; technical: boolean } | null>(null)
  const scan = useValuationScan(request)
  const explaining = useExplaining()
  const targetPe = parseTargetPe(pe)
  const minUndervaluation = parseMinUndervaluation(minimum)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (targetPe !== null && minUndervaluation !== null) setRequest({ targetPe, minUndervaluation, technical: false })
  }

  const eliminated = scan.data ? Object.entries(scan.data.eliminated.valuation ?? {}) : []
  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="scan-pe">{t('targetPe')}</Label>
          <Input id="scan-pe" inputMode="decimal" value={pe} onChange={(event) => setPe(event.target.value)} className="w-24" />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="scan-min">{t('minUndervaluation')}</Label>
          <Input id="scan-min" inputMode="decimal" value={minimum} onChange={(event) => setMinimum(event.target.value)} className="w-24" />
        </div>
        <Button type="submit" disabled={targetPe === null || minUndervaluation === null || scan.isFetching}>
          {t('scan')}
        </Button>
        <p className="w-full text-xs text-muted-foreground">{t('formula')}</p>
      </form>
      {!request && <StateBlock icon={Radar} title={t('start.scan.title')} description={t('start.scan.description')} className="rounded-xl bg-muted/50 py-10" />}
      {scan.isFetching && <p className="text-sm text-muted-foreground">{t(request?.technical ? 'loadingTechnical' : 'loadingMarket')}</p>}
      {scan.isError && <ErrorState error={scan.error} title={t('scanFailed')} onRetry={() => void scan.refetch()} className="rounded-xl border" />}
      {scan.data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <p>
              {t('survivors', { count: scan.data.survivors.length })}{' '}
              {eliminated.length > 0 && (
                <span className="text-muted-foreground">
                  {t('eliminatedAt')} {eliminated.map(([reason, count]) => `${t(`elimination.${reason}`)} ${format.number(count ?? 0)}`).join(' · ')}
                </span>
              )}
            </p>
            {scan.data.technical_strategy_id === null ? (
              scan.data.survivors.length > 0 && (
                <Button type="button" variant="outline" size="sm" onClick={() => request && setRequest({ ...request, technical: true })} disabled={scan.isFetching || explaining}>
                  {t('confirmTechnical', { count: scan.data.survivors.length })}
                </Button>
              )
            ) : (
              <p className="text-xs text-muted-foreground">{t('technicalApplied', { count: Object.keys(scan.data.technical_failures).length })}</p>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{t('lowPeCaveat')}</p>
          <div className="grid items-start gap-4 @3xl:grid-cols-2">
            {scan.data.survivors.map((report) => (
              <ReportCard
                key={report.valuation.stock.stock_id}
                report={report}
                explain={scan.data.explanation_candidates.includes(report.valuation.stock.stock_id) ? scan.data.criteria.target_pe : undefined}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ReportCard({
  report,
  explain,
}: {
  report: ValuationReport
  /** The target P/E an AI explanation is asked for; set only for the scan's explanation candidates. */
  explain?: number
}) {
  const { t } = useTranslation('valuation')
  const format = useFormat()
  const { valuation } = report
  const industryMedian = valuation.industry_median_pe
  const eps = valuation.eps
  const scenarios = typeof report.fair_value === 'string' ? null : report.fair_value
  return (
    <Panel
      title={
        <Link to={paths.stock(valuation.stock.stock_id)} className="flex items-baseline gap-2 hover:text-primary">
          <span className="font-mono text-xs font-normal text-muted-foreground">{valuation.stock.stock_id}</span>
          {valuation.stock.name}
        </Link>
      }
      aside={
        report.undervaluation !== null && (
          <span className={cn('tabular text-sm font-semibold', report.undervaluation > 0 ? 'text-brand' : 'text-foreground')}>{format.signedPercent(report.undervaluation, 1)}</span>
        )
      }
    >
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">{t('close')}</dt>
        <dd className="tabular text-right">
          {valuation.close ? `${format.price(valuation.close.close)} · ${format.date(valuation.close.ts)}` : t('noClose')}
          {!valuation.close_is_fresh && <span className="ml-1 text-gold">{t('staleClose')}</span>}
        </dd>
        <dt className="text-muted-foreground">{t('eps')}</dt>
        <dd className="tabular text-right">{'value' in eps ? `${format.number(eps.value, 2)} · ${eps.period_label} · ${t(`epsKind.${eps.kind}`)}` : t(`epsUnavailable.${eps.reason}`)}</dd>
        <dt className="text-muted-foreground">{t('currentPe')}</dt>
        <dd className="tabular text-right">{typeof valuation.current_pe === 'string' ? t(`peNotApplicable.${valuation.current_pe}`) : format.number(valuation.current_pe.value, 2)}</dd>
        {industryMedian && (
          <>
            <dt className="text-muted-foreground">{t('industryMedian', { industry: valuation.stock.industry })}</dt>
            <dd className="tabular text-right">{format.number(industryMedian.value, 2)}</dd>
          </>
        )}
      </dl>
      {scenarios ? (
        <dl className="mt-3 grid grid-cols-3 divide-x rounded-lg border text-center">
          {(['conservative', 'base', 'optimistic'] as const).map((name) => (
            <div key={name} className="px-2 py-2">
              <dt className="text-xs text-muted-foreground">{t(`scenario.${name}`, { pe: format.number(scenarios[name].target_pe, 1) })}</dt>
              <dd className="tabular text-sm font-semibold">{format.price(scenarios[name].fair_price)}</dd>
              <dd className="tabular text-xs text-muted-foreground">{format.signedPercent(scenarios[name].undervaluation, 1)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        report.target_pe !== null && <p className="mt-3 text-xs text-muted-foreground">{t('noFairPrice', { reason: t(`peNotApplicable.${report.fair_value}`) })}</p>
      )}
      {valuation.warnings.length > 0 && <p className="mt-3 text-xs text-gold">{valuation.warnings.join(' · ')}</p>}
      {explain !== undefined && <ExplainButton stockId={valuation.stock.stock_id} targetPe={explain} />}
    </Panel>
  )
}

function ExplainButton({ stockId, targetPe }: { stockId: string; targetPe: number }) {
  const { t } = useTranslation('valuation')
  const { explanation, pending, ask } = useExplanation(stockId, targetPe)
  const [asking, setAsking] = useState(false)
  const reason = useErrorReason()

  const run = () => {
    setAsking(false)
    ask(undefined, { onError: (error) => toast.error(t('explainFailed', { reason: reason(error) })) })
  }

  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      {explanation ? (
        <dl className="space-y-2 text-sm">
          {explanation.sections.map((section) => (
            <div key={section.title}>
              <dt className="font-medium">{section.title}</dt>
              {section.lines.map((line, index) => (
                <dd key={index} className="text-muted-foreground">
                  {line}
                </dd>
              ))}
            </div>
          ))}
        </dl>
      ) : (
        <Button type="button" size="sm" variant="outline" onClick={() => setAsking(true)} disabled={pending}>
          <Sparkles aria-hidden />
          {t(pending ? 'explaining' : 'explain')}
        </Button>
      )}
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t('explainTitle', { stock: stockId })}
        description={t('explainCost')}
        cancel={t('cancel')}
        confirm={t('explainConfirm')}
        onConfirm={run}
      />
    </div>
  )
}
