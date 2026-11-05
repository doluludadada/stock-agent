import type en from '../en/watchlist'
import type { DictionaryShape } from '../../types'

const watchlist: DictionaryShape<typeof en> = {
  title: '觀察清單',
  description: '手動加入的股票不會過期；分析任務加入的會自行到期。',
  count: '顯示 {{count}} / {{total}} 檔',
  addedAt: '{{date}} 起',
  expires: '至 {{date}}',
  unknownName: '已不在上市櫃清單中',
  automaticOnly: '由分析任務加入',
  loadFailed: '無法載入觀察清單。',
  type: { manual: '手動', technical: '技術', buzz: '社群熱度' },
  action: {
    add: '加入觀察清單',
    remove: '移除',
    removeNamed: '把 {{name}} 從手動觀察清單移除',
    addStock: '加入',
  },
  add: { label: '要加入的股票代號', placeholder: '代號，例如 2330' },
  search: {
    label: '篩選觀察清單',
    placeholder: '以代號或名稱篩選',
    noMatch: '沒有符合的股票',
    noMatchHint: '換個代號或名稱試試。',
  },
  empty: {
    title: '觀察清單是空的',
    description: '用代號加入，或從個股頁加入。',
  },
  toast: {
    added: '已把 {{name}} 加入手動觀察清單',
    removed: '已把 {{name}} 從手動觀察清單移除',
    unlisted: '{{code}} 不是上市櫃股票，沒有加入任何股票。',
    failed: '觀察清單沒有變更：{{reason}}',
  },
}

export default watchlist
