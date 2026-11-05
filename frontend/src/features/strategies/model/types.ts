import type { Schemas } from '@/shared/api'

/**
 * The editor's formula model. Its vocabulary (indicator kinds and parameters, outputs, operators, effects) is the
 * backend's, taken from the generated OpenAPI contract; `api/mapping.ts` is the one boundary that converts. The
 * editor adds what the API does not carry: an id on every rule and condition, and constants as tagged nodes.
 */

declare const brand: unique symbol
type Brand<T, Name extends string> = T & { readonly [brand]: Name }

export type StrategyId = Brand<string, 'StrategyId'>
/** Stable within one strategy. Never contains a period or a display name. */
export type IndicatorId = Brand<string, 'IndicatorId'>
/** Identifies a rule or a condition inside one edited strategy; never sent to the server. */
export type NodeId = Brand<string, 'NodeId'>

/** One member per kind, so `Extract<IndicatorConfig, { kind: K }>` narrows; the type test checks it against the API. */
export type IndicatorConfig =
  | { kind: 'sma'; period: number }
  | { kind: 'volume_sma'; period: number }
  | { kind: 'rsi'; period: number }
  | { kind: 'adx'; period: number }
  | { kind: 'atr'; period: number }
  | { kind: 'obv'; period: number }
  | { kind: 'mfi'; period: number }
  | { kind: 'macd'; fast: number; slow: number; signal: number }
  | { kind: 'bollinger'; period: number; std: number }
  | { kind: 'stochastic'; k_period: number; d_period: number }

export type IndicatorKind = Schemas['IndicatorParameters-Output']['kind']
export type IndicatorOutput = Schemas['IndicatorOutput']
export type MarketField = Schemas['MarketField']
export type ArithmeticOperator = Schemas['ArithmeticOperator']
export type Comparator = Schemas['ComparisonOperator']
export type GroupOperator = Schemas['GroupOperator']
/** What a rule does to a stock; applied once per rule, however many conditions it groups. */
export type RuleEffect = Schemas['RuleEffect']

/** `barsAgo` counts completed trading days: 0 is the latest bar, 1 the bar before it. */
export type NumericExpression =
  | { type: 'constant'; value: number }
  | { type: 'market'; field: MarketField; barsAgo: number }
  | { type: 'latest_price' }
  | { type: 'indicator'; indicatorId: IndicatorId; output: IndicatorOutput; barsAgo: number }
  | {
      type: 'arithmetic'
      operator: ArithmeticOperator
      left: NumericExpression
      right: NumericExpression
    }

export interface Comparison {
  type: 'comparison'
  id: NodeId
  operator: Comparator
  left: NumericExpression
  right: NumericExpression
}

export interface ConditionGroup {
  type: 'group'
  id: NodeId
  operator: GroupOperator
  conditions: Condition[]
  /** The API held a lone comparison here; while the group still holds exactly one, it is written back that way. */
  bare?: true
}

export type Condition = Comparison | ConditionGroup

export interface Rule {
  id: NodeId
  /** A label. The formula, not the name, decides behaviour. */
  name: string
  effect: RuleEffect
  condition: ConditionGroup
}

export interface Scoring {
  baseScore: number
  blockFailurePenalty: number
  failureScoreReduction: number
  passScoreIncrease: number
}

export interface Strategy {
  id: StrategyId
  name: string
  indicators: Record<IndicatorId, IndicatorConfig>
  rules: Rule[]
  scoring: Scoring
}

/** The owner's saved settings: their strategies, the one each workflow uses, and the revision a save must carry. */
export interface StrategySettings {
  activeStrategyId: StrategyId
  buzzStrategyId: StrategyId
  strategies: Strategy[]
  revision: number
}

/** Where an expression sits inside a comparison: a side, then arithmetic branches. */
export type ExpressionPath = readonly ('left' | 'right')[]

export type IdFactory = (prefix: 'stg' | 'ind' | 'node') => string
