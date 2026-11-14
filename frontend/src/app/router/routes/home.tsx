import { useState, type ComponentType } from 'react'
import { HoldingsToday } from '@/features/holdings'
import { MarketToday } from '@/features/market-overview'
import { RankingToday } from '@/features/ranking'
import { WatchlistToday } from '@/features/watchlist'
import { useTranslation } from '@/i18n'
import { useSession, useShown, type Feature } from '@/shared/api'
import { useFormat } from '@/shared/lib/format'
import { sessionDate } from '@/shared/lib/chart-range'
import { PageHeader } from '@/shared/ui/page-header'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { PageSkeleton } from '@/shared/ui/skeleton'

type Place = 'top' | 'left' | 'right'

/**
 * The home page's cards in reading order, each with the feature it belongs to: the market across the top, this
 * month's ranking, then what is the reader's own beside it. A card shows only where the site shows its feature.
 */
const CARDS: readonly { feature: Feature; Card: ComponentType<{ className?: string }>; needsSignIn: boolean; place: Place }[] = [
  { feature: 'market_overview', Card: MarketToday, needsSignIn: false, place: 'top' },
  { feature: 'ranking', Card: RankingToday, needsSignIn: true, place: 'left' },
  { feature: 'holdings', Card: HoldingsToday, needsSignIn: true, place: 'right' },
  { feature: 'watchlist', Card: WatchlistToday, needsSignIn: true, place: 'right' },
]

/**
 * "What should I look at today": the four things that change between visits, each card leading to its page. A visitor
 * gets the public cards and one invitation to sign in, not one per private card.
 */
export function HomeRoute() {
  const { t } = useTranslation()
  const format = useFormat()
  const shown = useShown()
  const [today] = useState(() => sessionDate(new Date().toISOString()))
  const signedOut = useSession().status === 'signedOut'
  const offered = CARDS.filter((item) => shown.shows([item.feature]))
  const cards = signedOut ? offered.filter((item) => !item.needsSignIn) : offered
  const at = (place: Place) => cards.filter((item) => item.place === place).map(({ feature, Card }) => <Card key={feature} />)
  const [left, right] = [at('left'), at('right')]
  return (
    <div className="page-stack">
      <PageHeader title={t('home.title')} description={format.date(today, 'long')} />
      {shown.pending ? (
        <PageSkeleton />
      ) : (
        <div className="card-stack">
          {at('top')}
          {/* Each side is its own stack, so a short card on one side leaves no gap beside a long one on the other. */}
          <div className={left.length > 0 && right.length > 0 ? 'card-grid xl:grid-cols-2' : 'card-stack'}>
            {left.length > 0 && <div className="card-stack">{left}</div>}
            {right.length > 0 && <div className="card-stack">{right}</div>}
          </div>
          {signedOut && cards.length < offered.length && <RequireSignIn layout="page">{null}</RequireSignIn>}
        </div>
      )}
    </div>
  )
}
