import type en from '../en/watchlist'
import type { DictionaryShape } from '../../types'

const watchlist: DictionaryShape<typeof en> = {
  today: { all: '完整清單' },
  signIn: '登入後查看你的觀察清單',
  title: '觀察清單',
  addedAt: '{{date}} 加入',
  expires: '至 {{date}}',
  unknownName: '已不在上市櫃清單中',
  automaticOnly: '由分析任務加入',
  loadFailed: '無法載入觀察清單。',
  type: { manual: '手動', technical: '技術', buzz: '社群熱度' },
  action: {
    add: '加入觀察清單',
    remove: '移除',
    removeNamed: '把 {{name}} 從手動觀察清單移除',
    addStock: '加入股票',
    signInToWatch: '登入後加入觀察清單',
    watching: '已在觀察清單',
    edit: '編輯',
    doneEditing: '完成',
  },
  search: {
    label: '篩選觀察清單',
    placeholder: '代號或名稱',
    noMatch: '沒有符合的股票',
    noMatchHint: '換個代號或名稱試試。',
  },
  filter: { label: '來源', all: '全部' },
  sort: { label: '排序', change: '依漲跌幅', code: '依代號', added: '依加入時間' },
  column: { stock: '股票', trend: '近一個月', close: '收盤', change: '漲跌', source: '來源', actions: '操作' },
  summary: {
    title: '收盤表現',
    question: '{{date}} 收盤',
    waiting: '你的股票在最近一個交易日的表現',
    withNote: '{{main}}。{{note}}。',
    pending: '還在載入 {{count}} 檔的報價',
    earlier: '另有 {{count}} 檔的最後收盤在較早的交易日，未計入',
    moves: '漲跌家數',
    up: '{{count}} 漲',
    down: '{{count}} 跌',
    flat: '{{count}} 平',
    average: '平均漲跌',
    best: '表現最好',
    worst: '表現最弱',
  },
  list: { title: '股票' },
  empty: {
    title: '觀察清單是空的',
    description: '加入股票，追蹤它的收盤與近一個月走勢。',
  },
  toast: {
    added: '已把 {{name}} 加入手動觀察清單',
    removed: '已把 {{name}} 從手動觀察清單移除',
    unlisted: '{{code}} 不是上市櫃股票，沒有加入任何股票。',
    failed: '觀察清單沒有變更：{{reason}}',
  },
}

export default watchlist
