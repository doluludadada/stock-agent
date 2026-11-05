import openapi from '@/shared/api/openapi.json'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { accountProblems, changeBody, changeKey, changeOptions, EMAIL_PATTERN, EMPTY_ACCOUNT_FORM, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, safeNext, USERNAME_PATTERN } from './model'

const schemas = openapi.components.schemas

describe('the account rules', () => {
  it('are the contract’s', () => {
    expect(USERNAME_PATTERN.source).toBe(schemas.Username.pattern)
    expect(EMAIL_PATTERN.source).toBe(schemas.EmailAddress.pattern)
    expect(PASSWORD_MIN_LENGTH).toBe(schemas.NewPassword.minLength)
    expect(PASSWORD_MAX_LENGTH).toBe(schemas.NewPassword.maxLength)
  })

  it('name every problem of a new account under its field, the setup code only for the first-time setup', () => {
    const form = { ...EMPTY_ACCOUNT_FORM, username: '.mei', email: 'mei@', password: 'short', confirm: 'other' }
    expect(accountProblems(form, true)).toEqual({ setupCode: 'required', username: 'usernameFormat', email: 'emailFormat', password: 'passwordShort', confirm: 'mismatch' })
    expect(accountProblems({ ...form, username: 'mei.lin', email: 'mei@example.com', password: 'twelve chars', confirm: 'twelve chars' }, false)).toEqual({})
  })
})

describe('the changes an administrator can make', () => {
  it('never demote or deactivate the administrator themselves, but another administrator yes', () => {
    const own = changeOptions(TEST_ADMIN.user_id, TEST_ADMIN)
    expect(own.map((option) => [changeKey(option.change), option.blocked])).toEqual([
      ['makeUser', true],
      ['deactivate', true],
      ['password', false],
    ])
    const other = changeOptions(TEST_ADMIN.user_id, { ...TEST_ADMIN, user_id: 'u-kai' })
    expect(other.every((option) => !option.blocked)).toBe(true)
  })

  it('offer the other role and status of a user, and send only what changes', () => {
    const options = changeOptions(TEST_ADMIN.user_id, { ...TEST_USER, status: 'deactivated' })
    expect(options.map((option) => changeKey(option.change))).toEqual(['makeAdmin', 'reactivate', 'password'])
    expect(changeBody(options[0]!.change, '')).toEqual({ confirm: true, role: 'administrator' })
    expect(changeBody(options[1]!.change, '')).toEqual({ confirm: true, status: 'active' })
    expect(changeBody(options[2]!.change, 'a new password')).toEqual({ confirm: true, password: 'a new password' })
  })
})

describe('the page to return to after signing in', () => {
  it('stays on this site and never returns to an account page', () => {
    expect(safeNext('/watchlist?sort=code', '/')).toBe('/watchlist?sort=code')
    expect(safeNext('//evil.example/x', '/')).toBe('/')
    expect(safeNext('/\\evil.example', '/')).toBe('/')
    expect(safeNext('https://evil.example', '/')).toBe('/')
    expect(safeNext('/sign-in?next=%2F', '/')).toBe('/')
    expect(safeNext(null, '/')).toBe('/')
  })
})
