import { readFileSync } from 'node:fs'
import path from 'node:path'
import { strategyFromApi, type ApiStrategy } from '../api/mapping'
import type { BuiltInId } from './settings'
import type { IdFactory, Strategy } from './types'

export function sequentialIds(): IdFactory {
  let next = 0
  return (prefix) => `${prefix}_t${(next += 1)}`
}

export const fakeText = {
  t: (key: string, params?: Record<string, string | number>) => (params ? `${key}${JSON.stringify(params)}` : key),
  number: (value: number) => String(value),
}

export { BUILT_IN_IDS } from './settings'

const folder = path.resolve(import.meta.dirname, '../../../../../config/strategies')

/** The JSON the backend answers for config/strategies/<id>.json: every default written out. */
function withDefaults(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(withDefaults)
  if (typeof node !== 'object' || node === null) return node
  const object = Object.fromEntries(Object.entries(node).map(([key, value]) => [key, withDefaults(value)]))
  if (object.type === 'market') return { bars_ago: 0, ...object }
  if (object.type === 'indicator') return { output: 'value', bars_ago: 0, ...object }
  return object
}

export function builtInJson(id: BuiltInId): ApiStrategy {
  return withDefaults(JSON.parse(readFileSync(path.join(folder, `${id}.json`), 'utf8'))) as ApiStrategy
}

export function builtIn(id: BuiltInId): Strategy {
  return strategyFromApi(builtInJson(id))
}
