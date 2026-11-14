import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { initI18n } from '@/i18n'
import { RouteErrorBoundary } from './RouteFallbacks'

function Broken(): never {
  throw new Error('broken page')
}

describe('a page that broke', () => {
  it.each([
    ['zh-TW', '回到首頁'],
    ['en', 'Back to the home page'],
  ] as const)('offers one way on in %s, and it leads where it says: the home page', async (locale, label) => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const i18n = initI18n(locale)
    await i18n.changeLanguage(locale)
    const router = createMemoryRouter([{ path: '/market', element: <Broken />, errorElement: <RouteErrorBoundary /> }], { initialEntries: ['/market'] })
    render(
      <I18nextProvider i18n={i18n}>
        <RouterProvider router={router} />
      </I18nextProvider>,
    )

    const links = await screen.findAllByRole('link')
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([[label, '/']])
    expect(screen.queryByText(/市場總覽|overview/i)).not.toBeInTheDocument()
    vi.restoreAllMocks()
  })
})
