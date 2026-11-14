import { CircleSlash } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import type { Schemas } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'

/** A stock's standing in the monthly ranking, as the stock page and a holding both carry it. */
export type RankingStanding = Schemas['StockRankingResponse']

const DASH = '—'

/** A stock the ranking left out with no reason given has no daily history here, the first reason the ranking checks. */
const exclusionOf = (standing: RankingStanding) => standing.exclusion ?? 'no_history'

interface Scored {
  place: number
  stock: NonNullable<RankingStanding['stock']>
}

/** The place and the factors of a stock the ranking scored; null for one it left out. */
function scoredOf({ place, stock }: RankingStanding): Scored | null {
  return place === null || stock === null ? null : { place, stock }
}

function TopMark({ standing, className }: { standing: RankingStanding; className?: string }) {
  const { t } = useTranslation()
  return (
    <span className={cn('rounded-full px-2.5 py-1 text-xs font-medium', standing.in_top ? 'bg-brand-soft text-brand' : 'bg-muted text-muted-foreground', className)}>
      {t(standing.in_top ? 'score.inTop' : 'score.notInTop', { top: standing.top })}
    </span>
  )
}

/**
 * The score as a card's content: 0 to 100, whether the ranking holds the stock now, its place among the scored stocks
 * and each factor's percentile as a bar; or why the ranking gives it no score.
 */
export function RankingScore({ standing }: { standing: RankingStanding }) {
  const { t } = useTranslation()
  const format = useFormat()
  const scored = scoredOf(standing)
  if (!scored) {
    return (
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
          <CircleSlash aria-hidden className="size-5" />
        </span>
        <div className="min-w-0 space-y-1">
          <p className="text-title font-semibold">{t('score.none')}</p>
          <p className="text-sm text-pretty text-muted-foreground">{t(`score.exclusion.${exclusionOf(standing)}`)}</p>
        </div>
      </div>
    )
  }
  const { place, stock } = scored
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <p className="flex items-baseline gap-1.5">
          <span className="figure">{standing.score === null ? DASH : format.number(standing.score)}</span>
          <span className="text-sm text-muted-foreground">{t('score.outOf')}</span>
        </p>
        <TopMark standing={standing} />
      </div>
      <p className="text-sm text-muted-foreground">{t('score.place', { place: format.number(place), scored: format.number(standing.scored) })}</p>
      <dl className="grid gap-3">
        <Factor label={t('score.acceleration')} percentile={stock.acceleration_rank * 100} value={`×${format.number(stock.revenue_acceleration, 2)}`} />
        <Factor label={t('score.nearness')} percentile={stock.nearness_rank * 100} value={`${format.number(stock.nearness_to_high * 100, 1)}%`} />
      </dl>
    </div>
  )
}

/** One of the ranking's two factors: where it ranks among the scored stocks, as a bar and a number, and its own value. */
function Factor({ label, percentile, value }: { label: string; percentile: number; value: ReactNode }) {
  const { t } = useTranslation()
  const format = useFormat()
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <dt className="min-w-0 truncate text-muted-foreground">{label}</dt>
        <dd className="tabular shrink-0 font-medium">
          {t('score.percentile', { value: format.number(percentile) })}
          <span className="ml-2 font-normal text-muted-foreground">{value}</span>
        </dd>
      </div>
      <div aria-hidden className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-brand" style={{ width: `${Math.min(100, Math.max(0, percentile))}%` }} />
      </div>
    </div>
  )
}

/**
 * The same score in a table row: the figure with its place, the two factors' percentiles in one line, and a mark only
 * while the ranking holds the stock; or the reason it has no score.
 */
export function RankingScoreLine({ standing, className }: { standing: RankingStanding; className?: string }) {
  const { t } = useTranslation()
  const format = useFormat()
  const scored = scoredOf(standing)
  if (!scored) {
    return (
      <span className={cn('flex min-w-0 flex-col leading-tight', className)}>
        <span className="text-muted-foreground">{t('score.none')}</span>
        <span className="text-xs text-pretty whitespace-normal text-muted-foreground">{t(`score.exclusion.${exclusionOf(standing)}`)}</span>
      </span>
    )
  }
  const { place, stock } = scored
  return (
    <span className={cn('flex min-w-0 flex-col gap-0.5 leading-tight', className)}>
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="tabular whitespace-nowrap">
          <span className="font-semibold">{standing.score === null ? DASH : format.number(standing.score)}</span>
          <span className="ml-1 text-xs text-muted-foreground">{t('score.placeShort', { place: format.number(place), scored: format.number(standing.scored) })}</span>
        </span>
        {standing.in_top && <TopMark standing={standing} className="px-2 py-0.5" />}
      </span>
      <span className="tabular text-xs whitespace-normal text-muted-foreground">
        {t('score.factors', { acceleration: format.number(stock.acceleration_rank * 100), nearness: format.number(stock.nearness_rank * 100) })}
      </span>
    </span>
  )
}

/** Said wherever a score shows: what it measures, that it predicts nothing, and where its evidence is. */
export function RankingScoreNote({ className }: { className?: string }) {
  const { t } = useTranslation()
  return (
    <p className={cn('text-xs leading-relaxed text-pretty text-muted-foreground', className)}>
      {t('score.method')}{' '}
      <Link to={paths.ranking} className="inline-flex min-h-11 items-center text-brand underline-offset-4 hover:underline md:min-h-0">
        {t('score.open')}
      </Link>
    </p>
  )
}
