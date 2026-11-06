import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import type { Attribution } from './api'
import { AttributionPage } from './AttributionPage'

const attribution: Attribution = {
  providers: [
    { provider: '臺灣證券交易所', datasets: ['上市個股日成交資訊', '上市公司每月營業收入彙總表'] },
    { provider: '證券櫃檯買賣中心', datasets: ['上櫃股票行情'] },
  ],
  notice: '此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。',
  license: '政府資料開放授權條款－第1版',
  license_url: 'https://data.gov.tw/license',
}

describe('the data sources page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('credits every provider with each dataset the site reads, the license’s notice, its name and its address, as the server gives them', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(attribution), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    render(
      <I18nextProvider i18n={initI18n('zh-TW')}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <AttributionPage />
        </QueryClientProvider>
      </I18nextProvider>,
    )

    const twse = await screen.findByRole('region', { name: '臺灣證券交易所' })
    expect(within(twse).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['上市個股日成交資訊', '上市公司每月營業收入彙總表'])
    expect(within(screen.getByRole('region', { name: '證券櫃檯買賣中心' })).getByText('上櫃股票行情')).toBeInTheDocument()
    const license = screen.getByRole('region', { name: '授權條款' })
    expect(within(license).getByRole('link', { name: '政府資料開放授權條款－第1版' })).toHaveAttribute('href', 'https://data.gov.tw/license')
    expect(within(license).getByText('https://data.gov.tw/license')).toBeInTheDocument()
    expect(within(license).getByText(attribution.notice)).toBeInTheDocument()
  })
})
