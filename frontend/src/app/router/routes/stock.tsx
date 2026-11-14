import { useParams } from 'react-router'
import { StockResearchPage } from '@/features/stock-research'
import { useRuleSentences, useStrategyLabels } from '@/features/strategies'
import { WatchButton } from '@/features/watchlist'
import { useShows } from '@/shared/api'

export function StockRoute() {
  const { code = '' } = useParams()
  const labels = useStrategyLabels()
  const ruleSentences = useRuleSentences()
  const watchlist = useShows('watchlist')
  return (
    <StockResearchPage
      key={code}
      code={code}
      actions={watchlist ? (stock) => <WatchButton code={stock.code} label={stock.name} /> : undefined}
      strategyName={(strategy) => labels.name({ id: strategy.strategy_id, name: strategy.name })}
      ruleSentences={ruleSentences}
      ruleName={(strategy, name) => labels.rule(strategy.strategy_id, name)}
    />
  )
}
