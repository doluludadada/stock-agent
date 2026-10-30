a_domain/rules/trading/
    entry.py
    exit.py
    decision.py
    reason.py
    sizing.py
    cost.py
    order_rule.py
    valuation.py

各自責任如下：

| 檔案              | Class               | 責任                                                                 |
| --------------- | ------------------- | ------------------------------------------------------------------ |
| `entry.py`      | `EntryRule`         | 沒持倉時，根據 buy threshold 決定 BUY / HOLD；手動 BUY 只略過 threshold，不略過 sizing |
| `exit.py`       | `ExitRule`          | 有持倉時，根據 stop-loss / sell threshold 決定 SELL / HOLD                    |
| `decision.py`   | `DecisionRule`      | 根據 position 是否存在，派給 Entry 或 Exit                                   |
| `reason.py`     | `ReasonRule`        | 建立 readable reason 的 stateless helpers                              |
| `sizing.py`     | `SizingRule`        | BUY quantity 計算：risk budget，並以含手續費後的現金為上限                           |
| `cost.py`       | `TradingCostRule`   | 手續費（含最低手續費）與證交稅（只有 SELL）的唯一來源                                   |
| `order_rule.py` | `OrderRule`         | 送單前的 gate（order mode、開盤、報價新鮮度）與訂單形狀（LIMIT、IOC）                      |
| `valuation.py`  | `ValuationRule`     | 持倉市值、扣除賣出成本的未實現損益、資產曲線                                          |
