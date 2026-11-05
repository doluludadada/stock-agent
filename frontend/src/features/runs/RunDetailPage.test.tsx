import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { RunDetailPage } from './RunDetailPage'

const RUN = '11111111-1111-4111-8111-111111111111'
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function renderRun() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <RunDetailPage runId={RUN} />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('a finished run whose decisions or orders failed to load', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('says the load failed and retries it, instead of saying the run made no decision and placed no order', async () => {
    let failing = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === `/v1/runs/${RUN}`) return json({ run_id: RUN, state: 'finished', error: null, summary: null, reports: [] })
      return failing ? json({ detail: 'boom' }, 500) : json([])
    }))
    renderRun()

    const failures = await screen.findAllByRole('button', { name: 'Try again' })
    expect(failures).toHaveLength(2)
    expect(screen.queryByText('The run recorded no decision.')).not.toBeInTheDocument()
    expect(screen.queryByText('The run placed no order.')).not.toBeInTheDocument()

    failing = false
    const user = userEvent.setup()
    for (const retry of failures) await user.click(retry)

    expect(await screen.findByText('The run recorded no decision.')).toBeInTheDocument()
    expect(await screen.findByText('The run placed no order.')).toBeInTheDocument()
    expect(within(document.body).queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })
})
