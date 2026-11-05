import { FilePlus2, Layers } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { isApiError } from '@/shared/api'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { useBuiltInStrategies, useSaveStrategySettings, useStrategySettings } from '../api/queries'
import { deletionRefusal, isRefusal, withSelection, withoutStrategy } from '../model/settings'
import type { Strategy, StrategySettings } from '../model/types'
import { useStrategyLabels } from '../use-formula-text'
import { StrategyCard } from './StrategyCard'
import { StrategyRulesSheet } from './StrategyRulesSheet'

export function StrategyLibraryPage() {
  const { t } = useTranslation('strategies')
  const [viewing, setViewing] = useState<Strategy | null>(null)

  return (
    <div className="space-y-6">
      <PageHeader
        title={t('library.title')}
        description={t('library.description')}
        actions={
          <Button asChild size="sm">
            <Link to={paths.newStrategy}>
              <FilePlus2 aria-hidden />
              {t('action.createBlank')}
            </Link>
          </Button>
        }
      />
      <OfficialStrategies onView={setViewing} />
      <section className="space-y-3" aria-labelledby="custom-title">
        <div className="space-y-0.5">
          <h2 id="custom-title" className="text-base font-semibold">
            {t('library.customTitle')}
          </h2>
          <p className="text-xs text-muted-foreground">{t('library.selectionNote')}</p>
        </div>
        <RequireSignIn layout="page" reason={t('signIn')}>
          <OwnerStrategies onView={setViewing} />
        </RequireSignIn>
      </section>
      <StrategyRulesSheet strategy={viewing} onOpenChange={(open) => !open && setViewing(null)} />
    </div>
  )
}

function CardGrid({ children }: { children: ReactNode }) {
  // A last card alone in its row of two takes the row, so a column of three never leaves half a row empty.
  return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 md:max-xl:[&>*:last-child:nth-child(odd)]:col-span-2">{children}</div>
}

function LoadingGrid() {
  return (
    <CardGrid>
      {[0, 1, 2].map((index) => (
        <Skeleton key={index} className="h-64 rounded-xl" />
      ))}
    </CardGrid>
  )
}

function OfficialStrategies({ onView }: { onView: (strategy: Strategy) => void }) {
  const { t } = useTranslation('strategies')
  const builtIns = useBuiltInStrategies()
  return (
    <section className="space-y-3" aria-labelledby="builtin-title">
      <div className="space-y-0.5">
        <h2 id="builtin-title" className="text-base font-semibold">
          {t('library.builtinTitle')}
        </h2>
        <p className="text-xs text-muted-foreground">{t('library.builtinNote')}</p>
      </div>
      {builtIns.isPending && <LoadingGrid />}
      {builtIns.isError && <ErrorState error={builtIns.error} title={t('library.loadFailed')} onRetry={() => void builtIns.refetch()} className="rounded-xl border" />}
      {builtIns.data && (
        <CardGrid>
          {builtIns.data.map((strategy) => (
            <StrategyCard key={strategy.id} strategy={strategy} official copyHref={paths.copyBuiltInStrategy(strategy.id)} onViewRules={() => onView(strategy)} />
          ))}
        </CardGrid>
      )}
    </section>
  )
}

function OwnerStrategies({ onView }: { onView: (strategy: Strategy) => void }) {
  const { t } = useTranslation('strategies')
  const labels = useStrategyLabels()
  const settings = useStrategySettings()
  const save = useSaveStrategySettings()
  const [deleting, setDeleting] = useState<Strategy | null>(null)

  if (settings.isPending) return <LoadingGrid />
  if (settings.isError) return <ErrorState error={settings.error} title={t('library.loadFailed')} onRetry={() => void settings.refetch()} className="rounded-xl border" />
  const current = settings.data

  const submit = (next: StrategySettings, success: string) =>
    save.mutate(next, {
      onSuccess: (saved) => toast.success(success, { description: t('toast.saved', { revision: saved.revision }) }),
      onError: (error) =>
        isApiError(error, 'conflict') ? toast.error(t('toast.conflict')) : toast.error(t('toast.failed', { reason: error.message })),
    })

  const confirmDelete = () => {
    if (!deleting) return
    const next = withoutStrategy(current, deleting.id)
    if (!isRefusal(next)) submit(next, t('toast.deleted', { name: labels.name(deleting) }))
    setDeleting(null)
  }

  if (current.strategies.length === 0) {
    return (
      <StateBlock
        icon={Layers}
        title={t('library.emptyTitle')}
        description={t('library.emptyDescription')}
        className="rounded-xl border"
        action={
          <Button asChild size="sm">
            <Link to={paths.newStrategy}>{t('action.createBlank')}</Link>
          </Button>
        }
      />
    )
  }

  return (
    <>
      <CardGrid>
        {current.strategies.map((strategy) => {
          const refusal = deletionRefusal(current, strategy.id)
          return (
            <StrategyCard
              key={strategy.id}
              strategy={strategy}
              active={current.activeStrategyId === strategy.id}
              buzz={current.buzzStrategyId === strategy.id}
              busy={save.isPending}
              copyHref={paths.copyStrategy(strategy.id)}
              editHref={paths.editStrategy(strategy.id)}
              onActivate={() => submit(withSelection(current, 'active', strategy.id), t('toast.activated', { name: labels.name(strategy) }))}
              onSetBuzz={() => submit(withSelection(current, 'buzz', strategy.id), t('toast.buzz', { name: labels.name(strategy) }))}
              onViewRules={() => onView(strategy)}
              onDelete={() => setDeleting(strategy)}
              deleteBlocked={refusal === null ? undefined : t(refusal === 'selected' ? 'delete.selected' : 'delete.last')}
            />
          )
        })}
      </CardGrid>
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t('delete.title', { name: deleting ? labels.name(deleting) : '' })}
        description={t('delete.description')}
        cancel={t('delete.cancel')}
        confirm={t('delete.confirm')}
        onConfirm={confirmDelete}
        destructive
      />
    </>
  )
}
