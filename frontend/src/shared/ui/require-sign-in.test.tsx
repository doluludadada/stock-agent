import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { AuthLinksProvider, RequireSignIn } from './require-sign-in'

function renderGate(needs?: 'manage_users') {
  return render(
    <I18nextProvider i18n={initI18n('en')}>
      <MemoryRouter initialEntries={['/watchlist?sort=code']}>
        <AuthLinksProvider value={{ signIn: (next) => `/sign-in?next=${encodeURIComponent(next)}`, register: '/register' }}>
          <RequireSignIn needs={needs} reason="Sign in to see your watchlist" layout="page">
            <p>private rows</p>
          </RequireSignIn>
        </AuthLinksProvider>
      </MemoryRouter>
    </I18nextProvider>,
  )
}

describe('a private page', () => {
  afterEach(() => session.signOut())

  it('asks a visitor to sign in and come back, or to create an account, with no token or unlock in sight', () => {
    session.signOut()
    renderGate()

    expect(screen.getByText('Sign in to see your watchlist')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in?next=%2Fwatchlist%3Fsort%3Dcode')
    expect(screen.getByRole('link', { name: 'Create account' })).toHaveAttribute('href', '/register')
    expect(screen.queryByText('private rows')).toBeNull()
    expect(document.body.textContent).not.toMatch(/token|unlock/i)
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
