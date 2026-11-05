import openapi from '@/shared/api/openapi.json'
import { INDICATOR_CATALOG, INDICATOR_KINDS, LIMITS } from './catalog'

type JsonSchema = Record<string, unknown> & { properties?: Record<string, JsonSchema>; $ref?: string; enum?: string[]; const?: string }

const schemas = openapi.components.schemas as unknown as Record<string, JsonSchema>
const resolve = (schema: JsonSchema): JsonSchema => (schema.$ref ? schemas[schema.$ref.split('/').at(-1)!]! : schema)

/** Each indicator's parameter schema in the backend's contract, keyed by kind. */
function backendParameters(): Map<string, Record<string, JsonSchema>> {
  const byKind = new Map<string, Record<string, JsonSchema>>()
  for (const name of ['MovingAverageIndicator', 'PeriodIndicator', 'MacdIndicator', 'BollingerIndicator', 'StochasticIndicator']) {
    const { kind, ...parameters } = schemas[name]!.properties!
    for (const value of kind!.enum ?? [kind!.const!]) byKind.set(value, Object.fromEntries(Object.entries(parameters).map(([key, schema]) => [key, resolve(schema)])))
  }
  return byKind
}

describe('the designer catalog is the backend contract', () => {
  it('knows exactly the backend indicator kinds', () => {
    expect(new Set(INDICATOR_KINDS)).toEqual(new Set(backendParameters().keys()))
  })

  it('bounds every parameter as the backend validates it', () => {
    const backend = backendParameters()
    for (const kind of INDICATOR_KINDS) {
      const parameters = backend.get(kind)!
      expect(INDICATOR_CATALOG[kind].params.map((param) => param.key).sort(), kind).toEqual(Object.keys(parameters).sort())
      for (const param of INDICATOR_CATALOG[kind].params) {
        const schema = parameters[param.key]!
        expect(param.integer, `${kind}.${param.key} integer`).toBe(schema.type === 'integer')
        expect(param.max, `${kind}.${param.key} max`).toBe(schema.maximum)
        if (param.exclusiveMin) expect(param.min).toBe(schema.exclusiveMinimum)
        else expect(param.min, `${kind}.${param.key} min`).toBe((schema.exclusiveMinimum as number) + 1)
      }
    }
  })

  it('limits offsets, rules, groups and strategies as the backend does', () => {
    expect(LIMITS.maxBarsAgo).toBe(schemas.BarsAgo!.maximum)
    expect(LIMITS.maxRules).toBe((schemas['TechnicalStrategy-Input']!.properties!.rules as JsonSchema).maxItems)
    expect(LIMITS.maxConditionsPerGroup).toBe((schemas['ConditionGroup-Input']!.properties!.conditions as JsonSchema).maxItems)
    expect(LIMITS.maxStrategies).toBe((schemas['TechnicalSettings-Input']!.properties!.strategies as JsonSchema).maxItems)
    expect(LIMITS.maxBaseScore).toBe(schemas.Score_int_!.maximum)
  })
})
