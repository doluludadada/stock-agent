import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { FollowSchedulePanel } from './FollowSchedulePanel'

/** The follow's answer as far as the panel reads it, and each time the panel saves. */
function serve(schedule: { time: string | null; times: string[] }) {
  const saved: unknown[] = []
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method !== 'PUT') return json({ running: false, refusal: null, schedule })
      saved.push(JSON.parse(String(init.body)))
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
