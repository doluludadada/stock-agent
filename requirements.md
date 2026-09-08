## 產品目標

建立一套以台灣上市櫃股票為主的分析系統，整合：

- 技術分析
- 新聞與市場情緒
- 基本面資料
- EPS 與本益比估值
- 觀察清單
- 模擬交易
- AI 分析與解釋

AI 應負責解釋與整理資料，而不是自行捏造 EPS、股價或財務數字。

---

# Epic 1：完成現有核心交易流程

## US-001 計算技術分析分數

**優先級：P0**

作為使用者，  
我希望每一支經過技術篩選的股票都有技術分數，  
以便系統能夠計算綜合分數並產生交易訊號。

### 驗收條件

- 每支完成技術篩選的股票都具有 `technical_score`。
- 分數介於 0 到 100。
- hard failure、soft failure 與技術指標加分會反映在分數中。

目前已經存在 `TechnicalScoreCalculator`，但 `TechnicalFilter` 尚未使用它；同時 `Signals` 會直接跳過沒有技術分數的股票
然後我想重新研究我目前的Domain layer 這些models設計是否得當
會不會拆分太細
然後考慮到appsetting.yaml、strategies.yaml 這些檔案，關於技術計分的config設定

---

## US-002 儲存技術分析觀察清單

**優先級：P0**

作為使用者，  
我希望完整市場掃描通過的股票被標記為 `TECHNICAL` 並儲存，  
以便稍後能在盤中重新分析這些股票。

### 驗收條件

- Full Cycle 通過技術篩選的股票被標記為 `WatchlistType.TECHNICAL`。
- 股票被加入 runtime watchlist。
- watchlist 最後會透過 repository 持久化。
- 不允許 repository 在來源缺失時默認猜測為 `TECHNICAL`。
- 所有 watchlist entry 都必須有明確的 `candidate_source`。

---

## US-003 手動加入觀察清單

**優先級：P0**

作為使用者，  
我希望在查看指定股票的完整分析後，自行決定是否加入觀察清單，  
以便只有經過我確認的股票才會被標記為手動觀察股票。

### 驗收條件

- CLI 在分析報告顯示後詢問使用者。
- 只有通過技術篩選的 `survivors` 可以加入。
- 使用者拒絕時不修改 watchlist。
- 使用者同意時，股票被標記為 `WatchlistType.MANUAL`。
- 已存在的 watchlist entry 按照 `WatchlistRule` 合併。
- `MANUAL` 的優先級高於 `TECHNICAL` 與 `BUZZ`。
- 加入結果會顯示給使用者。

目前 CLI 已明確顯示這項功能正在等待 Pipeline 方法實作。

---

## US-004 — Trade Manually Watched Stocks

**Priority: P0**

As a user,

I want stocks that I manually add to the watchlist to participate in the normal trading workflow,

so that the system can continue monitoring them and automatically trade them when the normal strategy finds a valid opportunity.

### Business Rules

- Adding a stock to the manual watchlist does **not** mean BUY immediately.
- `WatchlistType.MANUAL` describes how the stock entered the watchlist.
- Trading decisions are still made by the normal strategy.
- A stock may have multiple watchlist types at the same time:
  - `TECHNICAL`
  - `BUZZ`
  - `MANUAL`
- A manually watched stock may remain on the watchlist even if it previously failed the technical filter.
- Manual watchlist membership must not bypass normal trading or risk rules.

### Acceptance Criteria

- Active `MANUAL` watchlist stocks are loaded by the trading workflow.
- Manual watchlist stocks are merged with other active watchlist stocks by `stock_id`.
- Duplicate watchlist sources must not cause the same stock to be analysed multiple times.
- The system refreshes the stock's required market data before making a decision.
- The system performs the normal analysis required for trading:
  - technical analysis
  - AI analysis
  - composite score calculation
- `composite_score` must contain the actual calculated score and must not remain at its default value.
- The normal `DecisionRule` determines whether the result is:
  - `BUY`
  - `HOLD`
  - `SELL`
- If the strategy creates a BUY signal for a manually watched stock, the signal source reflects the **decision source**, not the watchlist source.
- A `MANUAL` watchlist stock therefore does not automatically create a `SignalSource.MANUAL` signal.
- Normal position sizing must be used.
- Normal risk checks must still apply.
- Normal order validation must still apply.
- `OrderExecution` remains responsible for executable orders.
- Merely adding a stock to the manual watchlist must never directly create an order.

### Expected Flow

```
User manually adds stock
        ↓
WatchlistType.MANUAL
        ↓
Trading workflow loads active watchlist
        ↓
Refresh market data
        ↓
Technical + AI analysis
        ↓
Composite score
        ↓
DecisionRule
        ↓
BUY / HOLD / SELL
        ↓
Risk + sizing
        ↓
OrderExecution
```

---

## US-004-1 — Manual BUY Override

**Priority: P0**

As a user,

I want to explicitly create a manual BUY after reviewing a specific stock report,

so that I can intentionally override the automatic entry decision while still using the system's sizing, risk, and execution protections.

### Business Rules

- Manual BUY and manual watchlist membership are independent actions.
- A stock does not need to be added to the manual watchlist before performing a Manual BUY.
- Adding a stock to the manual watchlist does not authorize a Manual BUY.
- Manual BUY represents an explicit user trading decision.
- Manual BUY may bypass the automatic BUY threshold or `EntryRule` decision.
- Manual BUY must **not** bypass sizing, account, risk, or order validation.

### Acceptance Criteria

- The specific-stock report is shown before offering Manual BUY.
- The report contains the real calculated `composite_score`.
- The user must explicitly confirm the Manual BUY.
- Declining the confirmation creates no signal and no order.
- The confirmation for Manual BUY is separate from:
  - adding the stock to the manual watchlist
- A confirmed Manual BUY creates:
  - `TradeSignal`
  - `SignalAction.BUY`
  - `SignalSource.MANUAL`
- The system loads the latest account state before calculating the order quantity.
- The system calculates a valid quantity using the existing sizing rules.
- Quantity must be greater than zero.
- Manual BUY does not call the normal `EntryRule` to decide whether BUY is allowed.
- The resulting signal is persisted using the existing signal persistence mechanism.
- The signal is passed through the existing `OrderExecution`.
- Existing order validation must not be bypassed.
- Execution must still validate:
  - market is open
  - price is valid
  - quantity is greater than zero
  - sufficient cash is available
  - existing broker/execution constraints
- If execution is rejected, the user receives the rejection result instead of silently creating a successful trade.
- Normal Full Cycle execution must never create a `SignalSource.MANUAL` signal automatically.
- A Manual BUY can only originate from an explicit user action.

### Expected Flow

```
Analyse specific stock
        ↓
Technical + AI analysis
        ↓
Composite score
        ↓
Show report
        ↓
Optional: Add to manual watchlist?
        │
        └── independent action

Manual BUY?
        ↓
No → Finish

Yes
 ↓
Explicit confirmation
 ↓
Load current account
 ↓
Calculate legal quantity
 ↓
TradeSignal(
    action=BUY,
    source=MANUAL
)
 ↓
Persist signal
 ↓
OrderExecution
 ↓
Validation
 ↓
Executed / Rejected
```

### Explicit Non-Goal

US-004-1 does not implement:

```
"Buy this stock when price reaches X"
```

That is a persistent conditional trading instruction and should be implemented as a separate future story rather than mixed into Manual BUY.

---

# US-005 — Complete Specific-Stock Analysis with Human Override

Priority: P0

As a user,

I want stocks that I explicitly request to receive a complete analysis even when
they fail the technical strategy,

so that I can review the technical failure, News, AI analysis, and composite
score before making my own watchlist or Manual BUY decision.

## Business Rules

Automatic workflows and manual specific-stock analysis have different policies.

Automatic workflow:

Market / Watchlist Stocks
↓
Technical Analysis
↓
Technical FAIL
↓
Stop News / AI / trading for this run

Manual specific-stock workflow:

User requests stock
↓
Technical Analysis
↓
Technical PASS / FAIL
↓
News Analysis
↓
AI Analysis
↓
Composite Score
↓
Show Complete Report
↓
Optional Manual Watchlist
↓
Optional Manual BUY

Technical failure does not prevent explicit human analysis.

Technical failure does not prevent a stock from being added to the MANUAL
watchlist.

Technical failure does not automatically authorize a trade.

Manual watchlist membership and Manual BUY remain independent actions.

## Acceptance Criteria

- `manual_stocks` contains every successfully loaded stock explicitly requested
  by the user.
- `survivors` contains only stocks that passed the active technical strategy.
- Every manual stock receives a `TechnicalReport`.
- Technical failure remains visible through `hard_failures`.
- NewsFeed processes every `manual_stock`.
- AiAnalyser processes every `manual_stock`.
- CompositeScorer processes every completely analysed `manual_stock`.
- A technically failed manual stock may still receive an AI score and
  composite score.
- A technically failed manual stock may still be added to
  `WatchlistType.MANUAL`.
- Adding a technically failed stock to the MANUAL watchlist does not add it to
  `survivors`.
- Adding a stock to the MANUAL watchlist does not create a trading signal or
  order.
- Manual BUY remains a separate explicit user confirmation.
- Automatic Full Cycle and Intraday workflows continue sending only
  `survivors` to News, AI, composite scoring, and automatic decisions.
- TechnicalFilter must not contain manual-mode or workflow-specific behavior.
- AiAnalyser must not decide whether a stock is technically eligible. The
  calling workflow owns that decision.

## Expected Manual Flow

Analyse Specific Stock
↓
MarketDataCollector
↓
TechnicalFilter
↓
TechnicalReport
├── PASS → included in survivors
└── FAIL → excluded from survivors
↓
remains in manual_stocks
↓
NewsFeed
↓
AiAnalyser
↓
CompositeScorer
↓
Complete Report
↓
Add to MANUAL watchlist?
↓
Optional Manual BUY?

## Explicit Non-Goals

US-005 does not change:

- TechnicalStrategy rules
- TechnicalFilter pass/fail behavior
- automatic trading thresholds
- DecisionRule
- SizingRule
- OrderExecution
- ManualBuy execution rules
- watchlist persistence rules

No new use case or application function is required.

---

## US-006 完成 Social Buzz Workflow

**優先級：P0**

作為使用者，  
我希望系統能尋找近期熱門討論股票並完成分析流程，  
以便找出市場正在關注的交易機會。

### 驗收條件

- 呼叫 BuzzScanner 取得熱門股票。
- 取得股票 OHLCV 與技術指標。
- 執行技術篩選。
- 通過股票標記為 `BUZZ`。
- 通過股票加入並儲存 watchlist。
- 執行新聞與 AI 分析。
- 計算技術分數與綜合分數。
- 產生並儲存訊號。
- 市場與風險條件允許時才執行訂單。
- Pipeline 最後回傳完整 `PipelineStatus`。

目前 `run_buzz_scan()` 尚未實作。

---

## US-007 實際套用 Social Buzz 門檻

**優先級：P1**

作為使用者，  
我希望只有討論數量或推文分數達到門檻的股票才被視為熱門股票，  
以便降低雜訊與不具代表性的討論。

### 驗收條件

- 使用設定中的 `buzz_min_mentions`。
- 使用設定中的 `buzz_min_push_count`。
- 呼叫現有 `SocialBuzzCriteria.is_trending()`。
- 未達門檻的股票不得進入後續分析。
- 統計資料記錄過濾前後數量。

目前 `SocialBuzzCriteria` 已存在，但尚未接入實際流程。

---

## US-008 完成 Intraday Trading Workflow

**優先級：P0**

作為使用者，  
我希望盤中重新分析持倉與有效觀察清單，  
以便根據最新市場資料產生 BUY、SELL 或 HOLD 訊號。

### 驗收條件

- 每次執行建立新的 `PipelineStatus`。
- 載入帳戶現金與持倉。
- 載入 active watchlist。
- 合併持倉股票與 watchlist 股票，並以 `stock_id` 去重。
- 取得盤中或最新市場資料。
- 檢查資料新鮮度。
- 重新計算技術指標。
- 執行技術、新聞與 AI 分析。
- 產生交易訊號。
- 執行允許的訂單。
- 儲存決策與執行結果。
- 回傳完整 PipelineStatus。

目前 `run_intraday()` 尚未實作。

---

## US-009 明確控制自動下單模式

**優先級：P1**

作為系統管理者，  
我希望能透過設定決定 workflow 是否允許執行訂單，  
以便分析流程與交易流程不會意外混在一起。

### 驗收條件

- `OrderMode.DISABLED`：完全不下單。
- `OrderMode.MOCK_ONLY`：只允許 MockExecutionProvider。
- `OrderMode.LIVE`：只允許明確配置的真實券商。
- Full Cycle 預設不下單。
- Buzz 與 Intraday 根據 order mode 決定是否呼叫 OrderExecution。
- CLI 清楚顯示目前 execution provider 與 order mode。
- 不另外建立重複的布林值作為第二個 source of truth。

---

## US-010 保存 AI 分析與交易決策歷史

**優先級：P1**

作為使用者，  
我希望過去的分析與交易決策能被保存，  
以便 AI 在未來分析相同股票時參考先前判斷。

### 驗收條件

- 每個成功產生的 TradeSignal 都可被保存到 knowledge repository。
- 保存內容包含股票、分數、訊號、理由與時間。
- DecisionMemory 接入需要產生訊號的 workflow。
- 單一股票保存失敗不應中斷整批流程。
- 下次分析時可以取得相關歷史內容。

---

# Epic 2：基本面資料與估值功能

## 重要產品原則

EPS 不應由 AI 猜測。

正確流程應為：

```text
財務資料來源
    ↓
取得 EPS 與財報期間
    ↓
Domain 計算本益比
    ↓
使用者輸入期望本益比
    ↓
Domain 計算合理價
    ↓
AI 解釋估值結果與風險
```

AI 可以提出估值理由，但所有財務數字必須有實際資料來源。這也符合現有提示詞中「缺少資料時必須說 Data Unavailable，不得捏造財務數字」的原則。

---

## US-101 取得股票基本面資料

**優先級：P1**

作為使用者，  
我希望系統能取得股票的基本面資料，  
以便進行 EPS、本益比與合理價分析。

### 驗收條件

- 可以取得最新財報 EPS。
- 明確標示 EPS 類型：
  - 單季 EPS
  - 累計 EPS
  - 年度 EPS
  - 近四季 EPS（TTM）
- 記錄財務資料的期間。
- 記錄資料來源。
- 記錄資料取得時間。
- 資料缺失時回傳 unavailable，而不是零。
- AI 不得自行填補缺失數字。

---

## US-102 顯示 EPS

**優先級：P1**

作為使用者，  
我希望股票報告顯示目前使用的 EPS，  
以便了解後續本益比與合理價是如何計算的。

### 驗收條件

- 報告顯示 EPS 數值。
- 報告顯示 EPS 期間。
- 報告顯示 EPS 是實際值還是預估值。
- 報告顯示資料來源。
- 無 EPS 時顯示「資料不足」。
- 不得只顯示數字而不顯示期間。

---

## US-103 計算目前本益比

**優先級：P1**

作為使用者，  
我希望系統根據最新股價與 EPS 計算目前本益比，  
以便判斷目前市場估值。

### 計算方式

```text
目前本益比 = 目前股價 ÷ EPS
```

### 驗收條件

- 計算使用明確的 EPS 類型，MVP 建議使用 TTM EPS。
- 股價必須大於零。
- EPS 大於零時才計算一般本益比。
- EPS 等於零時顯示無法計算。
- EPS 小於零時顯示虧損，本益比不適用。
- 計算由 domain rule 完成，不由 AI 完成。
- 顯示計算使用的股價時間。

---

## US-104 詢問使用者期望本益比

**優先級：P1**

作為使用者，  
我希望輸入自己認為合理的本益比，  
以便系統依照我的估值假設計算合理股價。

### 驗收條件

- CLI 詢問目標本益比。
- 必須輸入大於零的有限數字。
- 使用者可以取消。
- 顯示目前市場本益比供使用者參考。
- 顯示產業資訊，但 MVP 不強制自動決定產業本益比。
- 使用者輸入只適用於本次分析，除非明確要求保存偏好。

---

## US-105 計算合理股價

**優先級：P1**

作為使用者，  
我希望系統根據 EPS 與目標本益比計算合理股價，  
以便比較目前股價是否被高估或低估。

### 計算方式

```text
合理股價 = EPS × 目標本益比
```

### 驗收條件

- 使用 EPS 與使用者輸入的目標本益比。
- 顯示合理股價。
- 顯示目前股價。
- 顯示價差。
- 顯示低估或高估百分比。
- EPS 小於或等於零時不使用此模型。
- 結果必須清楚標示為「基於指定本益比的估值」，不能稱為客觀真實價值。

---

## US-106 提供合理價範圍

**優先級：P2**

作為使用者，  
我希望看到保守、基準與樂觀三種合理價，  
以便理解估值的不確定性。

### 驗收條件

- 支援三個目標本益比：
  - 保守
  - 基準
  - 樂觀
- 分別計算三個合理價。
- 本益比必須由設定、使用者輸入或明確規則提供。
- AI 可以解釋三種情境，但不能自行修改數值。
- 顯示每種情境的假設。

---

## US-107 AI 解釋估值結果

**優先級：P1**

作為使用者，  
我希望 AI 根據真實 EPS、目前本益比與合理價結果進行解釋，  
以便了解股票可能被高估或低估的原因。

### 驗收條件

AI 報告至少包含：

- 目前股價
- EPS 與財報期間
- 目前本益比
- 使用者設定的目標本益比
- 推算合理股價
- 高估或低估百分比
- 可能支持較高本益比的因素
- 可能導致本益比下修的風險
- 資料不足警告
- 非投資建議聲明

AI 不得：

- 自行創造 EPS。
- 將新聞中的推測當成正式財務數據。
- 在缺少資料時給出精確合理價。
- 把單一估值公式描述為唯一正確答案。

---

## US-108 尋找本益比低估股票

**優先級：P1**

作為使用者，  
我希望輸入目標本益比並掃描市場，  
以便找出目前價格低於推算合理價的股票。

### 驗收條件

- 使用者輸入目標本益比。
- 系統取得股票清單。
- 取得每支股票的最新價格與 EPS。
- 排除：
  - EPS 缺失
  - EPS 小於或等於零
  - 股價資料過期
- 計算目前本益比。
- 計算合理價。
- 計算低估幅度。
- 只保留符合使用者條件的股票。
- 依低估幅度排序。
- 結果顯示：
  - 股票代碼
  - 股票名稱
  - 目前股價
  - EPS
  - 目前本益比
  - 目標本益比
  - 合理價
  - 低估幅度
  - 財務資料期間
  - 資料來源

---

## US-109 結合估值與技術篩選

**優先級：P2**

作為使用者，  
我希望先找出估值偏低的股票，再套用技術分析條件，  
以便避免只因價格便宜就選到基本面或趨勢不佳的股票。

### 驗收條件

- 估值篩選與技術篩選是兩個明確步驟。
- 顯示股票在哪一個步驟被淘汰。
- 股票必須同時符合：
  - EPS 有效
  - 估值條件
  - 技術面沒有 hard failure
- 不直接將「低本益比」視為 BUY。
- AI 報告需要解釋低本益比可能來自成長下降或市場風險。

---

# Epic 3：資料可靠性與交易安全

## US-201 驗證即時資料新鮮度

**優先級：P1**

作為使用者，  
我希望系統避免使用過期股價執行交易，  
以免根據失效資料下單。

### 驗收條件

- Intraday workflow 使用 `DataFreshnessRule`。
- 過期資料不得產生可執行 BUY 訂單。
- 過期資料記錄在 stats。
- 報告顯示最後資料時間。
- 歷史分析與即時交易使用不同的新鮮度要求。

---

## US-202 納入交易費用與交易稅

**優先級：P1**

作為使用者，  
我希望模擬交易包含手續費與交易稅，  
以便帳戶餘額與損益更接近真實交易。

### 驗收條件

- BUY 計算手續費。
- SELL 計算手續費與交易稅。
- 支援最低手續費。
- SizingRule 計算數量時保留交易成本。
- 訂單結果保存實際成本。
- realized PnL 包含費用與稅。

目前設定已包含 fee rate、tax rate 與 minimum fee，但帳戶模型仍將這些列為未完成限制。

---

## US-203 保存帳戶與持倉快照

**優先級：P2**

作為使用者，  
我希望查看過去的現金與持倉變化，  
以便分析模擬交易績效。

### 驗收條件

- 保存 cash snapshot。
- 保存 position snapshot。
- 每次訂單成交後建立快照。
- 可以查詢指定日期的帳戶狀態。
- 可以計算資產曲線。
- 可以計算未實現損益。

目前 DTO 中已留下 cash snapshot、position snapshot、market value 與 unrealized PnL 的待辦。

---

## US-204 建立執行稽核紀錄

**優先級：P2**

作為使用者，  
我希望知道某筆訂單是由哪次 workflow 與哪個決策產生，  
以便追蹤問題與驗證 AI 判斷。

### 驗收條件

- 每次 workflow 有唯一 run ID。
- 每個訊號有唯一 decision ID。
- 訂單保存 run ID 與 decision ID。
- 可以從訂單追蹤回：
  - 股票資料
  - 技術分析
  - AI 報告
  - 交易訊號
  - 執行結果

---

## US-205 完整支援訂單生命週期

**優先級：P2**

作為使用者，  
我希望系統正確處理 pending、submitted、filled、cancelled、rejected 與 failed，  
以便訂單狀態不會不一致。

### 驗收條件

- 每個狀態有合法的轉換路徑。
- 不合法轉換會失敗。
- ROD、IOC、FOK 有明確行為。
- rejected 與 failed 有明確區別。
- cancel 只允許尚未成交的訂單。
- 測試涵蓋所有狀態轉換。

---

# Epic 4：未來擴充

## US-301 串接 Shioaji 真實券商

**優先級：P3**

作為使用者，  
我希望未來可以選擇串接真實券商，  
以便在充分測試與風險控制後執行真實訂單。

### 驗收條件

- 登入 Shioaji。
- 取得真實現金。
- 取得真實持倉。
- 將 domain Order 轉換為券商訂單。
- 將券商回應轉回 domain Order。
- 必須明確啟用 LIVE mode。
- 預設仍使用 MockExecutionProvider。

目前 Shioaji execution provider 的所有方法仍為未實作。

---

## US-302 提供 Web API 交易 Workflow

**優先級：P3**

作為前端使用者，  
我希望透過 API 執行分析與查看結果，  
以便不需要依賴 CLI。

### 驗收條件

- API 可以啟動 Full Cycle。
- API 可以分析指定股票。
- API 可以取得 watchlist。
- API 可以取得 signals 與 orders。
- 寫入操作有權限與確認機制。
- API 不複製 domain business rules。

---

## US-303 提供可調整技術參數的 UI

**優先級：P3**

作為進階使用者，  
我希望調整 RSI、MACD、MA 與其他技術指標週期，  
以便測試不同策略敏感度。

### 驗收條件

- UI 欄位對應現有 IndicatorParameters。
- 所有輸入經過驗證。
- 不直接修改 domain object。
- 儲存後由新的 workflow 使用。
- 顯示目前使用的 strategy 與參數。

設定檔已明確將這項功能列為未來 UI Parameter Tuning。

---

# 技術債／Enabler Stories

這些不是優先產品功能，但應安排處理：

1. 清理 Yahoo Finance Adapter。
2. 統一 MarketClock 命名與台灣時區表示方式。
3. 檢查 OHLCV table 的 composite primary key 與 `trading_date` 是否重複。
4. 檢查 `Stock` 是否承擔太多 pipeline 狀態。
5. 決定 hard failures、soft failures、observations 是否應移至獨立 screening result。
6. 移除 repository 對缺失 `candidate_source` 的默認值。
7. 整理 AiReportParser 的資料驗證與錯誤處理。
8. 移除已完成 TODO 註解。
9. 統一 Ruff 與 CI formatter；目前 CI 使用 Black，但專案設定主要使用 Ruff formatter。
10. 每次 workflow 改動時同步：
    - README
    - CLI 文字
    - dependency wiring
    - tests
    - API schema

---

# 建議開發順序

## 第一階段：讓目前系統真正跑通

1. US-001 技術分數
2. US-002 TECHNICAL watchlist persistence
3. US-005 修正 specific stock survivor 流程
4. US-003 Manual watchlist
5. US-004 Manual BUY
6. US-006 Buzz Workflow
7. US-008 Intraday Workflow
8. Workflow integration tests

## 第二階段：估值 MVP

1. US-101 基本面資料
2. US-102 EPS 顯示
3. US-103 本益比計算
4. US-104 詢問目標本益比
5. US-105 合理股價
6. US-107 AI 估值解釋
7. US-108 低估股票篩選

## 第三階段：可靠性

1. 資料新鮮度
2. 手續費與交易稅
3. 決策歷史
4. 帳戶快照
5. 訂單生命週期

## 第四階段：介面與真實交易

1. Web API
2. UI
3. Shioaji
4. 參數調整
