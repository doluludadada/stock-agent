import { useParams } from 'react-router'
import { StockResearchPage } from '@/features/stock-research'
import { useRuleSentences } from '@/features/strategies'
import { WatchButton } from '@/features/watchlist'
import { useShows } from '@/shared/api'

export function StockRoute() {
  const { code = '' } = useParams()
  const ruleSentences = useRuleSentences()
  const watchlist = useShows('watchlist')
  return (
    <StockResearchPage
      key={code}
      code={code}
      actions={watchlist ? (stock) => <WatchButton code={stock.code} label={stock.name} /> : undefined}
      ruleSentences={ruleSentences}
    />
  )
}
