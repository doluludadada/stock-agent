import type { DictionaryShape } from '../../types'
import type en from '../en/world'

const world: DictionaryShape<typeof en> = {
  title: '國際局勢',
  signIn: '登入後即可閱讀國際局勢摘要與新聞',
  failed: '無法載入國際局勢。',
  today: { all: '摘要與新聞' },
  indicators: {
    title: '指標',
    none: '目前還沒有保存任何指標。',
    source: '臺灣期貨交易所參考匯率與美國財政部公債殖利率，每日一筆。',
    points: '個百分點',
    name: {
      usd_twd: '美元／新台幣',
      usd_jpy: '美元／日圓',
      eur_usd: '歐元／美元',
      usd_cny: '美元／人民幣',
      us_10y_yield: '美國 10 年期公債殖利率',
      us_2y_yield: '美國 2 年期公債殖利率',
    },
  },
  brief: {
    title: '國際局勢摘要',
    older: '較早的摘要',
    newer: '較新的摘要',
    window: '新聞範圍：{{first}} 至 {{last}}。',
    writtenIn: {
      'zh-TW': '以繁體中文撰寫。',
      en: '以英文撰寫。',
    },
    citation: {
      indicator: '指標 · {{date}}',
      item: '{{publisher}} · {{date}}',
      news: '國際新聞',
    },
    waiting: {
      title: '還沒有國際局勢摘要',
      description: '每天一篇，台北時間 {{time}} 起撰寫。',
    },
    off: {
      title: '本站不寫國際局勢摘要',
      description: '網站自己的 AI 撰寫功能目前關閉。',
    },
  },
  news: {
    title: '國際新聞',
    filter: '來源',
    allSources: '全部',
    showAll: '顯示全部 {{count}} 則',
    showLess: '顯示較少',
    none: {
      title: '目前還沒有保存任何國際新聞',
      description: '網站會定時讀取各新聞來源。',
    },
  },
}

export default world
