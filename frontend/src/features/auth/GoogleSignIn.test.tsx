import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { SetupScreen, SignInScreen } from './AccountScreens'

function renderAt(entry: string, googleSignIn: boolean, screenElement: React.ReactNode, language: 'en' | 'zh-TW' = 'en') {
  const status = { needs_first_administrator: false, registration_open: false, google_sign_in: googleSignIn }
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(status), { status: 200, headers: { 'Content-Type': 'application/json' } })),
  )
  const i18n = initI18n(language)
  void i18n.changeLanguage(language)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={[entry]}>{screenElement}</MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('sign-in with Google', { timeout: 20_000 }, () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('is a link the browser navigates to, on the sign-in screen of a site that offers it', async () => {
    renderAt('/sign-in', true, <SignInScreen registerHref="/register" onDone={() => undefined} />)

    expect(await screen.findByRole('link', { name: 'Sign in with Google' })).toHaveAttribute('href', '/v1/auth/google/start')
    expect(screen.getByLabelText('Username or email')).toBeVisible()
  })

  it('is on the first-time setup too, beside the setup code', async () => {
    renderAt('/setup', true, <SetupScreen onDone={() => undefined} />, 'zh-TW')

    expect(await screen.findByRole('link', { name: '使用 Google 登入' })).toHaveAttribute('href', '/v1/auth/google/start')
    expect(screen.getByText(/不需要設定碼/)).toBeVisible()
  })

  it('is absent on a site that does not offer it', async () => {
    renderAt('/sign-in', false, <SignInScreen registerHref="/register" onDone={() => undefined} />)

    expect(await screen.findByText(/Registration is closed/)).toBeVisible()
    expect(screen.queryByRole('link', { name: 'Sign in with Google' })).not.toBeInTheDocument()
  })

  it.each([
    ['not_allowed', /not allowed on this site, and no account was created/],
    ['deactivated', /is deactivated/],
    ['cancelled', /was cancelled/],
    ['throttled', /Too many sign-in attempts/],
    ['something_new', /did not go through/],
  ])('says why a sign-in ended without a session: %s', async (refusal, words) => {
    renderAt(`/sign-in?google=${refusal}`, true, <SignInScreen registerHref="/register" onDone={() => undefined} />)

    expect(await screen.findByRole('alert')).toHaveTextContent(words)
  })
})
