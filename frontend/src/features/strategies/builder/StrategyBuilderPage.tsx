import { ArrowLeft, CheckCircle2, ChevronDown, CircleAlert, Eye, ListPlus, Save, SlidersHorizontal } from 'lucide-react'
import { AnimatePresence } from 'motion/react'
import { useCallback, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { usePageTitle } from '@/shared/lib/page-title'
import { useStrategyLabels } from '@/shared/lib/strategy-labels'
import { paths } from '@/shared/config/paths'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Panel } from '@/shared/ui/panel'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/shared/ui/sheet'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { useBuiltInStrategies, useStrategySettings } from '../api/queries'
import { blankRule } from '../model/edit'
import type { NodeId, Scoring, Strategy } from '../model/types'
import { errorsOf, issuesByOwner, issuesByPath, requiredBars } from '../model/validate'
import { RuleSummaryList } from '../library/RuleSummaryList'
import { FieldError, NumberField } from './fields'
import { RuleCard, type EditorContext } from './RuleCard'
import { draftIds, resolveDraftSource, useStrategyDraft, type BuilderMode, type DraftSource } from './use-strategy-draft'

interface StrategyBuilderPageProps {
  mode: BuilderMode
}

export function StrategyBuilderPage({ mode }: StrategyBuilderPageProps) {
  const { t } = useTranslation('builder')
  return (
    <RequireSignIn layout="page" reason={t('signIn')}>
      <BuilderSource mode={mode} />
    </RequireSignIn>
  )
}

/** Resolves the draft's starting point once both lists load; later refetches never replace a draft in progress. */
function BuilderSource({ mode }: StrategyBuilderPageProps) {
  const { t } = useTranslation('builder')
  const strategyText = useTranslation('strategies').t
  const labels = useStrategyLabels()
  const settings = useStrategySettings()
  const builtIns = useBuiltInStrategies()
  const [source, setSource] = useState<DraftSource | null>(null)
  if (source === null && settings.data && builtIns.data) {
    const copyName = (original: Strategy) => strategyText('copyName', { name: labels.name(original) })
    setSource(resolveDraftSource(mode, settings.data.strategies, builtIns.data, { copyName, ruleName: labels.rule }))
  }
  if (source === null && (settings.isError || builtIns.isError)) {
    const retry = () => void Promise.all([settings.refetch(), builtIns.refetch()])
    return <ErrorState error={settings.error ?? builtIns.error} title={t('loadFailed')} onRetry={retry} className="rounded-xl border" />
  }
  if (source === null) return <Skeleton className="h-96 rounded-xl" />
  if (source.status === 'missing') {
    return (
      <StateBlock
        icon={CircleAlert}
        title={t('missing.title')}
        description={t('missing.description')}
        className="rounded-xl border"
        action={
          <Button asChild variant="outline">
            <Link to={paths.strategies}>{t('backToLibrary')}</Link>
          </Button>
        }
      />
    )
  }
  return <Builder initial={source.strategy} isNew={source.isNew} name={mode.type === 'blank' ? mode.type : `${mode.type}:${mode.type === 'copy' ? mode.source : ''}:${mode.id}`} />
}

/** `name` tells this draft from the other drafts the user may have open: the strategy edited, or the source of a copy. */
function Builder({ initial, isNew, name }: { initial: Strategy; isNew: boolean; name: string }) {
  const { t } = useTranslation('builder')
  const navigate = useNavigate()
  const { draft, edit, issues, attempted, dirty, save, saving, conflict, serverChanged, revision, blocker } = useStrategyDraft(initial, name)
  const [refused, setRefused] = useState<(number | null)[]>([])
  const [expanded, setExpanded] = useState<Set<NodeId>>(() => {
    const first = initial.rules[0]?.condition.conditions[0]
    return new Set(isNew && initial.rules.length === 1 && first ? [first.id] : [])
  })
  const [savedOnce, setSavedOnce] = useState(!isNew)

  const visibleIssues = useMemo(
    () => (attempted ? issues : issues.filter((issue) => issue.code !== 'required' && issue.code !== 'noRules')),
    [issues, attempted],
  )
  const errorCount = errorsOf(issues).length
  const lookup = useMemo(() => issuesByPath(visibleIssues), [visibleIssues])
  const issue = useCallback((path: string) => lookup.get(path), [lookup])
  const issueOf = useMemo(() => issuesByOwner(visibleIssues), [visibleIssues])

  const toggle = useCallback((id: NodeId, open?: boolean) => {
    setExpanded((current) => {
      const next = new Set(current)
      const shouldOpen = open ?? !next.has(id)
      if (shouldOpen) next.add(id)
      else next.delete(id)
      return next
    })
  }, [])

  const context: EditorContext = { strategy: draft, edit, issue, issueOf, ids: draftIds, expanded, toggle }

  const addRule = () => {
    const { rule, indicators } = blankRule(draftIds)
    edit({ type: 'addRule', rule, indicators })
    toggle(rule.condition.conditions[0]!.id, true)
  }

  const handleSave = async () => {
    setRefused([])
    const result = await save()
    if (result.ok) {
      toast.success(t('save.success'), { description: t('save.successDetail', { revision: result.settings.revision }) })
      setSavedOnce(true)
      if (isNew) navigate(paths.editStrategy(draft.id), { replace: true })
      return
    }
    switch (result.reason) {
      case 'invalid':
        toast.error(t('save.invalid', { count: errorCount }))
        requestAnimationFrame(() => {
          const first = document.querySelector<HTMLElement>('[aria-invalid="true"]')
          first?.focus()
          first?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        })
        return
      case 'conflict':
        toast.error(t('save.conflict'))
        return
      case 'refused':
        setRefused(result.rules)
        toast.error(t('save.refused'))
        return
      case 'full':
        toast.error(t('save.full'))
        return
      case 'notLoaded':
        toast.error(t('save.notLoaded'))
        return
      case 'failed':
        toast.error(t('save.failed'))
    }
  }

  const statusTone = dirty ? 'pending' : savedOnce ? 'saved' : 'new'
  const saveButton = (className?: string) => (
    <Button type="button" className={className} onClick={() => void handleSave()} disabled={saving}>
      <Save aria-hidden className="size-4" />
      {t(saving ? 'save.saving' : 'save.action')}
    </Button>
  )

  return (
    <div className="space-y-5 pb-24 xl:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground">
          <Link to={paths.strategies}>
            <ArrowLeft aria-hidden className="size-4" />
            {t('backToLibrary')}
          </Link>
        </Button>
        <div className="flex items-center gap-3">
          <SaveStatus tone={statusTone} revision={revision} />
          {saveButton('max-xl:hidden')}
        </div>
      </div>

      {conflict && (
        <div role="alert" className="flex flex-wrap items-start gap-3 rounded-lg border border-gold/40 bg-gold-soft px-3 py-2.5 text-sm">
          <CircleAlert aria-hidden className="mt-0.5 size-4 text-gold" />
          <div className="flex-1 space-y-1">
            <p className="font-medium">{t('conflict.title')}</p>
            <p className="text-muted-foreground">{t(serverChanged ? 'conflict.sameStrategy' : 'conflict.otherChanges')}</p>
          </div>
          <Button type="button" size="sm" onClick={() => void handleSave()} disabled={saving}>
            {t('conflict.reapply')}
          </Button>
        </div>
      )}

      {refused.length > 0 && (
        <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm">
          <p className="font-medium">{t('save.refusedTitle')}</p>
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
            {refused.map((rule) => (
              <li key={rule ?? 'strategy'}>
                {rule !== null && <span className="font-medium text-foreground">{t('rule.label', { index: rule + 1 })}: </span>}
                {t('common:errors.invalid')}
              </li>
            ))}
          </ul>
        </div>
      )}

      <StrategyHeading strategy={draft} edit={edit} issue={issue} />
      {attempted && errorCount > 0 && (
        <p className="flex items-center gap-1.5 text-xs text-destructive" role="alert">
          <CircleAlert aria-hidden className="size-3.5" />
          {t('save.invalid', { count: errorCount })}
        </p>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-3">
          <FieldError id="rules-error" issue={issue('rules')} />
          <AnimatePresence initial={false}>
            {draft.rules.map((rule, index) => (
              <RuleCard key={rule.id} context={context} rule={rule} index={index} />
            ))}
          </AnimatePresence>
          <Button type="button" variant="outline" className="w-full border-dashed" onClick={addRule}>
            <ListPlus aria-hidden className="size-4" />
            {t('rule.add')}
          </Button>
        </div>

        <aside className="max-xl:hidden xl:sticky xl:top-[calc(var(--topbar-height)+1rem)] xl:self-start">
          <PreviewCard strategy={draft} />
        </aside>
      </div>

      <div className="fixed inset-x-0 bottom-[calc(var(--tabbar-height)+env(safe-area-inset-bottom))] z-30 border-t bg-background/92 p-3 shadow-bar backdrop-blur-md md:bottom-0 md:left-(--rail-width) lg:left-(--sidebar-width) xl:hidden">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
          <SaveStatus tone={statusTone} revision={revision} />
          <div className="flex items-center gap-2">
            <Sheet>
              <SheetTrigger asChild>
                <Button type="button" variant="outline">
                  <Eye aria-hidden className="size-4" />
                  {t('preview.open')}
                </Button>
              </SheetTrigger>
              <SheetContent side="bottom" className="max-h-[80dvh] gap-0 overflow-y-auto rounded-t-2xl p-0">
                <SheetHeader className="sr-only">
                  <SheetTitle>{t('preview.title')}</SheetTitle>
                  <SheetDescription>{t('preview.note')}</SheetDescription>
                </SheetHeader>
                <div className="p-4 pt-10">
                  <PreviewCard strategy={draft} />
                </div>
              </SheetContent>
            </Sheet>
            {saveButton()}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={blocker.state === 'blocked'}
        title={t('leave.title')}
        description={t('leave.description')}
        cancel={t('leave.stay')}
        confirm={t('leave.discard')}
        onCancel={() => blocker.reset?.()}
        onConfirm={() => blocker.proceed?.()}
        destructive
      />
    </div>
  )
}

/** The strategy's name, edited in place as the page's title, then its id, the bars it needs and its scoring. */
function StrategyHeading({ strategy, edit, issue }: { strategy: Strategy; edit: EditorContext['edit']; issue: EditorContext['issue'] }) {
  const { t } = useTranslation('builder')
  const [scoringOpen, setScoringOpen] = useState(false)
  const nameIssue = issue('name')
  const keys: (keyof Scoring)[] = ['base_score', 'block_failure_penalty', 'failure_score_reduction', 'pass_score_increase']
  const title = strategy.name.trim() || t('untitled')
  usePageTitle(title)
  return (
    <header className="space-y-2">
      <h1 className="sr-only">{title}</h1>
      <Label htmlFor="strategy-name" className="sr-only">
        {t('name.label')}
      </Label>
      <Input
        id="strategy-name"
        value={strategy.name}
        onChange={(event) => edit({ type: 'setName', name: event.target.value })}
        placeholder={t('untitled')}
        aria-invalid={nameIssue ? true : undefined}
        aria-describedby={nameIssue ? 'strategy-name-error' : undefined}
        className="display h-auto min-h-11 border-transparent bg-transparent px-2 py-1 -ml-2 shadow-none hover:border-input focus-visible:border-ring md:h-auto md:text-[length:inherit]"
      />
      <FieldError id="strategy-name-error" issue={nameIssue} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="font-mono">{t('name.id', { id: strategy.id })}</span>
        <span className="tabular">{t('preview.bars', { count: requiredBars(strategy) })}</span>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="-ml-2 text-muted-foreground"
          onClick={() => setScoringOpen((open) => !open)}
          aria-expanded={scoringOpen}
          aria-controls="strategy-scoring"
        >
          <SlidersHorizontal aria-hidden />
          {t('scoring.summary', { base: strategy.scoring.base_score })}
          <ChevronDown aria-hidden className={cn('transition-transform', scoringOpen && 'rotate-180')} />
        </Button>
      </div>
      {scoringOpen && (
        <div id="strategy-scoring" className="max-w-xl space-y-2 rounded-xl border bg-card p-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {keys.map((key) => (
              <NumberField
                key={key}
                label={t(`scoring.${key}`)}
                value={strategy.scoring[key]}
                onChange={(value) => edit({ type: 'setScoring', key, value })}
                issue={issue(`scoring:${key}`)}
              />
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{t('scoring.note')}</p>
        </div>
      )}
    </header>
  )
}

function SaveStatus({ tone, revision }: { tone: 'pending' | 'saved' | 'new'; revision: number | undefined }) {
  const { t } = useTranslation('builder')
  return (
    <span
      aria-live="polite"
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
        tone === 'pending' && 'border-gold/35 text-gold',
        tone === 'saved' && 'border-brand/35 text-brand',
        tone === 'new' && 'text-muted-foreground',
      )}
    >
      {tone === 'saved' ? <CheckCircle2 aria-hidden className="size-3.5" /> : <span aria-hidden className={cn('size-1.5 rounded-full', tone === 'pending' ? 'bg-gold' : 'bg-muted-foreground')} />}
      {t(`status.${tone}`)}
      {revision !== undefined && <span className="tabular text-muted-foreground">· {t('status.revision', { revision })}</span>}
    </span>
  )
}

function PreviewCard({ strategy }: { strategy: Strategy }) {
  const { t } = useTranslation('builder')
  return (
    <Panel title={t('preview.title')}>
      {strategy.rules.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('preview.empty')}</p>
      ) : (
        <div aria-live="polite">
          <RuleSummaryList strategy={strategy} ruleName={(name) => name} />
        </div>
      )}
    </Panel>
  )
}
