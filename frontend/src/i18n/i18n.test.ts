import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { COMPARATORS, INDICATOR_CATALOG, INDICATOR_KINDS, RULE_EFFECTS } from '@/features/strategies/model/catalog'
import openapi from '@/shared/api/openapi.json'
import { resources } from './resources'

type Tree = { [key: string]: string | Tree }

function flatten(tree: Tree, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string' ? [`${prefix}${key}`] : flatten(value, `${prefix}${key}.`),
  )
}

function lookup(namespace: string, key: string): unknown {
  const tree = (resources.en as unknown as Record<string, Tree>)[namespace]
  return key.split('.').reduce<unknown>((node, part) => (node as Tree | undefined)?.[part], tree)
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name)
    if (statSync(full).isDirectory()) return name === 'i18n' ? [] : sourceFiles(full)
    return /\.tsx?$/.test(name) && !/\.test\./.test(name) ? [full] : []
  })
}

describe('translations', () => {
  it('zh-TW and en have exactly the same keys in every namespace', () => {
    for (const namespace of Object.keys(resources.en)) {
      const en = flatten((resources.en as unknown as Record<string, Tree>)[namespace]!).sort()
      const zh = flatten((resources['zh-TW'] as unknown as Record<string, Tree>)[namespace]!).sort()
      expect(zh, namespace).toEqual(en)
    }
  })

  it('every literal key used in the source exists', () => {
    const missing: string[] = []
    for (const file of sourceFiles(path.resolve(import.meta.dirname, '..'))) {
      const text = readFileSync(file, 'utf8')
      const namespace = text.match(/useTranslation\('([\w-]+)'\)/)?.[1] ?? 'common'
      for (const call of text.matchAll(/\bt\(([^()]*?)(?:,|\))/g)) {
        for (const literal of call[1]!.matchAll(/(?<![=!]==\s*)'([\w.:-]+)'/g)) {
          const raw = literal[1]!
          const [ns, key] = raw.includes(':') ? raw.split(':') : [namespace, raw]
          if (typeof lookup(ns!, key!) !== 'string') missing.push(`${path.basename(file)}: ${ns}:${key}`)
        }
      }
    }
    expect(missing).toEqual([])
  })

  it('every dynamic key family resolves for each value it can take', () => {
    const families: [string, string, readonly string[]][] = [
      ['formula', 'comparator', COMPARATORS],
      ['formula', 'indicator', INDICATOR_KINDS],
      ['formula', 'indicatorKind', INDICATOR_KINDS],
      ['formula', 'output', INDICATOR_KINDS.flatMap((kind) => INDICATOR_CATALOG[kind].outputs)],
      ['formula', 'field', ['open', 'high', 'low', 'close', 'volume']],
      ['strategies', 'effect', RULE_EFFECTS],
      ['builder', 'error', ['required', 'notNumber', 'notInteger', 'outOfRange', 'macdFastSlow', 'emptyGroup', 'noRules', 'tooManyRules', 'tooManyConditions', 'missingIndicator', 'invalidOutput', 'divideByZero', 'needsData', 'crossingLatestPrice', 'unitMismatch', 'unsupportedArithmetic']],
      ['runs', 'state', ['running', 'finished', 'failed', 'unfinished']],
      ['runs', 'workflow', ['full_cycle', 'buzz_scan', 'intraday', 'specific_stocks', 'manual_buy', 'valuation', 'research']],
      ['runs', 'action', ['buy', 'sell', 'hold']],
      ['watchlist', 'type', ['manual', 'technical', 'buzz']],
      ['valuation', 'elimination', ['eps_unavailable', 'eps_not_positive', 'price_missing', 'price_stale', 'below_min_undervaluation', 'no_price_history', 'technical_hard_failure']],
      ['valuation', 'epsUnavailable', ['not_loaded', 'not_reported', 'incomplete_history', 'source_failed']],
      ['valuation', 'peNotApplicable', ['eps_unavailable', 'eps_zero', 'eps_negative', 'invalid_price']],
      ['admin', 'setting', (openapi.components.schemas.EditableSetting.enum as string[]).map((setting) => setting.replaceAll('.', '_'))],
      ['admin', 'group', ['ai', 'behavior', 'analysis', 'sentiment', 'collect_rules', 'quality', 'freshness', 'valuation', 'watchlist', 'market_data', 'prompts']],
      ['common', 'errors', ['unauthorized', 'forbidden', 'notFound', 'conflict', 'invalid', 'unavailable', 'network', 'server']],
      ['overview', 'index', openapi.components.schemas.MarketIndex.enum as string[]],
    ]
    for (const [namespace, family, values] of families) {
      for (const value of values) expect(lookup(namespace, `${family}.${value}`), `${namespace}:${family}.${value}`).toBeTypeOf('string')
    }
  })
})
