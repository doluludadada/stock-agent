import { useParams, useSearchParams } from 'react-router'
import { StrategyBuilderPage, StrategyLibraryPage, type BuilderMode } from '@/features/strategies'

export function StrategyLibraryRoute() {
  return <StrategyLibraryPage />
}

export function NewStrategyRoute() {
  const [params] = useSearchParams()
  const builtIn = params.get('builtin')
  const from = params.get('from')
  const mode: BuilderMode = builtIn ? { type: 'copy', source: 'builtIn', id: builtIn } : from ? { type: 'copy', source: 'owned', id: from } : { type: 'blank' }
  return <StrategyBuilderPage key={JSON.stringify(mode)} mode={mode} />
}

export function EditStrategyRoute() {
  const { id = '' } = useParams()
  return <StrategyBuilderPage key={`edit:${id}`} mode={{ type: 'edit', id }} />
}
