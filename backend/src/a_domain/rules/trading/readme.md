a_domain/rules/trading/
    entry.py
    exit.py
    decision.py
    reason.py
    sizing.py
    cost.py
    tick.py
    order_rule.py
    execution.py
    account_value.py

Each rule makes one decision in `apply`:

| File            | Rule                      | Decision                                                                                   |
| --------------- | ------------------------- | ------------------------------------------------------------------------------------------ |
| `entry.py`      | `EntryRule`               | BUY or HOLD for a stock not held (ADD or HOLD for a held one), at or above the buy threshold |
|                 | `ManualEntryRule`         | The user's confirmed BUY: it skips the buy threshold, never the sizing                     |
| `exit.py`       | `BlockedStockRule`        | Why the run acts on a stock no more: the stop-loss check sold it, or its quote is stale    |
|                 | `StopLossQuoteRule`       | Why a held stock gets no stop-loss check now: it is blocked, or it has no realtime quote   |
|                 | `StopLossRule`            | The emergency SELL of a position at or below its stop-loss price                           |
|                 | `ExitRule`                | SELL or HOLD for a held stock: the stop-loss first, then the sell threshold                |
| `decision.py`   | `DecisionSkipRule`        | Why a watchlist stock gets no decision: blocked, or no composite score or no price         |
|                 | `DecisionCandidatesRule`  | The stocks Intraday decides on: every technical survivor, then every other held stock      |
|                 | `DecisionRule`            | The final decision on one stock: EntryRule or ExitRule, by whether a position exists       |
|                 | `RunDecisionsRule`        | One run's decisions, best score first, each BUY sized on the equity and the cash left      |
| `reason.py`     | `AnalysisSummaryRule`     | The technical verdict, cited AI factors and scores every reason ends with                  |
|                 | `EntryReasonRule`         | The reason of a BUY or HOLD on a stock not held                                            |
|                 | `ExitReasonRule`          | The reason of a SELL or HOLD on a held position                                            |
| `sizing.py`     | `BuyCostRule`             | The cash a BUY can take: its quantity at the order's limit plus the fee                    |
|                 | `SizingRule`              | The BUY quantity: the risk budget on the equity, capped by the cash after the fee          |
| `cost.py`       | `TradingCostRule`         | The broker fee (with its minimum) and the transaction tax (SELL only)                      |
|                 | `AffordableQuantityRule`  | The largest lot-aligned BUY quantity the cash pays for, fee included                       |
| `tick.py`       | `TickSizeRule`            | The exchange tick of a price                                                               |
|                 | `LimitPriceRule`          | An order's limit price: the decided price as a tick, up for a BUY and down for a SELL      |
| `order_rule.py` | `OrderGateRule`           | Why an order may not be sent now: order mode, continuous trading, quote age                |
|                 | `OrderRule`               | The order for a decision: LIMIT IOC at its limit price, or REJECTED with the gate's reason |
| `execution.py`  | `OrderAcceptanceRule`     | Why any broker refuses an order unsent: not LIMIT, ROD, or more than the account covers    |
|                 | `LotSplitRule`            | An order's shares as the exchange trades them: one board-lot part and one odd-lot part     |
|                 | `FillRule`                | What one fill settles: its fee and tax, and a SELL's realized PnL                          |
|                 | `BrokerOutcomeRule`       | The final status of a real broker's order once every lot part it sent has reported         |
| `account_value.py` | `AccountValueRule`     | Positions marked to market, unrealized PnL net of the selling costs                        |
|                 | `EquityRule`              | The equity a run sizes its BUYs on: cash plus positions at the run's latest prices         |
|                 | `SnapshotValueRule`       | A snapshot's account marked at a day's closes                                              |
|                 | `FillSnapshotRule`        | The account right after a fill: the filled stock at its fill price, others at the latest   |
|                 | `EquityCurveRule`         | The account at the end of each trading day since the first snapshot                        |
|                 | `AccountAsOfRule`         | The account at the end of a day                                                            |
|                 | `LatestMarkRule`          | Each stock's latest price: its realtime quote, else its last daily close                   |
|                 | `PriceHistoryStartRule`   | Where the daily prices the account history needs start                                     |
