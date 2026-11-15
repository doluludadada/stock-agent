const world = {
  title: 'World',
  signIn: 'Sign in to read the world brief and news',
  failed: 'The world could not be loaded.',
  today: { all: 'Brief and news' },
  indicators: {
    title: 'Indicators',
    none: 'No indicator is held yet.',
    source: 'Taiwan Futures Exchange reference rates and US Treasury par yields, one reading a day.',
    points: 'pt',
    name: {
      usd_twd: 'USD/TWD',
      usd_jpy: 'USD/JPY',
      eur_usd: 'EUR/USD',
      usd_cny: 'USD/CNY',
      us_10y_yield: 'US 10-year yield',
      us_2y_yield: 'US 2-year yield',
    },
  },
  brief: {
    title: 'World brief',
    older: 'Earlier brief',
    newer: 'Later brief',
    window: 'News from {{first}} to {{last}}.',
    writtenIn: {
      'zh-TW': 'Written in Traditional Chinese.',
      en: 'Written in English.',
    },
    citation: {
      indicator: 'Indicator · {{date}}',
      item: '{{publisher}} · {{date}}',
      news: 'World news',
    },
    waiting: {
      title: 'No world brief yet',
      description: 'One a day, written from {{time}} Taipei.',
    },
    off: {
      title: 'This site writes no world brief',
      description: 'Its own AI writing is off.',
    },
  },
  news: {
    title: 'World news',
    filter: 'Publisher',
    allSources: 'All',
    showAll: 'Show all {{count}}',
    showLess: 'Show fewer',
    none: {
      title: 'No world news is held yet',
      description: 'The site reads the publishers’ feeds on a timer.',
    },
  },
}

export default world
