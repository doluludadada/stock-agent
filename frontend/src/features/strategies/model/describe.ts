import { readParam } from './catalog'
import { measuresVolume } from './edit'
import type { Comparison, Condition, IndicatorConfig, NumericExpression, Strategy } from './types'

/**
 * Builds the human-readable formula preview from the formula itself, so the sentence can never
 * drift from what is stored. Translation and number formatting are passed in.
 */
export interface FormulaText {
  t: (key: string, params?: Record<string, string | number>) => string
  number: (value: number) => string
}

/** The arithmetic operators as the preview and the operand editor write them. */
export const SYMBOLS = { add: '+', subtract: '−', multiply: '×', divide: '÷' } as const

export function describeIndicator(config: IndicatorConfig, text: FormulaText): string {
  const params: Record<string, string> = {}
  for (const key of ['period', 'fast', 'slow', 'signal', 'std', 'k_period', 'd_period']) {
    const value = readParam(config, key)
    if (Number.isFinite(value)) params[key] = text.number(value)
    else if (key in config) params[key] = '?'
  }
  return text.t(`formula:indicator.${config.kind}`, params)
}

function at(kind: 'marketAt' | 'indicatorAt', barsAgo: number, params: Record<string, string>, text: FormulaText): string {
  const day = barsAgo === 0 ? 'today' : barsAgo === 1 ? 'yesterday' : 'ago'
  return text.t(`formula:${kind}.${day}`, { ...params, count: Number.isFinite(barsAgo) ? barsAgo : '?' })
}

export function describeExpression(
  expression: NumericExpression,
  strategy: Pick<Strategy, 'indicators'>,
  text: FormulaText,
  options: { volumeUnit?: boolean } = {},
): string {
  switch (expression.type) {
    case 'constant': {
      const value = Number.isFinite(expression.value) ? text.number(expression.value) : '?'
      return options.volumeUnit ? `${value} ${text.t('formula:unit.shares')}` : value
    }
    case 'market':
      return at('marketAt', expression.barsAgo, { field: text.t(`formula:field.${expression.field}`) }, text)
    case 'latest_price':
      return text.t('formula:latestPrice')
    case 'indicator': {
      const config = strategy.indicators[expression.indicatorId]
      if (!config) return text.t('formula:missingIndicator')
      if (config.kind === 'volume_sma' && expression.barsAgo === 1) {
        return text.t('formula:averageExcludingToday', { period: text.number(config.period) })
      }
      const output = expression.output === 'value' ? '' : ` ${text.t(`formula:output.${expression.output}`)}`
      const name = `${describeIndicator(config, text)}${output}`
      return expression.barsAgo === 0 ? name : at('indicatorAt', expression.barsAgo, { name }, text)
    }
    case 'arithmetic': {
      const wrap = (side: NumericExpression) => {
        const inner = describeExpression(side, strategy, text, options)
        return side.type === 'arithmetic' ? `(${inner})` : inner
      }
      const rightOptions = expression.operator === 'add' || expression.operator === 'subtract' ? options : {}
      const right =
        expression.right.type === 'arithmetic'
          ? `(${describeExpression(expression.right, strategy, text, rightOptions)})`
          : describeExpression(expression.right, strategy, text, rightOptions)
      return `${wrap(expression.left)} ${SYMBOLS[expression.operator]} ${right}`
    }
  }
}

export function describeComparison(comparison: Comparison, strategy: Pick<Strategy, 'indicators'>, text: FormulaText): string {
  const volumeUnit = measuresVolume(comparison.left, strategy.indicators) || measuresVolume(comparison.right, strategy.indicators)
  const left = describeExpression(comparison.left, strategy, text, { volumeUnit })
  const right = describeExpression(comparison.right, strategy, text, { volumeUnit })
  return `${left} ${text.t(`formula:comparator.${comparison.operator}`)} ${right}`
}

export function describeCondition(condition: Condition, strategy: Pick<Strategy, 'indicators'>, text: FormulaText, nested = false): string {
  if (condition.type === 'comparison') return describeComparison(condition, strategy, text)
  if (condition.conditions.length === 0) return text.t('formula:emptyGroup')
  const joiner = ` ${text.t(`formula:join.${condition.operator}`)} `
  const body = condition.conditions.map((child) => describeCondition(child, strategy, text, true)).join(joiner)
  return nested && condition.conditions.length > 1 ? `(${body})` : body
}
