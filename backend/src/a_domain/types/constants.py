from typing import Final

# TODO: Move to enums. 
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
