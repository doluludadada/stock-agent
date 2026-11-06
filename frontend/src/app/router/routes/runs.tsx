import { useParams } from 'react-router'
import { RunDetailPage, RunsPage } from '@/features/runs'
import { useStrategyLabels } from '@/features/strategies'
import { WatchButton } from '@/features/watchlist'

export function RunsRoute() {
  return <RunsPage />
}

export function RunRoute() {
  const { runId = '' } = useParams()
  const labels = useStrategyLabels()
  return (
    <RunDetailPage
      key={runId}
      runId={runId}
      renderWatch={(code, label) => <WatchButton code={code} label={label} variant="icon" />}
      ruleName={labels.rule}
    />
  )
}
