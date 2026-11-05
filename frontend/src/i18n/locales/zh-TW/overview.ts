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
    failed: '無法載入價格',
  },
  breadth: {
    title: '市場廣度',
    advancers: '上漲',
    decliners: '下跌',
    unchanged: '平盤',
    average: '平均漲跌',
    sectors: '產業漲跌',
    column: { industry: '產業', moves: '漲 / 跌', average: '平均漲跌' },
    showAll: '顯示全部 {{count}} 個產業',
    showLess: '收合',
    noIndustries: '這個交易日沒有產業資料。',
    failed: '無法載入市場廣度',
  },
  mostTraded: {
    title: '成交熱絡',
    failed: '無法載入成交排行',
    empty: '最近交易日沒有成交資料。',
    showAll: '顯示全部 {{count}} 檔',
    showLess: '收合',
    column: { stock: '股票', close: '收盤', volume: '成交量' },
  },
}

export default overview
