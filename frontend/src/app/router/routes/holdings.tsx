import { HoldingsPage } from '@/features/holdings'
import { useWatchedStocks } from '@/features/watchlist'
import { useShows } from '@/shared/api'

/** The watched stocks reach the holdings page only where the site shows the viewer the watchlist. */
export function HoldingsRoute() {
  const watchlist = useShows('watchlist')
  const watched = useWatchedStocks(watchlist)
  return <HoldingsPage watched={watchlist ? watched : undefined} />
}
