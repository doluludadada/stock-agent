
``` mermaid
graph TD
    subgraph Background [背景作業]
        A1[昨晚技術篩選 SQL] -->|產出| LIST_A(技術觀察名單 - 30檔)
        A2[即時 PTT/News 監聽] -->|Regex提取 + 統計| LIST_B(輿情熱門名單 - 10檔)
    end

    subgraph Intraday Pipeline [盤中執行]
        LIST_A & LIST_B --> M[MarketScanner: 合併名單]
        M --> P[PriceCollector: 取得即時報價]
        P --> T{Technical Analyser: 技術過濾}
        
        T -->|趨勢向下/不符策略| DROP[剔除]
        T -->|趨勢向上/支撐有效| CANDIDATES[倖存候選人 3-5檔]
        
        CANDIDATES --> AI[Sentiment Analyser: AI 深度解讀]
        AI -->|分析新聞/財報/推文| SCORE[計算信心分數]
        
        SCORE --> DECISION{分數 > 閥值?}
        DECISION -->|Yes| BUY[🚀 下單 / 通知]
    end
```

```
Layer Boundaries
┌─────────────────────────────────────────────────────────────────┐
│ Layer A (Domain)                                                │
│                                                                 │
│   ✓ Models (pure data structures)                               │
│   ✓ Ports (interfaces only, no implementation)                  │
│   ✓ Rules (pure business logic, no I/O)                         │
│   ✓ Types (enums, constants)                                    │
│                                                                 │
│   ✗ No imports from Layer B, C, D                               │
│   ✗ No framework dependencies                                   │
│   ✗ No I/O operations                                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Layer B (Application)                                           │
│                                                                 │
│   ✓ Use Cases (orchestrate domain rules + ports)                │
│   ✓ Schemas (DTOs, config)                                      │
│   ✓ Pipeline (orchestrates use cases only)                      │
│                                                                 │
│   ✗ No direct database/API calls                                │
│   ✗ No framework dependencies                                   │
│   ✗ Business logic belongs in Domain Rules                      │
└─────────────────────────────────────────────────────────────────┘
```


# Stock Agent - Technical Analysis Rules

## Overview

This package provides a comprehensive set of technical analysis rules based on established financial literature.

## Rule Categories

### 1. Trend Rules (`trend/`)

**Purpose:** Identify if a stock is in an uptrend suitable for buying.

| Rule                      | Logic                            | Reference                       |
| ------------------------- | -------------------------------- | ------------------------------- |
| `PriceAboveMa20Rule`      | Price > 20-day MA                | Murphy (1999)                   |
| `PriceAboveMa60Rule`      | Price > 60-day MA                | Murphy (1999)                   |
| `MaBullishAlignmentRule`  | MA20 > MA60                      | Murphy (1999)                   |
| `GoldenCrossRule`         | MA20 crossed above MA60 recently | Murphy (1999), Bulkowski (2005) |
| `AdxTrendStrengthRule`    | ADX between 20-50                | Wilder (1978)                   |
| `AdxBullishDirectionRule` | +DI > -DI                        | Wilder (1978)                   |

### 2. Momentum Rules (`momentum/`)

**Purpose:** Measure strength and speed of price movements.

| Rule                          | Logic                | Reference                   |
| ----------------------------- | -------------------- | --------------------------- |
| `RsiHealthyRule`              | RSI between 50-70    | Wilder (1978), Brown (1999) |
| `RsiNotOverboughtRule`        | RSI < 80             | Elder (1993)                |
| `RsiBullishMomentumRule`      | RSI > 50             | Brown (1999)                |
| `MacdBullishRule`             | MACD > Signal        | Appel (2005)                |
| `MacdPositiveRule`            | MACD > 0             | Appel (2005)                |
| `MacdHistogramRisingRule`     | Histogram increasing | Elder (1993)                |
| `StochasticNotOverboughtRule` | %K < 80              | Lane (1984)                 |
| `StochasticBullishCrossRule`  | %K > %D              | Lane (1984)                 |
| `MfiNotOverboughtRule`        | MFI < 80             | Quong & Soudack (1989)      |

### 3. Volume Rules (`volume/`)

**Purpose:** Confirm price moves with volume.

| Rule                     | Logic              | Reference        |
| ------------------------ | ------------------ | ---------------- |
| `VolumeAboveAverageRule` | Volume > 5-day avg | Murphy (1999)    |
| `VolumeBreakoutRule`     | Volume > 1.5x avg  | O'Neil (1988)    |
| `VolumeNotDryRule`       | Volume > 50% avg   | Elder (1993)     |
| `ObvRisingRule`          | OBV trending up    | Granville (1963) |
| `LiquidityRule`          | Volume > 500 lots  | O'Neil (1988)    |
| `MinimumPriceRule`       | Price > NT$15      | O'Neil (1988)    |

### 4. Volatility Rules (`volatility/`)

**Purpose:** Measure risk and time entries.

| Rule                         | Logic               | Reference                       |
| ---------------------------- | ------------------- | ------------------------------- |
| `BollingerNotOverboughtRule` | %B < 0.9            | Bollinger (2001)                |
| `BollingerAboveMiddleRule`   | Price > Middle Band | Bollinger (2001)                |
| `BollingerSqueezeRule`       | Bandwidth low       | Bollinger (2001)                |
| `AtrPositionSizingRule`      | ATR% in range       | Wilder (1978), Van Tharp (2006) |
| `VolatilityNotExtremeRule`   | Daily range < 7%    | Elder (1993)                    |

### 5. Entry Timing Rules (`entry_timing/`)

**Purpose:** Optimize exact entry moment (intraday only).

| Rule                         | Logic                | Reference                |
| ---------------------------- | -------------------- | ------------------------ |
| `NotCrashingRule`            | Today's drop < 3%    | Livermore (1940)         |
| `IntradayMomentumRule`       | Price > Today's open | Schwartz (1998)          |
| `VolumeConfirmationRule`     | Volume > 50% avg     | Murphy (1999)            |
| `NotGappedUpExcessivelyRule` | Gap < 3%             | Elder (1993)             |
| `IntradayRangePositionRule`  | Not at intraday high | Schwartz (1998)          |
| `ConsecutiveUpDaysRule`      | < 4 up days          | Connors & Raschke (1995) |

---

## Strategy Configurations

### Conservative (High Win Rate)

```python
from backend.src.a_domain.rules.process.policies.policy_factory import create_conservative_policy

policy = create_conservative_policy()
# Win rate: 60-70%, Trades/week: 2-5
```

### Moderate (Balanced)

```python
from backend.src.a_domain.rules.process.policies.policy_factory import create_moderate_policy

policy = create_moderate_policy()
# Win rate: 50-60%, Trades/week: 5-10
```

### Aggressive (More Trades)

```python
from backend.src.a_domain.rules.process.policies.policy_factory import create_aggressive_policy

policy = create_aggressive_policy()
# Win rate: 40-50%, Trades/week: 10-20
```

### Buzz Stock (Social Media Plays)

```python
from backend.src.a_domain.rules.process.policies.policy_factory import create_buzz_stock_policy

policy = create_buzz_stock_policy()
# For PTT/Twitter trending stocks
```

---

## Rule Application Matrix

| Source              | Setup Rules | Safety Rules | Entry Timing  |
| ------------------- | ----------- | ------------ | ------------- |
| TECHNICAL_WATCHLIST | ✅ All       | ✅ All        | ✅ If intraday |
| SOCIAL_BUZZ         | ❌ Skip      | ✅ All        | ✅ If intraday |
| MANUAL_INPUT        | ❌ Skip      | ✅ All        | ✅ If intraday |

---

## Usage in Pipeline

```python
# In FilterCandidates use case
survivors = filter_candidates.execute(
    contexts,
    is_intraday=True,  # Applies entry timing rules
)

# For nightly screening
watchlist = filter_candidates.execute(
    contexts,
    is_intraday=False,  # Skips entry timing rules
)
```

---

## References

### Books

1. **Murphy, J.J. (1999).** *Technical Analysis of the Financial Markets.* New York Institute of Finance.
   - The definitive guide to technical analysis. Covers trends, moving averages, oscillators.

2. **Elder, A. (1993).** *Trading for a Living.* Wiley.
   - Triple Screen Trading System. Psychology + Risk Management + Method.

3. **Wilder, J.W. (1978).** *New Concepts in Technical Trading Systems.*
   - Introduced RSI, ADX, ATR. Original source for these indicators.

4. **Appel, G. (2005).** *Technical Analysis: Power Tools for Active Investors.*
   - MACD creator. Definitive guide to MACD usage.

5. **Bollinger, J. (2001).** *Bollinger on Bollinger Bands.* McGraw-Hill.
   - Official guide to Bollinger Bands by the creator.

6. **O'Neil, W. (1988).** *How to Make Money in Stocks.* McGraw-Hill.
   - CAN SLIM methodology. Volume confirmation, breakouts.

7. **Granville, J. (1963).** *Granville's New Key to Stock Market Profits.*
   - On-Balance Volume (OBV) creator.

8. **Bulkowski, T. (2005).** *Encyclopedia of Chart Patterns.*
   - Statistical analysis of chart patterns. Golden/Death cross success rates.

9. **Connors, L. & Raschke, L. (1995).** *Street Smarts.*
   - Short-term trading patterns. Consecutive up/down days research.

10. **Schwartz, M. (1998).** *Pit Bull.*
    - Practical scalping and day trading wisdom.

11. **Van Tharp (2006).** *Trade Your Way to Financial Freedom.*
    - Position sizing, risk management, expectancy.

12. **Brown, C. (1999).** *Technical Analysis for the Trading Professional.*
    - Advanced RSI analysis. RSI range shifts in trends.

### Papers & Articles

- Lane, G. (1984). "Lane's Stochastics." *Technical Analysis of Stocks & Commodities.*
- Quong, G. & Soudack, A. (1989). "Volume-Weighted RSI." *Technical Analysis of Stocks & Commodities.*

---

## Files Structure

```
src/a_domain/rules/process/
├── indicators/
│   ├── __init__.py           # Master exports
│   ├── trend/
│   │   ├── __init__.py
│   │   └── trend_rules.py    # MA, ADX rules
│   ├── momentum/
│   │   ├── __init__.py
│   │   └── momentum_rules.py # RSI, MACD, Stochastic rules
│   ├── volume/
│   │   ├── __init__.py
│   │   └── volume_rules.py   # Volume, liquidity rules
│   ├── volatility/
│   │   ├── __init__.py
│   │   └── volatility_rules.py # Bollinger, ATR rules
│   └── entry_timing/
│       ├── __init__.py
│       └── entry_timing_rules.py # Intraday rules
└── policies/
    ├── technical_screening.py  # Master policy
    └── policy_factory.py       # Strategy configurations
```