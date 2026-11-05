const overview = {
  title: 'Market overview',
  session: 'Last session {{date}}',
  noData: 'No data yet',
  target: {
    default: 'Default',
    index: 'Index',
    change: 'Change',
    reset: 'Back to {{name}}',
    notFound: 'No listed stock {{id}}',
  },
  index: {
    taiex: 'TAIEX',
  },
  trend: {
    failed: 'Prices did not load',
  },
  breadth: {
    title: 'Market breadth',
    advancers: 'Advancers',
    decliners: 'Decliners',
    unchanged: 'Unchanged',
    average: 'Average',
    sectors: 'Industry moves',
    column: { industry: 'Industry', moves: 'Up / down', average: 'Average' },
    showAll: 'Show all {{count}} industries',
    showLess: 'Show fewer',
    noIndustries: 'No industry data for this session.',
    failed: 'Market breadth did not load',
  },
  mostTraded: {
    title: 'Most traded',
    failed: 'Most traded did not load',
    empty: 'No trades for the last session.',
    showAll: 'Show all {{count}}',
    showLess: 'Show fewer',
    column: { stock: 'Stock', close: 'Close', volume: 'Volume' },
  },
}

export default overview
