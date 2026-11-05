const watchlist = {
  title: 'Watchlist',
  description: 'Manual entries never expire; entries added by runs expire on their own.',
  count: '{{count}} of {{total}} stocks shown',
  addedAt: 'since {{date}}',
  expires: 'until {{date}}',
  unknownName: 'No longer in the listing',
  automaticOnly: 'Added by a run',
  loadFailed: 'The watchlist could not be loaded.',
  type: { manual: 'Manual', technical: 'Technical', buzz: 'Buzz' },
  action: {
    add: 'Add to watchlist',
    remove: 'Remove',
    removeNamed: 'Remove {{name}} from the manual watchlist',
    addStock: 'Add',
  },
  add: { label: 'Stock code to add', placeholder: 'Code, e.g. 2330' },
  search: {
    label: 'Filter the watchlist',
    placeholder: 'Filter by code or name',
    noMatch: 'No stock matches',
    noMatchHint: 'Try another code or name.',
  },
  empty: {
    title: 'Your watchlist is empty',
    description: 'Add a stock by its code or from a stock page.',
  },
  toast: {
    added: '{{name}} added to the manual watchlist',
    removed: '{{name}} removed from the manual watchlist',
    unlisted: '{{code}} is not a listed stock; nothing was added.',
    failed: 'The watchlist did not change: {{reason}}',
  },
}

export default watchlist
