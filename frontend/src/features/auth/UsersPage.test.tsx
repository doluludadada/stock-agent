import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { Toaster } from 'sonner'
import { initI18n } from '@/i18n'
import { session, type User } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { UsersPage } from './UsersPage'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The users API over these users; a change of a user listed in `refusals` gets that answer instead. */
function serve(users: User[], refusals: Record<string, Response> = {}) {
  const writes: { url: string; init: RequestInit }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (url === '/v1/admin/users') return json(users)
      if (url.startsWith('/v1/admin/users/') && init.method === 'PATCH') {
        writes.push({ url, init })
        const id = decodeURIComponent(url.split('/').at(-1)!)
        if (refusals[id]) return refusals[id]
        const changed = { ...users.find((user) => user.user_id === id)!, ...(JSON.parse(String(init.body)) as Partial<User>) }
        return json(changed)
      }
      return json({ detail: 'Not Found' }, 404)
    }),
  )
  return writes
}

function renderUsers() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <UsersPage />
          <Toaster />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the users page', { timeout: 20_000 }, () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('deactivates another account after asking, and never offers administrators to demote or deactivate themselves', async () => {
    const writes = serve([TEST_ADMIN, TEST_USER])
    session.signIn(TEST_ADMIN)
    const user = userEvent.setup({ delay: null })
    renderUsers()

    await user.click(await screen.findByRole('button', { name: 'Actions for hsiu' }))
    expect(screen.getByRole('menuitem', { name: 'Deactivate' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('menuitem', { name: 'Make user' })).toHaveAttribute('aria-disabled', 'true')
    await user.keyboard('{Escape}')

    await user.click(screen.getByRole('button', { name: 'Actions for mei' }))
    await user.click(screen.getByRole('menuitem', { name: 'Deactivate' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Deactivate mei?' })
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))

    const row = (await screen.findByText('mei@example.com')).closest('tr')!
    expect(await within(row).findAllByText('Deactivated')).not.toHaveLength(0)
    expect(writes).toHaveLength(1)
    expect(writes[0]!.url).toBe('/v1/admin/users/u-mei')
    expect(JSON.parse(String(writes[0]!.init.body))).toEqual({ confirm: true, status: 'deactivated' })
    expect((writes[0]!.init.headers as Record<string, string>)['X-Requested-With']).toBe('stock-agent')
  })

  it('says the site needs an administrator when the server refuses a change with that code', async () => {
    const lin: User = { ...TEST_ADMIN, user_id: 'u-lin', username: 'lin', email: 'lin@example.com' }
    serve([TEST_ADMIN, lin], { 'u-lin': json({ detail: 'No active administrator would remain.', code: 'last_administrator' }, 409) })
    session.signIn(TEST_ADMIN)
    const user = userEvent.setup({ delay: null })
    renderUsers()

    await user.click(await screen.findByRole('button', { name: 'Actions for lin' }))
    await user.click(screen.getByRole('menuitem', { name: 'Make user' }))
    await user.click(within(screen.getByRole('alertdialog', { name: 'Make lin a user?' })).getByRole('button', { name: 'Make user' }))

    expect(await screen.findByText('Nothing changed: the site needs at least one active administrator.')).toBeInTheDocument()
  })

  it('names the columns for screen readers', async () => {
    serve([TEST_ADMIN, TEST_USER])
    session.signIn(TEST_ADMIN)
    renderUsers()

    const table = await screen.findByRole('table', { name: 'Accounts' })
    expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['User', 'Role', 'Status', 'Created', 'Actions'])
  })
})
