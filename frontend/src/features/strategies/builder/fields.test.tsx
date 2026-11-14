import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import type { ValidationIssue } from '../model/validate'
import { DayField } from './fields'

const OUT_OF_RANGE: ValidationIssue = { path: 'days', code: 'outOfRange', severity: 'error', params: { min: 0, max: 250 } }

function renderDay(value: number, issue?: ValidationIssue) {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <DayField value={value} onChange={() => undefined} issue={issue} />
    </I18nextProvider>,
  )
}

describe('the trading-day field with a custom number of days', () => {
  it('marks the number invalid and describes it by the error, which is said once', () => {
    renderDay(999, OUT_OF_RANGE)

    const days = screen.getByRole('textbox', { name: 'Trading days ago' })
    expect(days).toHaveAttribute('aria-invalid', 'true')
    expect(days).toHaveAccessibleDescription('Use a value from 0 to 250.')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })

  it('marks nothing while the number has no issue', () => {
    renderDay(5)

    const days = screen.getByRole('textbox', { name: 'Trading days ago' })
    expect(days).not.toHaveAttribute('aria-invalid')
    expect(days).toHaveAccessibleDescription('')
  })
})
