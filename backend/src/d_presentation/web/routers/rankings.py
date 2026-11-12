from datetime import date
from typing import Any

from fastapi import APIRouter, status

from a_domain.rules.trading.ranking import Ranking
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from d_presentation.web.schemas import ErrorResponse
from d_presentation.web.session import PrivateAccess, UserPipeline

router = APIRouter(prefix="/rankings", tags=["Rankings"], dependencies=[PrivateAccess])

UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": (
            "ranking_unavailable: the site's daily history holds no decision session yet; `detail` says what it holds. "
            "backtest_period_unavailable: the period holds no decision session the history holds; `detail` says which "
            "sessions it holds. invalid_request: a query parameter does not validate."
        ),
    }
}


@router.get("/latest", responses=UNAVAILABLE)
async def get_latest_ranking(pipeline: UserPipeline) -> Ranking:
    """
    The monthly stock ranking by revenue acceleration and nearness to the 250-session high at the latest decision session
    the site's daily history holds: the stocks to hold from the next session's open, best first, each with its two
    factors, their ranks and its score, and the revenue month it read. It reads only the held history and the archived
    monthly revenue; a month without revenue ranks nothing and says so in `scored`. The first answer after a start reads
    every held bar, which takes seconds; later ones reuse it until the history holds another session.
    """
    return await pipeline.load_ranking()


@router.get("/backtest", responses=UNAVAILABLE)
async def get_ranking_backtest(first: date, last: date, pipeline: UserPipeline) -> RankingBacktest:
    """
    The monthly ranking replayed over the decision sessions from `first` to `last`: bought at each next open in equal
    weights, at the site's fee and tax, against ranking.benchmark_id held over the same sessions by its total return.
    It answers the value of both at every session, their total, annual and yearly returns and drawdowns, the costs, and
    each decision's ranking and the stocks it held. It saves nothing, asks no AI and never orders.
    """
    return await pipeline.run_ranking_backtest(first, last)
