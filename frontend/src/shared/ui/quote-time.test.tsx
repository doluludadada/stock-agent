import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { QuoteTime } from './quote-time'

describe('when a shown price is from', () => {
  const show = (tradedAt: string | null, live: boolean) =>
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QuoteTime session="2026-11-13" tradedAt={tradedAt} live={live} />
      </I18nextProvider>,
    )

  it('says the session of a settled close, with no live mark', () => {
    const { container } = show(null, true)
    expect(container).toHaveTextContent('11/13 close')
    expect(screen.queryByTestId('quote-time')).toBeNull()
  })

  it('says the last trade’s Taipei time with the live mark while the session trades, and without it afterwards', () => {
    const live = show('2026-11-16T02:32:05Z', true)
    expect(screen.getByTestId('quote-time')).toHaveTextContent('Live 10:32')
    expect(screen.getByTestId('quote-time').querySelector('[aria-hidden]')).not.toBeNull()
    live.unmount()

    show('2026-11-16T13:30:00+08:00', false)
    expect(screen.getByTestId('quote-time')).toHaveTextContent('Last trade 13:30')
    expect(screen.getByTestId('quote-time').querySelector('[aria-hidden]')).toBeNull()
  })
})
