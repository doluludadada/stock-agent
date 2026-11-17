import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { FollowSchedulePanel } from './FollowSchedulePanel'
import type { FollowSchedule } from './model'

/** The schedule's own endpoint, the only one the panel asks, and each time the panel saves. */
function serve(schedule: Pick<FollowSchedule, 'time' | 'times'> & Partial<Pick<FollowSchedule, 'broker' | 'broker_offered' | 'brokers'>>) {
  const saved: unknown[] = []
  const answer: FollowSchedule = { broker: 'mock', broker_offered: true, brokers: ['mock'], ...schedule, pending: null, unfinished: null, due: false }
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (new URL(url, 'http://localhost').pathname !== '/v1/rankings/follow/schedule') return json({ detail: 'Not found.', code: 'not_found' }, 404)
      if (init?.method !== 'PUT') return json(answer)
      const body = JSON.parse(String(init.body)) as Pick<FollowSchedule, 'time' | 'broker'>
      saved.push(body)
      Object.assign(answer, { time: body.time, broker: body.broker, broker_offered: answer.brokers.includes(body.broker) })
      return new Response(null, { status: 204 })
    }),
  )
  return saved
}

function open(locale: 'en' | 'zh-TW' = 'en') {
  const i18n = initI18n('en')
  void i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <FollowSchedulePanel />
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the scheduled follow on My settings', () => {
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

  it('offers off and a few times as buttons, and saves the one picked at once', async () => {
    const saved = serve({ time: null, times: ['09:05:00', '09:30:00'] })
    open()

    const choice = await screen.findByRole('radiogroup')
    expect(within(choice).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['Off', '09:05', '09:30'])
    await userEvent.setup().click(within(choice).getByRole('radio', { name: '09:30' }))
    expect(saved).toEqual([{ confirm: true, time: '09:30:00', broker: 'mock' }])
    expect(screen.queryByRole('radiogroup', { name: 'Account to follow on' }), 'the mock account alone is no choice').not.toBeInTheDocument()
    expect(screen.getByText(/into your mock account by itself/)).toBeVisible()
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

  it('offers the account beside the time where the site lets the follow order on SinoPac’s simulation account, and saves both', async () => {
    const saved = serve({ time: '09:05:00', times: ['09:05:00', '09:30:00'], brokers: ['mock', 'shioaji'] })
    const user = userEvent.setup()
    open()

    const account = await screen.findByRole('radiogroup', { name: 'Account to follow on' })
    expect(within(account).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['Mock account', 'SinoPac (simulation)'])
    expect(within(account).getByRole('radio', { name: 'Mock account' })).toBeChecked()
    expect(account).toHaveAccessibleDescription('SinoPac (simulation) is SinoPac’s simulation account: no real money is used.')
    expect(screen.getByText(/into the account chosen below by itself/)).toBeVisible()

    await user.click(within(account).getByRole('radio', { name: 'SinoPac (simulation)' }))
    await waitFor(() => expect(within(account).getByRole('radio', { name: 'SinoPac (simulation)' })).toBeChecked())
    await user.click(within(screen.getByRole('radiogroup', { name: 'Scheduled follow' })).getByRole('radio', { name: '09:30' }))
    expect(saved).toEqual([
      { confirm: true, time: '09:05:00', broker: 'shioaji' },
      { confirm: true, time: '09:30:00', broker: 'shioaji' },
    ])
  })

  it('keeps the account chosen while the schedule is off for the next time saved', async () => {
    const saved = serve({ time: null, times: ['09:05:00'], brokers: ['mock', 'shioaji'] })
    const user = userEvent.setup()
    open()

    const account = await screen.findByRole('radiogroup', { name: 'Account to follow on' })
    await user.click(within(account).getByRole('radio', { name: 'SinoPac (simulation)' }))
    await waitFor(() => expect(within(account).getByRole('radio', { name: 'SinoPac (simulation)' })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: '09:05' }))
    expect(saved).toEqual([
      { confirm: true, time: null, broker: 'shioaji' },
      { confirm: true, time: '09:05:00', broker: 'shioaji' },
    ])
  })

  it('shows a saved SinoPac account the site no longer offers, and says it follows on no account instead', async () => {
    const saved = serve({ time: '09:05:00', times: ['09:05:00'], broker: 'shioaji', broker_offered: false, brokers: ['mock'] })
    const user = userEvent.setup()
    open()

    const account = await screen.findByRole('radiogroup', { name: 'Account to follow on' })
    expect(within(account).getByRole('radio', { name: 'SinoPac (simulation)' })).toBeChecked()
    expect(screen.getByText('The site does not follow on SinoPac’s simulation account for you now, and it follows on no other account instead.')).toBeVisible()

    await user.click(within(account).getByRole('radio', { name: 'Mock account' }))
    expect(saved).toEqual([{ confirm: true, time: '09:05:00', broker: 'mock' }])
    await waitFor(() => expect(screen.queryByRole('radiogroup', { name: 'Account to follow on' }), 'the mock account alone again').not.toBeInTheDocument())
  })

  it('reads the account choice in Traditional Chinese', async () => {
    serve({ time: null, times: ['09:05:00'], broker: 'shioaji', broker_offered: false, brokers: ['mock'] })
    open('zh-TW')

    const account = await screen.findByRole('radiogroup', { name: '跟單帳戶' })
    expect(within(account).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['模擬帳戶', '永豐金模擬帳戶'])
    expect(account).toHaveAccessibleDescription('永豐金模擬帳戶是永豐金的模擬環境，不使用真實資金。 本站目前不會幫你在永豐金模擬帳戶跟單，也不會改在其他帳戶跟單。')
  })
})
