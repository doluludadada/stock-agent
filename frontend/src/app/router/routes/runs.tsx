import { useParams } from 'react-router'
import { RunDetailPage, RunsPage } from '@/features/runs'
import { WatchButton } from '@/features/watchlist'

export function RunsRoute() {
  return <RunsPage />
}

export function RunRoute() {
  const { runId = '' } = useParams()
  return (
    <RunDetailPage
      key={runId}
      runId={runId}
      renderWatch={(code, label) => <WatchButton code={code} label={label} variant="icon" />}
    />
  )
}
