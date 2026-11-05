const research = {
  back: 'Back',
  insufficient: 'Not enough data',
  loadFailed: 'This stock could not be loaded.',
  technicalFailed: 'The technical evaluation could not be loaded.',
  market: { twse: 'TWSE', tpex: 'TPEX' },
  notFound: { title: 'No listed stock with code {{code}}', description: 'Search by code or name from the top bar.' },
  chart: {
    title: 'Price and volume',
    sma: '{{period}}-day MA',
  },
  indicator: {
    title: 'Strategy indicators',
  },
  evaluation: {
    title: 'Technical evaluation',
    lastBar: 'Last bar {{date}}',
    score: 'Score',
    passed: 'Passes',
    excluded: 'Excluded',
    none: 'The strategy could not evaluate this stock.',
    hard: 'Exclusions',
    soft: 'Deductions',
    observations: 'Bonus checks',
    noneListed: 'None',
  },
}

export default research
