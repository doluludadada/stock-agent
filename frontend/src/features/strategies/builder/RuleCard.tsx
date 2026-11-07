import { BarChart3, CandlestickChart, ChevronDown, CircleAlert, FolderPlus, Gauge, Plus, Sparkles, Trash2, Volume2 } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useId, type ReactNode } from 'react'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/shared/ui/dropdown-menu'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/shared/ui/toggle-group'
import { COMPARATORS, RULE_EFFECTS, isCrossing } from '../model/catalog'
import { describeComparison, describeCondition } from '../model/describe'
import { blankComparison, blankGroup, indicatorIdsOf, measuresVolume, type StrategyEdit } from '../model/edit'
import { QUICK_FILLS, quickFill, type QuickFillKind } from '../model/quick-fill'
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
}

export function RuleCard({ context, rule, index }: RuleCardProps) {
  const { t } = useTranslation('builder')
  const nameId = useId()
  const { edit, issue } = context
  const hasIssues = ruleHasIssues(context.issueOf, rule)

  return (
    <motion.section
      layout="position"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      aria-label={t('rule.label', { index: index + 1 })}
      className={cn('rounded-xl border bg-card shadow-card transition-colors', hasIssues && 'border-destructive/40')}
    >
      <header className="flex flex-wrap items-start gap-2 border-b p-3 sm:flex-nowrap md:px-4">
        <div className="flex min-w-0 flex-1 basis-full items-start gap-2 sm:basis-auto">
          <span aria-hidden className="tabular grid h-11 w-6 shrink-0 place-items-center text-sm text-muted-foreground md:h-9">
            {index + 1}
          </span>
          <div className="min-w-0 flex-1 space-y-1">
            <Label htmlFor={nameId} className="sr-only">
              {t('rule.name')}
            </Label>
            <Input
              id={nameId}
              value={rule.name}
              onChange={(event) => edit({ type: 'setRuleName', ruleId: rule.id, name: event.target.value })}
              placeholder={t('rule.name')}
              className="md:h-9"
              aria-invalid={isBlocking(issue(`rule:${rule.id}`)) ? true : undefined}
              aria-describedby={issue(`rule:${rule.id}`) ? `${nameId}-error` : undefined}
            />
            <FieldError id={`${nameId}-error`} issue={issue(`rule:${rule.id}`)} />
          </div>
        </div>
        <div className="ml-8 flex items-start gap-1 sm:ml-0">
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

      <div className="p-3 md:px-4">
        <GroupBody context={context} group={rule.condition} root />
      </div>
    </motion.section>
  )
}

function EffectPicker({ value, onChange }: { value: RuleEffect; onChange: (effect: RuleEffect) => void }) {
  const { t } = useTranslation('builder')
  const id = useId()
  return (
    <div>
      <Label htmlFor={id} className="sr-only">
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

  const addQuickFill = (kind: QuickFillKind) => {
    const { condition, indicators } = quickFill(kind, ids)
    edit({ type: 'addCondition', groupId: group.id, condition, indicators })
    toggle(condition.id, true)
  }

  return (
    <div className="space-y-3">
      {group.conditions.length > 1 && <GroupOperatorToggle group={group} edit={edit} />}
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
      <div className="flex flex-wrap gap-1">
        <Button type="button" variant="ghost" size="sm" className="-ml-2 text-brand" onClick={addComparison}>
          <Plus aria-hidden className="size-4" />
          {t('group.addCondition')}
        </Button>
        {root && (
          <Button type="button" variant="ghost" size="sm" className="text-muted-foreground" onClick={addGroup}>
            <FolderPlus aria-hidden className="size-4" />
            {t('group.addGroup')}
          </Button>
        )}
        {root && <QuickFillMenu onFill={addQuickFill} />}
      </div>
    </div>
  )
}

const QUICK_FILL_ICON: Record<QuickFillKind, typeof Gauge> = {
  macdCross: CandlestickChart,
  rsiThreshold: Gauge,
  volumeAboveAverage: BarChart3,
  volumeAboveYesterday: Volume2,
}

/** Common conditions, each inserted as an ordinary comparison that stays fully editable. */
function QuickFillMenu({ onFill }: { onFill: (kind: QuickFillKind) => void }) {
  const { t } = useTranslation('builder')
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="text-muted-foreground">
          <Sparkles aria-hidden className="size-4" />
          {t('quickFill.title')}
          <ChevronDown aria-hidden className="size-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {QUICK_FILLS.map((kind) => {
          const Icon = QUICK_FILL_ICON[kind]
          return (
            <DropdownMenuItem key={kind} onSelect={() => onFill(kind)}>
              <Icon aria-hidden />
              {t(`quickFill.kind.${kind}`)}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
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
    <div className={cn('rounded-lg border transition-colors', open && 'bg-background', invalid && 'border-destructive/40')}>
      <div className="flex items-start gap-2 px-3 py-2">
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
    <div className="@container border-t px-3 pb-3">
      <div className="divide-y">
        <Step title={t('condition.observe')}>
          <OperandEditor context={operandContext} path={['left']} expression={comparison.left} volumeUnit={volumeUnit} />
        </Step>
        <Step title={t('condition.judge')}>
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
        <Step title={t('condition.compare')}>
          <OperandEditor context={operandContext} path={['right']} expression={comparison.right} volumeUnit={volumeUnit} />
        </Step>
      </div>
      <FieldError id={`${comparison.id}-node-error`} issue={context.issue(`node:${comparison.id}`)} />
    </div>
  )
}

function Step({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="grid gap-2 py-3 @2xl:grid-cols-[6.5rem_minmax(0,1fr)] @2xl:gap-4">
      <legend className="sr-only">{title}</legend>
      <span aria-hidden className="text-xs font-medium text-muted-foreground @2xl:pt-2">
        {title}
      </span>
      <div className="min-w-0 space-y-2">{children}</div>
    </fieldset>
  )
}
