import {
  ArrowLeft,
  BarChart3,
  CandlestickChart,
  CheckCircle2,
  CircleAlert,
  Eye,
  Gauge,
  ListPlus,
  Save,
  SlidersHorizontal,
  Sparkles,
  Volume2,
  Waves,
} from 'lucide-react'
import { AnimatePresence } from 'motion/react'
import { useCallback, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { cn } from '@/shared/lib/utils'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ConfirmDialog } from '@/shared/ui/confirm-dialog'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Panel } from '@/shared/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/shared/ui/sheet'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { useBuiltInStrategies, useStrategySettings } from '../api/queries'
import { blankRule } from '../model/edit'
import { QUICK_FILLS, quickFill, type QuickFillKind } from '../model/quick-fill'
import type { NodeId, Scoring, Strategy } from '../model/types'
import { errorsOf, issuesByOwner, issuesByPath, requiredBars } from '../model/validate'
import { RuleSummaryList } from '../library/RuleSummaryList'
import { useStrategyLabels } from '../use-formula-text'
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
  return <Builder initial={source.strategy} isNew={source.isNew} />
}

const QUICK_FILL_ICON: Record<QuickFillKind, typeof Waves> = {
  maCross: Waves,
  macdCross: CandlestickChart,
  rsiThreshold: Gauge,
  volumeAboveAverage: BarChart3,
  volumeAboveYesterday: Volume2,
}

function Builder({ initial, isNew }: { initial: Strategy; isNew: boolean }) {
  const { t } = useTranslation('builder')
  const navigate = useNavigate()
  const { draft, edit, issues, attempted, dirty, save, saving, conflict, serverChanged, revision, blocker } = useStrategyDraft(initial)
  const [refused, setRefused] = useState<{ rule: number | null; message: string }[]>([])
  const [expanded, setExpanded] = useState<Set<NodeId>>(() => {
    const first = initial.rules[0]?.condition.conditions[0]
    return new Set(isNew && initial.rules.length === 1 && first ? [first.id] : [])
  })
  const [targetRuleId, setTargetRuleId] = useState<NodeId | null>(initial.rules[0]?.id ?? null)
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
  const target = draft.rules.find((rule) => rule.id === targetRuleId) ?? draft.rules.at(-1) ?? null

  const addRule = () => {
    const { rule, indicators } = blankRule(draftIds)
    edit({ type: 'addRule', rule, indicators })
    setTargetRuleId(rule.id)
    toggle(rule.condition.conditions[0]!.id, true)
  }

  const applyQuickFill = (kind: QuickFillKind) => {
    const { condition, indicators } = quickFill(kind, draftIds)
    if (target) {
      edit({ type: 'addCondition', groupId: target.condition.id, condition, indicators })
    } else {
      const { rule } = blankRule(draftIds)
      edit({ type: 'addRule', rule: { ...rule, condition: { ...rule.condition, conditions: [condition] } }, indicators })
      setTargetRuleId(rule.id)
    }
    toggle(condition.id, true)
    toast.success(t('quickFill.added', { name: t(`quickFill.kind.${kind}`) }), { description: t('quickFill.editable') })
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
          const first = document.querySelector<HTMLElement>('[aria-invalid="true"], [data-invalid="true"]')
          first?.focus()
          first?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        })
        return
      case 'conflict':
        toast.error(t('save.conflict'))
        return
      case 'refused':
        setRefused(result.problems)
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

  return (
    <div className="space-y-4 pb-24 xl:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground">
          <Link to={paths.strategies}>
            <ArrowLeft aria-hidden className="size-4" />
            {t('backToLibrary')}
          </Link>
        </Button>
        <SaveStatus tone={statusTone} revision={revision} />
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
            {refused.map((problem, index) => (
              <li key={index}>
                {problem.rule !== null && <span className="font-medium text-foreground">{t('rule.label', { index: problem.rule + 1 })}: </span>}
                {problem.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <header className="space-y-1">
        <div className="eyebrow">{t(isNew ? 'eyebrowNew' : 'eyebrowEdit')}</div>
        <h1 className="display">{draft.name.trim() || t('untitled')}</h1>
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-4">
          <QuickFillBar target={target} strategy={draft} onTarget={setTargetRuleId} onFill={applyQuickFill} />

          <FieldError id="rules-error" issue={issue('rules')} />
          <div className="space-y-4">
            <AnimatePresence initial={false}>
              {draft.rules.map((rule, index) => (
                <RuleCard
                  key={rule.id}
                  context={context}
                  rule={rule}
                  index={index}
                  targeted={target?.id === rule.id}
                  onTarget={() => setTargetRuleId(rule.id)}
                />
              ))}
            </AnimatePresence>
          </div>
          <Button type="button" variant="outline" className="w-full border-dashed" onClick={addRule}>
            <ListPlus aria-hidden className="size-4" />
            {t('rule.add')}
          </Button>
        </div>

        <aside className="space-y-4 xl:sticky xl:top-[calc(var(--topbar-height)+1rem)] xl:self-start">
          <PreviewCard strategy={draft} />
          <ScoringCard scoring={draft.scoring} onChange={(key, value) => edit({ type: 'setScoring', key, value })} issue={issue} />
          <NameCard
            strategy={draft}
            issue={issue}
            onName={(name) => edit({ type: 'setName', name })}
            onSave={() => void handleSave()}
            saving={saving}
            dirty={dirty}
            errorCount={errorCount}
            attempted={attempted}
          />
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
            <Button type="button" onClick={() => void handleSave()} disabled={saving}>
              <Save aria-hidden className="size-4" />
              {t('save.action')}
            </Button>
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

function QuickFillBar({
  target,
  strategy,
  onTarget,
  onFill,
}: {
  target: Strategy['rules'][number] | null
  strategy: Strategy
  onTarget: (id: NodeId) => void
  onFill: (kind: QuickFillKind) => void
}) {
  const { t } = useTranslation('builder')
  const labels = useStrategyLabels()
  return (
    <Panel
      title={
        <>
          <Sparkles aria-hidden className="size-4 text-muted-foreground" />
          {t('quickFill.title')}
        </>
      }
      aside={
        strategy.rules.length > 0 && (
          <div className="flex items-center gap-2">
            <Label htmlFor="quick-fill-target" className="text-xs text-muted-foreground">
              {t('quickFill.target')}
            </Label>
            <Select value={target?.id ?? ''} onValueChange={(value) => onTarget(value as NodeId)}>
              <SelectTrigger id="quick-fill-target" className="w-44 md:h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {strategy.rules.map((rule, index) => (
                  <SelectItem key={rule.id} value={rule.id}>
                    {labels.rule(rule.name.trim()) || t('rule.label', { index: index + 1 })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )
      }
    >
      <p className="text-xs text-muted-foreground">{t('quickFill.description')}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {QUICK_FILLS.map((kind) => {
          const Icon = QUICK_FILL_ICON[kind]
          return (
            <Button key={kind} type="button" variant="outline" size="sm" onClick={() => onFill(kind)} className="hover:border-primary/40">
              <Icon aria-hidden className="size-4 text-primary" />
              {t(`quickFill.kind.${kind}`)}
            </Button>
          )
        })}
      </div>
    </Panel>
  )
}

function PreviewCard({ strategy }: { strategy: Strategy }) {
  const { t } = useTranslation('builder')
    return (
    <Panel
      title={t('preview.title')}
      aside={
        <Badge variant="outline" className="tabular font-normal">
          {t('preview.bars', { count: requiredBars(strategy) })}
        </Badge>
      }
    >
      {strategy.rules.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('preview.empty')}</p>
      ) : (
        <div aria-live="polite">
          <RuleSummaryList strategy={strategy} named />
        </div>
      )}
    </Panel>
  )
}

function ScoringCard({
  scoring,
  onChange,
  issue,
}: {
  scoring: Scoring
  onChange: (key: keyof Scoring, value: number) => void
  issue: (path: string) => ReturnType<EditorContext['issue']>
}) {
  const { t } = useTranslation('builder')
  const [open, setOpen] = useState(false)
  const keys: (keyof Scoring)[] = ['baseScore', 'blockFailurePenalty', 'failureScoreReduction', 'passScoreIncrease']
  return (
    <Panel
      title={
        <>
          <SlidersHorizontal aria-hidden className="size-4 text-muted-foreground" />
          {t('scoring.title')}
        </>
      }
      aside={
        <Button type="button" variant="ghost" size="sm" onClick={() => setOpen((value) => !value)} aria-expanded={open} className="-my-1 text-brand">
          {t(open ? 'scoring.hide' : 'scoring.show')}
        </Button>
      }
    >
      <p className="text-xs text-muted-foreground">{t('scoring.summary', { base: scoring.baseScore })}</p>
      {open && (
        <div className="mt-3 grid grid-cols-2 gap-3">
          {keys.map((key) => (
            <NumberField key={key} label={t(`scoring.${key}`)} value={scoring[key]} onChange={(value) => onChange(key, value)} issue={issue(`scoring:${key}`)} />
          ))}
          <p className="col-span-2 text-[0.6875rem] leading-relaxed text-muted-foreground">{t('scoring.note')}</p>
        </div>
      )}
    </Panel>
  )
}

function NameCard({
  strategy,
  issue,
  onName,
  onSave,
  saving,
  dirty,
  errorCount,
  attempted,
}: {
  strategy: Strategy
  issue: (path: string) => ReturnType<EditorContext['issue']>
  onName: (name: string) => void
  onSave: () => void
  saving: boolean
  dirty: boolean
  errorCount: number
  attempted: boolean
}) {
  const { t } = useTranslation('builder')
  const nameIssue = issue('name')
  return (
    <Panel title={t('name.title')}>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="strategy-name" className="text-xs text-muted-foreground">
            {t('name.label')}
          </Label>
          <Input
            id="strategy-name"
            value={strategy.name}
            onChange={(event) => onName(event.target.value)}
            placeholder={t('name.placeholder')}
            aria-invalid={nameIssue ? true : undefined}
            aria-describedby={nameIssue ? 'strategy-name-error' : undefined}
          />
          <FieldError id="strategy-name-error" issue={nameIssue} />
          <p className="font-mono text-[0.6875rem] text-muted-foreground">{t('name.id', { id: strategy.id })}</p>
        </div>
        {attempted && errorCount > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-destructive" role="alert">
            <CircleAlert aria-hidden className="size-3.5" />
            {t('save.invalid', { count: errorCount })}
          </p>
        )}
        <Button type="button" className="w-full max-xl:hidden" onClick={onSave} disabled={saving}>
          <Save aria-hidden className="size-4" />
          {t(saving ? 'save.saving' : 'save.action')}
        </Button>
        {dirty && <p className="text-center text-xs text-muted-foreground max-xl:hidden">{t('save.hintDirty')}</p>}
      </div>
    </Panel>
  )
}
