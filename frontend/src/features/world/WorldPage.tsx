import { ChevronLeft, ChevronRight, Globe, Newspaper } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { NewsRow } from '@/shared/ui/news-row'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Segmented } from '@/shared/ui/segmented'
import { ShowMore } from '@/shared/ui/show-more'
import { PageSkeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useWorld } from './api'
import { briefState, newsSources, shownNews, type SourceFilter, type World, type WorldNews } from './model'
import { BriefByline, BriefSentences, IndicatorStrip } from './WorldParts'

/** A day of world news is long; the first titles show what is new, and the rest open on request. A title leads to its article. */
const ITEMS_SHOWN = 20

/**
 * The world outside Taiwan's exchanges as the site holds it: the indicators, the day's AI brief with what each
 * sentence cites and the past days' briefs, and the news list by publisher. Every title, summary and sentence is a
 * third party's or the AI's and renders as text.
 */
export function WorldPage() {
  const { t } = useTranslation('world')
  const world = useWorld()
  return (
    <div className="page-stack">
      <PageHeader title={t('title')} />
      <RequireSignIn reason={t('signIn')} layout="page">
        {world.isPending ? (
          <PageSkeleton />
        ) : world.isError ? (
          <ErrorState error={world.error} title={t('failed')} onRetry={() => void world.refetch()} />
        ) : (
          <div className="card-stack">
            <Panel title={t('indicators.title')} description={world.data.indicators.length > 0 ? t('indicators.source') : undefined}>
              {world.data.indicators.length > 0 ? <IndicatorStrip readings={world.data.indicators} /> : <p className="text-sm text-muted-foreground">{t('indicators.none')}</p>}
            </Panel>
            <div className="card-grid xl:grid-cols-2">
              <Brief world={world.data} />
              <News items={world.data.news} />
            </div>
          </div>
        )}
      </RequireSignIn>
    </div>
  )
}

function Brief({ world }: { world: World }) {
  const { t } = useTranslation('world')
  const format = useFormat()
  const [index, setIndex] = useState(0)
  const state = briefState(world, index)
  const days = world.briefs.length
  const step = (
    <div className="flex items-center gap-1">
      <Button type="button" variant="ghost" size="icon" aria-label={t('brief.older')} disabled={index >= days - 1} onClick={() => setIndex(index + 1)}>
        <ChevronLeft aria-hidden />
      </Button>
      <span className="tabular text-sm text-muted-foreground">{state.kind === 'written' && format.date(state.brief.day)}</span>
      <Button type="button" variant="ghost" size="icon" aria-label={t('brief.newer')} disabled={index === 0} onClick={() => setIndex(index - 1)}>
        <ChevronRight aria-hidden />
      </Button>
    </div>
  )
  return (
    <Panel title={t('brief.title')} aside={days > 1 ? step : state.kind === 'written' ? <span className="tabular text-sm text-muted-foreground">{format.date(state.brief.day)}</span> : undefined}>
      {state.kind === 'written' ? (
        <div className="space-y-4">
          <BriefByline brief={state.brief} />
          <BriefSentences brief={state.brief} cited />
          <NotAdviceNote className="border-t pt-3" />
        </div>
      ) : (
        <StateBlock icon={Globe} title={t(`brief.${state.kind}.title`)} description={t(`brief.${state.kind}.description`, { time: state.kind === 'waiting' ? state.writeAt : '' })} className="py-4" />
      )}
    </Panel>
  )
}

function News({ items }: { items: readonly WorldNews[] }) {
  const { t } = useTranslation('world')
  const format = useFormat()
  const [filter, setFilter] = useState<SourceFilter>('all')
  const [expanded, setExpanded] = useState(false)
  const sources = newsSources(items)
  const shown = shownNews(items, sources.includes(filter as WorldNews['source']) ? filter : 'all')
  const options = [{ value: 'all' as const, label: t('news.allSources') }, ...sources.map((source) => ({ value: source, label: t(`research:news.source.${source}`) }))]
  return (
    <Panel
      title={t('news.title')}
      flush
      footer={
        shown.length > ITEMS_SHOWN && (
          <ShowMore expanded={expanded} onToggle={() => setExpanded(!expanded)} controls="world-news" moreLabel={t('news.showAll', { count: shown.length })} lessLabel={t('news.showLess')} />
        )
      }
    >
      {items.length === 0 ? (
        <StateBlock icon={Newspaper} title={t('news.none.title')} description={t('news.none.description')} />
      ) : (
        <>
          {sources.length > 1 && (
            <div className="px-4 pb-3 md:px-5">
              <Segmented value={filter} onChange={setFilter} options={options} label={t('news.filter')} />
            </div>
          )}
          <ul id="world-news" className="divide-y border-t">
            {(expanded ? shown : shown.slice(0, ITEMS_SHOWN)).map((item) => (
              <NewsRow
                key={`${item.source}-${item.url}-${item.published_at}`}
                source={t(`research:news.source.${item.source}`)}
                publishedAt={item.published_at}
                time={format.monthDayTime(item.published_at)}
                title={item.title}
                url={item.url}
              />
            ))}
          </ul>
        </>
      )}
    </Panel>
  )
}
