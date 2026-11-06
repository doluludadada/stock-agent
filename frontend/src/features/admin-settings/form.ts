import type { Schemas } from '@/shared/api'
import type { LocatedProblem, SettingsFileId } from './model'

export type SettingsForm = Schemas['SettingsForm']
export type SettingChange = Schemas['SettingChange']

/** The one settings file the form edits; instructions.yaml holds prompts, which stay text. */
export const FORM_FILE: SettingsFileId = 'appsetting'

export interface FormSection {
  /** The section's heading is `admin:form.section.<id>`; a problem the server places at this path shows under it. */
  id: string
  /** Settings shown, not edited: each changes only outside the form. */
  readOnly?: true
  /** Dotted paths in appsetting.yaml. A label is `admin:form.field.<path>`; the control comes from the schema there. */
  fields: readonly string[]
}

/**
 * The settings the form shows, in the order a business person reads them. A setting no section lists stays in the
 * Advanced (YAML) tab: URLs, prompts, file paths, sources, chat, folders and the built-in strategies.
 */
export const FORM_SECTIONS: readonly FormSection[] = [
  { id: 'site', readOnly: true, fields: ['environment', 'db.backend'] },
  { id: 'ai', fields: ['ai.active_model', 'ai.user_selectable', 'ai.temperature', 'ai.max_output_tokens', 'ai.connection_timeout'] },
  {
    id: 'accounts',
    fields: ['accounts.registration_open', 'accounts.daily_ai_calls', 'accounts.daily_ai_calls_total', 'accounts.session_days', 'accounts.max_concurrent_runs'],
  },
  { id: 'trading', fields: ['trading.execution_provider', 'trading.order_mode'] },
  { id: 'mock_trading', fields: ['mock_trading.initial_cash'] },
  {
    id: 'analysis',
    fields: [
      'analysis.technical_weight',
      'analysis.ai_weight',
      'analysis.min_combined_score_buy',
      'analysis.max_combined_score_sell',
      'analysis.risk_per_trade_pct',
      'analysis.stop_loss_pct',
      'analysis.lot_size',
      'analysis.reason_item_limit',
      'analysis.article_fetch_limit',
      'analysis.lookback_days',
      'analysis.history_calendar_days_per_bar',
    ],
  },
  { id: 'watchlist', fields: ['watchlist.automatic_expiry_sessions'] },
  { id: 'notifications', fields: ['notifications.enabled'] },
  { id: 'quality', fields: ['quality.min_chars_stock', 'quality.min_chars_news', 'quality.min_chars_gossip'] },
  {
    id: 'freshness',
    fields: ['freshness.realtime_max_lag_minutes', 'freshness.history_max_lag_days', 'freshness.missing_session_listed_stocks', 'freshness.daily_close_max_missed_sessions'],
  },
  {
    id: 'market_data',
    fields: ['market_data.quote_request_interval_seconds', 'market_data.history_batch_delay_seconds', 'market_data.history_retry_hours', 'market_data.listing_cache_hours'],
  },
]

/** The control a setting gets from its schema, holding the value the text sets. */
export type Control =
  | { kind: 'switch'; value: boolean }
  | { kind: 'select'; options: string[]; value: string }
  | { kind: 'choices'; options: string[]; value: string[] }
  | { kind: 'number'; integer: boolean; min: number | undefined; max: number | undefined; value: number }
  | { kind: 'text'; value: string }

/**
 * What one row of the form shows: a control over the value, the value read only, a setting the text leaves to its
 * default, or a value the form cannot show, which the YAML tab can.
 */
export type RowView = { kind: 'control'; control: Control } | { kind: 'readOnly'; value: string } | { kind: 'missing' } | { kind: 'yamlOnly' }

export interface FormRow {
  path: string
  /** The setting's own description in the schema: its docstring in the settings class. */
  description: string | null
  view: RowView
}

/** A JSON schema node, read field by field: the server's schema is data, checked where it is read. */
export type SchemaNode = Record<string, unknown>

function isSchemaNode(value: unknown): value is SchemaNode {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function strings(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : null
}

/** A node with its `$ref` followed and an optional's null branch dropped: the type, choices and bounds it holds. */
function resolved(root: SchemaNode, node: SchemaNode): SchemaNode {
  const { $ref, anyOf, ...rest } = node
  const definitions = isSchemaNode(root.$defs) ? root.$defs : {}
  if (typeof $ref === 'string') {
    const target = definitions[$ref.split('/').at(-1) ?? '']
    return isSchemaNode(target) ? resolved(root, { ...target, ...rest }) : rest
  }
  const branch = Array.isArray(anyOf) ? anyOf.find((item) => isSchemaNode(item) && item.type !== 'null') : undefined
  return isSchemaNode(branch) ? resolved(root, { ...branch, ...rest }) : node
}

/** The schema's property at a dotted path, unresolved, so its description is the setting's own and not its type's. */
function propertyAt(root: SchemaNode, path: string): SchemaNode | null {
  let property: SchemaNode | null = null
  let section: SchemaNode = root
  for (const key of path.split('.')) {
    const properties = resolved(root, section).properties
    property = isSchemaNode(properties) && isSchemaNode(properties[key]) ? properties[key] : null
    if (!property) return null
    section = property
  }
  return property
}

function numberControl(schema: SchemaNode, value: unknown): Control | null {
  if (typeof value !== 'number') return null
  const integer = schema.type === 'integer'
  const bound = (key: string) => {
    const limit = schema[key]
    return typeof limit === 'number' ? limit : undefined
  }
  const above = bound('exclusiveMinimum')
  const below = bound('exclusiveMaximum')
  const min = bound('minimum') ?? (above !== undefined && integer ? above + 1 : above)
  const max = bound('maximum') ?? (below !== undefined && integer ? below - 1 : below)
  return { kind: 'number', integer, min, max, value }
}

/** The control for a value by its schema: a switch, a select, checkboxes, a number or a text; null for any other. */
export function controlOf(root: SchemaNode, property: SchemaNode, value: unknown): Control | null {
  const schema = resolved(root, property)
  const options = strings(schema.enum)
  if (options) return typeof value === 'string' ? { kind: 'select', options, value } : null
  switch (schema.type) {
    case 'boolean':
      return typeof value === 'boolean' ? { kind: 'switch', value } : null
    case 'integer':
    case 'number':
      return numberControl(schema, value)
    case 'string':
      return typeof value === 'string' ? { kind: 'text', value } : null
    case 'array': {
      const choices = isSchemaNode(schema.items) ? strings(resolved(root, schema.items).enum) : null
      const chosen = strings(value)
      return choices && chosen ? { kind: 'choices', options: choices, value: chosen } : null
    }
    default:
      return null
  }
}

/** The rows of one section, in its order, for the settings a text sets and the schema of what each accepts. */
export function rowsOf(section: FormSection, root: SchemaNode, values: Readonly<Record<string, unknown>>): FormRow[] {
  return section.fields.map((path) => {
    const property = propertyAt(root, path)
    const description = typeof property?.description === 'string' ? property.description : null
    if (!Object.hasOwn(values, path)) return { path, description, view: { kind: 'missing' } }
    const value = values[path]
    if (section.readOnly) return { path, description, view: { kind: 'readOnly', value: String(value) } }
    const control = property ? controlOf(root, property, value) : null
    return { path, description, view: control ? { kind: 'control', control } : { kind: 'yamlOnly' } }
  })
}

/** The problems the server places at a setting or under it, such as `ai.user_selectable.0` for the AI models offered. */
export function problemsAt(problems: readonly LocatedProblem[], path: string): LocatedProblem[] {
  return problems.filter((problem) => problem.path !== null && (problem.path === path || problem.path.startsWith(`${path}.`)))
}

/** The change a control makes, by the dotted path of its setting. */
export function changeOf(path: string, value: SettingChange['value']): SettingChange {
  return { path: path.split('.'), value }
}
