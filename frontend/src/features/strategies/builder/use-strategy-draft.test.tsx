import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { session, useSession } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { newIds, strategyFromApi } from '../api/mapping'
import { builtInJson } from '../model/built-ins.test-support'
import { blankComparison } from '../model/edit'
import type { IndicatorId } from '../model/types'
import { errorsOf } from '../model/validate'
import { resolveDraftSource, useStrategyDraft } from './use-strategy-draft'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The server's settings; `answer` holds back the next save's reply until the test lets it through. */
function fakeServer() {
  const server = { revision: 1, strategies: [builtInJson('balanced'), { ...builtInJson('balanced'), strategy_id: 'stg_other', name: 'Other' }], answer: Promise.resolve() }
  const settings = () => ({ active_strategy_id: 'balanced', strategies: server.strategies, revision: server.revision })
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

type Draft = ReturnType<typeof useStrategyDraft>

/** The designer's draft of the built-in Balanced at `address`, shown only while someone is signed in, as its page is. */
function openDesigner(name: string, address = '/strategies/new') {
  const draft: { current: Draft | null } = { current: null }
  const capture = (value: Draft | null) => (draft.current = value)
  function Probe() {
    const value = useStrategyDraft(strategyFromApi(builtInJson('balanced')), name)
    capture(value)
    useEffect(() => () => void capture(null), [])
    return null
  }
  function Page() {
    return useSession().status === 'signedIn' ? <Probe /> : <p>Sign in</p>
  }
  const router = createMemoryRouter([{ path: '/strategies/new', element: <Page /> }, { path: '*', element: <p>Elsewhere</p> }], { initialEntries: [address] })
  const view = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { draft, router, view }
}

describe('leaving the designer with unsaved edits', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('asks first when only the query string changes, as it does for another page', async () => {
    vi.stubGlobal('fetch', fakeServer().fetch)
    session.signIn(TEST_USER)
    const { draft, router } = openDesigner('query-only', '/strategies/new?builtin=balanced')
    await waitFor(() => expect(draft.current?.revision).toBe(1))
    act(() => draft.current!.edit({ type: 'setName', name: 'Mine' }))

    await act(() => router.navigate('/strategies/new'))

    expect(draft.current!.blocker.state).toBe('blocked')
    expect(router.state.location.search).toBe('?builtin=balanced')

    await act(async () => draft.current!.blocker.proceed?.())
    expect(router.state.location.search).toBe('')
  })

  it('lets the page go right after a save, before it renders again, and asks again on the next edit', async () => {
    vi.stubGlobal('fetch', fakeServer().fetch)
    session.signIn(TEST_USER)
    const { draft, router } = openDesigner('saved', '/strategies/new?builtin=balanced')
    await waitFor(() => expect(draft.current?.revision).toBe(1))
    act(() => draft.current!.edit({ type: 'setName', name: 'Mine' }))

    await act(async () => {
      expect(await draft.current!.save()).toMatchObject({ ok: true })
      await router.navigate('/strategies/new')
    })
    expect(router.state.location.search, 'the save’s own navigation, as to the edit page').toBe('')

    act(() => draft.current!.edit({ type: 'setName', name: 'Mine again' }))
    await act(() => router.navigate('/strategies/new?builtin=balanced'))
    expect(draft.current!.blocker.state).toBe('blocked')
  })

  it('lets a navigation through when nothing was edited', async () => {
    vi.stubGlobal('fetch', fakeServer().fetch)
    session.signIn(TEST_USER)
    const { draft, router } = openDesigner('untouched', '/strategies/new?builtin=balanced')
    await waitFor(() => expect(draft.current?.revision).toBe(1))

    await act(() => router.navigate('/strategies/new'))

    expect(router.state.location.search).toBe('')
  })
})

describe('an unsaved draft when the session ends', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('comes back, still unsaved, when the same user signs in again', async () => {
    vi.stubGlobal('fetch', fakeServer().fetch)
    session.signIn(TEST_USER)
    const { draft } = openDesigner('same-user')
    await waitFor(() => expect(draft.current?.revision).toBe(1))
    act(() => draft.current!.edit({ type: 'setName', name: 'Half done' }))

    act(() => session.expire(session.generation()))
    expect(await screen.findByText('Sign in')).toBeInTheDocument()
    expect(draft.current).toBeNull()

    act(() => session.signIn(TEST_USER))
    await waitFor(() => expect(draft.current?.draft.name).toBe('Half done'))
    expect(draft.current!.dirty).toBe(true)
  })

  it('is not handed to another user who signs in next', async () => {
    vi.stubGlobal('fetch', fakeServer().fetch)
    session.signIn(TEST_USER)
    const { draft } = openDesigner('other-user')
    await waitFor(() => expect(draft.current?.revision).toBe(1))
    act(() => draft.current!.edit({ type: 'setName', name: 'Half done' }))

    act(() => session.signOut())
    expect(await screen.findByText('Sign in')).toBeInTheDocument()

    act(() => session.signIn(TEST_ADMIN))
    await waitFor(() => expect(draft.current).not.toBeNull())
    expect(draft.current!.draft.name).toBe(builtInJson('balanced').name)
    expect(draft.current!.dirty).toBe(false)
  })

  it('is dropped when the page is left while signed in', async () => {
    vi.stubGlobal('fetch', fakeServer().fetch)
    session.signIn(TEST_USER)
    const first = openDesigner('left-signed-in')
    await waitFor(() => expect(first.draft.current?.revision).toBe(1))
    act(() => first.draft.current!.edit({ type: 'setName', name: 'Half done' }))
    first.view.unmount()

    const again = openDesigner('left-signed-in')
    await waitFor(() => expect(again.draft.current?.revision).toBe(1))
    expect(again.draft.current!.draft.name).toBe(builtInJson('balanced').name)
    expect(again.draft.current!.dirty).toBe(false)
  })
})

describe('an indicator the editor made that no condition reads any more', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('does not hold the save back with a value no field shows', async () => {
    const { server, fetch } = fakeServer()
    vi.stubGlobal('fetch', fetch)
    session.signIn(TEST_USER)
    const { draft } = openDesigner('orphan-indicator')
    await waitFor(() => expect(draft.current?.revision).toBe(1))

    const added = blankComparison(newIds())
    const [indicatorId] = Object.keys(added.indicators) as IndicatorId[]
    act(() => draft.current!.edit({ type: 'addCondition', groupId: draft.current!.draft.rules[0]!.condition.id, ...added }))
    act(() => draft.current!.edit({ type: 'setIndicatorParam', indicatorId: indicatorId!, key: 'period', value: 0 }))
    expect(errorsOf(draft.current!.issues)).not.toEqual([])

    act(() => draft.current!.edit({ type: 'removeCondition', conditionId: added.condition.id }))
    expect(errorsOf(draft.current!.issues)).toEqual([])

    await act(async () => {
      expect(await draft.current!.save()).toMatchObject({ ok: true })
    })
    expect(server.strategies[0]!.indicators).not.toHaveProperty(indicatorId!)
  })
})

describe('saving a strategy draft', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('keeps what was typed during the save, and a later conflict over another strategy does not say this one changed', async () => {
    const { server, fetch } = fakeServer()
    vi.stubGlobal('fetch', fetch)
    session.signIn(TEST_USER)
    const draft: { current: ReturnType<typeof useStrategyDraft> | null } = { current: null }
    const capture = (value: ReturnType<typeof useStrategyDraft>) => (draft.current = value)
    function Probe() {
      capture(useStrategyDraft(strategyFromApi(builtInJson('balanced')), 'edit::balanced'))
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

describe('a new strategy on a site reached over plain http at a host name', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('starts with its ids, though the browser gives such a page no crypto.randomUUID', () => {
    const { getRandomValues } = globalThis.crypto
    vi.stubGlobal('crypto', { getRandomValues: getRandomValues.bind(globalThis.crypto) })
    const labels = { copyName: () => 'Copy', ruleName: (_strategyId: string, name: string) => name }

    const blank = resolveDraftSource({ type: 'blank' }, [], [], labels)
    const copy = resolveDraftSource({ type: 'copy', source: 'builtIn', id: 'balanced' }, [], [strategyFromApi(builtInJson('balanced'))], labels)

    expect(blank).toMatchObject({ status: 'ready', isNew: true, strategy: { id: expect.stringMatching(/^stg_[0-9a-f]+$/) } })
    expect(copy).toMatchObject({ status: 'ready', isNew: true, strategy: { id: expect.stringMatching(/^stg_[0-9a-f]+$/) } })
  })
})
