import { describe, expect, it } from 'vitest'
import { ApiError } from '@/shared/api'
import { changesOf, groupOf, inputOf, problemsAt, problemsElsewhere, sectionOf, sectionsOf, type SettingField } from './form'
import { refusalOf } from './model'

function field(path: string, kind: SettingField['kind'], value: SettingField['value'], extra: Partial<SettingField> = {}): SettingField {
  return { path, kind, value, options: [], minimum: null, maximum: null, exclusive_minimum: null, exclusive_maximum: null, restart_only: false, ...extra }
}

const temperature = field('ai.temperature', 'number', 0.7, { minimum: 0, maximum: 2 })
const tokens = field('ai.max_output_tokens', 'integer', 16000, { exclusive_minimum: 0 })
const models = field('ai.available_models', 'structure', { openai: 'gpt-5.5-mini', claude: 'claude-haiku-5-5' })
const hosts = field('api.allowed_hosts', 'lines', ['127.0.0.1', 'localhost'])
const environment = field('environment', 'choice', 'dev', { options: ['dev', 'test', 'prod'], restart_only: true })

describe('the settings form', () => {
  it('groups settings by their YAML section, top-level ones under site, and a third level under its own heading', () => {
    expect(['environment', 'ai.temperature', 'sources.exchange.twse_index_url'].map(sectionOf)).toEqual(['site', 'ai', 'sources'])
    expect(['ai.temperature', 'sources.exchange.twse_index_url'].map(groupOf)).toEqual([null, 'sources.exchange'])
    const sections = sectionsOf([environment, temperature, field('sources.ptt.base_url', 'text', 'https://www.ptt.cc'), field('sources.news.cnyes_api_url', 'text', 'x'), tokens])
    expect(sections.map((section) => [section.id, section.groups.map((group) => [group.id, group.fields.map((item) => item.path)])])).toEqual([
      ['site', [[null, ['environment']]]],
      ['ai', [[null, ['ai.temperature', 'ai.max_output_tokens']]]],
      ['sources', [['sources.ptt', ['sources.ptt.base_url']], ['sources.news', ['sources.news.cnyes_api_url']]]],
    ])
  })

  it('sends only the settings whose value changed, a list one item per line and a map from its JSON', () => {
    const fields = [temperature, tokens, models, hosts]
    const inputs = {
      'ai.temperature': '0.70',
      'ai.max_output_tokens': '8000',
      'ai.available_models': JSON.stringify({ openai: 'gpt-5.5', claude: 'claude-haiku-5-5' }),
      'api.allowed_hosts': inputOf(hosts) + '\n  stock.example.com \n\n',
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

  it('holds a save back with the refusal the server would give: a bound, a whole number, JSON', () => {
    const { changes, problems } = changesOf([temperature, tokens, models], { 'ai.temperature': '2.5', 'ai.max_output_tokens': '0.5', 'ai.available_models': '{"openai": ' })
    expect(changes).toEqual([])
    expect(problems.map((problem) => [problem.path, problem.code, problem.params])).toEqual([
      ['ai.temperature', 'less_than_equal', { le: 2 }],
      ['ai.max_output_tokens', 'int_from_float', {}],
      ['ai.available_models', 'json_invalid', {}],
    ])
    expect(changesOf([tokens], { 'ai.max_output_tokens': '0' }).problems[0]).toMatchObject({ code: 'greater_than', params: { gt: 0 } })
    expect(changesOf([tokens], { 'ai.max_output_tokens': '' }).problems[0]).toMatchObject({ code: 'int_parsing' })
    const unlimited = field('mock_trading.max_fill_quantity', 'integer', null, { exclusive_minimum: 0 })
    expect(changesOf([unlimited], { 'mock_trading.max_fill_quantity': '' }), 'a setting left empty on purpose stays empty').toEqual({ changes: [], problems: [] })
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
