import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { StockChip, StockLink } from './stock-name'

describe('a stock’s name and code', () => {
  it('links the name and the code to the stock’s page, with what the row adds', () => {
    render(
      <MemoryRouter>
        <StockLink stockId="2330" name="台積電" badge={<span>new</span>}>
          <span>second line</span>
        </StockLink>
      </MemoryRouter>,
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '/stocks/2330')
    expect(link).toHaveTextContent('台積電2330newsecond line')
  })

  it('shows the code once where the listing has no name, and the caller’s words where it gives some', () => {
    render(
      <MemoryRouter>
        <StockLink stockId="9999" name={null} />
        <StockLink stockId="8888" name={undefined} unnamed="No longer listed" />
        <StockChip stockId="7777" name={null} />
      </MemoryRouter>,
    )
    expect(screen.getAllByRole('link').map((link) => link.textContent)).toEqual(['9999', 'No longer listed8888', '7777'])
  })
})
