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

/**
 * The home page's cards in reading order, each with the feature it belongs to: the market in a row, this month's
 * ranking, then what is the reader's own. A card shows only where the site shows its feature to the viewer.
 */
const CARDS: readonly { feature: Feature; Card: ComponentType<{ className?: string }>; needsSignIn: boolean; className?: string }[] = [
  { feature: 'market_overview', Card: MarketToday, needsSignIn: false, className: 'xl:col-span-2' },
  { feature: 'ranking', Card: RankingToday, needsSignIn: true, className: 'xl:row-span-2' },
  { feature: 'holdings', Card: HoldingsToday, needsSignIn: true },
  { feature: 'watchlist', Card: WatchlistToday, needsSignIn: true },
]

/**
 * "What should I look at today": one page that reads the four things that change between visits, each card leading
 * to its page. The ranking decides once a month and the holdings may be empty, so neither alone is a home page.
 * A visitor gets the public cards and one invitation to sign in, not one per private card.
 */
export function HomeRoute() {
  const { t } = useTranslation()
  const format = useFormat()
  const shown = useShown()
  const [today] = useState(() => sessionDate(new Date().toISOString()))
  const signedOut = useSession().status === 'signedOut'
  const offered = CARDS.filter((item) => shown.shows([item.feature]))
  const cards = signedOut ? offered.filter((item) => !item.needsSignIn) : offered
  return (
    <div className="page-stack">
      <PageHeader title={t('home.title')} description={t('home.description', { date: format.date(today, 'long') })} />
      {shown.pending ? (
        <PageSkeleton />
      ) : (
        <div className="card-grid xl:grid-cols-2">
          {cards.map(({ feature, Card, className }) => (
            <Card key={feature} className={className} />
          ))}
          {signedOut && cards.length < offered.length && (
            <RequireSignIn layout="page" className="xl:col-span-2">
              {null}
            </RequireSignIn>
          )}
        </div>
      )}
    </div>
  )
}
