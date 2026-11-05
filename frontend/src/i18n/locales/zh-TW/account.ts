import type en from '../en/account'
import type { DictionaryShape } from '../../types'

const account: DictionaryShape<typeof en> = {
  title: '模擬帳戶',
  description: '交易流程使用的帳戶與每日權益。',
  loadFailed: '無法載入帳戶。',
  provider: { mock: '模擬券商', shioaji: '永豐 Shioaji' },
  orderMode: { mock_only: '模擬下單', live: '實際下單', disabled: '不下單' },
  mockNotice: '模擬券商維護的紙上帳戶，不是真實資產。',
  brokerNotice: '讀取設定中的永豐帳戶；網頁不會在此下單。',
  valueTitle: '帳戶價值',
  value: { equity: '總權益', cash: '現金', marketValue: '持股市值', unrealized: '未實現損益' },
  positionsTitle: '持股',
  noPositions: '目前沒有持股。',
  column: {
    stock: '股票',
    quantity: '股數',
    averageCost: '平均成本',
    markPrice: '價格',
    markedAt: '計價時間',
    marketValue: '市值',
    unrealized: '未實現',
  },
  unpriced: '沒有報價，以平均成本計',
  realtime: '即時報價',
  dailyClose: '最近日收盤',
  curveTitle: '每日收盤權益',
  noCurve: '還沒有成交，因此沒有權益曲線。',
  asOfLabel: '查看某日的帳戶',
  asOfHint: '選擇日期，查看當天收盤時的帳戶。',
  asOfShow: '查看',
  asOfNone: '{{date}} 當天或之前沒有任何成交。',
  asOfTitle: '截至 {{time}}（當日最後一筆成交）',
}

export default account
