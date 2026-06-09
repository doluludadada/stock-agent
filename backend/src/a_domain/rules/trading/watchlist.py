from dataclasses import dataclass

from a_domain.model.market.stock import Stock


# TODO: Use icontract
@dataclass(frozen=True)
class WatchlistRule:
    minimum_combined_score: int

    def accepts(self, stock: Stock) -> bool:
        if stock.is_eliminated:
            return False

        if stock.technical_score is None:
            return False

        if stock.ai_score is None:
            return False

        if stock.combined_score is None:
            return False

        return stock.combined_score >= self.minimum_combined_score
