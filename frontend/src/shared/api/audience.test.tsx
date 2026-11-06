import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { PERSONAL_SITE } from '@/test/audiences'
import { useAllows } from './audience'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

describe('what the site allows', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('asks the server again once the tab is back in focus a while later, since a login can go down or come back without a restart', async () => {
    let answer = PERSONAL_SITE
    vi.stubGlobal('fetch', vi.fn(async () => json(answer)))
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result } = renderHook(() => useAllows('realtime_quotes'), { wrapper })
    await waitFor(() => expect(result.current).toBe(true))

    answer = { ...PERSONAL_SITE, realtime_quotes: false }
    await act(async () => {
      vi.advanceTimersByTime(61_000)
      focusManager.setFocused(false)
      focusManager.setFocused(true)
    })

    await waitFor(() => expect(result.current).toBe(false))
  })
})
