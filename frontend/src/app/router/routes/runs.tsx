import { useParams } from 'react-router'
import { RunDetailPage, RunsPage, useRun } from '@/features/runs'
import { useStrategyLabels } from '@/features/strategies'
import { WatchButton } from '@/features/watchlist'
import { useShows } from '@/shared/api'

export function RunsRoute() {
  return <RunsPage />
}

export function RunRoute() {
  const { runId = '' } = useParams()
  const labels = useStrategyLabels()
  const strategyId = useRun(runId).data?.summary?.technical_strategy_id
  const watchlist = useShows('watchlist')
  return (
    <RunDetailPage
      key={runId}
      runId={runId}
      renderWatch={watchlist ? (code, label) => <WatchButton code={code} label={label} variant="icon" /> : undefined}
      ruleName={(name) => labels.rule(strategyId, name)}
    />
  )
}
