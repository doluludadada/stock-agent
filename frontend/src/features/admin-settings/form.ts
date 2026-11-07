import type { Schemas } from '@/shared/api'
import type { SettingsProblem } from './model'

export type SettingField = Schemas['SettingField']
export type SettingChange = Schemas['SettingChange']
type Value = SettingField['value']

/**
 * What a control holds while the administrator edits it: a switch's state, a choice, the chosen items, or the text
 * typed into a number, text, list or JSON field. A setting nobody touched has no input.
 */
export type Input = boolean | string | string[]

/** The section a setting shows under: the YAML key it sits in, and `site` for a top-level setting. */
export function sectionOf(path: string): string {
  const keys = path.split('.')
  return keys.length === 1 ? 'site' : keys[0]!
}

/** A heading inside a section for a setting two levels down, such as `sources.exchange`; null for the others. */
export function groupOf(path: string): string | null {
  const keys = path.split('.')
  return keys.length > 2 ? keys.slice(0, 2).join('.') : null
}

export interface Group {
  id: string | null
  fields: SettingField[]
}

export interface Section {
  id: string
  groups: Group[]
}

/** The fields in the server's order, by section, and inside a section by group. */
export function sectionsOf(fields: readonly SettingField[]): Section[] {
  const sections: Section[] = []
  for (const field of fields) {
    const id = sectionOf(field.path)
    let section = sections.find((item) => item.id === id)
    if (!section) sections.push((section = { id, groups: [] }))
    const group = groupOf(field.path)
    const last = section.groups.at(-1)
    if (last && last.id === group) last.fields.push(field)
    else section.groups.push({ id: group, fields: [field] })
  }
  return sections
}

const isNumberList = (value: Value): boolean => Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'number')

/** A text that reads better in a box than on one line: a prompt, a disclaimer. */
export function isLongText(field: SettingField): boolean {
  return field.kind === 'text' && typeof field.value === 'string' && (field.value.includes('\n') || field.value.length > 60)
}

/** The input a control starts from: the server's value as the control shows it. */
export function inputOf(field: SettingField): Input {
  const value = field.value
  switch (field.kind) {
    case 'switch':
      return value === true
    case 'choices':
      return Array.isArray(value) ? value.map(String) : []
    case 'lines':
      return Array.isArray(value) ? value.map(String).join('\n') : ''
    case 'structure':
      return JSON.stringify(value, null, 2)
    case 'choice':
    case 'integer':
    case 'number':
    case 'text':
      return value === null || value === undefined ? '' : String(value)
  }
}

export type Parsed = { ok: true; value: Value } | { ok: false; problem: SettingsProblem }

function problem(field: SettingField, code: string, params: Record<string, string | number> = {}): Parsed {
  return { ok: false, problem: { message: code, code, params, path: field.path, file: null, line: null, column: null } }
}

function parseNumber(field: SettingField, typed: string): Parsed {
  if (typed.trim() === '' && field.value === null) return { ok: true, value: null }
  const integer = field.kind === 'integer'
  const value = Number(typed)
  if (typed.trim() === '' || !Number.isFinite(value)) return problem(field, integer ? 'int_parsing' : 'float_parsing')
  if (integer && !Number.isInteger(value)) return problem(field, 'int_from_float')
  const { minimum, maximum, exclusive_minimum: above, exclusive_maximum: below } = field
  if (typeof above === 'number' && value <= above) return problem(field, 'greater_than', { gt: above })
  if (typeof minimum === 'number' && value < minimum) return problem(field, 'greater_than_equal', { ge: minimum })
  if (typeof below === 'number' && value >= below) return problem(field, 'less_than', { lt: below })
  if (typeof maximum === 'number' && value > maximum) return problem(field, 'less_than_equal', { le: maximum })
  return { ok: true, value }
}

function parseLines(field: SettingField, typed: string): Parsed {
  const items = typed.split('\n').map((line) => line.trim()).filter(Boolean)
  if (!isNumberList(field.value)) return { ok: true, value: items }
  const numbers = items.map(Number)
  return numbers.every(Number.isFinite) ? { ok: true, value: numbers } : problem(field, 'float_parsing')
}

/** The value an input stands for, or the problem the server would refuse it with, in the server's own codes. */
export function parse(field: SettingField, input: Input): Parsed {
  if (typeof input === 'boolean' || Array.isArray(input)) return { ok: true, value: input }
  switch (field.kind) {
    case 'integer':
    case 'number':
      return parseNumber(field, input)
    case 'lines':
      return parseLines(field, input)
    case 'structure':
      try {
        return { ok: true, value: JSON.parse(input) as Value }
      } catch {
        return problem(field, 'json_invalid')
      }
    default:
      return { ok: true, value: input }
  }
}

const same = (a: Value, b: Value) => JSON.stringify(a) === JSON.stringify(b)

/**
 * What a save sends: each touched setting whose value differs from the server's, and the problems of inputs that are
 * not a value yet. A save waits until there is no problem.
 */
export function changesOf(fields: readonly SettingField[], inputs: Readonly<Record<string, Input>>) {
  const changes: SettingChange[] = []
  const problems: SettingsProblem[] = []
  for (const field of fields) {
    if (!Object.hasOwn(inputs, field.path) || field.restart_only) continue
    const parsed = parse(field, inputs[field.path]!)
    if (!parsed.ok) problems.push(parsed.problem)
    else if (!same(parsed.value, field.value)) changes.push({ path: field.path, value: parsed.value })
  }
  return { changes, problems }
}

/** The problems about a setting or about a part of it, such as `ai.available_models.openai` for the models map. */
export function problemsAt(problems: readonly SettingsProblem[], path: string): SettingsProblem[] {
  return problems.filter((item) => item.path === path || item.path?.startsWith(`${path}.`))
}

/** The problems no field of the form holds: from .env, the database or a broker login. */
export function problemsElsewhere(problems: readonly SettingsProblem[], fields: readonly SettingField[]): SettingsProblem[] {
  return problems.filter((item) => !fields.some((field) => problemsAt([item], field.path).length > 0))
}
