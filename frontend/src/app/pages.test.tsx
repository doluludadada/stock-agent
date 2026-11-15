import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { ApiError, useAuthStatus } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { FEATURES, siteShowing } from '@/test/features'
import { TEST_ADMIN } from '@/test/users'
import { listedPageAt, navSections, type Viewer } from './layouts/navigation'
import { FEATURES_WITHOUT_PAGE, pageEntries, PAGES } from './pages'
import { createQueryClient } from './providers/query-client'

const pageFeatures = pageEntries.flatMap(([, page]) => page.features)
const keys = (viewer: Viewer) => navSections(viewer).flatMap((section) => section.items.map((item) => item.key))
const viewer = (hidden: Parameters<typeof siteShowing>[0], permissions: Viewer['permissions'] = []): Viewer => ({ permissions, audience: PERSONAL_SITE, visibilities: siteShowing(hidden).features })

describe('the pages and the features they belong to', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('names every feature of the contract at a page, so none can be hidden in the settings and still show', () => {
    const named = new Set<string>([...pageFeatures, ...FEATURES_WITHOUT_PAGE])
    expect(FEATURES.filter((feature) => !named.has(feature))).toEqual([])
  })

  it('opens no page for a feature that has none: ordering on SinoPac alone shows neither account', () => {
    const paged = new Set<string>(pageFeatures)
    expect(FEATURES_WITHOUT_PAGE.filter((feature) => paged.has(feature))).toEqual([])
    const orderingOnly = viewer({ mock_account: 'off', sinopac_account: 'off' }, ['use_real_broker'])
    expect(keys(orderingOnly)).not.toContain('account')
    expect(keys(orderingOnly)).not.toContain('brokerage')
  })

  it('lists the SinoPac account only for a viewer who may hold the real broker and sees its feature', () => {
    expect(keys(viewer({}))).not.toContain('brokerage')
    expect(keys(viewer({}, ['use_real_broker']))).toContain('brokerage')
    expect(keys(viewer({ sinopac_account: 'administrators' }, ['use_real_broker']))).not.toContain('brokerage')
    expect(keys(viewer({ sinopac_account: 'administrators' }, ['use_real_broker', 'see_administrator_features']))).toContain('brokerage')
    expect(keys(viewer({ sinopac_ordering: 'off' }, ['use_real_broker'])), 'reading the account does not need ordering').toContain('brokerage')
  })

  it('lists a page in the navigation only for a viewer the site shows one of its features to', () => {
    expect(keys(viewer({}))).toEqual(['home', 'ranking', 'overview', 'world', 'holdings', 'watchlist', 'settings', 'runs', 'account', 'valuation', 'strategies', 'backtest', 'builder'])
    expect(keys(viewer({ ranking: 'off', watchlist: 'administrators', strategy_designer: 'off' }))).toEqual(['home', 'overview', 'world', 'holdings', 'settings', 'runs', 'account', 'valuation', 'strategies', 'backtest'])
    expect(keys(viewer({ watchlist: 'administrators' }, ['see_administrator_features']))).toContain('watchlist')
    expect(keys({ ...viewer({}), visibilities: undefined }), 'nothing that names a feature until the server has said').toEqual(['home', 'settings'])
  })

  it('keeps a page of several features while any one of them shows, and drops a section left empty', () => {
    expect(keys(viewer({ mock_account: 'off' }))).not.toContain('account')
    expect(keys(viewer({ full_cycle: 'off', specific_stock: 'off', buzz: 'off' }))).toContain('runs')
    const withoutTools = viewer({ full_cycle: 'off', specific_stock: 'off', buzz: 'off', intraday: 'off', mock_account: 'off', valuation: 'off', strategy_library: 'off', strategy_backtest: 'off', strategy_designer: 'off' })
    expect(navSections(withoutTools).map((section) => section.key)).toEqual(['today', 'research', 'mine'])
  })

  it('always has the home page, which belongs to no feature, first', () => {
    const everythingOff = viewer(Object.fromEntries(FEATURES.map((feature) => [feature, 'off'])))
    expect(keys(everythingOff)).toEqual(['home', 'settings'])
    expect(navSections(viewer({}))[0]).toMatchObject({ key: 'today', items: [{ key: 'home', to: '/' }] })
  })

  it('gives the administrator’s pages no feature, so no setting can lock the administrator out of the settings', () => {
    const everythingOff = viewer(Object.fromEntries(FEATURES.map((feature) => [feature, 'off'])), TEST_ADMIN.permissions)
    expect(keys(everythingOff)).toEqual(['home', 'settings', 'users', 'admin'])
    expect(navSections(everythingOff).flatMap((section) => section.items).flatMap((item) => PAGES[item.key].features)).toEqual([])
  })

  it('marks one listed page for every address: its own, or the page it sits under', () => {
    expect(listedPageAt('/')).toBe('home')
    expect(listedPageAt('/account')).toBe('account')
    expect(listedPageAt('/account/sinopac'), 'the SinoPac account sits under the mock account’s address and marks its own entry').toBe('brokerage')
    expect(listedPageAt('/stocks/2330')).toBe('overview')
    expect(listedPageAt('/runs/abc')).toBe('runs')
    expect(listedPageAt('/strategies')).toBe('strategies')
    expect(listedPageAt('/strategies/new')).toBe('builder')
    expect(listedPageAt('/strategies/mine/edit')).toBe('builder')
    expect(listedPageAt('/no-such-page')).toBeNull()
    const listed = new Set(navSections(viewer({}, TEST_ADMIN.permissions)).flatMap((section) => section.items.map((item) => item.key as string)))
    expect(pageEntries.filter(([, page]) => page.under !== undefined && !listed.has(page.under)).map(([key]) => key)).toEqual([])
  })

  it('lists the tab bar’s and the account menu’s pages from the same table', () => {
    const items = navSections(viewer({}, TEST_ADMIN.permissions)).flatMap((section) => section.items)
    expect(items.filter((item) => item.tab).map((item) => item.key)).toEqual(['home', 'ranking', 'holdings'])
    expect(items.filter((item) => item.menu).map((item) => [item.key, item.to])).toEqual([
      ['settings', '/settings'],
      ['users', '/admin/users'],
      ['admin', '/admin/settings'],
    ])
    expect(navSections(viewer({})).flatMap((section) => section.items).filter((item) => item.menu).map((item) => item.key), 'a user without the permissions').toEqual(['settings'])
  })

  it('asks the server what shows now when a request is refused because its feature was hidden', async () => {
    let asked = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        asked += 1
        return new Response(JSON.stringify(siteShowing()), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }),
    )
    const client = createQueryClient()
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const refused = new ApiError('forbidden', 403, 'Hidden.', [], null, { detail: 'Hidden.', code: 'feature_hidden' })
    const { result, rerender } = renderHook(
      ({ failing }: { failing: boolean }) => {
        const status = useAuthStatus()
        useQuery({ queryKey: ['owner', 'watchlist'], queryFn: () => Promise.reject(refused), enabled: failing })
        return status
      },
      { wrapper, initialProps: { failing: false } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(asked).toBe(1)

    rerender({ failing: true })

    await waitFor(() => expect(asked).toBe(2))
  })
})
