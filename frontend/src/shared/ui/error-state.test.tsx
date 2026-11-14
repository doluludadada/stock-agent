import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { ApiError } from '@/shared/api'
import { ErrorState } from './error-state'

async function renderError(error: unknown, locale: 'en' | 'zh-TW') {
  const i18n = initI18n(locale)
  await i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <ErrorState error={error} title="Title" />
    </I18nextProvider>,
  )
}

const refusal = (status: number, kind: ApiError['kind'], code: string, detail: string) => new ApiError(kind, status, detail, [], null, { detail, code })

describe('a failed request said to the reader', () => {
  it('says a refusal by its code in the reader’s language, never in the server’s English', async () => {
    await renderError(refusal(429, 'rateLimited', 'too_many_runs', 'You started too many runs this hour.'), 'zh-TW')

    expect(screen.getByText('目前已達分析次數上限，請稍後再試。')).toBeVisible()
    expect(screen.queryByText(/You started too many runs/)).not.toBeInTheDocument()
  })

  it('says the same refusal in English to an English reader, in the app’s words', async () => {
    await renderError(refusal(429, 'rateLimited', 'too_many_runs', 'You started too many runs this hour.'), 'en')

    expect(screen.getByText('You have reached the limit of runs for now. Try again later.')).toBeVisible()
    expect(screen.queryByText(/You started too many runs/)).not.toBeInTheDocument()
  })

  it('falls back to the words of the kind of failure for a code it has no words for', async () => {
    await renderError(refusal(403, 'forbidden', 'a_code_from_a_newer_server', 'This account may not do that.'), 'zh-TW')

    expect(screen.getByText('伺服器拒絕這個操作。')).toBeVisible()
    expect(screen.queryByText(/This account may not do that/)).not.toBeInTheDocument()
  })

  it('says an error that did not come from the server as a server failure', async () => {
    await renderError(new Error('undefined is not a function'), 'en')

    expect(screen.getByText('The server could not finish this request.')).toBeVisible()
  })
})
