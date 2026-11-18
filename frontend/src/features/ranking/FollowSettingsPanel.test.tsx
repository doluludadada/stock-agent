import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { session, type Broker } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { FollowSettingsPanel } from './FollowSettingsPanel'
import type { FollowAccount, FollowSchedule, FollowSettings } from './model'

type Saved = { path: 'account'; body: { broker: string } } | { path: 'schedule'; body: { time: string | null } }

/**
 * The panel's one read, the follow account with the schedule, and each save, by the endpoint it went to. A save changes
 * only its own field of what the read answers, as the server saves the other field as it was; an account the site
 * offers is one it no longer refuses.
 */
function serve(schedule: Pick<FollowSchedule, 'time' | 'times'>, account: Partial<FollowAccount> = {}) {
  const saved: Saved[] = []
  const answer = {
    account: { broker: 'mock', brokers: ['mock'], refusal: null, server: null, ...account },
    schedule: { ...schedule, pending: null, unfinished: null, due: false },
  } satisfies FollowSettings
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url, 'http://localhost').pathname.replace('/v1/rankings/follow/', '')
      if (path === 'schedule' && init?.method !== 'PUT') return json(answer)
      if (init?.method !== 'PUT' || (path !== 'account' && path !== 'schedule')) return json({ detail: 'Not found.', code: 'not_found' }, 404)
      const { confirm, ...body } = JSON.parse(String(init.body)) as { confirm: boolean; broker?: Broker; time?: string | null }
      expect(confirm).toBe(true)
      saved.push({ path, body } as Saved)
      if (body.broker) answer.account = { ...answer.account, broker: body.broker, refusal: answer.account.brokers.includes(body.broker) ? null : answer.account.refusal }
      if (body.time !== undefined) answer.schedule = { ...answer.schedule, time: body.time }
      return new Response(null, { status: 204 })
    }),
  )
  return saved
}

/** Picks an account in the account's list, which English names too long for a phone's row of buttons. */
async function pick(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole('combobox', { name: 'Follow account' }))
  await user.click(await screen.findByRole('option', { name }))
}

function open(locale: 'en' | 'zh-TW' = 'en') {
  const i18n = initI18n('en')
  void i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <FollowSettingsPanel />
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the ranking follow on My settings', () => {
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

  it('offers off and a few times as buttons, and saves the one picked alone', async () => {
    const saved = serve({ time: null, times: ['09:05:00', '09:30:00'] })
    open()

    const choice = await screen.findByRole('radiogroup', { name: 'Scheduled follow' })
    expect(within(choice).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['Off', '09:05', '09:30'])
    await userEvent.setup().click(within(choice).getByRole('radio', { name: '09:30' }))
    expect(saved).toEqual([{ path: 'schedule', body: { time: '09:30:00' } }])
    expect(screen.queryByRole('combobox', { name: 'Follow account' }), 'the mock account alone is no choice').not.toBeInTheDocument()
    expect(choice).toHaveAccessibleDescription(/into Mock account by itself/)
    await waitFor(() => expect(within(choice).getByRole('radio', { name: '09:30' }), 'the schedule is asked again after the save').toBeChecked())
  })

  it('lists more times than a phone’s row holds, with the user’s own time the site no longer offers in its place', async () => {
    serve({ time: '09:15:00', times: ['09:05:00', '09:30:00', '10:00:00', '11:00:00', '13:00:00'] })
    open()

    const list = await screen.findByRole('combobox')
    expect(list).toHaveTextContent('09:15')
    await userEvent.setup().click(list)
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual(['Off', '09:05', '09:15', '09:30', '10:00', '11:00', '13:00'])
  })

  it('offers the follow account beside the time where the site lets the follow order on SinoPac, and saves each without the other', async () => {
    const saved = serve({ time: '09:05:00', times: ['09:05:00', '09:30:00'] }, { brokers: ['mock', 'shioaji'], server: 'simulation' })
    const user = userEvent.setup()
    open()

    const account = await screen.findByRole('combobox', { name: 'Follow account' })
    expect(account).toHaveTextContent('Mock account')
    expect(account).toHaveAccessibleDescription('The ranking page’s button and the schedule both follow on this account.')
    await user.click(account)
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual(['Mock account', 'SinoPac account · Simulation'])
    await user.click(screen.getByRole('option', { name: 'SinoPac account · Simulation' }))
    await waitFor(() => expect(account).toHaveTextContent('SinoPac account · Simulation'))
    const time = screen.getByRole('radiogroup', { name: 'Scheduled follow' })
    expect(within(time).getByRole('radio', { name: '09:05' }), 'the account’s save keeps the time').toBeChecked()
    expect(time).toHaveAccessibleDescription(/into SinoPac account · Simulation by itself/)
    await user.click(within(time).getByRole('radio', { name: '09:30' }))
    await waitFor(() => expect(within(time).getByRole('radio', { name: '09:30' })).toBeChecked())
    expect(account, 'the time’s save keeps the account').toHaveTextContent('SinoPac account · Simulation')
    expect(saved).toEqual([
      { path: 'account', body: { broker: 'shioaji' } },
      { path: 'schedule', body: { time: '09:30:00' } },
    ])
  })

  it('saves the follow account while the schedule is off, and leaves it off', async () => {
    const saved = serve({ time: null, times: ['09:05:00'] }, { brokers: ['mock', 'shioaji'], server: 'simulation' })
    const user = userEvent.setup()
    open()

    await screen.findByRole('combobox', { name: 'Follow account' })
    await pick(user, 'SinoPac account · Simulation')
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Follow account' })).toHaveTextContent('SinoPac account · Simulation'))
    expect(within(screen.getByRole('radiogroup', { name: 'Scheduled follow' })).getByRole('radio', { name: 'Off' })).toBeChecked()
    expect(saved).toEqual([{ path: 'account', body: { broker: 'shioaji' } }])
  })

  it('shows a saved SinoPac account the site no longer offers, says why it follows on no account, and offers the mock account in its place', async () => {
    const saved = serve({ time: '09:05:00', times: ['09:05:00'] }, { broker: 'shioaji', brokers: ['mock'], refusal: 'not_simulation', server: 'production' })
    const user = userEvent.setup()
    open()

    expect(await screen.findByRole('combobox', { name: 'Follow account' })).toHaveTextContent('SinoPac account · Production')
    expect(screen.getByText('This account cannot follow now, and the site follows on no other account instead. Choose another one here.')).toBeVisible()
    const time = screen.getByRole('radiogroup', { name: 'Scheduled follow' })
    expect(time, 'never the account it would follow on').toHaveAccessibleDescription(
      'The site follows on no account now: The SinoPac account is on Production now, and a ranking follow orders on Simulation only, never with real money. The schedule never moves to another account.',
    )

    await pick(user, 'Mock account')
    expect(saved).toEqual([{ path: 'account', body: { broker: 'mock' } }])
    await waitFor(() => expect(screen.queryByRole('combobox', { name: 'Follow account' }), 'the mock account alone again').not.toBeInTheDocument())
    expect(time).toHaveAccessibleDescription(/into Mock account by itself/)
  })

  it('says why the site follows on no account where it offers the viewer none, and still lets the schedule be turned off', async () => {
    const saved = serve({ time: '09:05:00', times: ['09:05:00'] }, { brokers: [], refusal: 'ordering_off' })
    open()

    const time = await screen.findByRole('radiogroup', { name: 'Scheduled follow' })
    expect(screen.queryByRole('combobox', { name: 'Follow account' }), 'no account to choose').not.toBeInTheDocument()
    expect(time).toHaveAccessibleDescription('The site follows on no account now: The site does not let you follow the ranking on this account now. The schedule never moves to another account.')
    await userEvent.setup().click(within(time).getByRole('radio', { name: 'Off' }))
    expect(saved).toEqual([{ path: 'schedule', body: { time: null } }])
  })

  it('reads the account choice in Traditional Chinese, the server always beside SinoPac’s name', async () => {
    serve({ time: null, times: ['09:05:00'] }, { broker: 'shioaji', brokers: ['mock', 'shioaji'], server: 'simulation' })
    open('zh-TW')

    const account = await screen.findByRole('radiogroup', { name: '跟單帳戶' })
    expect(within(account).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['本站模擬帳戶', '永豐金帳戶・測試環境'])
    expect(account).toHaveAccessibleDescription('排名頁的跟單按鈕和排程都在這個帳戶跟單。')
    expect(screen.getByRole('radiogroup', { name: '排程自動跟單' })).toHaveAccessibleDescription(/自動在永豐金帳戶・測試環境跟單/)
    cleanup()

    serve({ time: '09:05:00', times: ['09:05:00'] }, { broker: 'shioaji', brokers: ['mock'], refusal: 'broker_unavailable', server: 'production' })
    open('zh-TW')
    expect(await screen.findByRole('radiogroup', { name: '跟單帳戶' })).toHaveAccessibleDescription(
      '排名頁的跟單按鈕和排程都在這個帳戶跟單。 這個帳戶目前不能跟單，網站也不會改在其他帳戶跟單。請在這裡換一個帳戶。',
    )
    expect(screen.getByRole('radiogroup', { name: '排程自動跟單' }), '不寫它會在永豐金帳戶・正式環境跟單').toHaveAccessibleDescription(
      '網站目前不會在任何帳戶自動跟單：本站目前沒有可下單的永豐金帳戶登入。排程也不會改到其他帳戶。',
    )
  })
})
