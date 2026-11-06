/**
 * The rule names of the built-in strategies (config/strategies) in Traditional Chinese, keyed by the English name
 * exactly as the backend sends it. The names hold `.` and `:`, so they are looked up as text, never as i18next keys.
 */
const ruleNames: ReadonlyMap<string, string> = new Map(
  Object.entries({
    'Price Above MA_20': '股價站上 20 日均線',
    'Price Above MA_60': '股價站上 60 日均線',
    'MA_20 > MA_60 Alignment': '均線多頭排列（20 日 > 60 日）',
    'Golden Cross': '黃金交叉',
    'MACD Bullish (line > signal)': 'MACD 多頭（快線 > 訊號線）',
    'MACD Bullish (line > signal, line > 0)': 'MACD 多頭（快線 > 訊號線、快線 > 0）',
    'MACD Bullish (line > 0, histogram > 0)': 'MACD 多頭（快線 > 0、柱狀體 > 0）',
    'MACD Bullish (histogram > 0)': 'MACD 多頭（柱狀體 > 0）',
    'RSI Range 0-80': 'RSI 區間 0–80',
    'RSI Range 0-85': 'RSI 區間 0–85',
    'RSI Range 50-65': 'RSI 區間 50–65',
    'RSI Range 50-70': 'RSI 區間 50–70',
    'RSI Range 50-100': 'RSI 區間 50–100',
    'Stochastic Health (K < 80)': 'KD 健康（K < 80）',
    'Stochastic Health (K > D)': 'KD 健康（K > D）',
    'Stochastic Health (K < 80, K > D)': 'KD 健康（K < 80、K > D）',
    'Bollinger %B < 0.85': '布林通道 %B < 0.85',
    'Bollinger %B < 0.9': '布林通道 %B < 0.9',
    'Bollinger Squeeze < 0.1': '布林通道收窄（帶寬 < 0.1）',
    'Bollinger Above Middle': '股價站上布林通道中軌',
    'ADX Trend 20-50 with Bullish Direction': 'ADX 趨勢 20–50 且方向偏多',
    'ATR Range': 'ATR 區間',
    'MFI < 80': 'MFI < 80',
    'OBV Trend': 'OBV 走揚',
    'Volume Expansion >= 0.5x vs MA_5': '量能放大（≥ 5 日均量 0.5 倍）',
    'Volume Expansion >= 0.7x vs MA_5': '量能放大（≥ 5 日均量 0.7 倍）',
    'Volume Expansion >= 0.8x vs MA_5': '量能放大（≥ 5 日均量 0.8 倍）',
    'Volume Expansion >= 1.0x vs MA_5': '量能放大（≥ 5 日均量 1.0 倍）',
    'Volume Expansion >= 1.5x vs MA_5': '量能放大（≥ 5 日均量 1.5 倍）',
    'Daily Range Safety': '單日振幅安全',
    'Liquidity Check': '流動性檢查',
    'Minimum Price Check': '最低股價檢查',
  }),
)

export default ruleNames
