import { Globe } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { AiByline } from '@/shared/ui/ai-byline'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel, PanelLink } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { useWorld } from './api'
import { briefState, type World } from './model'
import { BriefSentences, IndicatorStrip } from './WorldParts'

/** The brief's first sentences are enough to see what moved; the page holds the rest with what each cites. */
const SENTENCES_SHOWN = 3

/** The world for the home page: the indicators as a strip, the newest brief's first sentences, and the way to the page. */
export function WorldToday({ className }: { className?: string }) {
  const { t } = useTranslation('world')
  const world = useWorld()
  return (
    <Panel className={className} title={t('title')} aside={<PanelLink to={paths.world}>{t('today.all')}</PanelLink>}>
      <RequireSignIn reason={t('signIn')}>
        {world.isPending ? (
          <Skeleton className="h-32 rounded-lg" />
        ) : world.isError ? (
          <ErrorState error={world.error} title={t('failed')} onRetry={() => void world.refetch()} />
        ) : (
          <Held world={world.data} />
        )}
      </RequireSignIn>
    </Panel>
  )
}

function Held({ world }: { world: World }) {
  const { t } = useTranslation('world')
  const state = briefState(world)
  if (world.indicators.length === 0 && state.kind !== 'written') {
    return <StateBlock icon={Globe} title={t(`brief.${state.kind}.title`)} description={t(`brief.${state.kind}.description`, { time: state.kind === 'waiting' ? state.writeAt : '' })} className="py-4" />
  }
  return (
    <div className="space-y-4">
      {world.indicators.length > 0 && <IndicatorStrip readings={world.indicators} />}
      {state.kind === 'written' ? (
        <div className="space-y-2 border-t pt-3">
          <BriefSentences brief={state.brief} limit={SENTENCES_SHOWN} />
          <AiByline model={state.brief.model} writtenAt={state.brief.written_at} />
        </div>
      ) : (
        <p className="border-t pt-3 text-sm text-muted-foreground">{t(`brief.${state.kind}.description`, { time: state.kind === 'waiting' ? state.writeAt : '' })}</p>
      )}
    </div>
  )
}
