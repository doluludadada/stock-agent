import { useParams } from 'react-router'
import { RunDetailPage, RunsPage, useRun } from '@/features/runs'
import { useStrategyLabels } from '@/features/strategies'
import { WatchButton } from '@/features/watchlist'

export function RunsRoute() {
  return <RunsPage />
}

export function RunRoute() {
  const { runId = '' } = useParams()
  const labels = useStrategyLabels()
  const strategyId = useRun(runId).data?.summary?.technical_strategy_id
  return (
    <RunDetailPage
      key={runId}
      runId={runId}
      renderWatch={(code, label) => <WatchButton code={code} label={label} variant="icon" />}
      ruleName={(name) => labels.rule(strategyId, name)}
    />
  )
}
