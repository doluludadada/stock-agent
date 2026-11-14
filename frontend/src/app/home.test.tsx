import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { ThemeProvider } from '@/shared/lib/theme'
import { TooltipProvider } from '@/shared/ui/tooltip'
import { PERSONAL_SITE, PUBLIC_SITE } from '@/test/audiences'
import { OPEN_SITE, siteShowing } from '@/test/features'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { routes } from './router/router'

const BALANCED = builtInJson('balanced')
const ADMINISTRATOR = { ...TEST_ADMIN, permissions: [...TEST_ADMIN.permissions, 'see_administrator_features' as const] }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The whole app at `path`, for a signed-in user with no run yet or for a visitor, on the owner's site or a public one. */
function renderApp(path: string, viewer: 'user' | 'visitor' | 'administrator', site = PERSONAL_SITE, status = OPEN_SITE) {
  const fetch = vi.fn(async (url: string) => {
    if (url === '/v1/auth/status') return json(status)
    if (url === '/v1/auth/me') return viewer === 'visitor' ? json({ detail: 'Sign in first.', code: 'unauthorized' }, 401) : json(viewer === 'user' ? TEST_USER : ADMINISTRATOR)
    if (url === '/v1/market/audience') return json(site)
    if (url === '/v1/market/archive-status') return json({ sessions: 3, needed: 61 })
    if (url.startsWith('/v1/runs?')) return json([])
    if (url === '/v1/technical-settings/built-in-strategies') return json([BALANCED])
    if (url === '/v1/technical-settings') return json({ active_strategy_id: 'balanced', strategies: [BALANCED, { ...BALANCED, strategy_id: 'stg_1', name: 'Mine' }], revision: 1 })
    return json({ detail: 'Not Found', code: 'not_found' }, 404)
  })
  vi.stubGlobal('fetch', fetch)
  if (viewer === 'visitor') session.signOut()
  else session.signIn(viewer === 'user' ? TEST_USER : ADMINISTRATOR)
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const view = render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ThemeProvider>
          <TooltipProvider>
            <RouterProvider router={router} />
          </TooltipProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </I18nextProvider>,
  )
  return { router, fetch, unmount: view.unmount }
}

const texts = (elements: HTMLElement[]) => elements.map((element) => element.textContent)
const asked = (fetch: ReturnType<typeof renderApp>['fetch'], prefix: string) => fetch.mock.calls.map(([url]) => url).filter((url) => url.startsWith(prefix))

const TOOLS = ['Analysis runs', 'Mock account', 'Valuation', 'Strategy library', 'Backtest', 'Formula designer']
const CARDS = ['TAIEX', "This month's ranking", 'My holdings', 'Watchlist']
/** The home page's cards by their titles, in reading order. */
const cards = () =>
  within(screen.getByRole('main'))
    .getAllByRole('region')
    .map((card) => within(card).getByRole('heading', { level: 2 }).textContent)

describe('the home page', { timeout: 20_000 }, () => {
  beforeEach(() => {
    vi.stubGlobal('scrollTo', () => undefined)
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  })
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    window.localStorage.clear()
  })

  it('is Today, first in the navigation and in the phone’s tab bar, with a card for each feature that leads to its page', async () => {
    renderApp('/', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'Today' })).toBeInTheDocument()
    const main = screen.getByRole('main')
    await waitFor(() => expect(cards()).toEqual(CARDS))
    const ways = { TAIEX: ['Market overview', '/market'], "This month's ranking": ['All 20 and the backtest', '/ranking'], 'My holdings': ['Every holding', '/holdings'], Watchlist: ['The whole list', '/watchlist'] }
    for (const [card, [name, to]] of Object.entries(ways)) expect(within(within(main).getByRole('region', { name: card })).getByRole('link', { name })).toHaveAttribute('href', to)
    expect(within(main).queryByRole('link', { name: 'Sign in' }), 'a signed-in reader is asked nothing').not.toBeInTheDocument()

    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(texts(within(nav).getAllByText(/^(Today|Research|Mine|Supporting analysis tools)$/)), 'the home page stands alone, under no heading').toEqual(['Today', 'Research', 'Mine', 'Supporting analysis tools'])
    expect(texts(within(nav).getAllByRole('link'))).toEqual(['Today', 'Revenue ranking', 'Market overview', 'My holdings', 'Watchlist', 'My settings'])
    expect(within(nav).getByRole('link', { name: 'Today' })).toHaveAttribute('aria-current', 'page')
    const tabs = screen.getByRole('navigation', { name: 'Main pages' })
    expect(texts(within(tabs).getAllByRole('link'))).toEqual(['Today', 'Ranking', 'Holdings'])
    expect(within(tabs).getByRole('link', { name: 'Today' })).toHaveAttribute('aria-current', 'page')
  })

  it('shows a visitor the public card and one invitation to sign in, in place of the cards that need an account', async () => {
    const { fetch } = renderApp('/', 'visitor')

    expect(await screen.findByRole('heading', { level: 1, name: 'Today' })).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(await within(main).findByRole('region', { name: 'TAIEX' })).toBeInTheDocument()
    expect(cards()).toEqual(['TAIEX'])
    expect(within(main).getAllByRole('link', { name: 'Sign in' }), 'one invitation, not one per private card').toHaveLength(1)
    expect(within(main).getByRole('link', { name: 'Sign in' }), 'signing in comes back home').toHaveAttribute('href', '/sign-in')
    expect(within(main).getAllByText(/^Sign in to /)).toHaveLength(1)
    const holds = within(within(main).getByText('Your account keeps').parentElement!).getAllByRole('listitem')
    expect(holds).toHaveLength(3)
    for (const [index, name] of ['Revenue ranking', 'My holdings', 'Watchlist'].entries()) expect(within(holds[index]!).getByText(name)).toBeInTheDocument()
    for (const owned of ['/v1/ranking', '/v1/holdings', '/v1/watchlist']) expect(asked(fetch, owned), owned).toEqual([])
  })

  it.each([
    ['/', 'Today'],
    ['/ranking', 'Monthly revenue ranking'],
    ['/market', 'Market overview'],
    ['/holdings', 'My holdings'],
  ])('names the browser tab on %s after the page', async (path, title) => {
    renderApp(path, 'user')

    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument()
    expect(document.title).toBe(`${title} · Stock Agent`)
  })

  it('moves the focus to the page’s content after a navigation, and leaves it alone on the first page', async () => {
    renderApp('/', 'user')
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Today' })).toBeInTheDocument()
    expect(document.activeElement).not.toBe(screen.getByRole('main'))

    fireEvent.click(within(nav).getByRole('link', { name: 'Market overview' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Market overview' })).toBeInTheDocument()
    expect(document.activeElement).toBe(screen.getByRole('main'))
  })

  it('keeps the other tools in a section that opens on a click and stays as the reader left it', async () => {
    const first = renderApp('/', 'user')
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    const section = within(nav).getByRole('button', { name: 'Supporting analysis tools' })
    expect(section).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(section)

    expect(section).toHaveAttribute('aria-expanded', 'true')
    expect(texts(within(nav).getAllByRole('link')).slice(6)).toEqual(TOOLS)

    first.unmount()
    renderApp('/', 'user')
    const again = await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(within(again).getByRole('button', { name: 'Supporting analysis tools' }), 'the browser remembers').toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(within(again).getByRole('button', { name: 'Supporting analysis tools' }))
    expect(within(again).queryByRole('link', { name: 'Backtest' })).not.toBeInTheDocument()
  })

  it('opens and closes the section for the visit when the browser refuses storage', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage is blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage is blocked')
    })
    renderApp('/', 'user')
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })

    fireEvent.click(within(nav).getByRole('button', { name: 'Supporting analysis tools' }))

    expect(within(nav).getByRole('link', { name: 'Strategy library' })).toBeInTheDocument()
  })

  it.each(['/runs', '/strategies', '/strategies/stg_1/edit', '/backtest', '/strategies/new'])(
    'shows the section open on %s, one of its pages, and marks that page alone',
    async (path) => {
      renderApp(path, 'user')

      const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
      const section = within(nav).getByRole('button', { name: 'Supporting analysis tools' })
      expect(section).toHaveAttribute('aria-expanded', 'true')
      expect(section, 'it cannot close over the page the reader is on').toBeDisabled()
      expect(within(nav).getAllByRole('link', { current: 'page' })).toHaveLength(1)
    },
  )

  it.each(['/account', '/valuation'])('shows the section open on %s too, the tools that moved in beside the technical strategies', async (path) => {
    renderApp(path, 'user')

    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(await within(nav).findByRole('button', { name: 'Supporting analysis tools' })).toBeDisabled()
    await waitFor(() => expect(texts(within(nav).getAllByRole('link', { current: 'page' }))).toEqual([path === '/account' ? 'Mock account' : 'Valuation']))
  })

  it('opens the market overview at its own address, with the research target a link named', async () => {
    const { router, fetch } = renderApp('/market?target=2330', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'Market overview' })).toBeInTheDocument()
    expect([router.state.location.pathname, router.state.location.search]).toEqual(['/market', '?target=2330'])
    expect(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name: 'Market overview' })).toHaveAttribute('aria-current', 'page')
    expect(within(screen.getByRole('navigation', { name: 'Main pages' })).queryByRole('link', { current: 'page' }), 'the overview is in the sheet of all pages').not.toBeInTheDocument()
    expect(asked(fetch, '/v1/technical-settings'), 'the overview carries no strategy card').toEqual([])
  })

  it('keeps the analysis runs at their own address, which the tab bar reaches through its more button', async () => {
    renderApp('/runs', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'Analysis runs' })).toBeInTheDocument()
    expect(await screen.findAllByRole('button', { name: 'Start' }), 'one per analysis kind').toHaveLength(4)
    const tabs = screen.getByRole('navigation', { name: 'Main pages' })
    expect(within(tabs).queryByRole('link', { current: 'page' })).not.toBeInTheDocument()
    fireEvent.click(within(tabs).getByRole('button', { name: 'More' }))
    const sheet = await screen.findByRole('dialog', { name: 'All pages' })
    expect(within(sheet).getByRole('link', { name: 'Analysis runs' })).toHaveAttribute('aria-current', 'page')
  })

  it('folds the other tools in the phone’s sheet of all pages too, one tap from each', async () => {
    renderApp('/', 'user')
    fireEvent.click(within(await screen.findByRole('navigation', { name: 'Main pages' })).getByRole('button', { name: 'More' }))
    const sheet = await screen.findByRole('dialog', { name: 'All pages' })
    expect(texts(within(sheet).getAllByRole('link')), 'the watchlist and the market, which the tab bar leaves out').toEqual(['Today', 'Revenue ranking', 'Market overview', 'My holdings', 'Watchlist', 'My settings'])

    fireEvent.click(within(sheet).getByRole('button', { name: 'Supporting analysis tools' }))

    expect(texts(within(sheet).getAllByRole('link')).slice(6)).toEqual(TOOLS)
  })

  it('marks the analysis runs in the sidebar on a run’s own page', async () => {
    renderApp('/runs/r1', 'user')

    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(await within(nav).findByRole('link', { name: 'Analysis runs' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Market overview' })).not.toHaveAttribute('aria-current')
  })

  it('tells a visitor what the analyses do, with sign-in, registration and the market overview a click away', async () => {
    renderApp('/runs', 'visitor')

    expect(await screen.findByRole('heading', { level: 1, name: 'Analysis runs' })).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(await within(main).findByText('Full Cycle'), 'once the server said what the site offers').toBeInTheDocument()
    for (const kind of ['Full Cycle', 'Specific stocks', 'Social Buzz', 'Intraday']) expect(within(main).getByText(kind)).toBeInTheDocument()
    expect(within(main).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in?next=%2Fruns')
    expect(within(main).getByRole('link', { name: 'Create account' })).toHaveAttribute('href', '/register')
    expect(within(main).getByRole('link', { name: 'Market overview' })).toHaveAttribute('href', '/market')
    expect(within(main).queryByRole('button', { name: 'Start' })).not.toBeInTheDocument()
  })

  it('credits the open data and says nothing here is advice under every page', async () => {
    renderApp('/', 'visitor')

    const footer = await screen.findByRole('contentinfo')
    expect(within(footer).getByRole('link', { name: 'Data sources and license' })).toHaveAttribute('href', '/attribution')
    expect(within(footer).getByText(/not investment advice/)).toBeInTheDocument()
  })

  it('offers on a public site neither the valuation nor a workflow that needs realtime quotes, and says how far its data has come', async () => {
    renderApp('/runs', 'user', PUBLIC_SITE)

    expect(await screen.findAllByRole('button', { name: 'Start' }), 'Full Cycle and specific stocks').toHaveLength(2)
    const main = screen.getByRole('main')
    for (const kind of ['Social Buzz', 'Intraday']) expect(within(main).queryByText(kind)).not.toBeInTheDocument()
    expect(within(main).getByText('Two workflows; one of yours runs at a time')).toBeInTheDocument()
    expect((await within(main).findByRole('region', { name: 'Open-data archive' })).textContent).toContain('Data accumulating 3/61')
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(texts(within(nav).getAllByRole('link'))).toEqual(['Today', 'Revenue ranking', 'Market overview', 'My holdings', 'Watchlist', 'My settings', ...TOOLS.filter((tool) => tool !== 'Valuation')])
  })

  it('says why a public site has no valuation when a link opens it, and asks the server for none', async () => {
    const { fetch } = renderApp('/valuation', 'user', PUBLIC_SITE)

    expect(await screen.findByRole('heading', { level: 1, name: 'This site offers no valuation' })).toBeInTheDocument()
    expect(screen.getByText(/no MOPS income statements/)).toBeInTheDocument()
    expect(asked(fetch, '/v1/valuation')).toEqual([])
  })

  it('opens the valuation on the owner’s site', async () => {
    renderApp('/valuation', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'P/E valuation' })).toBeInTheDocument()
  })

  it('hides a page the administrator turned off from the navigation, the tab bar and its own address', async () => {
    const { fetch } = renderApp('/watchlist', 'user', PERSONAL_SITE, siteShowing({ watchlist: 'off', ranking: 'administrators' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'This page does not exist' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to the home page' })).toHaveAttribute('href', '/')
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(texts(within(nav).getAllByRole('link'))).toEqual(['Today', 'Market overview', 'My holdings', 'My settings'])
    expect(texts(within(screen.getByRole('navigation', { name: 'Main pages' })).getAllByRole('link'))).toEqual(['Today', 'Holdings'])
    expect(asked(fetch, '/v1/watchlist')).toEqual([])
  })

  it('shows a feature kept for administrators to an administrator, and to nobody else', async () => {
    const status = siteShowing({ ranking: 'administrators' })
    const first = renderApp('/', 'administrator', PERSONAL_SITE, status)
    expect(await within(await screen.findByRole('navigation', { name: 'Main navigation' })).findByRole('link', { name: 'Revenue ranking' })).toBeInTheDocument()
    expect(await within(screen.getByRole('main')).findByRole('region', { name: "This month's ranking" })).toBeInTheDocument()
    first.unmount()

    renderApp('/ranking', 'visitor', PERSONAL_SITE, status)
    expect(await screen.findByRole('heading', { level: 1, name: 'This page does not exist' })).toBeInTheDocument()
  })

  it('keeps the home page whatever the site hides, without the card of a hidden feature or a request for it', async () => {
    const { router, fetch } = renderApp('/', 'user', PERSONAL_SITE, siteShowing({ market_overview: 'off', ranking: 'off' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Today' })).toBeInTheDocument()
    await waitFor(() => expect(cards()).toEqual(['My holdings', 'Watchlist']))
    expect(router.state.location.pathname).toBe('/')
    for (const hidden of ['/v1/market/indexes', '/v1/market/breadth', '/v1/ranking']) expect(asked(fetch, hidden), hidden).toEqual([])
    expect(asked(fetch, '/v1/holdings'), 'a card that shows does ask').not.toEqual([])
  })

  it('has no market overview at its address on a site that hides it, and the home page stays', async () => {
    renderApp('/market', 'user', PERSONAL_SITE, siteShowing({ market_overview: 'off' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'This page does not exist' })).toBeInTheDocument()
    expect(texts(within(screen.getByRole('navigation', { name: 'Main navigation' })).getAllByRole('link')).slice(0, 2)).toEqual(['Today', 'Revenue ranking'])
  })

  it('has no stock search and no stock page on a site that hides stock pages', async () => {
    renderApp('/stocks/2330', 'user', PERSONAL_SITE, siteShowing({ stock_pages: 'off' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'This page does not exist' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Search stocks' })).not.toBeInTheDocument()
    expect(texts(within(screen.getByRole('navigation', { name: 'Main pages' })).getAllByRole('button'))).toEqual(['More'])
  })

  it('offers only the analyses the site shows, and no runs page once all four are off', async () => {
    const first = renderApp('/runs', 'user', PERSONAL_SITE, siteShowing({ buzz: 'off', full_cycle: 'off' }))
    expect(await screen.findAllByRole('button', { name: 'Start' })).toHaveLength(2)
    const main = screen.getByRole('main')
    for (const kind of ['Social Buzz', 'Full Cycle']) expect(within(main).queryByText(kind)).not.toBeInTheDocument()
    for (const kind of ['Specific stocks', 'Intraday']) expect(within(main).getByText(kind)).toBeInTheDocument()
    expect(within(main).getByText('One of yours runs at a time')).toBeInTheDocument()
    first.unmount()

    renderApp('/runs', 'user', PERSONAL_SITE, siteShowing({ buzz: 'off', full_cycle: 'off', specific_stock: 'off', intraday: 'off' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'This page does not exist' })).toBeInTheDocument()
  })
})
