import type en from '../en/research'
import type { DictionaryShape } from '../../types'

const research: DictionaryShape<typeof en> = {
  back: '返回',
  insufficient: '資料不足',
  loadFailed: '無法載入這檔股票。',
  technicalFailed: '無法載入技術評估。',
  market: { twse: '上市', tpex: '上櫃' },
  notFound: { title: '找不到代號 {{code}} 的上市櫃股票', description: '請從上方搜尋列以代號或名稱搜尋。' },
  chart: {
    title: '價格與成交量',
    sma: '{{period}} 日均線',
  },
  indicator: {
    title: '策略指標',
  },
  evaluation: {
    title: '技術評估',
    lastBar: '最後一根 {{date}}',
    score: '分數',
    passed: '通過',
    excluded: '排除',
    none: '策略無法評估這檔股票。',
    hard: '排除項目',
    soft: '扣分項目',
    observations: '加分檢查',
    noneListed: '無',
  },
}

export default research
