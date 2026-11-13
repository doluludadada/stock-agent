import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { StrategyLibraryPage } from './StrategyLibraryPage'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

const BUILT_INS = [builtInJson('balanced')]
/** The copy a first read saved while the app shipped an Aggressive built-in, which it no longer does. */
const RETIRED = { ...builtInJson('balanced'), strategy_id: 'aggressive', name: 'Aggressive' }
const MINE = { ...builtInJson('balanced'), strategy_id: 'stg_mine', name: 'Mine' }

/** The library of a user who has the first read's copies, one of a built-in that no longer ships, and one strategy of their own. */
async function renderLibrary(active: string) {
  const saved: unknown[] = []
  const settings = { active_strategy_id: active, strategies: [...BUILT_INS, RETIRED, MINE], revision: 1 }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/v1/market/audience') return json(PERSONAL_SITE)
      if (url === '/v1/technical-settings/built-in-strategies') return json(BUILT_INS)
      if (url === '/v1/technical-settings' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { settings: typeof settings }
        saved.push(body.settings)
        return json({ ...body.settings, revision: 2 })
      }
      if (url === '/v1/technical-settings') return json(settings)
      return json([])
    }),
  )
  session.signIn(TEST_USER)
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <StrategyLibraryPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
  await screen.findByRole('radiogroup', { name: 'Strategy in use' })
  return saved
}

describe('the strategy library', { timeout: 20_000 }, () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('offers the one built-in, and lists the user’s own strategies below, a copy of a built-in that no longer ships among them', async () => {
    await renderLibrary('balanced')

    const choice = screen.getByRole('radiogroup', { name: 'Strategy in use' })
    expect(within(choice).getAllByRole('radio').map((option) => option.textContent)).toEqual(['Balanced'])
    expect(within(choice).getByRole('radio', { name: 'Balanced' })).toHaveAttribute('aria-checked', 'true')
    const mine = screen.getByRole('list')
    expect(within(mine).getAllByRole('listitem').map((row) => row.getAttribute('aria-label'))).toEqual(['Aggressive', 'Mine'])
    expect(screen.queryByText(/Social Buzz/)).not.toBeInTheDocument()
    fireEvent.pointerDown(screen.getByRole('button', { name: 'New strategy' }), { button: 0, ctrlKey: false })
    expect((await screen.findAllByRole('menuitem')).map((item) => item.textContent)).toEqual(['Blank strategy', 'Copy Balanced'])
  })

  it('keeps a copy of a built-in that no longer ships in use until the user picks another strategy', async () => {
    const saved = await renderLibrary('aggressive')

    const choice = screen.getByRole('radiogroup', { name: 'Strategy in use' })
    expect(within(choice).queryByRole('radio', { checked: true })).toBeNull()
    expect(screen.getByText('Every workflow uses your strategy “Aggressive”.')).toBeInTheDocument()
    expect(within(screen.getByRole('listitem', { name: 'Aggressive' })).getByText('In use')).toBeInTheDocument()
    expect(saved).toEqual([])

    fireEvent.click(within(choice).getByRole('radio', { name: 'Balanced' }))

    await waitFor(() => expect(saved).toEqual([expect.objectContaining({ active_strategy_id: 'balanced', revision: 1 })]))
  })

  it('says which of the user’s own strategies is in use, and offers each one to use, edit, duplicate or delete', async () => {
    await renderLibrary('stg_mine')

    expect(within(screen.getByRole('radiogroup', { name: 'Strategy in use' })).queryByRole('radio', { checked: true })).toBeNull()
    expect(screen.getByText('Every workflow uses your strategy “Mine”.')).toBeInTheDocument()
    const row = screen.getByRole('listitem', { name: 'Mine' })
    expect(within(row).getByText('In use')).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Use' })).not.toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/strategies/stg_mine/edit')
    expect(within(row).getByRole('link', { name: 'Copy Mine' })).toHaveAttribute('href', '/strategies/new?from=stg_mine')
    expect(within(row).getByRole('button', { name: /^Delete Mine: / })).toBeDisabled()
  })
})
