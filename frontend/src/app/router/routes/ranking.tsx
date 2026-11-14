import { RankingPage } from '@/features/ranking'
import { useShows } from '@/shared/api'

export function RankingRoute() {
  return <RankingPage mockAccount={useShows('mock_account')} />
}
