import { describe, expect, it } from 'vitest'
import { ApiError } from '@/shared/api'
import openapi from '@/shared/api/openapi.json'
import { changesOf, choiceEntriesOf, entriesOf, GROUPS, groupsOf, headingOf, inputOf, onGrid, problemsAt, problemsElsewhere, sectionOf, shownAmount, stepped, type SettingField } from './form'
import { refusalOf } from './model'

function field(path: string, kind: SettingField['kind'], value: SettingField['value'], extra: Partial<SettingField> = {}): SettingField {
  return { path, kind, value, group: 'advanced', options: [], steps: [], minimum: null, maximum: null, step: null, unit: null, nullable: false, restart_only: false, ...extra }
}

const temperature = field('ai.temperature', 'range', 0.7, { group: 'ai', minimum: 0, maximum: 2, step: 0.1 })
const tokens = field('ai.max_output_tokens', 'steps', 16000, { steps: [4000, 8000, 16000, 32000] })
const models = field('ai.available_models', 'structure', { openai: 'gpt-5.5-mini', claude: 'claude-haiku-5-5' })
const hosts = field('api.allowed_hosts', 'lines', ['127.0.0.1', 'localhost'])
const environment = field('environment', 'choice', 'dev', { group: 'site_access', options: ['dev', 'test', 'prod'], restart_only: true })
const benchmark = field('ranking.benchmark_id', 'choice', '0050', { group: 'ranking', options: ['0050', '006208'] })
const stopLoss = field('analysis.stop_loss_pct', 'steps', 0.07, { group: 'trading_limits', steps: [0.05, 0.08, 0.1], unit: 'percent' })

const values = (entries: { value: SettingField['value']; custom: boolean }[]) => entries.map((entry) => [entry.value, entry.custom])

describe('the settings form', () => {
  it('lists the groups in the contract’s order', () => {
    expect(GROUPS).toEqual(openapi.components.schemas.SettingGroup.enum)
  })

  it('shows the settings by group in that order, and inside a group by YAML section in the server’s order', () => {
    expect(['environment', 'ai.temperature', 'sources.exchange.twse_index_url'].map(sectionOf)).toEqual(['site', 'ai', 'sources'])
    expect(['ai.temperature', 'sources.exchange.twse_index_url'].map(headingOf)).toEqual([null, 'sources.exchange'])
    const groups = groupsOf([models, environment, temperature, field('sources.ptt.base_url', 'text', 'https://www.ptt.cc'), hosts, field('sources.news.cnyes_api_url', 'text', 'x'), tokens])
    expect(groups.map((group) => [group.id, group.parts.map((part) => [part.section, part.heading, part.fields.map((item) => item.path)])])).toEqual([
      ['site_access', [['site', null, ['environment']]]],
      ['ai', [['ai', null, ['ai.temperature']]]],
      [
        'advanced',
        [
          ['ai', null, ['ai.available_models', 'ai.max_output_tokens']],
          ['sources', 'sources.ptt', ['sources.ptt.base_url']],
          ['api', null, ['api.allowed_hosts']],
          ['sources', 'sources.news', ['sources.news.cnyes_api_url']],
        ],
      ],
    ])
  })

  it('offers a choice its options and a steps setting its steps, with “not set” first where the setting may be unset', () => {
    expect(values(entriesOf(benchmark))).toEqual([['0050', false], ['006208', false]])
    expect(values(entriesOf(tokens))).toEqual([[4000, false], [8000, false], [16000, false], [32000, false]])
    expect(values(entriesOf({ ...tokens, value: null, nullable: true }))).toEqual([[null, false], [4000, false], [8000, false], [16000, false], [32000, false]])
  })

  it('keeps a value of the file that is none of the options listed as the custom one, a step in its place by size', () => {
    expect(values(entriesOf(stopLoss))).toEqual([[0.05, false], [0.07, true], [0.08, false], [0.1, false]])
    expect(values(entriesOf({ ...tokens, value: 64000 }))).toEqual([[4000, false], [8000, false], [16000, false], [32000, false], [64000, true]])
    expect(values(entriesOf({ ...benchmark, value: '2330' }))).toEqual([['0050', false], ['006208', false], ['2330', true]])
    const selectable = field('ai.user_selectable', 'choices', ['claude', 'mistral'], { options: ['openai', 'claude'] })
    expect(values(choiceEntriesOf(selectable))).toEqual([['openai', false], ['claude', false], ['mistral', true]])
  })

  it('leaves an off-list value alone when another setting is saved, and when it is picked again', () => {
    const fields = [stopLoss, tokens, { ...temperature, value: 0.73 }]
    expect(changesOf(fields, { 'ai.max_output_tokens': 8000 }), 'only the touched setting is sent').toEqual({ changes: [{ path: 'ai.max_output_tokens', value: 8000 }], problems: [] })
    expect(changesOf(fields, { 'analysis.stop_loss_pct': 0.07, 'ai.temperature': 0.73 }), 'picking the custom value again changes nothing').toEqual({ changes: [], problems: [] })
    expect(changesOf(fields, { 'analysis.stop_loss_pct': 0.08 }).changes).toEqual([{ path: 'analysis.stop_loss_pct', value: 0.08 }])
  })

  it('sends null for “not set”, and nothing when the setting was unset already', () => {
    const cap = field('mock_trading.max_fill_quantity', 'steps', 1000, { steps: [1000, 5000], nullable: true })
    expect(changesOf([cap], { 'mock_trading.max_fill_quantity': null }).changes).toEqual([{ path: 'mock_trading.max_fill_quantity', value: null }])
    expect(changesOf([{ ...cap, value: null }], { 'mock_trading.max_fill_quantity': null }).changes).toEqual([])
    const until = field('market.bond_etf_tax_exempt_until', 'date', '2026-12-31', { nullable: true })
    expect(changesOf([until], { 'market.bond_etf_tax_exempt_until': '' }).changes).toEqual([{ path: 'market.bond_etf_tax_exempt_until', value: null }])
    expect(changesOf([{ ...until, nullable: false }], { 'market.bond_etf_tax_exempt_until': '' }).problems[0]).toMatchObject({ code: 'missing' })
  })

  it('moves a range one step at a time inside its bounds, and a value between two steps onto the next one', () => {
    expect([stepped(temperature, 0.7, 1), stepped(temperature, 0.7, -1)]).toEqual([0.8, 0.6])
    expect([stepped(temperature, 2, 1), stepped(temperature, 0, -1)], 'the ends hold').toEqual([2, 0])
    expect([onGrid(temperature, 0.7), onGrid(temperature, 0.73), onGrid(temperature, 2.5)]).toEqual([true, false, false])
    expect([stepped(temperature, 0.73, 1), stepped(temperature, 0.73, -1)]).toEqual([0.8, 0.7])
    const day = field('ranking.decision_day', 'range', 10, { minimum: 1, maximum: null, step: 1 })
    expect([stepped(day, 10, 1), stepped(day, 1, -1), stepped({ ...day, nullable: true }, null, 1)]).toEqual([11, 1, 1])
  })

  it('says a fraction as a percentage with the digits it needs', () => {
    expect([shownAmount(0.07, 'percent'), shownAmount(0.001425, 'percent'), shownAmount(100000, 'twd'), shownAmount(0.5, null)]).toEqual([
      { value: 7, decimals: 0 },
      { value: 0.1425, decimals: 4 },
      { value: 100000, decimals: 0 },
      { value: 0.5, decimals: 1 },
    ])
  })

  it('sends only the settings whose value changed, a list one item per line and a map from its JSON', () => {
    const fields = [temperature, tokens, models, hosts]
    const inputs = {
      'ai.temperature': 0.7,
      'ai.max_output_tokens': 8000,
      'ai.available_models': JSON.stringify({ openai: 'gpt-5.5', claude: 'claude-haiku-5-5' }),
      'api.allowed_hosts': String(inputOf(hosts)) + '\n  stock.example.com \n\n',
    }
    expect(changesOf(fields, inputs)).toEqual({
      changes: [
        { path: 'ai.max_output_tokens', value: 8000 },
        { path: 'ai.available_models', value: { openai: 'gpt-5.5', claude: 'claude-haiku-5-5' } },
        { path: 'api.allowed_hosts', value: ['127.0.0.1', 'localhost', 'stock.example.com'] },
      ],
      problems: [],
    })
  })

  it('holds a save back while a typed setting is not a value yet', () => {
    const { changes, problems } = changesOf([models, tokens], { 'ai.available_models': '{"openai": ', 'ai.max_output_tokens': 8000 })
    expect(changes).toEqual([{ path: 'ai.max_output_tokens', value: 8000 }])
    expect(problems.map((problem) => [problem.path, problem.code])).toEqual([['ai.available_models', 'json_invalid']])
  })

  it('never sends a setting that changes only at a restart', () => {
    expect(changesOf([environment], { environment: 'prod' })).toEqual({ changes: [], problems: [] })
  })

  it('places a problem at its setting or at a part of it, and keeps the rest for the top of the form', () => {
    const problems = [
      { message: 'missing', path: 'ai.available_models.openai' },
      { message: 'low', path: 'ai.temperature' },
      { message: 'The app would not start: OperationalError.', path: null },
    ]
    expect(problemsAt(problems, 'ai.available_models').map((problem) => problem.message)).toEqual(['missing'])
    expect(problemsAt(problems, 'ai.temp')).toEqual([])
    expect(problemsElsewhere(problems, [temperature, models]).map((problem) => problem.message)).toEqual(['The app would not start: OperationalError.'])
  })

  it('reads a refused save by its code: problems at their settings, a wrong password, a conflict', () => {
    const body = { detail: 'The app would not start', code: 'settings_refused', problems: [{ message: 'Input should be less than or equal to 2', path: 'ai.temperature', code: 'less_than_equal', params: { le: 2 } }] }
    expect(refusalOf(new ApiError('invalid', 422, body.detail, [], null, body))).toMatchObject({ kind: 'refused', problems: [{ path: 'ai.temperature', code: 'less_than_equal' }] })
    expect(refusalOf(new ApiError('forbidden', 403, 'wrong', [], null, { detail: 'wrong', code: 'password_refused' }))).toEqual({ kind: 'wrongPassword' })
    expect(refusalOf(new ApiError('conflict', 409, 'moved', [], null, { detail: 'moved', code: 'settings_conflict' }))).toEqual({ kind: 'conflict' })
  })
})
