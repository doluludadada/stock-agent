import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within, waitFor } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type Audience } from '@/shared/api'
import { PERSONAL_SITE, PUBLIC_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import type { WatchlistEntry } from './api'
import { WatchlistPage } from './WatchlistPage'

const ENTRY: WatchlistEntry = { stock_id: '2330', name: '台積電', watchlist_type: 'manual', created_at: '2026-11-01T00:00:00Z', expires_at: null }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function open(audience: Audience) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/v1/market/audience') return json(audience)
      if (url === '/v1/watchlist') return json([ENTRY])
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  session.signIn(TEST_USER)
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <WatchlistPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

const filters = async () => within(await screen.findByRole('radiogroup', { name: 'Source' })).getAllByRole('radio').map((radio) => radio.textContent)

describe('the watchlist’s sources', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('offer Social buzz where the site runs Buzz scans', async () => {
    open(PERSONAL_SITE)
    await waitFor(async () => expect((await filters()).some((label) => label?.startsWith('Social buzz'))).toBe(true))
  })

  it('leave Social buzz out of the filter on a public site, which runs none', async () => {
    open(PUBLIC_SITE)
    expect(await filters()).toEqual(expect.arrayContaining([expect.stringMatching(/^Manual/), expect.stringMatching(/^Technical/)]))
    expect((await filters()).some((label) => label?.startsWith('Social buzz'))).toBe(false)
  })
})
