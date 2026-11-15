import type { Schemas } from '@/shared/api'
import type { SettingsProblem } from './model'

export type SettingField = Schemas['SettingField']
export type SettingChange = Schemas['SettingChange']
export type SettingGroup = Schemas['SettingGroup']
export type SettingUnit = Schemas['SettingUnit']
export type Value = SettingField['value']

/**
 * What a control holds while the administrator edits it. A chosen kind holds the value itself: a switch's state, the
 * option or step picked, the chosen items, a number on the range, null for not set. A typed kind holds its text.
 * A setting nobody touched has no input.
 */
export type Input = Value

/** The groups in the order the form shows them; the compiler refuses this table when the contract adds or drops one. */
const GROUP_ORDER = { site_access: 0, features: 1, ranking: 2, data_history: 3, ai: 4, trading_limits: 5, advanced: 6 } as const satisfies Record<SettingGroup, number>

export const GROUPS = (Object.keys(GROUP_ORDER) as SettingGroup[]).sort((a, b) => GROUP_ORDER[a] - GROUP_ORDER[b])

/** The YAML section a setting sits in, and `site` for a top-level setting. */
export function sectionOf(path: string): string {
  const keys = path.split('.')
  return keys.length === 1 ? 'site' : keys[0]!
}

/** A second heading for a setting two levels down, such as `sources.exchange`; null for the others. */
export function headingOf(path: string): string | null {
  const keys = path.split('.')
  return keys.length > 2 ? keys.slice(0, 2).join('.') : null
}

/** The settings of one YAML section inside a group, under one sub-heading. */
export interface Part {
  section: string
  heading: string | null
  fields: SettingField[]
}

export interface Group {
  id: SettingGroup
  parts: Part[]
}

/** The fields by group in the form's order, and inside a group by YAML section in the server's order. */
export function groupsOf(fields: readonly SettingField[]): Group[] {
  return GROUPS.flatMap((id) => {
    const parts: Part[] = []
    for (const field of fields) {
      if (field.group !== id) continue
      const [section, heading] = [sectionOf(field.path), headingOf(field.path)]
      let part = parts.find((item) => item.section === section && item.heading === heading)
      if (!part) parts.push((part = { section, heading, fields: [] }))
      part.fields.push(field)
    }
    return parts.length > 0 ? [{ id, parts }] : []
  })
}

/** An option the dictionaries name (`admin:form.option.<option>`): a plain word, such as an enum's member. Any other shows as it is. */
export const isNamedOption = (option: string): boolean => /^[\w-]+$/.test(option)

const isNumberList = (value: Value): boolean => Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'number')

/** A text that reads better in a box than on one line: a prompt, a disclaimer. */
export function isLongText(field: SettingField): boolean {
  return field.kind === 'text' && typeof field.value === 'string' && (field.value.includes('\n') || field.value.length > 60)
}

/** The input a control starts from: the server's value as the control shows it. */
export function inputOf(field: SettingField): Input {
  const value = field.value
  switch (field.kind) {
    case 'lines':
      return Array.isArray(value) ? value.map(String).join('\n') : ''
    case 'structure':
      return JSON.stringify(value, null, 2)
    case 'text':
    case 'date':
    case 'time':
      return value === null ? '' : String(value)
    case 'switch':
    case 'choice':
    case 'choices':
    case 'steps':
    case 'range':
      return value
  }
}

/** One entry a choice or a steps control lists. */
export interface Entry {
  /** The entry's name inside the control: its value as JSON, so "5" and 5 never collide. */
  key: string
  value: Value
  /** The value the settings file holds now, which is none of the options: it stays listed so picking it again changes nothing. */
  custom: boolean
}

export const entryKey = (value: Value): string => JSON.stringify(value)

/**
 * What a choice or a steps control lists: "not set" first where the setting may be unset, the options or steps, and
 * the file's own value when it is none of them, a step in its place by size.
 */
export function entriesOf(field: SettingField): Entry[] {
  const offered: Value[] = field.kind === 'steps' ? field.steps : field.options
  const listed = [...offered]
  const current = field.value
  const custom = current !== null && !offered.some((item) => item === current)
  if (custom) {
    const after = typeof current === 'number' ? listed.findIndex((item) => typeof item === 'number' && item > current) : -1
    listed.splice(after === -1 ? listed.length : after, 0, current)
  }
  const entries = listed.map((value) => ({ key: entryKey(value), value, custom: custom && value === current }))
  return field.nullable ? [{ key: entryKey(null), value: null, custom: false }, ...entries] : entries
}

/** The items a choices control lists: the options, then each item the file holds that is none of them. */
export function choiceEntriesOf(field: SettingField): Entry[] {
  const held = Array.isArray(field.value) ? field.value.map(String) : []
  const extra = held.filter((item) => !field.options.includes(item))
  return [...field.options.map((value) => ({ key: value, value, custom: false })), ...extra.map((value) => ({ key: value, value, custom: true }))]
}

function decimalsOf(value: number): number {
  const [mantissa = '', exponent = '0'] = String(value).split('e')
  return Math.max(0, (mantissa.split('.')[1]?.length ?? 0) - Number(exponent))
}

/** A setting's number as the form says it: a fraction as a percentage, with the digits it needs and no more. */
export function shownAmount(value: number, unit: SettingField['unit']): { value: number; decimals: number } {
  // 0.07 * 100 is 7.000000000000001 in binary; twelve digits are more than any setting holds.
  const shown = Number((unit === 'percent' ? value * 100 : value).toPrecision(12))
  return { value: shown, decimals: Math.min(decimalsOf(shown), 6) }
}

/** Whether a range's value sits on the grid its buttons and slider move on; one that does not shows as a custom value. */
export function onGrid(field: SettingField, value: number): boolean {
  const { minimum, maximum, step } = field
  if ((typeof minimum === 'number' && value < minimum) || (typeof maximum === 'number' && value > maximum)) return false
  if (typeof step !== 'number' || step <= 0) return true
  const steps = (value - (minimum ?? 0)) / step
  return Math.abs(steps - Math.round(steps)) < 1e-6
}

/**
 * The value one press of minus or plus leads to: the next point of the grid in that direction, inside the bounds. A
 * value off the grid moves onto it, and a setting not set yet starts at its minimum.
 */
export function stepped(field: SettingField, current: number | null, direction: 1 | -1): number {
  const { minimum, maximum } = field
  const step = typeof field.step === 'number' && field.step > 0 ? field.step : 1
  const base = minimum ?? 0
  const clamp = (value: number) => Math.min(maximum ?? Infinity, Math.max(minimum ?? -Infinity, value))
  if (current === null) return clamp(base)
  const steps = (current - base) / step
  const next = direction === 1 ? Math.floor(steps + 1e-6) + 1 : Math.ceil(steps - 1e-6) - 1
  // Binary fractions drift (0.1 + 0.2), so the result is cut to the digits the grid has.
  return clamp(Number((base + next * step).toFixed(Math.max(decimalsOf(step), decimalsOf(base)))))
}

export type Parsed = { ok: true; value: Value } | { ok: false; problem: SettingsProblem }

function problem(field: SettingField, code: string, params: Record<string, string | number> = {}): Parsed {
  return { ok: false, problem: { message: code, code, params, path: field.path, file: null, line: null, column: null } }
}

function parseLines(field: SettingField, typed: string): Parsed {
  const items = typed.split('\n').map((line) => line.trim()).filter(Boolean)
  if (!isNumberList(field.value)) return { ok: true, value: items }
  const numbers = items.map(Number)
  return numbers.every(Number.isFinite) ? { ok: true, value: numbers } : problem(field, 'float_parsing')
}

/** The value an input stands for, or the problem the server would refuse it with, in the server's own codes. */
export function parse(field: SettingField, input: Input): Parsed {
  if (typeof input !== 'string') return { ok: true, value: input }
  switch (field.kind) {
    case 'lines':
      return parseLines(field, input)
    case 'structure':
      try {
        return { ok: true, value: JSON.parse(input) as Value }
      } catch {
        return problem(field, 'json_invalid')
      }
    case 'date':
    case 'time':
      if (input !== '') return { ok: true, value: input }
      return field.nullable ? { ok: true, value: null } : problem(field, 'missing')
    case 'text':
      return { ok: true, value: input === '' && field.nullable ? null : input }
    default:
      return { ok: true, value: input }
  }
}

const same = (a: Value, b: Value) => JSON.stringify(a) === JSON.stringify(b)

/**
 * What a save sends: each touched setting whose value differs from the server's, and the problems of inputs that are
 * not a value yet. A save waits until there is no problem. A setting nobody touched is never sent, so a value the
 * file holds that the form would not offer stays as it is.
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
