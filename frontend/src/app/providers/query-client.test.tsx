import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { useChooseAiModel } from '@/features/auth/api'
import { session, useSaveSettings } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { createQueryClient, scopeCacheToSession } from './query-client'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

/** A server whose one answer waits until the test lets it go. */
function heldAnswer(body: unknown) {
  let release = () => {}
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  vi.stubGlobal('fetch', vi.fn(async () => held.then(() => json(body))))
  return release
}

const wrapperOf = (client: QueryClient) => ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>

describe('the cache and the session', () => {
  let client: QueryClient
  let stop: () => void

  beforeEach(() => {
    session.signIn(TEST_ADMIN)
    client = createQueryClient()
    stop = scopeCacheToSession(client)
  })

  afterEach(() => {
    stop()
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('drops the private queries and every mutation when another user holds the tab, and keeps the public ones', async () => {
    client.setQueryData(['owner', 'watchlist'], ['2330'])
    client.setQueryData(['admin', 'users'], [TEST_ADMIN])
    client.setQueryData(['public', 'audience'], { audience: 'personal' })
    const release = heldAnswer([])
    const { result } = renderHook(() => useSaveSettings(), { wrapper: wrapperOf(client) })
    act(() => result.current.mutate({ changes: [], password: 'x' }))
    await waitFor(() => expect(client.getMutationCache().getAll()).toHaveLength(1))

    act(() => session.signIn(TEST_USER))

    expect(client.getQueryData(['owner', 'watchlist'])).toBeUndefined()
    expect(client.getQueryData(['admin', 'users'])).toBeUndefined()
    expect(client.getQueryData(['public', 'audience'])).toEqual({ audience: 'personal' })
    expect(client.getMutationCache().getAll()).toEqual([])
    release()
  })

  it('keeps a settings save that answers after another user signed in out of that user’s cache', async () => {
    const release = heldAnswer([{ path: 'ai.temperature' }])
    const { result } = renderHook(() => useSaveSettings(), { wrapper: wrapperOf(client) })
    const saving = act(() => result.current.mutateAsync({ changes: [], password: 'x' }).catch(() => undefined))

    act(() => session.signIn(TEST_USER))
    release()
    await saving

    expect(client.getQueryData(['admin', 'settings', 'form'])).toBeUndefined()
  })

  it('keeps a late AI model answer out of the next user’s cache, and writes one that answers in its own session', async () => {
    const answer = { in_use: 'claude', site_default: 'claude', models: { claude: 'Claude' } }
    let release = heldAnswer(answer)
    const { result } = renderHook(() => useChooseAiModel(), { wrapper: wrapperOf(client) })
    let saving = act(() => result.current.mutateAsync('claude').catch(() => undefined))
    act(() => session.signIn(TEST_USER))
    release()
    await saving
    expect(client.getQueryData(['owner', 'settings', 'ai-model'])).toBeUndefined()

    release = heldAnswer(answer)
    saving = act(() => result.current.mutateAsync('claude'))
    release()
    await saving
    await waitFor(() => expect(client.getQueryData(['owner', 'settings', 'ai-model'])).toEqual(answer))
  })
})
