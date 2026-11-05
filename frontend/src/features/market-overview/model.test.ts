import { breadthMood, heatLevel, industryEnds, listedChange, rankIndustries } from './model'

const flat = { advancers: 0, decliners: 0, unchanged: 1 }
const ranked = (...changes: number[]) => rankIndustries(Object.fromEntries(changes.map((change, index) => [`產業${index}`, { ...flat, average_change_percent: change }])))

describe('the market breadth model', () => {
  it('ranks industries by their average change, strongest first, and equal ones by name', () => {
    const rows = rankIndustries({
      水泥工業: { ...flat, average_change_percent: 0 },
      半導體業: { ...flat, average_change_percent: -2.5 },
      航運業: { ...flat, average_change_percent: 1.2 },
      光電業: { ...flat, average_change_percent: 0 },
    })

    expect(rows.map((row) => row.industry)).toEqual(['航運業', ...['水泥工業', '光電業'].sort((a, b) => a.localeCompare(b)), '半導體業'])
  })

  it('names the session by how broad its move was', () => {
    expect(breadthMood({ advancers: 119, decliners: 1792, unchanged: 56, average_change_percent: -3.3 })).toBe('broadDown')
    expect(breadthMood({ advancers: 900, decliners: 800, unchanged: 100, average_change_percent: 0.1 })).toBe('mixed')
    expect(breadthMood({ advancers: 1500, decliners: 300, unchanged: 100, average_change_percent: 1.8 })).toBe('broadUp')
  })

  it('never calls the top of an all-falling day the leaders: it is the smallest declines, and the bottom the largest', () => {
    const ends = industryEnds(ranked(-0.65, -0.93, -0.94, -2, -5.11, -5.5, -6.09), 3)
    expect(ends.top.label).toBe('leastDown')
    expect(ends.bottom.label).toBe('losers')
    expect(ends.top.rows.map((row) => row.average_change_percent)).toEqual([-0.65, -0.93, -0.94])
  })

  it('names the ends by their sign on a rising day and on a split one', () => {
    expect(industryEnds(ranked(4, 3, 2, 1, 0.5, 0.2), 2)).toMatchObject({ top: { label: 'gainers' }, bottom: { label: 'leastUp' } })
    expect(industryEnds(ranked(2, -0.1, -0.2, -1, 0.3, -3), 2)).toMatchObject({ top: { label: 'gainers' }, bottom: { label: 'losers' } })
    expect(industryEnds(ranked(1, -0.5, -2, 0.4), 3)).toMatchObject({ top: { label: 'strongest' }, bottom: { label: 'weakest' } })
  })

  it('steps an industry’s heat by the size of its move, either way', () => {
    expect([0.2, -0.6, 1.5, -3.2, 7].map(heatLevel)).toEqual([0, 1, 2, 3, 4])
  })

  it('reads a listed stock’s change against the exchange’s reference price', () => {
    const change = listedChange({ ts: '2026-11-03T13:30:00+08:00', open: 102.5, high: 103.35, low: 100.5, close: 100.6, volume: 302407473, change: -3.5 })
    expect(change?.value).toBe(-3.5)
    expect(change?.ratio).toBeCloseTo(-3.5 / 104.1)
    expect(listedChange({ ts: '2026-11-03T13:30:00+08:00', open: 1, high: 1, low: 1, close: 1, volume: 1, change: null })).toBeNull()
  })
})
