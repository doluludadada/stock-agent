import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { PERSONAL_SITE, PUBLIC_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { latestQuote, quotesPollMs, useLiveQuotes, useQuotesThenRefetch, type DailyBar, type PageQuotes, type StockQuote } from './market'
import { session } from './session'

const bar = (ts: string, close: number, change: number | null = 2): DailyBar => ({ ts, open: close, high: close, low: close, close, volume: 9_000, change })
const SETTLED: StockQuote = { close: 100, change: 1, changeRatio: 0.0101, session: '2026-11-13', tradedAt: null }
const REFRESH_SECONDS = 10
const RECHECK_SECONDS = 300

describe('the price a page shows', () => {
  it('stays the settled close when there is no quote, and when the close of the quote’s session is settled', () => {
    expect(latestQuote(SETTLED, undefined)).toBe(SETTLED)
    expect(latestQuote(SETTLED, null)).toBe(SETTLED)
    expect(latestQuote(SETTLED, bar('2026-11-13T13:30:00+08:00', 101))).toBe(SETTLED)
    expect(latestQuote(null, undefined)).toBeNull()
  })

  it('is today’s quote, with its last trade’s time and its change against the reference price, once that is a newer session', () => {
    const quoted = bar('2026-11-16T10:32:05+08:00', 104, 4)
    expect(latestQuote(SETTLED, quoted)).toEqual({ close: 104, change: 4, changeRatio: 0.04, session: '2026-11-16', tradedAt: quoted.ts })
    expect(latestQuote(null, quoted)?.tradedAt).toBe(quoted.ts)
  })
})

describe('when a tab asks for the quotes again', () => {
  const answerOf = (changing: boolean, realtime = true): PageQuotes => ({
    realtime_quotes: realtime,
    refresh: realtime ? { changing, seconds: changing ? REFRESH_SECONDS : RECHECK_SECONDS } : null,
    quotes: { '2330': changing ? bar('2026-11-16T10:32:05+08:00', 1_000) : null, '2317': null },
  })
  let asked: string[]
  let answer: PageQuotes
  let audience = PERSONAL_SITE

  function watch() {
    // Like the app's client, answers count as fresh for a while, which must not keep a tab back in view on an old price.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    return renderHook(() => useLiveQuotes(['2330', '2317', '2330']), { wrapper })
  }
  const quoteRequests = () => asked.filter((url) => url.includes('/v1/market/quotes'))
  const pass = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)))

  beforeEach(() => {
    asked = []
    answer = answerOf(true)
    audience = PERSONAL_SITE
    session.signIn(TEST_USER)
    focusManager.setFocused(true)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input)
      asked.push(url)
      return new Response(JSON.stringify(url.includes('/audience') ? audience : answer), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
  })

  afterEach(() => {
    session.signOut()
    focusManager.setFocused(undefined)
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('waits as long as the server answered, and sets no timer without an answer or on a site without quotes now', () => {
    expect(quotesPollMs(answerOf(true))).toBe(REFRESH_SECONDS * 1000)
    expect(quotesPollMs(answerOf(false))).toBe(RECHECK_SECONDS * 1000)
    expect(quotesPollMs(answerOf(false, false))).toBe(false)
    expect(quotesPollMs(undefined)).toBe(false)
  })

  it('names each stock once, asks again at the interval while the tab is visible, and gives the stocks that traded', async () => {
    const { result } = watch()
    await waitFor(() => expect(result.current.live).toBe(true))
    expect(quoteRequests()).toHaveLength(1)
    expect(new URL(quoteRequests()[0]!, 'http://site').searchParams.getAll('ids')).toEqual(['2317', '2330'])
    expect([...result.current.bars.keys()]).toEqual(['2330'])

    answer = { ...answer, quotes: { '2330': bar('2026-11-16T10:32:15+08:00', 1_005), '2317': null } }
    await pass(REFRESH_SECONDS * 1000 + 50)
    await waitFor(() => expect(result.current.bars.get('2330')?.close).toBe(1_005))
    expect(quoteRequests()).toHaveLength(2)
  })

  it('asks nothing while the tab is hidden and at once when it is back in view', async () => {
    const { result } = watch()
    await waitFor(() => expect(result.current.live).toBe(true))

    act(() => focusManager.setFocused(false))
    await pass(REFRESH_SECONDS * 1000 * 6)
    expect(quoteRequests()).toHaveLength(1)

    act(() => focusManager.setFocused(true))
    await waitFor(() => expect(quoteRequests()).toHaveLength(2))
  })

  it('looks again only after the server’s longer wait once the session is over', async () => {
    answer = answerOf(false)
    const { result } = watch()
    await waitFor(() => expect(quoteRequests()).toHaveLength(1))
    expect(result.current).toMatchObject({ live: false })
    expect(result.current.bars.size).toBe(0)

    await pass(REFRESH_SECONDS * 1000 * 6)
    expect(quoteRequests()).toHaveLength(1)
    await pass(RECHECK_SECONDS * 1000)
    await waitFor(() => expect(quoteRequests()).toHaveLength(2))
  })

  it('never asks for a visitor or on a site without realtime quotes', async () => {
    audience = PUBLIC_SITE
    const onPublicSite = watch()
    await waitFor(() => expect(asked.some((url) => url.includes('/audience'))).toBe(true))
    await pass(REFRESH_SECONDS * 1000 * 2)
    expect(onPublicSite.result.current).toMatchObject({ live: false })
    onPublicSite.unmount()

    audience = PERSONAL_SITE
    session.signOut()
    watch()
    await pass(REFRESH_SECONDS * 1000 * 2)
    expect(quoteRequests()).toHaveLength(0)
  })
})

describe('a page whose own answer the server values at the quotes', () => {
  const quotes = (ts: string): PageQuotes => ({ realtime_quotes: true, refresh: { changing: true, seconds: REFRESH_SECONDS }, quotes: { '2330': bar(ts, 1_000), '2317': null } })
  let answer: PageQuotes
  const pass = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)))

  beforeEach(() => {
    session.signIn(TEST_USER)
    focusManager.setFocused(true)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input)
      return new Response(JSON.stringify(url.includes('/audience') ? PERSONAL_SITE : answer), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
  })

  afterEach(() => {
    session.signOut()
    focusManager.setFocused(undefined)
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('asks its own endpoint again when a held stock has a newer trade, and not while the quotes stay the same', async () => {
    answer = quotes('2026-11-16T10:32:05+08:00')
    const refetch = vi.fn()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    renderHook(() => useQuotesThenRefetch(['2330', '2317'], refetch), { wrapper })
    await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1))

    await pass(REFRESH_SECONDS * 1000 + 50)
    expect(refetch).toHaveBeenCalledTimes(1)

    answer = quotes('2026-11-16T10:32:25+08:00')
    await pass(REFRESH_SECONDS * 1000 + 50)
    await waitFor(() => expect(refetch).toHaveBeenCalledTimes(2))
  })
})
