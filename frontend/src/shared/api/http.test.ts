import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { apiRequest, isApiError } from './http'
import { session } from './session'

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
const refused = () => json({ detail: 'Sign in first.' }, 401)
const sent = (fetch: ReturnType<typeof vi.fn>, call = 0) => (fetch.mock.calls[call] as unknown as [string, RequestInit])[1]

describe('the transport', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('sends the session cookie with every request, and the app header with every write only', async () => {
    const fetch = vi.fn(async () => json([]))
    vi.stubGlobal('fetch', fetch)

    await apiRequest('get', '/v1/watchlist')
    await apiRequest('post', '/v1/watchlist/manual', { body: { confirm: true, stock_ids: ['2330'] } })

    expect(sent(fetch, 0).credentials).toBe('same-origin')
    expect((sent(fetch, 0).headers as Record<string, string>)['X-Requested-With']).toBeUndefined()
    expect(sent(fetch, 1).credentials).toBe('same-origin')
    expect((sent(fetch, 1).headers as Record<string, string>)['X-Requested-With']).toBe('stock-agent')
    expect((sent(fetch, 1).headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('signs the tab out when the server ends the session it sent the request in', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => refused()))
    session.signIn(TEST_USER)

    const error = await apiRequest('get', '/v1/watchlist').catch((reason: unknown) => reason)

    expect(isApiError(error, 'unauthorized')).toBe(true)
    expect(session.current()).toEqual({ status: 'signedOut', ended: true })
  })

  it('keeps a session started while the refusal of an earlier one was on its way', async () => {
    let answer: (response: Response) => void = () => undefined
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => (answer = resolve))))
    session.signIn(TEST_USER)

    const request = apiRequest('get', '/v1/watchlist').catch((reason: unknown) => reason)
    session.signIn(TEST_ADMIN)
    answer(refused())

    expect(isApiError(await request, 'unauthorized')).toBe(true)
    expect(session.current()).toEqual({ status: 'signedIn', user: TEST_ADMIN })
  })

  it('stays signed in on a 403, which means not allowed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'Administrators only.' }, 403)))
    session.signIn(TEST_USER)

    const error = await apiRequest('get', '/v1/admin/users').catch((reason: unknown) => reason)

    expect(isApiError(error, 'forbidden')).toBe(true)
    expect(session.current()).toEqual({ status: 'signedIn', user: TEST_USER })
  })

  it('says how long to wait after too many attempts', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'Too many sign-in attempts.' }, 429, { 'Retry-After': '240' })))

    const error = await apiRequest('post', '/v1/auth/sign-in', { body: { identifier: 'mei', password: 'wrong' } }).catch((reason: unknown) => reason)

    expect(isApiError(error, 'rateLimited')).toBe(true)
    expect(isApiError(error) && error.retryAfter).toBe(240)
  })

  it('keeps a refusal’s whole body, with its detail as the message', async () => {
    const problems = [{ message: 'names no setting', file: 'appsetting', path: 'trading.order_mod', line: 207, column: 3 }]
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'The app would not start with these settings.', problems }, 422)))

    const error = await apiRequest('put', '/v1/admin/settings/{file}', { params: { file: 'appsetting' }, body: { confirm: true, revision: 'a'.repeat(64), text: '' } }).catch(
      (reason: unknown) => reason,
    )

    expect(isApiError(error, 'invalid') && error.message).toBe('The app would not start with these settings.')
    expect(isApiError(error) && error.body).toEqual({ detail: 'The app would not start with these settings.', problems })
  })

  it('names a refusal by its code, and a code this build does not know by none', async () => {
    const answers = [json({ detail: 'The password is wrong.', code: 'password_refused' }, 403), json({ detail: 'Refused.', code: 'a_code_from_later' }, 403)]
    vi.stubGlobal('fetch', vi.fn(async () => answers.shift()))
    const save = () =>
      apiRequest('put', '/v1/admin/settings/{file}', { params: { file: 'appsetting' }, body: { confirm: true, revision: 'a'.repeat(64), text: '', password: 'x' } }).catch(
        (reason: unknown) => reason,
      )

    const known = await save()
    const unknown = await save()

    expect(isApiError(known, 'forbidden') && known.code).toBe('password_refused')
    expect(isApiError(unknown, 'forbidden') && unknown.code).toBeNull()
  })

  it('answers a 204 with nothing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    await expect(apiRequest('post', '/v1/auth/sign-out')).resolves.toBeUndefined()
  })
})
