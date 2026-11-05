import { BUILT_IN_IDS as BUILT_INS, builtInJson as builtIn } from '../model/built-ins.test-support'
import { errorsOf, validateStrategy } from '../model/validate'
import { settingsFromApi, settingsToApi, strategyFromApi, strategyToApi } from './mapping'

describe('the formula JSON boundary', () => {
  it.each(BUILT_INS)('reads and writes back the %s built-in strategy unchanged', (id) => {
    const api = builtIn(id)
    const strategy = strategyFromApi(api)

    expect(strategyToApi(strategy)).toEqual(api)
    expect(strategy.rules).toHaveLength(api.rules.length)
  })

  it('reads all 23, 23 and 20 built-in rules with every effect, constants, arithmetic, MACD outputs and latest_price', () => {
    const strategies = BUILT_INS.map((id) => strategyFromApi(builtIn(id)))
    const text = JSON.stringify(strategies)

    expect(strategies.map((strategy) => strategy.rules.length)).toEqual([23, 23, 20])
    for (const effect of ['block_on_fail', 'reduce_score_on_fail', 'increase_score_on_pass']) expect(text).toContain(`"effect":"${effect}"`)
    for (const node of ['"type":"latest_price"', '"type":"constant"', '"output":"histogram"', '"output":"signal"', '"type":"arithmetic"']) expect(text).toContain(node)
    expect(text).not.toContain('indicator_id')
  })

  it('passes the editor validation without a blocking error', () => {
    for (const id of BUILT_INS) expect(errorsOf(validateStrategy(strategyFromApi(builtIn(id)))), id).toEqual([])
  })

  it('drops the editor ids and writes ne, constants and offsets in the API form', () => {
    const api = builtIn('balanced')
    const strategy = strategyFromApi(api)
    const [rule] = strategy.rules
    const edited = {
      ...strategy,
      rules: [
        {
          ...rule!,
          condition: {
            ...rule!.condition,
            bare: undefined,
            conditions: [
              {
                type: 'comparison' as const,
                id: 'node_extra' as never,
                operator: 'ne' as const,
                left: { type: 'market' as const, field: 'close' as const, barsAgo: 2 },
                right: { type: 'constant' as const, value: 1.5 },
              },
            ],
          },
        },
      ],
    }

    expect(strategyToApi(edited).rules[0]!.condition).toEqual({
      type: 'group',
      operator: 'all',
      conditions: [{ type: 'comparison', operator: 'ne', left: { type: 'market', field: 'close', bars_ago: 2 }, right: 1.5 }],
    })
    expect(JSON.stringify(strategyToApi(edited))).not.toMatch(/"id"|node_|rule_/)
  })

  it('keeps the selections and the revision a save must carry', () => {
    const api = {
      active_strategy_id: 'balanced',
      buzz_strategy_id: 'aggressive',
      strategies: BUILT_INS.map(builtIn),
      revision: 7,
    }

    expect(settingsToApi(settingsFromApi(api))).toEqual(api)
  })
})
