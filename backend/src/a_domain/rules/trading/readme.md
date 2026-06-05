a_domain/rules/trading/
    entry.py
    exit.py
    decision.py
    reason.py
    sizing.py

各自責任如下：

| 檔案            | Class          | 責任                               |
| ------------- | -------------- | -------------------------------- |
| `entry.py`    | `EntryRule`    | 沒持倉時，根據 buy threshold 決定 BUY / HOLD |
| `exit.py`     | `ExitRule`     | 有持倉時，根據 stop-loss / sell threshold 決定 SELL / HOLD |
| `decision.py` | `DecisionRule` | 根據 position 是否存在，派給 Entry 或 Exit |
| `reason.py`   | `ReasonRule`   | 建立 readable reason 的 stateless helpers |
| `sizing.py`   | `SizingRule`   | BUY quantity 計算                  |
