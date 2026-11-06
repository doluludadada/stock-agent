import { useParams } from 'react-router'
import { StockResearchPage } from '@/features/stock-research'
import { useRuleSentences, useStrategyLabels } from '@/features/strategies'
import { WatchButton } from '@/features/watchlist'

export function StockRoute() {
  const { code = '' } = useParams()
  const labels = useStrategyLabels()
  const ruleSentences = useRuleSentences()
  return (
    <StockResearchPage
      key={code}
      code={code}
      actions={(stock) => <WatchButton code={stock.code} label={stock.name} />}
      strategyName={(strategy) => labels.name({ id: strategy.strategy_id, name: strategy.name })}
      ruleSentences={ruleSentences}
      ruleName={labels.rule}
    />
  )
}
