import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { useWatchlistChange, watchlistKeys, type WatchlistEntry } from './api'

const manual = (stockId: string): WatchlistEntry => ({ stock_id: stockId, name: null, watchlist_type: 'manual', created_at: '2026-11-01T00:00:00Z', expires_at: null })

describe('adding to the manual watchlist', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('shows a stock already on the manual list once while the server answers', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))
    session.signIn(TEST_USER)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData<WatchlistEntry[]>(watchlistKeys.all, [manual('2330')])
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const change = renderHook(() => useWatchlistChange(), { wrapper })

    act(() => change.result.current.mutate({ action: 'add', stockIds: ['2330', '2317'] }))

    await waitFor(() => expect(client.getQueryData<WatchlistEntry[]>(watchlistKeys.all)?.map((entry) => entry.stock_id)).toEqual(['2330', '2317']))
  })

  it("rolls back only the refused click and keeps the other click's change", async () => {
    const answers: ((response: Response) => void)[] = []
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => answers.push(resolve))))
    session.signIn(TEST_USER)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData<WatchlistEntry[]>(watchlistKeys.all, [manual('2330')])
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const first = renderHook(() => useWatchlistChange(), { wrapper })
    const second = renderHook(() => useWatchlistChange(), { wrapper })
    const shown = () => client.getQueryData<WatchlistEntry[]>(watchlistKeys.all)?.map((entry) => entry.stock_id)

    act(() => first.result.current.mutate({ action: 'add', stockIds: ['2317'] }))
    await waitFor(() => expect(answers).toHaveLength(1))
    act(() => second.result.current.mutate({ action: 'remove', stockIds: ['2330'] }))
    await waitFor(() => expect(answers).toHaveLength(2))
    expect(shown()).toEqual(['2317'])

    answers[0]!(new Response(JSON.stringify({ detail: 'refused' }), { status: 500, headers: { 'Content-Type': 'application/json' } }))

    await waitFor(() => expect(first.result.current.isError).toBe(true))
    expect(shown()).toEqual([])
  })
})
