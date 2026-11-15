import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { headingOf, sectionOf } from '@/features/admin-settings/form'
import { BUILT_IN_IDS, builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { EMPTY_DRAFT } from '@/features/holdings/model'
import { CAVEATS, PRESET_KEYS } from '@/features/ranking/model'
import { NEWS_SOURCES, QUARTER_FIGURES, READING_TONE } from '@/features/stock-research/model'
import { COMPARATORS, INDICATOR_CATALOG, INDICATOR_KINDS, RULE_EFFECTS } from '@/features/strategies/model/catalog'
import openapi from '@/shared/api/openapi.json'
import settingsFields from '@/shared/api/settings-fields.json'
import zhRuleNames from './locales/zh-TW/rule-names'
import { adminResources } from './admin-resources'
import { resources as shared } from './resources'

/** Every namespace: the ones every page downloads and the settings form's, which loads with its page. */
const resources = { en: { ...shared.en, ...adminResources.en }, 'zh-TW': { ...shared['zh-TW'], ...adminResources['zh-TW'] } }

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

/** Every setting the server's settings form shows: each needs a label and a help in every locale. */
const SETTING_PATHS = settingsFields.map((field) => field.path)

describe('translations', () => {
  it('zh-TW and en have exactly the same keys in every namespace', () => {
    for (const namespace of Object.keys(resources.en)) {
      const en = flatten((resources.en as unknown as Record<string, Tree>)[namespace]!).sort()
      const zh = flatten((resources['zh-TW'] as unknown as Record<string, Tree>)[namespace]!).sort()
      expect(zh, namespace).toEqual(en)
    }
  })

  it('names every rule of the built-in strategies in zh-TW, no two alike', () => {
    const names = new Set(BUILT_IN_IDS.flatMap((id) => builtInJson(id).rules.map((rule) => rule.name)))
    expect([...names].filter((name) => !zhRuleNames.has(name)), 'built-in rules with no zh-TW name').toEqual([])
    expect(new Set(zhRuleNames.values()).size, 'a report names its rules, so a copy needs a distinct name for each').toBe(zhRuleNames.size)
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
      ['runs', 'workflow', openapi.components.schemas.Workflow.enum as string[]],
      ['runs', 'action', ['buy', 'sell', 'hold']],
      ['runs', 'orderStatus', openapi.components.schemas.OrderStatus.enum as string[]],
      ['runs', 'followMark', ['open', 'followed']],
      ['runs', 'follow.ready', openapi.components.schemas.OrderPricing.enum as string[]],
      ['runs', 'follow.window', openapi.components.schemas.OrderPricing.enum as string[]],
      ['runs', 'follow.confirm', openapi.components.schemas.OrderPricing.enum as string[]],
      ['watchlist', 'type', ['manual', 'technical', 'buzz']],
      ['valuation', 'elimination', ['eps_unavailable', 'eps_not_positive', 'price_missing', 'price_stale', 'below_min_undervaluation', 'no_price_history', 'technical_hard_failure']],
      ['valuation', 'epsUnavailable', ['not_loaded', 'not_reported', 'incomplete_history', 'source_failed']],
      ['valuation', 'peNotApplicable', ['eps_unavailable', 'eps_zero', 'eps_negative', 'invalid_price']],
      ['admin', 'form.section', [...new Set(SETTING_PATHS.map(sectionOf))]],
      ['admin', 'form.heading', [...new Set(SETTING_PATHS.flatMap((path) => headingOf(path) ?? []))]],
      ['admin', 'form.group', [...new Set([...settingsFields.map((field) => field.group), ...(openapi.components.schemas.SettingGroup.enum as string[])])].flatMap((group) => [`${group}.title`, `${group}.description`])],
      ['admin', 'form.unit', openapi.components.schemas.SettingUnit.enum as string[]],
      ['admin', 'form.field', SETTING_PATHS],
      ['admin', 'form.help', SETTING_PATHS],
      ['admin', 'form.option', [...new Set(settingsFields.flatMap((field) => field.options))]],
      ['common', 'broker.name', openapi.components.schemas.ExecutionProvider.enum as string[]],
      ['account', 'page', (openapi.components.schemas.ExecutionProvider.enum as string[]).map((broker) => `${broker}.title`)],
      ['account', 'brokerage.server', ['simulation', 'live']],
      ['holdings', 'source', openapi.components.schemas.HoldingSource.enum as string[]],
      ['holdings', 'form.problem', Object.keys(EMPTY_DRAFT)],
      ['holdings', 'form.refusal', ['unlisted', 'failed']],
      ['common', 'errors', ['unauthorized', 'forbidden', 'notFound', 'conflict', 'invalid', 'rateLimited', 'unavailable', 'network', 'server']],
      ['auth', 'role', openapi.components.schemas.Role.enum as string[]],
      ['auth', 'settings.provider', openapi.components.schemas.AiProvider.enum as string[]],
      ['auth', 'users.status', openapi.components.schemas.UserStatus.enum as string[]],
      ['auth', 'users.change', ['makeAdmin', 'makeUser', 'deactivate', 'reactivate', 'password']],
      ['auth', 'users.done', ['makeAdmin', 'makeUser', 'deactivate', 'reactivate', 'password']],
      ['auth', 'users.confirm', ['makeAdmin.title', 'makeUser.title', 'deactivate.title', 'reactivate.title']],
      ['auth', 'users.filter', ['all', 'administrator', 'user', 'deactivated']],
      ['auth', 'problem', ['required', 'usernameFormat', 'emailFormat', 'passwordShort', 'passwordLong', 'mismatch', 'wrongCode']],
      ['auth', 'alert', ['failed', 'closed', 'alreadySetUp', 'taken', 'rateLimited']],
      ['common', 'nav', ['home', 'overview', 'world', 'valuation', 'watchlist', 'holdings', 'account', 'brokerage', 'settings', 'runs', 'strategies', 'backtest', 'ranking', 'builder', 'users', 'admin']],
      ['backtest', 'verdict.result', ['up', 'down', 'flat']],
      ['backtest', 'verdict.index', ['ahead', 'behind', 'level', 'none']],
      ['backtest', 'exit', ['stopLoss', 'score', 'open', 'other']],
      ['backtest', 'problem', ['dateRequired', 'beforeFirst', 'afterLast', 'firstAfterLast', 'cash', 'score']],
      ['backtest', 'preset', ['3M', '6M', '1Y', 'all']],
      ['backtest', 'trades.column', ['bought', 'sold', 'pnl', 'return', 'held']],
      ['backtest', 'notes', ['technicalOnly', 'nextOpen', 'listedToday']],
      ['ranking', 'preset', PRESET_KEYS],
      ['ranking', 'problem', ['dateRequired', 'firstAfterLast', 'afterLast']],
      ['ranking', 'mark', ['entered', 'notBought']],
      ['ranking', 'record.row', ['annual', 'worth', 'drawdown']],
      ['ranking', 'caveats', CAVEATS.flatMap((caveat) => [`${caveat}.title`, `${caveat}.detail`])],
      ['common', 'nav.section', ['today', 'research', 'mine', 'tools', 'admin']],
      ['common', 'nav.tab', ['home', 'ranking', 'search', 'holdings', 'more']],
      ['common', 'auth.prompt.what', ['ranking', 'holdings', 'watchlist']],
      ['overview', 'index', openapi.components.schemas.MarketIndex.enum as string[]],
      ['research', 'financials.figure', QUARTER_FIGURES.map((figure) => figure.key)],
      ['research', 'analysis.reading.kind', Object.keys(READING_TONE).flatMap((kind) => [`${kind}_one`, `${kind}_other`])],
      ['research', 'analysis.valuation.ratio', ['pe', 'pb', 'yield']],
      ['common', 'score.exclusion', openapi.components.schemas.RankingExclusion.enum as string[]],
      ...['factor', 'short', 'phrase'].map((family): [string, string, string[]] => ['common', `formula.${family}`, Object.keys(openapi.components.schemas.RankingFactor.discriminator.mapping)]),
      ['research', 'news.source', Object.keys(NEWS_SOURCES)],
      ['research', 'news.none', ['articles', 'openData']],
      ['research', 'brief.kind', openapi.components.schemas.BriefSourceKind.enum as string[]],
      ['research', 'brief.writtenIn', openapi.components.schemas.BriefLanguage.enum as string[]],
      ['research', 'brief.part', ['company', 'movement']],
      ['world', 'indicators.name', openapi.components.schemas.WorldIndicator.enum as string[]],
      ['world', 'brief.writtenIn', openapi.components.schemas.BriefLanguage.enum as string[]],
      ['world', 'brief', ['waiting.title', 'waiting.description', 'off.title', 'off.description']],
    ]
    for (const [namespace, family, values] of families) {
      for (const value of values) expect(lookup(namespace, `${family}.${value}`), `${namespace}:${family}.${value}`).toBeTypeOf('string')
    }
  })
})
