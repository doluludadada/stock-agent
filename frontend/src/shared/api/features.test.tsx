import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { siteShowing } from '@/test/features'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { shows, useShows } from './features'
import { session } from './session'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

describe('whom the site shows a feature to', () => {
  afterEach(() => {
    session.signOut()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('shows a feature for everyone to all, one for administrators to a user with the permission, and one that is off to nobody', () => {
    const visibilities = { ranking: 'everyone', watchlist: 'administrators', valuation: 'off' } as const
    const seen = (permissions: readonly (typeof TEST_ADMIN.permissions)[number][]) => (['ranking', 'watchlist', 'valuation'] as const).filter((feature) => shows(visibilities, permissions, feature))
    expect(seen([]), 'a visitor').toEqual(['ranking'])
    expect(seen(['manage_users', 'edit_system_settings']), 'another permission does not open it').toEqual(['ranking'])
    expect(seen(['see_administrator_features'])).toEqual(['ranking', 'watchlist'])
  })

  it('shows nothing until the server has said, and nothing the answer leaves out', () => {
    expect(shows(undefined, ['see_administrator_features'], 'ranking')).toBe(false)
    expect(shows({}, ['see_administrator_features'], 'ranking')).toBe(false)
  })

  it('reads the signed-in user’s permissions, and asks the server again once the tab is back in focus a minute later', async () => {
    let answer = siteShowing({ watchlist: 'administrators' })
    vi.stubGlobal('fetch', vi.fn(async () => json(answer)))
    vi.useFakeTimers({ shouldAdvanceTime: true })
    session.signIn(TEST_USER)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result } = renderHook(() => [useShows('watchlist'), useShows('ranking'), useShows(['watchlist', 'ranking'])], { wrapper })
    await waitFor(() => expect(result.current).toEqual([false, true, true]))

    act(() => session.signIn({ ...TEST_ADMIN, permissions: [...TEST_ADMIN.permissions, 'see_administrator_features'] }))
    expect(result.current).toEqual([true, true, true])

    answer = siteShowing({ watchlist: 'off', ranking: 'off' })
    await act(async () => {
      vi.advanceTimersByTime(61_000)
      focusManager.setFocused(false)
      focusManager.setFocused(true)
    })

    await waitFor(() => expect(result.current).toEqual([false, false, false]))
  })
})
