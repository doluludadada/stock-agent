import { reloadOnStaleBuild } from './stale-build'

function inMemory() {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => void values.set(key, value) }
}

/** A window of its own: the listener, its sessionStorage and a reload that only counts. */
function tab(sessionStorage: Pick<Storage, 'getItem' | 'setItem'> = inMemory(), onLine = true) {
  const target = new EventTarget() as Window
  const reload = vi.fn()
  Object.assign(target, { sessionStorage, location: { reload }, navigator: { onLine } })
  return { target, reload }
}

/** A failed import as Vite reports it, then whatever the page has scheduled: whether the listener took the failure. */
function failImport(target: EventTarget) {
  const event = new Event('vite:preloadError', { cancelable: true })
  target.dispatchEvent(event)
  vi.runAllTimers()
  return event.defaultPrevented
}

describe('a tab left open across a deploy', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('loads the page again on the first failed import, once the router has moved to the page the user clicked', () => {
    const { target, reload } = tab()
    reloadOnStaleBuild(target, () => 1_000_000)

    target.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))
    expect(reload).not.toHaveBeenCalled()
    vi.runAllTimers()
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('shows the error page instead of reloading again within a minute, and reloads once more after it', () => {
    let clock = 1_000_000
    const { target, reload } = tab()
    reloadOnStaleBuild(target, () => clock)

    failImport(target)
    clock += 59_000
    expect(failImport(target)).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)

    clock += 2_000
    expect(failImport(target)).toBe(true)
    expect(reload).toHaveBeenCalledTimes(2)
  })

  it('keeps the page offline, where the import failed for want of a network', () => {
    const { target, reload } = tab(inMemory(), false)
    reloadOnStaleBuild(target, () => 1_000_000)

    expect(failImport(target)).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })

  it('never reloads where sessionStorage refuses the note, so a missing file cannot loop', () => {
    const refusing = {
      getItem: () => null,
      setItem: () => {
        throw new Error('storage disabled')
      },
    }
    const { target, reload } = tab(refusing)
    reloadOnStaleBuild(target, () => 1_000_000)

    expect(failImport(target)).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })
})
