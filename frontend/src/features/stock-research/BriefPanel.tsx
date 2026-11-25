import { ArrowDown, Check, Circle, CircleSlash, ExternalLink, LoaderCircle, PenLine, Sparkles } from 'lucide-react'
import { useId } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { useAllows, useSession } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { AiByline } from '@/shared/ui/ai-byline'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { ErrorState } from '@/shared/ui/error-state'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { Panel } from '@/shared/ui/panel'
import { useAuthLinks } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useStockBrief, useStockCompany, useWriteStockBrief } from './api'
import { briefSteps, briefView, citedSources, sourceLink, usedSources, type BriefAsk, type BriefSentence, type BriefSource, type BriefStep, type BriefView, type StockBrief } from './brief'

/**
 * The AI's brief of the stock: how the facts the site holds relate to its recent move; what the company is, the
 * company card above it says. The
 * site writes one per stock and day for every viewer, and only when a signed-in viewer clicks: opening the page never
 * spends an AI call. Every sentence and title is the AI's or a third party's and renders as text. A first brief of a
 * stock can take a minute, because the site first reads the company's filings and writes its card: while it is being
 * written the card says each step and which one the site is at, from what the site holds, asked again every few
 * seconds.
 */
export function BriefPanel({ stockId }: { stockId: string }) {
  const { t } = useTranslation('research')
  const brief = useStockBrief(stockId)
  const write = useWriteStockBrief(stockId)
  const viewer = useSession().status
  const view = brief.data ? briefView(brief.data, { pending: write.isPending, error: write.error }, viewer) : null
  const company = useStockCompany(stockId, view?.kind === 'writing')
  const reads = { mainBusiness: useAllows('mops'), annualReports: useAllows('annual_reports') }
  return (
    <Panel title={t('brief.title')}>
      {brief.data && view ? (
        <View view={view} steps={briefSteps(company.data, brief.data, reads)} onWrite={() => write.mutate()} />
      ) : brief.isError ? (
        <ErrorState error={brief.error} title={t('brief.loadFailed')} onRetry={() => void brief.refetch()} />
      ) : (
        <Skeleton className="h-40 rounded-lg" />
      )}
    </Panel>
  )
}

function View({ view, steps, onWrite }: { view: BriefView; steps: readonly BriefStep[]; onWrite: () => void }) {
  const { t } = useTranslation('research')
  if (view.kind === 'written') return <ShownBrief brief={view.brief} />
  return (
    <div className="space-y-4">
      {view.kind === 'writing' && (
        <StateBlock icon={PenLine} title={t('brief.writing.title')} description={t('brief.writing.description')} action={<Steps steps={steps} />} className="py-4" />
      )}
      {view.kind === 'failed' &&
        (view.error ? (
          <ErrorState error={view.error} title={t('brief.failed.title')} className="py-4" />
        ) : (
          <StateBlock icon={CircleSlash} tone="danger" title={t('brief.failed.title')} description={t('brief.failed.description')} className="py-4" />
        ))}
      {view.kind === 'limit' && <StateBlock icon={CircleSlash} title={t('brief.limit.title')} description={t('brief.limit.description')} className="py-4" />}
      {view.kind === 'unwritten' && <StateBlock icon={Sparkles} title={t('brief.none.title')} description={t('brief.none.description')} className="py-4" />}
      {(view.kind === 'failed' || view.kind === 'unwritten') && <Ask ask={view.ask} label={t(view.kind === 'failed' ? 'brief.retry' : 'brief.write')} onWrite={onWrite} />}
      {view.earlier && <Earlier brief={view.earlier} />}
    </div>
  )
}

const STEP_ICON = { done: Check, active: LoaderCircle, waiting: Circle } as const

/** What the site does for the brief, in order, and where it is now; each step also says its state in words. The state block around it announces a change. */
function Steps({ steps }: { steps: readonly BriefStep[] }) {
  const { t } = useTranslation('research')
  return (
    <ol className="space-y-1.5 text-left text-sm">
      {steps.map(({ step, state }) => {
        const Icon = STEP_ICON[state]
        return (
          <li key={step} aria-current={state === 'active' ? 'step' : undefined} className={state === 'waiting' ? 'flex items-center gap-2 text-muted-foreground' : 'flex items-center gap-2'}>
            <Icon aria-hidden className={state === 'active' ? 'size-4 shrink-0 animate-spin text-brand motion-reduce:animate-none' : 'size-4 shrink-0'} />
            <span>{t(`brief.writing.step.${step}`)}</span>
            <span className="sr-only">{t(`brief.writing.state.${state}`)}</span>
          </li>
        )
      })}
    </ol>
  )
}

/** The one way to ask for today's brief: a deliberate click by a signed-in viewer, and a visitor is told who may ask. */
function Ask({ ask, label, onWrite }: { ask: BriefAsk; label: string; onWrite: () => void }) {
  const { t } = useTranslation('research')
  const links = useAuthLinks()
  if (ask === 'none') return null
  if (ask === 'signIn') {
    return (
      <p className="text-center text-sm text-pretty text-muted-foreground">
        {t('brief.signIn')}{' '}
        <Link to={links.signIn} className="tap font-medium text-brand underline-offset-4 hover:underline">
          {t('common:auth.signIn')}
        </Link>
      </p>
    )
  }
  return (
    <div className="flex flex-col items-center gap-2 text-center">
      <Button type="button" onClick={onWrite}>
        <Sparkles aria-hidden />
        {label}
      </Button>
      <p className="max-w-sm text-xs text-pretty text-muted-foreground">{t('brief.writeNote')}</p>
    </div>
  )
}

function Earlier({ brief }: { brief: StockBrief }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const id = useId()
  return (
    <section aria-labelledby={id} className="space-y-3 border-t pt-4">
      <h3 id={id} className="text-sm font-semibold">
        {t('brief.earlier', { date: format.date(brief.day) })}
      </h3>
      <ShownBrief brief={brief} />
    </section>
  )
}

function ShownBrief({ brief }: { brief: StockBrief }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const locale = useLocale()
  const sources = brief.sources ?? []
  return (
    <div className="space-y-4">
      <div className="space-y-1.5 text-xs text-pretty text-muted-foreground">
        <AiByline model={brief.model} writtenAt={brief.written_at} />
        {brief.window_first && brief.window_last ? (
          <p>
            {t('brief.window', { first: format.date(brief.window_first), last: format.date(brief.window_last) })}
            {typeof brief.price_change === 'number' && (
              <>
                {' '}
                {t('brief.windowChange')} <ChangeValue value={brief.price_change} format="percent" />
              </>
            )}
          </p>
        ) : (
          <p>{t('brief.noWindow')}</p>
        )}
        {brief.language !== locale && <p>{t(`brief.writtenIn.${brief.language}`)}</p>}
      </div>
      {(brief.company ?? []).length > 0 && <Part title={t('brief.part.company')} sentences={brief.company ?? []} sources={sources} />}
      <Part title={t('brief.part.movement')} sentences={brief.movement ?? []} sources={sources} />
      <CitedSources sources={usedSources(brief)} />
      <NotAdviceNote className="border-t pt-3" />
    </div>
  )
}

/** A source's name comes from its kind and date alone, never from the AI's or a third party's text. */
function useSourceLabel(): (source: BriefSource) => string {
  const { t } = useTranslation('research')
  const format = useFormat()
  return (source) => t('brief.citation', { kind: t(`brief.kind.${source.kind}`), date: format.monthDay(source.dated) })
}

function Part({ title, sentences, sources }: { title: string; sentences: readonly BriefSentence[]; sources: readonly BriefSource[] }) {
  const { t } = useTranslation('research')
  const id = useId()
  return (
    <section aria-labelledby={id} className="space-y-2">
      <h3 id={id} className="text-sm font-semibold">
        {title}
      </h3>
      {sentences.length === 0 && <p className="text-sm text-muted-foreground">{t('brief.part.none')}</p>}
      <Sentences sentences={sentences} sources={sources} />
    </section>
  )
}

/** An AI text's sentences, each as text with the held items it rests on named after it. */
export function Sentences({ sentences, sources }: { sentences: readonly BriefSentence[]; sources: readonly BriefSource[] }) {
  const label = useSourceLabel()
  return sentences.map((sentence, index) => (
    <p key={index} className="text-sm leading-relaxed text-pretty break-words">
      {sentence.text}{' '}
      {citedSources(sentence, sources).map((source) => (
        <span key={source.key} className="tabular mr-1 inline-block rounded-full border px-1.5 text-xs leading-5 whitespace-nowrap text-muted-foreground">
          {label(source)}
        </span>
      ))}
    </p>
  ))
}

function CitedSources({ sources }: { sources: readonly BriefSource[] }) {
  const { t } = useTranslation('research')
  const label = useSourceLabel()
  const id = useId()
  if (sources.length === 0) return null
  return (
    <section aria-labelledby={id} className="space-y-1">
      <h3 id={id} className="text-xs font-medium text-muted-foreground">
        {t('brief.sources.title')}
      </h3>
      <ul className="text-sm">
        {sources.map((source) => {
          const link = sourceLink(source)
          return (
            <li key={source.key} className="flex flex-wrap items-baseline gap-x-2 py-0.5">
              {link.to === 'section' ? (
                <a href={`#${link.anchor}`} className="tap shrink-0 gap-1 text-xs text-brand underline-offset-4 hover:underline">
                  {label(source)}
                  <ArrowDown aria-hidden className="size-3 shrink-0" />
                  <span className="sr-only">{t('brief.sources.onPage')}</span>
                </a>
              ) : (
                <span className="shrink-0 text-xs text-muted-foreground">{label(source)}</span>
              )}
              {link.to === 'outbound' ? (
                <a href={link.href} target="_blank" rel="noopener noreferrer nofollow" className="tap min-w-0 gap-1.5 font-medium text-pretty break-words hover:text-brand hover:underline">
                  <span className="min-w-0">{source.title || link.href}</span>
                  <ExternalLink aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="sr-only">{t('common:opensSource')}</span>
                </a>
              ) : (
                source.title && <span className="min-w-0 text-pretty break-words">{source.title}</span>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
