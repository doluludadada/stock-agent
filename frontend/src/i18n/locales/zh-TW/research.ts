import type en from '../en/research'
import type { DictionaryShape } from '../../types'

const research: DictionaryShape<typeof en> = {
  signIn: '登入後用你的策略評估這檔股票',
  back: '返回',
  insufficient: '資料不足',
  loadFailed: '無法載入這檔股票。',
  technicalFailed: '無法載入技術評估。',
  market: { twse: '上市', tpex: '上櫃' },
  notFound: { title: '找不到代號 {{code}} 的上市櫃股票', description: '請從上方搜尋列以代號或名稱搜尋。' },
  chart: {
    title: '價格與成交量',
    question: '每日收盤、均線與成交量',
    sma: '{{period}} 日均線',
  },
  day: {
    title: '當日行情',
    question: '{{date}} 交易日',
    open: '開盤',
    high: '最高',
    low: '最低',
    previousClose: '昨收',
    amplitude: '振幅',
    volume: '成交量',
  },
  year: {
    title: '一年區間',
    question: '近 {{count}} 個交易日',
    low: '一年最低',
    high: '一年最高',
    fromHigh: '距最高',
    fromLow: '距最低',
  },
  evaluation: {
    title: '技術評估',
    lastBar: '最後一根 {{date}}',
    score: '分',
    passed: '通過',
    excluded: '排除',
    none: '策略無法評估這檔股票。',
    hard: '排除項目',
    soft: '扣分項目',
    observations: '加分檢查',
    noneListed: '無',
    details: '查看評估明細',
    detailsTitle: '評估明細',
    detailsQuestion: '哪些條件排除這檔股票、扣分或加分',
    detected: '有出現',
    notDetected: '未出現',
  },
  indicator: {
    title: '策略指標',
    question: '策略讀到的最後一根 K 線',
    showAll: '顯示全部 {{count}} 個指標',
    showLess: '收合',
  },
}

export default research
