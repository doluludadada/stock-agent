import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { session } from '@/shared/api'
import { strategyFromApi } from '../api/mapping'
import { builtInJson } from '../model/built-ins.test-support'
import { useStrategyDraft } from './use-strategy-draft'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The server's settings; `answer` holds back the next save's reply until the test lets it through. */
function fakeServer() {
  const server = { revision: 1, strategies: [builtInJson('balanced'), builtInJson('aggressive')], answer: Promise.resolve() }
  const settings = () => ({ active_strategy_id: 'balanced', buzz_strategy_id: 'balanced', strategies: server.strategies, revision: server.revision })
  const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method !== 'PUT') return json(settings())
    const body = JSON.parse(String(init.body)) as { settings: { revision: number; strategies: typeof server.strategies } }
    await server.answer
    if (body.settings.revision !== server.revision) return json({ detail: 'stale' }, 409)
    server.strategies = body.settings.strategies
    server.revision += 1
    return json(settings())
  })
  return { server, fetch }
}

describe('saving a strategy draft', () => {
  afterEach(() => {
    session.lock('owner')
    vi.unstubAllGlobals()
  })

  it('keeps what was typed during the save, and a later conflict over another strategy does not say this one changed', async () => {
    const { server, fetch } = fakeServer()
    vi.stubGlobal('fetch', fetch)
    session.unlock('owner', 'owner-token')
    const draft: { current: ReturnType<typeof useStrategyDraft> | null } = { current: null }
    const capture = (value: ReturnType<typeof useStrategyDraft>) => (draft.current = value)
    function Probe() {
      capture(useStrategyDraft(strategyFromApi(builtInJson('balanced'))))
      return null
    }
    const router = createMemoryRouter([{ path: '/', element: <Probe /> }])
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(draft.current?.revision).toBe(1))

    let answer = () => {}
    server.answer = new Promise((resolve) => (answer = resolve))
    act(() => draft.current!.edit({ type: 'setName', name: 'Balanced v2' }))
    let saved!: Promise<unknown>
    act(() => {
      saved = draft.current!.save()
    })
    act(() => draft.current!.edit({ type: 'setName', name: 'Balanced v3' }))
    answer()
    await act(() => saved)

    expect(draft.current!.draft.name).toBe('Balanced v3')
    expect(draft.current!.dirty).toBe(true)

    server.strategies = [server.strategies[0]!, { ...server.strategies[1]!, name: 'Changed elsewhere' }]
    server.revision += 1
    await act(async () => {
      expect(await draft.current!.save()).toEqual({ ok: false, reason: 'conflict' })
    })

    expect(draft.current!.conflict).toBe(true)
    expect(draft.current!.serverChanged).toBe(false)
  })
})
