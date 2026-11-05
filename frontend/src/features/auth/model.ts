import type { Schemas, User } from '@/shared/api'

export type Role = Schemas['Role']
export type UserStatus = Schemas['UserStatus']

/**
 * The contract's account rules (openapi.json: Username, EmailAddress, NewPassword). The forms check them as the user
 * types so a mistake shows next to its field; the server checks them again. model.test.ts compares them with the
 * contract.
 */
export const USERNAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$/
export const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
export const PASSWORD_MIN_LENGTH = 12
export const PASSWORD_MAX_LENGTH = 256

export type AccountField = 'setupCode' | 'username' | 'email' | 'password' | 'confirm'
export type AccountProblem = 'required' | 'usernameFormat' | 'emailFormat' | 'passwordShort' | 'passwordLong' | 'mismatch' | 'taken' | 'wrongCode'
export type AccountProblems = Partial<Record<AccountField, AccountProblem>>

export interface AccountForm {
  setupCode: string
  username: string
  email: string
  password: string
  confirm: string
}

export const EMPTY_ACCOUNT_FORM: AccountForm = { setupCode: '', username: '', email: '', password: '', confirm: '' }

export function passwordProblem(password: string): AccountProblem | null {
  if (!password) return 'required'
  if (password.length < PASSWORD_MIN_LENGTH) return 'passwordShort'
  if (password.length > PASSWORD_MAX_LENGTH) return 'passwordLong'
  return null
}

/** What is wrong with a new account form; `needsCode` is the first-time setup, which also asks for the console's code. */
export function accountProblems(form: AccountForm, needsCode: boolean): AccountProblems {
  const problems: AccountProblems = {}
  const username = form.username.trim()
  const email = form.email.trim()
  if (needsCode && !form.setupCode.trim()) problems.setupCode = 'required'
  if (!username) problems.username = 'required'
  else if (!USERNAME_PATTERN.test(username)) problems.username = 'usernameFormat'
  if (!email) problems.email = 'required'
  else if (!EMAIL_PATTERN.test(email)) problems.email = 'emailFormat'
  const password = passwordProblem(form.password)
  if (password) problems.password = password
  if (!form.confirm) problems.confirm = 'required'
  else if (form.confirm !== form.password) problems.confirm = 'mismatch'
  return problems
}

/** The changes an administrator can make to an account from the users page. */
export type UserChange = { kind: 'role'; role: Role } | { kind: 'status'; status: UserStatus } | { kind: 'password' }

export interface UserChangeOption {
  change: UserChange
  /** An administrator never demotes or deactivates themselves, so the site keeps one who can sign in. */
  blocked: boolean
}

/** The menu of a user's row: the other role, the other status, and a new password. */
export function changeOptions(actorId: string, target: User): UserChangeOption[] {
  const isSelf = target.user_id === actorId
  return [
    { change: { kind: 'role', role: target.role === 'administrator' ? 'user' : 'administrator' }, blocked: isSelf && target.role === 'administrator' },
    { change: { kind: 'status', status: target.status === 'active' ? 'deactivated' : 'active' }, blocked: isSelf && target.status === 'active' },
    { change: { kind: 'password' }, blocked: false },
  ]
}

/** The key a change's menu item, confirmation and result read their words from. */
export function changeKey(change: UserChange): 'makeAdmin' | 'makeUser' | 'deactivate' | 'reactivate' | 'password' {
  switch (change.kind) {
    case 'role':
      return change.role === 'administrator' ? 'makeAdmin' : 'makeUser'
    case 'status':
      return change.status === 'deactivated' ? 'deactivate' : 'reactivate'
    case 'password':
      return 'password'
    default: {
      const exhaustive: never = change
      return exhaustive
    }
  }
}

/** The body the server takes for a change; a field left out stays as it is. */
export function changeBody(change: UserChange, password: string): Schemas['UserChangeRequest'] {
  switch (change.kind) {
    case 'role':
      return { confirm: true, role: change.role }
    case 'status':
      return { confirm: true, status: change.status }
    case 'password':
      return { confirm: true, password }
    default: {
      const exhaustive: never = change
      return exhaustive
    }
  }
}

const AUTH_PATHS = ['/setup', '/sign-in', '/register']

/** A path inside this site to return to after signing in; anything else, or an account page, falls back. */
export function safeNext(next: string | null, fallback: string): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return fallback
  return AUTH_PATHS.some((path) => next === path || next.startsWith(`${path}?`)) ? fallback : next
}
