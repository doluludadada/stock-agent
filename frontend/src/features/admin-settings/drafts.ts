import { useMemo, useSyncExternalStore } from 'react'
import { isSettingsFileId, type SettingsFileId } from './model'

/**
 * The administrator's unsaved text of one settings file and the file it started from. It exists only while the text
 * differs from that file: without one, the editor shows the file as it is on disk.
 */
export interface Draft {
  /** The user who typed it: another user signing in on this tab never sees it. */
  owner: string
  base: { revision: string; text: string }
  text: string
  /** When the text last changed, as an ISO time. */
  editedAt: string
  /** The administrator kept this text over a newer file on disk: saving it also undoes that file's changes. */
  rebased?: boolean
}

/** A draft written before this page loaded came back from the tab's storage, after a reload or a session that ended. */
export const PAGE_LOADED_AT = new Date().toISOString()

/**
 * Drafts live in this tab's sessionStorage, so a reload, a session that ended or a visit to another page loses no
 * text; closing the tab does, which the page warns about. Saving or discarding removes the draft.
 */
const STORAGE_KEY = 'stock-agent.settings-drafts'

type Stored = Partial<Record<SettingsFileId, Draft>>

let stored: Stored = read()
const listeners = new Set<() => void>()

function read(): Stored {
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? '{}')
    if (typeof parsed !== 'object' || parsed === null) return {}
    return Object.fromEntries(Object.entries(parsed).filter(([file, draft]) => isSettingsFileId(file) && isDraft(draft)))
  } catch {
    return {}
  }
}

function isDraft(value: unknown): value is Draft {
  if (typeof value !== 'object' || value === null) return false
  const field = (key: string): unknown => Reflect.get(value, key)
  const base = field('base')
  return (
    typeof field('owner') === 'string' &&
    typeof field('text') === 'string' &&
    typeof field('editedAt') === 'string' &&
    typeof base === 'object' &&
    base !== null &&
    typeof Reflect.get(base, 'revision') === 'string' &&
    typeof Reflect.get(base, 'text') === 'string'
  )
}

function write(next: Stored) {
  stored = next
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // A full or blocked storage keeps the draft in memory for this page; nothing else to do.
  }
  listeners.forEach((listener) => listener())
}

export const drafts = {
  get: (file: SettingsFileId, owner: string): Draft | null => {
    const draft = stored[file]
    return draft && draft.owner === owner ? draft : null
  },
  /** Stores the text, or removes the draft when the text is the file it started from again. */
  put: (file: SettingsFileId, draft: Draft) => {
    const { [file]: _replaced, ...rest } = stored
    write(draft.text === draft.base.text ? rest : { ...rest, [file]: draft })
  },
  discard: (file: SettingsFileId) => {
    const { [file]: _discarded, ...rest } = stored
    write(rest)
  },
  subscribe: (listener: () => void) => {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  },
}

/** The files this user has unsaved text in. */
function ownedFiles(owner: string): SettingsFileId[] {
  return Object.entries(stored).flatMap(([file, draft]) => (isSettingsFileId(file) && draft.owner === owner ? [file] : []))
}

export function useDraft(file: SettingsFileId, owner: string): Draft | null {
  return useSyncExternalStore(drafts.subscribe, () => drafts.get(file, owner))
}

/** The files with unsaved text, as one string so the snapshot stays equal while nothing changes. */
export function useUnsavedFiles(owner: string): SettingsFileId[] {
  const joined = useSyncExternalStore(drafts.subscribe, () => ownedFiles(owner).join(','))
  return useMemo(() => joined.split(',').filter(isSettingsFileId), [joined])
}
