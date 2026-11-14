import { ChevronDown, Copy, Eye, FilePlus2, Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { isApiError } from '@/shared/api'
import { useErrorReason } from '@/shared/lib/error-reason'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/shared/ui/dropdown-menu'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Segmented } from '@/shared/ui/segmented'
import { Skeleton } from '@/shared/ui/skeleton'
import { TechnicalStrategyNote } from '@/shared/ui/technical-strategy-note'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { newIds } from '../api/mapping'
import { useBuiltInStrategies, useSaveStrategySettings, useStrategySettings } from '../api/queries'
import { BUILT_IN_IDS, builtInInUse, customStrategies, deletionRefusal, isRefusal, withActive, withBuiltInActive, withoutStrategy, type SettingsRefusal } from '../model/settings'
import type { Strategy, StrategyId, StrategySettings } from '../model/types'
import { requiredBars } from '../model/validate'
import { useStrategyLabels } from '../use-formula-text'
import { StrategyRulesSheet } from './StrategyRulesSheet'

const strategyIds = newIds()

export function StrategyLibraryPage() {
  const { t } = useTranslation('strategies')
  const [viewing, setViewing] = useState<Strategy | null>(null)

  return (
    <div className="space-y-6">
      <PageHeader title={t('library.title')} note={<TechnicalStrategyNote />} actions={<NewStrategyMenu />} />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <Library onView={setViewing} />
      </RequireSignIn>
      <StrategyRulesSheet strategy={viewing} onOpenChange={(open) => !open && setViewing(null)} />
    </div>
  )
}

/** A blank strategy, or a copy of a built-in one to adapt, which the designer opens unsaved. */
function NewStrategyMenu() {
  const { t } = useTranslation('strategies')
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm">
          <FilePlus2 aria-hidden />
          {t('action.create')}
          <ChevronDown aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to={paths.newStrategy}>{t('action.createBlank')}</Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {BUILT_IN_IDS.map((id) => (
          <DropdownMenuItem key={id} asChild>
            <Link to={paths.copyBuiltInStrategy(id)}>
              <Copy aria-hidden />
              {t('action.copyNamed', { name: t(`builtin.${id}.name`) })}
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** The one strategy every workflow uses, picked among the built-ins, and the owner's own strategies below it. */
function Library({ onView }: { onView: (strategy: Strategy) => void }) {
  const reason = useErrorReason()
  const { t } = useTranslation('strategies')
  const labels = useStrategyLabels()
  const settings = useStrategySettings()
  const builtIns = useBuiltInStrategies()
  const save = useSaveStrategySettings()
  const [deleting, setDeleting] = useState<Strategy | null>(null)

  if (settings.isPending || builtIns.isPending) return <Skeleton className="h-64 rounded-xl" />
  if (settings.isError || builtIns.isError) {
    const retry = () => void Promise.all([settings.refetch(), builtIns.refetch()])
    return <ErrorState error={settings.error ?? builtIns.error} title={t('library.loadFailed')} onRetry={retry} className="rounded-xl border" />
  }
  const current = settings.data
  const inUse = builtInInUse(current, builtIns.data)
  const mine = customStrategies(current, builtIns.data)
  const active = current.strategies.find((strategy) => strategy.id === current.activeStrategyId)

  const submit = (next: StrategySettings, success: string) =>
    save.mutate(next, {
      onSuccess: (saved) => toast.success(success, { description: t('toast.saved', { revision: saved.revision }) }),
      onError: (error) =>
        isApiError(error, 'conflict') ? toast.error(t('toast.conflict')) : toast.error(t('toast.failed', { reason: reason(error) })),
    })

  const chooseBuiltIn = (id: string) => {
    const builtIn = builtIns.data.find((strategy) => strategy.id === id)
    if (!builtIn || save.isPending) return
    const next = withBuiltInActive(current, builtIn, strategyIds('stg') as StrategyId)
    if (isRefusal(next)) toast.error(t('toast.full'))
    else submit(next, t('toast.activated', { name: labels.name(builtIn) }))
  }

  const confirmDelete = () => {
    if (!deleting) return
    const next = withoutStrategy(current, deleting.id)
    if (!isRefusal(next)) submit(next, t('toast.deleted', { name: labels.name(deleting) }))
    setDeleting(null)
  }

  return (
    <>
      <section className="space-y-3" aria-labelledby="in-use-title">
        <h2 id="in-use-title" className="text-base font-semibold">
          {t('library.inUseTitle')}
        </h2>
        <Segmented
          label={t('library.inUseTitle')}
          value={inUse?.id ?? ''}
          onChange={chooseBuiltIn}
          options={builtIns.data.map((strategy) => ({ value: strategy.id, label: labels.name(strategy) }))}
          className="md:h-10 md:*:px-5 md:*:text-sm"
        />
        {inUse ? (
          <div className="space-y-1">
            <p className="max-w-prose text-sm text-pretty text-muted-foreground">{labels.purpose(inUse)}</p>
            <Button type="button" size="xs" variant="ghost" className="-ml-2" onClick={() => onView(inUse)}>
              <Eye aria-hidden />
              {t('action.viewRules')}
            </Button>
          </div>
        ) : (
          active && <p className="text-sm text-muted-foreground">{t('library.customInUse', { name: labels.name(active) })}</p>
        )}
      </section>

      <section className="space-y-3" aria-labelledby="custom-title">
        <h2 id="custom-title" className="text-base font-semibold">
          {t('library.customTitle')}
        </h2>
        {mine.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('library.empty')}</p>
        ) : (
          <ul className="divide-y rounded-xl border bg-card shadow-card">
            {mine.map((strategy) => (
              <MyStrategy
                key={strategy.id}
                strategy={strategy}
                active={strategy.id === current.activeStrategyId}
                busy={save.isPending}
                deleteBlocked={deletionRefusal(current, strategy.id)}
                onActivate={() => submit(withActive(current, strategy.id), t('toast.activated', { name: labels.name(strategy) }))}
                onDelete={() => setDeleting(strategy)}
              />
            ))}
          </ul>
        )}
      </section>

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

interface MyStrategyProps {
  strategy: Strategy
  active: boolean
  busy: boolean
  /** Why the strategy cannot be deleted now, said on its delete button instead. */
  deleteBlocked: SettingsRefusal | null
  onActivate: () => void
  onDelete: () => void
}

function MyStrategy({ strategy, active, busy, deleteBlocked, onActivate, onDelete }: MyStrategyProps) {
  const { t } = useTranslation('strategies')
  const labels = useStrategyLabels()
  const name = labels.name(strategy)
  const blocked = deleteBlocked === null ? undefined : t(deleteBlocked === 'selected' ? 'delete.selected' : 'delete.last')

  return (
    <li aria-label={name} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
      <div className="min-w-48 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{name}</span>
          {active && <Badge>{t('inUse')}</Badge>}
        </div>
        <p className="tabular text-xs text-muted-foreground">{t('meta', { rules: strategy.rules.length, bars: requiredBars(strategy) })}</p>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {!active && (
          <Button type="button" size="xs" variant="outline" onClick={onActivate} disabled={busy}>
            {t('action.activate')}
          </Button>
        )}
        <Button asChild size="xs" variant="ghost">
          <Link to={paths.editStrategy(strategy.id)}>
            <Pencil aria-hidden />
            {t('action.edit')}
          </Link>
        </Button>
        <Button asChild size="xs" variant="ghost">
          <Link to={paths.copyStrategy(strategy.id)} aria-label={t('action.copyNamed', { name })}>
            <Copy aria-hidden />
            {t('action.duplicate')}
          </Link>
        </Button>
        <Button
          type="button"
          size="icon-xs"
          variant="ghost"
          className="text-muted-foreground hover:text-destructive"
          onClick={onDelete}
          disabled={busy || blocked !== undefined}
          aria-label={t('action.deleteNamed', { name })}
          aria-describedby={blocked ? `${strategy.id}-delete-blocked` : undefined}
        >
          <Trash2 aria-hidden />
        </Button>
      </div>
      {blocked && (
        <p id={`${strategy.id}-delete-blocked`} className="w-full text-xs text-pretty text-muted-foreground">
          {blocked}
        </p>
      )}
    </li>
  )
}
