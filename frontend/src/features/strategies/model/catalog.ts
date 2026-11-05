import outputs from '@/shared/api/indicator-outputs.json'
import type { ArithmeticOperator, Comparator, IndicatorConfig, IndicatorKind, IndicatorOutput, MarketField, RuleEffect } from './types'

/**
 * What the designer may combine, as the backend validates it (the OpenAPI schema and `indicator-outputs.json`).
 * `catalog.test.ts` compares every kind, parameter bound and output with the backend's published contract, so this
 * file cannot drift from it. Units, defaults and steps are editor hints the backend does not need.
 */

/** Value families that may be compared or combined. `scalar` is a unitless ratio or constant. */
export type ValueUnit = 'price' | 'volume' | 'oscillator' | 'macd' | 'scalar'

export interface ParamSpec {
  key: string
  min: number
  /** True when `min` itself is refused (a Bollinger width must be above 0). */
  exclusiveMin: boolean
  max: number
  step: number
  integer: boolean
}

interface IndicatorSpec<K extends IndicatorKind> {
  params: readonly ParamSpec[]
  outputs: readonly IndicatorOutput[]
  defaults: Extract<IndicatorConfig, { kind: K }>
  /** The backend's `required_bars`: completed daily bars before the latest value exists. */
  warmupBars: (config: Extract<IndicatorConfig, { kind: K }>) => number
}

/** Each kind's outputs as the backend names them, exported from its IndicatorKind.outputs. */
const OUTPUTS = (outputs satisfies Record<IndicatorKind, string[]>) as Record<IndicatorKind, readonly IndicatorOutput[]>

const MAX_PERIOD = 500
const period = (key = 'period'): ParamSpec => ({ key, min: 1, exclusiveMin: false, max: MAX_PERIOD, step: 1, integer: true })

export const INDICATOR_CATALOG: { [K in IndicatorKind]: IndicatorSpec<K> } = {
  sma: { params: [period()], outputs: OUTPUTS.sma, defaults: { kind: 'sma', period: 20 }, warmupBars: (config) => config.period },
  volume_sma: {
    params: [period()],
    outputs: OUTPUTS.volume_sma,
    defaults: { kind: 'volume_sma', period: 20 },
    warmupBars: (config) => config.period,
  },
  rsi: { params: [period()], outputs: OUTPUTS.rsi, defaults: { kind: 'rsi', period: 14 }, warmupBars: (config) => config.period + 1 },
  macd: {
    params: [period('fast'), period('slow'), period('signal')],
    outputs: OUTPUTS.macd,
    defaults: { kind: 'macd', fast: 12, slow: 26, signal: 9 },
    warmupBars: (config) => config.slow + config.signal - 1,
  },
  bollinger: {
    params: [period(), { key: 'std', min: 0, exclusiveMin: true, max: 10, step: 0.1, integer: false }],
    outputs: OUTPUTS.bollinger,
    defaults: { kind: 'bollinger', period: 20, std: 2 },
    warmupBars: (config) => config.period,
  },
  stochastic: {
    params: [period('k_period'), period('d_period')],
    outputs: OUTPUTS.stochastic,
    defaults: { kind: 'stochastic', k_period: 9, d_period: 3 },
    warmupBars: (config) => config.k_period + config.d_period - 1,
  },
  adx: {
    params: [period()],
    outputs: OUTPUTS.adx,
    defaults: { kind: 'adx', period: 14 },
    warmupBars: (config) => config.period * 2,
  },
  atr: { params: [period()], outputs: OUTPUTS.atr, defaults: { kind: 'atr', period: 14 }, warmupBars: (config) => config.period + 1 },
  obv: {
    params: [period()],
    outputs: OUTPUTS.obv,
    defaults: { kind: 'obv', period: 20 },
    warmupBars: (config) => config.period,
  },
  mfi: { params: [period()], outputs: OUTPUTS.mfi, defaults: { kind: 'mfi', period: 14 }, warmupBars: (config) => config.period + 1 },
}

export const INDICATOR_KINDS = Object.keys(INDICATOR_CATALOG) as IndicatorKind[]

/** Kinds the picker groups under volume; every other kind reads prices. */
export const VOLUME_KINDS: readonly IndicatorKind[] = ['volume_sma', 'obv']

export function indicatorSpec(kind: IndicatorKind): IndicatorSpec<IndicatorKind> {
  return INDICATOR_CATALOG[kind] as unknown as IndicatorSpec<IndicatorKind>
}

export function indicatorWarmup(config: IndicatorConfig): number {
  return indicatorSpec(config.kind).warmupBars(config)
}

/** The unit of one output, for the editor's comparison hints. */
export function outputUnit(kind: IndicatorKind, output: IndicatorOutput): ValueUnit {
  if (VOLUME_KINDS.includes(kind)) return 'volume'
  if (kind === 'macd') return 'macd'
  if (kind === 'bollinger') return output === 'bandwidth' || output === 'percent_b' ? 'scalar' : 'price'
  if (kind === 'sma' || kind === 'atr') return 'price'
  return 'oscillator'
}

export function readParam(config: IndicatorConfig, key: string): number {
  const value = (config as unknown as Record<string, unknown>)[key]
  return typeof value === 'number' ? value : Number.NaN
}

export function withParam(config: IndicatorConfig, key: string, value: number): IndicatorConfig {
  if (!indicatorSpec(config.kind).params.some((param) => param.key === key)) return config
  return { ...config, [key]: value } as IndicatorConfig
}

export const MARKET_FIELDS: readonly MarketField[] = ['close', 'open', 'high', 'low', 'volume']

export function marketFieldUnit(field: MarketField): ValueUnit {
  return field === 'volume' ? 'volume' : 'price'
}

export const COMPARATORS: readonly Comparator[] = ['gt', 'gte', 'lt', 'lte', 'eq', 'ne', 'crosses_above', 'crosses_below']

export const ARITHMETIC_OPERATORS: readonly ArithmeticOperator[] = ['multiply', 'divide', 'add', 'subtract']

export const RULE_EFFECTS: readonly RuleEffect[] = ['block_on_fail', 'reduce_score_on_fail', 'increase_score_on_pass']

/** The backend's limits: `TechnicalSettings`, `TechnicalStrategy`, `ConditionGroup`, `BarsAgo` and `Score`. */
export const LIMITS = {
  maxBarsAgo: 250,
  maxStrategies: 50,
  maxRules: 100,
  maxConditionsPerGroup: 50,
  maxBaseScore: 100,
  /** The editor nests arithmetic at most this deep; deeper formulas from the server still display and save. */
  maxArithmeticDepthInEditor: 2,
} as const

export function isCrossing(operator: Comparator): boolean {
  return operator === 'crosses_above' || operator === 'crosses_below'
}
