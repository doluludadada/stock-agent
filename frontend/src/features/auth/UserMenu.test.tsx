import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { Toaster } from 'sonner'
import { initI18n } from '@/i18n'
import { session, type User } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { UserMenu } from './UserMenu'

async function openMenu(user: User, locale: 'en' | 'zh-TW' = 'en') {
  session.signIn(user)
  const i18n = initI18n(locale)
  await i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <UserMenu onSignedOut={() => undefined} />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
  await userEvent.setup().click(screen.getByRole('button', { name: new RegExp(user.username) }))
  return screen.getAllByRole('menuitem').map((item) => [item.textContent, item.getAttribute('href')])
}

describe('The account menu', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('says a sign-out the server did not answer failed, and leaves the user signed in', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    const signedOut = vi.fn()
    session.signIn(TEST_USER)
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QueryClientProvider client={new QueryClient()}>
          <MemoryRouter>
            <UserMenu onSignedOut={signedOut} />
            <Toaster />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /mei/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))

    expect(await screen.findByText('Signing out did not reach the server. You are still signed in. Try again.')).toBeVisible()
    expect(session.current()).toEqual({ status: 'signedIn', user: TEST_USER })
    expect(signedOut).not.toHaveBeenCalled()
  })

  it('links every signed-in user to My settings, and nothing of the administrator’s', async () => {
    expect(await openMenu(TEST_USER)).toEqual([
      ['My settings', '/settings'],
      ['Sign out', null],
    ])
  })

  it('puts My settings beside the administrator’s pages', async () => {
    expect(await openMenu(TEST_ADMIN, 'zh-TW')).toEqual([
      ['我的設定', '/settings'],
      ['使用者管理', '/admin/users'],
      ['系統設定', '/admin/settings'],
      ['登出', null],
    ])
  })
})
