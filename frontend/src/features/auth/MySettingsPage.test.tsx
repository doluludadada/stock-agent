import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { MockAccountPanel } from '@/features/account'
import { initI18n } from '@/i18n'
import { session, type Schemas } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { MySettingsPage } from './MySettingsPage'

type Offer = Schemas['AiModelResponse']

const OFFER: Offer = { models: { claude: 'claude-haiku-5-5', openai: 'gpt-5.5-mini' }, site_default: 'claude', in_use: 'claude' }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The server's My settings: it answers the offer and keeps each save it accepts, as the backend does. */
function serve(offer: Offer) {
  const saves: unknown[] = []
  let current = offer
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url !== '/v1/auth/me/ai-model') return json({ detail: 'Not found.', code: 'not_found' }, 404)
      if (init?.method !== 'PUT') return json(current)
      const body = JSON.parse(String(init.body)) as Schemas['AiModelRequest']
      saves.push(body)
      current = { ...current, in_use: body.ai_model ?? current.site_default }
      return json(current)
    }),
  )
  return saves
}

function open() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <MySettingsPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('My settings', () => {
  beforeAll(() => {
    Element.prototype.scrollIntoView = () => undefined
    Element.prototype.hasPointerCapture = () => false
    Element.prototype.releasePointerCapture = () => undefined
  })
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('offers the site’s models with its default marked, and saves a pick at once', async () => {
    const saves = serve(OFFER)
    const user = userEvent.setup()
    open()

    const select = await screen.findByRole('combobox', { name: 'Model for your runs' })
    expect(select).toHaveTextContent('Claude · claude-haiku-5-5 (site default)')
    await user.click(select)
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual(['Claude · claude-haiku-5-5 (site default)', 'OpenAI · gpt-5.5-mini'])
    await user.click(screen.getByRole('option', { name: 'OpenAI · gpt-5.5-mini' }))

    expect(await screen.findByText('Saved. Your next runs use OpenAI · gpt-5.5-mini.')).toBeVisible()
    expect(select).toHaveTextContent('OpenAI · gpt-5.5-mini')
    expect(saves).toEqual([{ confirm: true, ai_model: 'openai' }])
  })

  it('saves the site’s default as no choice, so the user follows the administrator’s later changes', async () => {
    const saves = serve({ ...OFFER, in_use: 'openai' })
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('combobox', { name: 'Model for your runs' }))
    await user.click(screen.getByRole('option', { name: 'Claude · claude-haiku-5-5 (site default)' }))

    await waitFor(() => expect(saves).toEqual([{ confirm: true, ai_model: null }]))
    expect(await screen.findByText('Saved. Your next runs use Claude · claude-haiku-5-5.')).toBeVisible()
  })

  it('says the active strategy is chosen in the strategy library, with a link there', async () => {
    serve(OFFER)
    open()

    expect(await screen.findByText(/The active strategy is chosen in the strategy library/)).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open the strategy library' })).toHaveAttribute('href', '/strategies')
  })
})

type History = Schemas['AccountHistoryResponse']

const OPENED = { initial_cash: 1_000_000, opened_at: '2026-11-04T01:00:00Z' }
const history = (opening: History['opening']): History => ({
  current: { cash: 1_000_000, market_value: 0, unrealized_pnl: 0, equity: 1_000_000, positions: [] },
  live_stock_ids: [],
  equity_curve: {},
  as_of: null,
  execution_provider: 'mock',
  opening,
  profit: opening ? 0 : null,
})

/** The mock account as the backend keeps it: a reset it accepts opens the account again with the amount. */
function serveAccount(opening: History['opening'], refusal?: { status: number; detail: string; code: string }) {
  const resets: unknown[] = []
  let current = opening
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/v1/auth/me/ai-model') return json(OFFER)
      if (url === '/v1/account/history?broker=mock') return json(history(current))
      if (url === '/v1/account/reset' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Schemas['ResetRequest']
        resets.push(body)
        if (refusal) return json({ detail: refusal.detail, code: refusal.code }, refusal.status)
        current = { initial_cash: body.initial_cash, opened_at: '2026-11-06T03:00:00Z' }
        return json(current)
      }
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  return resets
}

function openWithMockAccount() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <MySettingsPage mockAccount={<MockAccountPanel />} />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

async function resetTo(amount: string) {
  const user = userEvent.setup()
  const input = await screen.findByRole('spinbutton', { name: 'New starting capital' })
  await user.clear(input)
  await user.type(input, amount)
  await user.click(screen.getByRole('button', { name: 'Reset mock account…' }))
  return { user, dialog: await screen.findByRole('alertdialog', { name: 'Reset your mock account?' }) }
}

describe('My settings’ mock account', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('shows the starting capital, and resets to the amount typed once the user confirms what goes and what stays', async () => {
    const resets = serveAccount(OPENED)
    openWithMockAccount()

    const panel = within(await screen.findByRole('region', { name: 'Mock account' }))
    expect(panel.getByRole('spinbutton', { name: 'New starting capital' })).toHaveValue(1_000_000)
    expect(panel.getByText('Starting capital').parentElement).toHaveTextContent('1,000,000')

    const { user, dialog } = await resetTo('2500000')
    for (const consequence of ['Every position.', 'Cash becomes 2,500,000.', 'The equity curve and the trades start over.', 'Your runs and their orders, in Analysis runs.']) {
      expect(within(dialog).getByText(consequence)).toBeVisible()
    }
    expect(resets).toEqual([])

    await user.click(within(dialog).getByRole('button', { name: 'Reset' }))
    expect(await panel.findByText(/^Reset\. Your mock account opened again on .+ with 2,500,000\.$/)).toBeVisible()
    expect(resets).toEqual([{ confirm: true, initial_cash: 2_500_000 }])
    expect(panel.getByText('Starting capital').parentElement).toHaveTextContent('2,500,000')
  })

  it('sends nothing for an amount that is not above zero', async () => {
    const resets = serveAccount(OPENED)
    const user = userEvent.setup()
    openWithMockAccount()

    const input = await screen.findByRole('spinbutton', { name: 'New starting capital' })
    await user.clear(input)
    await user.type(input, '0')

    expect(screen.getByText('Enter an amount above 0.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Reset mock account…' })).toBeDisabled()
    expect(resets).toEqual([])
  })

  it('says a reset waits while a run of the user is still going', async () => {
    serveAccount(OPENED, { status: 409, detail: 'A run is still running.', code: 'run_in_progress' })
    openWithMockAccount()

    const { user, dialog } = await resetTo('2000000')
    await user.click(within(dialog).getByRole('button', { name: 'Reset' }))

    expect(await screen.findByText('A run of yours is still going and could order meanwhile. Reset once it ends.')).toBeVisible()
  })
})
