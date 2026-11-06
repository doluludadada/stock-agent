import type en from '../en/attribution'
import type { DictionaryShape } from '../../types'

const attribution: DictionaryShape<typeof en> = {
  title: '資料來源與授權',
  description: '本站使用下列機關的開放資料，並依下方授權條款標示來源。',
  failed: '無法載入資料來源。',
  provider: { question: '本站使用的 {{count}} 項資料集' },
  license: { title: '授權條款', question: '開放資料釋出所依據的條款' },
}

export default attribution
