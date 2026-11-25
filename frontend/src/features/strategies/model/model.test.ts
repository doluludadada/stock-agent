import { describe, expect, it } from 'vitest'
import { describeComparison, describeCondition } from './describe'
import { applyEdit, copyStrategy, createBlankStrategy, findComparison, indicatorUsage, pruneEditorIndicators } from './edit'
import { quickFill } from './quick-fill'
import { builtInInUse, customStrategies, withBuiltInActive, withStrategy, withoutStrategy } from './settings'
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
  /** The copy a first read saved while the app shipped an Aggressive built-in, which it no longer does. */
  const retired: Strategy = { ...builtIn('balanced'), id: 'aggressive' as StrategyId, name: 'Aggressive' }
  const settings: StrategySettings = {
    activeStrategyId: 'balanced' as StrategyId,
    strategies: [builtIn('balanced'), retired],
    revision: 4,
  }
  const builtIns = [builtIn('balanced')]
  const edited = (strategy: Strategy): Strategy => ({ ...strategy, scoring: { ...strategy.scoring, base_score: 60 } })

  it('adds or replaces one strategy and keeps the revision the save must carry', () => {
    const copy = copyOfBalanced()
    const added = withStrategy(settings, copy)
    expect(added).toMatchObject({ revision: 4, strategies: [{ id: 'balanced' }, { id: 'aggressive' }, { id: copy.id }] })
  })

  it('never deletes the strategy in use', () => {
    expect(withoutStrategy(settings, 'balanced' as StrategyId)).toBe('selected')
    expect(withoutStrategy(settings, 'aggressive' as StrategyId)).toMatchObject({ strategies: [{ id: 'balanced' }] })
  })

  it('counts a copy of a built-in as the built-in, and as the owner’s own once it changed', () => {
    const mine = copyOfBalanced()
    const own = (given: StrategySettings) => customStrategies(given, builtIns).map((item) => item.id)
    expect(own({ ...settings, strategies: [builtIn('balanced'), mine] })).toEqual([mine.id])
    expect(builtInInUse(settings, builtIns)?.id).toBe('balanced')

    const changed = { ...settings, strategies: [edited(builtIn('balanced'))] }
    expect(own(changed)).toEqual(['balanced'])
    expect(builtInInUse(changed, builtIns)).toBeNull()
  })

  it('counts a saved copy of a built-in that no longer ships as the owner’s own, in use or not', () => {
    expect(customStrategies(settings, builtIns).map((item) => item.id)).toEqual(['aggressive'])
    expect(builtInInUse({ ...settings, activeStrategyId: retired.id }, builtIns)).toBeNull()
  })

  it('puts a built-in in use as it ships, bringing back a deleted copy and keeping a changed one under a new id', () => {
    const withoutBalanced = { ...settings, activeStrategyId: retired.id, strategies: [retired] }
    expect(withBuiltInActive(withoutBalanced, builtIn('balanced'), 'stg_new' as StrategyId)).toMatchObject({
      activeStrategyId: 'balanced',
      strategies: [{ id: 'aggressive' }, { id: 'balanced' }],
      revision: 4,
    })

    const changed = { ...settings, activeStrategyId: retired.id, strategies: [edited(builtIn('balanced')), retired] }
    const next = withBuiltInActive(changed, builtIn('balanced'), 'stg_new' as StrategyId)
    expect(next).toMatchObject({ activeStrategyId: 'balanced', strategies: [{ id: 'balanced' }, { id: 'aggressive' }, { id: 'stg_new' }] })
    if (typeof next === 'string') throw new Error(next)
    expect(next.strategies[0]!.scoring.base_score).toBe(builtIn('balanced').scoring.base_score)
    expect(next.strategies[2]!.scoring.base_score).toBe(60)
  })

  it('prunes only the indicator settings the editor itself left unused', () => {
    const balanced = builtIn('balanced')
    const kept = new Set(Object.keys(balanced.indicators))
    const withOrphan = { ...balanced, indicators: { ...balanced.indicators, ind_orphan: { kind: 'rsi', period: 9 } } } as Strategy
    expect(Object.keys(pruneEditorIndicators(withOrphan, kept).indicators)).toEqual([...kept])
  })
})
