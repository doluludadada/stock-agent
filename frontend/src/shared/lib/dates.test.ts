import { isIsoDate, monthsBefore, periodProblems } from './dates'

describe('calendar days', () => {
  it('counts months back across a year and onto a shorter month', () => {
    expect(monthsBefore('2026-02-10', 3)).toBe('2025-11-10')
    expect(monthsBefore('2026-05-31', 3)).toBe('2026-02-28')
    expect(monthsBefore('2024-05-31', 3)).toBe('2024-02-29')
    expect(monthsBefore('2024-02-29', 12), 'a leap day a year back is the month’s last day').toBe('2023-02-28')
  })

  it('takes only a real day written YYYY-MM-DD', () => {
    expect(isIsoDate('2024-10-31')).toBe(true)
    expect(isIsoDate('2023-13-01')).toBe(false)
    expect(isIsoDate('31/10/2024')).toBe(false)
    expect(isIsoDate('')).toBe(false)
    expect(isIsoDate(null)).toBe(false)
  })

  it('says what is wrong with two typed days at the field that is wrong', () => {
    const bounds = { first: '2024-01-02', last: '2026-11-11' }
    expect(periodProblems({ first: '2025-01-01', last: '2025-06-30' }, bounds)).toEqual({})
    expect(periodProblems({ first: '', last: 'soon' }, bounds)).toEqual({ first: 'dateRequired', last: 'dateRequired' })
    expect(periodProblems({ first: '2023-12-31', last: '2026-11-12' }, bounds)).toEqual({ first: 'beforeFirst', last: 'afterLast' })
    expect(periodProblems({ first: '2025-06-30', last: '2025-01-01' }, bounds)).toEqual({ last: 'firstAfterLast' })
    expect(periodProblems({ first: '2000-01-01', last: '2025-01-01' }, { last: '2026-11-11' }), 'no first bound').toEqual({})
  })
})
