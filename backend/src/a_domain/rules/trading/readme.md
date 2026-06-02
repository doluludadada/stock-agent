a_domain/rules/trading/
    action.py
    entry.py
    exit.py
    decision.py
    reason.py
    sizing.py

各自責任如下：

| 檔案            | Class          | 責任                               |
| ------------- | -------------- | -------------------------------- |
| `action.py`   | `ActionRule`   | score → BUY / HOLD / SELL        |
| `entry.py`    | `EntryRule`    | 沒持倉時，決定要不要產生 BUY signal          |
| `exit.py`     | `ExitRule`     | 有持倉時，決定要不要產生 SELL signal         |
| `decision.py` | `DecisionRule` | 根據 position 是否存在，派給 Entry 或 Exit |
| `reason.py`   | `ReasonRule`   | 建立 readable reason               |
| `sizing.py`   | `SizingRule`   | BUY quantity 計算                  |
