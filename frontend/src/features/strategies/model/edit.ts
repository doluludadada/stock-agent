import { INDICATOR_CATALOG, withParam } from './catalog'
import type {
  Comparator,
  Comparison,
  Condition,
  ConditionGroup,
  ExpressionPath,
  GroupOperator,
  IdFactory,
  IndicatorConfig,
  IndicatorId,
  IndicatorKind,
  NodeId,
  NumericExpression,
  Rule,
  RuleEffect,
  Scoring,
  Strategy,
  StrategyId,
} from './types'

export const DEFAULT_SCORING: Scoring = {
  baseScore: 50,
  blockFailurePenalty: 15,
  failureScoreReduction: 5,
  passScoreIncrease: 5,
}

export type IndicatorTable = Record<IndicatorId, IndicatorConfig>

/** Every edit the designer can make. Ids are created by the caller so the reducer stays pure. */
export type StrategyEdit =
  | { type: 'setName'; name: string }
  | { type: 'setScoring'; key: keyof Scoring; value: number }
  | { type: 'addRule'; rule: Rule; indicators: IndicatorTable }
  | { type: 'removeRule'; ruleId: NodeId }
  | { type: 'setRuleName'; ruleId: NodeId; name: string }
  | { type: 'setRuleEffect'; ruleId: NodeId; effect: RuleEffect }
  | { type: 'setGroupOperator'; groupId: NodeId; operator: GroupOperator }
  | { type: 'addCondition'; groupId: NodeId; condition: Condition; indicators: IndicatorTable }
  | { type: 'removeCondition'; conditionId: NodeId }
  | { type: 'setComparator'; conditionId: NodeId; operator: Comparator }
  | {
      type: 'setExpression'
      conditionId: NodeId
      path: ExpressionPath
      expression: NumericExpression
      indicators: IndicatorTable
    }
  | { type: 'setIndicatorParam'; indicatorId: IndicatorId; key: string; value: number }
  | { type: 'detachIndicator'; conditionId: NodeId; path: ExpressionPath; newIndicatorId: IndicatorId }

export function applyEdit(strategy: Strategy, edit: StrategyEdit): Strategy {
  switch (edit.type) {
    case 'setName':
      return { ...strategy, name: edit.name }
    case 'setScoring':
      return { ...strategy, scoring: { ...strategy.scoring, [edit.key]: edit.value } }
    case 'addRule':
      return {
        ...strategy,
        indicators: { ...strategy.indicators, ...edit.indicators },
        rules: [...strategy.rules, edit.rule],
      }
    case 'removeRule':
      return { ...strategy, rules: strategy.rules.filter((rule) => rule.id !== edit.ruleId) }
    case 'setRuleName':
      return mapRules(strategy, edit.ruleId, (rule) => ({ ...rule, name: edit.name }))
    case 'setRuleEffect':
      return mapRules(strategy, edit.ruleId, (rule) => ({ ...rule, effect: edit.effect }))
    case 'setGroupOperator':
      return mapConditions(strategy, edit.groupId, (node) =>
        node.type === 'group' ? { ...node, operator: edit.operator } : node,
      )
    case 'addCondition':
      return {
        ...mapConditions(strategy, edit.groupId, (node) =>
          node.type === 'group' ? { ...node, conditions: [...node.conditions, edit.condition] } : node,
        ),
        indicators: { ...strategy.indicators, ...edit.indicators },
      }
    case 'removeCondition':
      return {
        ...strategy,
        rules: strategy.rules.map((rule) => ({ ...rule, condition: removeFromGroup(rule.condition, edit.conditionId) })),
      }
    case 'setComparator':
      return mapConditions(strategy, edit.conditionId, (node) =>
        node.type === 'comparison' ? { ...node, operator: edit.operator } : node,
      )
    case 'setExpression':
      return {
        ...mapConditions(strategy, edit.conditionId, (node) =>
          node.type === 'comparison' ? replaceInComparison(node, edit.path, edit.expression) : node,
        ),
        indicators: { ...strategy.indicators, ...edit.indicators },
      }
    case 'setIndicatorParam': {
      const config = strategy.indicators[edit.indicatorId]
      if (!config) return strategy
      return {
        ...strategy,
        indicators: { ...strategy.indicators, [edit.indicatorId]: withParam(config, edit.key, edit.value) },
      }
    }
    case 'detachIndicator':
      return detachIndicator(strategy, edit.conditionId, edit.path, edit.newIndicatorId)
  }
}

function mapRules(strategy: Strategy, ruleId: NodeId, update: (rule: Rule) => Rule): Strategy {
  return { ...strategy, rules: strategy.rules.map((rule) => (rule.id === ruleId ? update(rule) : rule)) }
}

function mapConditions(strategy: Strategy, id: NodeId, update: (node: Condition) => Condition): Strategy {
  const visit = (node: Condition): Condition => {
    if (node.id === id) return update(node)
    if (node.type === 'group') return { ...node, conditions: node.conditions.map(visit) }
    return node
  }
  return {
    ...strategy,
    rules: strategy.rules.map((rule) => ({ ...rule, condition: visit(rule.condition) as ConditionGroup })),
  }
}

function removeFromGroup(group: ConditionGroup, id: NodeId): ConditionGroup {
  return {
    ...group,
    conditions: group.conditions
      .filter((node) => node.id !== id)
      .map((node) => (node.type === 'group' ? removeFromGroup(node, id) : node)),
  }
}

export function expressionAt(comparison: Comparison, path: ExpressionPath): NumericExpression | null {
  const [side, ...rest] = path
  if (!side) return null
  let current: NumericExpression = comparison[side]
  for (const branch of rest) {
    if (current.type !== 'arithmetic') return null
    current = current[branch]
  }
  return current
}

function replaceInComparison(comparison: Comparison, path: ExpressionPath, next: NumericExpression): Comparison {
  const [side, ...rest] = path
  if (!side) return comparison
  return { ...comparison, [side]: replaceInExpression(comparison[side], rest, next) }
}

function replaceInExpression(
  expression: NumericExpression,
  path: ExpressionPath,
  next: NumericExpression,
): NumericExpression {
  const [branch, ...rest] = path
  if (!branch) return next
  if (expression.type !== 'arithmetic') return expression
  return { ...expression, [branch]: replaceInExpression(expression[branch], rest, next) }
}

/** Points one operand at a copy of its indicator setting, leaving other references untouched. */
function detachIndicator(
  strategy: Strategy,
  conditionId: NodeId,
  path: ExpressionPath,
  newIndicatorId: IndicatorId,
): Strategy {
  const comparison = findComparison(strategy, conditionId)
  const operand = comparison ? expressionAt(comparison, path) : null
  if (!comparison || operand?.type !== 'indicator') return strategy
  const config = strategy.indicators[operand.indicatorId]
  if (!config) return strategy
  const moved = mapConditions(strategy, conditionId, (node) =>
    node.type === 'comparison' ? replaceInComparison(node, path, { ...operand, indicatorId: newIndicatorId }) : node,
  )
  return { ...moved, indicators: { ...strategy.indicators, [newIndicatorId]: { ...config } } }
}

export function* comparisonsOf(condition: Condition): Generator<Comparison> {
  if (condition.type === 'comparison') {
    yield condition
    return
  }
  for (const child of condition.conditions) yield* comparisonsOf(child)
}

export function* allComparisons(strategy: Strategy): Generator<Comparison> {
  for (const rule of strategy.rules) yield* comparisonsOf(rule.condition)
}

export function findComparison(strategy: Strategy, id: NodeId): Comparison | null {
  for (const comparison of allComparisons(strategy)) if (comparison.id === id) return comparison
  return null
}

export function* expressionsOf(expression: NumericExpression): Generator<NumericExpression> {
  yield expression
  if (expression.type === 'arithmetic') {
    yield* expressionsOf(expression.left)
    yield* expressionsOf(expression.right)
  }
}

/** Every expression node on both sides of the comparison. */
export function nodesOf(comparison: Comparison): NumericExpression[] {
  return [...expressionsOf(comparison.left), ...expressionsOf(comparison.right)]
}

/** The indicator settings a comparison reads. */
export function indicatorIdsOf(comparison: Comparison): Set<IndicatorId> {
  return new Set(nodesOf(comparison).flatMap((node) => (node.type === 'indicator' ? [node.indicatorId] : [])))
}

/** Counts shares: volume, its moving average, or a sum or product of those; a ratio of two volumes has no unit. */
export function measuresVolume(expression: NumericExpression, indicators: Strategy['indicators']): boolean {
  if (expression.type === 'market') return expression.field === 'volume'
  if (expression.type === 'indicator') return indicators[expression.indicatorId]?.kind === 'volume_sma'
  if (expression.type === 'arithmetic') {
    return expression.operator !== 'divide' && (measuresVolume(expression.left, indicators) || measuresVolume(expression.right, indicators))
  }
  return false
}

/** How many conditions read this indicator setting; editing its parameters affects all of them. */
export function indicatorUsage(strategy: Strategy, id: IndicatorId): number {
  let count = 0
  for (const comparison of allComparisons(strategy)) if (indicatorIdsOf(comparison).has(id)) count += 1
  return count
}

/**
 * Drops the indicator settings the editor created and no condition reads any more (switching an operand's kind
 * leaves one behind). Settings the strategy came with stay, read or not: the editor never deletes server data
 * the user did not touch.
 */
export function pruneEditorIndicators(strategy: Strategy, kept: ReadonlySet<string>): Strategy {
  const used = new Set<string>([...allComparisons(strategy)].flatMap((comparison) => [...indicatorIdsOf(comparison)]))
  const indicators = Object.fromEntries(
    Object.entries(strategy.indicators).filter(([id]) => used.has(id) || kept.has(id)),
  ) as IndicatorTable
  return { ...strategy, indicators }
}

export function indicatorsOfKind(strategy: Strategy, kind: IndicatorKind): IndicatorId[] {
  return (Object.entries(strategy.indicators) as [IndicatorId, IndicatorConfig][])
    .filter(([, config]) => config.kind === kind)
    .map(([id]) => id)
}

export function newIndicatorId(ids: IdFactory): IndicatorId {
  return ids('ind') as IndicatorId
}

export function newNodeId(ids: IdFactory): NodeId {
  return ids('node') as NodeId
}

export function defaultIndicator(kind: IndicatorKind): IndicatorConfig {
  return { ...INDICATOR_CATALOG[kind].defaults }
}

/** A starting comparison: today's close above a new 20-day SMA. */
export function blankComparison(ids: IdFactory): { condition: Comparison; indicators: IndicatorTable } {
  const indicatorId = newIndicatorId(ids)
  return {
    condition: {
      type: 'comparison',
      id: newNodeId(ids),
      operator: 'gt',
      left: { type: 'market', field: 'close', barsAgo: 0 },
      right: { type: 'indicator', indicatorId, output: 'value', barsAgo: 0 },
    },
    indicators: { [indicatorId]: defaultIndicator('sma') } as IndicatorTable,
  }
}

export function blankGroup(ids: IdFactory, operator: GroupOperator): { condition: ConditionGroup; indicators: IndicatorTable } {
  const first = blankComparison(ids)
  return {
    condition: { type: 'group', id: newNodeId(ids), operator, conditions: [first.condition] },
    indicators: first.indicators,
  }
}

export function blankRule(ids: IdFactory): { rule: Rule; indicators: IndicatorTable } {
  const group = blankGroup(ids, 'all')
  return {
    rule: { id: newNodeId(ids), name: '', effect: 'block_on_fail', condition: group.condition },
    indicators: group.indicators,
  }
}

export function createBlankStrategy(ids: IdFactory): Strategy {
  const first = blankRule(ids)
  return {
    id: ids('stg') as StrategyId,
    name: '',
    indicators: first.indicators,
    rules: [first.rule],
    scoring: { ...DEFAULT_SCORING },
  }
}

/** An independent copy with its own id; later edits never reach the source. */
export function copyStrategy(source: Strategy, options: { ids: IdFactory; name: string }): Strategy {
  return { ...structuredClone(source), id: options.ids('stg') as StrategyId, name: options.name }
}
