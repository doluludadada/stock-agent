import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { session } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { builtInJson } from '../model/built-ins.test-support'
import { settingsFromApi } from './mapping'
import { useSaveStrategySettings, useStrategySettings } from './queries'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
const settingsNamed = (name: string) => ({ active_strategy_id: 'balanced', strategies: [{ ...builtInJson('balanced'), name }], revision: 1 })

function Strategies() {
  const settings = useStrategySettings()
  return <p>{settings.data ? `strategies: ${settings.data.strategies.map((strategy) => strategy.name).join(', ')}` : 'loading'}</p>
}

/** Mei saves her settings; the server holds its answer until `answer`. Whoever reads the settings gets `stored`. */
function startSave() {
  let answer = () => {}
  const held = new Promise<void>((resolve) => (answer = resolve))
  const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method !== 'PUT') return json(settingsNamed('Stored on the server'))
    await held
    return json(settingsNamed('Saved by Mei'))
  })
  vi.stubGlobal('fetch', fetch)
  session.signIn(TEST_USER)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } })
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const save: { current: ReturnType<typeof useSaveStrategySettings>['mutateAsync'] | null } = { current: null }
  const capture = (mutate: typeof save.current) => (save.current = mutate)
  function Saver() {
    capture(useSaveStrategySettings().mutateAsync)
    return null
  }
  const page = render(<Saver />, { wrapper })
  let saved!: Promise<unknown>
  act(() => {
    saved = save.current!(settingsFromApi(settingsNamed('Saved by Mei')))
  })
  return { client, wrapper, page, saved, answer }
}

describe('a save of the strategy settings whose answer arrives late', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('shows the saved settings to the user who saved them, without asking the server again', async () => {
    const { wrapper, saved, answer } = startSave()
    answer()
    await act(() => saved)

    render(<Strategies />, { wrapper })
    expect(await screen.findByText('strategies: Saved by Mei')).toBeInTheDocument()
  })

  it('is not shown to another user who signed in on the tab meanwhile', async () => {
    const { client, wrapper, page, saved, answer } = startSave()
    act(() => session.signIn(TEST_ADMIN))
    // What the app does when the user of the tab changes.
    client.removeQueries({ queryKey: ['owner'] })
    page.unmount()

    answer()
    await act(() => saved)

    render(<Strategies />, { wrapper })
    expect(await screen.findByText('strategies: Stored on the server')).toBeInTheDocument()
  })
})
