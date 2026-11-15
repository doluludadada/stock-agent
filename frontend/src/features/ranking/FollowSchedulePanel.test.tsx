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
function serve(schedule: { time: string | null; times: string[] }) {
  const saved: unknown[] = []
  const answer: FollowSchedule = { ...schedule, pending: null, unfinished: null, due: false }
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (new URL(url, 'http://localhost').pathname !== '/v1/rankings/follow/schedule') return json({ detail: 'Not found.', code: 'not_found' }, 404)
      if (init?.method !== 'PUT') return json(answer)
      const body = JSON.parse(String(init.body)) as { time: string | null }
      saved.push(body)
      answer.time = body.time
      return new Response(null, { status: 204 })
    }),
  )
  return saved
}

function open() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
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
    expect(saved).toEqual([{ confirm: true, time: '09:30:00' }])
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
})
