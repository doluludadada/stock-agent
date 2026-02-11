from typing import Final

FINANCIAL_KEYWORDS_TW: Final[frozenset[str]] = frozenset(
    {
        "EPS",
        "YOY",
        "MOM",
        "毛利",
        "營收",
        "基本面",
        "技術面",
        "籌碼",
        "展望",
        "估值",
        "目標價",
    }
)

REASON_NIGHTLY_SCREEN: Final[str] = "Nightly Technical Scan"
REASON_SOCIAL_BUZZ: Final[str] = "Social Media Buzz"
REASON_MANUAL_REQ: Final[str] = "User Manual Request"
REASON_STOP_LOSS: Final[str] = "Stop Loss Triggered"
