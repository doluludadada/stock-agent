import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
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
