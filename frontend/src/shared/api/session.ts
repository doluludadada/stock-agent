import { useSyncExternalStore } from 'react'
import type { components } from './schema.gen'

type Schemas = components['schemas']
export type User = Schemas['User']
export type Permission = Schemas['Permission']

/**
 * Who is signed in, in this tab. The server keeps the session in an HttpOnly cookie the page cannot read, so this
 * mirrors what the server last said: `checking` until GET /v1/auth/me answers, then signed in or out. `ended` says a
 * 401 ended the session this tab held: it expired, the user was deactivated or got a new password, or signed out
 * in another tab.
 */
export type Session = { status: 'checking' } | { status: 'signedOut'; ended: boolean } | { status: 'signedIn'; user: User }

let current: Session = { status: 'checking' }
/** Counts the sessions this tab has known, so the refusal of an earlier one never ends a later one. */
let generation = 0
const listeners = new Set<() => void>()

function update(next: Session, newGeneration: boolean) {
  current = next
  if (newGeneration) generation += 1
  listeners.forEach((listener) => listener())
}

export const session = {
  current: (): Session => current,
  generation: (): number => generation,
  /** The server answered with this user; the same user again only refreshes the details, such as a changed role. */
  signIn: (user: User) => update({ status: 'signedIn', user }, current.status !== 'signedIn' || current.user.user_id !== user.user_id),
  signOut: () => update({ status: 'signedOut', ended: false }, true),
  /** A request sent during session `sentIn` answered 401: that session is over, unless another began since. */
  expire: (sentIn: number) => {
    if (sentIn === generation && current.status === 'signedIn') update({ status: 'signedOut', ended: true }, true)
  },
  subscribe: (listener: () => void) => {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  },
}

export function hasPermission(state: Session, permission: Permission): boolean {
  return state.status === 'signedIn' && state.user.permissions.includes(permission)
}

export function useSession(): Session {
  return useSyncExternalStore(session.subscribe, session.current)
}

/** Private data is read only while someone is signed in, so a visitor's page sends no request it knows will fail. */
export function useIsSignedIn(): boolean {
  return useSession().status === 'signedIn'
}

export function useHasPermission(permission: Permission): boolean {
  return hasPermission(useSession(), permission)
}
