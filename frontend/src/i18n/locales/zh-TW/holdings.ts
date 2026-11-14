import type en from '../en/holdings'
import type { DictionaryShape } from '../../types'

const holdings: DictionaryShape<typeof en> = {
  title: '我的持股',
  signIn: '登入後查看你的持股',
  loadFailed: '無法載入你的持股。',
  unknownName: '已不在上市櫃清單中',
  source: { brokerage: '永豐金證券庫存', manual: '手動輸入', mock: '模擬帳戶（虛擬資金）' },
  filter: { label: '計入的持股來源' },
  loginDown: '本站的永豐金連線中斷，這裡沒有計入永豐金證券帳戶的庫存。',
  noClose: '沒有收盤價，以成本計',
  empty: {
    title: '還沒有持股',
    description: '輸入你在別處持有的股票。只是紀錄，不會下單。',
  },
  noDecision: {
    title: '還沒有月排行的決策',
    description: '日線資料還沒有涵蓋決策日，暫時無法評分。仍可先輸入持股。',
  },
  action: { add: '輸入持股', change: '修改這筆紀錄', remove: '移除這筆紀錄', manage: '{{name}} 的紀錄' },
  today: {
    all: '全部持股',
    enter: '輸入持股',
    empty: '輸入持股後，這裡顯示市值與損益。',
  },
  summary: {
    marketValue: '持股市值',
    unrealized: '未實現損益',
    cost: '成本',
    concentration: '前 {{count}} 大占比',
    topShare: '在本月排名中的占比',
    weightedScore: '市值加權分數',
    unscored: '{{share}} 的市值沒有分數',
  },
  list: { title: '持股明細', none: '所選來源沒有持股。', count: '{{count}} 筆' },
  column: {
    stock: '股票',
    held: '股數 · 成本均價',
    close: '最近收盤',
    value: '市值 · 占比',
    unrealized: '未實現損益',
    score: '排行分數',
    revenue: '營收加速度',
    actions: '紀錄',
  },
  row: {
    held: '{{shares}} 股 @ {{cost}}',
    valued: '市值 {{value}} · 占比 {{weight}}',
    closed: '{{price}}，{{close}}',
    revenue: '營收加速度 {{figure}}',
    revenueRun: '營收加速度 {{figure}}，{{line}}',
  },
  revenue: {
    accelerating: '連續 {{count}} 個月高於 1',
    slowing: '連續 {{count}} 個月低於 1',
    short: '保存的月份不足以計算平均',
    none: '沒有月營收資料',
  },
  watched: {
    title: '從觀察清單加入',
    enter: '把 {{name}} 輸入為持股',
    more: '還有 {{count}} 檔',
  },
  form: {
    addTitle: '輸入持股',
    changeTitle: '修改紀錄',
    description: '只是紀錄，不會下單。',
    stock: '股票',
    chooseStock: '選擇股票',
    changeStock: '改選其他股票',
    quantity: '股數',
    quantityHint: '以股為單位，1 張是 1,000 股。',
    averageCost: '每股成本均價（新台幣）',
    openedOn: '買進日期（選填）',
    problem: {
      stockId: '請從上市櫃清單選擇股票。',
      quantity: '請輸入 1 到 {{quantity}} 的整數股數。',
      averageCost: '成本須大於 0，最高 {{averageCost}}。',
      openedOn: '日期不能晚於今天。',
    },
    refusal: {
      unlisted: '{{code}} 不在上市櫃清單中，沒有儲存。',
      failed: '沒有儲存。{{reason}}',
    },
    save: '儲存紀錄',
    saving: '儲存中…',
    saved: '已儲存 {{name}} 的紀錄。',
    cancel: '取消',
  },
  remove: {
    title: '要移除 {{name}} 的紀錄嗎？',
    description: '只移除這筆紀錄，不會下單。',
    done: '已移除 {{name}} 的紀錄。',
    failed: '沒有移除。{{reason}}',
  },
}

export default holdings
