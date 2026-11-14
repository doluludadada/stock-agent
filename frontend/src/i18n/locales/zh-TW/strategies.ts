import type en from '../en/strategies'
import type { DictionaryShape } from '../../types'

const strategies: DictionaryShape<typeof en> = {
  signIn: '登入後保存並使用你自己的策略',
  untitled: '未命名策略',
  copyName: '{{name}} 副本',
  bars: '{{count}} 根日 K',
  effect: {
    block_on_fail: '未通過即排除',
    reduce_score_on_fail: '未通過扣分',
    increase_score_on_pass: '通過加分',
  },
  builtin: {
    balanced: {
      apiName: 'Balanced',
      name: '平衡型',
      purpose: '23 條規則。趨勢、MACD、RSI 50–80 與流動性必須通過；ADX、布林、MFI、ATR 調整分數，黃金交叉或 OBV 走揚加分。',
    },
  },
  inUse: '使用中',
  meta: '{{rules}} 條規則 · 需要 {{bars}} 根日 K',
  library: {
    title: '策略庫',
    inUseTitle: '使用中的策略',
    customInUse: '所有流程都使用你的策略「{{name}}」。',
    customTitle: '我的策略',
    empty: '還沒有。複製一套內建策略再調整，或新增空白策略。',
    loadFailed: '無法載入策略。',
  },
  action: {
    activate: '使用',
    edit: '編輯',
    viewRules: '查看規則',
    duplicate: '建立副本',
    copyNamed: '複製 {{name}}',
    deleteNamed: '刪除 {{name}}',
    create: '新增策略',
    createBlank: '空白策略',
    createShort: '新增',
  },
  sheet: {
    noDescription: '沒有說明。',
    rules: '{{count}} 條規則',
    indicators: '指標設定',
    requiredBars: '需要的完整日 K 數',
    baseScore: '基礎分數',
  },
  toast: {
    activated: '已改用「{{name}}」',
    deleted: '已刪除「{{name}}」',
    full: '策略數量已達上限，請先刪除一套。',
    saved: '已儲存，版本 {{revision}}',
    conflict: '其他分頁或裝置先儲存了，已載入最新設定；請再做一次你的變更。',
    failed: '沒有儲存：{{reason}}',
  },
  delete: {
    title: '要刪除「{{name}}」嗎？',
    description: '策略會被刪除，內建策略仍在。',
    cancel: '保留',
    confirm: '刪除',
    selected: '使用中的策略不能刪除，請先改用其他策略。',
    last: '最後一套策略不能刪除。',
  },
}

export default strategies
