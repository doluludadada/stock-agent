import { useParams } from 'react-router'
import { RunDetailPage } from '@/features/runs'
import { WatchButton } from '@/features/watchlist'
import { useShows } from '@/shared/api'

export function RunRoute() {
  const { runId = '' } = useParams()
  const watchlist = useShows('watchlist')
  return <RunDetailPage key={runId} runId={runId} renderWatch={watchlist ? (code, label) => <WatchButton code={code} label={label} variant="icon" /> : undefined} />
}
