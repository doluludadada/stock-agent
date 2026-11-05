import type en from '../en/overview'
import type { DictionaryShape } from '../../types'

const overview: DictionaryShape<typeof en> = {
  title: '市場總覽',
  session: '最近交易日 {{date}}',
  noData: '尚無資料',
  target: {
    default: '預設',
    index: '指數',
    change: '更換',
    reset: '改回{{name}}',
    notFound: '找不到上市櫃代號 {{id}}',
  },
  index: {
    taiex: '加權指數',
  },
  trend: {
    question: '區間收盤走勢與成交量',
    failed: '無法載入價格',
  },
  breadth: {
    title: '漲跌家數',
    question: '{{date}} 上市櫃共 {{total}} 檔',
    advancers: '上漲',
    decliners: '下跌',
    unchanged: '平盤',
    average: '平均漲跌',
    mood: { broadUp: '普遍上漲', leaningUp: '漲多跌少', mixed: '漲跌互見', leaningDown: '跌多漲少', broadDown: '普遍下跌' },
    failed: '無法載入漲跌家數',
  },
  industries: {
    title: '產業強弱',
    question: '{{count}} 個產業，依平均漲跌排序',
    column: { industry: '產業', moves: '漲 / 跌', average: '平均漲跌' },
    ends: {
      gainers: '漲幅最大',
      leastDown: '跌幅最小',
      strongest: '表現最強',
      losers: '跌幅最大',
      leastUp: '漲幅最小',
      weakest: '表現最弱',
    },
    moves: '漲 {{up}} · 跌 {{down}}',
    showAll: '顯示全部 {{count}} 個產業',
    showLess: '收合',
    none: '這個交易日沒有產業資料。',
  },
  mostTraded: {
    title: '成交熱絡',
    question: '{{date}} 成交量最大的股票',
    failed: '無法載入成交排行',
    empty: '最近交易日沒有成交資料。',
    showAll: '顯示全部 {{count}} 檔',
    showLess: '收合',
    column: { rank: '排名', stock: '股票', close: '收盤', change: '漲跌', volume: '成交量' },
  },
}

export default overview
