import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { TEST_USER } from '@/test/users'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/**
 * The app as it starts: the session is not known yet, and the probe asks GET /v1/auth/me, which answers with `answers`
 * in turn and repeats the last. `seen` is every session state the app showed after the start.
 */
async function start(answers: (() => Response)[]) {
  vi.resetModules()
  const { session } = await import('@/shared/api')
  const { useSessionProbe } = await import('./api')
  let asked = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      const answer = answers[Math.min(asked, answers.length - 1)]!
      asked += 1
      return answer()
    }),
  )
  const seen: string[] = []
  session.subscribe(() => seen.push(session.current().status))
  function Probe() {
    useSessionProbe()
    return null
  }
  expect(session.current().status).toBe('checking')
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } })}>
      <Probe />
    </QueryClientProvider>,
  )
  return { session, seen, asked: () => asked }
}

describe('finding out who is signed in when the app starts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks again after a server error and ends signed in, without ever showing signed out', async () => {
    const app = await start([() => json({ detail: 'boom' }, 500), () => json(TEST_USER)])

    await waitFor(() => expect(app.session.current()).toEqual({ status: 'signedIn', user: TEST_USER }))
    expect(app.seen).toEqual(['signedIn'])
  })

  it('takes a 401 as signed out at once, without asking again', async () => {
    const app = await start([() => json({ detail: 'Sign in first.', code: 'sign_in_required' }, 401)])

    await waitFor(() => expect(app.session.current()).toEqual({ status: 'signedOut', ended: false }))
    expect(app.asked()).toBe(1)
  })

  it('counts as signed out once the server failed every try', async () => {
    const app = await start([() => json({ detail: 'boom' }, 500)])

    await waitFor(() => expect(app.session.current()).toEqual({ status: 'signedOut', ended: false }))
    expect(app.asked()).toBe(3)
  })
})
