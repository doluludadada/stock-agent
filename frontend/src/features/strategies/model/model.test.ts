import { describe, expect, it } from 'vitest'
import { describeComparison, describeCondition } from './describe'
import { applyEdit, copyStrategy, createBlankStrategy, findComparison, indicatorUsage, pruneEditorIndicators } from './edit'
import { quickFill } from './quick-fill'
import { withStrategy, withoutStrategy } from './settings'
import { builtIn, fakeText, sequentialIds } from './built-ins.test-support'
import type { IndicatorId, NodeId, Strategy, StrategyId, StrategySettings } from './types'
import { errorsOf, exprPath, requiredBars, validateStrategy } from './validate'

function copyOfBalanced(): Strategy {
  return copyStrategy(builtIn('balanced'), { ids: sequentialIds(), name: 'My balanced' })
}

function withQuickFill(strategy: Strategy, kind: Parameters<typeof quickFill>[0]) {
  const filled = quickFill(kind, sequentialIds())
  const groupId = strategy.rules[0]!.condition.id
  return { strategy: applyEdit(strategy, { type: 'addCondition', groupId, ...filled }), condition: filled.condition }
}

/** The comparison of rule `index` of a built-in strategy whose condition was a lone comparison. */
const bare = (index: number) => `rule_${index}_c` as NodeId

describe('built-in copies', () => {
  it('gets its own id and never changes the built-in it came from', () => {
    const balanced = builtIn('balanced')
    const copy = copyOfBalanced()
    const edited = applyEdit(copy, { type: 'setIndicatorParam', indicatorId: 'ind_a' as IndicatorId, key: 'period', value: 37 })

    expect(copy.id).not.toBe('balanced')
    expect(edited.indicators['ind_a' as IndicatorId]).toEqual({ kind: 'sma', period: 37 })
    expect(balanced.indicators['ind_a' as IndicatorId]).toEqual({ kind: 'sma', period: 20 })
  })
})

describe('indicator parameters', () => {
  it('one setting drives every condition that reads it', () => {
    const copy = copyOfBalanced()
    expect(indicatorUsage(copy, 'ind_a' as IndicatorId)).toBeGreaterThan(1)
  })

  it('the built-in strategies need 61 completed bars: SMA 60 crossing needs one more', () => {
    expect(requiredBars(builtIn('balanced'))).toBe(61)
    const longer = applyEdit(copyOfBalanced(), { type: 'setIndicatorParam', indicatorId: 'ind_b' as IndicatorId, key: 'period', value: 83 })
    expect(requiredBars(longer)).toBe(84)
  })
})

describe('names are labels', () => {
  it('renaming a strategy or a rule leaves the formula untouched', () => {
    const copy = copyOfBalanced()
    const renamed = applyEdit(applyEdit(copy, { type: 'setName', name: 'Golden Cross' }), {
      type: 'setRuleName',
      ruleId: copy.rules[0]!.id,
      name: 'Anything',
    })
    expect(renamed.rules[0]!.condition).toEqual(copy.rules[0]!.condition)
    expect(renamed.indicators).toEqual(copy.indicators)
  })
})

describe('MACD outputs', () => {
  it('reads the line and the signal from one setting', () => {
    const { strategy, condition } = withQuickFill(createBlankStrategy(sequentialIds()), 'macdCross')
    if (condition.left.type !== 'indicator' || condition.right.type !== 'indicator') throw new Error('expected indicators')
    expect(condition.left.indicatorId).toBe(condition.right.indicatorId)
    expect([condition.left.output, condition.right.output]).toEqual(['line', 'signal'])
    const updated = applyEdit(strategy, { type: 'setIndicatorParam', indicatorId: condition.left.indicatorId, key: 'slow', value: 30 })
    expect(updated.indicators[condition.left.indicatorId]).toMatchObject({ kind: 'macd', slow: 30 })
  })

  it('can split one reference into an independent setting', () => {
    const copy = copyOfBalanced()
    const golden = copy.rules.find((rule) => rule.name === 'Golden Cross')!
    const crossing = golden.condition.conditions[0]!
    const detached = applyEdit(copy, { type: 'detachIndicator', conditionId: crossing.id, path: ['left'], newIndicatorId: 'ind_new' as IndicatorId })
    const edited = applyEdit(detached, { type: 'setIndicatorParam', indicatorId: 'ind_new' as IndicatorId, key: 'period', value: 37 })
    expect(edited.indicators['ind_new' as IndicatorId]).toEqual({ kind: 'sma', period: 37 })
    expect(edited.indicators['ind_a' as IndicatorId]).toEqual({ kind: 'sma', period: 20 })
  })

  it('rejects a fast period that is not shorter than the slow one', () => {
    const { strategy, condition } = withQuickFill(createBlankStrategy(sequentialIds()), 'macdCross')
    if (condition.left.type !== 'indicator') throw new Error('expected indicator')
    const id = condition.left.indicatorId
    const broken = applyEdit({ ...strategy, name: 'x' }, { type: 'setIndicatorParam', indicatorId: id, key: 'fast', value: 26 })
    expect(validateStrategy(broken)).toContainEqual({ path: `indicator:${id}:fast`, code: 'macdFastSlow', severity: 'error', indicatorId: id })
  })
})

describe('formula checks the backend makes', () => {
  it('describes the built-in daily-range rule and its latest price', () => {
    const balanced = builtIn('balanced')
    const priceAbove = balanced.rules[0]!
    expect(describeCondition(priceAbove.condition, balanced, fakeText)).toContain('formula:latestPrice')
  })

  it('refuses the latest price in a crossing, a comparison of two numbers and a division by zero', () => {
    const base = copyOfBalanced()
    const target = bare(7)
    const crossingLatest = applyEdit(applyEdit(base, { type: 'setComparator', conditionId: target, operator: 'crosses_above' }), {
      type: 'setExpression',
      conditionId: target,
      path: ['left'],
      expression: { type: 'latest_price' },
      indicators: {},
    })
    expect(errorsOf(validateStrategy(crossingLatest))).toContainEqual({ path: `node:${target}`, code: 'crossingLatestPrice', severity: 'error', conditionId: target })

    const numbers = applyEdit(applyEdit(base, { type: 'setExpression', conditionId: target, path: ['left'], expression: { type: 'constant', value: 1 }, indicators: {} }), {
      type: 'setExpression',
      conditionId: target,
      path: ['right'],
      expression: { type: 'constant', value: 2 },
      indicators: {},
    })
    expect(errorsOf(validateStrategy(numbers))).toContainEqual({ path: `node:${target}`, code: 'needsData', severity: 'error', conditionId: target })

    const divided = applyEdit(base, {
      type: 'setExpression',
      conditionId: target,
      path: ['right'],
      expression: { type: 'arithmetic', operator: 'divide', left: { type: 'market', field: 'close', barsAgo: 1 }, right: { type: 'constant', value: 0 } },
      indicators: {},
    })
    expect(validateStrategy(divided)).toContainEqual({ path: exprPath(target, ['right', 'right'], 'value'), code: 'divideByZero', severity: 'error', conditionId: target })
  })

  it('warns about mixed units without blocking the save', () => {
    const target = bare(7)
    const mixed = applyEdit(copyOfBalanced(), {
      type: 'setExpression',
      conditionId: target,
      path: ['right'],
      expression: { type: 'market', field: 'volume', barsAgo: 0 },
      indicators: {},
    })
    expect(validateStrategy(mixed)).toContainEqual({ path: `node:${target}`, code: 'unitMismatch', severity: 'warning', conditionId: target })
    expect(errorsOf(validateStrategy(mixed))).toEqual([])
  })

  it('excludes today from the quick-fill volume average and labels shares', () => {
    const { strategy, condition } = withQuickFill(createBlankStrategy(sequentialIds()), 'volumeAboveAverage')
    expect(condition.right).toMatchObject({ type: 'arithmetic', left: { barsAgo: 1 }, right: { value: 1.5 } })
    const text = describeComparison(condition, strategy, fakeText)
    expect(text).toContain('formula:averageExcludingToday')
    expect(text).toContain('1.5')
  })
})

describe('invalid drafts', () => {
  it('a blank strategy needs a name and rule names before it can be saved', () => {
    const blank = createBlankStrategy(sequentialIds())
    const ruleId = blank.rules[0]!.id
    expect(errorsOf(validateStrategy(blank)).map((issue) => issue.path)).toEqual(['name', `rule:${ruleId}`])
    expect(errorsOf(validateStrategy({ ...blank, name: 'Trend', rules: [] })).map((issue) => issue.code)).toEqual(['noRules'])
  })

  it('flags bad day offsets on the exact operand', () => {
    const target = bare(7)
    const copy = applyEdit(copyOfBalanced(), {
      type: 'setExpression',
      conditionId: target,
      path: ['left'],
      expression: { type: 'market', field: 'close', barsAgo: -1 },
      indicators: {},
    })
    expect(validateStrategy(copy)).toContainEqual(expect.objectContaining({ path: exprPath(target, ['left'], 'barsAgo'), code: 'outOfRange' }))
  })

  it('finds a bare comparison by its id', () => {
    expect(findComparison(builtIn('balanced'), bare(7))).not.toBeNull()
  })
})

describe('saved settings', () => {
  const settings: StrategySettings = {
    activeStrategyId: 'balanced' as StrategyId,
    buzzStrategyId: 'aggressive' as StrategyId,
    strategies: [builtIn('balanced'), builtIn('aggressive')],
    revision: 4,
  }

  it('adds or replaces one strategy and keeps the revision the save must carry', () => {
    const copy = copyOfBalanced()
    const added = withStrategy(settings, copy)
    expect(added).toMatchObject({ revision: 4, strategies: [{ id: 'balanced' }, { id: 'aggressive' }, { id: copy.id }] })
  })

  it('never deletes a selected strategy', () => {
    expect(withoutStrategy(settings, 'balanced' as StrategyId)).toBe('selected')
    expect(withoutStrategy({ ...settings, buzzStrategyId: 'balanced' as StrategyId }, 'aggressive' as StrategyId)).toMatchObject({
      strategies: [{ id: 'balanced' }],
    })
  })

  it('prunes only the indicator settings the editor itself left unused', () => {
    const balanced = builtIn('balanced')
    const kept = new Set(Object.keys(balanced.indicators))
    const withOrphan = { ...balanced, indicators: { ...balanced.indicators, ind_orphan: { kind: 'rsi', period: 9 } } } as Strategy
    expect(Object.keys(pruneEditorIndicators(withOrphan, kept).indicators)).toEqual([...kept])
  })
})
