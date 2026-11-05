import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { RegisterScreen, SetupScreen } from './AccountScreens'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function renderScreen(screenElement: React.ReactNode) {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>{screenElement}</MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

async function fillAccount(user: ReturnType<typeof userEvent.setup>, account: { username: string; email: string; password: string }) {
  await user.type(screen.getByLabelText('Username'), account.username)
  await user.type(screen.getByLabelText('Email'), account.email)
  await user.type(screen.getByLabelText('Password'), account.password)
  await user.type(screen.getByLabelText('Password again'), account.password)
}

describe('the first-time setup', { timeout: 20_000 }, () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('names a wrong setup code under its field, then signs the administrator in with the right one', async () => {
    const sent: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        const body = JSON.parse(String(init.body)) as Record<string, string>
        sent.push({ url, body })
        if (url === '/v1/auth/setup') return body.setup_code === 'Gk3v9QpT' ? json(TEST_ADMIN, 201) : json({ detail: 'Wrong setup code.' }, 403)
        if (url === '/v1/auth/sign-in') return json(TEST_ADMIN)
        return json({}, 404)
      }),
    )
    const done = vi.fn()
    const user = userEvent.setup({ delay: null })
    renderScreen(<SetupScreen onDone={done} />)

    expect(screen.getByText(/printed this one-time code on its console/)).toBeVisible()
    await user.type(screen.getByLabelText('Setup code'), 'wrong-code')
    await fillAccount(user, { username: 'hsiu', email: 'hsiu@example.com', password: 'correct horse battery' })
    await user.click(screen.getByRole('button', { name: 'Create and sign in' }))
    expect(await screen.findByText('That setup code is wrong. Compare it with the one on the server console.')).toBeVisible()
    expect(done).not.toHaveBeenCalled()

    await user.clear(screen.getByLabelText('Setup code'))
    await user.type(screen.getByLabelText('Setup code'), 'Gk3v9QpT')
    await user.click(screen.getByRole('button', { name: 'Create and sign in' }))

    await vi.waitFor(() => expect(done).toHaveBeenCalled())
    expect(sent.at(-1)).toEqual({ url: '/v1/auth/sign-in', body: { identifier: 'hsiu', password: 'correct horse battery' } })
    expect(session.current()).toEqual({ status: 'signedIn', user: TEST_ADMIN })
  })
})

describe('registration', { timeout: 20_000 }, () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('names a taken email under the email field and keeps what was typed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/v1/auth/status') return json({ needs_first_administrator: false, registration_open: true })
        if (url === '/v1/auth/register') return json({ detail: 'That email is taken.' }, 409)
        return json({}, 404)
      }),
    )
    const user = userEvent.setup({ delay: null })
    renderScreen(<RegisterScreen signInHref="/sign-in" onDone={vi.fn()} />)

    await screen.findByRole('heading', { name: 'Create an account' })
    await fillAccount(user, { username: TEST_USER.username, email: TEST_USER.email, password: 'watchlist mei 88' })
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByText('This email already has an account.')).toBeVisible()
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Username')).toHaveValue('mei')
  })
})
