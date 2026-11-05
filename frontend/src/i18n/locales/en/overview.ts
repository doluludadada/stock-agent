const overview = {
  title: 'Market overview',
  session: 'Latest session {{date}}',
  noData: 'No data yet',
  target: {
    default: 'Default',
    index: 'Index',
    change: 'Change',
    reset: 'Back to the {{name}}',
    notFound: 'No listed stock with code {{id}}',
  },
  index: {
    taiex: 'TAIEX',
  },
  trend: {
    question: 'Closes over the range, and volume',
    failed: 'Prices could not be loaded',
  },
  breadth: {
    title: 'Advancers and decliners',
    question: '{{total}} listed stocks on {{date}}',
    advancers: 'Up',
    decliners: 'Down',
    unchanged: 'Unchanged',
    average: 'Average change',
    mood: { broadUp: 'Broadly up', leaningUp: 'Leaning up', mixed: 'Mixed', leaningDown: 'Leaning down', broadDown: 'Broadly down' },
    failed: 'The breadth could not be loaded',
  },
  industries: {
    title: 'Industries',
    question: '{{count}} industries by average change',
    column: { industry: 'Industry', moves: 'Up / down', average: 'Average change' },
    ends: {
      gainers: 'Largest gains',
      leastDown: 'Smallest declines',
      strongest: 'Strongest',
      losers: 'Largest declines',
      leastUp: 'Smallest gains',
      weakest: 'Weakest',
    },
    moves: '{{up}} up · {{down}} down',
    showAll: 'Show all {{count}} industries',
    showLess: 'Show fewer',
    none: 'No industry data for this session.',
  },
  mostTraded: {
    title: 'Most traded',
    question: 'The largest volume on {{date}}',
    failed: 'The most traded stocks could not be loaded',
    empty: 'No trades in the latest session.',
    showAll: 'Show all {{count}}',
    showLess: 'Show fewer',
    column: { rank: 'Rank', stock: 'Stock', close: 'Close', change: 'Change', volume: 'Volume' },
  },
}

export default overview
