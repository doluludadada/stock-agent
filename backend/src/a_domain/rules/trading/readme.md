a_domain/rules/trading/
    entry.py
    exit.py
    decision.py
    reason.py
    sizing.py
    cost.py
    tick.py
    order_rule.py
    valuation.py

Each rule makes one decision in `apply`:

| File            | Rule                      | Decision                                                                                   |
| --------------- | ------------------------- | ------------------------------------------------------------------------------------------ |
| `entry.py`      | `EntryRule`               | BUY or HOLD for a stock not held (ADD or HOLD for a held one), at or above the buy threshold |
|                 | `ManualEntryRule`         | The user's confirmed BUY: it skips the buy threshold, never the sizing                     |
| `exit.py`       | `StopLossQuoteRule`       | Why a held stock's quote cannot price a stop-loss SELL now                                 |
|                 | `StopLossRule`            | The emergency SELL of a position at or below its stop-loss price                           |
|                 | `ExitRule`                | SELL or HOLD for a held stock: the stop-loss first, then the sell threshold                |
| `decision.py`   | `DecisionSkipRule`        | Which watchlist stocks get no decision in this run, and why                                |
|                 | `DecisionRule`            | The final decision on one stock: EntryRule or ExitRule, by whether a position exists       |
|                 | `RunDecisionsRule`        | One run's decisions, best score first, each BUY sized against the cash left                |
| `reason.py`     | `AnalysisSummaryRule`     | The technical verdict, cited AI factors and scores every reason ends with                  |
|                 | `EntryReasonRule`         | The reason of a BUY or HOLD on a stock not held                                            |
|                 | `ExitReasonRule`          | The reason of a SELL or HOLD on a held position                                            |
| `sizing.py`     | `BuyCostRule`             | The cash a BUY can take: its quantity at the order's limit plus the fee                    |
|                 | `SizingRule`              | The BUY quantity: the risk budget, capped by the cash after the fee                        |
| `cost.py`       | `TradingCostRule`         | The broker fee (with its minimum) and the transaction tax (SELL only)                      |
|                 | `AffordableQuantityRule`  | The largest lot-aligned BUY quantity the cash pays for, fee included                       |
| `tick.py`       | `TickSizeRule`            | The exchange tick of a price                                                               |
|                 | `LimitPriceRule`          | An order's limit price: the decided price as a tick, up for a BUY and down for a SELL      |
| `order_rule.py` | `OrderGateRule`           | Why an order may not be sent now: order mode, continuous trading, quote age                |
|                 | `OrderRule`               | The order for a decision: LIMIT IOC at its limit price, or REJECTED with the gate's reason |
| `valuation.py`  | `ValuationRule`           | Positions marked to market, unrealized PnL net of the selling costs                        |
|                 | `SnapshotValuationRule`   | A snapshot's account marked at a day's closes                                              |
|                 | `EquityCurveRule`         | One equity point per trading day since the first snapshot                                  |
|                 | `AccountAsOfRule`         | The account at the end of a day                                                            |
|                 | `PriceHistoryStartRule`   | The first day of daily prices the account history needs                                    |
|                 | `AccountHistoryRule`      | The account now, its equity curve and the account as of a day                              |
