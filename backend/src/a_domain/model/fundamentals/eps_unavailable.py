from __future__ import annotations

from dataclasses import dataclass

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.types.enums import EpsUnavailableReason


@dataclass(frozen=True)
class EpsUnavailable:
    """Missing EPS. It is never 0, and the report shows 資料不足 with the reason."""

    reason: EpsUnavailableReason
    quarter: FiscalQuarter | None = None

    def describe(self) -> str:
        match self.reason:
            case EpsUnavailableReason.NOT_LOADED:
                return "資料不足：未載入財報資料"
            case EpsUnavailableReason.NOT_REPORTED:
                return f"資料不足：自 {self.quarter} 起無此代號的財報（ETF、DR、新上市或未申報）"
            case EpsUnavailableReason.INCOMPLETE_HISTORY:
                return f"資料不足：缺少 {self.quarter} 累計 EPS，無法計算近四季 EPS"
            case EpsUnavailableReason.SOURCE_FAILED:
                return f"資料不足：{self.quarter} 財報資料取得失敗"
