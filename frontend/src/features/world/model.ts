import type { Schemas } from '@/shared/api'
import { clockTime } from '@/shared/lib/format'

export type World = Schemas['WorldResponse']
export type WorldBrief = World['briefs'][number]
export type Reading = World['indicators'][number]
export type WorldNews = World['news'][number]
export type Sentence = NonNullable<WorldBrief['movement']>[number]
export type Source = NonNullable<WorldBrief['sources']>[number]

/** How each indicator's reading is written: its decimals, and whether it is a percentage, whose change is in points. */
export const INDICATORS = {
  usd_twd: { digits: 3, percent: false },
  usd_jpy: { digits: 2, percent: false },
  eur_usd: { digits: 4, percent: false },
  usd_cny: { digits: 4, percent: false },
  us_10y_yield: { digits: 2, percent: true },
  us_2y_yield: { digits: 2, percent: true },
} as const satisfies Record<Reading['indicator'], { digits: number; percent: boolean }>

/** The held items a sentence cites, in the sentence's own order. A key the brief does not hold names nothing. */
export function citedSources(sentence: Sentence, brief: WorldBrief): Source[] {
  return sentence.sources.flatMap((key) => (brief.sources ?? []).find((source) => source.key === key) ?? [])
}

export type SourceFilter = 'all' | WorldNews['source']

/** The publishers among the items, in the order they first appear: the choices the news list filters by. */
export function newsSources(items: readonly WorldNews[]): WorldNews['source'][] {
  return [...new Set(items.map((item) => item.source))]
}

export function shownNews(items: readonly WorldNews[], filter: SourceFilter): WorldNews[] {
  return filter === 'all' ? [...items] : items.filter((item) => item.source === filter)
}

/**
 * The brief's sentences about events: those that cite a news item. The home page shows these, since its strip
 * already says the indicators' figures; a brief with none shows its sentences as they are.
 */
export function eventSentences(brief: WorldBrief): Sentence[] {
  const sentences = brief.movement ?? []
  const events = sentences.filter((sentence) => citedSources(sentence, brief).some((source) => source.kind !== 'indicator'))
  return events.length > 0 ? events : sentences
}

export type BriefState = { kind: 'written'; brief: WorldBrief } | { kind: 'waiting'; writeAt: string } | { kind: 'off' }

/**
 * What the brief's card says: the written brief at `index` among the held ones, newest first; while the site holds
 * none, the time it writes the day's from, or that this site writes none.
 */
export function briefState(world: World, index = 0): BriefState {
  const brief = world.briefs[index] ?? world.briefs[0]
  if (brief) return { kind: 'written', brief }
  return world.write_at ? { kind: 'waiting', writeAt: clockTime(world.write_at) } : { kind: 'off' }
}
