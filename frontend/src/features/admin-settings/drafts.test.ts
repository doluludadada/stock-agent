import type { Draft } from './drafts'

const draft = (owner: string, text: string): Draft => ({ owner, base: { revision: 'a'.repeat(64), text: 'environment: dev\n' }, text, editedAt: '2026-11-04T06:00:00Z' })

/** The draft module as a page that just loaded would have it: read again from the tab's storage. */
async function reload() {
  vi.resetModules()
  return (await import('./drafts')).drafts
}

describe('unsaved settings text', () => {
  it('comes back after the page reloads, for the same user only', async () => {
    const before = await reload()
    before.put('appsetting', draft('local', 'environment: dev\n# changed\n'))

    const after = await reload()

    expect(after.get('appsetting', 'local')?.text).toBe('environment: dev\n# changed\n')
    expect(after.get('appsetting', 'someone-else')).toBeNull()
    expect(after.get('instructions', 'local')).toBeNull()
  })

  it('is gone once it is the file it started from again, or once it is discarded', async () => {
    const drafts = await reload()
    drafts.put('appsetting', draft('local', 'environment: dev\n# changed\n'))
    drafts.put('instructions', draft('local', 'system_prompt: hi\n'))

    drafts.put('appsetting', draft('local', 'environment: dev\n'))
    drafts.discard('instructions')

    const after = await reload()
    expect(after.get('appsetting', 'local')).toBeNull()
    expect(after.get('instructions', 'local')).toBeNull()
  })

  it('ignores storage it cannot read as drafts', async () => {
    window.sessionStorage.setItem('stock-agent.settings-drafts', JSON.stringify({ appsetting: { owner: 'local', text: 3 }, other: draft('local', 'x') }))
    expect((await reload()).get('appsetting', 'local')).toBeNull()

    window.sessionStorage.setItem('stock-agent.settings-drafts', '{not json')
    expect((await reload()).get('appsetting', 'local')).toBeNull()
  })
})
