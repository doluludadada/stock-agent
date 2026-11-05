import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { Toaster } from 'sonner'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { RunsPage } from './RunsPage'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** Starts a Full Cycle against a server that refuses it with this answer. */
async function startRefused(status: number, refusal: { detail: string; code: string }) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith('/v1/runs?')) return json([])
      if (url === '/v1/runs/full-cycle' && init?.method === 'POST') return json(refusal, status)
      return json({ detail: 'Not Found', code: 'not_found' }, 404)
    }),
  )
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <RunsPage />
          <Toaster />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
  const user = userEvent.setup()
  const [fullCycle] = await screen.findAllByRole('button', { name: 'Start' })
  await user.click(fullCycle!)
  await user.click(await screen.findByRole('button', { name: 'Start the run' }))
}

describe('a run the server refuses to start', { timeout: 20_000 }, () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('says another run is still going when the server says so', async () => {
    await startRefused(409, { detail: 'Your run is still running.', code: 'run_in_progress' })

    expect(await screen.findByText('Another run is still going. Wait for it to end.')).toBeInTheDocument()
  })

  it('names the mock broker only for its own refusal, not for every 403', async () => {
    const detail = 'This installation trades on a real broker. Only an administrator may use its private pages.'
    await startRefused(403, { detail, code: 'real_broker_refused' })

    expect(await screen.findByText(`The run did not start: ${detail}`)).toBeInTheDocument()
    expect(screen.queryByText('This workflow runs from the web only on the mock broker.')).not.toBeInTheDocument()
  })
})
