import { ChevronDown, CircleAlert, Eye, FolderPlus, Pencil, Plus, Trash2 } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useId, type ReactNode } from 'react'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/shared/ui/toggle-group'
import { COMPARATORS, RULE_EFFECTS, isCrossing } from '../model/catalog'
import { describeComparison, describeCondition } from '../model/describe'
import { blankComparison, blankGroup, indicatorIdsOf, measuresVolume, type StrategyEdit } from '../model/edit'
import type { Comparison, ConditionGroup, GroupOperator, IdFactory, NodeId, Rule, RuleEffect, Strategy } from '../model/types'
import { isBlocking, ruleHasIssues, type IssueOwner, type ValidationIssue } from '../model/validate'
import { useFormulaText } from '../use-formula-text'
import { Field, FieldError, type IssueLookup } from './fields'
import { OperandEditor, type OperandContext } from './OperandEditor'

export interface EditorContext {
  strategy: Strategy
  edit: (change: StrategyEdit) => void
  issue: IssueLookup
  issueOf: (owner: IssueOwner) => ValidationIssue | undefined
  ids: IdFactory
  expanded: ReadonlySet<NodeId>
  toggle: (id: NodeId, open?: boolean) => void
}

interface RuleCardProps {
  context: EditorContext
  rule: Rule
  index: number
  targeted: boolean
  onTarget: () => void
}

export function RuleCard({ context, rule, index, targeted, onTarget }: RuleCardProps) {
  const { t } = useTranslation('builder')
  const text = useFormulaText()
  const nameId = useId()
  const { strategy, edit, issue } = context
  const hasIssues = ruleHasIssues(context.issueOf, rule)

  return (
    <motion.section
      layout="position"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      onFocusCapture={onTarget}
      onPointerDown={onTarget}
      aria-label={t('rule.label', { index: index + 1 })}
      className={cn(
        'rounded-xl border bg-card shadow-card transition-colors',
        targeted && 'border-primary/40 ring-1 ring-primary/20',
        hasIssues && 'border-destructive/40',
      )}
    >
      <header className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-end">
        <div className="flex min-w-0 flex-1 items-end gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted font-mono text-sm text-muted-foreground">
            {String(index + 1).padStart(2, '0')}
          </span>
          <div className="min-w-0 flex-1 space-y-1.5">
            <Label htmlFor={nameId} className="text-xs text-muted-foreground">
              {t('rule.name')}
            </Label>
            <Input
              id={nameId}
              value={rule.name}
              onChange={(event) => edit({ type: 'setRuleName', ruleId: rule.id, name: event.target.value })}
              placeholder={t('rule.namePlaceholder')}
              className="md:h-9"
              aria-invalid={isBlocking(issue(`rule:${rule.id}`)) ? true : undefined}
              aria-describedby={issue(`rule:${rule.id}`) ? `${nameId}-error` : undefined}
            />
            <FieldError id={`${nameId}-error`} issue={issue(`rule:${rule.id}`)} />
          </div>
        </div>
        <div className="flex items-end gap-2">
          <EffectPicker value={rule.effect} onChange={(effect) => edit({ type: 'setRuleEffect', ruleId: rule.id, effect })} />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="text-muted-foreground hover:text-destructive md:size-9"
            onClick={() => edit({ type: 'removeRule', ruleId: rule.id })}
            aria-label={t('rule.remove', { index: index + 1 })}
          >
            <Trash2 aria-hidden className="size-4" />
          </Button>
        </div>
      </header>

      <div className="space-y-3 p-4">
        <GroupBody context={context} group={rule.condition} root />
        <p className="rounded-lg bg-muted/50 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
          <span className="font-medium text-foreground">{t('rule.preview')} </span>
          <span className="first-letter:uppercase">{describeCondition(rule.condition, strategy, text)}</span>
        </p>
      </div>
    </motion.section>
  )
}

function EffectPicker({ value, onChange }: { value: RuleEffect; onChange: (effect: RuleEffect) => void }) {
  const { t } = useTranslation('builder')
  const id = useId()
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {t('rule.effect')}
      </Label>
      <Select value={value} onValueChange={(effect) => onChange(effect as RuleEffect)}>
        <SelectTrigger id={id} className="w-40 md:h-9">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {RULE_EFFECTS.map((effect) => (
            <SelectItem key={effect} value={effect}>
              {t(`strategies:effect.${effect}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function GroupOperatorToggle({ group, edit }: { group: ConditionGroup; edit: EditorContext['edit'] }) {
  const { t } = useTranslation('builder')
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">{t('group.match')}</span>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={group.operator}
        onValueChange={(value) => value && edit({ type: 'setGroupOperator', groupId: group.id, operator: value as GroupOperator })}
        aria-label={t('group.match')}
      >
        <ToggleGroupItem value="all" className="px-3 text-xs">
          {t('group.all')}
        </ToggleGroupItem>
        <ToggleGroupItem value="any" className="px-3 text-xs">
          {t('group.any')}
        </ToggleGroupItem>
      </ToggleGroup>
    </div>
  )
}

function GroupBody({ context, group, root = false }: { context: EditorContext; group: ConditionGroup; root?: boolean }) {
  const { t } = useTranslation('builder')
  const { edit, ids, toggle, issue } = context

  const addComparison = () => {
    const { condition, indicators } = blankComparison(ids)
    edit({ type: 'addCondition', groupId: group.id, condition, indicators })
    toggle(condition.id, true)
  }

  const addGroup = () => {
    const { condition, indicators } = blankGroup(ids, group.operator === 'all' ? 'any' : 'all')
    edit({ type: 'addCondition', groupId: group.id, condition, indicators })
    toggle(condition.conditions[0]!.id, true)
  }

  return (
    <div className="space-y-3">
      <GroupOperatorToggle group={group} edit={edit} />
      <FieldError id={`${group.id}-error`} issue={issue(`node:${group.id}`)} />
      <ol className="space-y-2">
        <AnimatePresence initial={false}>
          {group.conditions.map((condition, index) => (
            <motion.li
              key={condition.id}
              layout="position"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2 }}
            >
              {index > 0 && (
                <div className="mb-2 flex items-center gap-2 text-[0.6875rem] font-medium tracking-wide text-muted-foreground uppercase" aria-hidden>
                  <span className="h-px flex-1 bg-border" />
                  {t(`formula:join.${group.operator}`)}
                  <span className="h-px flex-1 bg-border" />
                </div>
              )}
              {condition.type === 'group' ? (
                <NestedGroup context={context} group={condition} />
              ) : (
                <ComparisonItem context={context} comparison={condition} />
              )}
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={addComparison}>
          <Plus aria-hidden className="size-4" />
          {t('group.addCondition')}
        </Button>
        {root && (
          <Button type="button" variant="ghost" size="sm" onClick={addGroup}>
            <FolderPlus aria-hidden className="size-4" />
            {t('group.addGroup')}
          </Button>
        )}
      </div>
    </div>
  )
}

function NestedGroup({ context, group }: { context: EditorContext; group: ConditionGroup }) {
  const { t } = useTranslation('builder')
  const text = useFormulaText()
  return (
    <div className="rounded-xl border border-dashed bg-muted/20 p-3">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-medium">{t('group.nested')}</div>
          <p className="truncate text-xs text-muted-foreground">{describeCondition(group, context.strategy, text)}</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-xs text-muted-foreground hover:text-destructive md:h-7"
          onClick={() => context.edit({ type: 'removeCondition', conditionId: group.id })}
        >
          <Trash2 aria-hidden className="size-3.5" />
          {t('group.removeGroup')}
        </Button>
      </div>
      <GroupBody context={context} group={group} />
    </div>
  )
}

function ComparisonItem({ context, comparison }: { context: EditorContext; comparison: Comparison }) {
  const { t } = useTranslation('builder')
  const text = useFormulaText()
  const open = context.expanded.has(comparison.id)
  const invalid =
    context.issueOf({ conditionId: comparison.id }) !== undefined ||
    [...indicatorIdsOf(comparison)].some((indicatorId) => context.issueOf({ indicatorId }) !== undefined)
  const sentence = describeComparison(comparison, context.strategy, text)

  return (
    <div className={cn('rounded-xl border bg-background/40 transition-colors', open && 'bg-background shadow-sm', invalid && 'border-destructive/40')}>
      <div className="flex items-start gap-2 p-3">
        <button
          type="button"
          onClick={() => context.toggle(comparison.id)}
          aria-expanded={open}
          className="flex min-h-11 min-w-0 flex-1 items-start gap-2 rounded-md py-1 text-left md:min-h-0 md:py-0"
        >
          <ChevronDown aria-hidden className={cn('mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform', !open && '-rotate-90')} />
          <span className="min-w-0 text-sm leading-relaxed first-letter:uppercase">{sentence}</span>
        </button>
        <div className="flex shrink-0 items-center gap-1">
          {invalid && (
            <span className="flex items-center gap-1 text-xs text-destructive">
              <CircleAlert aria-hidden className="size-3.5" />
              <span className="max-sm:sr-only">{t('condition.needsFix')}</span>
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="text-muted-foreground md:size-8"
            onClick={() => context.toggle(comparison.id)}
            aria-label={t(open ? 'condition.collapse' : 'condition.edit')}
          >
            {open ? <Eye aria-hidden className="size-4" /> : <Pencil aria-hidden className="size-4" />}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="text-muted-foreground hover:text-destructive md:size-8"
            onClick={() => context.edit({ type: 'removeCondition', conditionId: comparison.id })}
            aria-label={t('condition.remove')}
          >
            <Trash2 aria-hidden className="size-4" />
          </Button>
        </div>
      </div>
      {open && <ComparisonEditor context={context} comparison={comparison} />}
    </div>
  )
}

function ComparisonEditor({ context, comparison }: { context: EditorContext; comparison: Comparison }) {
  const { t } = useTranslation('builder')
  const comparatorId = useId()
  const operandContext: OperandContext = {
    strategy: context.strategy,
    conditionId: comparison.id,
    edit: context.edit,
    issue: context.issue,
    ids: context.ids,
  }
  const volumeUnit = measuresVolume(comparison.left, context.strategy.indicators) || measuresVolume(comparison.right, context.strategy.indicators)

  return (
    <div className="@container border-t px-3 pb-3 sm:px-4 sm:pb-4">
      <div className="divide-y">
        <Step number={1} title={t('condition.observe')} hint={t('condition.observeHint')}>
          <OperandEditor context={operandContext} path={['left']} expression={comparison.left} volumeUnit={volumeUnit} />
        </Step>
        <Step number={2} title={t('condition.judge')} hint={t('condition.judgeHint')}>
          <Field label={t('condition.comparator')} htmlFor={comparatorId} className="max-w-64">
            <Select
              value={comparison.operator}
              onValueChange={(operator) => context.edit({ type: 'setComparator', conditionId: comparison.id, operator: operator as Comparison['operator'] })}
            >
              <SelectTrigger id={comparatorId} className="w-full md:h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COMPARATORS.map((operator) => (
                  <SelectItem key={operator} value={operator}>
                    {t(`formula:comparator.${operator}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {isCrossing(comparison.operator) && (
            <p className="text-[0.6875rem] leading-relaxed text-muted-foreground">{t(`condition.${comparison.operator}Hint`)}</p>
          )}
        </Step>
        <Step number={3} title={t('condition.compare')} hint={t('condition.compareHint')}>
          <OperandEditor context={operandContext} path={['right']} expression={comparison.right} volumeUnit={volumeUnit} />
        </Step>
      </div>
      <FieldError id={`${comparison.id}-node-error`} issue={context.issue(`node:${comparison.id}`)} />
      <div className="mt-3 flex justify-end">
        <Button type="button" size="sm" variant="secondary" onClick={() => context.toggle(comparison.id, false)}>
          {t('condition.done')}
        </Button>
      </div>
    </div>
  )
}

function Step({ number, title, hint, children }: { number: number; title: string; hint: string; children: ReactNode }) {
  return (
    <fieldset className="grid gap-3 py-4 @2xl:grid-cols-[9rem_minmax(0,1fr)] @2xl:gap-5">
      <legend className="sr-only">{title}</legend>
      <div aria-hidden className="flex items-start gap-2 @2xl:flex-col @2xl:gap-1">
        <span className="flex items-center gap-2">
          <span className="grid size-5 place-items-center rounded-full bg-primary/15 text-[0.6875rem] font-semibold text-primary">{number}</span>
          <span className="text-sm font-medium">{title}</span>
        </span>
        <span className="text-xs text-muted-foreground @2xl:pl-7">{hint}</span>
      </div>
      <div className="min-w-0 space-y-2">{children}</div>
    </fieldset>
  )
}
