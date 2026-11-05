import { useParams } from 'react-router'
import { StockResearchPage } from '@/features/stock-research'
import { useStrategyLabels } from '@/features/strategies'
import { WatchButton } from '@/features/watchlist'

export function StockRoute() {
  const { code = '' } = useParams()
  const labels = useStrategyLabels()
  return (
    <StockResearchPage
      key={code}
      code={code}
      actions={(stock) => <WatchButton code={stock.code} label={stock.name} />}
      strategyName={(strategy) => labels.name({ id: strategy.strategy_id, name: strategy.name })}
    />
  )
}
