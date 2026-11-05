import { breadthShares, rankIndustries } from './model'

const flat = { advancers: 0, decliners: 0, unchanged: 1 }

describe('the market breadth model', () => {
  it('ranks industries by their average change, strongest first, and equal ones by name', () => {
    const ranked = rankIndustries({
      水泥工業: { ...flat, average_change_percent: 0 },
      半導體業: { ...flat, average_change_percent: -2.5 },
      航運業: { ...flat, average_change_percent: 1.2 },
      光電業: { ...flat, average_change_percent: 0 },
    })

    expect(ranked.map((row) => row.industry)).toEqual(['航運業', ...['水泥工業', '光電業'].sort((a, b) => a.localeCompare(b)), '半導體業'])
  })

  it('splits the session into shares that add up to 100', () => {
    expect(breadthShares({ advancers: 1, decliners: 2, unchanged: 1, average_change_percent: 0 })).toEqual({ up: 25, flat: 25, down: 50 })
    expect(breadthShares({ advancers: 0, decliners: 0, unchanged: 0, average_change_percent: 0 })).toEqual({ up: 0, flat: 0, down: 0 })
  })
})
