import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { ThemeProvider } from '@/shared/lib/theme'
import { TooltipProvider } from '@/shared/ui/tooltip'
import { PERSONAL_SITE, PUBLIC_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { routes } from './router/router'

const BALANCED = builtInJson('balanced')
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The whole app at `path`, for a signed-in user with no run yet or for a visitor, on the owner's site or a public one. */
function renderApp(path: string, viewer: 'user' | 'visitor', site = PERSONAL_SITE) {
  const fetch = vi.fn(async (url: string) => {
    if (url === '/v1/auth/status') return json({ needs_first_administrator: false, registration_open: true })
    if (url === '/v1/auth/me') return viewer === 'user' ? json(TEST_USER) : json({ detail: 'Sign in first.', code: 'unauthorized' }, 401)
    if (url === '/v1/market/audience') return json(site)
    if (url === '/v1/market/archive-status') return json({ sessions: 3, needed: 61 })
    if (url.startsWith('/v1/runs?')) return json([])
    if (url === '/v1/technical-settings/built-in-strategies') return json([BALANCED])
    if (url === '/v1/technical-settings') return json({ active_strategy_id: 'balanced', strategies: [BALANCED, { ...BALANCED, strategy_id: 'stg_1', name: 'Mine' }], revision: 1 })
    return json({ detail: 'Not Found', code: 'not_found' }, 404)
  })
  vi.stubGlobal('fetch', fetch)
  if (viewer === 'user') session.signIn(TEST_USER)
  else session.signOut()
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

  it('is the market overview, after the ranking in the navigation and in the phone’s tab bar', async () => {
    renderApp('/', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'Market overview' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(texts(within(nav).getAllByText(/^(Research|Mine|Technical strategies)$/))).toEqual(['Research', 'Mine', 'Technical strategies'])
    expect(texts(within(nav).getAllByRole('link'))).toEqual(['Revenue ranking', 'Market overview', 'Valuation', 'Watchlist', 'Mock account', 'My settings'])
    const tabs = screen.getByRole('navigation', { name: 'Main pages' })
    expect(texts(within(tabs).getAllByRole('link'))).toEqual(['Ranking', 'Market', 'Watchlist', 'Account'])
    expect(within(tabs).getByRole('link', { name: 'Market' })).toHaveAttribute('aria-current', 'page')
  })

  it('keeps the technical-strategy pages in a section that opens on a click and stays as the reader left it', async () => {
    const first = renderApp('/', 'user')
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    const section = within(nav).getByRole('button', { name: 'Technical strategies' })
    expect(section).toHaveAttribute('aria-expanded', 'false')
    expect(within(nav).queryByText(/did not profit/)).not.toBeInTheDocument()

    fireEvent.click(section)

    expect(section).toHaveAttribute('aria-expanded', 'true')
    expect(within(nav).getByText('Did not profit in a backtest. Every page is kept.')).toBeInTheDocument()
    expect(texts(within(nav).getAllByRole('link')).slice(6)).toEqual(['Analysis runs', 'Strategy library', 'Backtest', 'Formula designer'])

    first.unmount()
    renderApp('/', 'user')
    const again = await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(within(again).getByRole('button', { name: 'Technical strategies' }), 'the browser remembers').toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(within(again).getByRole('button', { name: 'Technical strategies' }))
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

    fireEvent.click(within(nav).getByRole('button', { name: 'Technical strategies' }))

    expect(within(nav).getByRole('link', { name: 'Strategy library' })).toBeInTheDocument()
  })

  it.each(['/runs', '/strategies', '/strategies/stg_1/edit', '/backtest', '/strategies/new'])(
    'shows the section open on %s, one of its pages, which says where the app’s attention moved',
    async (path) => {
      renderApp(path, 'user')

      const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
      const section = within(nav).getByRole('button', { name: 'Technical strategies' })
      expect(section).toHaveAttribute('aria-expanded', 'true')
      expect(section, 'it cannot close over the page the reader is on').toBeDisabled()
      expect(within(nav).getAllByRole('link', { current: 'page' })).toHaveLength(1)
      const note = await within(screen.getByRole('main')).findByText(/The built-in technical strategies did not profit in a backtest/)
      expect(within(note).getByRole('link', { name: 'Open the ranking' })).toHaveAttribute('href', '/ranking')
    },
  )

  it('takes an old link to the market overview home, with the research target it named', async () => {
    const { router } = renderApp('/market?target=2330', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'Market overview' })).toBeInTheDocument()
    expect([router.state.location.pathname, router.state.location.search]).toEqual(['/', '?target=2330'])
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

  it('folds the technical-strategy pages in the phone’s sheet of all pages too, one tap from each', async () => {
    renderApp('/', 'user')
    fireEvent.click(within(await screen.findByRole('navigation', { name: 'Main pages' })).getByRole('button', { name: 'More' }))
    const sheet = await screen.findByRole('dialog', { name: 'All pages' })
    expect(texts(within(sheet).getAllByRole('link'))).toEqual(['Revenue ranking', 'Market overview', 'Valuation', 'Watchlist', 'Mock account', 'My settings'])

    fireEvent.click(within(sheet).getByRole('button', { name: 'Technical strategies' }))

    expect(texts(within(sheet).getAllByRole('link')).slice(6)).toEqual(['Analysis runs', 'Strategy library', 'Backtest', 'Formula designer'])
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
    expect(within(main).getByRole('link', { name: 'Market overview' })).toHaveAttribute('href', '/')
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
    expect(texts(within(nav).getAllByRole('link'))).toEqual(['Revenue ranking', 'Market overview', 'Watchlist', 'Mock account', 'My settings', 'Analysis runs', 'Strategy library', 'Backtest', 'Formula designer'])
  })

  it('says why a public site has no valuation when a link opens it, and asks the server for none', async () => {
    const { fetch } = renderApp('/valuation', 'user', PUBLIC_SITE)

    expect(await screen.findByRole('heading', { level: 1, name: 'This site offers no valuation' })).toBeInTheDocument()
    expect(screen.getByText(/no MOPS income statements/)).toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => url).filter((url) => url.startsWith('/v1/valuation'))).toEqual([])
  })

  it('opens the valuation on the owner’s site', async () => {
    renderApp('/valuation', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'P/E valuation' })).toBeInTheDocument()
  })
})
