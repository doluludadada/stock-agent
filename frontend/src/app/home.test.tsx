import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { ThemeProvider } from '@/shared/lib/theme'
import { TooltipProvider } from '@/shared/ui/tooltip'
import { TEST_USER } from '@/test/users'
import { routes } from './router/router'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The whole app at `path`, for a signed-in user with no run yet or for a visitor. */
function renderApp(path: string, viewer: 'user' | 'visitor') {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/v1/auth/status') return json({ needs_first_administrator: false, registration_open: true })
      if (url === '/v1/auth/me') return viewer === 'user' ? json(TEST_USER) : json({ detail: 'Sign in first.', code: 'unauthorized' }, 401)
      if (url.startsWith('/v1/runs?')) return json([])
      return json({ detail: 'Not Found', code: 'not_found' }, 404)
    }),
  )
  if (viewer === 'user') session.signIn(TEST_USER)
  else session.signOut()
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
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
  return router
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
  })

  it('is the analysis runs, first in the navigation and in the phone’s tab bar', async () => {
    renderApp('/', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'Analysis runs' })).toBeInTheDocument()
    expect(await screen.findAllByRole('button', { name: 'Start' }), 'one per analysis kind').toHaveLength(4)
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(texts(within(nav).getAllByText(/^(Analysis|Research|Mine)$/))).toEqual(['Analysis', 'Research', 'Mine'])
    expect(texts(within(nav).getAllByRole('link'))).toEqual(['Analysis runs', 'Strategy library', 'Formula designer', 'Market overview', 'Valuation', 'Watchlist', 'Mock account', 'My settings'])
    const tabs = screen.getByRole('navigation', { name: 'Main pages' })
    expect(texts(within(tabs).getAllByRole('link'))).toEqual(['Analysis', 'Market', 'Watchlist', 'Account'])
    expect(within(tabs).getByRole('link', { name: 'Analysis' })).toHaveAttribute('aria-current', 'page')
  })

  it('takes an old link to the runs page there', async () => {
    const router = renderApp('/runs', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'Analysis runs' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/')
  })

  it('moves the market overview to its own address, where the market tab holds it', async () => {
    renderApp('/market', 'user')

    expect(await screen.findByRole('heading', { level: 1, name: 'Market overview' })).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: 'Main pages' })).getByRole('link', { name: 'Market' })).toHaveAttribute('aria-current', 'page')
  })

  it('marks the analysis runs in the sidebar and the tab bar on a run’s own page', async () => {
    renderApp('/runs/r1', 'user')

    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(await within(nav).findByRole('link', { name: 'Analysis runs' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Market overview' })).not.toHaveAttribute('aria-current')
    expect(within(screen.getByRole('navigation', { name: 'Main pages' })).getByRole('link', { name: 'Analysis' })).toHaveAttribute('aria-current', 'page')
  })

  it('tells a visitor what the analyses do, with sign-in, registration and the market overview a click away', async () => {
    renderApp('/', 'visitor')

    expect(await screen.findByRole('heading', { level: 1, name: 'Analysis runs' })).toBeInTheDocument()
    const main = screen.getByRole('main')
    for (const kind of ['Full Cycle', 'Specific stocks', 'Social Buzz', 'Intraday']) expect(within(main).getByText(kind)).toBeInTheDocument()
    expect(within(main).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in')
    expect(within(main).getByRole('link', { name: 'Create account' })).toHaveAttribute('href', '/register')
    expect(within(main).getByRole('link', { name: 'Market overview' })).toHaveAttribute('href', '/market')
    expect(within(main).queryByRole('button', { name: 'Start' })).not.toBeInTheDocument()
  })
})
