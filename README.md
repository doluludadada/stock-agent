
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