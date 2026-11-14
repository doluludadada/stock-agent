import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { ConfirmDialog } from './confirm-dialog'

/** A dialog that stays open after the yes until its caller closes it, as one does while it closes or its action runs. */
function Question({ onConfirm }: { onConfirm: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Ask
      </button>
      <ConfirmDialog open={open} title="Delete it?" description="This cannot be undone." cancel="Cancel" confirm="Delete" onConfirm={onConfirm} onCancel={() => setOpen(false)} />
    </>
  )
}

describe('the confirm dialog', () => {
  it('confirms once for two quick presses, and again the next time it is opened', async () => {
    const confirmed = vi.fn()
    const user = userEvent.setup()
    render(<Question onConfirm={confirmed} />)

    await user.click(screen.getByRole('button', { name: 'Ask' }))
    const yes = await screen.findByRole('button', { name: 'Delete' })
    fireEvent.click(yes)
    fireEvent.click(yes)
    expect(confirmed).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Ask', hidden: true }))
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(confirmed).toHaveBeenCalledTimes(2)
  })
})
