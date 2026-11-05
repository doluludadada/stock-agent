import type { Schemas } from '@/shared/api'
import { DEFAULT_SCORING } from '../model/edit'
import type {
  Condition,
  ConditionGroup,
  IdFactory,
  IndicatorConfig,
  IndicatorId,
  NodeId,
  NumericExpression,
  Rule,
  Strategy,
  StrategyId,
  StrategySettings,
} from '../model/types'

/**
 * The one boundary between the API's formula JSON and the editor model. Reading gives every rule and condition a
 * position-derived id and turns numbers into constant nodes; writing drops the ids and writes every default
 * (`output`, `bars_ago`) explicitly. `mapping.test.ts` sends the three built-in strategies of config/strategies through
 * both directions and requires the backend's exact JSON back.
 */

export type ApiStrategy = Schemas['TechnicalStrategy-Output']
export type ApiStrategyInput = Schemas['TechnicalStrategy-Input']
export type ApiSettings = Schemas['TechnicalSettings-Output']
export type ApiSettingsInput = Schemas['TechnicalSettings-Input']
type ApiExpression = Schemas['NumericExpression-Output']
type ApiExpressionInput = Schemas['NumericExpression-Input']
type ApiCondition = Schemas['Comparison-Output'] | Schemas['ConditionGroup-Output']
type ApiConditionInput = Schemas['Comparison-Input'] | Schemas['ConditionGroup-Input']
type ApiIndicator = Schemas['IndicatorParameters-Output']
type ApiIndicatorInput = Schemas['IndicatorParameters-Input']

/** Fails to compile when the editor's indicator shapes and the API's stop describing the same JSON. */
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : never) : never
export const indicatorShapesMatch: Same<IndicatorConfig, ApiIndicator> & Same<IndicatorConfig, ApiIndicatorInput> = true

function expressionFromApi(expression: ApiExpression): NumericExpression {
  if (typeof expression === 'number') return { type: 'constant', value: expression }
  switch (expression.type) {
    case 'market':
      return { type: 'market', field: expression.field, barsAgo: expression.bars_ago ?? 0 }
    case 'latest_price':
      return { type: 'latest_price' }
    case 'indicator':
      return {
        type: 'indicator',
        indicatorId: expression.indicator_id as IndicatorId,
        output: expression.output ?? 'value',
        barsAgo: expression.bars_ago ?? 0,
      }
    case 'arithmetic':
      return {
        type: 'arithmetic',
        operator: expression.operator,
        left: expressionFromApi(expression.left),
        right: expressionFromApi(expression.right),
      }
  }
}

function conditionFromApi(condition: ApiCondition, id: string): Condition {
  if (condition.type === 'comparison') {
    return {
      type: 'comparison',
      id: id as NodeId,
      operator: condition.operator,
      left: expressionFromApi(condition.left),
      right: expressionFromApi(condition.right),
    }
  }
  return {
    type: 'group',
    id: id as NodeId,
    operator: condition.operator,
    conditions: condition.conditions.map((child, index) => conditionFromApi(child, `${id}_${index}`)),
  }
}

/** A rule whose condition is a single comparison is read as a group of one, the editor's only rule shape. */
function rootGroup(condition: Condition, id: string): ConditionGroup {
  if (condition.type === 'group') return condition
  return { type: 'group', id: `${id}_root` as NodeId, operator: 'all', conditions: [condition], bare: true }
}

export function strategyFromApi(strategy: ApiStrategy): Strategy {
  const rules: Rule[] = strategy.rules.map((rule, index) => {
    const id = `rule_${index}`
    return { id: id as NodeId, name: rule.name, effect: rule.effect, condition: rootGroup(conditionFromApi(rule.condition, `${id}_c`), id) }
  })
  return {
    id: strategy.strategy_id as StrategyId,
    name: strategy.name,
    indicators: structuredClone(strategy.indicators) as Record<IndicatorId, IndicatorConfig>,
    rules,
    scoring: {
      baseScore: strategy.scoring.base_score ?? DEFAULT_SCORING.baseScore,
      blockFailurePenalty: strategy.scoring.block_failure_penalty ?? DEFAULT_SCORING.blockFailurePenalty,
      failureScoreReduction: strategy.scoring.failure_score_reduction ?? DEFAULT_SCORING.failureScoreReduction,
      passScoreIncrease: strategy.scoring.pass_score_increase ?? DEFAULT_SCORING.passScoreIncrease,
    },
  }
}

function expressionToApi(expression: NumericExpression): ApiExpressionInput {
  switch (expression.type) {
    case 'constant':
      return expression.value
    case 'market':
      return { type: 'market', field: expression.field, bars_ago: expression.barsAgo }
    case 'latest_price':
      return { type: 'latest_price' }
    case 'indicator':
      return { type: 'indicator', indicator_id: expression.indicatorId, output: expression.output, bars_ago: expression.barsAgo }
    case 'arithmetic':
      return { type: 'arithmetic', operator: expression.operator, left: expressionToApi(expression.left), right: expressionToApi(expression.right) }
  }
}

function conditionToApi(condition: Condition): ApiConditionInput {
  const [only, ...others] = condition.type === 'group' ? condition.conditions : []
  if (condition.type === 'group' && condition.bare && only?.type === 'comparison' && others.length === 0) return conditionToApi(only)
  if (condition.type === 'comparison') {
    return { type: 'comparison', operator: condition.operator, left: expressionToApi(condition.left), right: expressionToApi(condition.right) }
  }
  return { type: 'group', operator: condition.operator, conditions: condition.conditions.map(conditionToApi) }
}

export function strategyToApi(strategy: Strategy): ApiStrategyInput {
  return {
    strategy_id: strategy.id,
    name: strategy.name.trim(),
    indicators: structuredClone(strategy.indicators),
    scoring: {
      base_score: strategy.scoring.baseScore,
      block_failure_penalty: strategy.scoring.blockFailurePenalty,
      failure_score_reduction: strategy.scoring.failureScoreReduction,
      pass_score_increase: strategy.scoring.passScoreIncrease,
    },
    rules: strategy.rules.map((rule) => ({ name: rule.name.trim(), effect: rule.effect, condition: conditionToApi(rule.condition) })),
  }
}

export function settingsFromApi(settings: ApiSettings): StrategySettings {
  return {
    activeStrategyId: settings.active_strategy_id as StrategyId,
    buzzStrategyId: settings.buzz_strategy_id as StrategyId,
    strategies: settings.strategies.map(strategyFromApi),
    revision: settings.revision ?? 0,
  }
}

export function settingsToApi(settings: StrategySettings): ApiSettingsInput {
  return {
    active_strategy_id: settings.activeStrategyId,
    buzz_strategy_id: settings.buzzStrategyId,
    strategies: settings.strategies.map(strategyToApi),
    revision: settings.revision,
  }
}

/** Where a 422 points inside PUT /v1/technical-settings, read back into the edited strategy's rule. */
export function ruleIndexOf(location: readonly (string | number)[], strategyIndex: number): number | null {
  const at = location.indexOf('strategies')
  if (at < 0 || location[at + 1] !== strategyIndex || location[at + 2] !== 'rules') return null
  const index = location[at + 3]
  return typeof index === 'number' ? index : null
}

export function newIds(): IdFactory {
  return (prefix) => `${prefix}_${crypto.randomUUID().replaceAll('-', '').slice(0, 10)}`
}
