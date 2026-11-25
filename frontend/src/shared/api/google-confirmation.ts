import { randomHex } from '@/shared/lib/random-id'
import type { components } from './schema.gen'

type SettingChange = components['schemas']['SettingChange']

const STORAGE_KEY = 'stock-agent.settings-confirmation'
const CONFIRMATION_ID_DIGITS = 32

/**
 * A save waiting for its confirmation by Google: the id the server grants, the changes to send once it has, and the
 * page the save was made on when it is not the settings page, which the browser goes back to once the save is sent.
 */
export interface PendingSave {
  id: string
  changes: SettingChange[]
  returnTo?: string
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
export function startGoogleConfirmation({
  changes,
  returnTo,
  navigate = (address) => window.location.assign(address),
}: {
  changes: SettingChange[]
  returnTo?: string
  navigate?: (address: string) => void
}) {
  const pending: PendingSave = { id: randomHex(CONFIRMATION_ID_DIGITS), changes, ...(returnTo ? { returnTo } : {}) }
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
    const returnTo: unknown = Reflect.get(pending, 'returnTo')
    if (typeof id !== 'string' || !Array.isArray(changes)) return null
    // Only a page of this site is gone back to, never an address someone wrote into the storage.
    return { id, changes: changes.filter(isChange), ...(typeof returnTo === 'string' && returnTo.startsWith('/') && !returnTo.startsWith('//') ? { returnTo } : {}) }
  } catch {
    return null
  }
}

function isChange(value: unknown): value is SettingChange {
  return typeof value === 'object' && value !== null && typeof Reflect.get(value, 'path') === 'string' && 'value' in value
}
