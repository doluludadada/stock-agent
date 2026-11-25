import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { siteShowing } from '@/test/features'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { RequireSignIn } from './require-sign-in'

function renderGate(needs?: 'manage_users', registrationOpen = true) {
  const status = { ...siteShowing(), registration_open: registrationOpen }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(status), { headers: { 'Content-Type': 'application/json' } })))
  return render(
    <I18nextProvider i18n={initI18n('en')}>
      <MemoryRouter initialEntries={['/watchlist?sort=code']}>
        <QueryClientProvider client={new QueryClient()}>
          <RequireSignIn needs={needs} reason="Sign in to see your watchlist" layout="page">
            <p>private rows</p>
          </RequireSignIn>
        </QueryClientProvider>
      </MemoryRouter>
    </I18nextProvider>,
  )
}

describe('a private page', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('asks a visitor to sign in and come back, or to create an account, with no token or unlock in sight', () => {
    session.signOut()
    renderGate()

    expect(screen.getByText('Sign in to see your watchlist')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in?next=%2Fwatchlist%3Fsort%3Dcode')
    expect(screen.getByRole('link', { name: 'Create account' })).toHaveAttribute('href', '/register')
    expect(screen.queryByText('private rows')).toBeNull()
    expect(document.body.textContent).not.toMatch(/token|unlock/i)
  })

  it('offers no account to create while the site takes no registrations', async () => {
    session.signOut()
    renderGate(undefined, false)

    expect(screen.getByRole('link', { name: 'Sign in' })).toBeVisible()
    await waitFor(() => expect(screen.queryByRole('link', { name: 'Create account' })).toBeNull())
  })

  it('says the session ended when the server ended it', () => {
    session.signIn(TEST_USER)
    session.expire(session.generation())
    renderGate()

    expect(screen.getByText('You were signed out')).toBeVisible()
  })

  it('shows an administrator page only to a role with its permission, and keeps the user signed in', () => {
    session.signIn(TEST_USER)
    const asUser = renderGate('manage_users')
    expect(screen.getByText('For administrators only')).toBeVisible()
    expect(screen.queryByText('private rows')).toBeNull()
    expect(session.current().status).toBe('signedIn')
    asUser.unmount()

    session.signIn(TEST_ADMIN)
    renderGate('manage_users')
    expect(screen.getByText('private rows')).toBeVisible()
  })
})
