import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { AdminSettingsPage } from './AdminSettingsPage'

const file = {
  status: { file: 'appsetting', revision: 'a'.repeat(64), running_revision: 'a'.repeat(64), modified_at: '2026-11-04T00:00:00Z', restart_required: false },
  settings: [
    { setting: 'collect_rules.spam_keywords', value: ['giveaway'], choices: [] },
    { setting: 'ai.temperature', value: 0.5, choices: [] },
  ],
  locked: {},
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const backup = { backup_id: '20261104T000000Z-0123456789ab', revision: 'b'.repeat(64), created_at: '2026-11-04T00:00:00Z' }

function renderPage(answers: Record<string, () => Response> = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      const answer = Object.entries(answers).find(([prefix]) => url.startsWith(prefix))?.[1]
      if (answer) return answer()
      if (url === '/v1/admin/settings/appsetting') return json(file)
      if (url.startsWith('/v1/admin/settings/appsetting/backups') || url.startsWith('/v1/admin/audit')) return json([])
      return new Response('{}', { status: 404 })
    }),
  )
  session.unlock('admin', 'admin-token')
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <AdminSettingsPage />
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the settings editor', () => {
  afterEach(() => {
    session.lock('admin')
    vi.unstubAllGlobals()
  })

  it('keeps a keyword with a space and a new line as they are typed', async () => {
    renderPage()
    const user = userEvent.setup()
    const keywords = await screen.findByLabelText('Spam keywords (one per line)')

    await user.click(keywords)
    await user.keyboard('{Control>}{End}{/Control}{Enter}free trial')

    expect(keywords).toHaveValue('giveaway\nfree trial')
    expect(screen.getByText('1 changed')).toBeInTheDocument()
  })

  it('puts typed numbers back when the changes are discarded', async () => {
    renderPage()
    const user = userEvent.setup()
    const temperature = await screen.findByLabelText('Temperature')

    await user.clear(temperature)
    await user.type(temperature, '0.9')
    await user.click(screen.getByRole('button', { name: 'Discard changes' }))

    expect(await screen.findByLabelText('Temperature')).toHaveValue('0.5')
    expect(screen.getByText('0 changed')).toBeInTheDocument()
  })

  it('says a backup preview failed instead of doing nothing', async () => {
    renderPage({
      '/v1/admin/settings/appsetting/backups/': () => json({ detail: 'The backup could not be read.' }, 500),
      '/v1/admin/settings/appsetting/backups': () => json([backup]),
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Preview restore' }))

    expect(await screen.findByText(/No preview/)).toBeInTheDocument()
  })

  it('shows that the recent saves failed to load, with a retry', async () => {
    let failing = true
    renderPage({ '/v1/admin/audit': () => (failing ? json({ detail: 'boom' }, 500) : json([])) })

    const retry = await screen.findByRole('button', { name: 'Try again' })
    failing = false
    await userEvent.setup().click(retry)

    await waitFor(() => expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument())
  })
})
