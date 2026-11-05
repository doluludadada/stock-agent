import {
  LIMITS,
  indicatorSpec,
  indicatorWarmup,
  isCrossing,
  marketFieldUnit,
  outputUnit,
  readParam,
  type ParamSpec,
  type ValueUnit,
} from './catalog'
import { allComparisons, nodesOf } from './edit'
import type { Comparison, Condition, ExpressionPath, NumericExpression, Strategy } from './types'

/**
 * Field addresses used to show an issue beside its input:
 *   name | scoring:<key> | indicator:<id>:<param> | rules
 *   node:<conditionId> | expr:<conditionId>:<path>[:barsAgo|:value]
 *
 * An `error` is something the backend refuses, so the editor does not send it. A `warning` is advice the backend
 * does not enforce, such as comparing a price with a volume; it never blocks a save.
 */
export type FieldPath = string

export type IssueCode =
  | 'required'
  | 'notNumber'
  | 'notInteger'
  | 'outOfRange'
  | 'macdFastSlow'
  | 'emptyGroup'
  | 'noRules'
  | 'tooManyRules'
  | 'tooManyConditions'
  | 'missingIndicator'
  | 'invalidOutput'
  | 'divideByZero'
  | 'needsData'
  | 'crossingLatestPrice'
  | 'unitMismatch'
  | 'unsupportedArithmetic'

export type IssueSeverity = 'error' | 'warning'

/** What an issue belongs to: a rule's name, a condition (a comparison or a group) or an indicator setting. */
export interface IssueOwner {
  ruleId?: string
  conditionId?: string
  indicatorId?: string
}

export interface ValidationIssue extends IssueOwner {
  path: FieldPath
  code: IssueCode
  severity: IssueSeverity
  params?: Record<string, number | string>
}

const WARNINGS: ReadonlySet<IssueCode> = new Set(['unitMismatch', 'unsupportedArithmetic'])

function issue(path: FieldPath, code: IssueCode, params?: ValidationIssue['params'], owner: IssueOwner = {}): ValidationIssue {
  return { path, code, severity: WARNINGS.has(code) ? 'warning' : 'error', params, ...owner }
}

export function exprPath(conditionId: string, path: ExpressionPath, field?: 'barsAgo' | 'value'): FieldPath {
  return `expr:${conditionId}:${path.join('.')}${field ? `:${field}` : ''}`
}

export function isBlocking(issue: ValidationIssue | undefined): boolean {
  return issue?.severity === 'error'
}

export function errorsOf(issues: readonly ValidationIssue[]): ValidationIssue[] {
  return issues.filter((item) => item.severity === 'error')
}

export function validateStrategy(strategy: Strategy): ValidationIssue[] {
  const issues: ValidationIssue[] = []
  if (!strategy.name.trim()) issues.push(issue('name', 'required'))
  const scoreLimit = { min: 0, max: LIMITS.maxBaseScore, integer: true }
  checkNumber(issues, 'scoring:baseScore', strategy.scoring.baseScore, scoreLimit)
  for (const key of ['blockFailurePenalty', 'failureScoreReduction', 'passScoreIncrease'] as const) {
    checkNumber(issues, `scoring:${key}`, strategy.scoring[key], { min: 0, max: Number.MAX_SAFE_INTEGER, integer: true })
  }
  for (const [id, config] of Object.entries(strategy.indicators)) {
    const owner = { indicatorId: id }
    for (const param of indicatorSpec(config.kind).params) checkParam(issues, `indicator:${id}:${param.key}`, readParam(config, param.key), param, owner)
    if (config.kind === 'macd' && config.fast >= config.slow) issues.push(issue(`indicator:${id}:fast`, 'macdFastSlow', undefined, owner))
  }
  if (strategy.rules.length === 0) issues.push(issue('rules', 'noRules'))
  if (strategy.rules.length > LIMITS.maxRules) issues.push(issue('rules', 'tooManyRules', { max: LIMITS.maxRules }))
  for (const rule of strategy.rules) {
    if (!rule.name.trim()) issues.push(issue(`rule:${rule.id}`, 'required', undefined, { ruleId: rule.id }))
    checkCondition(issues, strategy, rule.condition)
  }
  return issues
}

function checkCondition(issues: ValidationIssue[], strategy: Strategy, condition: Condition) {
  if (condition.type === 'group') {
    const owner = { conditionId: condition.id }
    if (condition.conditions.length === 0) issues.push(issue(`node:${condition.id}`, 'emptyGroup', undefined, owner))
    if (condition.conditions.length > LIMITS.maxConditionsPerGroup) {
      issues.push(issue(`node:${condition.id}`, 'tooManyConditions', { max: LIMITS.maxConditionsPerGroup }, owner))
    }
    for (const child of condition.conditions) checkCondition(issues, strategy, child)
    return
  }
  checkComparison(issues, strategy, condition)
}

function checkComparison(issues: ValidationIssue[], strategy: Strategy, comparison: Comparison) {
  const left = checkExpression(issues, strategy, comparison.id, comparison.left, ['left'])
  const right = checkExpression(issues, strategy, comparison.id, comparison.right, ['right'])
  const nodes = nodesOf(comparison)
  const owner = { conditionId: comparison.id }
  if (!nodes.some((node) => node.type === 'market' || node.type === 'indicator' || node.type === 'latest_price')) {
    issues.push(issue(`node:${comparison.id}`, 'needsData', undefined, owner))
    return
  }
  if (isCrossing(comparison.operator) && nodes.some((node) => node.type === 'latest_price')) {
    issues.push(issue(`node:${comparison.id}`, 'crossingLatestPrice', undefined, owner))
  }
  if (left === 'invalid' || right === 'invalid') return
  if (left !== 'constant' && right !== 'constant' && left !== right) issues.push(issue(`node:${comparison.id}`, 'unitMismatch', undefined, owner))
}

/** `constant` adapts to whatever it meets; `invalid` means an issue was already reported below. */
type InferredUnit = ValueUnit | 'constant' | 'invalid'

function checkExpression(
  issues: ValidationIssue[],
  strategy: Strategy,
  conditionId: string,
  expression: NumericExpression,
  path: ExpressionPath,
): InferredUnit {
  switch (expression.type) {
    case 'constant':
      if (Number.isFinite(expression.value)) return 'constant'
      issues.push(issue(exprPath(conditionId, path, 'value'), 'notNumber', undefined, { conditionId }))
      return 'invalid'
    case 'latest_price':
      return 'price'
    case 'market':
      return checkBarsAgo(issues, conditionId, path, expression.barsAgo) ? marketFieldUnit(expression.field) : 'invalid'
    case 'indicator': {
      const config = strategy.indicators[expression.indicatorId]
      if (!config) {
        issues.push(issue(exprPath(conditionId, path), 'missingIndicator', undefined, { conditionId }))
        return 'invalid'
      }
      if (!indicatorSpec(config.kind).outputs.includes(expression.output)) {
        issues.push(issue(exprPath(conditionId, path), 'invalidOutput', undefined, { conditionId }))
        return 'invalid'
      }
      return checkBarsAgo(issues, conditionId, path, expression.barsAgo) ? outputUnit(config.kind, expression.output) : 'invalid'
    }
    case 'arithmetic': {
      const left = checkExpression(issues, strategy, conditionId, expression.left, [...path, 'left'])
      const right = checkExpression(issues, strategy, conditionId, expression.right, [...path, 'right'])
      if (left === 'invalid' || right === 'invalid') return 'invalid'
      if (expression.operator === 'divide' && expression.right.type === 'constant' && expression.right.value === 0) {
        issues.push(issue(exprPath(conditionId, [...path, 'right'], 'value'), 'divideByZero', undefined, { conditionId }))
        return 'invalid'
      }
      const unit = combineUnits(expression.operator, left, right)
      if (unit === 'invalid') issues.push(issue(exprPath(conditionId, path), 'unsupportedArithmetic', undefined, { conditionId }))
      return unit
    }
  }
}

function combineUnits(operator: 'add' | 'subtract' | 'multiply' | 'divide', left: InferredUnit, right: InferredUnit): InferredUnit {
  if (left === 'constant' && right === 'constant') return 'constant'
  if (operator === 'add' || operator === 'subtract') {
    if (left === 'constant') return right
    if (right === 'constant' || left === right) return left
    return 'invalid'
  }
  if (operator === 'multiply') {
    if (left === 'constant' || left === 'scalar') return right
    if (right === 'constant' || right === 'scalar') return left
    return 'invalid'
  }
  if (right === 'constant' || right === 'scalar') return left
  if (left === right) return 'scalar'
  return 'invalid'
}

function checkBarsAgo(issues: ValidationIssue[], conditionId: string, path: ExpressionPath, value: number): boolean {
  return checkNumber(issues, exprPath(conditionId, path, 'barsAgo'), value, { min: 0, max: LIMITS.maxBarsAgo, integer: true }, { conditionId })
}

function checkParam(issues: ValidationIssue[], path: FieldPath, value: number, param: ParamSpec, owner: IssueOwner) {
  if (!checkNumber(issues, path, value, param, owner)) return
  if (param.exclusiveMin && value <= param.min) issues.push(issue(path, 'outOfRange', { min: param.min, max: param.max }, owner))
}

function checkNumber(
  issues: ValidationIssue[],
  path: FieldPath,
  value: number,
  rule: { min: number; max: number; integer: boolean },
  owner: IssueOwner = {},
): boolean {
  if (!Number.isFinite(value)) {
    issues.push(issue(path, 'notNumber', undefined, owner))
    return false
  }
  if (rule.integer && !Number.isInteger(value)) {
    issues.push(issue(path, 'notInteger', undefined, owner))
    return false
  }
  if (value < rule.min || value > rule.max) {
    issues.push(issue(path, 'outOfRange', { min: rule.min, max: rule.max }, owner))
    return false
  }
  return true
}

/** The backend's `required_bars`: each reference's own history plus how far back it is read, plus one for a crossing. */
export function requiredBars(strategy: Strategy): number {
  let required = 1
  for (const comparison of allComparisons(strategy)) required = Math.max(required, comparisonBars(strategy, comparison))
  return required
}

function comparisonBars(strategy: Strategy, comparison: Comparison): number {
  const crossing = isCrossing(comparison.operator) ? 1 : 0
  let bars = 1
  for (const node of nodesOf(comparison)) {
    if (node.type === 'market') bars = Math.max(bars, node.barsAgo + 1 + crossing)
    if (node.type === 'indicator') {
      const config = strategy.indicators[node.indicatorId]
      if (config) bars = Math.max(bars, indicatorWarmup(config) + node.barsAgo + crossing)
    }
  }
  return bars
}

export function issuesByPath(issues: ValidationIssue[]): Map<FieldPath, ValidationIssue> {
  const map = new Map<FieldPath, ValidationIssue>()
  for (const item of issues) {
    const existing = map.get(item.path)
    if (!existing || (existing.severity === 'warning' && item.severity === 'error')) map.set(item.path, item)
  }
  return map
}

/** The issue to show for one owner: its error when it has one, else its warning. */
export function issuesByOwner(issues: ValidationIssue[]): (owner: IssueOwner) => ValidationIssue | undefined {
  const owned = (owner: IssueOwner) => (item: ValidationIssue) =>
    (owner.ruleId !== undefined && item.ruleId === owner.ruleId) ||
    (owner.conditionId !== undefined && item.conditionId === owner.conditionId) ||
    (owner.indicatorId !== undefined && item.indicatorId === owner.indicatorId)
  return (owner) => {
    const mine = issues.filter(owned(owner))
    return mine.find((item) => item.severity === 'error') ?? mine[0]
  }
}

/** True when the rule's name or any condition inside it has an error. */
export function ruleHasIssues(issueOf: (owner: IssueOwner) => ValidationIssue | undefined, rule: { id: string; condition: Condition }): boolean {
  return isBlocking(issueOf({ ruleId: rule.id })) || conditionIdsOf(rule.condition).some((conditionId) => isBlocking(issueOf({ conditionId })))
}

function conditionIdsOf(condition: Condition): string[] {
  return condition.type === 'group' ? [condition.id, ...condition.conditions.flatMap(conditionIdsOf)] : [condition.id]
}
