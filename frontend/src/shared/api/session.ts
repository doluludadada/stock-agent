import { useSyncExternalStore } from 'react'

/**
 * The bearer tokens this tab holds, in memory only: never in storage, the URL or the bundle, so a reload asks again.
 * `owner` is API_TOKEN, `admin` is ADMIN_API_TOKEN; the server checks every request, this only carries them.
 */
export type Scope = 'owner' | 'admin'

export type LockReason = 'locked' | 'rejected'

interface ScopeState {
  token: string | null
  reason: LockReason
}

const state: Record<Scope, ScopeState> = {
  owner: { token: null, reason: 'locked' },
  admin: { token: null, reason: 'locked' },
}
const listeners = new Set<() => void>()
let snapshot = { owner: state.owner, admin: state.admin }

function update(scope: Scope, next: ScopeState) {
  state[scope] = next
  snapshot = { owner: state.owner, admin: state.admin }
  listeners.forEach((listener) => listener())
}

export const session = {
  token: (scope: Scope) => state[scope].token,
  unlock: (scope: Scope, token: string) => update(scope, { token: token.trim(), reason: 'locked' }),
  lock: (scope: Scope) => update(scope, { token: null, reason: 'locked' }),
  /**
   * The server refused `token` (401): forget it so the next request does not repeat it. An answer that arrives after
   * the user typed another token refers to the old one and leaves the new one alone.
   */
  reject: (scope: Scope, token: string) => {
    if (state[scope].token === token) update(scope, { token: null, reason: 'rejected' })
  },
  subscribe: (listener: () => void) => {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  },
  snapshot: () => snapshot,
}

export function useSession(scope: Scope) {
  const current = useSyncExternalStore(session.subscribe, session.snapshot)[scope]
  return { unlocked: current.token !== null, reason: current.reason }
}
