import { apiRequest, isApiError } from './http'
import { session } from './session'

const refused = () => new Response(JSON.stringify({ detail: 'A valid bearer token is required.' }), { status: 401, headers: { 'Content-Type': 'application/json' } })

describe('a 401 from the server', () => {
  afterEach(() => {
    session.lock('owner')
    vi.unstubAllGlobals()
  })

  it('forgets the refused token and says it was refused', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => refused()))
    session.unlock('owner', 'wrong-token')

    const error = await apiRequest('get', '/v1/watchlist', { scope: 'owner' }).catch((reason: unknown) => reason)

    expect(isApiError(error, 'unauthorized')).toBe(true)
    expect(session.token('owner')).toBeNull()
    expect(session.snapshot().owner.reason).toBe('rejected')
  })

  it('keeps a token the user typed while the refusal of the old one was on its way', async () => {
    let answer: (response: Response) => void = () => undefined
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => (answer = resolve))))
    session.unlock('owner', 'old-token')

    const request = apiRequest('post', '/v1/watchlist/manual', { scope: 'owner', body: { confirm: true, stock_ids: ['2330'] } }).catch((reason: unknown) => reason)
    session.unlock('owner', 'new-token')
    answer(refused())

    expect(isApiError(await request, 'unauthorized')).toBe(true)
    expect(session.token('owner')).toBe('new-token')
  })

  it('sends the token of its own scope only', async () => {
    const fetch = vi.fn(async () => new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    session.unlock('owner', 'owner-token')

    await apiRequest('get', '/v1/market/most-traded')
    await apiRequest('get', '/v1/watchlist', { scope: 'owner' })

    const headers = fetch.mock.calls.map((call) => (call as unknown as [string, RequestInit])[1].headers as Record<string, string>)
    expect(headers[0]!.Authorization).toBeUndefined()
    expect(headers[1]!.Authorization).toBe('Bearer owner-token')
  })
})
