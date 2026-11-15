import { ExternalLink } from 'lucide-react'
import { useLocale, useTranslation } from '@/i18n'
import { useListedNames } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { outboundUrl } from '@/shared/lib/outbound-url'
import { AiByline } from '@/shared/ui/ai-byline'
import { ChangeValue } from '@/shared/ui/change-value'
import { StockChip } from '@/shared/ui/stock-name'
import { citedSources, eventSentences, INDICATORS, type Reading, type Sentence, type Source, type WorldBrief } from './model'

/** The held indicators in one strip: each one's newest reading, its change from the reading before, and its day. */
export function IndicatorStrip({ readings }: { readings: readonly Reading[] }) {
  const { t } = useTranslation('world')
  const format = useFormat()
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 @md:grid-cols-3 @3xl:grid-cols-6">
      {readings.map((reading) => {
        const { digits, percent } = INDICATORS[reading.indicator]
        return (
          <div key={reading.indicator} className="min-w-0">
            <dt className="truncate text-xs text-muted-foreground">{t(`indicators.name.${reading.indicator}`)}</dt>
            <dd className="tabular flex flex-wrap items-baseline gap-x-2 text-sm font-semibold">
              <span>{percent ? `${format.number(reading.value, digits)}%` : format.number(reading.value, digits)}</span>
              {typeof reading.change === 'number' && (
                <span className="text-xs">
                  <ChangeValue value={reading.change} format={percent ? 'absolute' : 'percent'} />
                  {percent && <span className="text-muted-foreground"> {t('indicators.points')}</span>}
                </span>
              )}
            </dd>
            <dd className="tabular text-xs text-muted-foreground">{format.monthDay(reading.day)}</dd>
          </div>
        )
      })}
    </dl>
  )
}

/** That the brief is the AI's, which model wrote it and when, and the days of news it read. */
export function BriefByline({ brief }: { brief: WorldBrief }) {
  const { t } = useTranslation('world')
  const format = useFormat()
  const locale = useLocale()
  return (
    <div className="space-y-1.5 text-xs text-pretty text-muted-foreground">
      <AiByline model={brief.model} writtenAt={brief.written_at} />
      {brief.window_first && brief.window_last && <p>{t('brief.window', { first: format.date(brief.window_first), last: format.date(brief.window_last) })}</p>}
      {brief.language !== locale && <p>{t(`brief.writtenIn.${brief.language}`)}</p>}
    </div>
  )
}

/**
 * The brief's sentences as text. With `cited`, every sentence shows, each followed by the held items it rests on, a
 * news item as a link to its publisher's page, and by the listed stocks one of those items names. Without, the first
 * `limit` sentences about events show alone. A title is its publisher's: it renders as text, and its address is a
 * link only when it is http or https.
 */
export function BriefSentences({ brief, limit, cited = false }: { brief: WorldBrief; limit?: number; cited?: boolean }) {
  const sentences = cited ? (brief.movement ?? []) : eventSentences(brief).slice(0, limit)
  const names = useListedNames(cited ? sentences.flatMap((sentence) => sentence.stocks ?? []) : [])
  return (
    <ul className="space-y-3">
      {sentences.map((sentence, index) => (
        <li key={index} className="space-y-1.5">
          <p className="text-sm leading-relaxed text-pretty break-words">{sentence.text}</p>
          {cited && <Cited sentence={sentence} brief={brief} names={names} />}
        </li>
      ))}
    </ul>
  )
}

function Cited({ sentence, brief, names }: { sentence: Sentence; brief: WorldBrief; names: ReadonlyMap<string, string> }) {
  const stocks = sentence.stocks ?? []
  return (
    <>
      <ul className="space-y-0.5 border-l-2 pl-3 text-xs text-muted-foreground">
        {citedSources(sentence, brief)
          .filter((source, index, all) => source.title || all.findIndex((other) => !other.title && other.dated === source.dated) === index)
          .map((source) => (
            <li key={source.key}>
              <CitedSource source={source} />
            </li>
          ))}
      </ul>
      {stocks.length > 0 && (
        <p className="flex flex-wrap gap-1.5">
          {stocks.map((stockId) => (
            <StockChip key={stockId} stockId={stockId} name={names.get(stockId)} />
          ))}
        </p>
      )}
    </>
  )
}

function CitedSource({ source }: { source: Source }) {
  const { t } = useTranslation('world')
  const format = useFormat()
  const href = outboundUrl(source.url ?? null)
  const date = format.monthDay(source.dated)
  if (!source.title) return <span>{t('brief.citation.indicator', { date })}</span>
  const publisher = source.origin ? t(`research:news.source.${source.origin}`) : t('brief.citation.news')
  const label = (
    <>
      <span className="shrink-0">{t('brief.citation.item', { publisher, date })}</span> <span className="text-pretty break-words">{source.title}</span>
    </>
  )
  if (!href) return <span>{label}</span>
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="tap gap-1 hover:text-brand hover:underline">
      <span>{label}</span>
      <ExternalLink aria-hidden className="size-3 shrink-0" />
      <span className="sr-only">{t('common:opensSource')}</span>
    </a>
  )
}
