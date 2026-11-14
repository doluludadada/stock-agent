import { randomHex } from '@/shared/lib/random-id'
import { inputOf, type Input, type SettingChange, type SettingField } from './form'

const STORAGE_KEY = 'stock-agent.settings-confirmation'
const CONFIRMATION_ID_DIGITS = 32

/** A save waiting for its confirmation by Google: the id the server grants, and the changes to send once it has. */
export interface PendingSave {
  id: string
  changes: SettingChange[]
}

/** What `?google=` says when a confirmation ended without a grant; anything else reads as `failed`. */
const REFUSALS = ['stale_authentication', 'not_administrator', 'throttled'] as const

export function confirmationRefusal(outcome: string): (typeof REFUSALS)[number] | 'failed' {
  return REFUSALS.find((refusal) => refusal === outcome) ?? 'failed'
}

/**
 * An administrator without a password confirms a save by signing in to Google again. The changes wait in this tab's
 * session storage, under a fresh random id, while the browser is at Google; the server grants that id one save.
 */
export function startGoogleConfirmation(changes: SettingChange[], navigate: (address: string) => void = (address) => window.location.assign(address)) {
  const pending: PendingSave = { id: randomHex(CONFIRMATION_ID_DIGITS), changes }
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pending))
  navigate(`/v1/auth/google/start?confirmation=${pending.id}`)
}

/** The save that waited while the browser was at Google, once: reading it forgets it. */
export function takePendingSave(): PendingSave | null {
  const stored = sessionStorage.getItem(STORAGE_KEY)
  sessionStorage.removeItem(STORAGE_KEY)
  if (!stored) return null
  try {
    const pending: unknown = JSON.parse(stored)
    if (typeof pending !== 'object' || pending === null) return null
    const id: unknown = Reflect.get(pending, 'id')
    const changes: unknown = Reflect.get(pending, 'changes')
    return typeof id === 'string' && Array.isArray(changes) ? { id, changes: changes.filter(isChange) } : null
  } catch {
    return null
  }
}

function isChange(value: unknown): value is SettingChange {
  return typeof value === 'object' && value !== null && typeof Reflect.get(value, 'path') === 'string' && 'value' in value
}

/** The form's inputs that show the waiting changes again, so nothing typed before the trip to Google is lost. */
export function inputsOf(fields: readonly SettingField[], changes: readonly SettingChange[]): Record<string, Input> {
  const inputs: Record<string, Input> = {}
  for (const change of changes) {
    const field = fields.find((item) => item.path === change.path)
    if (field) inputs[change.path] = inputOf({ ...field, value: change.value })
  }
  return inputs
}
