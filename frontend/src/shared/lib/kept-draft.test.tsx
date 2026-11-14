import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
import { session, useSession } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { useKeptDraft } from './kept-draft'

/** A note typed on a page that shows only while someone is signed in; an empty note is no draft. */
function Note({ name }: { name: string }) {
  const kept = useKeptDraft<string>(name)
  const [text, setText] = useState(kept.restored ?? '')
  useEffect(() => kept.track(text === '' ? null : text), [kept, text])
  return <input aria-label="Note" value={text} onChange={(event) => setText(event.target.value)} />
}

function Page({ name }: { name: string }) {
  return useSession().status === 'signedIn' ? <Note name={name} /> : <p>Sign in</p>
}

describe('a draft kept over the end of the session', () => {
  afterEach(() => session.signOut())

  it('is handed back to the same user after the session expired, and again after it was typed on', async () => {
    session.signIn(TEST_USER)
    const user = userEvent.setup()
    render(<Page name="expired" />)
    await user.type(screen.getByLabelText('Note'), 'buy less')

    act(() => session.expire(session.generation()))
    expect(screen.getByText('Sign in')).toBeInTheDocument()
    act(() => session.signIn(TEST_USER))
    expect(screen.getByLabelText('Note')).toHaveValue('buy less')

    await user.type(screen.getByLabelText('Note'), ' today')
    act(() => session.signOut())
    act(() => session.signIn(TEST_USER))
    expect(screen.getByLabelText('Note')).toHaveValue('buy less today')
  })

  it('is kept again when the session ends a second time before the restored draft was touched', async () => {
    session.signIn(TEST_USER)
    render(<Page name="twice" />)
    await userEvent.setup().type(screen.getByLabelText('Note'), 'abc')

    act(() => session.signOut())
    act(() => session.signIn(TEST_USER))
    act(() => session.signOut())
    act(() => session.signIn(TEST_USER))
    expect(screen.getByLabelText('Note')).toHaveValue('abc')
  })

  it('is not handed to another user, nor to another page of the same user', async () => {
    session.signIn(TEST_USER)
    const user = userEvent.setup()
    const first = render(<Page name="private" />)
    await user.type(screen.getByLabelText('Note'), 'mine')

    act(() => session.signOut())
    act(() => session.signIn(TEST_ADMIN))
    expect(screen.getByLabelText('Note')).toHaveValue('')
    first.unmount()

    act(() => session.signOut())
    act(() => session.signIn(TEST_USER))
    render(<Page name="another page" />)
    expect(screen.getByLabelText('Note')).toHaveValue('')
  })

  it('keeps nothing when the page is left while signed in', async () => {
    session.signIn(TEST_USER)
    const user = userEvent.setup()
    const first = render(<Page name="left" />)
    await user.type(screen.getByLabelText('Note'), 'never mind')
    first.unmount()

    render(<Page name="left" />)
    expect(screen.getByLabelText('Note')).toHaveValue('')
  })

  it('keeps nothing of a page that held no draft when the session ended', async () => {
    session.signIn(TEST_USER)
    const user = userEvent.setup()
    render(<Page name="cleared" />)
    await user.type(screen.getByLabelText('Note'), 'x')
    act(() => session.signOut())
    act(() => session.signIn(TEST_USER))
    await user.clear(screen.getByLabelText('Note'))

    act(() => session.signOut())
    act(() => session.signIn(TEST_USER))
    expect(screen.getByLabelText('Note')).toHaveValue('')
  })
})
