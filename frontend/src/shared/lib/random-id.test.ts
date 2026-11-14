import { randomHex } from './random-id'

describe('random ids', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('has the digits asked for, odd counts too, and differs from one call to the next', () => {
    expect(randomHex(10)).toMatch(/^[0-9a-f]{10}$/)
    expect(randomHex(7)).toMatch(/^[0-9a-f]{7}$/)
    expect(randomHex(32)).not.toBe(randomHex(32))
  })

  it('works where the browser gives the page no secure context, so no crypto.randomUUID', () => {
    const { getRandomValues } = globalThis.crypto
    vi.stubGlobal('crypto', { getRandomValues: getRandomValues.bind(globalThis.crypto) })

    expect(randomHex(32)).toMatch(/^[0-9a-f]{32}$/)
  })
})
